# Operations Runbook

Load this reference for local startup, server deployment, scheduled jobs, environment variables, or debugging.

## Environment Variables

Project root `.env` may contain:

```env
POLYGON_API_KEY_1=...
POLYGON_API_KEY_2=...
POLYGON_API_KEY_3=...
POLYGON_API_KEY_4=...
POLYGON_API_KEY_5=...
POLYGON_API_KEY_6=...
POLYGON_API_KEY_7=...
POLYGON_API_KEY=...          # legacy fallback

TUSHARE_TOKEN=...
ALPHA_VANTAGE_API_KEY=...
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat
TAVILY_API_KEY=...
DASHSCOPE_API_KEY=...       # optional qwen fallback
BAILIAN_API_KEY=...          # optional qwen fallback

SMTP_HOST=...
SMTP_PORT=...
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=...
SMTP_TO=a@example.com,b@example.com
SMTP_USE_TLS=true
DAILY_BRIEF_PUBLIC_BASE_URL=https://your-domain.example/daily-briefs/files
```

Never commit `.env`.

## Local Setup

From project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm install
```

If dependencies already exist, do not reinstall unless imports/build fail.

## Local Backend

Preferred command from project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --app-dir backend
```

Alternative from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Most prior local runs used hidden background processes. To find the backend:

```powershell
netstat -ano | Select-String ':8001'
Get-Process python -ErrorAction SilentlyContinue
```

To restart only the backend on Windows:

```powershell
Stop-Process -Id <PID_FROM_NETSTAT> -Force
Start-Process -FilePath "E:\stock_ranking\us_stock_data_project\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8001" -WorkingDirectory "E:\stock_ranking\us_stock_data_project\backend" -WindowStyle Hidden
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

## Local Frontend

```powershell
cd E:\stock_ranking\us_stock_data_project\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173/
```

Vite proxy in `frontend/vite.config.ts` sends `/api` to `http://127.0.0.1:8001`. If frontend shows HTTP 502 or proxy errors, backend is not listening on 8001.

Build check:

```powershell
cd E:\stock_ranking\us_stock_data_project\frontend
npm run build
```

If Vite fails with `spawn EPERM` in the Codex sandbox, rerun with tool escalation.

## Main API Checks

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/api/health"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=QQQ&apply_announced_rebalance=true"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/alerts?window=10&benchmark=QQQ"
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/MU/peers"
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/QQQ/daily?limit=120"
```

PowerShell may display Chinese JSON as mojibake. Browser output is UTF-8 and should be fine.

## Daily Data Update

Ranking pool only, local:

```powershell
$tickers = ((Get-Content config\nasdaq100_tickers.txt | Where-Object { $_ -and -not $_.Trim().StartsWith("#") }) + "QQQ") -join ","
.\.venv\Scripts\python.exe -B scripts\update_latest_daily.py --tickers $tickers --download-missing --max-retries 2
.\.venv\Scripts\python.exe -B scripts\update_optionable_tickers.py --max-retries 2
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --windows 10,20 --days 20
```

Full server script:

```bash
cd /root/stock_ranking
bash scripts/server_daily_update.sh
```

`server_daily_update.sh` does:

1. update Nasdaq-100 + QQQ daily bars
2. update option availability
3. update A-share universe
4. rebuild curated US/A-share peer cache
5. rebuild ranking cache
6. restart `stock-ranking-api`
7. health check `/api/health`

## A-Share Peer Mapping Update

If user provides a new CSV mapping:

1. Copy it to `config/us_a_share_peer_mapping.csv`.
2. Refresh A-share universe when network permits:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_a_share_universe.py --source hybrid --spot-source akshare --retries 2 --retry-wait-seconds 10
```

3. Rebuild peer cache:

```powershell
.\.venv\Scripts\python.exe -B scripts\build_a_share_peer_cache.py
```

4. Restart backend.
5. Verify:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/MU/peers"
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/PANW/peers"
```

Current expected examples:

- `MU`: `source=csv_mapping`, fine type `存储芯片/存储设备`, peers `兆易创新`, `江波龙`, `北京君正`.
- `PANW`: `source=csv_mapping`, fine type `网络安全`, peers from `config/us_a_share_peer_mapping.csv`, sorted by refreshed market cap.

## Ranking Cache

Build recent 20 trading days:

```powershell
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --windows 10,20 --days 20
```

Specific end date:

```powershell
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --windows 10,20 --days 20 --end-date 2026-06-30
```

Delete/rebuild cache only if explicitly requested. Cache files live in:

```text
data/processed/rankings/ranking_window_10.csv
data/processed/rankings/ranking_window_20.csv
```

## Daily Brief HTML Email

Generate one window without LLM:

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_html.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

Generate with DeepSeek:

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10 --use-llm --llm-timeout 180 --llm-max-tokens 1500
```

Send latest HTML report links to configured recipients:

```powershell
.\.venv\Scripts\python.exe -B scripts\send_daily_brief_email.py --markets us --window 10
.\.venv\Scripts\python.exe -B scripts\send_daily_brief_email.py --markets cn,hk --window 10
```

Server all-in-one:

```bash
cd /root/stock_ranking
MARKET_GROUP=us bash scripts/run_daily_brief_email.sh
MARKET_GROUP=asia bash scripts/run_daily_brief_email.sh
```

Multiple recipients are comma-separated in `SMTP_TO`, or passed by CLI if supported.

## Sector Cloud

```powershell
.\.venv\Scripts\python.exe -B experiments\sector_cloud\generate_sector_cloud.py --window 10
.\.venv\Scripts\python.exe -B experiments\sector_cloud\generate_sector_cloud.py --window 20
```

Open:

```text
experiments/sector_cloud/output/index_w10.html
experiments/sector_cloud/output/index_w20.html
```

## Server Deployment

Known server setup:

- Backend service: `stock-ranking-api.service`
- Backend bind: `127.0.0.1:8001`
- Frontend static root: `/var/www/stock_ranking/dist`
- Nginx listen port for this site: `8081`
- Existing other site may use port 80 / backend 8000.

Backend service commands:

```bash
systemctl status stock-ranking-api --no-pager
systemctl restart stock-ranking-api
journalctl -u stock-ranking-api -n 80 --no-pager
curl -fsS http://127.0.0.1:8001/api/health
```

Build and deploy frontend on server:

```bash
cd /root/stock_ranking/frontend
npm install
npm run build
mkdir -p /var/www/stock_ranking
rsync -a --delete dist/ /var/www/stock_ranking/dist/
nginx -t
systemctl reload nginx
```

If nginx returns 500 with `Permission denied` on `/root/stock_ranking/frontend/dist/index.html`, do not serve static files directly from `/root`; copy `dist` to `/var/www/stock_ranking/dist`.

Example nginx site concept:

```nginx
server {
    listen 8081;
    server_name _;
    root /var/www/stock_ranking/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

## Cron / Timers

Beijing 09:00 daily data update:

```cron
0 9 * * 1-5 cd /root/stock_ranking && bash scripts/server_daily_update.sh >> logs/cron_daily_update.log 2>&1
```

Beijing 08:00 US daily brief email and 17:00 A/HK daily brief email:

```cron
0 8 * * 1-5 cd /root/stock_ranking && MARKET_GROUP=us bash scripts/run_daily_brief_email.sh >> logs/cron_daily_brief_email_us.log 2>&1
0 17 * * 1-5 cd /root/stock_ranking && MARKET_GROUP=asia bash scripts/run_daily_brief_email.sh >> logs/cron_daily_brief_email_asia.log 2>&1
```

Ensure server timezone is Asia/Shanghai:

```bash
timedatectl
```

## Common Debugging

Frontend says HTTP 502:

1. `curl http://127.0.0.1:8001/api/health`
2. Check Vite proxy or nginx `/api` proxy.
3. Restart backend.

Homepage stuck at loading:

1. Check `/api/rankings/latest?...`.
2. If ranking cache missing, run `scripts/build_ranking_cache.py`.
3. If daily data missing, run `scripts/update_latest_daily.py`.

Detail page A-share peers are old:

1. Inspect `config/stock_subtypes.csv` and `data/fundamental/a_share_subtype_leaders.csv`.
2. Call `/api/stocks/{ticker}/peers`.
3. Restart backend to clear `lru_cache`.

PDF font error on server:

- ReportLab may reject some `.ttc` CJK fonts with PostScript outlines. Use a TrueType CJK font path or the renderer fallback logic.

Git lock:

```powershell
Get-Process git -ErrorAction SilentlyContinue
Get-Item .git\index.lock
Remove-Item .git\index.lock -Force
```

Only remove lock when no git process is active.

## Commit Hygiene

The repo often has uncommitted data changes. Before committing:

```powershell
git status --short
git add <only requested files>
git diff --cached --name-only
git commit -m "Message"
git push origin main
```

Avoid accidentally staging:

- `data/raw/daily/*.csv` unless user asks to push data
- `logs/`
- `experiments/*/output/`
- `.env`
- unrelated `frontend/vite.config.ts` or script tuning changes
