"""Graph exploration over the edges produced by the Hermes linker.

Loads nodes from markdown + edges from data/knowledge/_graph/edges.json and
exposes:

- `GraphLoader`    — disk → in-memory `Graph`
- `Graph`          — nodes, edges, outgoing/incoming adjacency lists
- `GraphNavigator` — neighborhood, DFS traversal, BFS shortest path
- `GraphCLI`       — stateless rendering helpers for the kb subcommands

Pure offline. No Redis. No agents. The only optional LLM call lives behind
an injected `synth_fn` in `GraphCLI.explain_why` — the graph module itself
never reaches for the network.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from argos.linker import Edge, EdgeStore, NodeSnapshot
from argos.local_index import list_nodes


# ---------------------------------------------------------------------------
# In-memory graph
# ---------------------------------------------------------------------------


@dataclass
class Graph:
    nodes: dict[str, NodeSnapshot]
    edges: list[Edge]
    outgoing: dict[str, list[Edge]] = field(default_factory=dict)
    incoming: dict[str, list[Edge]] = field(default_factory=dict)

    @classmethod
    def build(cls, nodes: dict[str, NodeSnapshot], edges: list[Edge]) -> "Graph":
        outgoing: dict[str, list[Edge]] = {}
        incoming: dict[str, list[Edge]] = {}
        for e in edges:
            outgoing.setdefault(e.source_id, []).append(e)
            incoming.setdefault(e.target_id, []).append(e)
        return cls(nodes=nodes, edges=edges, outgoing=outgoing, incoming=incoming)

    def get(self, node_id: str) -> NodeSnapshot | None:
        return self.nodes.get(node_id)

    def resolve(self, query: str) -> list[str]:
        """Substring → candidate node ids, tiered: exact → prefix → substring."""
        q = query.lower()
        exact = [nid for nid in self.nodes if nid.lower() == q]
        if exact:
            return exact
        prefix = sorted(nid for nid in self.nodes if nid.lower().startswith(q))
        if prefix:
            return prefix
        return sorted(nid for nid in self.nodes if q in nid.lower())


class GraphLoader:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.edges_path = data_dir / "_graph" / "edges.json"

    def load(self) -> Graph:
        nodes: dict[str, NodeSnapshot] = {}
        for path in list_nodes(self.data_dir):
            try:
                snap = NodeSnapshot.load(path)
            except (OSError, UnicodeDecodeError):
                continue
            nodes[snap.id] = snap
        edges = EdgeStore(self.edges_path).load()
        # Discard edges that dangle (reference ids no longer on disk) so the
        # navigator never has to worry about missing targets.
        edges = [e for e in edges if e.source_id in nodes and e.target_id in nodes]
        return Graph.build(nodes, edges)


# ---------------------------------------------------------------------------
# Navigator — traversal logic
# ---------------------------------------------------------------------------


@dataclass
class TraversalNode:
    """One node in a traversal tree.

    `incoming_edge` is the edge connecting this node to its parent in the
    tree (None for the root). `cycle=True` marks a repeat visit — we stop
    descending at cycle points but still render the marker so the user can
    see where the loop closes.
    """

    node_id: str
    depth_remaining: int
    incoming_edge: Edge | None
    children: list["TraversalNode"] = field(default_factory=list)
    cycle: bool = False


class GraphNavigator:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def neighborhood(self, node_id: str) -> tuple[list[Edge], list[Edge]]:
        """Return (outgoing_edges, incoming_edges) for a single node."""
        return (
            list(self.graph.outgoing.get(node_id, [])),
            list(self.graph.incoming.get(node_id, [])),
        )

    def traverse(
        self,
        start: str,
        *,
        depth: int = 2,
        direction: str = "outgoing",
    ) -> TraversalNode:
        """DFS traversal tree up to `depth` hops deep.

        `direction`: "outgoing" | "incoming" | "both". A single `visited`
        set spans the whole traversal so no node is rendered twice and
        cycles surface as a `cycle=True` leaf.
        """
        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(f"direction must be outgoing/incoming/both, got {direction!r}")
        visited: set[str] = set()
        return self._walk(
            node_id=start,
            depth=depth,
            direction=direction,
            visited=visited,
            incoming_edge=None,
        )

    def _walk(
        self,
        *,
        node_id: str,
        depth: int,
        direction: str,
        visited: set[str],
        incoming_edge: Edge | None,
    ) -> TraversalNode:
        visited.add(node_id)
        node = TraversalNode(
            node_id=node_id,
            depth_remaining=depth,
            incoming_edge=incoming_edge,
        )
        if depth <= 0:
            return node

        edges: list[Edge] = []
        if direction in ("outgoing", "both"):
            edges.extend(self.graph.outgoing.get(node_id, []))
        if direction in ("incoming", "both"):
            edges.extend(self.graph.incoming.get(node_id, []))
        edges.sort(key=lambda e: (e.type, e.target_id, e.source_id))

        for e in edges:
            other = e.target_id if e.source_id == node_id else e.source_id
            if other in visited:
                node.children.append(
                    TraversalNode(
                        node_id=other,
                        depth_remaining=depth - 1,
                        incoming_edge=e,
                        cycle=True,
                    )
                )
                continue
            node.children.append(
                self._walk(
                    node_id=other,
                    depth=depth - 1,
                    direction=direction,
                    visited=visited,
                    incoming_edge=e,
                )
            )
        return node

    def shortest_path(
        self, start: str, end: str, *, directed: bool = False
    ) -> list[Edge] | None:
        """BFS. Returns None if unreachable, [] if start == end, else the
        chain of edges. `directed=True` follows only outgoing edges; the
        default treats every edge as bidirectional (connectivity, not flow)."""
        if start not in self.graph.nodes or end not in self.graph.nodes:
            return None
        if start == end:
            return []

        queue: deque[tuple[str, list[Edge]]] = deque([(start, [])])
        visited: set[str] = {start}
        while queue:
            node_id, path = queue.popleft()
            for edge, other in self._walkable(node_id, directed=directed):
                if other in visited:
                    continue
                new_path = path + [edge]
                if other == end:
                    return new_path
                visited.add(other)
                queue.append((other, new_path))
        return None

    def _walkable(
        self, node_id: str, *, directed: bool
    ) -> Iterator[tuple[Edge, str]]:
        for e in self.graph.outgoing.get(node_id, []):
            yield e, e.target_id
        if not directed:
            for e in self.graph.incoming.get(node_id, []):
                yield e, e.source_id


# ---------------------------------------------------------------------------
# Rendering (pure: yields strings, no I/O)
# ---------------------------------------------------------------------------


class GraphCLI:
    def __init__(self, graph: Graph, navigator: GraphNavigator) -> None:
        self.graph = graph
        self.navigator = navigator

    def render_graph(self, node_id: str) -> Iterable[str]:
        node = self.graph.get(node_id)
        if node is None:
            yield f"node not found: {node_id}"
            return
        outgoing, incoming = self.navigator.neighborhood(node_id)

        yield f"Node: {node.id}"
        yield f"  title: {node.title}"
        yield f"  type:  {node.type}"
        yield ""

        if outgoing:
            yield "OUTGOING:"
            for e in sorted(outgoing, key=lambda e: (e.type, e.target_id)):
                yield f"  {e.type} → {e.target_id}  (conf {e.confidence:.2f})"
        else:
            yield "OUTGOING: (none)"
        yield ""

        if incoming:
            yield "INCOMING:"
            for e in sorted(incoming, key=lambda e: (e.type, e.source_id)):
                yield f"  {e.type} ← {e.source_id}  (conf {e.confidence:.2f})"
        else:
            yield "INCOMING: (none)"

    def render_trace(
        self,
        node_id: str,
        *,
        depth: int = 2,
        direction: str = "outgoing",
    ) -> Iterable[str]:
        if node_id not in self.graph.nodes:
            yield f"node not found: {node_id}"
            return
        root = self.navigator.traverse(node_id, depth=depth, direction=direction)
        yield root.node_id
        yield from _format_children(root.children, indent="", show_arrow=(direction == "both"))

    def find_path(
        self, start: str, end: str, *, directed: bool = False
    ) -> Iterable[str]:
        if start not in self.graph.nodes:
            yield f"node not found: {start}"
            return
        if end not in self.graph.nodes:
            yield f"node not found: {end}"
            return
        path = self.navigator.shortest_path(start, end, directed=directed)
        if path is None:
            mode = "directed" if directed else "undirected"
            yield f"no path ({mode}): {start} ↛ {end}"
            return
        if not path:
            yield f"{start} (same node)"
            return

        # Walk the chain and render each hop with the arrow in the actual
        # traversal direction (forward = along source→target, backward =
        # followed an incoming edge).
        parts = [start]
        cursor = start
        for edge in path:
            if edge.source_id == cursor:
                nxt = edge.target_id
                parts.append(f" —[{edge.type}]→ {nxt}")
            else:
                nxt = edge.source_id
                parts.append(f" ←[{edge.type}]— {nxt}")
            cursor = nxt
        yield "".join(parts)
        yield ""
        yield f"{len(path)} hop(s)"

    def explain_why(
        self,
        node_id: str,
        *,
        synth_fn: Callable[[str], str] | None = None,
    ) -> Iterable[str]:
        """Summarize a node using its graph context.

        When `synth_fn` is provided, it receives the assembled context string
        and returns a natural-language summary. The graph module never calls
        the LLM itself — the caller (cli.py) owns the provider choice and
        credential handling.
        """
        node = self.graph.get(node_id)
        if node is None:
            yield f"node not found: {node_id}"
            return
        outgoing, incoming = self.navigator.neighborhood(node_id)

        if synth_fn is None:
            yield from self._render_why_deterministic(node, outgoing, incoming)
            return

        context = self._build_why_context(node, outgoing, incoming)
        yield synth_fn(context)

    def _render_why_deterministic(
        self,
        node: NodeSnapshot,
        outgoing: list[Edge],
        incoming: list[Edge],
    ) -> Iterable[str]:
        yield f"# {node.title}"
        yield f"  ({node.type}:{node.id})"
        yield ""
        if node.decision.strip():
            yield f"Decision: {node.decision.strip().splitlines()[0]}"
        if node.why.strip():
            yield f"Why:      {node.why.strip().splitlines()[0]}"

        if incoming:
            yield ""
            yield "Influenced by:"
            for e in incoming:
                src = self.graph.get(e.source_id)
                title = src.title if src else e.source_id
                yield f"  - [{e.type}] {title}"
                if e.reason:
                    yield f"      reason: {e.reason[:140]}"

        if outgoing:
            yield ""
            yield "Impacts / depends on:"
            for e in outgoing:
                tgt = self.graph.get(e.target_id)
                title = tgt.title if tgt else e.target_id
                yield f"  - [{e.type}] {title}"
                if e.reason:
                    yield f"      reason: {e.reason[:140]}"

        if not outgoing and not incoming:
            yield ""
            yield "(no graph connections — run `kb index` to build edges)"

    def _build_why_context(
        self,
        node: NodeSnapshot,
        outgoing: list[Edge],
        incoming: list[Edge],
    ) -> str:
        lines: list[str] = ["--- SUBJECT ---"]
        lines.append(f"id: {node.id}")
        lines.append(f"type: {node.type}")
        lines.append(f"title: {node.title}")
        for label, value in (
            ("Context", node.context),
            ("Decision", node.decision),
            ("Why", node.why),
            ("How", node.how),
        ):
            if value.strip():
                lines.append(f"\n{label}:\n{value.strip()}")

        if incoming:
            lines.append("\n--- INCOMING EDGES (nodes that influenced the subject) ---")
            for e in incoming:
                src = self.graph.get(e.source_id)
                if src is None:
                    continue
                lines.append(
                    f"\n[{e.type}] FROM '{src.title}' (conf {e.confidence:.2f})"
                )
                if e.reason:
                    lines.append(f"  edge reason: {e.reason}")
                if src.decision.strip():
                    lines.append(
                        f"  source decision: {src.decision.strip().splitlines()[0]}"
                    )

        if outgoing:
            lines.append(
                "\n--- OUTGOING EDGES (nodes the subject depends on or impacts) ---"
            )
            for e in outgoing:
                tgt = self.graph.get(e.target_id)
                if tgt is None:
                    continue
                lines.append(
                    f"\n[{e.type}] TO '{tgt.title}' (conf {e.confidence:.2f})"
                )
                if e.reason:
                    lines.append(f"  edge reason: {e.reason}")
                if tgt.decision.strip():
                    lines.append(
                        f"  target decision: {tgt.decision.strip().splitlines()[0]}"
                    )

        if not outgoing and not incoming:
            lines.append("\n(no graph connections)")

        return "\n".join(lines)


def _format_children(
    children: list[TraversalNode], indent: str, *, show_arrow: bool
) -> Iterable[str]:
    for i, child in enumerate(children):
        is_last = i == len(children) - 1
        branch = "└── " if is_last else "├── "
        e = child.incoming_edge
        if e is None:
            label = child.node_id
        else:
            parent_is_source = e.source_id != child.node_id
            if show_arrow:
                arrow = "→" if parent_is_source else "←"
                label = f"{e.type} {arrow} {child.node_id}"
            else:
                label = f"{e.type} {child.node_id}"
        suffix = "  (↩ cycle)" if child.cycle else ""
        yield f"{indent}{branch}{label}{suffix}"
        child_indent = indent + ("    " if is_last else "│   ")
        yield from _format_children(child.children, child_indent, show_arrow=show_arrow)
