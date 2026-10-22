# Tarjoman — ترجمان

**Translate PDFs into Persian with your own API key.** Tarjoman takes any PDF — an article, a textbook, a novel, even a **scanned** one — and returns a **right-to-left Persian PDF** (set in the Vazirmatn typeface) plus a Markdown version.

All you need is an API key from any OpenAI-compatible provider (OpenRouter, OpenAI, Gemini, …) — or run it completely free with a **local model** (Ollama / LM Studio). Everything else is handled by Tarjoman.

## Features

- **Three translation modes** for three kinds of text (see the table below)
- **Fully local OCR** for scanned PDFs, powered by [Indra OCR](https://huggingface.co/datalab-to/indra-ocr) — CPU-only, no GPU, and your files are never sent to any cloud OCR service
- **Persian text normalizer** that fixes common right-to-left OCR mix-ups (e.g. Urdu `بہتر` → Persian `بهتر`, Arabic `رفيق` → `رفیق`)
- **Living glossary**: key terms and proper names are extracted from the document first, then applied consistently across every chunk
- **Quality control**: each chunk's word-count ratio is checked; an abnormal chunk is retranslated once and flagged if it stays abnormal (never silently dropped), plus a final word-count integrity check
- Deterministic text extraction with PyMuPDF: two-column detection, repeated header/footer removal, chunking on paragraph boundaries
- A **separate model per mode** if you want one (e.g. a strong literary model for novels, a cheap fast model for articles)

## Translation modes

| Mode | `--mode` value | Best for | Behavior |
|---|---|---|---|
| Article | `article` (default) | Papers & academic text | Fluent, scholarly Persian; the English equivalent of a term is given in parentheses only at its first occurrence |
| Textbook | `textbook` | Textbooks & course notes | Examples, exercises and formulas keep their structure; formulas, code, variables and numbers are never altered; explanatory, teaching tone |
| Novel | `novel` | Fiction & novels | Storyteller prose (clean colloquial-standard narration); style guide customizable with your own prose sample |

## How it works

```
PDF ──► text extraction (PyMuPDF) ──► if scanned: local OCR (Indra)
    ──► Persian normalization ──► living glossary ──► chunk-by-chunk translation (your API)
    ──► word-ratio & integrity checks ──► assembly ──► PDF + Markdown
```

## Installation & usage

Requirements: **Python 3.10+** and an API key from any OpenAI-compatible provider (or a local model).

```bash
# 1) Get the project and create a virtual environment
git clone https://github.com/genuinezamani10/tarjoman.git
cd tarjoman
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2) Configure your key and model
cp .env.example .env
# edit .env and fill in TARJOMAN_API_KEY and TARJOMAN_MODEL

# 3) Run
.venv/bin/python tarjoman.py book.pdf --mode novel
.venv/bin/python tarjoman.py paper.pdf                    # article (default)
.venv/bin/python tarjoman.py lesson.pdf --mode textbook --pages 1-10
```

Output lands in `output/<file-name>/`: `<name>.fa.md` and `<name>.fa.pdf`.

**Font:** the PDF output needs the Vazirmatn typeface. Download `Vazirmatn-Regular.ttf` and `Vazirmatn-Bold.ttf` from the [Vazirmatn releases page](https://github.com/rastikerdar/vazirmatn/releases) and put them in a `fonts/` folder next to the project. (Without the font, use `--no-pdf` to produce Markdown only.)

**Free local models:** if you run Ollama, just put this in `.env`:

```
TARJOMAN_BASE_URL=http://localhost:11434/v1
TARJOMAN_API_KEY=local
TARJOMAN_MODEL=<your installed model name>
```

### Command-line options

| Option | Description |
|---|---|
| `pdf` | Path to the input PDF (required) |
| `--mode` | `article` \| `textbook` \| `novel` (default: `article`) |
| `--pages` | Page range such as `1-5` or `1,4-6` (default: all pages) |
| `--model` / `--base-url` / `--api-key` | Override `.env` values for this run |
| `--title` | Custom title for the output document |
| `--style-sample` | Path to a prose sample in your preferred style (novel mode) |
| `--outdir` | Output directory |
| `--no-pdf` | Produce Markdown only |

You can also define a model per mode: `TARJOMAN_MODEL_ARTICLE`, `TARJOMAN_MODEL_TEXTBOOK`, `TARJOMAN_MODEL_NOVEL`.

## Local OCR (Indra)

- A 1M-parameter ONNX model by Datalab; model download is about **76 MB** (once, on the first scanned PDF)
- CPU-only — roughly **0.5 s per page** on a 2-core machine
- 80+ languages, including **Persian** (a dedicated right-to-left recognizer), with layout detection and correct column reading order
- Limitations: handwriting and heavily degraded scans read poorly, and complex tables may come out scrambled; it excels on clean print

## Project structure

```
tarjoman.py              Main program — translation with your own API
.env.example             Sample configuration (API key, base URL, models)
scripts/
  extract_text.py        Deterministic PDF text extraction (two-column, cleanup, chunking)
  ocr_extract.py         Scanned-PDF OCR with Indra + normalization and chunking
  fa_normalize.py        Persian normalizer (half-spaces, digits, Urdu/Arabic codepoints)
  build_pdf.py           Right-to-left Persian PDF builder (Vazirmatn)
styles/
  style-guide-novel.md        Novel style guide
  tarjoman-article-style.md   Article style & preferred terminology
  tarjoman-novel-glossary.md  Preferred novel vocabulary
requirements.txt         Python dependencies
fonts/                   Put the Vazirmatn fonts here (not shipped in the repo)
```

## FAQ

**Do I have to connect an API?**
Yes — Tarjoman is built so that everyone runs it with **their own key and model**: any OpenAI-compatible service (OpenRouter, OpenAI, Gemini), or completely free with a local model (Ollama). Configuration is a single `.env` file; a ready template (`.env.example`) is included.

**Do my files go online?**
OCR, text extraction and assembly all run on your own machine. The extracted text is sent for translation only to the provider you choose in `.env` — and if you pick a local model, no text ever leaves your machine.

**Does it work on Windows?**
The program itself runs anywhere Python runs. Only Indra OCR is officially tested on Linux and macOS (Apple Silicon); on Windows it may work but is not guaranteed.

**My PDF is handwritten or an old, worn scan. Will it work?**
Handwriting and degraded scans are supported by the OCR but read far less accurately than clean print. Tarjoman is designed for printed books and papers.

**Can I change the novel translation style?**
Yes — pass your own prose sample with `--style-sample`, or edit `styles/style-guide-novel.md`.

## License

- The code in this project: **MIT** (see `LICENSE`)
- Indra OCR model weights belong to Datalab and are under a **modified OpenRAIL-M** license (free for personal and research use) — see the [model page](https://huggingface.co/datalab-to/indra-ocr) for full terms.
- The Vazirmatn typeface is released under the OFL license.
