"""Render a notice's TEXT to a synthetic PNG: plain white page, black DejaVu (or Arial) text and a diagonal SYNTHETIC
watermark. No logos, no emblems, no official's name or signature. Used by tests/test_ocr.py for the real OCR path and
by synthetic/make_notice_image.py (repo root) for the demo's ED_summons_synthetic.png. Needs only Pillow."""
import textwrap
from pathlib import Path

# DejaVu on Linux; on Windows, Arial, the plain sans-serif every Windows install ships.
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/TTF/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf")


class NoFont(RuntimeError):
    """None of FONT_PATHS exists on this machine."""


def font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise NoFont("no DejaVu font on this box")


def render_notice(text: str, path: Path) -> None:
    """Plain synthetic notice: black text on white at a size tesseract reads reliably, SYNTHETIC watermark behind."""
    from PIL import Image, ImageDraw
    lines = textwrap.wrap(text, width=58)
    width, line_h, margin = 1200, 48, 80
    height = 2 * margin + line_h * len(lines)
    img = Image.new("RGBA", (width, height), "white")
    watermark = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(watermark).text((width // 2, height // 2), "SYNTHETIC", font=font(110), fill=(0, 0, 0, 40), anchor="mm")
    img = Image.alpha_composite(img, watermark.rotate(30, center=(width // 2, height // 2)))
    draw, body = ImageDraw.Draw(img), font(32)
    for i, line in enumerate(lines):
        draw.text((margin, margin + i * line_h), line, font=body, fill="black")
    img.convert("RGB").save(path)
