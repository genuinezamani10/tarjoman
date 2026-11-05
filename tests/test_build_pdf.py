import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import os, sys, tempfile, types
sys.path.insert(0, "scripts")

# ---- fake libs (real ones are not installed here) ----
seen = {"base_dir": []}
ar = types.ModuleType("arabic_reshaper"); ar.reshape = lambda t: t
bd = types.ModuleType("bidi"); bda = types.ModuleType("bidi.algorithm")
def get_display(t, base_dir=None):
    seen["base_dir"].append(base_dir); return t[::-1]      # simulate visual reversal
bda.get_display = get_display; bd.algorithm = bda
sys.modules.update({"arabic_reshaper": ar, "bidi": bd, "bidi.algorithm": bda})

class FakePDF:
    instances = []
    def __init__(self, **kw): self.w, self.l_margin, self.r_margin, self.c_margin = 100.0, 10.0, 10.0, 1.0; self.x = 10.0; self.calls = []; self.size = 12; FakePDF.instances.append(self)
    def set_auto_page_break(self, **kw): pass
    def add_font(self, *a, **kw): pass
    def add_page(self): pass
    def set_font(self, name, style, size): self.size, self.style = size, style
    def get_string_width(self, t): return float(len(t))           # 1 mm per char
    def cell(self, w, h, text, border=0, align="", new_x=None, new_y=None):
        if w > self.w - self.r_margin - self.x + 1e-9: raise Exception("Not enough horizontal space to render a single character")
        self.calls.append((self.size, self.style, text, align))
        self.x = self.l_margin if new_x == "LMARGIN" else self.w - self.r_margin
    def ln(self, h): self.x = self.l_margin
    def output(self, path): open(path, "wb").write(b"%PDF")
fp = types.ModuleType("fpdf"); fp.FPDF = FakePDF; sys.modules["fpdf"] = fp

fontdir = tempfile.mkdtemp(); open(os.path.join(fontdir, "Vazirmatn-Regular.ttf"), "wb").write(b"x")
os.environ["TARJOMAN_FONT_DIR"] = fontdir
import build_pdf as B

PARA = ("شبکه‌های عصبی مصنوعی (Artificial Neural Networks) از مغز انسان الهام گرفته شده‌اند و در سال‌های اخیر "
        "پیشرفت‌های چشمگیری داشته‌اند. در سال 2024 تعداد مقالات منتشرشده در این حوزه از 15000 فراتر رفت و دقت "
        "مدل‌ها روی مجموعه‌داده ImageNet به ۹۲٫۵ درصد رسید.")

def run(paras, title="تیتر"):
    FakePDF.instances.clear(); out = os.path.join(tempfile.mkdtemp(), "o.pdf")
    B.build_pdf(title, paras, out); return FakePDF.instances[0].calls

# 1) line ORDER: un-reverse each drawn line (undo simulated visual order) -> logical lines in order
calls = run([PARA]); body = [c for c in calls if c[0] == 12]
assert len(body) >= 3, len(body)
logical = [c[2][::-1] for c in body]
assert " ".join(logical) == PARA, logical
assert logical[0].startswith("شبکه‌های عصبی") and logical[-1].endswith("رسید.")   # first line is the paragraph's START
# 2) every line fits (80 - 2*c_margin = 78) and is right-aligned
assert all(len(l) <= 78 for l in logical) and all(c[3] == "R" for c in calls)
# 3) bidi called with explicit RTL base direction
assert set(seen["base_dir"]) == {"R"}, set(seen["base_dir"])
# 4) the reported crash: heading + multi-line body in one chunk
calls = run(["## زیربخش\nخط اول بدنه.\nخط دوم."])
assert [(c[0], c[1]) for c in calls] == [(20, "B"), (15, "B"), (12, "")], calls
assert calls[2][2][::-1] == "خط اول بدنه. خط دوم."
# 5) heading must NOT swallow the rest of the chunk; headings inside a chunk are recognised; ### works
calls = run(["# عنوان\n\nبند اول.\n\n## زیر\nبند دوم.\n\n### ریز\nبند سوم."])
sizes = [(c[0], c[2][::-1]) for c in calls[1:]]
assert sizes == [(17, "عنوان"), (12, "بند اول."), (15, "زیر"), (12, "بند دوم."), (13, "ریز"), (12, "بند سوم.")], sizes
# 6) over-wide single word does not crash (stays on its own line)
calls = run(["http://example.com/" + "a" * 200 + " و متن"]); assert len(calls) >= 3
# 7) empty / blank paragraphs are ignored
assert len(run(["", "   ", "\n\n"])) == 1
print("build_pdf OK;", len(body), "lines in the long paragraph")
