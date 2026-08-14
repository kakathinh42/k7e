# k7e MCP server

Exposes k7e's compiled-knowledge retrieval to any MCP client (chat-agent,
Claude Desktop, IDE agents). The point: let the agent read **compact, compiled
wiki pages** instead of dumping **large raw documents** into the model context —
fewer tokens per call, faster retrieval (see `scripts/poc_token_savings.py`).

## Tools

| Tool | Purpose |
|------|---------|
| `search_wiki(query, limit=5)` | Permission-aware hybrid search → compact `{slug, title, snippet, score}` hits over compiled pages. |
| `get_wiki_page(slug)` | Full compiled Markdown for one page (synthesized + citation-backed at ingest). |

Both wrap the k7e HTTP API and forward caller identity headers, so results
respect the same permission filtering as the API.

## Install & run

```bash
uv pip install -e apps/mcp        # or: pip install -e apps/mcp
K7E_API_BASE=http://localhost:8001 k7e-mcp   # serves over stdio
```

Environment:

- `K7E_API_BASE` — k7e API origin (default `http://localhost:8001`).
- `WIKI_USER_ID` / `WIKI_USER_ROLES` — identity used for permission-aware
  retrieval (default `chat-agent` / `reader`).

## Connect chat-agent (or Claude Desktop)

```json
{
  "mcpServers": {
    "k7e": {
      "command": "k7e-mcp",
      "env": { "K7E_API_BASE": "http://localhost:8001" }
    }
  }
}
```

The agent then calls `search_wiki` to ground its answers in compiled company
knowledge.
