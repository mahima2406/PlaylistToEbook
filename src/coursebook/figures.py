"""Mermaid -> tightly cropped vector PDF using headless Chrome and Quarto's bundled mermaid.js.

LaTeX embeds the PDF as vector graphics (selectable text, sharp at any zoom).
Without Chrome, `render_vector` returns None and the caller falls back to a Quarto
mermaid block (raster PNG in PDF output). Results are cached by source hash.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from .core import digest

CHROME_CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff}}#out{{display:inline-block;padding:2px}}</style>
<script src="mermaid.min.js"></script></head><body><div id="out"></div><script>
mermaid.initialize({{startOnLoad:false, theme:"neutral", securityLevel:"strict",
  fontFamily:"Helvetica, Arial, sans-serif", flowchart:{{htmlLabels:false}}}});
mermaid.render("figure", {source}).then(({{svg}}) => {{
  const out = document.getElementById("out"); out.innerHTML = svg;
  const el = out.querySelector("svg"); const r = el.getBoundingClientRect();
  el.setAttribute("width", r.width); el.setAttribute("height", r.height);
  const page = document.createElement("style");
  page.textContent = `@page{{size:${{Math.ceil(r.width) + 6}}px ${{Math.ceil(r.height) + 6}}px;margin:0}}`;
  document.head.appendChild(page);
}});
</script></body></html>"""


def find_chrome():
    configured = os.environ.get("COURSEBOOK_CHROME")
    for candidate in ([configured] if configured else []) + CHROME_CANDIDATES:
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if path and os.path.exists(path):
            return path
    return None


def find_mermaid_js():
    quarto = shutil.which("quarto")
    if not quarto:
        return None
    root = Path(os.path.realpath(quarto)).parents[1]
    js = root / "share" / "formats" / "html" / "mermaid" / "mermaid.min.js"
    return js if js.exists() else None


def render_vector(source, out_dir):
    """Return the path of a vector PDF for `source`, or None if Chrome/mermaid.js is missing."""
    chrome, mermaid_js = find_chrome(), find_mermaid_js()
    if not chrome or not mermaid_js:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{digest({'src': source, 'mermaid': digest(mermaid_js.read_text())})[:16]}.pdf"
    if target.exists():
        return target
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copyfile(mermaid_js, Path(tmp) / "mermaid.min.js")
        page = Path(tmp) / "figure.html"
        page.write_text(PAGE.format(source=json.dumps(source)))
        result = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                                 "--virtual-time-budget=10000", "--allow-file-access-from-files",
                                 f"--print-to-pdf={target}", page.as_uri()],
                                capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not target.exists():
        raise ValueError(f"Chrome could not render a diagram: {result.stderr[-500:]}")
    return target
