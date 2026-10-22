export const meta = {
  name: "tarjoman",
  description: "ترجمان: ترجمه‌ی PDF به فارسی در سه حالت (مقاله/درسی/رمان) — استخراج قطعی با PyMuPDF، OCR لوکال (Indra) برای PDFهای اسکن‌شده، واژه‌نامه‌ی زنده، ترجمه‌ی پیوسته، کنترل کیفیت ترجمه و ظاهر، مونتاژ با اسکریپت، خروجی PDF و Markdown",
  phases: ["prepare", "translate", "assemble", "verify"]
};

const inputs = args ?? {};
const pdfPath = inputs.pdf_path;
const outName = inputs.output_name || "tarjoman-fa";
const rawMode = (inputs.mode || "article").toLowerCase();
const useMode = ["novel", "article", "textbook"].indexOf(rawMode) >= 0 ? rawMode : "article";
const modeFa = useMode === "novel" ? "رمان" : (useMode === "textbook" ? "درسی" : "مقاله");
const pagesArg = inputs.pages || "";
const titleOverride = inputs.title || "";
const styleSample = inputs.style_sample || "";

const STYLE_DIR = "workspace/workflows/tarjoman/";
// اگر نمونه‌ی نثر داده شده، راهنما در فایل جدا ذخیره می‌شود تا راهنمای مشترک بازنویسی نشود.
const STYLE_GUIDE_PATH = styleSample ? STYLE_DIR + "style-guide-novel-custom.md" : STYLE_DIR + "style-guide-novel.md";

const pad3 = (n) => ("000" + n).slice(-3);

// n اندیس پراکنده‌ی یکنواخت از میان 0..total-1
const spread = (total, picks) => {
  const out = [];
  picks.forEach((p) => {
    const idx = Math.min(total - 1, Math.max(0, Math.floor(total * p)));
    if (out.indexOf(idx) < 0) out.push(idx);
  });
  return out;
};

if (!pdfPath) {
  return {
    __hatchWorkflowControl: "blocked",
    result: {
      blocked_reason: "missing pdf_path",
      message: "ورودی‌ها: pdf_path (اجباری)، mode ‏(novel | article | textbook — پیش‌فرض article)، pages ‏(مثل «1-5» برای تست چند صفحه)، title ‏(اختیاری)، style_sample ‏(نمونه‌ی نثر دلخواه برای حالت رمان)، output_name ‏(اختیاری)"
    }
  };
}

let modeInstructions = "";
if (useMode === "novel") {
  modeInstructions =
    "حالت رمان: این یک متن داستانی است؛ ترجمه‌ی ادبی و روان انجام بده.\n" +
    "- فایل راهنمای سبک را کامل بخوان و لحن، دایره‌ی واژگان، ریتم جمله‌ها و سبک دیالوگ‌های آن را در سراسر ترجمه رعایت کن.\n" +
    "- فایل واژه‌نامه‌ی عمومی رمان (memory/tarjoman-novel-glossary.md) را کامل بخوان و واژگان ترجیحی آن را رعایت کن (نام‌های خاص داستان را همچنان از واژه‌نامه‌ی مشترک بگیر).\n" +
    "- دیالوگ‌ها طبیعی و زنده باشند، نه خشک و کتابی.\n" +
    "- حس و حال صحنه‌ها حفظ شود؛ ترجمه‌ی تحت‌اللفظی ممنوع.";
} else if (useMode === "textbook") {
  modeInstructions =
    "حالت درسی: این یک متن آموزشی است.\n" +
    "- فرمول‌ها، کدها، نام متغیرها، نمادها و عددها دقیقاً دست نخورده بمانند؛ اگر در منبع به‌هم‌ریخته‌اند همان را عیناً منتقل کن و بازسازی نکن.\n" +
    "- توضیحات به فارسی روان و آموزشی؛ ساختار مثال‌ها و تمرین‌ها حفظ شود.";
} else {
  modeInstructions =
    "حالت مقاله: این یک متن آکادمیک/علمی است.\n" +
    "- ترجمهٔ روان و علمی؛ از ترجمهٔ تحت‌اللفظی پرهیز کن — جمله‌ها را به فارسی طبیعی بازنویسی کن، نه کلمه‌به‌کلمه.\n" +
    "- معادل انگلیسی هر اصطلاح را فقط در نخستین کاربرد آن اصطلاح داخل پرانتز بیاور؛ در تکرارهای بعدی فقط معادل فارسی.\n" +
    "- فایل راهنمای سبک مقاله (memory/tarjoman-article-style.md) را کامل بخوان و واژگان ترجیحی آن را رعایت کن.\n" +
    "- لحن رسمی و علمی؛ دقت مقدم بر روانی، ولی معنا تحریف نشود.";
}

// ───────────────────────── prepare ─────────────────────────
phase("prepare");

let extracted = await agent(
  [
    "تو یک مهندس استخراج متن هستی. با Python و PyMuPDF یک اسکریپت بنویس و اجرا کن (اگر نصب نیست: pip install pymupdf).",
    "متن را خودت بازنویسی یا خلاصه نکن؛ فقط اسکریپت را اجرا کن و خروجی‌اش را ذخیره کن.",
    "",
    "حالت متن: " + useMode,
    "",
    "مشخصات اسکریپت:",
    "۱. فایل PDF را از این مسیر باز کن: " + pdfPath,
    "۲. فقط صفحات خواسته‌شده را پردازش کن. ورودی pages برابر است با: «" + pagesArg + "» — خالی یعنی همه‌ی صفحات. قالب‌ها: «1-5» یعنی صفحات ۱ تا ۵، «3» یعنی فقط صفحه‌ی ۳، «1,4-6» یعنی صفحه‌ی ۱ و ۴ تا ۶. شماره‌گذاری از ۱ شروع می‌شود.",
    "۳. ترتیب خواندن: برای هر صفحه page.get_text(\"blocks\") را بگیر و فقط بلاک‌های متنی (block_type == 0) را نگه دار. ترتیب پیش‌فرض PDF را حفظ کن و بلاک‌ها را کورکورانه بر اساس y و x مرتب نکن (ستون‌ها را به‌هم می‌ریزد).",
    "   اگر صفحه دوستونه بود (بیشتر بلاک‌ها کمتر از ۵۵٪ عرض صفحه را پر می‌کنند و x0 آن‌ها در دو خوشه‌ی چپ و راست می‌افتد)، ابتدا همه‌ی بلاک‌های ستون چپ از بالا به پایین، سپس ستون راست؛ بلاک‌های تمام‌عرض (عنوان و چکیده) را سر جای خودشان بر اساس y بگذار.",
    "۴. پاکسازی (فقط برای متن عادی):",
    "   - سرصفحه/پاصفحه‌های تکراری (متنی که در بیش از نیمی از صفحات در ۸٪ بالا یا پایین صفحه تکرار می‌شود) و شماره‌صفحه‌ی تنها را حذف کن.",
    "   - اگر خطی به «-» ختم می‌شود و خط بعد با حرف کوچک شروع می‌شود، دو نیمه‌ی کلمه را بچسبان.",
    "   - شکستن‌های خط داخل یک پاراگراف را به فاصله تبدیل کن و فقط بین پاراگراف‌ها یک خط خالی بگذار.",
    "   - در حالت textbook این پاکسازی را برای خطوطی که شبیه فرمول یا کد هستند (نمادهای ریاضی، تورفتگی، = + ∑ ∫) انجام نده و عیناً نگه‌شان دار.",
    "۵. اگر میانگین کاراکتر استخراج‌شده در هر صفحه کمتر از ۱۰۰ بود، PDF را اسکن‌شده اعلام کن (is_scanned=true).",
    "۶. متن را به تکه‌هایی حدوداً ۱۳۰۰ کلمه‌ای تقسیم کن، فقط روی مرز پاراگراف (خط خالی)؛ هیچ‌وقت وسط جمله نبر. اگر یک پاراگراف تکی از ۱۶۰۰ کلمه بیشتر شد، روی پایان جمله بشکن.",
    "۷. تکه‌ها را با نام‌های chunk-001.txt و الی آخر در همین دایرکتوری کاری ذخیره کن.",
    "۸. تعداد کلمات هر تکه را در همان اسکریپت با len(text.split()) حساب کن (نه تخمینی).",
    "۹. عنوان (title) را از متادیتای PDF بردار؛ اگر خالی بود از روی اولین خطوط متن حدس بزن.",
    "",
    "نتیجه را فقط در قالب JSON برگردان."
  ].join("\n"),
  {
    key: "extract",
    label: "استخراج قطعی متن (PyMuPDF)",
    timeoutMs: 300000,
    schema: {
      type: "object",
      required: ["chunks", "total_pages", "pages_used", "title", "is_scanned"],
      properties: {
        chunks: {
          type: "array",
          items: {
            type: "object",
            required: ["path", "words"],
            properties: { path: { type: "string" }, words: { type: "number" } }
          },
          description: "تکه‌ها به ترتیب"
        },
        total_pages: { type: "number" },
        pages_used: { type: "string" },
        title: { type: "string" },
        is_scanned: { type: "boolean" }
      }
    }
  }
);

let usedOcr = false;
if (extracted.is_scanned || !extracted.chunks || extracted.chunks.length === 0) {
  log("PDF اسکن‌شده است؛ OCR لوکال (Indra) اجرا می‌شود...");
  const ocrResult = await agent(
    [
      "تو یک مجری مرحله‌ی OCR ترجمان هستی. این PDF اسکن‌شده است و لایه‌ی متن ندارد. اسکریپت آماده‌ی OCR ترجمان (Indra OCR لوکال + نرمال‌ساز فارسی) را اجرا کن و خروجی‌اش را عیناً برگردان.",
      "متن را خودت بازنویسی، ترجمه یا خلاصه نکن و اسکریپت تازه ننویس؛ فقط دستور زیر را اجرا کن.",
      "",
      "مشخصات کار:",
      "۱. این دستور را اجرا کن:",
      "   ~/workspace/tools/indra-venv/bin/python ~/workspace/workflows/tarjoman/scripts/ocr_extract.py --pdf <مسیر PDF> --outdir <دایرکتوری کاری این اجرا>",
      "   - مسیر PDF: " + pdfPath,
      "   - صفحات خواسته‌شده: «" + pagesArg + "» — اگر خالی بود آرگومان --pages را نده؛ اگر پر بود دقیقاً اضافه کن: --pages «" + pagesArg + "» (شماره‌گذاری از ۱).",
      "   - اسکریپت خودش صفحات را جدا می‌کند، با Indra OCR (فقط CPU) می‌خواند، سرصفحه/پاصفحه‌ی تکراری و شماره‌صفحه را حذف می‌کند، نویسه‌های اردو/عربیِ قاطی‌شده را به فارسی نرمال می‌کند (ي→ی، ك→ک، ہ→ه و ...)، پاراگراف‌ها را بازسازی و متن را به تکه‌های حدوداً ۱۳۰۰ کلمه‌ای (chunk-001.txt و ...) تقسیم می‌کند.",
      "۲. خروجی اسکریپت روی stdout یک JSON است با قالب {chunks: [{path, words}], total_pages, pages_used, title, is_scanned} — همان را عیناً به‌عنوان نتیجه برگردان.",
      "۳. اگر اسکریپت به‌خاطر نبودن venv یا باینری Indra خطا داد، یک بار این‌ها را بساز و دوباره اجرا کن: python3 -m venv ~/workspace/tools/indra-venv و بعد ~/workspace/tools/indra-venv/bin/pip install indra-ocr pymupdf (دانلود مدل‌ها در اولین اجرا خودکار است). اگر باز هم خطا داد یا chunks خالی بود، chunks را آرایه‌ی خالی برگردان.",
      "",
      "نتیجه را فقط در قالب JSON برگردان."
    ].join("\n"),
    {
      key: "ocr",
      label: "OCR لوکال PDF اسکن‌شده (Indra)",
      timeoutMs: 1800000,
      schema: {
        type: "object",
        required: ["chunks", "total_pages", "pages_used", "title", "is_scanned"],
        properties: {
          chunks: {
            type: "array",
            items: {
              type: "object",
              required: ["path", "words"],
              properties: { path: { type: "string" }, words: { type: "number" } }
            },
            description: "تکه‌ها به ترتیب"
          },
          total_pages: { type: "number" },
          pages_used: { type: "string" },
          title: { type: "string" },
          is_scanned: { type: "boolean" }
        }
      }
    }
  );
  if (ocrResult && ocrResult.chunks && ocrResult.chunks.length > 0) {
    extracted = {
      chunks: ocrResult.chunks,
      total_pages: ocrResult.total_pages || extracted.total_pages,
      pages_used: ocrResult.pages_used || extracted.pages_used,
      title: ocrResult.title || extracted.title,
      is_scanned: false
    };
    usedOcr = true;
    log("OCR لوکال انجام شد: " + ocrResult.chunks.length + " تکه از PDF اسکن‌شده استخراج شد.");
  } else {
    return {
      __hatchWorkflowControl: "blocked",
      result: {
        blocked_reason: "no extractable text",
        message: "این PDF اسکن‌شده است و OCR لوکال (Indra) هم نتوانست متن خوانایی از آن بگیرد (احتمالاً اسکن بی‌کیفیت یا دست‌نویس است)."
      }
    };
  }
}

const finalTitle = titleOverride || extracted.title || outName;
const totalChunks = extracted.chunks.length;

const samplePaths = spread(totalChunks, [0, 0.02, 0.25, 0.5, 0.75, 0.99]).map((si) => extracted.chunks[si].path);

const prepResults = await parallel([
  async () => {
    return await agent(
      [
        "تو یک واژه‌نامه‌ساز هستی. این تکه‌های نمونه از یک متن «" + modeFa + "» را بخوان:",
        samplePaths.join("\n"),
        "",
        useMode === "novel"
          ? "نام شخصیت‌ها، لقب‌ها، نام مکان‌ها و اصطلاحات تکرارشونده‌ی داستان را استخراج کن."
          : "حدود ۴۰ اصطلاح تخصصی کلیدی و تکرارشونده را استخراج کن.",
        "برای هر مورد یک معادل فارسی دقیق و یکدست پیشنهاد بده (نام‌ها: آوانگاری یکدست و ثابت).",
        "یک فایل Markdown با نام glossary.md در همین دایرکتوری کاری ذخیره کن که دقیقاً با این سرجدول شروع شود و ردیف‌ها زیرش بیایند:",
        "| عبارت اصلی | معادل فارسی |",
        "| --- | --- |",
        "این فایل در طول ترجمه با ردیف‌های جدید تکمیل می‌شود؛ پس فقط یک جدول در آن باشد.",
        "نتیجه را فقط در قالب JSON برگردان."
      ].join("\n"),
      {
        key: "glossary",
        label: "ساخت واژه‌نامه‌ی اولیه",
        timeoutMs: 600000,
        schema: {
          type: "object",
          required: ["path", "term_count"],
          properties: { path: { type: "string" }, term_count: { type: "number" } }
        }
      }
    );
  },
  async () => {
    if (useMode !== "novel") return null;
    return await agent(
      [
        "تو یک پژوهشگر سبک‌شناسی ادبیات فارسی هستی.",
        "",
        styleSample
          ? "یک نمونه‌ی نثر دلخواه داده شده است:\n\"\"\"\n" + styleSample + "\n\"\"\"\n" +
            "سبک همین نمونه را تحلیل کن (دایره‌ی واژگان، لحن روایت و دیالوگ، ریتم جمله‌ها، چند مثال عینی، و نکن‌ها) و راهنمای سبک را بنویس. جست‌وجوی وب لازم نیست و فایل قبلی را دست نزن."
          : "۱. ابتدا بررسی کن آیا فایل " + STYLE_GUIDE_PATH + " از قبل وجود دارد و کامل است؛ اگر بله، همان مسیر را برگردان و پژوهش مجدد نکن.\n" +
            "۲. در غیر این صورت، سبک نگارش رمان‌های فارسی «کف خیابون»، «قهوه سرد» و «عشق و چیزهای دیگر» را بررسی کن (این‌ها مثال‌اند؛ اگر عنوانی دقیق پیدا نشد از رمان‌های مشابه همان فضا استفاده کن).\n" +
            "از جست‌وجوی وب برای یافتن نقدها و تحلیل‌های سبک استفاده کن؛ اگر وب در دسترس نبود از دانش خودت استفاده کن.\n" +
            "یک «راهنمای سبک» فارسی بنویس شامل: دایره‌ی واژگان غالب، لحن روایت و دیالوگ‌ها، ریتم و طول جمله‌ها، چند مثال عینی (با عبارت‌های خودت، نه نقل طولانی از متن رمان‌ها)، و نکن‌ها.",
        "",
        "راهنما را دقیقاً در مسیر " + STYLE_GUIDE_PATH + " ذخیره کن و نتیجه را فقط در قالب JSON برگردان."
      ].join("\n"),
      {
        key: "style-novel",
        label: "پژوهش سبک رمان",
        timeoutMs: 600000,
        schema: {
          type: "object",
          required: ["path"],
          properties: { path: { type: "string", description: "مسیر فایل راهنمای سبک" } }
        }
      }
    );
  }
]);

const glossRes = prepResults[0];
const styleRes = prepResults[1];
const glossPath = glossRes && glossRes.path ? glossRes.path : "glossary.md";
const styleGuidePath = styleRes && styleRes.path ? styleRes.path : STYLE_GUIDE_PATH;

log("حالت: " + modeFa + " | تکه‌ها: " + totalChunks + " | واژه‌های اولیه: " + (glossRes ? glossRes.term_count : 0));

// ───────────────────────── translate ─────────────────────────
phase("translate");

const translatedList = [];
const failedChunks = [];
const suspiciousChunks = [];
let prevTail = "";

const translateSchema = {
  type: "object",
  required: ["path", "words", "tail"],
  properties: {
    path: { type: "string" },
    words: { type: "number", description: "تعداد کلمات فایل ترجمه که با ابزار شمرده شده" },
    tail: { type: "string", description: "سه خط آخر ترجمه، خوانده‌شده از خود فایل" }
  }
};

for (let i = 0; i < totalChunks; i++) {
  const ch = extracted.chunks[i];
  const outFile = "fa-chunk-" + pad3(i + 1) + ".md";

  const buildPrompt = (retryNote) => {
    return [
      "تو یک مترجم حرفه‌ای به فارسی هستی. فایل متنی زیر را کامل بخوان و ترجمه کن: " + ch.path,
      "(تکه‌ی " + (i + 1) + " از " + totalChunks + ")",
      "",
      "۱. این فایل‌های مرجع را کامل بخوان و در سراسر ترجمه رعایت کن:",
      "   - واژه‌نامه‌ی مشترک: " + glossPath + " (نام‌ها و اصطلاحات دقیقاً طبق همین، بدون استثنا؛ اگر فایل وجود نداشت با همان سرجدول بساز)",
      useMode === "novel" ? "   - راهنمای سبک: " + styleGuidePath : "",
      prevTail ? "۲. سه خط پایانی ترجمه‌ی تکه‌ی قبل (پیوستگی):\n\"\"\"\n" + prevTail + "\n\"\"\"\nشروع این تکه باید به آن بچسبد؛ ضمیرها و ارجاع‌ها را با آن هماهنگ کن." : "",
      modeInstructions,
      "۳. هر نام یا اصطلاح تخصصی مهمی که در این تکه بود و در واژه‌نامه نیست را به‌صورت ردیف جدید به انتهای جدول " + glossPath + " اضافه کن (فقط append؛ ردیف‌های موجود را تغییر نده و حذف نکن).",
      retryNote ? "تذکر مهم: " + retryNote : "",
      "۴. ترجمه‌ی کامل را در فایل " + outFile + " در همین دایرکتوری کاری ذخیره کن. هیچ بخشی را حذف یا خلاصه نکن.",
      "۵. بعد از ذخیره، با ابزار bash تعداد کلمات فایل ترجمه را بشمار (wc -w) و سه خط آخر را با tail -n 3 از خود فایل بخوان؛ این‌ها را تخمینی یا از حافظه ننویس.",
      "نتیجه را فقط در قالب JSON برگردان: {path, words, tail}."
    ].filter((s) => s !== "").join("\n");
  };

  let res = null;
  let fallback = null;   // نتیجه‌ی دور اول اگر مشکوک بود
  let flagged = false;
  let note = "";

  for (let att = 1; att <= 2; att++) {
    let cur = null;
    try {
      cur = await agent(buildPrompt(note), {
        key: "translate-" + i + "-a" + att,
        label: "ترجمه‌ی تکه‌ی " + (i + 1) + "/" + totalChunks + (att > 1 ? " (تلاش " + att + ")" : ""),
        timeoutMs: 600000,
        schema: translateSchema
      });
    } catch (e) {
      cur = null;
    }

    if (cur && cur.path) {
      let problem = "";
      if (!(cur.words > 0)) {
        problem = "فایل ترجمه خالی است؛ دوباره و کامل ترجمه کن.";
      } else if (ch.words > 0) {
        const ratio = cur.words / ch.words;
        if (ratio < 0.45) {
          problem = "ترجمه ناقص یا خلاصه به نظر می‌رسد (نسبت کلمات پایین). لطفاً کامل و دقیق ترجمه کن و هیچ بخشی را حذف نکن.";
        } else if (ratio > 2.2) {
          problem = "ترجمه دچار تکرار یا حشو به نظر می‌رسد. بازبینی کن و حشوها را حذف کن.";
        }
      }
      if (!problem) {
        res = cur;
        break;
      }
      // به‌جای دور ریختن، نتیجه را نگه می‌داریم (مثلاً فهرست منابع نسبت غیرعادی دارد) و فقط علامت می‌زنیم.
      fallback = cur;
      note = problem;
      continue;
    }
    note = "تلاش قبلی ناموفق بود؛ دوباره با دقت کامل ترجمه کن.";
  }

  if (!res && fallback) {
    res = fallback;
    flagged = true;
  }

  if (res && res.path) {
    translatedList.push({ index: i, path: res.path });
    prevTail = res.tail || "";
    if (flagged) {
      suspiciousChunks.push(i);
      log("تکه‌ی " + (i + 1) + " ذخیره شد ولی نسبت کلمات مشکوک است (علامت‌گذاری شد).");
    }
  } else {
    failedChunks.push(i + 1);
    log("تکه‌ی " + (i + 1) + " پس از دو تلاش ناموفق ماند.");
  }
}

if (translatedList.length === 0) {
  throw new Error("ترجمه‌ی هیچ تکه‌ای موفق نبود.");
}

const byIndex = {};
translatedList.forEach((t) => { byIndex[t.index] = t.path; });
const orderedPaths = [];
for (let i = 0; i < totalChunks; i++) {
  if (byIndex[i]) orderedPaths.push("تکه‌ی " + (i + 1) + ": " + byIndex[i]);
}

// نمونه‌ی بازبینی: ابتدا تکه‌های مشکوک، بعد چند تکه‌ی پراکنده
const spotIdx = [];
suspiciousChunks.slice(0, 3).forEach((si) => { if (byIndex[si]) spotIdx.push(si); });
spread(totalChunks, [0, 0.33, 0.66, 0.99]).forEach((si) => {
  if (byIndex[si] && spotIdx.indexOf(si) < 0) spotIdx.push(si);
});
const spotPairs = spotIdx.map((si) => {
  return "منبع: " + extracted.chunks[si].path + " | ترجمه: " + byIndex[si] + " (تکه‌ی " + (si + 1) + ")";
});

// ───────────────────────── assemble + verify ─────────────────────────
phase("assemble");

const integrityOk = (b) => {
  if (!b || !(b.chunks_words_sum > 0)) return false;
  const diff = Math.abs(b.md_words - b.chunks_words_sum);
  return diff <= b.chunks_words_sum * 0.01 + 20;
};

let attemptNote = "";
let finalBuilt = null;
let finalLangCheck = null;
let finalIntegrity = true;

for (let attempt = 1; attempt <= 2; attempt++) {
  const built = await agent(
    [
      "تو یک سازنده‌ی سند فارسی هستی.",
      "قانون اصلی: متن ترجمه‌ها را هرگز خودت بازنویسی، خلاصه، ویرایش یا دوباره‌تایپ نکن. همه‌ی کار باید با یک اسکریپت Python (یا دستور cat) انجام شود که فایل‌ها را می‌خواند و می‌چسباند.",
      "",
      "فایل‌های ترجمه‌شده به همین ترتیب:",
      orderedPaths.join("\n"),
      "",
      "۱. با اسکریپت، فایل‌ها را به ترتیب بخوان و با یک خط خالی بین‌شان بچسبان. خط اول سند تیتر اصلی باشد: # " + finalTitle,
      failedChunks.length > 0
        ? "۲. تکه‌های شماره‌ی " + failedChunks.join("، ") + " ترجمه نشدند؛ جایشان را با یک خط مشخص «[ترجمه‌نشده: تکه‌ی N]» بگذار."
        : "۲. همه‌ی تکه‌ها ترجمه شده‌اند.",
      "۳. فایل Markdown را در workspace/your_files/tarjoman/" + outName + ".md ذخیره کن.",
      "۴. برای PDF: با اسکریپت Markdown را به HTML تبدیل کن (کتابخانه‌ی markdown؛ اگر نبود نصبش کن) با dir=\"rtl\" و lang=\"fa\" و فونت وزیرمتن (اگر فونت نیست دانلودش کن)، سپس HTML را به PDF تبدیل کن و در workspace/your_files/tarjoman/" + outName + ".pdf ذخیره کن.",
      "۵. شمارش برای کنترل یکپارچگی، با اسکریپت و نه تخمینی:",
      "   - chunks_words_sum = مجموع len(text.split()) همه‌ی فایل‌های ترجمه‌ی بالا.",
      "   - md_words = len(text.split()) فایل Markdown نهایی، بعد از حذف خط تیتر و خط‌های «[ترجمه‌نشده…]».",
      attemptNote ? "۶. بازخورد دور قبل که حتماً باید اصلاح شود: " + attemptNote : "",
      "نتیجه را فقط در قالب JSON برگردان."
    ].filter((s) => s !== "").join("\n"),
    {
      key: "assemble-" + attempt,
      label: "ساخت خروجی‌ها با اسکریپت (تلاش " + attempt + ")",
      timeoutMs: 600000,
      schema: {
        type: "object",
        required: ["pdf_path", "md_path", "page_count", "chunks_words_sum", "md_words"],
        properties: {
          pdf_path: { type: "string" },
          md_path: { type: "string" },
          page_count: { type: "number" },
          chunks_words_sum: { type: "number" },
          md_words: { type: "number" }
        }
      }
    }
  );
  finalBuilt = built;

  const intOk = integrityOk(built);
  finalIntegrity = intOk;
  if (!intOk && attempt < 2) {
    attemptNote = "تعداد کلمات سند نهایی (" + built.md_words + ") با مجموع تکه‌ها (" + built.chunks_words_sum + ") نمی‌خواند؛ احتمالاً بخشی حذف یا تغییر کرده. دقیقاً با اسکریپت بچسبان و متن را دست نزن.";
    log("خطای یکپارچگی: " + attemptNote);
    continue;
  }

  phase("verify");
  const look = await agent(
    [
      "تو یک بازبین کیفیت هستی. این فایل PDF را باز کن و فقط ظاهر آن را بررسی کن: " + built.pdf_path,
      "",
      "- آیا متن فارسی درست خوانده می‌شود (حروف چسبیده و مرتب، نه به‌هم‌ریخته)؟",
      "- آیا جهت متن راست‌به‌چپ و فونت فارسی درست رندر شده؟",
      "- آیا سند ناقص نیست؟ بخش ترجمه‌شده از صفحات «" + (extracted.pages_used || "همه") + "» از " + extracted.total_pages + " صفحه‌ی PDF اصلی است؛ تعداد صفحات خروجی را با همین بخش مقایسه کن.",
      "نتیجه را فقط در قالب JSON برگردان."
    ].join("\n"),
    {
      key: "verify-look-" + attempt,
      label: "بازبینی ظاهر PDF (تلاش " + attempt + ")",
      timeoutMs: 180000,
      schema: {
        type: "object",
        required: ["passed", "retryable", "feedback"],
        properties: {
          passed: { type: "boolean" },
          retryable: { type: "boolean" },
          feedback: { type: "string" }
        }
      }
    }
  );

  const lang = await agent(
    [
      "تو یک ویراستار دوزبانه‌ی سخت‌گیر هستی. این جفت‌فایل‌های نمونه (منبع و ترجمه) را بررسی کن:",
      spotPairs.join("\n"),
      "",
      "واژه‌نامه‌ی مرجع: " + glossPath + " (نام‌ها و اصطلاحات باید دقیقاً مطابق آن باشند)",
      "",
      "۱. آیا بخش‌های انگلیسی ترجمه‌نشده باقی مانده؟",
      "۲. آیا اصطلاحات/نام‌ها با واژه‌نامه ناهماهنگ‌اند؟",
      "۳. آیا پاراگرافی از منبع حذف شده؟ (تعداد پاراگراف‌های منبع و ترجمه را با اسکریپت مقایسه کن)",
      "نتیجه را فقط در قالب JSON برگردان: {passed, retryable, feedback, bad_chunks} که bad_chunks آرایه‌ی شماره‌ی تکه‌های مشکل‌دار است (شماره‌ی نمایش‌داده‌شده‌ی تکه، از ۱)."
    ].join("\n"),
    {
      key: "verify-lang-" + attempt,
      label: "بازبینی کیفیت ترجمه (تلاش " + attempt + ")",
      timeoutMs: 300000,
      schema: {
        type: "object",
        required: ["passed", "retryable", "feedback", "bad_chunks"],
        properties: {
          passed: { type: "boolean" },
          retryable: { type: "boolean" },
          feedback: { type: "string" },
          bad_chunks: { type: "array", items: { type: "number" } }
        }
      }
    }
  );
  finalLangCheck = lang;

  if (look.passed && lang.passed && intOk) {
    break;
  }
  if (attempt === 2 || (!look.retryable && !lang.retryable)) {
    break;
  }

  if (!lang.passed && lang.retryable && lang.bad_chunks && lang.bad_chunks.length > 0) {
    for (let bi = 0; bi < lang.bad_chunks.length; bi++) {
      const chunkNum = lang.bad_chunks[bi];
      const ti = chunkNum - 1;
      if (ti < 0 || ti >= totalChunks || !byIndex[ti]) continue;
      try {
        const fixed = await agent(
          [
            "تو یک مترجم حرفه‌ای به فارسی هستی. تکه‌ی شماره‌ی " + chunkNum + " را دوباره و کامل ترجمه کن. فایل منبع: " + extracted.chunks[ti].path,
            "",
            "واژه‌نامه‌ی مشترک (" + glossPath + ") را دقیق رعایت کن؛ ردیف‌های جدید را فقط append کن.",
            useMode === "novel" ? "راهنمای سبک را هم کامل بخوان و رعایت کن: " + styleGuidePath : "",
            "بازخورد ویراستار که باید اصلاح شود: " + lang.feedback,
            modeInstructions,
            "ترجمه‌ی اصلاح‌شده را در همان فایل قبلی بازنویسی کن: " + byIndex[ti],
            "بعد از ذخیره، تعداد کلمات را با wc -w بشمار و سه خط آخر را با tail -n 3 از فایل بخوان.",
            "نتیجه را فقط در قالب JSON برگردان: {path, words, tail}."
          ].filter((s) => s !== "").join("\n"),
          {
            key: "retranslate-" + ti + "-a" + attempt,
            label: "اصلاح تکه‌ی " + chunkNum,
            timeoutMs: 600000,
            schema: translateSchema
          }
        );
        if (fixed && fixed.path) {
          log("تکه‌ی " + chunkNum + " اصلاح شد.");
        }
      } catch (e) {
        log("اصلاح تکه‌ی " + chunkNum + " ناموفق بود.");
      }
    }
  }
  attemptNote = "ظاهر: " + look.feedback + " | ترجمه: " + lang.feedback;
  log("تلاش مجدد مونتاژ با بازخورد: " + attemptNote);
}

// ───────────────────────── result ─────────────────────────
let msg = "ترجمه آماده شد ✅ «" + finalTitle + "» در حالت «" + modeFa + "» به فارسی برگردانده شد (" + translatedList.length + " از " + totalChunks + " تکه).";
if (failedChunks.length > 0) {
  msg = msg + "\n⚠️ تکه‌های شماره‌ی " + failedChunks.join("، ") + " ترجمه نشدند و در خروجی با برچسب مشخص شده‌اند.";
}
if (suspiciousChunks.length > 0) {
  msg = msg + "\n⚠️ تکه‌های شماره‌ی " + suspiciousChunks.map((s) => s + 1).join("، ") + " نسبت کلمات غیرعادی داشتند (ممکن است خلاصه یا حشو باشند)؛ چشمی نگاهشان کن.";
}
if (!finalIntegrity) {
  msg = msg + "\n⚠️ تعداد کلمات سند نهایی با مجموع تکه‌ها نمی‌خواند؛ ممکن است مونتاژ بخشی را تغییر داده باشد.";
}
if (finalLangCheck && !finalLangCheck.passed) {
  msg = msg + "\n⚠️ بازبینی ترجمه ایرادهایی گزارش کرد: " + finalLangCheck.feedback;
}
if (usedOcr) {
  msg = msg + "\n🔎 این PDF اسکن‌شده بود و متنش با OCR لوکال (Indra) خوانده شد؛ خطای OCR ممکن است به ترجمه رسیده باشد — جاهای حساس (عددها، نام‌ها، فرمول‌ها) را با اصل سند چک کن.";
}
if (useMode === "textbook") {
  msg = msg + "\n💡 یادآوری حالت درسی: فرمول‌ها و جدول‌ها را حتماً چشمی بازبینی کن؛ استخراج متن ممکن است چیدمان آن‌ها را به‌هم ریخته باشد.";
}
return {
  message: msg,
  files: [finalBuilt.md_path, finalBuilt.pdf_path]
};