"""
Bicameral Visual Plans — auto-indexing static server.
Drop any .html file into plans/ and push to main.
The index page auto-discovers and lists all plans.
"""
import os
import re
import html
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

PLANS_DIR = Path(__file__).parent / "plans"

def slug_to_title(filename: str) -> str:
    """decision-ledger-mcp.html → Decision Ledger MCP"""
    name = filename.replace(".html", "")
    return " ".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())

def extract_meta(filepath: Path) -> dict:
    """Extract title and subtitle from the HTML file if present."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")[:4000]
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', content, re.IGNORECASE)
        page_title = (h1_match or title_match)
        title = page_title.group(1).strip() if page_title else slug_to_title(filepath.name)
        # Try to grab first .page-subtitle or .subtitle text
        sub_match = re.search(r'class="[^"]*subtitle[^"]*"[^>]*>([^<]{5,120})<', content, re.IGNORECASE)
        subtitle = sub_match.group(1).strip() if sub_match else ""
        return {"title": title, "subtitle": subtitle}
    except Exception:
        return {"title": slug_to_title(filepath.name), "subtitle": ""}

def build_index() -> str:
    plans = sorted(PLANS_DIR.glob("*.html"))
    rows = ""
    for plan in plans:
        meta = extract_meta(plan)
        stat = plan.stat()
        import datetime
        modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
        safe_title = html.escape(meta["title"])
        safe_sub = html.escape(meta["subtitle"])
        safe_name = html.escape(plan.name)
        rows += f"""
        <tr>
          <td><a href="/plans/{safe_name}">{safe_title}</a></td>
          <td class="dim">{safe_sub}</td>
          <td class="mono dim">{modified}</td>
        </tr>"""

    count = len(plans)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bicameral — Visual Plans</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,700;1,700&family=JetBrains+Mono:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #f6f5ff; --surface: #fff; --border: rgba(80,60,200,.09);
  --text: #1a1035; --dim: #6b6490;
  --accent: #5b4fff; --accent-dim: rgba(91,79,255,.08);
  --font: 'DM Sans',system-ui,sans-serif;
  --mono: 'JetBrains Mono','SF Mono',monospace;
  --display: 'Newsreader',Georgia,serif;
}}
@media(prefers-color-scheme:dark){{
  :root{{
    --bg:#0d0b1e; --surface:#15122a; --border:rgba(140,120,255,.1);
    --text:#e8e4ff; --dim:#9b96c4;
    --accent:#8b7dff; --accent-dim:rgba(139,125,255,.12);
  }}
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{
  background:var(--bg);
  background-image:
    repeating-linear-gradient(0deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px),
    repeating-linear-gradient(90deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px);
  color:var(--text); font-family:var(--font);
  min-height:100vh; padding:64px 40px;
}}
.wrap{{max-width:900px;margin:0 auto;}}
.label{{
  font-family:var(--mono);font-size:10px;font-weight:700;
  letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:12px;
}}
h1{{
  font-family:var(--display);font-style:italic;font-size:48px;
  font-weight:700;letter-spacing:-1.5px;line-height:1.05;margin-bottom:8px;
}}
.sub{{font-family:var(--mono);font-size:12px;color:var(--dim);margin-bottom:48px;}}
.count{{
  display:inline-block;font-family:var(--mono);font-size:11px;
  padding:3px 10px;border-radius:20px;
  background:var(--accent-dim);color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 25%,transparent 75%);
  margin-bottom:24px;
}}
table{{width:100%;border-collapse:collapse;}}
thead th{{
  font-family:var(--mono);font-size:10px;font-weight:700;
  letter-spacing:1px;text-transform:uppercase;color:var(--dim);
  text-align:left;padding:10px 16px;
  border-bottom:2px solid var(--border);
  background:color-mix(in srgb,var(--surface) 80%,var(--bg) 20%);
}}
tbody tr{{border-bottom:1px solid var(--border);transition:background .12s;}}
tbody tr:hover{{background:var(--accent-dim);}}
td{{padding:14px 16px;vertical-align:middle;}}
td a{{
  color:var(--text);text-decoration:none;font-weight:500;font-size:14px;
}}
td a:hover{{color:var(--accent);}}
.dim{{color:var(--dim);font-size:13px;}}
.mono{{font-family:var(--mono);font-size:11px;}}
.empty{{
  padding:48px 16px;text-align:center;color:var(--dim);
  font-family:var(--mono);font-size:12px;
}}
footer{{
  margin-top:64px;font-family:var(--mono);font-size:11px;color:var(--dim);
  border-top:1px solid var(--border);padding-top:20px;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="label">Bicameral · Implementation Plans</div>
  <h1>Visual Plans</h1>
  <p class="sub">Add a .html file to <code style="font-family:var(--mono);font-size:11px;background:var(--accent-dim);color:var(--accent);padding:1px 6px;border-radius:3px;">pilot/mcp/visual-plan/plans/</code> and push to main — it appears here automatically.</p>
  <div class="count">{count} plan{"s" if count != 1 else ""}</div>
  <table>
    <thead><tr><th>Plan</th><th>Description</th><th>Updated</th></tr></thead>
    <tbody>{"".join(rows) if plans else '<tr><td colspan="3" class="empty">No plans yet — drop a .html file in plans/ and push.</td></tr>'}
    </tbody>
  </table>
  <footer>Bicameral MCP &mdash; push to <code>pilot/mcp/visual-plan/plans/</code> on main to publish</footer>
</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default access log noise

    def send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])

        if path in ("/", "/index.html"):
            body = build_index().encode()
            self.send(200, "text/html; charset=utf-8", body)

        elif path.startswith("/plans/"):
            filename = path[len("/plans/"):]
            filepath = PLANS_DIR / filename
            if filepath.suffix == ".html" and filepath.is_file() and filepath.parent == PLANS_DIR:
                body = filepath.read_bytes()
                self.send(200, "text/html; charset=utf-8", body)
            else:
                self.send(404, "text/plain", b"Not found")

        else:
            self.send(404, "text/plain", b"Not found")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Bicameral visual plans serving on port {port}")
    server.serve_forever()
