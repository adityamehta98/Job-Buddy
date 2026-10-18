"""Notification sender for Job Buddy.

Supports multiple channels, selected via config.NOTIFY_CHANNELS:
  - telegram  (MarkdownV2 formatted, via Bot API)
  - whatsapp  (plain text, via the free Green API Developer plan)
  - ntfy      (plain text push, no account)
  - discord   (plain text via a channel webhook)

Each public send_* function builds one message and fans it out to every
enabled channel. Telegram receives a richly formatted version; WhatsApp (and
any future plain channel) receives a clean plain-text version.
"""

import html
from urllib.parse import urlsplit, urlunsplit

import httpx

import config

TELEGRAM_API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def _telegram_enabled() -> bool:
    return "telegram" in config.NOTIFY_CHANNELS


def _whatsapp_enabled() -> bool:
    return "whatsapp" in config.NOTIFY_CHANNELS


def _ntfy_enabled() -> bool:
    return "ntfy" in config.NOTIFY_CHANNELS


def _discord_enabled() -> bool:
    return "discord" in config.NOTIFY_CHANNELS


# --------------------------------------------------------------------------- #
# Message builders -> (markdown_for_telegram, plain_for_whatsapp)
# --------------------------------------------------------------------------- #

def _build_job_alert(company_name: str, job: dict) -> tuple[str, str]:
    title = job.get("title", "Unknown Position")
    team = job.get("team", "")
    location = job.get("location", "Location not specified")
    posted = job.get("posted", "")
    role_number = job.get("job_id") or job.get("role_number") or job.get("key", "")
    weekly_hours = job.get("weekly_hours", "")
    url = job.get("url", "")
    match = job.get("match")  # optional CV match % (set by the scraper)
    matched_count = job.get("matched_count")
    skill_count = job.get("jd_skill_count")
    missing = job.get("missing") or []
    match_note = job.get("match_note", "")  # shown when match could not be computed

    # ---- Telegram (MarkdownV2) ----
    esc_company = _escape_md(company_name)
    md = [
        f"🔔 *New {esc_company} Job Opening*",
        "",
        f"📌 *{_escape_md(title)}*",
        f"📍 {_escape_md(location)}",
    ]
    if team:
        md.insert(3, f"🏢 {_escape_md(team)}")
    if match is not None:
        denominator = f" ({matched_count}/{skill_count} keywords)" if skill_count else ""
        md.append(f"🎯 CV keyword coverage: *{_escape_md(str(match))}%*{_escape_md(denominator)}")
        if missing:
            md.append(f"🧩 Missing: {_escape_md(', '.join(missing[:6]))}")
    elif match_note:
        md.append(f"ℹ️ {_escape_md(match_note)}")
    if posted:
        md.append(f"🗓 {_escape_md(posted)}")
    if role_number:
        md.append(f"🆔 `{_escape_md(role_number)}`")
    if weekly_hours:
        md.append(f"⏱ {_escape_md(weekly_hours)}")
    if url:
        md.extend(["", f"[Open on {esc_company} Careers]({url})"])

    # ---- Plain (WhatsApp et al.) ----
    plain = [f"🔔 New {company_name} Job Opening", "", f"📌 {title}", f"📍 {location}"]
    if team:
        plain.insert(3, f"🏢 {team}")
    if match is not None:
        denominator = f" ({matched_count}/{skill_count} keywords)" if skill_count else ""
        plain.append(f"🎯 CV keyword coverage: {match}%{denominator}")
        if missing:
            plain.append(f"🧩 Missing: {', '.join(missing[:6])}")
    elif match_note:
        plain.append(f"ℹ️ {match_note}")
    if posted:
        plain.append(f"🗓 {posted}")
    if role_number:
        plain.append(f"🆔 {role_number}")
    if weekly_hours:
        plain.append(f"⏱ {weekly_hours}")
    if url:
        plain.extend(["", url])

    return "\n".join(md), "\n".join(plain)


async def send_job_alert_for_company(company_name: str, job: dict) -> bool:
    markdown, plain = _build_job_alert(company_name, job)
    return await _dispatch(markdown, plain)


def _compact_url(value: str) -> str:
    """Drop tracking/query data while preserving a direct job URL."""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return text
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _short_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _job_block(job: dict) -> tuple[str, str]:
    """Full detail block for one job: (telegram HTML, plain text)."""
    title = _short_text(job.get("title") or "Untitled role", 90)
    team = _short_text(job.get("team") or "", 60)
    location = _short_text(job.get("location") or "", 60)
    posted = str(job.get("posted") or "")
    role_number = job.get("job_id") or job.get("role_number") or job.get("key", "")
    url = _compact_url(job.get("url", ""))
    match = job.get("match")
    skill_count = job.get("jd_skill_count")
    matched_list = job.get("matched")
    matched_count = len(matched_list) if isinstance(matched_list, list) else job.get("matched_count")
    missing = job.get("missing") or []
    match_note = job.get("match_note", "")

    tg = [f"📌 <b>{html.escape(title)}</b>"]
    pl = [f"📌 {title}"]
    if team:
        tg.append(f"🏢 {html.escape(team)}")
        pl.append(f"🏢 {team}")
    if location:
        tg.append(f"📍 {html.escape(location)}")
        pl.append(f"📍 {location}")
    if match is not None:
        denom = f" ({matched_count}/{skill_count} keywords)" if skill_count else ""
        tg.append(f"🎯 CV match: <b>{match}%</b>{html.escape(denom)}")
        pl.append(f"🎯 CV match: {match}%{denom}")
        if missing:
            tg.append(f"🧩 Missing: {html.escape(', '.join(missing[:6]))}")
            pl.append(f"🧩 Missing: {', '.join(missing[:6])}")
    elif match_note:
        tg.append(f"ℹ️ {html.escape(match_note)}")
        pl.append(f"ℹ️ {match_note}")
    if posted:
        tg.append(f"🗓 {html.escape(posted)}")
        pl.append(f"🗓 {posted}")
    if role_number:
        tg.append(f"🆔 <code>{html.escape(str(role_number))}</code>")
        pl.append(f"🆔 {role_number}")
    if url:
        tg.append(f'🔗 <a href="{html.escape(url, quote=True)}">Open posting</a>')
        pl.append(f"🔗 {url}")

    return "\n".join(tg), "\n".join(pl)


# Keep each message safely under Telegram's 4096-char limit.
_DIGEST_CHAR_BUDGET = 3500


def _chunk_blocks(blocks: list[tuple[str, str]], budget: int) -> list[list[tuple[str, str]]]:
    chunks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_len = 0
    for block in blocks:
        block_len = max(len(block[0]), len(block[1])) + 2
        if current and current_len + block_len > budget:
            chunks.append(current)
            current, current_len = [], 0
        current.append(block)
        current_len += block_len
    if current:
        chunks.append(current)
    return chunks


async def send_company_digest(company_name: str, jobs: list[dict]) -> bool:
    """Send one notification per company that lists every new job in full.

    Splits into a few messages only if a batch is too large for one message.
    """
    if not jobs:
        return True

    blocks = [_job_block(job) for job in jobs]
    chunks = _chunk_blocks(blocks, _DIGEST_CHAR_BUDGET)
    total = len(chunks)
    count = len(jobs)
    noun = "role" if count == 1 else "roles"

    all_ok = True
    for index, chunk in enumerate(chunks, 1):
        part = f" (part {index}/{total})" if total > 1 else ""
        heading = f"🔔 {count} new {company_name} {noun} in the last 24h{part}"
        telegram = f"<b>{html.escape(heading)}</b>\n\n" + "\n\n".join(b[0] for b in chunk)
        plain = heading + "\n\n" + "\n\n".join(b[1] for b in chunk)
        ok = await _dispatch(telegram, plain, telegram_parse_mode="HTML")
        all_ok = all_ok and ok
    return all_ok


async def send_summary(company_name: str, new_count: int, total_scraped: int) -> bool:
    markdown = (
        f"📊 *{_escape_md(company_name)} Jobs Scan Complete*\n\n"
        f"• New jobs found: *{new_count}*\n"
        f"• Total jobs scanned: *{total_scraped}*"
    )
    plain = (
        f"📊 {company_name} Jobs Scan Complete\n\n"
        f"• New jobs found: {new_count}\n"
        f"• Total jobs scanned: {total_scraped}"
    )
    return await _dispatch(markdown, plain)


async def send_error(company_name: str, error_msg: str) -> bool:
    markdown = f"⚠️ *{_escape_md(company_name)} Jobs Scraper Error*\n\n`{_escape_md(error_msg)}`"
    plain = f"⚠️ {company_name} Jobs Scraper Error\n\n{error_msg}"
    return await _dispatch(markdown, plain)


async def send_plain(text: str) -> bool:
    return await _dispatch(text, text, telegram_parse_mode="")


# --------------------------------------------------------------------------- #
# Dispatch across enabled channels
# --------------------------------------------------------------------------- #

async def _dispatch(markdown: str, plain: str, telegram_parse_mode: str = "MarkdownV2") -> bool:
    results = []
    if _telegram_enabled():
        results.append(await _send_telegram(markdown, plain, parse_mode=telegram_parse_mode))
    if _whatsapp_enabled():
        results.append(await _send_whatsapp(plain))
    if _ntfy_enabled():
        results.append(await _send_ntfy(plain))
    if _discord_enabled():
        results.append(await _send_discord(plain))
    # True if at least one enabled channel delivered the message.
    return any(results) if results else False


async def verify_channels() -> bool:
    """Verify at least one enabled channel is configured and reachable."""
    ok = False
    if _telegram_enabled():
        if await _verify_telegram():
            ok = True
        else:
            print("[notifier] Telegram not verified (check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
    if _whatsapp_enabled():
        if config.GREENAPI_ID_INSTANCE and config.GREENAPI_API_TOKEN and config.GREENAPI_CHAT_ID:
            ok = True
        else:
            print("[notifier] WhatsApp enabled but GREENAPI_ID_INSTANCE / GREENAPI_API_TOKEN / GREENAPI_CHAT_ID not set.")
    if _ntfy_enabled():
        if config.NTFY_TOPIC:
            ok = True
        else:
            print("[notifier] ntfy enabled but NTFY_TOPIC not set.")
    if _discord_enabled():
        if config.DISCORD_WEBHOOK_URL:
            ok = True
        else:
            print("[notifier] Discord enabled but DISCORD_WEBHOOK_URL not set.")
    return ok


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #

async def _verify_telegram() -> bool:
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{TELEGRAM_API}/getMe")
            return resp.status_code == 200 and resp.json().get("ok", False)
    except httpx.HTTPError:
        return False


async def _send_telegram(text: str, plain_fallback: str, parse_mode: str = "MarkdownV2") -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[notifier] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set - skipping Telegram.")
        return False

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            print(f"[notifier] Telegram API error: {resp.status_code} - {resp.text}")
            if parse_mode and resp.status_code == 400:
                payload["parse_mode"] = ""
                payload["text"] = plain_fallback
                resp2 = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
                return resp2.status_code == 200
            return False
    except httpx.HTTPError as exc:
        print(f"[notifier] HTTP error sending Telegram message: {exc}")
        return False


# --------------------------------------------------------------------------- #
# WhatsApp (Green API)
# --------------------------------------------------------------------------- #

async def _send_whatsapp(text: str) -> bool:
    if not (config.GREENAPI_ID_INSTANCE and config.GREENAPI_API_TOKEN and config.GREENAPI_CHAT_ID):
        print("[notifier] Green API not configured - skipping WhatsApp.")
        return False
    base = config.GREENAPI_API_URL.rstrip("/")
    url = f"{base}/waInstance{config.GREENAPI_ID_INSTANCE}/sendMessage/{config.GREENAPI_API_TOKEN}"
    payload = {"chatId": config.GREENAPI_CHAT_ID, "message": text}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code in (200, 201):
                return True
            print(f"[notifier] Green API WhatsApp error: {resp.status_code} - {resp.text[:200]}")
            return False
    except httpx.HTTPError as exc:
        print(f"[notifier] HTTP error sending WhatsApp message: {exc}")
        return False


# --------------------------------------------------------------------------- #
# ntfy (free push, no account)
# --------------------------------------------------------------------------- #

async def _send_ntfy(text: str) -> bool:
    if not config.NTFY_TOPIC:
        print("[notifier] NTFY_TOPIC not set - skipping ntfy.")
        return False
    url = f"{config.NTFY_SERVER.rstrip('/')}/{config.NTFY_TOPIC}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                content=text.encode("utf-8"),
                headers={"Title": "Job Buddy", "Tags": "briefcase"},
            )
            if resp.status_code == 200:
                return True
            print(f"[notifier] ntfy error: {resp.status_code} - {resp.text[:200]}")
            return False
    except httpx.HTTPError as exc:
        print(f"[notifier] HTTP error sending ntfy message: {exc}")
        return False


# --------------------------------------------------------------------------- #
# Discord webhook
# --------------------------------------------------------------------------- #

async def _send_discord(text: str) -> bool:
    if not config.DISCORD_WEBHOOK_URL:
        print("[notifier] DISCORD_WEBHOOK_URL not set - skipping Discord.")
        return False
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(config.DISCORD_WEBHOOK_URL, json={"content": text[:1900]})
            if resp.status_code in (200, 204):
                return True
            print(f"[notifier] Discord error: {resp.status_code} - {resp.text[:200]}")
            return False
    except httpx.HTTPError as exc:
        print(f"[notifier] HTTP error sending Discord message: {exc}")
        return False


# --------------------------------------------------------------------------- #

def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for ch in str(text):
        if ch in special:
            escaped += f"\\{ch}"
        else:
            escaped += ch
    return escaped