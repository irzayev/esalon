"""Unicode PDF fonts (Cyrillic, Azerbaijani) for xhtml2pdf / ReportLab."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_REGULAR = _FONTS_DIR / "NotoSans-Regular.ttf"
_BOLD = _FONTS_DIR / "NotoSans-Bold.ttf"

FONT_FAMILY = "NotoSans"

_REGISTERED = False


def ensure_pdf_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    if not _REGULAR.is_file() or not _BOLD.is_file():
        raise FileNotFoundError(
            f"PDF fonts not found in {_FONTS_DIR}. "
            "Expected NotoSans-Regular.ttf and NotoSans-Bold.ttf"
        )
    pdfmetrics.registerFont(TTFont(FONT_FAMILY, str(_REGULAR)))
    pdfmetrics.registerFont(TTFont(f"{FONT_FAMILY}-Bold", str(_BOLD)))
    addMapping(FONT_FAMILY, 1, 0, f"{FONT_FAMILY}-Bold")
    _REGISTERED = True


def pdf_link_callback(uri: str, rel: str = "") -> str:
    """Resolve local font/asset paths for xhtml2pdf."""
    if uri.startswith("file://"):
        return uri[7:]
    name = Path(uri).name
    candidate = _FONTS_DIR / name
    if candidate.is_file():
        return str(candidate.resolve())
    path = Path(uri)
    if path.is_file():
        return str(path.resolve())
    return uri


def html_to_pdf_bytes(html: str) -> bytes:
    """Render HTML to PDF with UTF-8 Cyrillic / Azerbaijani support."""
    ensure_pdf_fonts()
    buf = BytesIO()
    status = pisa.CreatePDF(
        html,
        dest=buf,
        encoding="utf-8",
    )
    if status.err:
        raise RuntimeError("Не удалось сформировать PDF")
    return buf.getvalue()
