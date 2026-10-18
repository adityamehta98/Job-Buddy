"""Local resume store for the web UI.

Saves uploaded CVs under resumes/, keeps a small JSON index, lets you mark one
as the 'active' resume used for match scoring, and supports delete. Everything
is local-only (resumes/ is git-ignored).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import matcher

RESUMES_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "resumes"
INDEX_FILE = RESUMES_DIR / "index.json"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _ensure_dir() -> None:
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"resumes": [], "active_id": None}
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data.setdefault("resumes", [])
        data.setdefault("active_id", None)
        return data
    except (json.JSONDecodeError, OSError):
        return {"resumes": [], "active_id": None}


def _save_index(index: dict) -> None:
    _ensure_dir()
    with open(INDEX_FILE, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2)


def list_resumes() -> dict:
    """Return {resumes: [{id, filename, uploaded_at, active}], active_id}."""
    index = _load_index()
    active_id = index.get("active_id")
    resumes = [
        {
            "id": r["id"],
            "filename": r["filename"],
            "uploaded_at": r["uploaded_at"],
            "active": r["id"] == active_id,
            "chars": len(r.get("text", "")),
        }
        for r in index.get("resumes", [])
    ]
    resumes.sort(key=lambda r: r["uploaded_at"], reverse=True)
    return {"resumes": resumes, "active_id": active_id}


def save_resume(filename: str, file_bytes: bytes) -> dict:
    """Store an uploaded resume, extract its text, and make it the active one."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    _ensure_dir()
    resume_id = uuid.uuid4().hex[:12]
    stored_name = f"{resume_id}{ext}"
    stored_path = RESUMES_DIR / stored_name
    stored_path.write_bytes(file_bytes)

    text = matcher.extract_text(stored_path)

    index = _load_index()
    index["resumes"].append({
        "id": resume_id,
        "filename": filename,
        "stored_name": stored_name,
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M"),
        "text": text,
    })
    index["active_id"] = resume_id  # newest upload becomes active by default
    _save_index(index)
    return {"id": resume_id, "filename": filename, "chars": len(text)}


def set_active(resume_id: str) -> bool:
    index = _load_index()
    if not any(r["id"] == resume_id for r in index["resumes"]):
        return False
    index["active_id"] = resume_id
    _save_index(index)
    return True


def delete_resume(resume_id: str) -> bool:
    index = _load_index()
    remaining = []
    removed = False
    for r in index["resumes"]:
        if r["id"] == resume_id:
            removed = True
            try:
                (RESUMES_DIR / r["stored_name"]).unlink(missing_ok=True)
            except OSError:
                pass
        else:
            remaining.append(r)
    if not removed:
        return False
    index["resumes"] = remaining
    if index.get("active_id") == resume_id:
        index["active_id"] = remaining[0]["id"] if remaining else None
    _save_index(index)
    return True


def active_resume_text() -> str:
    """Text of the active resume, or '' if none selected."""
    index = _load_index()
    active_id = index.get("active_id")
    for r in index.get("resumes", []):
        if r["id"] == active_id:
            return r.get("text", "")
    return ""


def scraper_cv_text() -> str:
    """Resume text for headless match scoring.

    Prefers the active uploaded resume (local UI); falls back to a file path in
    the CV_PATH env var so GitHub Actions can score too (uploads are local-only).
    """
    text = active_resume_text()
    if text:
        return text
    # Hosted/scheduled runs cannot see a resume uploaded to a laptop. A
    # repository secret can provide its extracted text without committing the
    # original resume file to source control.
    secret_text = os.getenv("CV_TEXT", "").strip()
    if secret_text:
        return secret_text
    cv_path = os.getenv("CV_PATH", "")
    if cv_path and os.path.exists(cv_path):
        return matcher.extract_text(cv_path)
    return ""
