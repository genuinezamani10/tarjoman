import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import json, os, sys, tempfile, types
sys.path.insert(0, ".")
import tarjoman as T

class FakeApi:
    def __init__(self, replies): self.replies = list(replies); self.calls = 0; self.model = "fake"
    def chat(self, system, user, temperature=0.3, max_tokens=8192):
        self.calls += 1
        txt = self.replies.pop(0) if self.replies else "این یک ترجمهٔ فارسی کامل است با عدد ۱۰۰ و ۳٫۱۴ و ۲۰۱۹."
        return {"content": txt, "finish_reason": "stop", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

def ns(**kw):
    d = dict(qc_loose=False, polish=False, max_tokens=8192, workers=1, retry_failed=False,
             trust_old_checkpoints=False, glossary_text="", polish_model="")
    d.update(kw); return types.SimpleNamespace(**d)

chunks = ["Value 100 and 3.14 in 2019 are important here for the reader."]
good = "این یک ترجمهٔ فارسی کامل است با عدد ۱۰۰ و ۳٫۱۴ و ۲۰۱۹ برای خواننده."
bad  = "این یک ترجمهٔ فارسی کامل است برای خواننده بدون هیچ عددی."

# 1) textbook: first reply drops numbers -> retry with good -> status ok, 2 calls
wd = tempfile.mkdtemp()
api = FakeApi([bad, good])
recs = T.translate_all(api, chunks, "textbook", "", "", wd, ns())
assert recs[0]["status"] == "ok" and api.calls == 2 and recs[0]["attempts"] == 2, (recs[0]["status"], api.calls)
saved = json.load(open(T.chunk_path(wd, 1), encoding="utf-8"))
assert saved["src_hash"]
assert not [f for f in os.listdir(wd) if f.startswith(".tmp_")]

# 2) rerun, same text -> checkpoint used, 0 calls
api = FakeApi([])
T.translate_all(api, chunks, "textbook", "", "", wd, ns())
assert api.calls == 0

# 3) changed source text -> stale, retranslated
api = FakeApi([good])
recs = T.translate_all(api, ["Value 100 and 3.14 in 2019 changed text for the reader."], "textbook", "", "", wd, ns())
assert api.calls == 1 and recs[0]["status"] == "ok"

# 4) changed mode -> stale
api = FakeApi([good])
T.translate_all(api, ["Value 100 and 3.14 in 2019 changed text for the reader."], "article", "", "", wd, ns())
assert api.calls == 1

# 5) old record without hash: stale by default, trusted with flag
wd2 = tempfile.mkdtemp()
old = {"index": 1, "status": "ok", "translation": good}
json.dump(old, open(T.chunk_path(wd2, 1), "w", encoding="utf-8"), ensure_ascii=False)
api = FakeApi([good]); T.translate_all(api, chunks, "textbook", "", "", wd2, ns()); assert api.calls == 1
wd3 = tempfile.mkdtemp()
json.dump(old, open(T.chunk_path(wd3, 1), "w", encoding="utf-8"), ensure_ascii=False)
api = FakeApi([]); r = T.translate_all(api, chunks, "textbook", "", "", wd3, ns(trust_old_checkpoints=True))
assert api.calls == 0 and r[0]["status"] == "ok"

# 6) both attempts bad -> suspicious, kept, note mentions numbers
wd4 = tempfile.mkdtemp()
api = FakeApi([bad, bad])
r = T.translate_all(api, chunks, "textbook", "", "", wd4, ns())
assert r[0]["status"] == "suspicious"

# 7) parallel path + corrupt json record is tolerated
wd5 = tempfile.mkdtemp()
open(T.chunk_path(wd5, 1), "w").write("{broken")
api = FakeApi([good, good])
r = T.translate_all(api, chunks * 2, "textbook", "", "", wd5, ns(workers=2))
assert all(x["status"] == "ok" for x in r)

# 8) novel: no number check even if numbers vanish
wd6 = tempfile.mkdtemp()
api = FakeApi(["او به خانه رفت و در را بست و نشست و فکر کرد به همه چیز در آن شب سرد."])
r = T.translate_all(api, ["He went home 100 times and closed the door and sat and thought about it."], "novel", "", "", wd6, ns())
assert r[0]["status"] == "ok", r[0]
print("integration OK")
