"""Unicode PDF fonts (Cyrillic, Azerbaijani) for xhtml2pdf / ReportLab."""
from __future__ import annotations

import os
import re
from io import BytesIO
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_REGULAR = _FONTS_DIR / "NotoSans-Regular.ttf"
_BOLD = _FONTS_DIR / "NotoSans-Bold.ttf"
_FONT_BY_NAME = {
    _REGULAR.name: _REGULAR,
    _BOLD.name: _BOLD,
}

FONT_FAMILY = "NotoSans"

_REGISTERED = False
_XHTML2PDF_PATCHED = False


def _patch_reportlab_open_for_read() -> None:
    """ReportLab mis-parses 'C:\\path' and 'C:/path' as URLs on Windows."""
    if os.name != "nt":
        return
    import reportlab.lib.utils as rlutils

    if getattr(rlutils.open_for_read, "_washer_patched", False):
        return

    _orig = rlutils.open_for_read

    def open_for_read(name, mode="rb"):
        if (
            isinstance(name, str)
            and len(name) > 2
            and name[1] == ":"
            and name[2] in ("/", "\\")
        ):
            return open(name.replace("\\", "/"), mode)
        return _orig(name, mode)

    open_for_read._washer_patched = True  # type: ignore[attr-defined]
    rlutils.open_for_read = open_for_read


def _patch_xhtml2pdf_load_font() -> None:
    """Embed bundled TTFs by path (avoid broken temp-file copy on Windows)."""
    global _XHTML2PDF_PATCHED
    if _XHTML2PDF_PATCHED:
        return
    from xhtml2pdf.context import pisaContext

    _orig = pisaContext.loadFont

    def loadFont(self, names, src, bold=0, italic=0):  # noqa: N802
        uri = getattr(src, "uri", None) or ""
        direct = _FONT_BY_NAME.get(Path(uri).name)
        if direct and direct.is_file():
            path = str(direct.resolve()).replace("\\", "/")
            orig_named = src.getNamedFile
            src.getNamedFile = lambda p=path: p
            try:
                return _orig(self, names, src, bold=bold, italic=italic)
            finally:
                src.getNamedFile = orig_named
        return _orig(self, names, src, bold=bold, italic=italic)

    pisaContext.loadFont = loadFont
    _XHTML2PDF_PATCHED = True


def ensure_pdf_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    if not _REGULAR.is_file() or not _BOLD.is_file():
        raise FileNotFoundError(
            f"PDF fonts not found in {_FONTS_DIR}. "
            "Expected NotoSans-Regular.ttf and NotoSans-Bold.ttf"
        )
    _patch_reportlab_open_for_read()
    _patch_xhtml2pdf_load_font()
    regular = str(_REGULAR.resolve()).replace("\\", "/")
    bold = str(_BOLD.resolve()).replace("\\", "/")
    pdfmetrics.registerFont(TTFont(FONT_FAMILY, regular))
    pdfmetrics.registerFont(TTFont(f"{FONT_FAMILY}-Bold", bold))
    addMapping(FONT_FAMILY, 0, 0, FONT_FAMILY)
    addMapping(FONT_FAMILY, 1, 0, f"{FONT_FAMILY}-Bold")
    addMapping(FONT_FAMILY, 0, 1, FONT_FAMILY)
    addMapping(FONT_FAMILY, 1, 1, f"{FONT_FAMILY}-Bold")
    _REGISTERED = True


def pdf_font_face_css() -> str:
    """@font-face rules so xhtml2pdf embeds TTF glyphs (not Helvetica squares)."""
    return f"""
@font-face {{
  font-family: {FONT_FAMILY};
  src: url("{_REGULAR.name}");
}}
@font-face {{
  font-family: {FONT_FAMILY};
  font-weight: bold;
  src: url("{_BOLD.name}");
}}
"""


def _inject_font_css(html: str) -> str:
    css = f"<style type=\"text/css\">{pdf_font_face_css()}</style>"
    if re.search(r"<head\b", html, re.I):
        return re.sub(r"(<head[^>]*>)", rf"\1{css}", html, count=1, flags=re.I)
    return f"<!DOCTYPE html><html><head>{css}</head><body>{html}</body></html>"


def html_to_pdf_bytes(html: str) -> bytes:
    """Render HTML to PDF with UTF-8 Cyrillic / Azerbaijani support."""
    ensure_pdf_fonts()
    html = _inject_font_css(html)
    buf = BytesIO()
    status = pisa.CreatePDF(
        html,
        dest=buf,
        encoding="utf-8",
        path=str(_FONTS_DIR),
    )
    if status.err:
        raise RuntimeError("Не удалось сформировать PDF")
    return buf.getvalue()
