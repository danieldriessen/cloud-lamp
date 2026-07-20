#!/usr/bin/env python3
# ==============================================================================
# tools/build-manual.py — render docs/user-manual.md into docs/user-manual.pdf
#
# Usage:
#   python3 tools/build-manual.py
#
# What it does:
#   1. Converts docs/user-manual.md (the editable source of truth) to HTML.
#   2. Wraps it in a print stylesheet: A4, branded cover page, table of
#      contents with page numbers, running footer ("Page X of Y").
#   3. Writes docs/user-manual.pdf via WeasyPrint.
#
# The PDF is committed to the repository and served at the PERMANENT manual
# URL (sticker QR code + web-app book icon — see MANUAL_URL below). After
# editing user-manual.md, re-run this script and commit both files together.
#
# Requirements: pip install markdown weasyprint  (WeasyPrint additionally
# needs the pango native library: brew install pango)
# ==============================================================================

import datetime
import re
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "user-manual.md"
OUT = ROOT / "docs" / "user-manual.pdf"
LOGO = ROOT / "assets" / "cloud-lamp-logo.png"

# Permanent manual URL — must match web/app.html (MANUAL_URL), the sticker QR
# code and docs/device-credentials.md. NEVER change it once stickers exist.
MANUAL_URL = "https://github.com/danieldriessen/cloud-lamp/blob/main/docs/user-manual.pdf"

CSS = """
@page {
  size: A4;
  margin: 22mm 18mm 22mm 18mm;
  @bottom-left {
    content: "Cloud-Lamp \\2014 User Manual";
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 8pt; color: #8a97a5;
  }
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 8pt; color: #8a97a5;
  }
}
@page cover {
  margin: 0;
  @bottom-left { content: none; }
  @bottom-right { content: none; }
}

* { box-sizing: border-box; }
html { font-size: 10.5pt; }
body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #1c2733; line-height: 1.55; margin: 0;
}

/* ---------- Cover ---------- */
.cover {
  page: cover;
  height: 297mm; width: 210mm;
  background: linear-gradient(180deg, #cde9ff 0%, #eaf6ff 55%, #ffffff 100%);
  text-align: center;
  position: relative;
}
.cover .logo { width: 92mm; margin-top: 52mm; }
.cover h1 {
  font-size: 30pt; font-weight: 700; letter-spacing: 0.5pt;
  color: #133a5e; margin: 14mm 0 3mm;
}
.cover .subtitle { font-size: 12.5pt; color: #4a6076; margin: 0; }
.cover .footer {
  position: absolute; bottom: 16mm; left: 0; right: 0;
  font-size: 9pt; color: #6b7c8d;
}
.cover .footer .maker {
  font-size: 12pt; font-weight: 600; color: #2b4763;
  letter-spacing: 0.8pt; margin-bottom: 2.5mm;
}

/* ---------- Table of contents ---------- */
.toc { page-break-before: always; page-break-after: always; }
.toc h2 {
  font-size: 17pt; color: #133a5e; border-bottom: 2pt solid #cde9ff;
  padding-bottom: 2mm; margin: 10mm 0 6mm;
}
.toc ol { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 0 0 3.2mm; font-size: 11pt; }
.toc a {
  color: #1c2733; text-decoration: none; display: block;
}
.toc a::after {
  content: leader(".") " " target-counter(attr(href), page);
  color: #8a97a5;
}

/* ---------- Body ---------- */
.manual { padding-top: 2mm; }
.manual h2 {
  font-size: 15pt; color: #133a5e; margin: 9mm 0 3.5mm;
  border-bottom: 1.6pt solid #cde9ff; padding-bottom: 1.6mm;
  page-break-after: avoid;
}
.manual h2:first-child { margin-top: 0; }
.manual p { margin: 0 0 3mm; }
.manual a { color: #1e6fb8; text-decoration: none; }
.manual code {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: 9pt; background: #f0f5fa; border-radius: 2pt;
  padding: 0.4pt 2.5pt; color: #133a5e;
}
.manual ul, .manual ol { margin: 0 0 3.5mm; padding-left: 6mm; }
.manual li { margin-bottom: 1.6mm; }
.manual blockquote {
  margin: 4mm 0; padding: 3mm 4.5mm;
  background: #f0f7ff; border-left: 2.5pt solid #7db8e8;
  border-radius: 0 2mm 2mm 0; color: #2b4763;
  page-break-inside: avoid;
}
.manual blockquote p { margin: 0 0 1.5mm; }
.manual blockquote p:last-child { margin-bottom: 0; }
.manual table {
  width: 100%; border-collapse: collapse; margin: 3.5mm 0 5mm;
  font-size: 9.5pt; page-break-inside: avoid;
}
.manual th {
  text-align: left; background: #eaf3fb; color: #133a5e;
  padding: 2mm 3mm; border: 0.6pt solid #c9dcec;
}
.manual td { padding: 2mm 3mm; border: 0.6pt solid #d8e5f0; vertical-align: top; }
.manual tr:nth-child(even) td { background: #f7fafd; }
.manual hr { display: none; }  /* section rules are redundant in the PDF */
.manual strong { color: #10222f; }
.manual > p:last-child, .manual > p:last-child em { color: #6b7c8d; font-size: 9pt; }
"""

HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Cloud-Lamp — User Manual</title>
<style>{css}</style></head>
<body>
<div class="cover">
  <img class="logo" src="{logo}" alt="Cloud-Lamp">
  <h1>User Manual</h1>
  <p class="subtitle">Decorative Wi-Fi LED lamp &middot; controlled by one button or your phone</p>
  <div class="footer">
    <div class="maker">DD Productions</div>
    Revision {revision} &middot; always describes the latest firmware<br>
    {manual_url}
  </div>
</div>
<nav class="toc">
  <h2>Contents</h2>
  <ol>{toc}</ol>
</nav>
<div class="manual">
{body}
</div>
</body>
</html>"""


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    # The cover page carries the title — drop the markdown H1.
    text = re.sub(r"^# .*\n", "", text, count=1)

    md = markdown.Markdown(extensions=["tables", "toc"])
    body = md.convert(text)
    # Markdown tables need a header row, but e.g. the technical-data table
    # uses an empty one — drop empty <thead>s so no blank band is rendered.
    body = re.sub(r"<thead>\s*<tr>\s*(?:<th>\s*</th>\s*)+</tr>\s*</thead>", "", body)

    toc_items = "".join(
        f'<li><a href="#{t["id"]}">{t["name"]}</a></li>'
        for t in md.toc_tokens
    )

    html = HTML_SHELL.format(
        css=CSS,
        logo=LOGO.as_uri(),
        revision=datetime.date.today().strftime("%B %Y"),
        manual_url=MANUAL_URL,
        toc=toc_items,
        body=body,
    )

    HTML(string=html, base_url=str(ROOT)).write_pdf(str(OUT))
    print(f"OK: {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
