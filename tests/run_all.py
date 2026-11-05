#!/usr/bin/env python3
"""اجرای همهٔ تست‌های آفلاین (بدون API و بدون کتابخانه‌های PDF): python3 tests/run_all.py"""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
failed = []
for name in sorted(f for f in os.listdir(here) if f.startswith("test_") and f.endswith(".py")):
    r = subprocess.run([sys.executable, os.path.join(here, name)], capture_output=True, text=True)
    status = "PASS" if r.returncode == 0 else "FAIL"
    print(f"{status}  {name}")
    if r.returncode != 0:
        failed.append(name)
        print((r.stdout + r.stderr)[-1500:])
sys.exit(1 if failed else 0)
