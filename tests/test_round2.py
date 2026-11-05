import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import json, os, sys, tempfile, threading, types
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import tarjoman as T

# ---------- fakes for OCR page selection ----------
calls = {"insert": [], "ocr": [], "saved": []}
class FakeDoc:
    def __init__(self, n): self.page_count = n
    def insert_pdf(self, src, from_page, to_page): calls["insert"].append((from_page, to_page))
    def save(self, path): open(path, "wb").write(b"%PDF-fake"); calls["saved"].append(path)
    def close(self): pass
class FakePymupdf:
    TOTAL = 15
    @staticmethod
    def open(path=None): return FakeDoc(FakePymupdf.TOTAL if path else 0)
sys.modules["pymupdf"] = FakePymupdf

def parse_pages(spec, total):  # identical to ocr_extract.parse_pages
    if not spec or not spec.strip(): return list(range(total))
    picked = set()
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1); picked.update(range(int(a) - 1, int(b)))
        elif part: picked.add(int(part) - 1)
    return sorted(p for p in picked if 0 <= p < total)

def run_ocr(path, workdir):
    assert not os.path.exists(os.path.join(workdir, "indra-out")), "stale indra-out not cleaned"
    calls["ocr"].append(path)
    os.makedirs(os.path.join(workdir, "indra-out"))  # what Indra would leave behind
    return [{"page": 1, "lines": [{"text": "x"}]}]
fake_ocr = types.ModuleType("ocr_extract"); fake_ocr.parse_pages = parse_pages; fake_ocr.run_ocr = run_ocr
sys.modules["ocr_extract"] = fake_ocr

pdf = os.path.join(tempfile.mkdtemp(), "book.pdf"); open(pdf, "wb").write(b"%PDF-1")
wd = tempfile.mkdtemp()

def reset(): calls["insert"].clear(); calls["ocr"].clear(); calls["saved"].clear()

# non-contiguous pages, document order kept, only subset is OCRed
T.ocr_selected_pages(pdf, "2-4,8,11-13", wd)
assert calls["insert"] == [(p, p) for p in (1, 2, 3, 7, 10, 11, 12)], calls["insert"]
assert calls["ocr"] == [os.path.join(wd, "ocr_input.pdf")], calls["ocr"]
# same call again -> cache, no OCR
reset(); T.ocr_selected_pages(pdf, "2-4,8,11-13", wd); assert not calls["ocr"]
# different pages -> OCR again; stale indra-out from the previous run must be cleaned (asserted in run_ocr)
reset(); T.ocr_selected_pages(pdf, "2,5,9", wd)
assert calls["insert"] == [(1, 1), (4, 4), (8, 8)] and len(calls["ocr"]) == 1
# whole book -> original file, no subset built
wd2 = tempfile.mkdtemp(); reset(); T.ocr_selected_pages(pdf, "", wd2)
assert calls["ocr"] == [pdf] and not calls["insert"]
# file changed -> cache invalid
reset(); os.utime(pdf, (1, 1)); T.ocr_selected_pages(pdf, "", wd2); assert calls["ocr"] == [pdf]
# out of range
try: T.ocr_selected_pages(pdf, "50", tempfile.mkdtemp()); assert False
except SystemExit as e: assert e.code == 1
print("ocr pages OK")

# ---------- Api.add_usage is thread-safe ----------
api = T.Api("http://x", "k", "m")
def work():
    for _ in range(20000): api.add_usage({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
ts = [threading.Thread(target=work) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
assert api.total_usage == {"prompt_tokens": 160000, "completion_tokens": 320000, "total_tokens": 480000}, api.total_usage
print("lock OK")

# ---------- polish validation + context ----------
T1 = "این یک ترجمهٔ فارسی کامل است با عدد ۱۰۰ و ۳٫۱۴ و ۲۰۱۹ برای خواننده."
P_OK = "این برگردانی فارسی و کامل است با عدد ۱۰۰ و ۳٫۱۴ و ۲۰۱۹ برای خواننده."
class FakeApi:
    model = "fake"
    def __init__(self, translate, polish): self.translate, self.polish, self.prompts, self.polish_calls = list(translate), list(polish), [], 0
    def add_usage(self, u): pass
    def chat(self, system, user, temperature=0.3, max_tokens=8192):
        if system.startswith("تو یک ویراستار"):
            self.polish_calls += 1
            r = self.polish.pop(0) if self.polish else (P_OK, "stop")
            if isinstance(r, Exception): raise r
            return {"content": r[0], "finish_reason": r[1], "usage": {}}
        self.prompts.append(user)
        return {"content": self.translate.pop(0) if self.translate else T1, "finish_reason": "stop", "usage": {}}
def ns(**kw):
    d = dict(qc_loose=False, polish=True, max_tokens=8192, workers=1, retry_failed=False,
             trust_old_checkpoints=False, glossary_text="", polish_model="", mode="novel")
    d.update(kw); return types.SimpleNamespace(**d)
SRC = ["Value 100 and 3.14 in 2019 are important here for the reader.",
       "Second chunk text about the same thing for the reader again."]

def one(reply, **kw):
    a = FakeApi([T1], [reply]); d = tempfile.mkdtemp()
    r = T.translate_all(a, SRC[:1], "novel", "", "", d, ns(**kw)); return r[0], a, d

rec, a, d = one((P_OK, "stop")); assert rec["polished"] == P_OK and rec["status"] == "ok"
for bad, label in [(("", "stop"), "empty"), ((P_OK, "length"), "length"),
                   (("کوتاه", "stop"), "short"), ((P_OK.replace("۲۰۱۹", "۲۰۲۰"), "stop"), "number"),
                   (("This is English now with 100 and 3.14 and 2019 for the reader.", "stop"), "english")]:
    rec, a, d = one(bad)
    assert rec["polished"] is None and rec.get("polish_reason"), (label, rec.get("polished"))
    assert T.chunk_path and T._best(rec) == T1, label                       # first translation kept
    # rejected polish is NOT retried on the next run ...
    a2 = FakeApi([], []); T.translate_all(a2, SRC[:1], "novel", "", "", d, ns()); assert a2.polish_calls == 0, label
    # ... unless --retry-failed
    a3 = FakeApi([], [(P_OK, "stop")]); r3 = T.translate_all(a3, SRC[:1], "novel", "", "", d, ns(retry_failed=True))
    assert a3.polish_calls == 1 and r3[0]["polished"] == P_OK and "polish_reason" not in r3[0], label
# API error in polish: nothing recorded, retried next run
rec, a, d = one(RuntimeError("boom")); assert rec["polished"] is None and "polish_reason" not in rec
a2 = FakeApi([], [(P_OK, "stop")]); r2 = T.translate_all(a2, SRC[:1], "novel", "", "", d, ns()); assert r2[0]["polished"] == P_OK

# retroactive polish: chunk 1 done earlier WITHOUT --polish, now run with --polish; chunk 2 context sees polished text
d = tempfile.mkdtemp()
T.translate_all(FakeApi([T1], []), SRC[:1], "novel", "", "", d, ns(polish=False))
a = FakeApi([T1], [(P_OK, "stop")])
r = T.translate_all(a, SRC, "novel", "", "", d, ns())
assert r[0]["polished"] == P_OK and r[1]["polished"] == P_OK and a.polish_calls == 2
assert len(a.prompts) == 1 and "برگردانی" in a.prompts[0] and "ترجمهٔ فارسی کامل" not in a.prompts[0].split("متن تکهٔ جاری")[0].split("[ترجمهٔ فارسی تکهٔ قبل")[1], a.prompts[0]
print("polish OK")
