"""Landing page served at / — everything a human (or agent author) needs to connect."""

LANDING_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Croissant Validator — stateless MCP server</title>
<style>
  :root {
    --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --accent: #b45309;
    --card: #f7f5f2; --border: #e5e1da; --code-bg: #14120f; --code-fg: #f3ede2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14120f; --fg: #f3ede2; --muted: #a8a29e; --accent: #f59e0b;
      --card: #1e1b16; --border: #35302a; --code-bg: #0c0b09; --code-fg: #e7e0d3;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main { max-width: 46rem; margin: 0 auto; padding: 3rem 1.25rem 4rem; }
  h1 { font-size: 1.7rem; margin: 0 0 .25rem; }
  h1 .emoji { margin-right: .4rem; }
  h2 { font-size: 1.05rem; margin: 2.2rem 0 .6rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
  p { margin: .6rem 0; }
  a { color: var(--accent); }
  .sub { color: var(--muted); margin-top: 0; }
  .endpoint {
    display: block; background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: .8rem 1rem; font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: .95rem; overflow-x: auto; white-space: nowrap;
  }
  pre {
    background: var(--code-bg); color: var(--code-fg); border-radius: 10px;
    padding: 1rem; overflow-x: auto; font-size: .82rem; line-height: 1.5;
  }
  code { font-family: ui-monospace, "SF Mono", Menlo, monospace; }
  table { width: 100%; border-collapse: collapse; font-size: .95rem; }
  td, th { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; }
  td code { background: var(--card); border: 1px solid var(--border); border-radius: 5px; padding: .1rem .35rem; font-size: .85rem; }
  footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: .9rem; }
</style>
</head>
<body>
<main>
  <h1><span class="emoji">🥐</span>Croissant Validator</h1>
  <p class="sub">A stateless MCP server for validating
     <a href="https://mlcommons.org/working-groups/data/croissant/">MLCommons Croissant</a> dataset metadata.</p>

  <p>This server implements the <a href="https://modelcontextprotocol.io/specification/2026-07-28">MCP
  2026-07-28 specification</a> — the stateless protocol revision. There is no
  <code>initialize</code> handshake and no session ID: every request is
  self-contained, which is why this entire server runs on serverless functions.
  Validation is performed by the official
  <a href="https://github.com/mlcommons/croissant/tree/main/python/mlcroissant">mlcroissant</a> library.</p>

  <h2>Endpoint</h2>
  <span class="endpoint">https://croissant-validation.jetty.bot/mcp</span>

  <h2>Tools</h2>
  <table>
    <tr><th>Tool</th><th>Description</th></tr>
    <tr><td><code>validate_croissant</code></td>
        <td>Validate a Croissant JSON-LD document (object or JSON string) against the Croissant schema. Returns per-check results, errors, and warnings.</td></tr>
    <tr><td><code>validate_croissant_url</code></td>
        <td>Fetch metadata from a URL (e.g. a Hugging Face dataset's <code>/croissant</code> endpoint) and validate it.</td></tr>
    <tr><td><code>pdf_to_croissant</code></td>
        <td>Generate Croissant metadata from an academic paper: give it a PDF URL (or an <code>upload_id</code>, below) and a <a href="https://jetty.io">Jetty</a> agent reads the paper, writes <code>croissant.json</code>, and validates it — the MCP version of <a href="https://mlcroissant.jetty.bot">mlcroissant.jetty.bot</a>. Runs take 2–5 minutes.</td></tr>
    <tr><td><code>croissant_run_status</code></td>
        <td>Poll a running <code>pdf_to_croissant</code> job.</td></tr>
    <tr><td><code>croissant_run_result</code></td>
        <td>Fetch <code>croissant.json</code> (re-validated on the way out), <code>summary.md</code>, or <code>validation_report.json</code> from a completed run.</td></tr>
  </table>

  <h2>Local PDFs</h2>
  <p>MCP has no file-upload primitive, so local papers come in over plain
  HTTP. POST the PDF to <code>/upload</code>, then pass the returned
  <code>upload_id</code> to <code>pdf_to_croissant</code> instead of
  <code>pdf_url</code>:</p>
  <pre><code>curl -sS -F "file=@paper.pdf" \\
  https://croissant-validation.jetty.bot/upload</code></pre>
  <p>Hosted uploads are limited to ~4.5&nbsp;MB per request; larger papers
  (up to 15&nbsp;MB) should go through <code>pdf_url</code>.</p>

  <h2>Connect from Claude Code</h2>
  <pre><code>claude mcp add --transport http croissant-validator \\
  https://croissant-validation.jetty.bot/mcp</code></pre>

  <h2>One raw stateless request</h2>
  <p>No handshake — a single POST does everything:</p>
  <pre><code>curl -sS https://croissant-validation.jetty.bot/mcp \\
  -H 'Content-Type: application/json' \\
  -H 'Accept: application/json, text/event-stream' \\
  -H 'MCP-Protocol-Version: 2026-07-28' \\
  -d '{
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
      "name": "validate_croissant",
      "arguments": {"croissant": {"@type": "sc:Dataset", "name": "demo"}},
      "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {}
      }
    }
  }'</code></pre>
  <p>The <code>_meta</code> envelope replaces the old <code>initialize</code>
  handshake: the protocol version and client capabilities ride along on every
  request instead of being negotiated up front.</p>

  <footer>
    <a href="https://github.com/jettyio/croissant-validation">Source on GitHub</a> ·
    Powered by <a href="https://jetty.io">Jetty</a> ·
    See also <a href="https://mlcroissant.jetty.bot">PDF → Croissant</a>
  </footer>
</main>
</body>
</html>
"""
