import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import json, os, sys, tempfile, types, shutil
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import tarjoman as T

def ids(mode, prof=""): return T.resolve_style(mode, prof)

# ---- resolve_style ----
assert ids("novel") == ("modern-colloquial", ["novel-core.md", "profile-modern-colloquial.md"])
assert ids("novel", "romance-urban")[1][-2:] == ["profile-modern-colloquial.md", "profile-romance-urban.md"]
assert ids("novel", "literary-fable")[1][-1] == "profile-literary-fable.md" and "profile-modern-colloquial.md" not in ids("novel", "literary-fable")[1]
assert ids("novel", "legacy") == ("legacy", ["style-guide-novel.md", "tarjoman-novel-glossary.md"])
assert ids("article")[0] == "" and ids("textbook") == ("", [])
try: ids("novel", "nope"); assert False
except SystemExit as e: assert "nope" in str(e.code)

# ---- real files: loaded, in order, and profiles do not leak into each other ----
d = T.read_style("novel", None)
assert "اصل صفر" in d and "پروفایل پیش‌فرض رمان: محاوره‌ای معیار" in d and "غول خودخواه" not in d
lit = T.read_style("novel", None, "literary-fable")
assert "غول خودخواه" in lit and "نشانهٔ مفعول همیشه «رو»" not in lit
rom = T.read_style("novel", None, "romance-urban")
assert rom.index("پروفایل پیش‌فرض رمان: محاوره‌ای معیار") < rom.index("رمان عاشقانهٔ معاصر شهری")
# style sample goes last
tmp = tempfile.mkdtemp(); sp = os.path.join(tmp, "s.txt"); open(sp, "w", encoding="utf-8").write("نمونهٔ من")
assert T.read_style("novel", sp).rstrip().endswith("نمونهٔ من")

# ---- no table rows / glossary lines were lost when the old files were split ----
def rows(path): return [l for l in open(path, encoding="utf-8") if l.startswith("|") and not l.startswith("|---") and "مفهوم" not in l and "عبارت انگلیسی" not in l]
assert len(rows("styles/novel-core.md")) == 26
assert len(rows("styles/profile-literary-fable.md")) == 20
gl = [l for l in open("styles/books/animal-farm-glossary.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
assert len(gl) == 22 and all(" = " in l for l in gl)

# ---- missing novel file is fatal (not silently skipped); article still only warns ----
old_here = T.HERE; T.HERE = tempfile.mkdtemp()
try:
    T.read_style("novel", None); assert False
except SystemExit as e: assert "پیدا نشد" in str(e.code)
assert T.read_style("article", None) == ""
T.HERE = old_here

# ---- glossary file: '#' comment lines are not sent to the model ----
class A:  # api never needed when file exists
    pass
g, path = T.get_glossary(A(), ["x"], "novel", tempfile.mkdtemp(), "styles/books/animal-farm-glossary.txt", False)
assert "#" not in g and "python3" not in g and "comrade = رفقا" in g and len(g.splitlines()) == 22

# ---- checkpoint records the style; a different profile makes the chunk stale ----
T1 = "این یک ترجمهٔ فارسی کامل است برای خواننده و برای همه."
class FakeApi:
    model = "fake"
    def __init__(s): s.calls = 0
    def add_usage(s, u): pass
    def chat(s, system, user, temperature=0.3, max_tokens=8192):
        s.calls += 1; return {"content": T1, "finish_reason": "stop", "usage": {}}
def ns(**kw):
    d = dict(qc_loose=False, polish=False, max_tokens=8192, workers=1, retry_failed=False,
             trust_old_checkpoints=False, glossary_text="", polish_model="", mode="novel", style_id="modern-colloquial")
    d.update(kw); return types.SimpleNamespace(**d)
SRC = ["He went home and sat down for a long time with his tea in the evening."]
wd = tempfile.mkdtemp()
a = FakeApi(); r = T.translate_all(a, SRC, "novel", "", "", wd, ns()); assert a.calls == 1
assert json.load(open(T.chunk_path(wd, 1), encoding="utf-8"))["style"] == "modern-colloquial"
a = FakeApi(); T.translate_all(a, SRC, "novel", "", "", wd, ns()); assert a.calls == 0                      # same style -> reuse
a = FakeApi(); T.translate_all(a, SRC, "novel", "", "", wd, ns(style_id="literary-fable")); assert a.calls == 1   # other style -> redo
# old record without a style field is accepted (and reported), not silently re-translated
wd2 = tempfile.mkdtemp(); rec = json.load(open(T.chunk_path(wd, 1), encoding="utf-8")); rec.pop("style")
json.dump(rec, open(T.chunk_path(wd2, 1), "w", encoding="utf-8"), ensure_ascii=False)
a = FakeApi(); T.translate_all(a, SRC, "novel", "", "", wd2, ns()); assert a.calls == 0
# non-novel modes: style id empty, nothing changes
wd3 = tempfile.mkdtemp(); a = FakeApi(); T.translate_all(a, SRC, "article", "", "", wd3, ns(mode="article", style_id="")); assert a.calls == 1
# the style text really reaches the system prompt
assert "اصل صفر" in T.build_system("novel", d, "")

print("style OK")
