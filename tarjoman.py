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

امکانات مهم:
  • چک‌پوینت: هر تکه در work/chunk_0001.json ذخیره می‌شود؛ اجرای بعدی تکه‌های
    موفق را رد می‌کند. با --retry-failed تکه‌های ناموفق/مشکوک دوباره زده می‌شوند.
    هر رکورد هش متن منبع و حالت را دارد؛ اگر PDF، بازهٔ صفحات، --chunk-words
    یا --mode عوض شود، رکورد قدیمی معتبر نیست و آن تکه از نو ترجمه می‌شود.
    (رکوردهای ساخته‌شده با نسخهٔ قدیمی هش ندارند؛ با --trust-old-checkpoints
    همان‌ها را بپذیرید.) نوشتن رکوردها اتمیک است و قطع ناگهانی چیزی را خراب
    نمی‌کند.
  • واژه‌نامه: در work/glossary.txt ذخیره و قابل ویرایش دستی است؛ با --glossary
    مسیر دیگری بدهید و با --regen-glossary از نو بسازید.
  • زمینهٔ تکهٔ قبل (در حالت ترتیبی): دو پاراگراف آخر تکهٔ قبل (متن اصلی + ترجمه)
    به‌عنوان «زمینه، ترجمه نکن» به پرامپت اضافه می‌شود.
  • موازی‌سازی: برای article و textbook پیش‌فرض ۴ worker؛ برای novel ترتیبی (۱).
  • کنترل کیفیت: نسبت کلمات (به‌جز textbook که فرمول/کد دارد)، سهم حروف فارسی،
    تشخیص قطع شدن خروجی (finish_reason=length) و کنترل عددها (textbook و
    article: عددهای مهم متن اصلی باید در ترجمه باقی بمانند) با تلاش مجدد.
  • حالت article: معادل انگلیسی هر اصطلاح فقط در نخستین کاربرد داخل پرانتز
    می‌ماند (پاس قطعی بعد از ترجمه؛ با --no-dedupe-terms خاموش می‌شود).
  • پاس دوم ویرایش فارسی با --polish (اختیاری، بیشتر برای رمان). خروجی ویرایش
    فقط در صورت تأیید (کامل، هم‌طول، فارسی، با عددها و پاراگراف‌های سالم)
    جایگزین ترجمهٔ اول می‌شود؛ وگرنه ترجمهٔ اول می‌ماند و دلیل در رکورد ثبت
    می‌شود. نسخهٔ ویراسته‌شده در حالت ترتیبی زمینهٔ تکهٔ بعد هم هست. اگر بعداً
    با --polish اجرا کنی، تکه‌های سالمِ بدون ویرایش هم ویرایش می‌شوند.
  • PDF اسکن‌شده: OCR فقط روی صفحاتِ --pages انجام می‌شود (مثلاً 2-4,8,11-13) و
    نتیجه در work/ocr_pages.json کش می‌شود؛ اجرای دوباره OCR را تکرار نمی‌کند.
  • سبک رمان سه‌لایه است: هستهٔ مشترک ضدماشینی + پروفایل (--style-profile:
    modern-colloquial پیش‌فرض، romance-urban، literary-fable، legacy) + واژه‌نامهٔ
    کتاب (--glossary styles/books/...). پروفایل در چک‌پوینت ثبت می‌شود و تکه‌های
    با پروفایل دیگر از نو ترجمه می‌شوند. جزئیات: styles/README.md

نکته برای مدل لوکال (Ollama): چون Api سازگار با OpenAI است همین کد کار می‌کند؛
برای مدل‌های کوچک تکه‌ها را کوچک‌تر کنید (--chunk-words 600) و کنترل کیفیت را
شل‌تر (--qc-loose).
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

import tj_checks as tjc  # noqa: E402

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
}

# رمان: هستهٔ مشترک + پروفایل سبک (انتخاب با --style-profile). ساختار: styles/README.md
NOVEL_CORE = ["novel-core.md"]
NOVEL_PROFILES = {
    "modern-colloquial": ["profile-modern-colloquial.md"],
    "romance-urban": ["profile-modern-colloquial.md", "profile-romance-urban.md"],
    "literary-fable": ["profile-literary-fable.md"],
}
NOVEL_LEGACY = ["style-guide-novel.md", "tarjoman-novel-glossary.md"]
DEFAULT_NOVEL_PROFILE = "modern-colloquial"
STYLE_PROFILE_CHOICES = [*NOVEL_PROFILES, "legacy"]


def resolve_style(mode: str, profile: str = "") -> tuple[str, list[str]]:
    """(شناسهٔ سبک، فهرست فایل‌های styles/). شناسه در چک‌پوینت ثبت می‌شود؛
    برای article و textbook خالی است."""
    if mode != "novel":
        return "", list(STYLE_FILES.get(mode, []))
    profile = profile or DEFAULT_NOVEL_PROFILE
    if profile == "legacy":
        return "legacy", list(NOVEL_LEGACY)
    if profile not in NOVEL_PROFILES:
        raise SystemExit("⛔ پروفایل سبک ناشناخته: " + profile + " — گزینه‌ها: "
                         + "، ".join(STYLE_PROFILE_CHOICES))
    return profile, NOVEL_CORE + NOVEL_PROFILES[profile]


def read_style(mode: str, style_sample: str | None, profile: str = "") -> str:
    parts = []
    _, names = resolve_style(mode, profile)
    for name in names:
        path = os.path.join(HERE, "styles", name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                parts.append(f.read())
        elif mode == "novel":
            raise SystemExit(f"⛔ فایل سبک رمان پیدا نشد: {path}\n"
                             f"   پوشهٔ styles/ را کامل کنار tarjoman.py بگذار، یا با "
                             f"--style-profile legacy به دو فایل قدیمی برگرد.")
        else:
            print(f"⚠️ فایل سبک پیدا نشد و رد شد: {path}")
    if style_sample:
        with open(style_sample, encoding="utf-8") as f:
            parts.append(
                "نمونه‌ی نثر دلخواه کاربر — لحن، دایره‌ی واژگان، ریتم جمله‌ها و سبک "
                "دیالوگ‌ها را از این نمونه بگیر و در سراسر ترجمه رعایت کن:\n" + f.read()
            )
    return "\n\n".join(parts)


# ───────────────────────── کنترل کیفیت ─────────────────────────

RATIO_MIN, RATIO_MAX = 0.45, 1.9            # بازهٔ عادی نسبت کلمات
RATIO_MIN_LOOSE, RATIO_MAX_LOOSE = 0.35, 2.2  # برای مدل‌های کوچک لوکال
FA_MIN = {"article": 0.5, "novel": 0.5, "textbook": 0.2}
FA_MIN_LOOSE = {"article": 0.35, "novel": 0.35, "textbook": 0.15}
_FA_RANGES = [("\u0600", "\u06FF"), ("\uFB50", "\uFDFF"), ("\uFE70", "\uFEFF")]


def fa_ratio(text: str) -> float:
    """سهم حروف فارسی از کل حروف خروجی (۰ تا ۱)."""
    if not text:
        return 0.0
    fa = sum(1 for c in text
             if any(lo <= c <= hi for lo, hi in _FA_RANGES))
    letters = sum(1 for c in text if c.isalpha())
    return (fa / letters) if letters else 0.0


def check_quality(out: str, src_text: str, mode: str, o) -> str:
    """بررسی کیفیت یک تکه؛ خروجی: رشتهٔ خالی یعنی سالم، وگرنه شرح مشکل."""
    notes = []
    src_words = len(src_text.split())
    # نسبت کلمات برای textbook معتبر نیست (فرمول‌ها و کدها لاتین‌اند)
    if mode != "textbook":
        rmin, rmax = ((RATIO_MIN_LOOSE, RATIO_MAX_LOOSE) if o.qc_loose
                      else (RATIO_MIN, RATIO_MAX))
        ratio = (len(out.split()) / src_words) if src_words else 0
        if ratio < rmin or ratio > rmax:
            notes.append(f"نسبت کلمات غیرعادی ({ratio:.2f})")
    fa_min = (FA_MIN_LOOSE if o.qc_loose else FA_MIN)[mode]
    fr = fa_ratio(out)
    if fr < fa_min:
        notes.append(f"سهم حروف فارسی کم ({fr:.0%}) — احتمال ترجمه‌نشدن")
    # عددهای مهم متن اصلی باید در ترجمه مانده باشند (textbook و article)
    num_note = tjc.check_numbers(src_text, out, mode, loose=o.qc_loose)
    if num_note:
        notes.append(num_note)
    return "؛ ".join(notes)


def _tail_paras(text: str, n: int = 2) -> str:
    ps = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    return "\n\n".join(ps[-n:])


# ───────────────────────── کلاینت API ─────────────────────────

class Api:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.model = model
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0}
        self._usage_lock = threading.Lock()  # چند worker یک شیء Api را مشترک دارند

    def add_usage(self, usage: dict) -> None:
        """جمع مصرف توکن؛ thread-safe."""
        with self._usage_lock:
            for k in self.total_usage:
                self.total_usage[k] += (usage or {}).get(k, 0) or 0

    def chat(self, system: str, user: str, temperature: float = 0.3,
             max_tokens: int = 8192) -> dict:
        """خروجی: {"content", "finish_reason", "usage"} — با رعایت Retry-After."""
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        last_err = None
        for attempt in range(4):
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
                choice = data["choices"][0]
                content = (choice["message"].get("content") or "").strip()
                usage = data.get("usage") or {}
                self.add_usage(usage)
                return {"content": content,
                        "finish_reason": choice.get("finish_reason"),
                        "usage": usage}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last_err = f"HTTP {e.code}: {detail}"
                if e.code == 429:
                    ra = e.headers.get("Retry-After")
                    wait = min(int(ra), 120) if ra and ra.isdigit() else 2 ** attempt * 3
                    print(f"⏳ محدودیت نرخ (429)؛ {wait} ثانیه صبر...")
                    time.sleep(wait)
                    continue
                if e.code not in (500, 502, 503, 504):
                    break
            except Exception as e:  # خطای شبکه و ...
                last_err = str(e)
            time.sleep(2 ** attempt * 3)
        raise RuntimeError("خطای API: " + str(last_err))


# ───────────────────────── مراحل خط لوله ─────────────────────────

def ocr_selected_pages(pdf: str, pages: str, workdir: str) -> list:
    """
    OCR لوکال فقط روی صفحات انتخابی (--pages)، با کش در work/ocr_pages.json.

    اگر فقط بخشی از صفحات خواسته شده باشد، با PyMuPDF یک PDF موقت (work/ocr_input.pdf)
    از همان صفحات به‌ترتیب صعودی ساخته و فقط همان به Indra داده می‌شود؛ پس
    هزینه و زمان OCR کل کتاب پرداخت نمی‌شود. کلید کش: نام/حجم/زمان تغییر فایل + --pages.
    """
    import ocr_extract

    st = os.stat(pdf)
    key = {"pdf": os.path.basename(pdf), "size": st.st_size,
           "mtime": int(st.st_mtime), "pages": (pages or "").replace(" ", "")}
    cache = os.path.join(workdir, "ocr_pages.json")
    if os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("key") == key and c.get("pages_data"):
                print("📄 نتیجهٔ OCR از کش خوانده شد (OCR دوباره اجرا نمی‌شود).")
                return c["pages_data"]
        except Exception:
            pass  # کش خراب است؛ OCR از نو

    import pymupdf

    doc = pymupdf.open(pdf)
    total = doc.page_count
    selected = ocr_extract.parse_pages(pages, total)
    if not selected:
        doc.close()
        print(f"⛔ بازهٔ صفحات «{pages}» با هیچ صفحه‌ای از این PDF ({total} صفحه) نمی‌خواند.")
        sys.exit(1)
    target = pdf
    if len(selected) != total:
        target = os.path.join(workdir, "ocr_input.pdf")
        sub = pymupdf.open()
        for p in selected:
            sub.insert_pdf(doc, from_page=p, to_page=p)
        sub.save(target)
        sub.close()
        print(f"📄 فقط {len(selected)} از {total} صفحه به OCR داده می‌شود.")
    doc.close()

    # خروجی‌های یک اجرای قبلی (با صفحات دیگر) نباید با این اجرا قاطی شوند
    shutil.rmtree(os.path.join(workdir, "indra-out"), ignore_errors=True)
    ocr_pages = ocr_extract.run_ocr(target, workdir)
    tjc.atomic_write_text(cache, json.dumps(
        {"key": key, "pages_data": ocr_pages}, ensure_ascii=False))
    return ocr_pages


def get_chunks(pdf: str, pages: str, mode: str, workdir: str, chunk_words: int):
    """استخراج متن یا (برای اسکن‌شده) OCR لوکال؛ خروجی: فهرست متن تکه‌ها."""
    import extract_text

    res = extract_text.extract(pdf, pages, mode == "textbook")
    if not res["is_scanned"]:
        from ocr_extract import chunk
        return chunk(res["paragraphs"], target=chunk_words), res

    print("📄 PDF اسکن‌شده است؛ OCR لوکال (Indra) اجرا می‌شود...")
    import ocr_extract

    ocr_pages = ocr_selected_pages(pdf, pages, workdir)
    pages_lines = [[l.get("text", "") for l in pg.get("lines", [])]
                   for pg in ocr_pages]
    pages_lines = ocr_extract.drop_furniture(pages_lines)
    paragraphs = ocr_extract.build_paragraphs(pages_lines)
    from ocr_extract import chunk
    return chunk(paragraphs, target=chunk_words), res


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
                        ask + "\n\n" + samples)["content"]
    except Exception as e:
        print("⚠️ ساخت واژه‌نامه ناموفق بود (" + str(e) + ")؛ بدون واژه‌نامه ادامه می‌دهیم.")
        return ""


def get_glossary(api: Api, chunks: list[str], mode: str, workdir: str,
                 glossary_arg: str, regen: bool) -> tuple[str, str]:
    """خواندن واژه‌نامه از فایل (اگر هست) وگرنه ساخت و ذخیرهٔ آن."""
    path = glossary_arg or os.path.join(workdir, "glossary.txt")
    if os.path.isfile(path) and not regen:
        with open(path, encoding="utf-8") as f:
            g = "\n".join(ln for ln in f.read().splitlines()
                          if ln.strip() and not ln.lstrip().startswith("#")).strip()
        print(f"📖 واژه‌نامه از {path} خوانده شد ({len(g.splitlines())} مورد).")
        return g, path
    g = build_glossary(api, chunks, mode)
    if g:
        tjc.atomic_write_text(path, g + "\n")
        print(f"📖 واژه‌نامه در {path} ذخیره شد — می‌توانید دستی ویرایشش کنید "
              f"و برای رمان‌های بلند، نام‌های تازه را به آن اضافه کنید.")
    return g, path


# ───────────────────────── چک‌پوینت تکه‌ها ─────────────────────────

def chunk_path(workdir: str, idx: int) -> str:
    return os.path.join(workdir, f"chunk_{idx:04d}.json")


def load_record(workdir: str, idx: int):
    p = chunk_path(workdir, idx)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_record(workdir: str, idx: int, rec: dict):
    tjc.atomic_write_text(chunk_path(workdir, idx),
                          json.dumps(rec, ensure_ascii=False, indent=1))


def _checkpoint_decision(rec, expected_hash: str, retry_failed: bool,
                         trust_old: bool, style_id: str = "") -> str:
    """
    تصمیم دربارهٔ یک رکورد چک‌پوینت:
      "use"            رکورد معتبر است و استفاده می‌شود
      "run"            رکوردی نیست یا ناموفق است؛ باید ترجمه شود
      "stale-nohash"   رکورد قدیمی (بدون هش منبع)؛ از نو ترجمه می‌شود
      "stale-changed"  متن منبع یا حالت فرق کرده؛ از نو ترجمه می‌شود
      "stale-style"    پروفایل سبکِ ثبت‌شده در رکورد با پروفایل فعلی فرق دارد؛
                       از نو ترجمه می‌شود (رکوردِ بدون ثبت سبک معتبر می‌ماند)
    مشکوک‌ها فقط با --retry-failed دوباره زده می‌شوند؛ ناموفق‌ها همیشه.
    """
    if not rec:
        return "run"
    status = rec.get("status")
    if status not in ("ok", "suspicious"):
        return "run"
    h = rec.get("src_hash")
    if h is None:
        if not trust_old:
            return "stale-nohash"
    elif h != expected_hash:
        return "stale-changed"
    rec_style = rec.get("style")
    if rec_style is not None and rec_style != style_id:
        return "stale-style"
    if status == "ok" or not retry_failed:
        return "use"
    return "run"


def build_system(mode: str, style_text: str, glossary: str) -> str:
    return (
        "تو یک مترجم حرفه‌ای به فارسی هستی. متن داده‌شده را کامل و جمله‌به‌جمله "
        "به فارسی ترجمه کن؛ هیچ بخشی را خلاصه، حذف یا اضافه نکن. فقط خودِ ترجمه "
        "را برگردان، بدون هیچ توضیح یا مقدمه‌ای.\n\n"
        + MODE_INSTRUCTIONS[mode]
        + (("\n\nراهنمای سبک و واژگان ترجیحی:\n" + style_text) if style_text else "")
        + (("\n\nواژه‌نامهٔ مشترک این سند (معادل‌هایش را یکدست رعایت کن):\n" + glossary)
           if glossary else "")
    )


def _best(rec) -> str:
    """بهترین متن پذیرفته‌شدهٔ یک تکه: ویراسته‌ی تأییدشده، وگرنه ترجمهٔ اول."""
    return (rec or {}).get("polished") or (rec or {}).get("translation") or ""


def polish_one(api: Api, translation: str, o):
    """
    پاس دوم: روان‌سازی فارسی و یکدستی نام‌ها (اختیاری).
    خروجی: (متن ویراسته یا None، دلیل رد یا None).
      • خطای API:   (None, None)  — دلیلی ثبت نمی‌شود تا اجرای بعدی دوباره تلاش کند
      • رد شدن:     (None, "دلیل") — ترجمهٔ اول می‌ماند و دلیل در رکورد ثبت می‌شود
      • تأیید شد:   (متن، None)
    """
    sys_p = (
        "تو یک ویراستار حرفه‌ای زبان فارسی هستی. متن فارسی زیر را فقط از نظر "
        "روانی و درستی زبان ویرایش کن: جمله‌های خشک را طبیعی کن و نام‌ها و "
        "اصطلاحات را طبق واژه‌نامه یکدست کن. معنا، ترتیب و محتوای متن را هیچ "
        "تغییری نده؛ چیزی اضافه یا حذف نکن. فقط متن ویراسته را برگردان، بدون "
        "هیچ توضیحی."
        + (("\n\nواژه‌نامه:\n" + o.glossary_text) if o.glossary_text else "")
    )
    model = o.polish_model or api.model
    api2 = api if model == api.model else Api(api.base, api.key, model)
    try:
        r = api2.chat(sys_p, translation, temperature=0.2,
                      max_tokens=o.max_tokens)
        if api2 is not api:  # مصرف توکن مدل دوم را هم جمع بزن
            api.add_usage(r["usage"])
    except Exception as e:
        print("⚠️ پاس ویرایش ناموفق بود (" + str(e) + ")؛ همان ترجمهٔ اول می‌ماند.")
        return None, None
    reason = tjc.check_polish(translation, r["content"], r.get("finish_reason"))
    if reason:
        print(f"⚠️ خروجی ویرایش پذیرفته نشد ({reason})؛ ترجمهٔ اول می‌ماند.")
        return None, reason
    return r["content"], None


def _apply_polish(api: Api, idx: int, rec: dict, o) -> None:
    """ویرایش رکورد (در جا). فقط نتیجهٔ تأییدشده در rec["polished"] می‌نشیند."""
    print(f"✨ پاس ویرایش تکهٔ {idx}...")
    text, reason = polish_one(api, rec.get("translation") or "", o)
    if text:
        rec["polished"] = text
        rec.pop("polish_reason", None)
    elif reason:  # ردشده؛ دلیلش ثبت می‌شود. خطای API دلیلی ثبت نمی‌کند (بار بعد دوباره)
        rec["polished"] = None
        rec["polish_reason"] = reason


def _needs_polish(rec, retry_failed: bool) -> bool:
    """تکهٔ سالمی که هنوز ویراسته نشده (یا ردشده و --retry-failed داده شده)."""
    if not rec or rec.get("status") != "ok" or rec.get("polished"):
        return False
    return retry_failed or not rec.get("polish_reason")


def translate_one(api: Api, idx: int, ch: str, mode: str, system_base: str,
                  workdir: str, o, prev=None) -> dict:
    """ترجمهٔ یک تکه + کنترل کیفیت + چک‌پوینت. خروجی: رکورد تکه."""
    src_words = len(ch.split())
    user_prompt = ch
    if prev and prev[0]:
        user_prompt = (
            "زمینهٔ تکهٔ قبلی (فقط برای حفظ لحن، ضمیرها و ارجاع‌ها — این بخش را "
            "ترجمه نکن):\n\n[متن اصلی تکهٔ قبلی — دو پاراگراف آخر]\n"
            + prev[0] +
            "\n\n[ترجمهٔ فارسی تکهٔ قبلی — دو پاراگراف آخر]\n"
            + prev[1] +
            "\n\n---\n\nمتن تکهٔ جاری — فقط همین را ترجمه کن:\n\n" + ch
        )
    rec = {"index": idx, "src_hash": tjc.src_hash(ch, mode),
           "style": getattr(o, "style_id", ""),
           "src_words": src_words, "status": "failed",
           "translation": "", "polished": None, "attempts": 0,
           "finish_reason": None, "word_ratio": 0.0, "fa_ratio": 0.0,
           "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
           "error": None}

    def _add_usage(u):
        for k in rec["usage"]:
            rec["usage"][k] += (u.get(k, 0) or 0)

    try:
        r = api.chat(system_base, user_prompt, max_tokens=o.max_tokens)
        rec["attempts"] += 1
        _add_usage(r["usage"])
        out, fr = r["content"], r["finish_reason"]
        rec["finish_reason"] = fr
        # ۴. اگر خروجی وسط جمله قطع شده (length)، با max_tokens بیشتر تلاش مجدد
        if fr == "length":
            print(f"✂️ تکهٔ {idx}: خروجی ناقص قطع شد؛ تلاش مجدد با max_tokens بیشتر...")
            r = api.chat(system_base, user_prompt,
                         max_tokens=min(o.max_tokens * 2, 32768))
            rec["attempts"] += 1
            _add_usage(r["usage"])
            out, fr = r["content"], r["finish_reason"]
            rec["finish_reason"] = fr
        problems = check_quality(out, ch, mode, o)
        if problems or fr == "length":
            if fr != "length":  # برای length همان تلاش مجدد بالا کافی است
                print(f"⚠️ تکهٔ {idx}: {problems}؛ تلاش مجدد...")
                hint = user_prompt + ("\n\n(تذکر: خروجی قبلی مشکل داشت — "
                                      + problems +
                                      "؛ این بار کامل و بدون خلاصه‌سازی ترجمه کن.)")
                r = api.chat(system_base, hint, max_tokens=o.max_tokens)
                rec["attempts"] += 1
                _add_usage(r["usage"])
                out2, fr2 = r["content"], r["finish_reason"]
                problems2 = check_quality(out2, ch, mode, o)
                if not problems2 and fr2 != "length":
                    out, fr, problems = out2, fr2, ""
                else:
                    problems = problems2 or problems
            rec["finish_reason"] = fr
        rec["translation"] = out
        rec["word_ratio"] = (len(out.split()) / src_words) if src_words else 0
        rec["fa_ratio"] = fa_ratio(out)
        if problems or fr == "length":
            rec["status"] = "suspicious"
            print(f"⚠️ تکهٔ {idx} مشکوک ثبت شد ({problems or 'خروجی ناقص'}).")
        else:
            rec["status"] = "ok"
        if o.polish and rec["status"] == "ok":
            _apply_polish(api, idx, rec, o)
    except Exception as e:
        rec["error"] = str(e)[:300]
        print(f"❌ تکهٔ {idx} ناموفق: {e}")
    save_record(workdir, idx, rec)
    return rec


def translate_all(api: Api, chunks: list[str], mode: str, style_text: str,
                  glossary: str, workdir: str, o) -> list:
    n = len(chunks)
    records: list = [None] * n
    stale = 0
    nohash = 0
    nostyle = 0
    for i in range(n):
        rec = load_record(workdir, i + 1)
        verdict = _checkpoint_decision(
            rec, tjc.src_hash(chunks[i], mode), o.retry_failed,
            o.trust_old_checkpoints, getattr(o, "style_id", ""))
        if verdict == "use":
            records[i] = rec
            if getattr(o, "style_id", "") and rec.get("style") is None:
                nostyle += 1
            print(f"⏭️ تکهٔ {i + 1} از {n} از چک‌پوینت رد شد.")
        elif verdict == "stale-changed":
            stale += 1
            print(f"♻️ تکهٔ {i + 1}: متن منبع یا حالت با چک‌پوینت فرق دارد؛ از نو ترجمه می‌شود.")
        elif verdict == "stale-style":
            stale += 1
            print(f"♻️ تکهٔ {i + 1}: با پروفایل سبک دیگری ترجمه شده بود؛ از نو ترجمه می‌شود.")
        elif verdict == "stale-nohash":
            stale += 1
            nohash += 1
            print(f"♻️ تکهٔ {i + 1}: چک‌پوینت قدیمی است (هش منبع ندارد)؛ از نو ترجمه می‌شود.")
    if stale:
        print(f"⚠️ {stale} تکه از چک‌پوینت نامعتبر بود و از نو ترجمه می‌شود.")
    if nohash:
        print(f"   {nohash} مورد از آن‌ها رکورد قدیمی بدون هش منبع بود؛ اگر مطمئنی متعلق به "
              f"همین PDF و تنظیمات‌اند، با --trust-old-checkpoints بپذیرشان.")
    if o.polish:  # تکه‌های سالمِ چک‌پوینت که هنوز ویرایش نشده‌اند
        pending = [i for i in range(n)
                   if _needs_polish(records[i], o.retry_failed)]

        def _polish_saved(i):
            _apply_polish(api, i + 1, records[i], o)
            save_record(workdir, i + 1, records[i])

        if pending:
            print(f"✨ {len(pending)} تکهٔ سالمِ بدون ویرایش از چک‌پوینت ویرایش می‌شود...")
            if o.workers > 1:
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=o.workers) as ex:
                    list(ex.map(_polish_saved, pending))
            else:
                for i in pending:
                    _polish_saved(i)
    if nostyle:
        print(f"ℹ️ {nostyle} تکهٔ چک‌پوینت پروفایل سبک ثبت نکرده بود و پذیرفته شد؛ "
              f"اگر با سبک دیگری ترجمه شده‌اند، متن ناهمگون می‌شود.")
    todo = [i for i in range(n) if records[i] is None]
    if not todo:
        return records
    system_base = build_system(mode, style_text, glossary)
    print(f"⚙️ حالت اجرا: {'ترتیبی (با زمینهٔ تکهٔ قبل)' if o.workers == 1 else f'موازی با {o.workers} worker'}")
    if o.workers == 1:
        # ترتیبی: زمینهٔ تکهٔ قبل (متن اصلی + ترجمه) در دسترس است
        prev = None
        for i in range(n):
            if records[i] is not None:
                prev = (_tail_paras(chunks[i]),
                        _tail_paras(_best(records[i])))
                continue
            print(f"✏️ ترجمهٔ تکهٔ {i + 1} از {n} ({len(chunks[i].split())} کلمه)...")
            rec = translate_one(api, i + 1, chunks[i], mode, system_base,
                                workdir, o, prev)
            records[i] = rec
            prev = (_tail_paras(chunks[i]),
                    _tail_paras(_best(rec)))
    else:
        # موازی (فقط article/textbook): هر تکه مستقل، بدون زمینهٔ تکهٔ قبل
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=o.workers) as ex:
            futs = {ex.submit(translate_one, api, i + 1, chunks[i], mode,
                              system_base, workdir, o, None): i for i in todo}
            done = 0
            for fut in concurrent.futures.as_completed(futs):
                i = futs[fut]
                done += 1
                print(f"📦 تکهٔ {i + 1} از {n} تمام شد ({done}/{len(todo)}).")
                try:
                    records[i] = fut.result()
                except Exception as e:
                    print(f"❌ خطای worker برای تکهٔ {i + 1}: {e}")
                    records[i] = {"index": i + 1, "status": "failed",
                                  "translation": "", "error": str(e)[:200]}
    return records


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
    ap.add_argument("--style-profile", default="", choices=[""] + STYLE_PROFILE_CHOICES,
                    help="پروفایل سبک رمان (فقط --mode novel): modern-colloquial "
                         "(پیش‌فرض)، romance-urban، literary-fable، "
                         "legacy")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--no-pdf", action="store_true")
    # ── فلگ‌های جدید ──
    ap.add_argument("--retry-failed", action="store_true",
                    help="تلاش مجدد فقط برای تکه‌های ناموفق و مشکوک")
    ap.add_argument("--trust-old-checkpoints", action="store_true",
                    help="رکوردهای چک‌پوینت بدون هش منبع (ساخته‌شده با نسخهٔ قدیمی) "
                         "را معتبر بدان")
    ap.add_argument("--no-dedupe-terms", action="store_true",
                    help="در حالت article، حذف معادل انگلیسیِ تکراری داخل پرانتز را "
                         "خاموش کن")
    ap.add_argument("--glossary", default="",
                    help="مسیر فایل واژه‌نامه (پیش‌فرض: work/glossary.txt)؛ اگر باشد "
                         "خوانده می‌شود وگرنه ساخته و ذخیره می‌شود")
    ap.add_argument("--regen-glossary", action="store_true",
                    help="ساخت دوبارهٔ واژه‌نامه حتی اگر فایلش هست")
    ap.add_argument("--workers", type=int, default=0,
                    help="تعداد worker موازی (پیش‌فرض: رمان ۱، بقیه ۴)")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="سقف توکن خروجی هر درخواست")
    ap.add_argument("--chunk-words", type=int, default=1300,
                    help="اندازهٔ تقریبی هر تکه به کلمه (برای مدل کوچک: ۶۰۰)")
    ap.add_argument("--qc-loose", action="store_true",
                    help="شل‌تر کردن کنترل کیفیت برای مدل‌های کوچک لوکال")
    ap.add_argument("--polish", action="store_true",
                    help="پاس دوم ویرایش فارسی (روان‌سازی + یکدستی نام‌ها)")
    ap.add_argument("--polish-model", default="",
                    help="مدل پاس ویرایش (پیش‌فرض: همان مدل اصلی)")
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
    args.polish_model = (args.polish_model
                         or os.environ.get("TARJOMAN_POLISH_MODEL") or "")
    if args.workers <= 0:
        args.workers = 1 if args.mode == "novel" else 4
    if args.mode == "novel" and args.workers > 1:
        print("⚠️ برای رمان حالت ترتیبی توصیه می‌شود (زمینهٔ تکهٔ قبل)؛ "
              "با --workers 1 ترتیبی می‌شود.")

    name = os.path.splitext(os.path.basename(args.pdf))[0]
    outdir = args.outdir or os.path.join(HERE, "output", name)
    workdir = os.path.join(outdir, "work")
    os.makedirs(workdir, exist_ok=True)

    print(f"🚀 ترجمان شروع شد — حالت: {args.mode} | مدل: {model} | "
          f"تکه: ~{args.chunk_words} کلمه")
    args.style_id, style_files = resolve_style(args.mode, args.style_profile)
    if args.style_profile and args.mode != "novel":
        print("⚠️ --style-profile فقط برای --mode novel است؛ نادیده گرفته شد.")
    if style_files:
        print("🎨 سبک: " + " + ".join(style_files))
    chunks, meta = get_chunks(args.pdf, args.pages, args.mode, workdir,
                              args.chunk_words)
    if not chunks:
        print("⛔ متنی برای ترجمه به دست نیامد (PDF خالی یا اسکن ناخوانا).")
        sys.exit(1)
    title = args.title or meta.get("title") or name
    print(f"📚 {len(chunks)} تکه آماده شد. واژه‌نامه...")
    api = Api(base_url, api_key, model)
    glossary, glossary_path = get_glossary(api, chunks, args.mode, workdir,
                                           args.glossary, args.regen_glossary)
    args.glossary_text = glossary
    style_text = read_style(args.mode, args.style_sample or None,
                            args.style_profile)
    records = translate_all(api, chunks, args.mode, style_text, glossary,
                            workdir, args)

    final, suspicious, failed = [], [], []
    for i, rec in enumerate(records, 1):
        if rec and rec.get("status") in ("ok", "suspicious"):
            final.append(_best(rec))
            if rec.get("status") == "suspicious":
                suspicious.append(i)
        else:
            failed.append(i)
            final.append(f"[ترجمهٔ این تکه ناموفق بود — تکهٔ {i} از متن اصلی]")

    # حالت article: معادل انگلیسی هر اصطلاح فقط در نخستین کاربرد داخل پرانتز بماند.
    # روی خروجی نهایی اعمال می‌شود، نه روی چک‌پوینت‌ها؛ پس با هر اجرا یکسان است.
    if args.mode == "article" and not args.no_dedupe_terms:
        final, removed = tjc.dedupe_first_use_parens(final, glossary)
        if removed:
            print(f"🧹 {removed} معادل انگلیسیِ تکراری داخل پرانتز حذف شد "
                  f"(فقط نخستین کاربرد هر اصطلاح می‌ماند).")

    md = "# " + title + "\n\n" + "\n\n".join(final) + "\n"
    md_path = os.path.join(outdir, name + ".fa.md")
    tjc.atomic_write_text(md_path, md)
    total_out = sum(len(t.split()) for t in final)
    print(f"🧮 کنترل تمامیت: {total_out} کلمه در خروجی نهایی.")
    u = api.total_usage
    print(f"🔢 مصرف توکن: prompt={u['prompt_tokens']:,} | "
          f"completion={u['completion_tokens']:,} | total={u['total_tokens']:,}")
    if suspicious:
        print("⚠️ تکه‌های مشکوک (بازبینی دستی): " + "، ".join(map(str, suspicious)))
    if failed:
        print("⚠️ تکه‌های ناموفق (با --retry-failed دوباره بزنید): "
              + "، ".join(map(str, failed)))

    pdf_path = None
    if not args.no_pdf:
        try:
            import build_pdf
            pdf_path = os.path.join(outdir, name + ".fa.pdf")
            build_pdf.build_pdf(title, final, pdf_path)
        except Exception as e:
            print("⚠️ ساخت PDF ناموفق بود (" + str(e) + ")؛ Markdown آماده است.")
    print("✅ تمام شد!")
    print("   Markdown: " + md_path)
    if pdf_path:
        print("   PDF: " + pdf_path)


if __name__ == "__main__":
    main()
