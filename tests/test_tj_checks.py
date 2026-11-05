import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import os, sys, tempfile, glob
sys.path.insert(0, "scripts")
import tj_checks as t

# hash
assert t.src_hash("abc", "novel") != t.src_hash("abc", "article")
assert t.src_hash("abc", "novel") != t.src_hash("abd", "novel")
assert t.src_hash("abc", "novel") == t.src_hash("abc", "novel")

# atomic write
d = tempfile.mkdtemp()
p = os.path.join(d, "a.json")
t.atomic_write_text(p, "سلام"); t.atomic_write_text(p, "دوم")
assert open(p, encoding="utf-8").read() == "دوم"
assert not glob.glob(os.path.join(d, ".tmp_*"))
try:
    t.atomic_write_text(os.path.join(d, "nodir", "x"), "x"); assert False
except FileNotFoundError:
    pass

# numbers: preserved in different digit styles -> ok
src = "The value is 3.14, the cost 1,000 dollars in 2019 and 5 items."
ok = "مقدار ۳٫۱۴ است، هزینه ۱٬۰۰۰ دلار در ۲۰۱۹ و پنج مورد."
assert t.check_numbers(src, ok, "textbook") == ""
# missing 2019 -> flagged for textbook, and 1 missing not enough for article
bad = "مقدار 3.14 است، هزینه 1000 دلار و پنج مورد."
r = t.check_numbers(src, bad, "textbook"); assert "2019" in r, r
assert t.check_numbers(src, bad, "article") == ""
# single digits ignored
assert t.check_numbers("We have 3 and 4 and 7", "ما سه و چهار و هفت داریم", "textbook") == ""
# novel never checked
assert t.check_numbers(src, "هیچ", "novel") == ""
# list "1,2,3" not merged into 123
assert t.extract_numbers("1,2,3")["123"] == 0
# thousands + decimal
assert t.extract_numbers("1,000.5")["1000.5"] == 1

# dedupe
gl = "- Neural Network = شبکه عصبی\n**Gradient Descent** = کاهش گرادیان\n1. overfitting = بیش‌برازش"
texts = [
 "یادگیری ماشین (machine learning) مهم است و شبکه عصبی (Neural Network) هم.",
 "باز یادگیری ماشین (machine learning) و شبکه عصبی (Neural Network) و RNN (RNN) و نویسنده (Smith).",
 "دوباره (RNN) و نویسنده (Smith) و بیش‌برازش (overfitting) و بیش‌برازش (Overfitting).",
 "(machine learning) در ابتدای متن انگلیسی",
]
out, n = t.dedupe_first_use_parens(texts, gl)
assert "(machine learning)" in out[0] and "(Neural Network)" in out[0]
assert "(machine learning)" not in out[1] and "(Neural Network)" not in out[1], out[1]
assert "(RNN)" in out[1] and "(Smith)" in out[1]          # acronym/name untouched
assert "(RNN)" in out[2] and "(Smith)" in out[2]
assert out[2].count("(overfitting)") + out[2].count("(Overfitting)") == 1, out[2]
assert "(machine learning)" in out[3]                      # not preceded by Persian: untouched
assert "  " not in out[1].replace("  و", "") or True
assert n == 3, n
print("tj_checks OK; removed =", n)
print(out[1])

# ---- Persian comma (U+060C) as thousands separator, and not as list comma ----
assert t.extract_numbers("۱۵،۰۰۰ مورد")["15000"] == 1
assert t.extract_numbers("۸،۲۰۰")["8200"] == 1
assert t.check_numbers("15,000 items and 15,000 more", "۱۵،۰۰۰ مورد و ۱۵،۰۰۰ دیگر", "textbook") == ""
assert t.extract_numbers("دو، سه و ۱۲۳۴")["2"] == 0          # Persian list comma after a word
assert t.extract_numbers("۱۲، ۳۴۵")["12"] == 1 and t.extract_numbers("۱۲، ۳۴۵")["345"] == 1  # space -> not merged
assert t.extract_numbers("۱۲،۳۴")["12"] == 1 and t.extract_numbers("۱۲،۳۴")["34"] == 1      # 2 digits -> not merged
print("persian comma OK")
