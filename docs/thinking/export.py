"""Export the design doc (course-to-book-engine.html) to a PDF and to standalone sketch images for the README.

    uv run python docs/thinking/export.py
    -> docs/thinking/course-to-book-engine.pdf   (A4, light theme, via headless Chrome)
    -> docs/thinking/figures/<section>.svg       (each sketch, hand font and colours embedded)
The font file (Caveat, SIL Open Font License) is embedded so the sketches look the same on GitHub.
"""
import base64
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "course-to-book-engine.html"
CHROME = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium"]
TOKENS = {"--paper": "#fbfaf6", "--card": "#ffffff", "--ink": "#23303d", "--muted": "#66707b", "--rule": "#dfe3e2",
          "--pen": "#2c63c9", "--marker": "#f6cf4a", "--marker-ink": "#4d3a00", "--red": "#c4462b", "--green": "#2f8a57"}
PRINT_CSS = """<style>
@page { size: A4; margin: 14mm 12mm }
@media print {
  :root, :root[data-theme] { --paper:#ffffff !important; --card:#ffffff !important; --ink:#23303d; --muted:#5d6670; --rule:#d6dbda;
    --pen:#2c63c9; --marker:#f6cf4a; --marker-ink:#4d3a00; --red:#c4462b; --green:#2f8a57; color-scheme: light }
  html, body { background: #ffffff !important } body { padding-inline: 0 !important; font-size: 13.5px }
  main { display: block !important } main > * { margin-bottom: 16px }
  .part, h2 { break-after: avoid; page-break-after: avoid }
  .card, .tldr, .part-card, .lesson, figure { break-inside: avoid }
  .sk svg { min-width: 0 !important }
  .links a { border: 0; padding: 0; text-decoration: underline }
}
</style>"""
SVG_CSS = """@font-face{font-family:"Caveat";src:url(data:font/woff2;base64,FONT) format("woff2");font-weight:400 700}
svg{color:var(--ink);font-family:"Caveat",cursive} text{fill:currentColor}
.t{font-family:"Caveat",cursive;font-size:21px}.ts{font-family:"Caveat",cursive;font-size:17px;fill:var(--muted)}
.tp{font-family:"Caveat",cursive;font-size:20px;fill:var(--pen)}.tr{font-family:"Caveat",cursive;font-size:19px;fill:var(--red)}.tm{fill:var(--marker-ink)}
.ln{stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.lp{stroke:var(--pen);stroke-width:2.4;fill:none;stroke-linecap:round;stroke-linejoin:round}
.ld{stroke:var(--muted);stroke-width:1.8;fill:none;stroke-dasharray:6 5;stroke-linecap:round}
.lr{stroke:var(--red);stroke-width:2;fill:none;stroke-linecap:round}
.bx{fill:var(--card);stroke:currentColor;stroke-width:2}.bp{fill:var(--card);stroke:var(--pen);stroke-width:2.6}
.bm{fill:var(--marker);stroke:var(--marker);stroke-width:2}
.fill-pen{fill:var(--pen)}.fill-ink{fill:currentColor}.fill-green{fill:var(--green)}.fill-marker{fill:var(--marker)}
.rough{filter:url(#rough)}"""


def resolve(text):
    for name, value in sorted(TOKENS.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(f"var({name})", value)
    return text


def chrome():
    for c in CHROME:
        if Path(c).exists() or subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    raise SystemExit("Chrome not found")


def export_pdf(src):
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "print.html"
        page.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">' + PRINT_CSS + "</head><body>" + src + "</body></html>")
        subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                        f"--print-to-pdf={HERE / 'course-to-book-engine.pdf'}", page.as_uri()], check=True, capture_output=True)


def export_figures(src):
    font = base64.b64encode((HERE / "caveat-500-latin.woff2").read_bytes()).decode()
    css = resolve(SVG_CSS.replace("FONT", font))
    defs = re.search(r"<defs>(.*?)</defs>", src, re.S).group(1)
    out_dir = HERE / "figures"
    out_dir.mkdir(exist_ok=True)
    count = 0
    for section_id, body in re.findall(r'<section class="card" id="([^"]+)">(.*?)</section>', src, re.S):
        figure = re.search(r'<figure class="sk">\s*(<svg[^>]*>)(.*?)</svg>\s*</figure>', body, re.S)
        if not figure:
            continue
        open_tag, inner = figure.groups()
        view_box = re.search(r'viewBox="([^"]+)"', open_tag).group(1)
        width, height = view_box.split()[2:]
        label = re.search(r'aria-label="([^"]*)"', open_tag)
        (out_dir / f"{section_id}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" width="{width}" height="{height}" role="img"'
            + (f' aria-label="{label.group(1)}"' if label else "") + ">"
            + f"<defs>{defs}</defs><style>{css}</style>" + f'<rect width="100%" height="100%" fill="{TOKENS["--paper"]}"/>'
            + resolve(inner) + "</svg>")
        count += 1
    return count


if __name__ == "__main__":
    source = SRC.read_text()
    export_pdf(source)
    print({"pdf": str(HERE / "course-to-book-engine.pdf"), "figures": export_figures(source)})
