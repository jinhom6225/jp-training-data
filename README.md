# jp-training-data

Data pipeline for the Android app 職業訓練アラート (`com.joe.jobtrainingalert`).
It collects 公共職業訓練 and 求職者支援訓練 courses from ハローワークインターネットサービス
(HWIS) twice a day and publishes one JSON file per prefecture on GitHub Pages:

```
https://jinhom6225.github.io/jp-training-data/meta.json
https://jinhom6225.github.io/jp-training-data/stats.json
https://jinhom6225.github.io/jp-training-data/pref/01.json … pref/47.json
```

The file format is the app's `data_schema.md` (schemaVersion 1). Source:
ハローワークインターネットサービス. This is not an official service.

## Layout

| Path | What |
|---|---|
| `scraper/hwis_client.py` | The only HTTP client for HWIS: one request at a time, ≥ 1.5 s after the previous response, 20 s timeout, one retry, stops on 403/429 |
| `scraper/parse_list.py`, `parse_detail.py` | Result pages and course detail pages → values, with structure checks |
| `scraper/collect.py` | Per-prefecture searches with paging, the 託児サービスあり search, detail fetching, offline cache |
| `scraper/classify.py` + `fields.yml` | Field classification (分類 string, then course-name keywords, else `other`) |
| `scraper/record.py` | Detail → course object (city, limits, selection dates) |
| `scraper/assemble.py` | Which details to fetch and the run's course list (D7 recheck, reuse) |
| `scraper/overrides.py` + `overrides.json` | Hand-made 東京 予告 entries (`python -m scraper.overrides --check`) |
| `scraper/validate.py`, `rules.py` + `rule_cases.json` | The app's validator, ported; `rule_cases.json` is a copy of the app's `tools/rule_cases.json` |
| `scraper/anomaly.py` | Blocks publishing when the total drops > 30 %, markers are missing, > 10 % of details fail, or a prefecture with ≥ 10 courses has 0 |
| `scraper/publish.py` | Writes `meta.json` (schema keys only), `stats.json` and `pref/NN.json`; loads the previous publish |
| `scraper/telegram.py` | Notices (only logged when the secrets are absent) |
| `scraper/run.py` | One run; `scraper/smoke.py` is the access check |
| `.github/workflows/collect.yml` | 06:30 and 18:30 JST, plus manual `auto / normal / full / dry / force-anomaly` |
| `.github/workflows/smoke.yml` | Manual access check from the Actions IP |

## Local use

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest --cov=scraper

# One prefecture, no previous publish, keep raw pages for offline rebuilds
.venv/bin/python -m scraper.run --mode full --prefs 13 --pages-url "" --out out --cache out/cache
# Rebuild from the cache after a fields.yml change (no HWIS requests)
.venv/bin/python -m scraper.run --mode full --pages-url "" --out out --cache out/cache --from-cache
```

Output: `out/site/` (what Pages serves) and `out/report.json` (run report).
Exit codes: 0 published, 2 anomaly (nothing written to `out/site`), 3 blocked by HWIS, 1 other error.

When the app's `tools/rule_cases.json` changes, copy it to `scraper/rule_cases.json`;
`tests/test_rule_cases_sync.py` fails until the copies match (set `APP_REPO` if the
app repo is not at `../jp_job_training_alert` or `../../jp_job_training_alert`).

## Secrets

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Pages source: GitHub Actions.
No FCM: the app does not use push (decided 2026-10-28).
