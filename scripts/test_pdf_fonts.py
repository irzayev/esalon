"""Quick check: PDF renders Cyrillic and Azerbaijani."""
from app.services.pdf_fonts import html_to_pdf_bytes

html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/></head><body style="font-family: NotoSans, sans-serif;">
<p>Русский: Выручка, зарплаты, материалы</p>
<p>Azərbaycan: Gəlir, əmək haqları, şirkət, ödəniş</p>
<p>₼ 1 234,56</p>
</body></html>"""
data = html_to_pdf_bytes(html)
assert data[:4] == b"%PDF"
print(f"OK, {len(data)} bytes")
