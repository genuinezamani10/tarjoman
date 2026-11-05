# Tarjoman — Agent Playbook (v1.5 → complete core)

Audience: an autonomous coding agent (OpenCode) working in the `tarjoman` repo.
Language of this file: English. Language of the product, prompts, style files and user-facing logs: **Persian**.
Read sections 1–3 fully before touching anything. Then execute phases **T0 → T9 in order**. Do not skip a phase; do not start a phase before the previous one's acceptance checks pass.

---

## 1. What Tarjoman is

A stdlib-only Python CLI (`tarjoman.py`) that translates English PDFs into fluent Persian through any OpenAI-compatible API (OpenRouter, OpenAI, Gemini, or local Ollama/LM Studio).

Pipeline: `extract_text` (PyMuPDF, or local OCR via Indra for scanned PDFs) → chunking → glossary → per-chunk translation with QC and checkpoints → optional `--polish` pass → Markdown + RTL PDF.

Three modes with different behavior:

| Mode | Priority | Execution |
|---|---|---|
| `article` | consistent terminology | parallel (4 workers), glossary, first-use English term in parentheses (deterministic dedupe pass) |
| `textbook` | exactness | parallel, number check (deterministic), formulas/code untouched |
| `novel` | **natural prose that does not feel translated** | sequential, previous-chunk context, 3-layer style system, optional polish |

**The product goal (owner's words):** a program that translates without a human, and the Persian must not read like machine translation.

## 2. Hard rules (non-negotiable)

1. **The repo is PUBLIC. Never commit copyrighted text**: no passages from books (source or translation), no hand-edited versions of them, no model outputs of such passages. Allowed: short owner-authored style examples (≤ 2 sentences each) and synthetic text you write yourself. Before **every** commit run the scan in section 7. A match outside the allowlist blocks the commit.
2. **Git is the single source of truth.** Other tools (a chat assistant) have delivered files and, twice, working copies changed under another process. One branch per phase (`t0-sync`, `t1-loader`, …). Touch only the files listed for the phase. Never rewrite history without explicit owner approval.
3. **Do not change fidelity rules.** `MODE_INSTRUCTIONS` and the "no additions / no omissions / no summarising" instruction stay as they are. Style may change *how* something is said, never *what* is said.
4. **Do not rewrite Persian style rules on your own taste.** You may restructure, deduplicate, fix contradictions and add tests; new stylistic rules need owner-supplied examples (see T2, T7).
5. **No new dependencies** unless a specific, demonstrated bug requires one. Runtime stays stdlib + the optional `pymupdf`, `fpdf2`, `arabic-reshaper`, `python-bidi`.
6. **Checkpoint compatibility.** `src_hash` = SHA-1 of (mode + chunk text) only. The model name is deliberately *not* part of it. The record stores `style` (profile id). Do not change these semantics.
7. **Tests first.** For each change write the failing test, see it fail, then fix. (Lesson: a patch silently did not apply while the new tests were green, because the tests did not exercise the fix.) All tests run offline with a fake API.
8. **Unicode hygiene.** The code touches invisible or look-alike characters: ZWNJ `U+200C`, Persian/Arabic comma `U+060C`, Arabic thousands separator `U+066C`, decimal separator `U+066B`, Persian digits `U+06F0–06F9`. In code and tests refer to them by escape (`"\u200c"`) or by explicit constant, never by pasting look-alikes; exact-text search/replace fails on them.
9. Log messages and CLI help are Persian, short, and say what to do next.

## 3. Owner decisions already made (do not re-litigate)

- **Default register for ALL novels: standard colloquial** (`رو`, `اون`, `می‌ره`, `باهاش`): narration and dialogue. "Clean spoken Persian, not heavy slang, not stiff bookish." The accusative marker is always `رو`, and `را`/`رو` must not be mixed in one text (exception: in-story formal documents or quotes).
- **Hand-written/hand-edited passages are NOT a style source** in this repo. Do not reintroduce them, do not derive rules or thresholds from them. (Two comments in `scripts/tj_checks.py` still mention them: reword in T0.)
- Teaching the model = **rules + before/after pairs in the prompt** (T2). Weight fine-tuning only after the owner has at least several hundred reviewed pairs. Not in scope here.
- Deterministic checks come before any LLM-based judge. No mandatory LLM evaluator per chunk.
- Known weak spot to remember: tests so far used a weak free model; every threshold must be re-checked with the owner's real model (T7).

## 4. Repo map (expected at start of T0)

```
tarjoman.py                       CLI, pipeline, checkpoints, style loader (NOVEL_CORE, NOVEL_PROFILES, resolve_style, read_style)
scripts/extract_text.py           PDF text extraction
scripts/ocr_extract.py            Indra OCR helpers (do not edit unless a task says so)
scripts/fa_normalize.py           OCR output normalisation
scripts/build_pdf.py              RTL PDF (per-line wrap, base_dir="R", cell(new_x="LMARGIN"))
scripts/tj_checks.py              src_hash, atomic_write_text, check_numbers, dedupe_first_use_parens, check_polish
scripts/eval_style.py             compare candidates to a private gold set (chrF, word similarity, style stats)
styles/novel-core.md              layer 1: register-neutral rules + preferred lexicon + punctuation
styles/profile-modern-colloquial.md   layer 2 (default)
styles/profile-romance-urban.md   layer 2 (extends colloquial)
styles/profile-literary-fable.md  layer 2 (literary register)
styles/books/animal-farm-glossary.txt layer 3: per-book glossary ("source = target", '#' lines are comments)
styles/style-guide-novel.md       LEGACY (used only by --style-profile legacy)
styles/tarjoman-novel-glossary.md LEGACY + the owner's original general glossary. Do not rewrite.
styles/tarjoman-article-style.md  article mode style
styles/README.md                  how profiles work
tests/                            offline tests, run: python3 tests/run_all.py
```

Style prompt assembly (novel): `novel-core.md` → profile file(s) → `--style-extra` files → `--style-sample`; the book glossary goes through `--glossary` (replaces the auto-generated glossary when the file exists).

## 5. Phases

### T0 — Sync and verify (no new features)
**Goal:** the repo on the owner's machine equals the intended v1.5 state and is provably consistent.
**Do:**
1. Add the five style files if missing: `styles/novel-core.md`, `styles/profile-modern-colloquial.md`, `styles/profile-romance-urban.md`, `styles/profile-literary-fable.md`, `styles/README.md`. Add `tests/` (offline tests + `run_all.py`). Do **not** overwrite `styles/tarjoman-novel-glossary.md` or `styles/style-guide-novel.md` if they already exist in git; `git diff` and ask the owner on any difference.
2. Reference check: every `*.md`/`*.txt` file name referenced in `tarjoman.py` exists (`glossary.txt` is generated at runtime and is the only allowed exception).
3. Reword the two comments in `scripts/tj_checks.py` near `POLISH_WORD_RATIO` / `POLISH_PARA_SPLIT_MAX` so they no longer mention a book or hand-edited passages (keep the numbers, justify them generically: "allow paragraph splitting and moderate expansion, but reject summaries and truncation").
4. Add `.gitignore` entries: `.env`, `output/`, `*.fa.md`, `*.fa.pdf`, `__pycache__/`, `tests/golden/`, `styles/private/`, `eval/`.
5. Run `python3 tests/run_all.py` and the scan from section 7.
**Acceptance:** all tests pass; scan is clean; `python3 -c "import tarjoman"` works from the repo root; `git status` clean after commit.
**Commit:** `chore: sync style layers, tests, gitignore (T0)`.

### T1 — Style loader polish and a no-API dry run
**Goal:** make the style system inspectable without spending API money.
**Files:** `tarjoman.py`, `tests/test_style.py`, `styles/README.md`.
**Do:**
1. `--list-profiles`: print available profiles with their files and one-line descriptions (first heading of each profile file), exit.
2. `--dry-run`: run extraction + chunking + glossary-file read + style resolution, print: chunk count and word totals, resolved style files with char counts, rough prompt size (chars ÷ 3 as token estimate), and the first 600 chars of the final system prompt. **No API call**, exit 0.
3. Startup log line for novel mode: `🎨 سبک: <profile> | فایل‌ها: … | <N> کاراکتر`. Warn if the style text exceeds 14 000 characters (long prompts lower adherence).
**Acceptance:** tests for `--list-profiles` and `--dry-run` (using a tiny synthetic PDF generated in the test if PyMuPDF/fpdf2 are present, otherwise skip with a clear message); `--dry-run` never constructs an `Api` object (assert via monkeypatch).
**Commit:** `feat: --list-profiles and --dry-run (T1)`.

### T2 — Before/after pairs ("teach the model")
**Goal:** transfer the owner's taste through examples, which move style more than rules do.
**Files:** `tarjoman.py`, `scripts/style_pairs.py` (new), `styles/pairs/README.md` (new), `tests/test_pairs.py` (new).
**Format** (plain text, one pair per block, blocks separated by a line `---`; keys are English so RTL text cannot break parsing):
```
RAW: <model output, Persian>
FIXED: <owner's corrected Persian>
NOTE: <optional: what was changed deliberately, one line>
```
**Do:**
1. Parser with strict validation (RAW and FIXED required, non-empty, no duplicates), clear Persian error with line numbers.
2. Loader: `--pairs PATH` (repeatable) plus auto-load of `styles/pairs/<profile>.md` when it exists. `--max-pairs N` (default 12) and a hard character cap (default 6 000). Deterministic selection: file order, first N that fit.
3. Prompt section placed after the profile, in Persian: pairs show *how to transform*; the model must **not copy their content or imagery**; apply the pattern to the new text only.
4. Record `pairs_hash` (short SHA-1 of the injected pairs) in each chunk record. A mismatch only prints an info line; it does **not** mark chunks stale (owner decision: do not retranslate a book because one pair changed).
5. Privacy: tracked pair files contain only owner-authored short pairs (≤ 2 sentences each, no verbatim passages). Longer or sensitive pairs live in `styles/private/` (git-ignored) and are passed with `--pairs`.
**Acceptance:** parser tests (valid, missing key, empty, duplicate); cap and ordering tests; prompt contains the pairs section and the do-not-copy instruction; `src_hash` unchanged by pairs.
**Owner input needed:** the first real pairs (10–20). The agent ships the mechanism with 2–3 neutral synthetic pairs as a fixture, not as shipped style data.
**Commit:** `feat: before/after pairs in the style prompt (T2)`.

### T3 — Deterministic style flags
**Goal:** cheap, explainable signals that a chunk drifted toward "translationese".
**Files:** `scripts/tj_checks.py`, `tarjoman.py`, `tests/test_style_flags.py` (new).
**Do:** add `style_flags(text, profile) -> dict` with a single tunable table `STYLE_FLAG_RULES` (all thresholds in one place, each with a comment explaining the intent). Flags:
- `register_mix`: for the colloquial profiles, standalone `را` occurring outside guillemet quotes while `رو` also occurs (or `را` count ≥ 3 with zero `رو`). Whole-token matching with ZWNJ-aware boundaries.
- `calque_markers`: per-1000-words count of `توسط`, `در مورد`, `به منظور`, `علاوه بر این`, `همچنین`.
- `pronoun_density`: subject pronoun (`او`, `اون`, `آنها`) per sentence above a threshold.
- `long_sentences`: any sentence over N words (default 45) — informational.
Store flags in the chunk record (`style_flags`), print a per-run summary table at the end (chunk → flags). **No automatic action** in this phase.
**Acceptance:** unit tests with synthetic Persian strings for each flag (positive and negative cases, including quotes and ZWNJ forms); flags never raise on empty text; records written before this phase load fine.
**Commit:** `feat: deterministic style flags (T3)`.

### T4 — Opt-in targeted retry for flagged chunks
**Goal:** use the flags to repair, without paying for it by default.
**Files:** `tarjoman.py`, `tests/test_style_retry.py` (new).
**Do:** `--style-retry`. For a chunk with status `ok` and at least one actionable flag (`register_mix`, `calque_markers`), make **one** extra request using the existing hint mechanism (list the concrete flags, e.g. the offending tokens). Accept the new output only if it passes all existing QC (word ratio, Persian share, numbers, not truncated) **and** has strictly fewer flags; otherwise keep the original and log why. Log the extra token cost.
**Acceptance:** fake-API tests: accepted case, rejected-because-worse case, rejected-because-QC-fails case, disabled-by-default case, retry never loops.
**Commit:** `feat: --style-retry (T4)`.

### T5 — Glossary pipeline completion
**Goal:** a per-book glossary must not disable name extraction.
**Files:** `tarjoman.py`, `scripts/tj_checks.py` (glossary helpers), `tests/test_glossary.py` (new), `styles/README.md`.
**Do:**
1. `--glossary-seed PATH`: seed lines (`source = target`, `#` comments ignored) are merged with the auto-generated glossary; **seed wins** on duplicate sources; result saved to `work/glossary.txt`. `--glossary` keeps its current meaning (file replaces auto-generation) and the README must say so in one sentence.
2. `--glossary-grow K` (default off): in novel mode, after every K translated chunks extract *new* proper names/terms from those chunks only and **append** them; never edit or remove existing lines. Respect the owner's manual edits to `work/glossary.txt`.
3. Parse tolerance for bullets, numbering and `**bold**` in model-generated glossary lines (reuse `parse_glossary_sources`).
**Acceptance:** tests for merge precedence, comment stripping, append-only growth, and that growth never runs in parallel modes.
**Commit:** `feat: glossary seed and growth (T5)`.

### T6 — Private golden-set harness
**Goal:** measure style changes on the owner's own material without ever committing it.
**Files:** `scripts/run_golden.py` (new), `scripts/eval_style.py`, `tests/test_eval.py` (new), `tests/golden/README.md` (new, tracked; everything else under `tests/golden/` is ignored).
**Do:**
1. `run_golden.py DIR --profile NAME [--pairs …] [--glossary …] [--label X]`: for every `<id>.src.txt` in DIR, build the system prompt exactly as `translate_one` does (same `build_system`, `read_style`), call the API once per passage, write `<id>.<label>.txt`. No PDF involved.
2. `eval_style.py` compares `<id>.<label>.txt` against `<id>.gold.txt` (owner-private) and prints chrF, word similarity and the style statistics; add the `style_flags` counts per candidate.
3. Tests use synthetic text generated in a temp dir (never real book text) and a fake API.
**Acceptance:** `run_golden.py` + `eval_style.py` run end-to-end on synthetic data; the README states in bold that gold and source files must never be committed and that `.gitignore` enforces it.
**Commit:** `feat: private golden harness (T6)`.

### T7 — A/B protocol and calibration (owner in the loop)
**Goal:** replace opinions with measurements, then fix defaults.
**Do (agent):** write `docs/AB_PROTOCOL.md` and a helper `scripts/ab_blind.py` that takes candidate files for the same passage, shuffles and relabels them (A/B/C…), writes the blind sheet for the owner, and stores the key separately.
**Variants to compare per mode (≥ 3 passages each):** (a) profile only, (b) profile + pairs, (c) + `--polish`, (d) + `--style-retry`.
**Do (owner):** read blind, pick, score 1–5 for "does not feel translated" and "faithful". Agent records only labels, scores and metrics in `docs/decisions.md` (**no text**).
**Calibrate** `STYLE_FLAG_RULES`, `POLISH_WORD_RATIO`, `RATIO_*` and `FA_MIN` from owner-approved text, never from model output, using the owner's real model. Update defaults accordingly.
**Acceptance:** `docs/decisions.md` exists with the chosen defaults and the numbers behind them; owner sign-off recorded in the commit message.
**Commit:** `docs: A/B decisions and calibrated thresholds (T7)`.

### T8 — Output quality (independent items; ship each separately)
1. `build_pdf.py`: strip paired `**…**` and `__…__` emphasis markers from model output; in textbook mode keep fenced code blocks and formula lines with their line breaks (monospace, left-to-right block). Regression PDF test (needs `fpdf2`; skip cleanly if absent). Remember: the first RTL fix was validated only with fakes in the sandbox — verify on real `fpdf2`, `arabic-reshaper`, `python-bidi` and a multi-line paragraph that starts with an English word.
2. `extract_text.py`: running heads on alternating pages (frequency threshold ≈ 30% after stripping digits); heading detection from font size (emit `## `); merge paragraphs split across pages (previous does not end with sentence punctuation and next starts lowercase); column ordering with full-width blocks in the middle of a page.
3. `ocr_extract.chunk`: the hard-coded `1600`-word split threshold must follow `--chunk-words` (e.g. `target * 1.25`).
Each item: synthetic-input unit tests, no copyrighted PDFs.

### T9 — Release
1. Update `README.md` (install, usage per mode, style layers, pairs, glossary options, eval harness, privacy rules), add `CHANGELOG.md`, set a `__version__`.
2. Full regression: `python3 tests/run_all.py`, `--list-profiles`, `--dry-run` on a synthetic PDF, scan from section 7.
3. Tag `v1.6` (or the next minor) after the owner approves.

## 6. Definition of Done — "complete core"
- All tests pass offline; `--dry-run` works without network or key.
- Style system: core + profile + (optional) pairs + book glossary resolve deterministically; changing profile re-translates only chunks of another profile; pairs and glossary changes never silently invalidate a finished book.
- Deterministic flags are recorded per chunk and summarised per run; `--style-retry` is opt-in and never worsens a chunk.
- Glossary seed/growth work and never overwrite manual edits.
- Golden harness works end-to-end on synthetic data; no private data is tracked (verified by scan and `.gitignore`).
- Thresholds in `tj_checks.py` and `tarjoman.py` are calibrated on owner-approved text with the owner's real model, and the decision is recorded.
- Copyright scan clean; README and `styles/README.md` match the code.

## 7. Copyright and privacy scan (run before every commit)

```bash
# 1) tracked files: book names/characters that must not appear (owner-authored glossary examples are the only allowlisted file)
git grep -nE "<owner-maintained pattern list>" -- . ':!styles/tarjoman-novel-glossary.md'

# 2) nothing private is staged
git diff --cached --name-only | grep -E '^(tests/golden/|styles/private/|eval/|output/)' && echo "BLOCK: private path staged"

# 3) history check (read-only)
git log --all --oneline -- tests/golden eval styles/private
```
Keep the pattern list in a local, git-ignored file (`.scan_patterns`) so the repo itself never contains the strings being scanned for. Any hit blocks the commit; ask the owner.

## 8. Lessons learned (do not repeat)
- Check that a patch applied before trusting green tests; add the failing test first.
- `--glossary FILE` replaces the auto-generated glossary (character names are then never extracted) → T5.
- Choosing a Persian word for an English term is the owner's call; examples carry the owner's taste, rules should be transformation rules (never "add an image/scene/heading/closing line").
- Mixing `را` and `رو` inside one passage is the most visible inconsistency → T3 flag, T4 repair.
- Do not make an example change meaning to satisfy a register rule (e.g., replacing a horse-drawn carriage with a car).
- Rendering fixes validated only with fake libraries are provisional until run with the real ones.

## 9. Commands cheat sheet
```bash
python3 tests/run_all.py
python3 tarjoman.py --list-profiles                       # after T1
python3 tarjoman.py book.pdf --mode novel --dry-run       # after T1
python3 tarjoman.py book.pdf --mode novel --pages 1-10
python3 tarjoman.py book.pdf --mode novel --style-profile romance-urban --glossary styles/books/<book>-glossary.txt
python3 tarjoman.py book.pdf --mode novel --polish --style-retry            # after T4
python3 scripts/run_golden.py tests/golden/<set> --profile modern-colloquial --label base   # after T6
python3 scripts/eval_style.py tests/golden/<set> --cand base
```
