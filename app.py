#!/usr/bin/env python3
"""Local web UI for Job Buddy.

Run it locally:  python app.py   ->   open http://127.0.0.1:5000

Tabs:
  Jobs       list of scraped / live roles, posted date, CV match %, missing
             keywords, open link, and a one-click "Applied" button
  Resumes    upload CVs (multiple), pick the active one used for scoring, delete
  Applied    jobs you've marked applied (suppressed from the Jobs tab)
  Companies  add/remove companies by Name + URL (writes custom_companies.json)

This is a local tool only; it is not meant to be exposed on a public network.
"""

from __future__ import annotations

import os
import threading
import time

from flask import Flask, jsonify, render_template, request

import jobs_service
import resume_store
from companies import list_companies
from companies.generic_ats import slugify
from state import list_applied, mark_applied, unmark_applied

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload cap

_launcher_managed = os.getenv("JOB_BUDDY_LAUNCHER") == "1"
_launcher_lock = threading.Lock()
_launcher_shutdown_at: float | None = None


@app.get("/")
def index():
    return render_template("index.html", launcher_managed=_launcher_managed)


# ---- Launcher lifecycle --------------------------------------------------- #

@app.post("/api/launcher/heartbeat")
def api_launcher_heartbeat():
    """Cancel a pending shutdown when the managed Brave tab is alive."""
    global _launcher_shutdown_at
    if _launcher_managed:
        with _launcher_lock:
            _launcher_shutdown_at = None
    return ("", 204)


@app.post("/api/launcher/closing")
def api_launcher_closing():
    """Stop the managed server shortly after its dashboard tab closes."""
    global _launcher_shutdown_at
    if _launcher_managed:
        with _launcher_lock:
            # The grace period lets an ordinary page refresh reconnect.
            _launcher_shutdown_at = time.monotonic() + 5
    return ("", 204)


def _launcher_watchdog() -> None:
    while True:
        time.sleep(0.25)
        with _launcher_lock:
            shutdown_at = _launcher_shutdown_at
        if shutdown_at is not None and time.monotonic() >= shutdown_at:
            os._exit(0)


# ---- Jobs ------------------------------------------------------------------ #

@app.get("/api/jobs")
def api_jobs():
    only_unapplied = request.args.get("unapplied", "1") != "0"
    include_builtins = request.args.get("builtins", "1") != "0"
    return jsonify(jobs_service.get_all_jobs(only_unapplied, include_builtins))


@app.post("/api/jobs/apply")
def api_apply():
    data = request.get_json(force=True, silent=True) or {}
    slug, key = data.get("slug"), data.get("key")
    if not slug or not key:
        return jsonify({"ok": False, "error": "slug and key required"}), 400
    mark_applied(slug, [key])
    return jsonify({"ok": True})


@app.post("/api/jobs/unapply")
def api_unapply():
    data = request.get_json(force=True, silent=True) or {}
    slug, key = data.get("slug"), data.get("key")
    if not slug or not key:
        return jsonify({"ok": False, "error": "slug and key required"}), 400
    unmark_applied(slug, [key])
    return jsonify({"ok": True})


# ---- Applied --------------------------------------------------------------- #

@app.get("/api/applied")
def api_applied():
    custom_slugs = {slugify(str(c.get("name", ""))) for c in jobs_service.list_custom_companies()}
    slugs = set(list_companies()) | custom_slugs
    rows = []
    for slug in sorted(slugs):
        for item in list_applied(slug):
            item["slug"] = slug
            rows.append(item)
    rows.sort(key=lambda r: r.get("applied_at", ""), reverse=True)
    return jsonify({"applied": rows})


# ---- Resumes --------------------------------------------------------------- #

@app.get("/api/resumes")
def api_resumes():
    return jsonify(resume_store.list_resumes())


@app.post("/api/resumes")
def api_upload_resume():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "no file"}), 400
    try:
        info = resume_store.save_resume(uploaded.filename, uploaded.read())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "resume": info})


@app.post("/api/resumes/<resume_id>/active")
def api_set_active(resume_id):
    ok = resume_store.set_active(resume_id)
    return jsonify({"ok": ok})


@app.delete("/api/resumes/<resume_id>")
def api_delete_resume(resume_id):
    ok = resume_store.delete_resume(resume_id)
    return jsonify({"ok": ok})


# ---- Companies ------------------------------------------------------------- #

@app.get("/api/companies")
def api_companies():
    return jsonify({"companies": jobs_service.list_custom_companies()})


@app.post("/api/companies")
def api_add_company():
    data = request.get_json(force=True, silent=True) or {}
    try:
        entry = jobs_service.add_custom_company(
            data.get("name", ""), data.get("url", ""),
            data.get("ats", ""), data.get("token", ""),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "company": entry})


@app.delete("/api/companies")
def api_delete_company():
    data = request.get_json(force=True, silent=True) or {}
    ok = jobs_service.delete_custom_company(data.get("name", ""))
    return jsonify({"ok": ok})


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    if _launcher_managed:
        # If Brave never reaches the page, do not leave an orphaned server.
        with _launcher_lock:
            _launcher_shutdown_at = time.monotonic() + 30
        threading.Thread(target=_launcher_watchdog, daemon=True).start()
    print(f"Job Buddy running at http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
