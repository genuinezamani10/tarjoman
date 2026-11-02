#!/usr/bin/env python3
"""
build_pdf.py — ساخت PDF فارسی راست‌به‌چپ از متن ترجمه‌شده (بخشی از ترجمان)

با fpdf2 + arabic-reshaper + python-bidi متن فارسی را درست شکل‌دهی و
راست‌چین می‌کند. فونت وزیرمتن لازم است؛ به این ترتیب پیدایش می‌کند:
  ۱. پوشهٔ fonts/ کنار پروژه (Vazirmatn-Regular.ttf و در صورت وجود Bold)
  ۲. متغیر محیطی TARJOMAN_FONT_DIR
  ۳. ~/.fonts/
اگر فونتی پیدا نشود، خطای واضح با راهنمای دانلود برمی‌گرداند.

شکستن خط: متن «منطقی» پاراگراف اول با اندازه‌گیری عرضِ شکل‌گرفتهٔ هر کلمه به خط‌ها
شکسته می‌شود؛ بعد روی هر خط جداگانه reshape + bidi (با جهت پایهٔ راست‌به‌چپ)
اعمال و خط با cell نوشته می‌شود. (نسخهٔ قبلی کل پاراگراف را به ترتیب دیداری
برمی‌گرداند و بعد multi_cell می‌شکست، که ترتیب خط‌ها را وارونه می‌کرد.)
"""

import functools
import os
import re

FONT_REGULAR = "Vazirmatn-Regular.ttf"
FONT_BOLD = "Vazirmatn-Bold.ttf"
DOWNLOAD_HINT = (
    "فونت وزیرمتن پیدا نشد. آن را از https://github.com/rastikerdar/vazirmatn "
    "بگیرید و فایل‌های Vazirmatn-Regular.ttf و Vazirmatn-Bold.ttf را در پوشهٔ "
    "fonts/ کنار پروژه بگذارید (یا TARJOMAN_FONT_DIR را به پوشهٔ فونت‌ها بدهید)."
)

# سطح عنوان ← (اندازهٔ فونت، فاصله بعد از عنوان)
HEADING_STYLES = {1: (17, 6), 2: (15, 5), 3: (13, 4)}
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


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


@functools.lru_cache(maxsize=50000)
def _shape(text: str) -> str:
    """reshape + bidi با جهت پایهٔ راست‌به‌چپ (برای یک خط یا یک کلمه).

    جهت پایه باید صریحاً راست‌به‌چپ باشد؛ وگرنه خطی که با واژهٔ انگلیسی شروع شود
    خودکار چپ‌به‌راست حساب می‌شود و ترتیب اجزایش به‌هم می‌ریزد."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    shaped = arabic_reshaper.reshape(text)
    try:
        return get_display(shaped, base_dir="R")
    except TypeError:  # نسخه‌ای از python-bidi که base_dir ندارد
        return get_display(shaped)


def wrap_logical(text: str, max_w: float, measure, shape=None) -> list[str]:
    """
    متن منطقی را به خط‌هایی بشکن که عرض شکل‌گرفته‌شان از max_w بیشتر نشود.

    خروجی خط‌هایی به ترتیب منطقی (خط اول = ابتدای پاراگراف) و هنوز بدون shape است.
    عرض هر کلمه جداگانه و روی شکل نهایی‌اش (measure(shape(word))) سنجیده می‌شود؛
    چون اتصال حروف از مرز فاصله رد نمی‌شود، جمع عرض کلمه‌ها = عرض خط.
    کلمه‌ای که تنهایی از max_w پهن‌تر باشد (مثلاً URL) در خط خودش می‌ماند.
    """
    shape = shape or _shape
    space_w = measure(" ")
    lines, cur, cur_w = [], [], 0.0
    for word in text.split():
        ww = measure(shape(word))
        add = ww if not cur else space_w + ww
        if cur and cur_w + add > max_w:
            lines.append(" ".join(cur))
            cur, cur_w = [word], ww
        else:
            cur.append(word)
            cur_w += add
    if cur:
        lines.append(" ".join(cur))
    return lines


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
        avail = pdf.w - pdf.l_margin - pdf.r_margin
        line_h = size * 0.62
        # حاشیهٔ داخلی cell (c_margin) از دو طرف از عرض قابل‌استفاده کم می‌شود
        usable = avail - 2 * getattr(pdf, "c_margin", 1.0)
        for line in wrap_logical(text, usable, pdf.get_string_width):
            # new_x="LMARGIN": بعد از هر خط مکان‌نما به حاشیهٔ چپ برمی‌گردد
            # (بدون آن، خط بعدی عرض صفر می‌گرفت و fpdf کرش می‌کرد)
            pdf.cell(avail, line_h, _shape(line), align="R",
                     new_x="LMARGIN", new_y="NEXT")
        pdf.ln(space_after)

    def write_block(block: str):
        """یک بلوک (بین دو خط خالی): خط‌های «#»، «##» و «###» عنوان‌اند؛
        بقیهٔ خط‌ها (پشت‌سرهم) یک پاراگراف می‌شوند."""
        buf: list[str] = []

        def flush():
            if buf:
                write_rtl(" ".join(buf), 12, space_after=4)
                buf.clear()

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _HEADING_RE.match(line)
            if m:
                flush()
                size, after = HEADING_STYLES[len(m.group(1))]
                write_rtl(m.group(2), size, bold_style=True, space_after=after)
            else:
                buf.append(line)
        flush()

    write_rtl(title, 20, bold_style=True, space_after=8)
    for para in paragraphs:
        for block in re.split(r"\n\s*\n", (para or "").strip()):
            if block.strip():
                write_block(block)
    pdf.output(out_path)
    return out_path


if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], encoding="utf-8").read()
    build_pdf("ترجمان", [src], sys.argv[2])
    print("OK:", sys.argv[2])
