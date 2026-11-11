# Kindle Daily v0.1

Daily RSS-to-EPUB prototype for KOReader. Feeds: NASA and 3D Printing Industry; original-language content; up to 10 articles total.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

Or with Docker:

```bash
docker compose run --rm kindle-daily
```

Output: `output/kindle-daily-YYYY-MM-DD.epub` and `output/catalog.xml`.

## GitHub Pages

1. Push this project to a GitHub repository.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Actions → Kindle Daily → Run workflow. Scheduled runs are configured for 10:00 UTC (07:00 Argentina); GitHub scheduling may be delayed.
4. In KOReader, add a custom OPDS catalog URL: `https://YOUR-USER.github.io/YOUR-REPO/catalog.xml` (actual Pages URL depends on repository settings).

The Pages workflow publishes the latest edition only; history is a future enhancement. Do not put passwords or paywalled text into a public repository or public Pages site. The first prototype has no authentication and must only publish content you have rights to redistribute. For private subscription content, use a private distribution mechanism instead.

## Raspberry Pi migration

Install Docker on a 64-bit Raspberry Pi OS, clone repository, and run `docker compose run --rm kindle-daily`. Schedule that command with systemd timer or cron; serve the `output` directory with an HTTP server accessible to KOReader. Keep the same Python code and feeds file.

## Known limitations

No AI ranking, Sheets, images, paywall login, full archive, or automatic Kindle download yet. Full text depends on each publisher's site and extraction quality. EPUB may contain an original-article link instead of full text. Test OPDS compatibility on the actual KOReader device. GitHub Actions is scheduled execution, not an always-on server.
