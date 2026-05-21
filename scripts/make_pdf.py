"""Generate docs/RUNBOOK.pdf from docs/RUNBOOK.md.

Requires the `markdown` package (`pip install markdown`) and Microsoft Edge
(headless, ships with Windows 11). Run from the repo root.

Usage:
    python scripts/make_pdf.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "docs" / "RUNBOOK.md"
HTML_PATH = ROOT / "docs" / "RUNBOOK.html"
PDF_PATH = ROOT / "docs" / "RUNBOOK.pdf"

CSS = """
@page { size: Letter; margin: 0.75in 0.7in 0.85in 0.7in; }
:root {
  --fg: #1a1a1a;
  --muted: #555;
  --accent: #DC2626;
  --code-bg: #f4f4f4;
  --border: #e5e5e5;
}
* { box-sizing: border-box; }
html { font-size: 10pt; }
body {
  font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: var(--fg);
  line-height: 1.5;
  margin: 0;
}
h1 {
  font-size: 22pt;
  border-bottom: 3px solid var(--accent);
  padding-bottom: 0.3em;
  margin: 0 0 0.6em;
  page-break-after: avoid;
}
h2 {
  font-size: 15pt;
  color: var(--accent);
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.2em;
  margin-top: 1.6em;
  page-break-after: avoid;
}
h3 {
  font-size: 12pt;
  margin-top: 1.2em;
  page-break-after: avoid;
}
h4 { font-size: 10.5pt; margin-top: 1em; }
p, ul, ol { margin: 0.5em 0; }
ul, ol { padding-left: 1.6em; }
li { margin: 0.15em 0; }
code {
  font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
  font-size: 9pt;
  background: var(--code-bg);
  padding: 1px 5px;
  border-radius: 3px;
}
pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 10px 12px;
  overflow-x: auto;
  page-break-inside: avoid;
  margin: 0.7em 0;
}
pre code {
  background: transparent;
  padding: 0;
  font-size: 8.5pt;
  line-height: 1.45;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.7em 0;
  font-size: 9pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid var(--border);
  padding: 6px 9px;
  text-align: left;
  vertical-align: top;
}
th { background: #fafafa; font-weight: 600; }
tr:nth-child(even) td { background: #fafafa; }
blockquote {
  border-left: 3px solid var(--accent);
  margin: 0.5em 0;
  padding: 0.2em 0.9em;
  color: var(--muted);
}
hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2em 0;
}
a { color: var(--accent); text-decoration: none; }
strong { color: var(--fg); }
em { color: var(--muted); }
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def find_edge() -> str | None:
    for candidate in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("msedge")


def main() -> int:
    if not MD_PATH.exists():
        print(f"missing {MD_PATH}", file=sys.stderr)
        return 1

    md_text = MD_PATH.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["extra", "tables", "fenced_code", "toc", "sane_lists"],
    )
    html_full = HTML_TEMPLATE.format(title="Relay Runbook", css=CSS, body=html_body)
    HTML_PATH.write_text(html_full, encoding="utf-8")
    print(f"wrote intermediate {HTML_PATH} ({HTML_PATH.stat().st_size} bytes)")

    edge = find_edge()
    if edge is None:
        print("microsoft edge not found; HTML written but PDF skipped", file=sys.stderr)
        return 2

    cmd = [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}",
        HTML_PATH.as_uri(),
    ]
    print(f"running: {' '.join(cmd[:4])} ... {HTML_PATH.name}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"edge exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return result.returncode

    if not PDF_PATH.exists():
        print(f"edge ran but produced no PDF at {PDF_PATH}", file=sys.stderr)
        return 3

    # Clean up the intermediate HTML
    HTML_PATH.unlink()
    print(f"wrote {PDF_PATH} ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
