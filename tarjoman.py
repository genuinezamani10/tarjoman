#!/usr/bin/env python3
"""
ترجمان — Tarjoman (نسخهٔ مستقل با API)

ترجمهٔ PDF به فارسی بدون نیاز به هیچ محیط خاصی: اسکریپت را با کلید API خودتان
(هر سرویس سازگار با OpenAI — مثل OpenRouter، OpenAI، Gemini یا حتی یک مدل
لوکال مثل Ollama/LM Studio) اجرا کنید.

    cp .env.example .env        # کلید و مدل را داخلش بگذارید
    python3 tarjoman.py book.pdf --mode novel
    python3 tarjoman.py paper.pdf                 # پیش‌فرض: article
    python3 tarjoman.py lesson.pdf --mode textbook --pages 1-10

خروجی: فایل Markdown + PDF فارسی راست‌به‌چپ (فونت وزیرمتن) در پوشهٔ خروجی.
PDF اسکن‌شده هم پشتیبانی می‌شود: OCR کاملاً لوکال با Indra انجام می‌شود و
فقط متن استخراج‌شده برای ترجمه به API می‌رود.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

# ───────────────────────── پیکربندی ─────────────────────────

def load_env_file():
    for cand in (os.path.join(os.getcwd(), ".env"), os.path.join(HERE, ".env")):
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            return cand
    return None


def cfg(name, flag=None, default=None):
    return flag or os.environ.get(name) or default


# ───────────────────────── دستورهای سه حالت ─────────────────────────

MODE_INSTRUCTIONS = {
    "article": (
        "حالت مقاله: این یک متن آکادمیک/علمی است.\n"
        "- ترجمهٔ روان و علمی؛ از ترجمهٔ تحت‌اللفظی پرهیز کن — جمله‌ها را به فارسی طبیعی بازنویسی کن، نه کلمه‌به‌کلمه.\n"
        "- معادل انگلیسی هر اصطلاح را فقط در نخستین کاربرد آن اصطلاح داخل پرانتز بیاور؛ در تکرارهای بعدی فقط معادل فارسی.\n"
        "- لحن رسمی و علمی؛ دقت مقدم بر روانی، ولی معنا تحریف نشود."
    ),
    "textbook": (
        "حالت درسی: این یک متن آموزشی است.\n"
        "- فرمول‌ها، کدها، نام متغیرها، نمادها و عددها دقیقاً دست نخورده بمانند؛ اگر در منبع به‌هم‌ریخته‌اند همان را عیناً منتقل کن و بازسازی نکن.\n"
        "- توضیحات به فارسی روان و آموزشی؛ ساختار مثال‌ها و تمرین‌ها حفظ شود."
    ),
    "novel": (
        "حالت رمان: این یک متن داستانی است؛ ترجمه‌ی ادبی و روان انجام بده.\n"
        "- دیالوگ‌ها طبیعی و زنده باشند، نه خشک و کتابی.\n"
        "- حس و حال صحنه‌ها حفظ شود؛ ترجمه‌ی تحت‌اللفظی ممنوع."
    ),
}

STYLE_FILES = {
    "article": ["tarjoman-article-style.md"],
    "textbook": [],
    "novel": ["style-guide-novel.md", "tarjoman-novel-glossary.md"],
}


def read_style(mode: str, style_sample: str | None) -> str:
    parts = []
    for name in STYLE_FILES.get(mode, []):
        path = os.path.join(HERE, "styles", name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                parts.append(f.read())
    if style_sample:
        with open(style_sample, encoding="utf-8") as f:
            parts.append(
                "نمونه‌ی نثر دلخواه کاربر — لحن، دایره‌ی واژگان، ریتم جمله‌ها و سبک "
                "دیالوگ‌ها را از این نمونه بگیر و در سراسر ترجمه رعایت کن:\n" + f.read()
            )
    return "\n\n".join(parts)


# ───────────────────────── کلاینت API ─────────────────────────

class Api:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.model = model

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }).encode("utf-8")
        last_err = None
        for attempt in range(3):
            req = urllib.request.Request(
                self.base + "/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.key,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last_err = f"HTTP {e.code}: {detail}"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:  # خطای شبکه و ...
                last_err = str(e)
            time.sleep(2 ** attempt * 3)
        raise RuntimeError("خطای API: " + str(last_err))


# ───────────────────────── مراحل خط لوله ─────────────────────────

def get_chunks(pdf: str, pages: str, mode: str, workdir: str):
    """استخراج متن یا (برای اسکن‌شده) OCR لوکال؛ خروجی: فهرست متن تکه‌ها."""
    import extract_text

    res = extract_text.extract(pdf, pages, mode == "textbook")
    if not res["is_scanned"]:
        from ocr_extract import chunk
        return chunk(res["paragraphs"]), res

    print("📄 PDF اسکن‌شده است؛ OCR لوکال (Indra) اجرا می‌شود...")
    import ocr_extract

    ocr_pages = ocr_extract.run_ocr(pdf, workdir)
    pages_lines = [[l.get("text", "") for l in pg.get("lines", [])]
                   for pg in ocr_pages]
    pages_lines = ocr_extract.drop_furniture(pages_lines)
    paragraphs = ocr_extract.build_paragraphs(pages_lines)
    from ocr_extract import chunk
    return chunk(paragraphs), res


def build_glossary(api: Api, chunks: list[str], mode: str) -> str:
    if not chunks:
        return ""
    idx = sorted({0, len(chunks) // 4, len(chunks) // 2,
                  3 * len(chunks) // 4, len(chunks) - 1})
    samples = "\n\n---\n\n".join(chunks[i][:3500] for i in idx)
    if mode == "novel":
        ask = ("از نمونه‌های زیرِ یک متن داستانی، نام شخصیت‌ها، لقب‌ها، نام مکان‌ها "
               "و اصطلاحات تکرارشونده‌ی داستان را استخراج کن و برای هر کدام معادل "
               "فارسی پیشنهادی‌ات را بنویس (هر مورد یک خط: اصل = معادل).")
    else:
        ask = ("از نمونه‌های زیر، حدود ۴۰ اصطلاح تخصصی کلیدی و تکرارشونده را استخراج "
               "کن و برای هر کدام معادل فارسی پیشنهادی‌ات را بنویس "
               "(هر مورد یک خط: اصل = معادل).")
    try:
        return api.chat("تو یک واژه‌نامه‌ساز برای پروژه‌ی ترجمه به فارسی هستی.", 
                        ask + "\n\n" + samples)
    except Exception as e:
        print("⚠️ ساخت واژه‌نامه ناموفق بود (" + str(e) + ")؛ بدون واژه‌نامه ادامه می‌دهیم.")
        return ""


def translate_all(api: Api, chunks: list[str], mode: str,
                  style_text: str, glossary: str):
    system = (
        "تو یک مترجم حرفه‌ای به فارسی هستی. متن داده‌شده را کامل و جمله‌به‌جمله "
        "به فارسی ترجمه کن؛ هیچ بخشی را خلاصه، حذف یا اضافه نکن. فقط خودِ ترجمه "
        "را برگردان، بدون هیچ توضیح یا مقدمه‌ای.\n\n"
        + MODE_INSTRUCTIONS[mode]
        + (("\n\nراهنمای سبک و واژگان ترجیحی:\n" + style_text) if style_text else "")
        + (("\n\nواژه‌نامهٔ مشترک این سند (معادل‌هایش را یکدست رعایت کن):\n" + glossary)
           if glossary else "")
    )
    translated, suspicious, failed = [], [], []
    for i, ch in enumerate(chunks, 1):
        src_words = len(ch.split())
        print(f"✏️  ترجمهٔ تکهٔ {i} از {len(chunks)} ({src_words} کلمه)...")
        try:
            out = api.chat(system, ch)
        except Exception as e:
            print("❌ تکهٔ " + str(i) + " ناموفق: " + str(e))
            failed.append(i)
            translated.append(f"[ترجمهٔ این تکه ناموفق بود — تکهٔ {i} از متن اصلی]")
            continue
        ratio = (len(out.split()) / src_words) if src_words else 0
        if ratio < 0.45 or ratio > 1.9:
            print(f"⚠️ نسبت کلمات تکهٔ {i} غیرعادی است ({ratio:.2f})؛ تلاش مجدد...")
            try:
                out2 = api.chat(system, ch + "\n\n(تذکر: ترجمهٔ قبلی از نظر حجم "
                                "غیرعادی بود؛ این بار کامل و بدون خلاصه‌سازی ترجمه کن.)")
                ratio2 = (len(out2.split()) / src_words) if src_words else 0
                if 0.45 <= ratio2 <= 1.9:
                    out = out2
                else:
                    suspicious.append(i)
            except Exception:
                suspicious.append(i)
        translated.append(out)
    return translated, suspicious, failed


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ترجمان — ترجمهٔ PDF به فارسی با API خودتان")
    ap.add_argument("pdf")
    ap.add_argument("--mode", choices=["article", "textbook", "novel"],
                    default="article")
    ap.add_argument("--pages", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--outdir", default="")
    ap.add_argument("--style-sample", default="")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    load_env_file()
    base_url = cfg("TARJOMAN_BASE_URL", args.base_url,
                   "https://openrouter.ai/api/v1")
    api_key = cfg("TARJOMAN_API_KEY", args.api_key)
    model = (args.model or os.environ.get("TARJOMAN_MODEL_" + args.mode.upper())
             or os.environ.get("TARJOMAN_MODEL"))
    if not api_key:
        print("⛔ کلید API پیدا نشد. یکی از این کارها را بکنید:\n"
              "   • فایل .env بسازید (از روی .env.example) و TARJOMAN_API_KEY را داخلش بگذارید\n"
              "   • یا اجرا کنید: TARJOMAN_API_KEY=... python3 tarjoman.py ...\n"
              "   • یا فلگ --api-key بدهید.\n"
              "برای مدل لوکال (Ollama) کلید لازم نیست؛ هر رشته‌ای بگذارید کافی است.")
        sys.exit(2)
    if not model:
        print("⛔ مدل مشخص نشده است. در .env مقدار TARJOMAN_MODEL را بگذارید "
              "(مثلاً برای OpenRouter: google/gemini-2.5-flash) یا --model بدهید.")
        sys.exit(2)

    name = os.path.splitext(os.path.basename(args.pdf))[0]
    outdir = args.outdir or os.path.join(HERE, "output", name)
    workdir = os.path.join(outdir, "work")
    os.makedirs(workdir, exist_ok=True)

    print(f"🚀 ترجمان شروع شد — حالت: {args.mode} | مدل: {model}")
    chunks, meta = get_chunks(args.pdf, args.pages, args.mode, workdir)
    if not chunks:
        print("⛔ متنی برای ترجمه به دست نیامد (PDF خالی یا اسکن ناخوانا).")
        sys.exit(1)
    title = args.title or meta.get("title") or name
    print(f"📚 {len(chunks)} تکه آماده شد. ساخت واژه‌نامهٔ زنده...")
    api = Api(base_url, api_key, model)
    glossary = build_glossary(api, chunks, args.mode)
    style_text = read_style(args.mode, args.style_sample or None)
    translated, suspicious, failed = translate_all(
        api, chunks, args.mode, style_text, glossary)

    md = "# " + title + "\n\n" + "\n\n".join(translated) + "\n"
    md_path = os.path.join(outdir, name + ".fa.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    total_out = sum(len(t.split()) for t in translated)
    print(f"🧮 کنترل تمامیت: {total_out} کلمه در خروجی نهایی.")
    if suspicious:
        print("⚠️ تکه‌های مشکوک (نسبت کلمات غیرعادی): " + "، ".join(map(str, suspicious)))
    if failed:
        print("⚠️ تکه‌های ناموفق: " + "، ".join(map(str, failed)))

    pdf_path = None
    if not args.no_pdf:
        try:
            import build_pdf
            pdf_path = os.path.join(outdir, name + ".fa.pdf")
            build_pdf.build_pdf(title, translated, pdf_path)
        except Exception as e:
            print("⚠️ ساخت PDF ناموفق بود (" + str(e) + ")؛ Markdown آماده است.")
    print("✅ تمام شد!")
    print("   Markdown: " + md_path)
    if pdf_path:
        print("   PDF: " + pdf_path)


if __name__ == "__main__":
    main()
