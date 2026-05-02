# campsite-watcher

Checks ReserveAmerica every 2 hours for available campsites at Saranac Lake Islands, NY.
Results appear on a GitHub Pages web app you can bookmark on your iPhone home screen.

---

## One-time setup (~20 minutes)

### 1. Create the GitHub repository

1. Go to [github.com](https://github.com) and sign in
2. Click **+** → **New repository**
3. Name it `campsite-watcher`
4. Set it to **Public** (required for free GitHub Pages)
5. Click **Create repository**

### 2. Put this code in the repository

On your Mac, open Terminal and run:

```bash
cd ~/Desktop
git clone https://github.com/YOUR_USERNAME/campsite-watcher.git
```

Replace `YOUR_USERNAME` with your actual GitHub username.

Then copy all the files from this folder into the cloned directory, and push:

```bash
cd campsite-watcher
git add .
git commit -m "initial setup"
git push
```

### 3. Enable GitHub Pages

1. On GitHub, go to your repository → **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Set Branch to `main`, folder to `/docs`
4. Click **Save**
5. After a minute, your app will be live at:
   `https://YOUR_USERNAME.github.io/campsite-watcher/`

### 4. Verify the scraper runs correctly

Before relying on it, test that the API response is what we expect:

```bash
cd ~/Desktop/campsite-watcher
pip install -r requirements.txt
python watcher.py --debug
```

This will print the raw JSON response from ReserveAmerica. You should see a list of
sites with `availabilities` keys. If the structure looks different from what's described
in `watcher.py`, the `parse_availability()` function may need a small adjustment.

If `--debug` works, run it for real:

```bash
python watcher.py
```

Check `docs/results.json` — it should have finds (or an empty list if nothing is
available right now). Then push the updated results:

```bash
git add docs/results.json
git commit -m "test run"
git push
```

### 5. Add your iPhone home screen bookmark

1. Open Safari on your iPhone
2. Go to `https://YOUR_USERNAME.github.io/campsite-watcher/`
3. Tap the Share button → **Add to Home Screen**
4. Name it "Campsite" and tap **Add**

It will now appear on your home screen like an app.

---

## Daily usage

- Open the app from your home screen
- A **green banner** at the top means new finds since your last visit
- Tap **Book on ReserveAmerica** to go directly to the booking page
- If there's no banner, nothing new has come up since you last checked

The script runs automatically on GitHub's servers every 2 hours, 24/7.
You don't need your Mac on for it to run.

---

## Customizing your search

Edit `config.yml` and push the change — GitHub Actions picks it up automatically.

**Add a date range:**
```yaml
date_ranges:
  - label: "Labor Day weekend"
    start: "2025-08-30"
    end: "2025-09-04"
    active: true
```

**Change minimum nights:**
```yaml
search:
  min_consecutive_nights: 4
```

**Change site preferences:**
```yaml
sites:
  mode: "preferred_list"  # or "any" or "specific_only"
  preferred:
    - id: 14
      type: "lean-to"
```

After editing, push:
```bash
git add config.yml
git commit -m "update config"
git push
```

---

## Troubleshooting

**The app shows "Could not load results"**
- Check that GitHub Pages is enabled (Settings → Pages)
- Make sure the workflow has run at least once (Actions tab on GitHub)

**No finds are appearing but I know sites exist**
- Run `python watcher.py --debug` to inspect the raw API response
- The `parse_availability()` function in `watcher.py` may need adjustment
  if ReserveAmerica has changed their response format

**GitHub Actions isn't running**
- Go to your repo → Actions tab → check if workflows are enabled
- Click "Run workflow" to trigger a manual run and check the logs

**The site filter isn't working**
- Site numbers in `config.yml` must match the numbers on the ReserveAmerica site
- Run `--debug` and check the `siteNumber` field in the raw response

---

## Files

```
campsite-watcher/
├── config.yml                   ← your settings (edit this)
├── watcher.py                   ← the scraper
├── requirements.txt             ← Python dependencies
├── .github/
│   └── workflows/
│       └── check.yml            ← runs every 2 hours on GitHub
├── docs/
│   ├── index.html               ← the web app (iPhone home screen)
│   └── results.json             ← written by the scraper, read by the app
└── README.md                    ← this file
```
