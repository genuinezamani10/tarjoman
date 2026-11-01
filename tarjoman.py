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
  • واژه‌نامه: در work/glossary.txt ذخیره و قابل ویرایش دستی است؛ با --glossary
    مسیر دیگری بدهید و با --regen-glossary از نو بسازید.
  • زمینهٔ تکهٔ قبل (در حالت ترتیبی): دو پاراگراف آخر تکهٔ قبل (متن اصلی + ترجمه)
    به‌عنوان «زمینه، ترجمه نکن» به پرامپت اضافه می‌شود.
  • موازی‌سازی: برای article و textbook پیش‌فرض ۴ worker؛ برای novel ترتیبی (۱).
  • کنترل کیفیت: نسبت کلمات (به‌جز textbook که فرمول/کد دارد)، سهم حروف فارسی،
    و تشخیص قطع شدن خروجی (finish_reason=length) با تلاش مجدد.
  • پاس دوم ویرایش فارسی با --polish (اختیاری، بیشتر برای رمان).

نکته برای مدل لوکال (Ollama): چون Api سازگار با OpenAI است همین کد کار می‌کند؛
برای مدل‌های کوچک تکه‌ها را کوچک‌تر کنید (--chunk-words 600) و کنترل کیفیت را
شل‌تر (--qc-loose).
"""

import argparse
import concurrent.futures
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


def check_quality(out: str, src_words: int, mode: str, o) -> str:
    """بررسی کیفیت یک تکه؛ خروجی: رشتهٔ خالی یعنی سالم، وگرنه شرح مشکل."""
    notes = []
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
                for k in self.total_usage:
                    self.total_usage[k] += usage.get(k, 0) or 0
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

def get_chunks(pdf: str, pages: str, mode: str, workdir: str, chunk_words: int):
    """استخراج متن یا (برای اسکن‌شده) OCR لوکال؛ خروجی: فهرست متن تکه‌ها."""
    import extract_text

    res = extract_text.extract(pdf, pages, mode == "textbook")
    if not res["is_scanned"]:
        from ocr_extract import chunk
        return chunk(res["paragraphs"], target=chunk_words), res

    print("📄 PDF اسکن‌شده است؛ OCR لوکال (Indra) اجرا می‌شود...")
    import ocr_extract

    ocr_pages = ocr_extract.run_ocr(pdf, workdir)
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
            g = f.read().strip()
        print(f"📖 واژه‌نامه از {path} خوانده شد ({len(g.splitlines())} مورد).")
        return g, path
    g = build_glossary(api, chunks, mode)
    if g:
        with open(path, "w", encoding="utf-8") as f:
            f.write(g + "\n")
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
    with open(chunk_path(workdir, idx), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)


def _should_skip(rec, retry_failed: bool) -> bool:
    if not rec:
        return False
    if rec.get("status") == "ok":
        return True
    # مشکوک‌ها فقط با --retry-failed دوباره زده می‌شوند؛ ناموفق‌ها همیشه
    return rec.get("status") == "suspicious" and not retry_failed


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


def polish_one(api: Api, translation: str, o) -> str | None:
    """پاس دوم: روان‌سازی فارسی و یکدستی نام‌ها (اختیاری)."""
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
            for k in api.total_usage:
                api.total_usage[k] += (r["usage"].get(k, 0) or 0)
        return r["content"]
    except Exception as e:
        print("⚠️ پاس ویرایش ناموفق بود (" + str(e) + ")؛ همان ترجمهٔ اول می‌ماند.")
        return None


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
    rec = {"index": idx, "src_words": src_words, "status": "failed",
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
        problems = check_quality(out, src_words, mode, o)
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
                if not check_quality(out2, src_words, mode, o) and fr2 != "length":
                    out, fr, problems = out2, fr2, ""
                else:
                    problems = check_quality(out2, src_words, mode, o) or problems
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
            print(f"✨ پاس ویرایش تکهٔ {idx}...")
            rec["polished"] = polish_one(api, out, o)
    except Exception as e:
        rec["error"] = str(e)[:300]
        print(f"❌ تکهٔ {idx} ناموفق: {e}")
    save_record(workdir, idx, rec)
    return rec


def translate_all(api: Api, chunks: list[str], mode: str, style_text: str,
                  glossary: str, workdir: str, o) -> list:
    n = len(chunks)
    records: list = [None] * n
    for i in range(n):
        rec = load_record(workdir, i + 1)
        if _should_skip(rec, o.retry_failed):
            records[i] = rec
            print(f"⏭️ تکهٔ {i + 1} از {n} از چک‌پوینت رد شد.")
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
                        _tail_paras(records[i].get("translation") or ""))
                continue
            print(f"✏️ ترجمهٔ تکهٔ {i + 1} از {n} ({len(chunks[i].split())} کلمه)...")
            rec = translate_one(api, i + 1, chunks[i], mode, system_base,
                                workdir, o, prev)
            records[i] = rec
            prev = (_tail_paras(chunks[i]),
                    _tail_paras(rec.get("translation") or ""))
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
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--no-pdf", action="store_true")
    # ── فلگ‌های جدید ──
    ap.add_argument("--retry-failed", action="store_true",
                    help="تلاش مجدد فقط برای تکه‌های ناموفق و مشکوک")
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
    style_text = read_style(args.mode, args.style_sample or None)
    records = translate_all(api, chunks, args.mode, style_text, glossary,
                            workdir, args)

    final, suspicious, failed = [], [], []
    for i, rec in enumerate(records, 1):
        if rec and rec.get("status") in ("ok", "suspicious"):
            final.append(rec.get("polished") or rec.get("translation") or "")
            if rec.get("status") == "suspicious":
                suspicious.append(i)
        else:
            failed.append(i)
            final.append(f"[ترجمهٔ این تکه ناموفق بود — تکهٔ {i} از متن اصلی]")

    md = "# " + title + "\n\n" + "\n\n".join(final) + "\n"
    md_path = os.path.join(outdir, name + ".fa.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
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
