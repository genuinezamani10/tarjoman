#!/usr/bin/env python3
"""
ocr_extract.py — مرحلهٔ OCR لوکال ترجمان برای PDFهای اسکن‌شده

PDF اسکن‌شده (بدون لایهٔ متن) را با Indra OCR (مدل ONNX، فقط CPU) می‌خواند،
خروجی را پاک‌سازی و نرمال‌سازی فارسی می‌کند و دقیقاً همان قالبی را تحویل
می‌دهد که مرحلهٔ استخراج عادی ترجمان (PyMuPDF) تولید می‌کند: تکه‌های حدوداً
۱۳۰۰ کلمه‌ای روی مرز پاراگراف + یک JSON manifest روی stdout.

استفاده:
    python3 ocr_extract.py --pdf input.pdf --outdir workdir [--pages "1-5,8"]

پیش‌نیازها:
    pip install pymupdf        (داخل همان venv)
    pip install indra-ocr      (باینری indra-ocr در PATH یا INDRA_OCR_BIN)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa_normalize import normalize_fa  # noqa: E402

SENTENCE_END = (".", "!", "؟", "?", "؛", ":", "»", "…")


def log(*a):
    print(*a, file=sys.stderr)


def parse_pages(spec: str, total: int) -> list[int]:
    """'1-5,8' → فهرست صفرمبنا؛ خالی یعنی همهٔ صفحات."""
    if not spec or not spec.strip():
        return list(range(total))
    picked = set()
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            picked.update(range(int(a) - 1, int(b)))
        elif part:
            picked.add(int(part) - 1)
    return sorted(p for p in picked if 0 <= p < total)


def pages_label(pages: list[int], total: int) -> str:
    if len(pages) == total:
        return "همهٔ صفحات"
    return ",".join(str(p + 1) for p in pages)


def find_indra() -> str:
    cand = os.environ.get("INDRA_OCR_BIN") or shutil.which("indra-ocr")
    if cand:
        return cand
    fallback = os.path.expanduser("~/workspace/tools/indra-venv/bin/indra-ocr")
    if os.path.exists(fallback):
        return fallback
    raise SystemExit("indra-ocr پیدا نشد؛ اول نصبش کن: pip install indra-ocr")


def run_ocr(pdf_path: str, tmpdir: str) -> list[dict]:
    out_dir = os.path.join(tmpdir, "indra-out")
    cmd = [find_indra(), pdf_path, "--mode", "ocr", "--format", "json",
           "--out", out_dir]
    log("اجرا:", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    pages = []
    for name in sorted(os.listdir(out_dir)):
        with open(os.path.join(out_dir, name), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    pages.append(json.loads(line))
    pages.sort(key=lambda p: p.get("page", 0))
    return pages


def drop_furniture(pages_lines: list[list[str]]) -> list[list[str]]:
    """حذف سرصفحه/پاصفحهٔ تکراری و شماره‌صفحهٔ تنها از اول/آخر صفحات."""
    n = len(pages_lines)
    if n == 0:
        return pages_lines
    bare_number = re.compile(r"^[\d۰-۹\s\.\-–—/]+$")
    if n >= 3:
        from collections import Counter
        slots = Counter()
        for lines in pages_lines:
            edge = [l.strip() for l in lines[:2]] + [l.strip() for l in lines[-2:]]
            for e in set(edge):
                if e:
                    slots[e] += 1
        furniture = {t for t, c in slots.items() if c > n / 2}
    else:
        furniture = set()
    cleaned = []
    for lines in pages_lines:
        out = []
        for i, l in enumerate(lines):
            edge = i < 2 or i >= len(lines) - 2
            s = l.strip()
            if edge and (s in furniture or (s and bare_number.match(s))):
                continue
            out.append(l)
        cleaned.append(out)
    return cleaned


def build_paragraphs(pages_lines: list[list[str]]) -> list[str]:
    all_lines = [l for lines in pages_lines for l in lines if l.strip()]
    if not all_lines:
        return []
    med = median(len(l) for l in all_lines) or 1
    paragraphs, cur = [], []
    for lines in pages_lines:
        for raw in lines:
            line = normalize_fa(raw)
            if not line:
                continue
            cur.append(line)
            short = len(line) < 0.55 * med
            if line.endswith(SENTENCE_END) or short:
                paragraphs.append(" ".join(cur))
                cur = []
        if cur:  # پایان صفحه هم مرز امن پاراگراف است
            paragraphs.append(" ".join(cur))
            cur = []
    if cur:
        paragraphs.append(" ".join(cur))
    return [p for p in paragraphs if p.strip()]


def split_long_paragraph(p: str, max_words: int) -> list[str]:
    parts, buf = [], ""
    for sent in re.split(r"(?<=[.!؟])\s+", p):
        cand = (buf + " " + sent).strip()
        if len(cand.split()) > max_words and buf:
            parts.append(buf)
            buf = sent
        else:
            buf = cand
    if buf:
        parts.append(buf)
    return parts


def chunk(paragraphs: list[str], target: int = 1300) -> list[str]:
    chunks, cur, cur_words = [], [], 0
    for p in paragraphs:
        w = len(p.split())
        if w > 1600:
            if cur:
                chunks.append("\n\n".join(cur))
                cur, cur_words = [], 0
            chunks.extend(split_long_paragraph(p, target))
            continue
        if cur and cur_words + w > target:
            chunks.append("\n\n".join(cur))
            cur, cur_words = [], 0
        cur.append(p)
        cur_words += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pages", default="")
    args = ap.parse_args()

    import pymupdf  # PyMuPDF

    doc = pymupdf.open(args.pdf)
    total = doc.page_count
    pages = parse_pages(args.pages, total)
    title = (doc.metadata or {}).get("title") or ""

    with tempfile.TemporaryDirectory() as tmpdir:
        target = args.pdf
        if len(pages) != total:
            target = os.path.join(tmpdir, "subset.pdf")
            sub = pymupdf.open()
            for p in pages:
                sub.insert_pdf(doc, from_page=p, to_page=p)
            sub.save(target)
            sub.close()
        ocr_pages = run_ocr(target, tmpdir)

    pages_lines = [[l.get("text", "") for l in pg.get("lines", [])]
                   for pg in ocr_pages]
    pages_lines = drop_furniture(pages_lines)
    paragraphs = build_paragraphs(pages_lines)
    texts = chunk(paragraphs)

    os.makedirs(args.outdir, exist_ok=True)
    chunks_meta = []
    for i, t in enumerate(texts, 1):
        path = os.path.join(args.outdir, f"chunk-{i:03d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(t)
        chunks_meta.append({"path": os.path.abspath(path),
                            "words": len(t.split())})

    if not title and paragraphs:
        title = paragraphs[0][:80]
    manifest = {
        "chunks": chunks_meta,
        "total_pages": total,
        "pages_used": pages_label(pages, total),
        "title": title,
        "is_scanned": False,
    }
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
