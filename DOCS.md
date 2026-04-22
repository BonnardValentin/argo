# argos

Local-first professional knowledge graph. Ingests PRs / issues / threads / diffs,
extracts structured decisions, stores them as markdown, and (soon) links them
into a graph.

## Status

**Step 1 — GitHub ingestion + decision extraction.** Working.
**Step 2 — Local read commands (`kb show`, `kb recent`).** Working, stdlib-only.
**Step 3 — Redis vector index + `kb ask`.** Working; embedder swappable.
**Step 4 — Hermes Linker (graph edges).** Working; LLM classifier with heuristic fallback; edges persist in `data/knowledge/_graph/edges.json`.
**Step 5 — Graph CLI (`kb graph / trace / why / path`).** Working; offline traversal + optional Claude synthesis for `kb why`.
**Step 6 — Galaxy View (web UI).** Working; Vite + React + react-force-graph-2d; reads static `graph.json` produced by `kb export`.

Next steps (not built yet): LLM answer synthesis for `kb ask`.

## Layout

```
argos/
├── argos/
│   ├── config.py            # env settings
│   ├── models.py            # pydantic contracts (RawArtifact, KnowledgeNode, …)
│   ├── ingestion/github.py  # GitHub → RawArtifact (deterministic)
│   ├── extraction/extractor.py  # RawArtifact → KnowledgeNode | None (LLM, tool-use)
│   ├── storage/markdown.py  # node ↔ .md with YAML frontmatter
│   ├── reader.py            # parse .md → title + section dict (stdlib)
│   ├── local_index.py       # list + rank by timestamp (stdlib)
│   ├── utils.py             # id matching, formatting (stdlib)
│   ├── embedding.py         # Embedder protocol; OpenAI + hash fallback
│   ├── indexer.py           # Redis FT vector index + linker orchestration
│   ├── search.py            # embed query + KNN search
│   ├── linker.py            # Hermes: typed edges (LLM or heuristic)
│   ├── graph.py             # GraphLoader, Navigator (BFS/DFS), GraphCLI
│   └── cli.py               # `kb` entrypoint
└── data/knowledge/          # markdown (canonical source of truth)
    ├── decisions/
    ├── discussions/
    ├── incidents/
    ├── meetings/
    └── _graph/
        └── edges.json       # derived graph (regenerate with `kb index`)
```

## Install

```bash
cd argos
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env to set GITHUB_TOKEN and ANTHROPIC_API_KEY
```

## Run

### Ingest

```bash
kb ingest github anthropics/anthropic-sdk-python --max 5 --no-issues
```

Flags: `--max N` (default 20), `--since 2025-01-01`, `--issues/--no-issues`,
`--prs/--no-prs`. Output lands in `data/knowledge/*.md`.

### Browse

```bash
# List the 10 most recent nodes (default)
kb recent

# List the 5 most recent
kb recent 5

# Show a node — exact id, prefix, or substring all work
kb show decision-graphql-api
kb show graphql
```

### Semantic search

Needs Redis Stack (for the `FT.*` commands). Either:

```bash
# One-liner
docker run -d -p 6379:6379 --name argos-redis redis/redis-stack:latest

# Or with RedisInsight UI on :8001 + :5540
docker compose up -d
```

Build (or refresh) the index, then ask:

```bash
kb index                       # walks data/knowledge/ and writes embeddings
kb index --reset               # drop + rebuild (needed if you change dim/model)

kb ask "why did we choose graphql?"
kb ask "caching strategy decisions"
kb ask "queue saturation" -k 3
```

Output:

```
query: why did we choose graphql?

[+0.812] decision:decision-graphql-api
    Use GraphQL for the public API
    › Adopt GraphQL (Apollo Server) as the single public API. REST endpoints will be deprecated…

[+0.574] meeting:meeting-api-roadmap
    API roadmap sync — Q2
    › Freeze REST v1 changes; all new surfaces land in the GraphQL endpoint.
```

**Embedder selection** (via env, see `.env.example`):

- Leave `ARGOS_EMBEDDING_API_KEY` blank → uses the deterministic `HashEmbedder` (no network, weak semantics, good for local dev).
- Set `ARGOS_EMBEDDING_API_KEY` → uses an OpenAI-compatible `/embeddings` endpoint. Point `ARGOS_EMBEDDING_BASE_URL` at any compatible service (OpenAI, Ollama, vLLM, etc.).
- Changing `ARGOS_EMBEDDING_DIM` or the model requires `kb index --reset` (the FT index pins dimensionality at create time).

### Graph (Hermes Linker)

`kb index` automatically runs the linker after embedding. For each node it
retrieves the top-K similar neighbors from Redis and classifies each pair
into one of: `depends_on`, `contradicts`, `refines`, `caused_by`, `related_to`
— or skips. Edges land in `data/knowledge/_graph/edges.json`.

```bash
kb index                  # default: embed + link
kb index --no-link        # skip the linker phase
kb index --link-k 8       # consider top-8 neighbors per source
kb index --verbose        # log every candidate + rejected edge
kb index --reset          # full rebuild (index + edges)
```

**Backends:**
- **LLMClassifier (preferred)** — one batched Anthropic tool-use call per source node, low latency. Active whenever `ANTHROPIC_API_KEY` is set.
- **HeuristicClassifier (fallback)** — no-network, cosine-only. Emits *only* `related_to` edges (directional relations can't be inferred from similarity alone). Tune with `ARGOS_LINKER_HEURISTIC_THRESHOLD`.

**Confidence = the gate on what enters the graph.** Computed as:

```
LLM mode:        conf = 0.6 × llm_self_confidence + 0.4 × cosine_similarity
heuristic mode:  conf = cosine_similarity
```

Both inputs are clamped to [0, 1]. Edges with `conf < ARGOS_LINKER_MIN_CONFIDENCE`
(default **0.6**) are logged under DEBUG and dropped. The blend keeps the LLM
grounded: a confidently-asserted edge with weak retrieval similarity gets
tempered down; a near-duplicate cosine match doesn't get auto-promoted without
semantic backup.

Storage contract for `edges.json`:

```json
[
  {
    "source_id": "decision-graphql-api",
    "target_id": "meeting-api-roadmap",
    "type": "refines",
    "confidence": 0.82,
    "reason": "Decision operationalizes the roadmap commitment to GraphQL-only new surfaces."
  }
]
```

`upsert` is keyed on `(source_id, target_id, type)` — re-running `kb index`
converges to a stable set rather than appending duplicates.

If `kb show <query>` matches multiple files, you get a numbered picker:

```
3 matches:
  [1] decision-graphql-api
  [2] discussion-graphql-rate-limit
  [3] incident-graphql-timeouts
pick: 2
```

`kb recent` uses the `timestamp:` field from each file's frontmatter, falling
back to filesystem mtime when the field is missing or unparseable.

### Graph exploration (step 5)

Four terminal commands over the edges produced by the linker. No Redis, no
network required (except `kb why` when Claude is configured).

```bash
kb graph <id>                    # immediate neighborhood, grouped by direction
kb trace <id> [depth]            # DFS tree of outgoing edges (default depth 2)
kb trace <id> 3 --direction both # walk both directions; arrows disambiguate
kb why <id>                      # 2-4 sentence synthesis from graph context
kb path <id_a> <id_b>            # BFS shortest path (undirected by default)
kb path a b --directed           # respect edge direction
```

**Traversal algorithm.** `kb trace` uses iterative DFS with a shared `visited`
set across the whole tree: a repeat-visit yields a `(↩ cycle)` leaf instead of
recursing. Children at each level are sorted by `(type, target_id, source_id)`
so output is stable across runs. `kb path` uses standard BFS; without
`--directed`, each edge is walked in both directions (connectivity search),
otherwise only source→target. The rendered chain preserves each edge's actual
direction in the arrows (`—[type]→` for forward, `←[type]—` for backward).

**`kb why` synthesis.** The graph module never calls an LLM itself — `cli.py`
injects a `synth_fn` only when `ANTHROPIC_API_KEY` is set. The system prompt
is scoped tightly: *use only information present in the provided material, do
not invent relationships*. Without a key, a deterministic bullet summary is
printed instead (same data, no prose).

Example:

```
$ kb graph graphql
Node: decision-graphql-api
  title: Use GraphQL for the public API
  type:  decision

OUTGOING:
  caused_by → meeting-api-roadmap  (conf 0.83)

INCOMING:
  depends_on ← meeting-api-roadmap  (conf 0.87)

$ kb trace graphql 2
decision-graphql-api
└── caused_by meeting-api-roadmap
    └── depends_on decision-graphql-api  (↩ cycle)

$ kb path cache-redis incident
decision-cache-redis —[related_to]→ incident-queue-saturation

1 hop(s)
```

## Design notes

- **Markdown is the source of truth.** Redis is a derived index; `kb index --reset` rebuilds from markdown alone.
- **Ingestion is deterministic.** No LLM calls — same input, same output.
- **Extraction filters hard.** The `emit` tool has a `keep=false` path and the system prompt pushes for precision over recall.
- **Embeddings are swappable.** `Embedder` is a Protocol; code references it, not a specific provider.
- **Agents are deferred to the linker.** Step 3 is still a straight deterministic pipeline — no autonomy.
