from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from argos import indexer as redis_indexer
from argos.config import settings
from argos.extraction.extractor import Extractor
from argos.graph import Graph, GraphCLI, GraphLoader, GraphNavigator
from argos.ingestion.github import GitHubIngestor
from argos.linker import EdgeStore, get_linker
from argos.local_index import load_index, recent as indexer_recent
from argos.reader import parse_file
from argos.search import search as vector_search
from argos.storage.markdown import write_node
from argos.utils import format_timestamp, match_files, truncate

app = typer.Typer(no_args_is_help=True, help="Argos — local-first knowledge graph.")
ingest_app = typer.Typer(no_args_is_help=True, help="Pull raw artifacts from sources.")
app.add_typer(ingest_app, name="ingest")

console = Console()


@ingest_app.command("github")
def ingest_github(
    target: Annotated[str, typer.Argument(help="owner/repo")],
    since: Annotated[
        str | None,
        typer.Option(help="ISO date; only process artifacts updated after this."),
    ] = None,
    max_items: Annotated[
        int, typer.Option("--max", help="Max artifacts per kind.")
    ] = 20,
    include_issues: Annotated[bool, typer.Option("--issues/--no-issues")] = True,
    include_prs: Annotated[bool, typer.Option("--prs/--no-prs")] = True,
) -> None:
    """Ingest PRs and issues from a GitHub repo, extract knowledge, write markdown."""
    if not settings.github_token:
        console.print("[red]GITHUB_TOKEN not set[/red] — copy .env.example to .env")
        raise typer.Exit(code=2)
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY not set[/red] — copy .env.example to .env")
        raise typer.Exit(code=2)
    if "/" not in target:
        console.print("[red]target must be owner/repo[/red]")
        raise typer.Exit(code=2)

    owner, repo = target.split("/", 1)
    since_dt = datetime.fromisoformat(since) if since else None
    extractor = Extractor(settings.anthropic_api_key, settings.extraction_model)

    table = Table(title=f"Ingest {target}")
    table.add_column("kind")
    table.add_column("ref")
    table.add_column("result")

    kept = 0
    dropped = 0

    with GitHubIngestor(settings.github_token) as gh:
        streams = []
        if include_prs:
            streams.append(("pr", gh.iter_pulls(owner, repo, since=since_dt, max_items=max_items)))
        if include_issues:
            streams.append(("issue", gh.iter_issues(owner, repo, since=since_dt, max_items=max_items)))

        for kind, stream in streams:
            for artifact in stream:
                try:
                    node = extractor.extract(artifact)
                except Exception as exc:  # noqa: BLE001 — CLI should keep going
                    table.add_row(kind, artifact.source.ref or "?", f"[red]error: {exc}[/red]")
                    continue
                if node is None:
                    dropped += 1
                    table.add_row(kind, artifact.source.ref or "?", "[dim]noise[/dim]")
                    continue
                path = write_node(settings.data_dir, node)
                kept += 1
                table.add_row(
                    kind,
                    artifact.source.ref or "?",
                    f"[green]{node.type.value}[/green] → {path.relative_to(settings.data_dir.parent.parent) if path.is_relative_to(settings.data_dir.parent.parent) else path}",
                )

    console.print(table)
    console.print(f"[bold]kept[/bold] {kept}  [dim]dropped[/dim] {dropped}")


@ingest_app.command("local")
def ingest_local(
    path: Annotated[Path, typer.Argument(help="Path to a local repository root")],
    max_items: Annotated[
        int,
        typer.Option("--max", help="Cap on docs to process (0 = unlimited)."),
    ] = 0,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Extra glob patterns (relative to repo root). Repeatable.",
        ),
    ] = None,
    max_bytes: Annotated[
        int,
        typer.Option(
            "--max-bytes",
            help="Truncate docs larger than this (default 200 KB).",
        ),
    ] = 200_000,
) -> None:
    """Scan a local repo for docs (README, ARCHITECTURE, CLAUDE.md, docs/**,
    ADRs, …), extract structured knowledge, write markdown.

    Point at a checked-out repository root; the extractor decides what's
    signal. Idempotent — nodes with the same source ref overwrite in place.
    """
    from argos.ingestion.local_docs import DEFAULT_PATTERNS, LocalDocsIngestor

    if not settings.anthropic_api_key:
        console.print(
            "[red]ANTHROPIC_API_KEY not set[/red] — copy .env.example to .env"
        )
        raise typer.Exit(code=2)

    root = path.expanduser().resolve()
    if not root.is_dir():
        console.print(f"[red]not a directory:[/red] {root}")
        raise typer.Exit(code=2)

    patterns = DEFAULT_PATTERNS + tuple(include or ())
    ingestor = LocalDocsIngestor(root, patterns=patterns, max_bytes=max_bytes)
    extractor = Extractor(settings.anthropic_api_key, settings.extraction_model)

    table = Table(title=f"Ingest local docs: {root}")
    table.add_column("ref")
    table.add_column("result")

    kept = 0
    dropped = 0
    cap = max_items if max_items > 0 else None

    for artifact in ingestor.iter_docs(max_items=cap):
        try:
            node = extractor.extract(artifact)
        except Exception as exc:  # noqa: BLE001 — CLI should keep going
            table.add_row(artifact.source.ref or "?", f"[red]error: {exc}[/red]")
            continue
        if node is None:
            dropped += 1
            table.add_row(artifact.source.ref or "?", "[dim]noise[/dim]")
            continue
        out_path = write_node(settings.data_dir, node)
        kept += 1
        rel = (
            out_path.relative_to(settings.data_dir.parent.parent)
            if out_path.is_relative_to(settings.data_dir.parent.parent)
            else out_path
        )
        table.add_row(
            artifact.source.ref or "?",
            f"[green]{node.type.value}[/green] → {rel}",
        )

    console.print(table)
    console.print(f"[bold]kept[/bold] {kept}  [dim]dropped[/dim] {dropped}")


@app.command("show")
def show(
    node_id: Annotated[str, typer.Argument(help="Node id (filename stem or substring)")],
) -> None:
    """Show a single knowledge node by id."""
    index = load_index(settings.data_dir)
    if not index:
        typer.echo(f"no nodes in {settings.data_dir}")
        raise typer.Exit(code=1)

    matches = match_files([e.path for e in index], node_id)
    if not matches:
        typer.echo(f"no match for '{node_id}'")
        raise typer.Exit(code=1)

    path = matches[0] if len(matches) == 1 else _choose(matches)
    if path is None:
        raise typer.Exit(code=1)
    _print_node(path)


@app.command("recent")
def recent(
    n: Annotated[int, typer.Argument(help="How many to show")] = 10,
) -> None:
    """List the most recent knowledge nodes."""
    entries = indexer_recent(settings.data_dir, n)
    if not entries:
        typer.echo(f"no nodes in {settings.data_dir}")
        return
    for e in entries:
        typer.echo(f"{format_timestamp(e.timestamp)}  {e.id}")
        typer.echo(f"    {e.title}")
        if e.preview:
            typer.echo(f"    › {truncate(e.preview, 100)}")
        typer.echo("")


def _choose(paths: list[Path]) -> Path | None:
    typer.echo(f"{len(paths)} matches:")
    for i, p in enumerate(paths, 1):
        typer.echo(f"  [{i}] {p.stem}")
    try:
        raw = input("pick: ").strip()
    except (EOFError, KeyboardInterrupt):
        typer.echo("")
        return None
    try:
        idx = int(raw) - 1
        if not 0 <= idx < len(paths):
            raise IndexError
    except (ValueError, IndexError):
        typer.echo("invalid choice")
        return None
    return paths[idx]


def _print_node(path: Path) -> None:
    node = parse_file(path)
    typer.echo(f"id:    {node.id}")
    typer.echo(f"title: {node.title}")
    if node.timestamp:
        typer.echo(f"when:  {format_timestamp(node.timestamp)}")
    typer.echo(f"file:  {path}")
    typer.echo("")
    for name, content in node.sections.items():
        if not content.strip():
            continue
        typer.echo(f"## {name}")
        typer.echo("")
        typer.echo(content)
        typer.echo("")


@app.command("index")
def index_cmd(
    reset: Annotated[
        bool,
        typer.Option(
            "--reset/--no-reset",
            help="Drop the Redis index (and its documents) before rebuilding.",
        ),
    ] = False,
    link: Annotated[
        bool,
        typer.Option(
            "--link/--no-link",
            help="After indexing, run the Hermes linker to build graph edges.",
        ),
    ] = True,
    link_top_k: Annotated[
        int,
        typer.Option(
            "--link-k",
            help="How many similar candidates to consider per source node.",
        ),
    ] = 5,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose/--quiet",
            "-v/-q",
            help="Log candidates considered and edges rejected.",
        ),
    ] = False,
) -> None:
    """Build or refresh the Redis vector index; then run the linker."""
    _configure_logging(verbose)

    linker = None
    edge_store = None
    if link:
        linker = get_linker()
        edge_store = EdgeStore(settings.data_dir / "_graph" / "edges.json")
        if reset and edge_store.path.exists():
            edge_store.path.unlink()

    try:
        result = redis_indexer.build(
            settings.data_dir,
            redis_url=settings.redis_url,
            index_name=settings.redis_index_name,
            reset=reset,
            linker=linker,
            edge_store=edge_store,
            link_top_k=link_top_k,
        )
    except Exception as exc:  # redis down, auth failure, etc.
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"indexed {result.indexed} node(s) via {result.embedder.name} "
        f"→ {settings.redis_index_name}"
    )
    if result.linker_name:
        typer.echo(
            f"linked via {result.linker_name}: "
            f"+{result.edges_added} new, {result.edges_updated} updated, "
            f"{result.edges_total} total edges → {edge_store.path}"
        )


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("argos.linker").setLevel(level)


@app.command("ask")
def ask_cmd(
    query: Annotated[str, typer.Argument(help="Question or keywords")],
    k: Annotated[int, typer.Option("-k", "--top", help="How many results")] = 5,
) -> None:
    """Semantic search over the indexed nodes."""
    try:
        results = vector_search(
            query,
            redis_url=settings.redis_url,
            index_name=settings.redis_index_name,
            k=k,
        )
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        typer.echo("(did you run `kb index` yet?)", err=True)
        raise typer.Exit(code=1)

    if not results:
        typer.echo("no results")
        return

    typer.echo(f"query: {query}")
    typer.echo("")
    for r in results:
        preview = _decision_preview(r.path)
        typer.echo(f"[{r.score:+.3f}] {r.type}:{r.id}")
        typer.echo(f"    {r.title}")
        if preview:
            typer.echo(f"    › {truncate(preview, 160)}")
        typer.echo("")


def _decision_preview(path: Path) -> str:
    """Load the node's Decision section from markdown (source of truth),
    flattened to a single line for display."""
    if not path or not path.exists():
        return ""
    try:
        node = parse_file(path)
    except (OSError, UnicodeDecodeError):
        return ""
    decision = node.sections.get("Decision", "")
    non_blank = [line.strip() for line in decision.splitlines() if line.strip()]
    return " ".join(non_blank)


@app.command("export")
def export_cmd(
    out: Annotated[
        Path,
        typer.Option(
            "-o",
            "--out",
            help="Output JSON path. Relative paths resolve against the project root.",
        ),
    ] = Path("argos-ui/public/graph.json"),
) -> None:
    """Export the corpus + graph as a single static JSON for the web UI.

    Projection only — reads markdown + edges.json, writes one JSON. Does not
    modify the knowledge system.
    """
    import json
    from datetime import datetime, timezone

    from argos.config import PROJECT_ROOT
    from argos.linker import EdgeStore
    from argos.local_index import list_nodes
    from argos.reader import parse_file
    from argos.utils import type_from_path

    node_paths = list_nodes(settings.data_dir)
    nodes_out: list[dict] = []
    for path in node_paths:
        try:
            parsed = parse_file(path)
        except (OSError, UnicodeDecodeError):
            continue
        nodes_out.append(
            {
                "id": path.stem,
                "type": type_from_path(path),
                "title": parsed.title,
                "timestamp": parsed.timestamp.isoformat() if parsed.timestamp else None,
                "content": parsed.body or parsed.raw,
            }
        )

    edge_path = settings.data_dir / "_graph" / "edges.json"
    edges_in = EdgeStore(edge_path).load()
    edges_out = [
        {
            "source_id": e.source_id,
            "target_id": e.target_id,
            "type": e.type,
            "confidence": e.confidence,
            "reason": e.reason,
        }
        for e in edges_in
    ]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes_out),
        "edge_count": len(edges_out),
        "nodes": nodes_out,
        "edges": edges_out,
    }

    out_path = out if out.is_absolute() else (PROJECT_ROOT / out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    typer.echo(
        f"exported {len(nodes_out)} node(s) + {len(edges_out)} edge(s) → {out_path}"
    )


@app.command("graph")
def graph_cmd(
    node_id: Annotated[str, typer.Argument(help="Node id (exact, prefix, or substring)")],
) -> None:
    """Show a node and its immediate graph neighborhood."""
    cli_helper = _make_graph_cli()
    resolved = _resolve_node_or_exit(cli_helper.graph, node_id)
    for line in cli_helper.render_graph(resolved):
        typer.echo(line)


@app.command("trace")
def trace_cmd(
    node_id: Annotated[str, typer.Argument(help="Node id (exact, prefix, or substring)")],
    depth: Annotated[int, typer.Argument(help="Traversal depth")] = 2,
    direction: Annotated[
        str,
        typer.Option(
            "--direction", "-d",
            help="outgoing | incoming | both",
        ),
    ] = "outgoing",
) -> None:
    """Recursively traverse the graph and show a reasoning tree."""
    if direction not in ("outgoing", "incoming", "both"):
        typer.echo("--direction must be one of: outgoing, incoming, both", err=True)
        raise typer.Exit(code=2)
    cli_helper = _make_graph_cli()
    resolved = _resolve_node_or_exit(cli_helper.graph, node_id)
    for line in cli_helper.render_trace(resolved, depth=depth, direction=direction):
        typer.echo(line)


@app.command("why")
def why_cmd(
    node_id: Annotated[str, typer.Argument(help="Node id (exact, prefix, or substring)")],
) -> None:
    """Explain a node using its graph context.

    Uses Claude to synthesize a short explanation when ANTHROPIC_API_KEY is
    set. Falls back to a deterministic bullet summary otherwise.
    """
    cli_helper = _make_graph_cli()
    resolved = _resolve_node_or_exit(cli_helper.graph, node_id)
    synth_fn = _build_why_synth_fn()
    for line in cli_helper.explain_why(resolved, synth_fn=synth_fn):
        typer.echo(line)


@app.command("path")
def path_cmd(
    node_a: Annotated[str, typer.Argument(help="Start node")],
    node_b: Annotated[str, typer.Argument(help="End node")],
    directed: Annotated[
        bool,
        typer.Option(
            "--directed/--undirected",
            help="Respect edge direction (default: undirected)",
        ),
    ] = False,
) -> None:
    """Find the shortest relationship path between two nodes (BFS)."""
    cli_helper = _make_graph_cli()
    a = _resolve_node_or_exit(cli_helper.graph, node_a)
    b = _resolve_node_or_exit(cli_helper.graph, node_b)
    for line in cli_helper.find_path(a, b, directed=directed):
        typer.echo(line)


def _make_graph_cli() -> GraphCLI:
    loader = GraphLoader(settings.data_dir)
    graph = loader.load()
    return GraphCLI(graph, GraphNavigator(graph))


def _resolve_node_or_exit(graph: Graph, query: str) -> str:
    if query in graph.nodes:
        return query
    matches = graph.resolve(query)
    if not matches:
        typer.echo(f"no node matching '{query}'", err=True)
        raise typer.Exit(code=1)
    if len(matches) == 1:
        return matches[0]
    typer.echo(f"{len(matches)} matches:", err=True)
    for i, m in enumerate(matches, 1):
        typer.echo(f"  [{i}] {m}", err=True)
    try:
        raw = input("pick: ").strip()
    except (EOFError, KeyboardInterrupt):
        typer.echo("", err=True)
        raise typer.Exit(code=1)
    try:
        idx = int(raw) - 1
        if not 0 <= idx < len(matches):
            raise IndexError
    except (ValueError, IndexError):
        typer.echo("invalid choice", err=True)
        raise typer.Exit(code=1)
    return matches[idx]


def _build_why_synth_fn():
    """Return a synth callable when Claude is available; None otherwise."""
    key = settings.anthropic_api_key
    if not key:
        return None

    import os
    from anthropic import Anthropic

    model = os.getenv("ARGOS_WHY_MODEL") or settings.extraction_model
    client = Anthropic(api_key=key)

    system = (
        "You are the Argos graph synthesizer. You will be given:\n"
        "  1. A SUBJECT knowledge node with its context, decision, rationale.\n"
        "  2. The neighbors connected to it by typed edges (incoming + outgoing).\n"
        "\n"
        "Write a concise 2-4 sentence explanation in plain prose covering:\n"
        "  - why this node exists,\n"
        "  - what influenced it (from incoming edges),\n"
        "  - what it impacts or depends on (from outgoing edges).\n"
        "\n"
        "Strict rules:\n"
        "- Use ONLY information explicitly present in the provided material.\n"
        "- Do NOT invent relationships, motivations, or facts.\n"
        "- If incoming is empty, do not speculate about origin.\n"
        "- If outgoing is empty, do not speculate about impact.\n"
        "- If context is sparse, say so plainly; do not fill the gap.\n"
        "- Plain prose only. No bullet lists, no headers, no edge-type labels."
    )

    def synth(context: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": context}],
        )
        chunks: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                chunks.append(block.text)
        return "\n".join(chunks).strip()

    return synth


if __name__ == "__main__":
    app()
