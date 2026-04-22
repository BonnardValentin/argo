import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import ForceGraph3D from 'react-force-graph-3d';
import SpriteText from 'three-spritetext';
import * as THREE from 'three';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

export const TYPE_COLORS = {
  decision: '#6ea8fe',
  incident: '#e17c74',
  meeting: '#7db78b',
  discussion: '#d4a75a',
  note: '#9ca3af',
};

const DEFAULT_COLOR = '#9ca3af';
const DIMMED_NODE = 'rgba(120,120,120,0.22)';
const DIMMED_TEXT = 'rgba(225,228,235,0.28)';
const HIGHLIGHT = '#ff7849';

// `layout` is either "force" (no DAG constraint) or one of the library's
// dagMode values: "lr", "td", "bu", "rl", "radialout", "radialin", "zout", "zin".
const DAG_LAYOUTS = new Set(['lr', 'td', 'bu', 'rl', 'radialout', 'radialin', 'zout', 'zin']);

export default function GraphView({
  data,
  mode,
  layout,
  showLabels,
  bloom,
  onSelect,
  selectedId,
  focusId,
}) {
  const fgRef = useRef(null);
  const containerRef = useRef(null);
  const [hoverId, setHoverId] = useState(null);
  const [size, setSize] = useState({ w: 1, h: 1 });

  // Resize observer — keep the canvas flush with the pane.
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

  // Undirected adjacency for hover/select highlighting. Precomputed so the
  // per-frame color callbacks stay O(1).
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
      if (!activeId) return true;
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

  // Focus / recenter on request.
  useEffect(() => {
    if (!focusId || !fgRef.current) return;
    const node = data.nodes.find((n) => n.id === focusId);
    if (!node) return;
    if (mode === '2d' && typeof node.x === 'number') {
      fgRef.current.centerAt(node.x, node.y, 600);
      fgRef.current.zoom(3, 600);
    } else if (mode === '3d' && typeof node.x === 'number') {
      // 3D: move camera to look at the node from a reasonable distance.
      const dist = 120;
      const ratio = 1 + dist / Math.hypot(node.x, node.y, node.z);
      fgRef.current.cameraPosition(
        { x: node.x * ratio, y: node.y * ratio, z: node.z * ratio },
        node,
        600
      );
    }
  }, [focusId, data.nodes, mode]);

  // Bloom post-processing. Much gentler than v1 — threshold 0.85 means only
  // the very brightest pixels (node centers) bloom, instead of the whole
  // scene washing out to white.
  useEffect(() => {
    if (mode !== '3d' || !fgRef.current) return undefined;
    const composer = fgRef.current.postProcessingComposer?.();
    if (!composer) return undefined;

    let bloomPass = null;
    if (bloom) {
      bloomPass = new UnrealBloomPass(
        new THREE.Vector2(size.w, size.h),
        0.5, // strength (was 1.6 — too hot)
        0.35, // radius
        0.85 // threshold — only the brightest pixels bloom
      );
      composer.addPass(bloomPass);
    }
    return () => {
      if (bloomPass && composer.passes.includes(bloomPass)) {
        composer.removePass(bloomPass);
        bloomPass.dispose?.();
      }
    };
  }, [mode, bloom, size.w, size.h]);

  const dagMode = DAG_LAYOUTS.has(layout) ? layout : null;

  const shared = {
    graphData: data,
    backgroundColor: mode === '3d' ? '#05070b' : '#0f1115',
    nodeId: 'id',
    nodeLabel: (n) => `${n.group}: ${n.name}`,
    linkLabel: (l) => `${l.label}  (conf ${(l.confidence || 0).toFixed(2)})`,
    linkWidth: (l) => 0.5 + (l.confidence || 0) * 2.5,
    linkDirectionalArrowLength: 5,
    linkDirectionalArrowRelPos: 0.94,
    dagMode,
    dagLevelDistance: mode === '3d' ? 60 : 140,
    // Click just notifies; App.jsx re-routes through `focusId` so that
    // direct node clicks and panel-link navigation animate identically.
    onNodeClick: (n) => onSelect(n.id),
    onNodeHover: (n) => setHoverId(n ? n.id : null),
    cooldownTicks: 120,
    warmupTicks: 40,
    // Break cycles silently if present — Argos can have bidirectional pairs
    // (decision ↔ meeting). Don't throw the console.
    onDagError: () => {},
  };

  if (mode === '2d') {
    return (
      <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
        <ForceGraph2D
          ref={fgRef}
          width={size.w}
          height={size.h}
          {...shared}
          nodeRelSize={6}
          nodeColor={(n) =>
            isNodeHighlighted(n.id) ? (TYPE_COLORS[n.group] || DEFAULT_COLOR) : DIMMED_NODE
          }
          nodeCanvasObjectMode={() => (showLabels ? 'after' : undefined)}
          nodeCanvasObject={(node, ctx, globalScale) => {
            if (!showLabels) return;
            // Clamp font to a sensible pixel range so labels stay legible
            // at any zoom — this was the "huge text" bug.
            const fontSize = Math.max(6, Math.min(13, 10 / globalScale));
            ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = isNodeHighlighted(node.id) ? '#e1e4eb' : DIMMED_TEXT;
            ctx.fillText(node.name, node.x + 8, node.y);
          }}
          linkColor={(l) => (isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(180,180,180,0.32)')}
          linkDirectionalArrowColor={(l) =>
            isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(180,180,180,0.5)'
          }
        />
      </div>
    );
  }

  // 3D
  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
      <ForceGraph3D
        ref={fgRef}
        width={size.w}
        height={size.h}
        {...shared}
        nodeVal={(n) => (n.id === activeId ? 2.5 : 1)}
        nodeOpacity={0.9}
        nodeResolution={16}
        nodeColor={(n) =>
          isNodeHighlighted(n.id) ? (TYPE_COLORS[n.group] || DEFAULT_COLOR) : '#3a3f4a'
        }
        nodeThreeObjectExtend={true}
        nodeThreeObject={
          showLabels
            ? (node) => {
                const sprite = new SpriteText(node.name);
                sprite.color = isNodeHighlighted(node.id) ? '#e1e4eb' : 'rgba(200,200,200,0.35)';
                sprite.textHeight = 3;
                sprite.backgroundColor = false;
                sprite.padding = 0;
                sprite.position.y = 6;
                return sprite;
              }
            : undefined
        }
        linkOpacity={0.45}
        linkColor={(l) => (isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(180,180,200,0.55)')}
        linkDirectionalArrowColor={(l) =>
          isLinkHighlighted(l) ? HIGHLIGHT : 'rgba(200,200,220,0.7)'
        }
        linkDirectionalParticles={(l) => (isLinkHighlighted(l) ? 3 : 1)}
        linkDirectionalParticleSpeed={(l) => 0.003 + (l.confidence || 0) * 0.006}
        linkDirectionalParticleWidth={1.6}
        linkDirectionalParticleColor={(l) =>
          isLinkHighlighted(l) ? HIGHLIGHT : TYPE_COLORS[l.label] || '#8899aa'
        }
      />
    </div>
  );
}
