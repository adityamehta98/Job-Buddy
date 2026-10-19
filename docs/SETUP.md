# Job Buddy: setup and run guide

## 0. Prerequisites
- Python 3.11 or newer (3.12 recommended, matches GitHub Actions)
- Git

## 1. Install
```bash
cd Job-Buddy
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium        # only needed for the scraper, not the UI
```

## 2. Create your .env
```bash
copy .env.example .env        # Windows   (macOS/Linux: cp .env.example .env)
```
Then open `.env` and fill in the values below.

### 2a. Telegram token + chat id
1. In Telegram, search for **@BotFather**, start it, send `/newbot`, follow the prompts.
2. BotFather replies with a **bot token** like `8123456789:AAH...`. Put it in `TELEGRAM_BOT_TOKEN`.
3. Search for and open your new bot, press Start, and send it any message ("hi").
4. In a browser go to: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   (paste your token in place of `<YOUR_TOKEN>`). Look for `"chat":{"id":123456789` in the
   response. That number is your **chat id**. Put it in `TELEGRAM_CHAT_ID`.

### 2b. WhatsApp (optional, free via Green API)
Only needed if you set `NOTIFY_CHANNELS=whatsapp` (or add it to the list).
1. Sign up at https://green-api.com and create an **Instance** on the free Developer plan.
2. Open the instance, scan the QR code with WhatsApp (Settings, Linked devices) to link your phone.
3. From the console copy **idInstance**, **apiTokenInstance**, and **ApiUrl** into your `.env`
   as `GREENAPI_ID_INSTANCE`, `GREENAPI_API_TOKEN`, and `GREENAPI_API_URL`.
4. Set `GREENAPI_CHAT_ID` to your own number with country code (e.g. `14155551234`).
   The free plan allows messaging up to 3 chats, which is plenty for alerting yourself.

Even simpler, no-account options are also supported: set `NOTIFY_CHANNELS=ntfy` and a
`NTFY_TOPIC` (install the ntfy phone app, subscribe to that topic), or `NOTIFY_CHANNELS=discord`
with a `DISCORD_WEBHOOK_URL`.

## 3. Seed state (do this once, so the first run does not alert on every existing job)
```bash
python full_scrape.py --company all
```

## 4. Run the scraper locally (sends alerts for new jobs)
```bash
python scraper.py --company all
# or a subset:
python scraper.py --company anthropic,chime,apple
```

## 5. Run the local UI
```bash
python app.py
```
Open http://127.0.0.1:5000 in your browser. Tabs:
- **Jobs**: every role with posted date, CV keyword coverage, and missing skills. Click
  **View details** for the complete JD and per-keyword JD/resume evidence. Click **Applied**
  to hide a job for good. Full-description roles are scored; title-only roles are explicitly
  left unscored.
- **Resumes**: upload one or more CVs (PDF/DOCX/TXT). The newest becomes the active one used
  for scoring; switch with the radio button, or delete old ones.
- **Applied**: everything you marked applied, with an Unmark button.
- **Companies**: add a company by Name + careers URL (auto-detects Greenhouse, Lever, Ashby,
  SmartRecruiters). This writes `custom_companies.json` for you, so the scraper picks it up too.

The UI is local only. It is not meant to be exposed on a public network.

## 6. Run it hands-off on GitHub Actions
1. Push this repo to your own GitHub.
2. Repo Settings -> Secrets and variables -> Actions:
   - Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (and for WhatsApp: `GREENAPI_ID_INSTANCE`, `GREENAPI_API_TOKEN`, `GREENAPI_CHAT_ID`; or `NTFY_TOPIC` / `DISCORD_WEBHOOK_URL`).
   - Variables (optional): `NOTIFY_CHANNELS` (e.g. `telegram,whatsapp`), `INCLUDE_KEYWORDS`,
     `MAX_PAGES_CAP`, `MAX_AGE_HOURS`, `MATCH_THRESHOLD`.
   - Secret (optional): `CV_TEXT`, containing extracted resume text for scheduled matching.
     Do not commit the original resume to the repository.
3. The `Job Buddy` workflow runs every 10 minutes (cron) and on manual trigger.
   Enable Actions if prompted. State is committed back to the repo automatically.

US plus remote filtering is enabled by default. Explicit US signals such as `United States`,
`USA`, `Remote - US`, a full US state name, or `San Francisco, CA` are accepted. Country-
ambiguous values such as `Remote` and `Remote-Friendly` are also accepted. Explicitly foreign
remote roles such as `Remote - UK`, `Remote, Canada`, and `Remote - EMEA` are rejected.

## Relevance filter
By default only titles matching cloud / AI / ML / data / analytics / SWE keywords are alerted on.
Edit `DEFAULT_INCLUDE_KEYWORDS` in `config.py`, or set the `INCLUDE_KEYWORDS` env var / repo
variable. Set `INCLUDE_KEYWORDS=all` to turn the filter off and receive every role.

## Alert limits (pages, recency, CV match)
Set these in `.env` (or as repo variables for GitHub Actions):
- `MAX_PAGES_CAP` (default 5): scrape at most this many pages per company. Set 0 to disable.
- `MAX_AGE_HOURS` (default 24): only alert on jobs posted within this window, where a real post
  date is known. Jobs with no detectable date are kept. Set 0 to disable.
- `MATCH_THRESHOLD` (default 75): only alert when the job scores at least this percent against
  your CV. Set 0 to disable. Needs an active resume (uploaded in the UI) or `CV_PATH` set to a
  resume file. On GitHub Actions there is no uploaded resume, so set `CV_PATH` to a committed
  resume file if you want match filtering there.

Note on CV match: the score is reliable for companies where the full job description is available
(the custom companies you add, which are Greenhouse/Lever/Ashby). Built-in giants like Apple and
Amazon only expose the title, so their match is title-only and will rarely clear 75%. If you want
those filtered by match too, we can add full description fetching for them.

## Marking a job applied from the command line (alternative to the UI)
```bash
python applied.py --company chime --id gh-4461450008
python applied.py --company chime --list
```
