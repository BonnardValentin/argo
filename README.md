# argos

Local-first professional knowledge graph. Ingests PRs, issues, and meeting
notes, extracts structured decisions as markdown, and links them into a typed
graph backed by Redis vector search.

Markdown is the canonical source of truth. Redis and the graph are derived
artifacts — rebuildable from markdown alone.

## Quick start

```bash
docker compose up -d                          # Redis Stack + RedisInsight

python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env                          # set ANTHROPIC_API_KEY, GITHUB_TOKEN

kb ingest github <owner>/<repo> --max 5       # fetch + extract
kb index                                      # embed + link
kb ask "why did we choose graphql?"
```

## Commands

| | |
|---|---|
| `kb ingest github owner/repo` | Fetch PRs/issues, extract structured knowledge, write markdown |
| `kb recent [N]` | Latest nodes, newest first |
| `kb show <id>` | Pretty-print a node (substring match, picker on ambiguity) |
| `kb index` | Embed nodes into Redis + run the Hermes linker |
| `kb ask "..."` | Semantic KNN search |

## How it works

```
Sources → Ingestor → Extractor (LLM) → Markdown ←→ Redis index ← Linker (LLM)
```

- **Ingestion** is deterministic (raw HTTP, no LLM).
- **Extraction** uses Claude tool-use with a strict `keep=false` path — precision over recall.
- **Storage** is markdown with YAML frontmatter, nested by node type: `decisions/`, `incidents/`, `meetings/`, `discussions/`.
- **Vector search** rides Redis Stack's RediSearch (FLAT, cosine). Embedder is swappable — OpenAI-compatible or deterministic hash fallback for offline use.
- **Linker** (Hermes) classifies each pair into `depends_on`, `contradicts`, `refines`, `caused_by`, or `related_to`. Edges persist in `data/knowledge/_graph/edges.json`, gated at confidence ≥ 0.6.

See [DOCS.md](DOCS.md) for the full build log, configuration reference, and
step-by-step rationale.

## Status

Working end-to-end through step 4 (linker). Deferred: `kb graph` renderer, web
UI, LLM answer synthesis for `kb ask`.
