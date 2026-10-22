#!/usr/bin/env python3
"""
extract_text.py — استخراج قطعی متن از PDFهای دارای لایهٔ متن (بخشی از ترجمان)

همان قواعد مرحلهٔ استخراج ترجمان را پیاده می‌کند:
  - خواندن بلاک‌های متنی با حفظ ترتیب سند؛ تشخیص صفحهٔ دوستونه و خواندن
    ستون‌به‌ستون (چپ بعد راست؛ بلاک‌های تمام‌عرض سر جای خودشان)
  - حذف سرصفحه/پاصفحهٔ تکراری و شماره‌صفحهٔ تنها
  - چسباندن کلمات دوشقه‌شده با خط تیره، یکی‌کردن شکست خط‌های داخل پاراگراف
  - در حالت textbook خطوط شبیه فرمول/کد دست نخورده می‌مانند
  - اگر میانگین کاراکتر هر صفحه < ۱۰۰ بود: is_scanned=true (یعنی نوبت OCR است)
  - تکه‌بندی حدوداً ۱۳۰۰ کلمه‌ای روی مرز پاراگراف + JSON manifest روی stdout

استفاده:
    python3 extract_text.py --pdf input.pdf --outdir workdir [--pages "1-5"] [--mode textbook]
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ocr_extract import parse_pages, pages_label, chunk  # noqa: E402

FORMULA_RE = re.compile(r"[=+∑∫√π∞±×÷<>^_{}\\]|^\s{2,}\S")
BARE_NUMBER = re.compile(r"^[\d۰-۹\s\.\-–—/]+$")


def page_paragraphs(page, textbook: bool) -> list[tuple[str, float, float]]:
    """پاراگراف‌های یک صفحه را با مختصاتشان برمی‌گرداند: (متن، y0، ارتفاع صفحه)"""
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not blocks:
        return []
    pw, ph = page.rect.width, page.rect.height
    widths = [b[2] - b[0] for b in blocks]
    narrow = [b for b in blocks if (b[2] - b[0]) < 0.55 * pw]
    two_col = (
        len(narrow) >= 4
        and any((b[0] + b[2]) / 2 < pw / 2 for b in narrow)
        and any((b[0] + b[2]) / 2 >= pw / 2 for b in narrow)
    )

    def block_text(b) -> str:
        raw = b[4]
        if textbook and any(FORMULA_RE.search(l) for l in raw.splitlines()):
            return raw.strip()  # خطوط فرمول/کد عیناً حفظ می‌شوند
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        out = ""
        for l in lines:
            if out.endswith("-") and l and l[0].islower():
                out = out[:-1] + l  # چسباندن کلمهٔ دوشقه
            elif out:
                out += " " + l
            else:
                out = l
        return out

    if not two_col:
        ordered = sorted(blocks, key=lambda b: (round(b[1]), b[0]))
        return [(block_text(b), b[1], ph) for b in ordered]

    mid = pw / 2
    wide = sorted([b for b in blocks if (b[2] - b[0]) >= 0.8 * pw],
                  key=lambda b: b[1])
    left = sorted([b for b in narrow if (b[0] + b[2]) / 2 < mid],
                  key=lambda b: b[1])
    right = sorted([b for b in narrow if (b[0] + b[2]) / 2 >= mid],
                   key=lambda b: b[1])
    seq = []
    wi = 0
    for col in (left, right):
        for b in col:
            while wi < len(wide) and wide[wi][1] < b[1]:
                seq.append(wide[wi])
                wi += 1
            seq.append(b)
    while wi < len(wide):
        seq.append(wide[wi])
        wi += 1
    return [(block_text(b), b[1], ph) for b in seq]


def extract(pdf_path: str, pages_spec: str, textbook: bool):
    import pymupdf

    doc = pymupdf.open(pdf_path)
    total = doc.page_count
    pages = parse_pages(pages_spec, total)
    title = (doc.metadata or {}).get("title") or ""

    per_page = []   # (متن صفحه با پاراگراف‌های \n\n جداشده، تعداد کاراکتر)
    raw_paras = []  # (پاراگراف، شماره صفحه، y0 نسبی)
    for pno in pages:
        paras = page_paragraphs(doc[pno], textbook)
        chars = sum(len(t) for t, _, _ in paras)
        per_page.append(chars)
        for text, y0, ph in paras:
            raw_paras.append((text, pno, y0 / ph if ph else 0))

    avg_chars = (sum(per_page) / len(per_page)) if per_page else 0
    is_scanned = avg_chars < 100

    # حذف سرصفحه/پاصفحهٔ تکراری: پاراگرافی که در ناحیهٔ بالا/پایینِ بیش از
    # نیمی از صفحات تکرار شود، یا شماره‌صفحهٔ تنها در لبه‌ها باشد
    from collections import Counter
    n = len(pages)
    edge_count = Counter()
    for text, pno, rel_y in raw_paras:
        if rel_y < 0.08 or rel_y > 0.92:
            edge_count[text] += 1
    furniture = {t for t, c in edge_count.items() if n >= 3 and c > n / 2}

    paragraphs = []
    for text, pno, rel_y in raw_paras:
        edge = rel_y < 0.08 or rel_y > 0.92
        if edge and (text in furniture or BARE_NUMBER.match(text)):
            continue
        paragraphs.append(text)

    return {
        "paragraphs": paragraphs,
        "total_pages": total,
        "pages_used": pages_label(pages, total),
        "title": title,
        "is_scanned": is_scanned,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pages", default="")
    ap.add_argument("--mode", default="article")
    args = ap.parse_args()

    res = extract(args.pdf, args.pages, args.mode == "textbook")
    os.makedirs(args.outdir, exist_ok=True)
    chunks_meta = []
    if not res["is_scanned"]:
        for i, t in enumerate(chunk(res["paragraphs"]), 1):
            path = os.path.join(args.outdir, f"chunk-{i:03d}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(t)
            chunks_meta.append({"path": os.path.abspath(path),
                                "words": len(t.split())})
    if not res["title"] and res["paragraphs"]:
        res["title"] = res["paragraphs"][0][:80]
    print(json.dumps({
        "chunks": chunks_meta,
        "total_pages": res["total_pages"],
        "pages_used": res["pages_used"],
        "title": res["title"],
        "is_scanned": res["is_scanned"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
