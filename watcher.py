#!/usr/bin/env python3
"""
campsite-watcher
Scrapes ReserveAmerica for Saranac Lake Islands availability
and writes results to docs/results.json for the GitHub Pages web app.

Usage:
  python watcher.py           # normal run
  python watcher.py --debug   # print raw API response and exit (useful for setup)
"""

import json
import logging
import sys
import yaml
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
RESULTS_PATH = Path("docs/results.json")
CONFIG_PATH = Path("config.yml")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_availability(base_url, contract_code, park_id, start_date, end_date):
    """
    Call the ReserveAmerica availability endpoint.

    ReserveAmerica date format: MM-DD-YYYY

    If you get unexpected results, run:
        python watcher.py --debug
    to print the raw API response so you can inspect its structure.
    """
    url = f"{base_url}/camping/campsite_availability.json"

    params = {
        "contractCode": contract_code,
        "parkId": park_id,
        "startDate": start_date.strftime("%m-%d-%Y"),
        "endDate": end_date.strftime("%m-%d-%Y"),
        "offset": 0,
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": (
            f"{base_url}/camping/campground_details.do"
            f"?contractCode={contract_code}&parkId={park_id}"
        ),
    }

    log.info(f"Fetching: {start_date} → {end_date}")
    resp = requests.get(url, params=params, headers=headers, timeout=30)

    if resp.status_code != 200:
        log.error(f"HTTP {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()

    return resp.json()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_availability(data, site_cfg):
    """
    Parse the API response into a list of site dicts with available dates.

    Expected response shape:
    {
      "availability": [
        {
          "siteID": 12345,
          "siteNumber": "14",
          "loop": "Lower Saranac",
          "siteType": "STANDARD NONELECTRIC",
          "availabilities": {
            "07-04-2025": "A",   <- A = available
            "07-05-2025": "R",   <- R = reserved
            ...
          }
        },
        ...
      ]
    }

    If this doesn't match what comes back, run --debug and adjust here.
    Availability status codes: A=available, R=reserved, W=walk-up, X=closed
    """
    raw_sites = data.get("availability", [])

    if not raw_sites:
        log.warning("No 'availability' key in response. Keys found: %s", list(data.keys()))
        return []

    results = []

    for site in raw_sites:
        site_number = str(site.get("siteNumber", site.get("site", ""))).strip()
        site_id = str(site.get("siteID", site.get("siteId", ""))).strip()
        site_type = site.get("siteType", site.get("type", ""))
        loop = site.get("loop", "")
        availabilities = site.get("availabilities", {})

        available_dates = [
            d for d, status in availabilities.items()
            if str(status).upper() in ("A", "AVAILABLE", "W", "WALK_IN", "WALK UP")
        ]

        if not available_dates:
            continue

        priority = _get_priority(site_number, site_cfg)

        if priority is None and site_cfg.get("mode") == "specific_only":
            continue

        results.append({
            "site_number": site_number,
            "site_id": site_id,
            "site_type": _clean_type(site_type),
            "loop": loop,
            "available_dates": sorted(available_dates, key=_parse_date),
            "priority": priority or "any",
        })

    return results


def _get_priority(site_number, site_cfg):
    preferred = [str(s["id"]) for s in site_cfg.get("preferred", [])]
    watch = [str(s["id"]) for s in site_cfg.get("watch", [])]
    if site_number in preferred:
        return "preferred"
    if site_number in watch:
        return "watch"
    return None


def _clean_type(raw):
    t = raw.upper()
    if "LEAN" in t:
        return "Lean-to"
    if "TENT" in t:
        return "Tent"
    if "CANOE" in t:
        return "Canoe-in"
    if "STANDARD" in t:
        return "Standard"
    return raw.title() if raw else "Site"


def _parse_date(s):
    """Parse MM-DD-YYYY to a date for sorting."""
    return datetime.strptime(s, "%m-%d-%Y").date()


# ---------------------------------------------------------------------------
# Consecutive run finder
# ---------------------------------------------------------------------------

def find_consecutive_runs(available_dates, min_nights):
    """
    Given available_dates (list of MM-DD-YYYY strings), return all runs of
    consecutive dates that are at least min_nights long.
    """
    if not available_dates:
        return []

    dates = sorted(available_dates, key=_parse_date)
    runs = []
    current = [dates[0]]

    for i in range(1, len(dates)):
        gap = (_parse_date(dates[i]) - _parse_date(dates[i - 1])).days
        if gap == 1:
            current.append(dates[i])
        else:
            if len(current) >= min_nights:
                runs.append(current[:])
            current = [dates[i]]

    if len(current) >= min_nights:
        runs.append(current)

    return runs


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def run_check(config):
    cg = config["campground"]
    search = config["search"]
    site_cfg = config["sites"]
    min_nights = search["min_consecutive_nights"]
    now = datetime.now(EASTERN)
    finds = []

    for range_cfg in search["date_ranges"]:
        if not range_cfg.get("active", True):
            log.info(f"Skipping paused range: {range_cfg.get('label', '')}")
            continue

        start = datetime.strptime(range_cfg["start"], "%Y-%m-%d").date()
        end = datetime.strptime(range_cfg["end"], "%Y-%m-%d").date()
        label = range_cfg.get("label", f"{range_cfg['start']} to {range_cfg['end']}")

        log.info(f"Range: {label}")

        try:
            data = fetch_availability(
                cg["base_url"], cg["contract_code"], cg["park_id"], start, end
            )
        except Exception as e:
            log.error(f"Failed to fetch {label}: {e}")
            continue

        sites = parse_availability(data, site_cfg)
        log.info(f"  {len(sites)} sites with availability")

        for site in sites:
            runs = find_consecutive_runs(site["available_dates"], min_nights)
            for run in runs:
                booking_url = (
                    f"{cg['base_url']}/camping/campsite_details.do"
                    f"?contractCode={cg['contract_code']}"
                    f"&parkId={cg['park_id']}"
                    f"&siteId={site['site_id']}"
                    f"&startDate={run[0]}"
                )
                find = {
                    "site_number": site["site_number"],
                    "site_id": site["site_id"],
                    "site_type": site["site_type"],
                    "loop": site["loop"],
                    "priority": site["priority"],
                    "range_label": label,
                    "start_date": run[0],
                    "end_date": run[-1],
                    "nights": len(run),
                    "available_dates": run,
                    "booking_url": booking_url,
                    "found_at": now.isoformat(),
                    "is_new": True,
                }
                finds.append(find)
                log.info(
                    f"  FIND  site={site['site_number']} ({site['site_type']}) "
                    f"{run[0]}–{run[-1]} [{len(run)} nights] [{site['priority']}]"
                )

    log.info(f"Total finds this run: {len(finds)}")
    return finds


# ---------------------------------------------------------------------------
# Results management
# ---------------------------------------------------------------------------

def load_existing():
    if RESULTS_PATH.exists():
        try:
            return json.loads(RESULTS_PATH.read_text())
        except Exception:
            pass
    return {"finds": []}


def merge_finds(new_finds, existing):
    """
    Merge new finds with existing ones.
    - Preserve original found_at for known finds (so they don't reset to 'new').
    - Mark genuinely new finds with is_new=True.
    """
    def key(f):
        return f"{f['site_number']}|{f['start_date']}|{f['range_label']}"

    existing_by_key = {key(f): f for f in existing.get("finds", [])}

    merged = []
    for f in new_finds:
        k = key(f)
        if k in existing_by_key:
            f["found_at"] = existing_by_key[k]["found_at"]
            f["is_new"] = False
        else:
            f["is_new"] = True
        merged.append(f)

    priority_order = {"preferred": 0, "watch": 1, "any": 2}
    merged.sort(
        key=lambda f: (priority_order.get(f["priority"], 2), -f["nights"], f["start_date"])
    )
    return merged


def write_results(finds, config):
    now = datetime.now(EASTERN)

    next_even_hour = now.replace(minute=0, second=0, microsecond=0)
    next_even_hour = next_even_hour.replace(hour=((now.hour // 2) * 2 + 2) % 24)
    if next_even_hour <= now:
        next_even_hour += timedelta(hours=2)

    new_count = sum(1 for f in finds if f.get("is_new", False))

    results = {
        "last_checked": now.isoformat(),
        "next_check": next_even_hour.isoformat(),
        "new_count": new_count,
        "finds": finds,
        "meta": {
            "campground_name": config["campground"]["name"],
            "min_nights": config["search"]["min_consecutive_nights"],
            "map_url": "https://extapps.dec.ny.gov/docs/permits_ej_operations_pdf/sarnaclakeisl23.pdf",
            "date_ranges": [
                {
                    "label": r.get("label", f"{r['start']} to {r['end']}"),
                    "start": r["start"],
                    "end": r["end"],
                    "active": r.get("active", True),
                }
                for r in config["search"]["date_ranges"]
            ],
            "preferred_sites": [str(s["id"]) for s in config["sites"].get("preferred", [])],
            "watch_sites": [str(s["id"]) for s in config["sites"].get("watch", [])],
        },
    }

    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    log.info(f"Wrote {len(finds)} finds ({new_count} new) → {RESULTS_PATH}")
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    debug = "--debug" in sys.argv
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=== campsite-watcher starting ===")
    config = load_config()

    if debug:
        cg = config["campground"]
        active_ranges = [r for r in config["search"]["date_ranges"] if r.get("active", True)]
        if active_ranges:
            r = active_ranges[0]
            start = datetime.strptime(r["start"], "%Y-%m-%d").date()
            end = datetime.strptime(r["end"], "%Y-%m-%d").date()
            data = fetch_availability(cg["base_url"], cg["contract_code"], cg["park_id"], start, end)
            print("\n=== RAW API RESPONSE (first 6000 chars) ===")
            print(json.dumps(data, indent=2)[:6000])
        else:
            log.warning("No active date ranges in config.yml")
        return

    existing = load_existing()
    new_finds = run_check(config)
    merged = merge_finds(new_finds, existing)
    write_results(merged, config)
    log.info("=== done ===")


if __name__ == "__main__":
    main()
