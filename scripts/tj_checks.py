#!/usr/bin/env python3
"""
tj_checks.py — بررسی‌ها و ابزارهای کمکی ترجمان (بخشی از ترجمان)

فقط کتابخانهٔ استاندارد دارد و چهار کار انجام می‌دهد:

  ۱. src_hash(chunk, mode)
       هش کوتاه متن منبع + حالت ترجمه؛ در هر رکورد چک‌پوینت ذخیره می‌شود تا اگر
       PDF، بازهٔ صفحات، اندازهٔ تکه یا حالت عوض شد، ترجمهٔ قدیمی به‌اشتباه
       استفاده نشود.
  ۲. atomic_write_text(path, text)
       نوشتن اتمیک (فایل موقت + fsync + os.replace)؛ قطع ناگهانی برنامه هیچ‌وقت
       فایل نیمه‌نوشته یا خراب باقی نمی‌گذارد.
  ۳. check_numbers(src, out, mode)
       مقایسهٔ عددهای «مهم» (دو رقمی به بالا یا اعشاری) متن اصلی و ترجمه برای
       حالت‌های textbook و article. ارقام فارسی/عربی/لاتین و جداکنندهٔ هزارگان
       و اعشار نرمال می‌شوند. عددهای تک‌رقمی نادیده گرفته می‌شوند، چون مترجم
       معمولاً آن‌ها را حروفی می‌نویسد («۳ نوع» ← «سه نوع»).
  ۴. dedupe_first_use_parens(texts, glossary)
       حالت article: معادل انگلیسی هر اصطلاح فقط در نخستین کاربرد داخل پرانتز
       بماند. چون تکه‌ها مستقل ترجمه می‌شوند و هر تکه خودش را «اول» می‌داند،
       این پاس قطعی بعد از ترجمه تکرارها را حذف می‌کند.
  ۵. check_polish(before, after, finish_reason)
       خروجی پاس ویرایش فقط وقتی جایگزین ترجمهٔ اول می‌شود که خالی/قطع‌شده
       نباشد، طولش نزدیک ترجمهٔ اول باشد، فارسی بماند، عددهای مهم را حفظ کرده
       باشد و تعداد پاراگراف‌ها تقریباً همان باشد.
"""

import hashlib
import os
import re
import tempfile
from collections import Counter


# ───────────────────── ۱. هش منبع برای چک‌پوینت ─────────────────────

def src_hash(chunk: str, mode: str) -> str:
    return hashlib.sha1((mode + "\0" + chunk).encode("utf-8")).hexdigest()[:12]


# ───────────────────── ۲. نوشتن اتمیک ─────────────────────

def atomic_write_text(path: str, text: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ───────────────────── ۳. کنترل عددها ─────────────────────

# ارقام فارسی و عربی-هندی ← لاتین
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# هزارگان فقط وقتی که بعد از جداکننده دقیقاً سه رقم بیاید (۱,۰۰۰ یا ۱٬۰۰۰ یا ۱،۰۰۰)؛
# اعشار با «.» یا «٫». به‌این‌ترتیب «1,2,3» سه عدد جدا حساب می‌شود.
_NUM_RE = re.compile(r"\d{1,3}(?:[,٬،]\d{3})+(?:[.٫]\d+)?|\d+(?:[.٫]\d+)?")

# (کمینهٔ تعداد عدد گم‌شده، کمینهٔ نسبت گم‌شده به کل عددهای مهم)
NUM_RULES = {"textbook": (1, 0.0), "article": (2, 0.15)}
NUM_RULES_LOOSE = {"textbook": (2, 0.10), "article": (3, 0.25)}


def extract_numbers(text: str) -> Counter:
    c: Counter = Counter()
    for tok in _NUM_RE.findall((text or "").translate(_DIGIT_MAP)):
        c[tok.replace(",", "").replace("٬", "").replace("،", "").replace("٫", ".")] += 1
    return c


def _significant(n: str) -> bool:
    return "." in n or len(n) >= 2


def missing_significant(src: str, out: str):
    """(عددهای مهمِ متن اصلی که در خروجی نیامده‌اند، تعداد کل عددهای مهم منبع)."""
    s = Counter({k: v for k, v in extract_numbers(src).items()
                 if _significant(k)})
    missing = s - extract_numbers(out)  # فقط مقدارهای مثبت می‌مانند
    if missing:
        # اعشار فارسی گاهی با «/» نوشته می‌شود (۳/۱۴)؛ آن را معادل «3.14» بدان
        out_norm = (out or "").translate(_DIGIT_MAP)
        for key in list(missing):
            if "." not in key:
                continue
            pat = (r"(?<![\d/.])" + re.escape(key.replace(".", "/"))
                   + r"(?![\d/])")
            found = len(re.findall(pat, out_norm))
            if found:
                missing[key] -= min(found, missing[key])
                if missing[key] <= 0:
                    del missing[key]
    return missing, sum(s.values())


def check_numbers(src: str, out: str, mode: str, loose: bool = False) -> str:
    """رشتهٔ خالی یعنی سالم؛ وگرنه شرح عددهای گم‌شده یا تغییریافته."""
    rules = (NUM_RULES_LOOSE if loose else NUM_RULES).get(mode)
    if not rules:
        return ""
    min_missing, min_ratio = rules
    missing, total = missing_significant(src, out)
    if not total:
        return ""
    miss_n = sum(missing.values())
    if miss_n < min_missing or miss_n / total < min_ratio:
        return ""
    sample = "، ".join(list(missing.elements())[:6])
    return f"{miss_n} عدد از {total} عدد مهم متن اصلی در ترجمه نیست ({sample})"


# ───────────────────── ۵. اعتبارسنجی خروجی پاس ویرایش (polish) ─────────────────────

POLISH_WORD_RATIO = (0.85, 1.15)  # نسبت کلمات ویراسته به ترجمهٔ اول


def fa_ratio(text: str) -> float:
    """سهم حروف فارسی از کل حروف (۰ تا ۱)."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _is_persian(c)) / len(letters)


def _paragraph_count(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text or "") if p.strip()])


def check_polish(before: str, after: str, finish_reason=None) -> str:
    """
    آیا خروجی ویرایش را می‌شود جایگزین ترجمهٔ اول کرد؟
    رشتهٔ خالی یعنی بله؛ وگرنه دلیل رد شدن (و ترجمهٔ اول می‌ماند).
    """
    if not (after or "").strip():
        return "خروجی خالی"
    if finish_reason == "length":
        return "خروجی ناقص (قطع‌شده با length)"
    wb, wa = len(before.split()), len(after.split())
    if wb:
        r = wa / wb
        if r < POLISH_WORD_RATIO[0] or r > POLISH_WORD_RATIO[1]:
            return f"نسبت طول غیرعادی ({r:.2f})"
    if fa_ratio(after) < fa_ratio(before) - 0.10:
        return "سهم حروف فارسی افت کرده (احتمال توضیح یا متن غیرفارسی)"
    missing, _ = missing_significant(before, after)
    if missing:
        sample = "، ".join(list(missing.elements())[:6])
        return f"عدد گم‌شده یا تغییریافته ({sample})"
    pb, pa = _paragraph_count(before), _paragraph_count(after)
    if abs(pa - pb) > max(1, round(0.1 * pb)):
        return f"تعداد پاراگراف تغییر کرده ({pb}←{pa})"
    return ""


# ───────────────────── ۴. معادل انگلیسی فقط در نخستین کاربرد ─────────────────────

_PAREN_RE = re.compile(r"([ \t\u200c]*)\(\s*([^()\n]{2,80}?)\s*\)")
_LOWER_PHRASE = re.compile(r"[a-z][a-z0-9\-' ]*")


def _is_persian(c: str) -> bool:
    return ("\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufdff"
            or "\ufe70" <= c <= "\ufeff")


def _norm_key(s: str) -> str:
    return " ".join(s.lower().split())


def parse_glossary_sources(glossary: str) -> list[str]:
    """ستون چپ هر خط «اصل = معادل» واژه‌نامه (فقط اصل‌های لاتین)."""
    terms = []
    for line in (glossary or "").splitlines():
        line = line.strip().lstrip("-*•· \t")
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if "=" not in line:
            continue
        left = line.split("=", 1)[0].strip().strip("*`\"'").strip()
        if not left or any(_is_persian(c) for c in left):
            continue
        if re.search(r"[A-Za-z]", left):
            terms.append(left)
    return terms


def dedupe_first_use_parens(texts: list[str], glossary: str = ""):
    """
    ورودی: ترجمهٔ تکه‌ها به‌ترتیب سند. خروجی: (متن‌های اصلاح‌شده، تعداد حذف‌شده‌ها).

    یک «(English)» فقط وقتی حذف می‌شود که
      • درست بعد از یک کلمهٔ فارسی آمده باشد، و
      • یا اصلش در واژه‌نامه باشد، یا عبارتی کاملاً با حروف کوچک (و حداقل ۴ حرف)
        باشد؛ پس اسم خاص و مخفف‌ها («(Smith)»، «(RNN)») دست نمی‌خورند، مگر
        اینکه در واژه‌نامه آمده باشند، و
      • پیش‌تر در سند یک بار با همان معادل آمده باشد.
    """
    keys = {_norm_key(t) for t in parse_glossary_sources(glossary)}
    seen: set[str] = set()
    removed = 0

    def fix(text: str) -> str:
        nonlocal removed

        def repl(m):
            nonlocal removed
            content = m.group(2)
            key = _norm_key(content)
            eligible = key in keys or (
                len(content) >= 4 and _LOWER_PHRASE.fullmatch(content))
            if not eligible:
                return m.group(0)
            before = text[:m.start()]
            if not before or not _is_persian(before[-1]):
                return m.group(0)
            if key in seen:
                removed += 1
                return ""
            seen.add(key)
            return m.group(0)

        return _PAREN_RE.sub(repl, text)

    return [fix(t) for t in texts], removed
