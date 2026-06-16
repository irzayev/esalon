"""Backup & restore for the entire application data:
 - SQLite database (app/static/data/app.db)
 - Uploads folder (app/static/uploads/)

Один zip-архив, который можно скачать или загрузить обратно для восстановления.
"""
from __future__ import annotations
import io
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from flask import current_app

from ..config import DATA_DIR, UPLOAD_DIR


def _safe_target(base: Path, *parts: str) -> Path | None:
    """Resolve a target path and ensure it stays inside `base` (anti zip-slip)."""
    base = base.resolve()
    target = (base / Path(*parts)).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def create_backup_zip() -> tuple[bytes, str]:
    """Build a zip archive in memory with DB + uploads."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # DB
        for db_file in DATA_DIR.glob("*.db*"):
            zf.write(db_file, arcname=f"data/{db_file.name}")
        # Uploads
        if UPLOAD_DIR.exists():
            for path in UPLOAD_DIR.rglob("*"):
                if path.is_file():
                    arc = Path("uploads") / path.relative_to(UPLOAD_DIR)
                    zf.write(path, arcname=str(arc).replace("\\", "/"))
        # Manifest
        manifest = (
            f"eSalon backup\n"
            f"Created: {datetime.utcnow().isoformat()}Z\n"
        )
        zf.writestr("MANIFEST.txt", manifest)
    buf.seek(0)
    fname = f"esalon-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return buf.getvalue(), fname


def restore_backup_zip(file_storage) -> tuple[bool, str]:
    """Restore from uploaded zip. Overwrites DB and uploads."""
    try:
        data = file_storage.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if "MANIFEST.txt" not in names:
                return False, "Файл не является валидным бэкапом (нет MANIFEST.txt)"

            # Clear uploads
            if UPLOAD_DIR.exists():
                for child in UPLOAD_DIR.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        try:
                            child.unlink()
                        except OSError:
                            pass

            for name in names:
                if name.endswith("/") or name == "MANIFEST.txt":
                    continue
                if name.startswith("data/"):
                    target = _safe_target(DATA_DIR, Path(name).name)
                elif name.startswith("uploads/"):
                    target = _safe_target(UPLOAD_DIR, *Path(name).parts[1:])
                else:
                    continue
                # Skip any entry that resolves outside the intended directory.
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        return True, "Бэкап успешно восстановлен. Перезапустите приложение для применения."
    except zipfile.BadZipFile:
        return False, "Файл не является ZIP-архивом"
    except Exception as e:
        current_app.logger.exception("Restore failed")
        return False, f"Ошибка восстановления: {e}"
