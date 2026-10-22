#!/usr/bin/env python3
"""
build_pdf.py — ساخت PDF فارسی راست‌به‌چپ از متن ترجمه‌شده (بخشی از ترجمان)

با fpdf2 + arabic-reshaper + python-bidi متن فارسی را درست شکل‌دهی و
راست‌چین می‌کند. فونت وزیرمتن لازم است؛ به این ترتیب پیدایش می‌کند:
  ۱. پوشهٔ fonts/ کنار پروژه (Vazirmatn-Regular.ttf و در صورت وجود Bold)
  ۲. متغیر محیطی TARJOMAN_FONT_DIR
  ۳. ~/.fonts/
اگر فونتی پیدا نشود، خطای واضح با راهنمای دانلود برمی‌گرداند.
"""

import os
import re

FONT_REGULAR = "Vazirmatn-Regular.ttf"
FONT_BOLD = "Vazirmatn-Bold.ttf"
DOWNLOAD_HINT = (
    "فونت وزیرمتن پیدا نشد. آن را از https://github.com/rastikerdar/vazirmatn "
    "بگیرید و فایل‌های Vazirmatn-Regular.ttf و Vazirmatn-Bold.ttf را در پوشهٔ "
    "fonts/ کنار پروژه بگذارید (یا TARJOMAN_FONT_DIR را به پوشهٔ فونت‌ها بدهید)."
)


def _find_font(filename: str) -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "fonts", filename),
        os.path.join(os.getcwd(), "fonts", filename),
        os.path.expanduser(os.path.join("~/.fonts", filename)),
    ]
    env_dir = os.environ.get("TARJOMAN_FONT_DIR")
    if env_dir:
        candidates.insert(0, os.path.join(env_dir, filename))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _shape(text: str) -> str:
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


def build_pdf(title: str, paragraphs: list[str], out_path: str) -> str:
    from fpdf import FPDF

    regular = _find_font(FONT_REGULAR)
    if not regular:
        raise FileNotFoundError(DOWNLOAD_HINT)
    bold = _find_font(FONT_BOLD) or regular

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("vazir", "", regular, uni=True)
    pdf.add_font("vazir", "B", bold, uni=True)
    pdf.add_page()

    def write_rtl(text: str, size: int, bold_style: bool = False,
                  space_after: float = 4):
        pdf.set_font("vazir", "B" if bold_style else "", size)
        for line in text.split("\n"):
            line = line.strip()
            if line:
                pdf.multi_cell(0, size * 0.62, _shape(line), align="R")
        pdf.ln(space_after)

    write_rtl(title, 20, bold_style=True, space_after=8)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith("## "):
            write_rtl(para[3:], 15, bold_style=True, space_after=5)
        elif para.startswith("# "):
            write_rtl(para[2:], 17, bold_style=True, space_after=6)
        else:
            # پاراگراف ممکن است چند زیربند با خط خالی داشته باشد
            for sub in re.split(r"\n\s*\n", para):
                if sub.strip():
                    write_rtl(sub.replace("\n", " "), 12, space_after=4)
    pdf.output(out_path)
    return out_path


if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], encoding="utf-8").read()
    build_pdf("ترجمان", [src], sys.argv[2])
    print("OK:", sys.argv[2])
