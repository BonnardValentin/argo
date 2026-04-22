// Hierarchical layout via dagre — produces deterministic (x, y) for each
// node plus lane assignments, so ReactFlow can render a clean layered DAG
// instead of a force-directed blob.
//
// dagre breaks cycles internally (reverses one edge of each cycle) — Argos
// has some bidirectional pairs (decision ↔ meeting), which would otherwise
// prevent layering. We don't surface the reversal to the UI; edges keep
// their original direction.

import dagre from '@dagrejs/dagre';

export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 64;

export function layoutSequential(
  nodes,
  links,
  { direction = 'LR', rankSep = 140, nodeSep = 28 } = {}
) {
  const g = new dagre.graphlib.Graph({ compound: false });
  g.setGraph({
    rankdir: direction,          // LR | RL | TB | BT
    nodesep: nodeSep,
    ranksep: rankSep,
    marginx: 40,
    marginy: 40,
    ranker: 'network-simplex',
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const link of links) {
    const source = typeof link.source === 'object' ? link.source.id : link.source;
    const target = typeof link.target === 'object' ? link.target.id : link.target;
    // skip self-loops (dagre layer math doesn't like them)
    if (source === target) continue;
    g.setEdge(source, target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const laid = g.node(n.id) || { x: 0, y: 0 };
    return {
      ...n,
      // ReactFlow expects top-left corner; dagre gives center.
      position: { x: laid.x - NODE_WIDTH / 2, y: laid.y - NODE_HEIGHT / 2 },
    };
  });
}
