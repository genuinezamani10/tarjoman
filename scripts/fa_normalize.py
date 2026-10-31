#!/usr/bin/env python3
"""
fa_normalize.py — نرمال‌ساز متن فارسی برای خروجی OCR (بخشی از پروژهٔ ترجمان)

مدل‌های OCR راست‌به‌چپ (مثل Indra) گاهی نویسه‌های اردو/عربی را به جای معادل
فارسی‌شان می‌نویسند (مثلاً «بہتر» به جای «بهتر» یا «رفيق» به جای «رفیق»).
این اسکریپت آن قاطی‌شدن‌ها را به‌صورت قطعی و بدون تغییر معنا اصلاح می‌کند:

  - ي (عربی) → ی ، ك (عربی) → ک ، ى (الف مقصوره) → ی
  - ہ / ھ / ۂ / ۃ / ۀ (اردو) → ه
  - ة → ه ، أ / إ / ٱ → ا
  - ٹ → ت ، ڈ → د ، ڑ → ر ، ے / ۓ → ی ، ں → ن  (حروف خاص اردو)
  - حذف کشیدگی (ـ) و اعراب عربی
  - حذف نویسه‌های نامرئی جهت‌دهی (U+200E/F، U+061C، U+2066–U+2069) که OCR گاهی می‌نویسد
  - ارقام عربی (٠١٢٣) → ارقام فارسی (۰۱۲۳)
  - چسباندن نیم‌فاصله در «می‌/نمی‌» و پسوندهای «ها/های/هایی»
  - مرتب‌سازی فاصله دور علائم نگارشی

استفاده:
    from fa_normalize import normalize_fa
    clean = normalize_fa(raw_text)

    python3 fa_normalize.py input.txt output.txt   # یا stdin → stdout
"""

import re
import sys

# ── جدول جایگزینی نویسه‌ها ─────────────────────────────────────────────
_CHAR_MAP = {
    "ي": "ی",  # U+064A Arabic yeh      → U+06CC Farsi yeh
    "ك": "ک",  # U+0643 Arabic kaf      → U+06A9 Farsi kaf
    "ہ": "ه",  # U+06C1 Urdu heh goal   → U+0647 heh
    "ھ": "ه",  # U+06BE Urdu heh doachashmee → ه
    "ۂ": "ه",  # U+06C2 heh goal + hamza → ه
    "ۃ": "ه",  # U+06C3 teh marbuta goal → ه
    "ۀ": "ه",  # U+06C0 heh + yeh above (Urdu ezafe) → ه
    "ة": "ه",  # U+0629 teh marbuta     → ه
    "أ": "ا",  # U+0623 alef + hamza above → ا
    "إ": "ا",  # U+0625 alef + hamza below → ا
    "ٱ": "ا",  # U+0671 alef wasla      → ا
    "ٹ": "ت",  # U+0679 Urdu tteh       → ت
    "ڈ": "د",  # U+0688 Urdu dal        → د
    "ڑ": "ر",  # U+0691 Urdu rreh       → ر
    "ے": "ی",  # U+06D2 Urdu bari yeh   → ی
    "ۓ": "ی",  # U+06D3 bari yeh + hamza → ی
    "ں": "ن",  # U+06BA Urdu noon ghunna → ن
    "ى": "ی",  # U+0649 alef maksura    → ی (OCR عربی‌محور به‌جای ی فارسی)
    "ـ": "",   # U+0640 tatweel (کشیدگی) حذف می‌شود
    "ٰ": "",   # U+0670 superscript alef حذف می‌شود
}

# اعراب عربی (فتحه، ضمه، کسره، تشدید و ...) U+064B..U+0652 حذف می‌شوند
_DIACRITICS = re.compile(r"[ً-ْ]")

# نویسه‌های نامرئی جهت‌دهی/قالب‌بندی (U+200E/F، U+061C، U+2066–U+2069):
# موتورهای OCR گاهی آن‌ها را در متن می‌نویسند و در رندر PDF اخلال می‌کنند
_BIDI_MARKS = re.compile("[‎‏؜⁦-⁩]")

# ارقام عربی ٠-٩ (U+0660..U+0669) → ارقام فارسی ۰-۹ (U+06F0..U+06F9)
_DIGIT_MAP = {chr(0x0660 + i): chr(0x06F0 + i) for i in range(10)}

_TRANS = str.maketrans({**_CHAR_MAP, **_DIGIT_MAP})

_ZWNJ = "‌"

# «می روم» / «نمی شود» → «می‌روم» / «نمی‌شود» (فقط وقتی «می/نمی» جدا و سرِ فعل است)
_MI_RE = re.compile(r"(?<![\w‌])(ن?می)[ \t]+(?=[^\s])")
# «کتاب ها» → «کتاب‌ها» ، «خانه های» → «خانه‌های» ، «مدرسه هایی» → «مدرسه‌هایی»
_HA_RE = re.compile(r"(\S)[ \t]+(ها|های|هایی)(?=[\s\.,!؟?؛:»\)\]]|$)")
# فاصلهٔ اضافی قبل از علائم نگارشی: «سلام .» → «سلام.»
_PUNCT_SPACE_RE = re.compile(r"[ \t]+([\.،!؟?؛:»])")
# نبود فاصله بعد از علائم وقتی چسبیده به حرف بعدی‌اند: «سلام،خوبی» → «سلام، خوبی»
_PUNCT_JOIN_RE = re.compile(r"([،؛:])(?=[^\s\d])")


def normalize_fa(text: str) -> str:
    """متن فارسیِ خروجی OCR را نرمال می‌کند؛ برای متن غیرفارسی بی‌اثر و امن است."""
    if not text:
        return text
    text = text.translate(_TRANS)
    text = _DIACRITICS.sub("", text)
    text = _BIDI_MARKS.sub("", text)
    text = text.replace(" ", " ")
    text = _MI_RE.sub(lambda m: m.group(1) + _ZWNJ, text)
    text = _HA_RE.sub(lambda m: m.group(1) + _ZWNJ + m.group(2), text)
    text = _PUNCT_SPACE_RE.sub(r"\1", text)
    text = _PUNCT_JOIN_RE.sub(r"\1 ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = f.read()
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(normalize_fa(data))
    else:
        sys.stdout.write(normalize_fa(sys.stdin.read()))
