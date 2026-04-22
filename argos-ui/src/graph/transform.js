// Convert the Argos export shape into react-force-graph's {nodes, links}.
//
// react-force-graph mutates node/link objects in place (attaches x/y/vx/vy,
// and replaces source/target string ids with node object refs). We keep our
// own stable fields (id, name, group, content) separate from the library's
// layout fields, and we never mutate the return values after passing them in.

export function toGraphData(raw) {
  const nodes = (raw?.nodes ?? []).map((n) => ({
    id: n.id,
    name: n.title,
    group: n.type,
    content: n.content ?? '',
    timestamp: n.timestamp ?? null,
  }));

  const links = (raw?.edges ?? []).map((e) => ({
    source: e.source_id,
    target: e.target_id,
    label: e.type,
    confidence: typeof e.confidence === 'number' ? e.confidence : 0,
    reason: e.reason ?? '',
  }));

  return { nodes, links };
}

// Build outgoing/incoming adjacency maps keyed on node id. Each edge entry
// carries an `other` field — the far endpoint from that map's perspective —
// so the panel can render both directions without branching on source/target.
export function buildAdjacency(links) {
  const out = new Map();
  const inc = new Map();
  for (const link of links) {
    // After the force-graph engine runs, source/target are object refs;
    // before, they're string ids. Handle both.
    const s = typeof link.source === 'object' ? link.source.id : link.source;
    const t = typeof link.target === 'object' ? link.target.id : link.target;
    if (!out.has(s)) out.set(s, []);
    if (!inc.has(t)) inc.set(t, []);
    out.get(s).push({ ...link, other: t });
    inc.get(t).push({ ...link, other: s });
  }
  return { out, inc };
}
