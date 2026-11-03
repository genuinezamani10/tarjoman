#!/usr/bin/env python3
"""
eval_style.py — سنجش فاصلهٔ ترجمه با نسخهٔ دست‌نویسِ خودت (مجموعهٔ طلایی)

ساختار پوشه (مثلاً tests/golden/<نام-کتاب>/):
    p1.raw.txt    خروجی خام مدل (خط پایه)
    p1.gold.txt   نسخهٔ نهایی دست‌نویس تو
    p1.new.txt    (اختیاری) خروجی ترجمان با پروفایل تازه؛ با --cand new

اجرا:
    python3 scripts/eval_style.py tests/golden/<نام-قطعه>
    python3 scripts/eval_style.py tests/golden/<نام-قطعه> --cand colloquial --cand plain

برای هر قطعه و هر نامزد چاپ می‌کند:
  chrF       شباهت n-gram حرفی با نسخهٔ طلایی (۰ تا ۱۰۰، بیشتر = نزدیک‌تر)
  wordSim    شباهت دنبالهٔ کلمه‌ها با نسخهٔ طلایی (۰ تا ۱۰۰)
  و آمار سبک: تعداد کلمه و جمله، میانگین و بیشینهٔ طول جمله، پاراگراف، «؛» و «—»،
  «را» و «رو»، و نشانه‌های ترجمه‌زدگی («توسط»، «در مورد»، «به منظور»، ...).

هشدار تفسیر: تنها یک نسخهٔ دست‌نویس مبناست و ترجمهٔ درست چندین شکل دارد، پس
عددها فقط برای «مقایسهٔ نسبی روی همین قطعه‌ها» معنا دارند (قبل/بعد از تغییر
پروفایل یا پرامپت)، نه امتیاز مطلق کیفیت. آمار سبک را کنار نسخهٔ طلایی بخوان:
هدف، نزدیک‌شدن به آمار طلایی است، نه کمینه یا بیشینه‌کردن.
"""

import argparse
import difflib
import glob
import os
import re
import statistics
from collections import Counter

CALQUE_MARKERS = ["توسط", "در مورد", "به منظور", "علاوه بر این", "همچنین"]


def _norm(text: str) -> str:
    """نرمال‌سازی برای مقایسهٔ حرفی: فاصله، نیم‌فاصله، کشیده و نگارش حذف می‌شود."""
    t = text.replace("ك", "ک").replace("ي", "ی").replace("ـ", "")
    t = re.sub(r"[\s\u200c\u200f\u200e]+", "", t)
    return re.sub(r"[^\w]", "", t)


def chrf(hyp: str, ref: str, n: int = 6, beta: float = 2.0) -> float:
    h_s, r_s = _norm(hyp), _norm(ref)
    ps, rs = [], []
    for k in range(1, n + 1):
        h = Counter(h_s[i:i + k] for i in range(len(h_s) - k + 1))
        r = Counter(r_s[i:i + k] for i in range(len(r_s) - k + 1))
        if not h or not r:
            continue
        match = sum((h & r).values())
        ps.append(match / sum(h.values()))
        rs.append(match / sum(r.values()))
    if not ps:
        return 0.0
    p, r = statistics.mean(ps), statistics.mean(rs)
    if p + r == 0:
        return 0.0
    return 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def word_sim(hyp: str, ref: str) -> float:
    a = re.sub(r"[^\w\s\u200c]", " ", hyp).split()
    b = re.sub(r"[^\w\s\u200c]", " ", ref).split()
    return 100 * difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def stats(text: str) -> dict:
    sentences = [s for s in re.split(r"(?<=[.!?؟…])[»\"”]?\s+", text.strip()) if s.strip()]
    lens = [len(s.split()) for s in sentences]
    return {
        "words": len(text.split()),
        "sents": len(sentences),
        "avg_len": statistics.mean(lens) if lens else 0,
        "max_len": max(lens) if lens else 0,
        "paras": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
        "semi": text.count("؛") + text.count(";"),
        "dash": text.count("—") + text.count("–"),
        "ra": len(re.findall(r"(?<![\w\u200c])را(?![\w\u200c])", text)),
        "ro": len(re.findall(r"(?<![\w\u200c])رو(?![\w\u200c])", text)),
        "calque": sum(text.count(m) for m in CALQUE_MARKERS),
    }


def _fmt(label: str, hyp: str, gold: str, is_gold: bool = False) -> str:
    s = stats(hyp)
    sims = "   -        -  " if is_gold else f"{chrf(hyp, gold):6.1f}  {word_sim(hyp, gold):6.1f}"
    return (f"  {label:<10}{sims}  | {s['words']:4d} {s['sents']:4d} {s['avg_len']:5.1f} {s['max_len']:4d}"
            f" {s['paras']:4d} {s['semi']:3d} {s['dash']:3d} {s['ra']:3d} {s['ro']:3d} {s['calque']:3d}")


HEADER = ("  {:<10}{:>6}  {:>6}  | {:>4} {:>4} {:>5} {:>4} {:>4} {:>3} {:>3} {:>3} {:>3} {:>3}"
          .format("", "chrF", "wordSm", "wrds", "sent", "avgL", "maxL", "para", "؛", "—", "را", "رو", "cal"))


def main() -> None:
    ap = argparse.ArgumentParser(description="مقایسهٔ ترجمه با نسخهٔ طلایی")
    ap.add_argument("dir")
    ap.add_argument("--cand", action="append", default=[],
                    help="پسوند فایل نامزد: p1.<پسوند>.txt (می‌شود چندبار داد)")
    args = ap.parse_args()

    ids = sorted(os.path.basename(p)[:-len(".gold.txt")]
                 for p in glob.glob(os.path.join(args.dir, "*.gold.txt")))
    if not ids:
        raise SystemExit("هیچ فایل *.gold.txt در " + args.dir + " پیدا نشد.")
    labels = ["raw"] + args.cand
    totals = {lb: [] for lb in labels}
    for pid in ids:
        gold = open(os.path.join(args.dir, pid + ".gold.txt"), encoding="utf-8").read()
        print(f"\n{pid}\n{HEADER}")
        for lb in labels:
            path = os.path.join(args.dir, f"{pid}.{lb}.txt")
            if not os.path.isfile(path):
                print(f"  {lb:<10}(فایل {os.path.basename(path)} نیست)")
                continue
            hyp = open(path, encoding="utf-8").read()
            print(_fmt(lb, hyp, gold))
            totals[lb].append((chrf(hyp, gold), word_sim(hyp, gold)))
        print(_fmt("gold", gold, gold, is_gold=True))
    print("\nمیانگین روی همهٔ قطعه‌ها:")
    for lb in labels:
        if totals[lb]:
            c = statistics.mean(x[0] for x in totals[lb])
            w = statistics.mean(x[1] for x in totals[lb])
            print(f"  {lb:<10} chrF {c:5.1f}   wordSim {w:5.1f}   ({len(totals[lb])} قطعه)")


if __name__ == "__main__":
    main()
