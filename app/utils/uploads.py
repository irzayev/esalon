"""Safe file uploads into persistent /static/uploads."""
import os
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_IMAGE = {"png", "jpg", "jpeg", "webp", "gif"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def save_upload(file_storage, subdir: str = "", allowed: set[str] | None = None) -> str | None:
    """Save uploaded file. Returns relative path inside /static/uploads."""
    if not file_storage or not file_storage.filename:
        return None
    ext = _ext(file_storage.filename)
    if allowed and ext not in allowed:
        return None

    base = Path(current_app.config["UPLOAD_FOLDER"])
    target_dir = base / subdir if subdir else base
    target_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"
    fname = secure_filename(fname)
    target = target_dir / fname
    file_storage.save(target)

    rel = os.path.relpath(target, base).replace("\\", "/")
    return f"{subdir + '/' if subdir else ''}{fname}" if subdir else rel


def upload_url(rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    return f"/static/uploads/{rel_path}"
