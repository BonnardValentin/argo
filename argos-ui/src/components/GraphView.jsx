import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

// Type → color. Keep in sync with the legend + App.jsx.
export const TYPE_COLORS = {
  decision: '#6ea8fe',
  incident: '#e17c74',
  meeting: '#7db78b',
  discussion: '#d4a75a',
  note: '#9ca3af',
};

const DEFAULT_COLOR = '#9ca3af';
const DIMMED = 'rgba(120,120,120,0.22)';
const DIMMED_TEXT = 'rgba(225,228,235,0.28)';
const HIGHLIGHT = '#ff7849';

export default function GraphView({ data, onSelect, selectedId, focusId }) {
  const fgRef = useRef(null);
  const containerRef = useRef(null);
  const [hoverId, setHoverId] = useState(null);
  const [size, setSize] = useState({ w: 1, h: 1 });

  // Resize observer so the canvas matches the pane when the panel opens/closes.
  useEffect(() => {
    if (!containerRef.current) return undefined;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSize({
          w: Math.max(1, Math.floor(entry.contentRect.width)),
          h: Math.max(1, Math.floor(entry.contentRect.height)),
        });
      }
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Adjacency for hover/selection highlighting. Undirected (both neighbors
  // light up regardless of edge direction) — visualizes "what is connected".
  const adjacency = useMemo(() => {
    const map = new Map();
    for (const link of data.links) {
      const s = typeof link.source === 'object' ? link.source.id : link.source;
      const t = typeof link.target === 'object' ? link.target.id : link.target;
      if (!map.has(s)) map.set(s, new Set());
      if (!map.has(t)) map.set(t, new Set());
      map.get(s).add(t);
      map.get(t).add(s);
    }
    return map;
  }, [data.links]);

  const activeId = hoverId || selectedId;

  const isNodeHighlighted = useCallback(
    (id) => {
      if (!activeId) return true; // nothing active → everything renders normally
      if (id === activeId) return true;
      return adjacency.get(activeId)?.has(id) ?? false;
    },
    [activeId, adjacency]
  );

  const isLinkHighlighted = useCallback(
    (link) => {
      if (!activeId) return false;
      const s = typeof link.source === 'object' ? link.source.id : link.source;
      const t = typeof link.target === 'object' ? link.target.id : link.target;
      return s === activeId || t === activeId;
    },
    [activeId]
  );

  // Recenter/zoom when the caller asks us to focus on a node (e.g. from search).
  useEffect(() => {
    if (!focusId || !fgRef.current) return;
    const node = data.nodes.find((n) => n.id === focusId);
    if (node && typeof node.x === 'number') {
      fgRef.current.centerAt(node.x, node.y, 600);
      fgRef.current.zoom(3, 600);
    }
  }, [focusId, data.nodes]);

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
      <ForceGraph2D
        ref={fgRef}
        width={size.w}
        height={size.h}
        graphData={data}
        backgroundColor="#0f1115"
        nodeId="id"
        nodeLabel={(n) => `${n.group}: ${n.name}`}
        nodeColor={(n) =>
          isNodeHighlighted(n.id) ? (TYPE_COLORS[n.group] || DEFAULT_COLOR) : DIMMED
        }
        nodeRelSize={6}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.name;
          const fontSize = Math.max(10, 12 / globalScale);
          ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;
          ctx.textAlign = 'left';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = isNodeHighlighted(node.id) ? '#e1e4eb' : DIMMED_TEXT;
          ctx.fillText(label, node.x + 8, node.y);
        }}
        linkColor={(l) =>
          isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(180,180,180,0.32)'
        }
        linkWidth={(l) => 0.5 + (l.confidence || 0) * 2.5}
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={0.94}
        linkDirectionalArrowColor={(l) =>
          isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(180,180,180,0.5)'
        }
        linkLabel={(l) =>
          `${l.label}  (conf ${(l.confidence || 0).toFixed(2)})`
        }
        onNodeClick={(n) => {
          onSelect(n.id);
          if (fgRef.current && typeof n.x === 'number') {
            fgRef.current.centerAt(n.x, n.y, 400);
          }
        }}
        onNodeHover={(n) => setHoverId(n ? n.id : null)}
        cooldownTicks={120}
        warmupTicks={40}
      />
    </div>
  );
}
