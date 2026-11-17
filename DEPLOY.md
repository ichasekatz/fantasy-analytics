# Deploying to Streamlit Community Cloud (free, always on)

## One-time setup

### 1. Create a GitHub repo

Go to github.com → New repository → set it **Private** → Create.

### 2. Push this project

```bash
cd ~/Desktop/Random/Fantasy/fantasy_analytics
git add .
git commit -m "Initial fantasy analytics project"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

### 3. Deploy on Streamlit Cloud

1. Go to **share.streamlit.io** and sign in with your GitHub account
2. Click **New app**
3. Select your repo and branch (`main`)
4. Set **Main file path** to: `dashboard/app.py`
5. Click **Deploy**

Your app will be live at `https://YOUR_USERNAME-YOUR_REPO_NAME-....streamlit.app` in ~2 minutes.

## Adding new league data later

1. Drop the new export JSON into `data/raw/`
2. Register it in `config/leagues.json`
3. `git add . && git commit -m "Add 2021 season data" && git push`
4. Streamlit Cloud auto-redeploys within ~1 minute

## Running locally

```bash
./run.sh
# or
uv run streamlit run dashboard/app.py
```

## Notes

- The DuckDB file is **not** stored in git — it rebuilds from the JSON exports on every cold start (~5 seconds)
- Identity merges (`data/identity/manager_aliases.json`) **are** stored in git — commit after merging profiles
- Streamlit Cloud free tier: 1GB RAM, sleeps after 7 days inactivity (wakes in ~15 seconds on visit)
