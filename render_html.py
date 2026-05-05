"""Convert mathlib-build-deep-dive.md to a standalone HTML file with inlined SVGs."""
import re
import os
import markdown

INPUT = "mathlib-build-deep-dive.md"
OUTPUT = "mathlib-build-deep-dive.html"

with open(INPUT) as f:
    md_text = f.read()

# Convert markdown to HTML
html_body = markdown.markdown(
    md_text,
    extensions=["tables", "fenced_code", "codehilite", "toc", "attr_list"],
    extension_configs={"codehilite": {"guess_lang": False, "noclasses": True}},
)

# Inline SVGs: replace <img src="figs/X.svg" alt="..." /> with raw <svg> content
def inline_svg(match):
    src = match.group(1)
    alt = match.group(2) if match.lastindex >= 2 else ""
    if not os.path.exists(src):
        return match.group(0)
    with open(src) as f:
        svg = f.read()
    # Strip XML declaration if present
    svg = re.sub(r"<\?xml[^?]*\?>", "", svg).strip()
    # Strip DOCTYPE
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg).strip()
    return f'<figure class="figure"><figcaption class="figcaption">{alt}</figcaption>{svg}</figure>'

# Match either order of attributes: src first, or alt first.
html_body = re.sub(
    r'<img\s+alt="([^"]*)"\s+src="([^"]+\.svg)"\s*/?>',
    lambda m: inline_svg(re.match(r"", "")) or inline_svg_kw(m.group(2), m.group(1)),
    html_body,
) if False else html_body

def inline_svg_kw(src, alt):
    if not os.path.exists(src):
        return f'<img alt="{alt}" src="{src}">'
    with open(src) as f:
        svg = f.read()
    svg = re.sub(r"<\?xml[^?]*\?>", "", svg).strip()
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg).strip()
    return f'<figure class="figure"><figcaption class="figcaption">{alt}</figcaption>{svg}</figure>'

# Replace each form
html_body = re.sub(
    r'<img\s+alt="([^"]*)"\s+src="([^"]+\.svg)"\s*/?>',
    lambda m: inline_svg_kw(m.group(2), m.group(1)),
    html_body,
)
html_body = re.sub(
    r'<img\s+src="([^"]+\.svg)"\s+alt="([^"]*)"\s*/?>',
    lambda m: inline_svg_kw(m.group(1), m.group(2)),
    html_body,
)

CSS = """
:root {
  --fg: #1f2328; --bg: #ffffff; --muted: #57606a; --border: #d0d7de;
  --link: #0969da; --code-bg: #f6f8fa; --accent: #cf222e;
  --max-width: 760px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e6edf3; --bg: #0d1117; --muted: #8b949e; --border: #30363d;
    --link: #2f81f7; --code-bg: #161b22; --accent: #f85149;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 16px; line-height: 1.6; color: var(--fg); background: var(--bg);
  padding: 2rem 1rem 4rem;
}
main { max-width: var(--max-width); margin: 0 auto; }
h1, h2, h3, h4 { line-height: 1.25; margin-top: 2.2rem; margin-bottom: 0.8rem; }
h1 { font-size: 2rem; padding-bottom: .3em; border-bottom: 1px solid var(--border); }
h2 { font-size: 1.5rem; padding-bottom: .3em; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.2rem; }
h4 { font-size: 1.05rem; color: var(--muted); }
p { margin: 0.8rem 0; }
blockquote {
  margin: 1rem 0; padding: 0.6rem 1rem; border-left: 4px solid var(--border);
  color: var(--muted); background: var(--code-bg); border-radius: 4px;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 1.5rem; }
li { margin: 0.2rem 0; }
code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.9em; padding: 0.15em 0.35em; background: var(--code-bg); border-radius: 4px;
}
pre {
  background: var(--code-bg); border-radius: 6px; padding: 1rem; overflow-x: auto;
  font-size: 0.875rem; line-height: 1.45;
}
pre code { padding: 0; background: transparent; font-size: inherit; }
table {
  border-collapse: collapse; margin: 1rem 0; font-size: 0.92rem;
  display: block; overflow-x: auto; max-width: 100%;
}
table thead { background: var(--code-bg); }
th, td { border: 1px solid var(--border); padding: 0.4rem 0.7rem; text-align: left; }
th { font-weight: 600; }
tbody tr:nth-child(even) { background: rgba(0,0,0,0.02); }
@media (prefers-color-scheme: dark) {
  tbody tr:nth-child(even) { background: rgba(255,255,255,0.02); }
}
hr { border: 0; border-top: 1px solid var(--border); margin: 2.5rem 0; }
.figure {
  margin: 1.5rem 0; padding: 1rem; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg);
}
.figure svg { width: 100%; height: auto; max-width: 100%; display: block; }
.figcaption {
  color: var(--muted); font-size: 0.85rem; text-align: center;
  margin-bottom: 0.75rem; font-style: italic;
}
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anatomy of a 9-hour build — mathlib4 build-graph deep dive</title>
<style>{CSS}</style>
</head>
<body>
<main>
{html_body}
</main>
</body>
</html>
"""

with open(OUTPUT, "w") as f:
    f.write(html)

size = os.path.getsize(OUTPUT)
print(f"wrote {OUTPUT}: {size:,} bytes")
