# 🥐 croissant-validation

A **stateless MCP server** for validating [MLCommons Croissant](https://mlcommons.org/working-groups/data/croissant/) dataset metadata — built as a working demonstration of the [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28), the revision that made the Model Context Protocol stateless.

**Live endpoint:** `https://croissant-validation.jetty.bot/mcp`

## Why this exists

The 2026-07-28 spec removed the `initialize`/`notifications/initialized` handshake and the `Mcp-Session-Id` header. Every request is now self-contained: protocol version and client capabilities travel in `_meta`, and servers advertise themselves via `server/discover`. That means an MCP server can run on plain serverless functions behind any load balancer — no sticky sessions, no shared session store.

This repo is exactly that: the [MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk) (`mcp==2.0.0`, released alongside the spec) serving Croissant validation from Vercel serverless functions. Validation is performed by the official [`mlcroissant`](https://github.com/mlcommons/croissant/tree/main/python/mlcroissant) library — the same checks as the MLCommons croissant-validator, previously hosted in the [mlcbakery](https://github.com/jettyio/mlcbakery) MCP server.

## Tools

| Tool | Description |
|------|-------------|
| `validate_croissant` | Validate a Croissant JSON-LD document (object or JSON string) against the Croissant schema. Returns per-check results, blocking `errors`, and non-blocking `warnings`. |
| `validate_croissant_url` | Fetch metadata from a URL (e.g. a Hugging Face dataset's `/croissant` endpoint) and validate it. |

## Connect

Claude Code:

```bash
claude mcp add --transport http croissant-validator https://croissant-validation.jetty.bot/mcp
```

Or any MCP client that speaks Streamable HTTP — clients on the 2025-era protocol still work; the SDK answers the legacy handshake alongside `server/discover`.

## One raw stateless request

No handshake — a single POST does everything:

```bash
curl -sS https://croissant-validation.jetty.bot/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -d '{
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
      "name": "validate_croissant_url",
      "arguments": {"url": "https://huggingface.co/api/datasets/mnist/croissant"},
      "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {}
      }
    }
  }'
```

The `params._meta` envelope replaces the old `initialize` handshake — the protocol version and client capabilities ride along on every request instead of being negotiated up front. (The server rejects 2026-07-28 requests without it.)

## Development

```bash
uv sync
uv run pytest -q                                  # validation + stateless HTTP round-trip tests
uv run uvicorn croissant_mcp.server:app --reload  # local server on :8000
```

Layout:

- `croissant_mcp/validation.py` — mlcroissant-backed validation (JSON well-formedness → Croissant schema; warnings surfaced from `mlcroissant`'s issue tracker)
- `croissant_mcp/server.py` — `MCPServer` definition, tools, landing page, and the stateless Streamable HTTP ASGI app (`stateless_http=True, json_response=True`)
- `api/index.py` — Vercel entrypoint
- `examples/` — a valid Croissant file ([Titanic, from the MLCommons repo](https://github.com/mlcommons/croissant/tree/main/datasets/1.0/titanic)) and an invalid variant (`invalid-not-a-dataset.json`, missing its `@type`)

Record-set generation checks (actually materializing data) are intentionally out of scope here — they can download arbitrarily large files, which doesn't belong in a serverless request. Schema validation is the static contract check.

## Deploy

Deployed on Vercel (Python runtime, Fluid Compute). The one serverless-specific consideration: `streamable_http_app()` starts its session manager via ASGI lifespan, which [Vercel now runs](https://vercel.com/changelog/fastapi-lifespan-events-are-now-supported-on-vercel). In stateless mode there is no cross-request state, so cold starts and horizontal scaling are free.

## Roadmap

- Wire into [Jetty](https://jetty.io) workflows as the validation step for an MCP-native version of [PDF → Croissant](https://mlcroissant.jetty.bot).

## License

MIT
