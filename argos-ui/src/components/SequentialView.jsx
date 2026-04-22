import { useEffect, useMemo, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  MarkerType,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { layoutSequential } from '../graph/layout.js';
import TypedNode, { } from './TypedNode.jsx';
import { TYPE_COLORS } from './GraphView.jsx';

// Relation-type → edge color. Subtle by default; the two directional
// relations (depends_on, caused_by) use the node-type palette so the eye
// can trace causality at a glance.
const EDGE_COLORS = {
  depends_on: '#6ea8fe',
  caused_by: '#e17c74',
  refines: '#7db78b',
  contradicts: '#d4a75a',
  related_to: 'rgba(180,180,200,0.45)',
};

const nodeTypes = { typed: TypedNode };

function ViewInner({
  data,
  direction,
  showLabels,
  onSelect,
  selectedId,
}) {
  const { fitView } = useReactFlow();
  const fitRef = useRef(false);

  // Build ReactFlow nodes/edges + dagre positions. Re-laying out every time
  // `direction` changes is cheap (< 20 ms for this graph size).
  const { rfNodes, rfEdges } = useMemo(() => {
    const positioned = layoutSequential(data.nodes, data.links, { direction });

    const activeId = selectedId;
    const neighbors = new Set();
    if (activeId) {
      for (const l of data.links) {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        if (s === activeId) neighbors.add(t);
        if (t === activeId) neighbors.add(s);
      }
    }

    const rfNodes = positioned.map((n) => {
      const isActive = activeId != null;
      const isSelf = n.id === activeId;
      const isNeighbor = neighbors.has(n.id);
      const dim = isActive && !isSelf && !isNeighbor;
      return {
        id: n.id,
        type: 'typed',
        position: n.position,
        data: { name: n.name, group: n.group, id: n.id, dim },
        selected: isSelf,
      };
    });

    const rfEdges = data.links.map((l, i) => {
      const source = typeof l.source === 'object' ? l.source.id : l.source;
      const target = typeof l.target === 'object' ? l.target.id : l.target;
      const isActive = selectedId != null;
      const isIncident = isActive && (source === selectedId || target === selectedId);
      const stroke = EDGE_COLORS[l.label] || 'rgba(180,180,200,0.4)';
      const width = Math.max(1, 0.8 + (l.confidence || 0) * 1.6);
      return {
        id: `e${i}`,
        source,
        target,
        type: 'smoothstep',
        label: showLabels ? l.label : undefined,
        labelStyle: {
          fill: isIncident ? '#e1e4eb' : '#7a8292',
          fontSize: 10,
          fontFamily: 'ui-monospace, monospace',
        },
        labelBgStyle: {
          fill: '#0f1115',
          fillOpacity: 0.92,
        },
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 3,
        style: {
          stroke: isIncident ? stroke : dimStroke(stroke, isActive),
          strokeWidth: isIncident ? width + 0.6 : width,
          opacity: isActive && !isIncident ? 0.25 : 1,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isIncident ? stroke : dimStroke(stroke, isActive),
          width: 14,
          height: 14,
        },
      };
    });

    return { rfNodes, rfEdges };
  }, [data, direction, showLabels, selectedId]);

  // First-layout fit: recenter once on initial render, and again when the
  // corpus changes shape or direction flips.
  useEffect(() => {
    fitRef.current = false;
  }, [direction, data]);

  useEffect(() => {
    if (fitRef.current) return;
    const id = setTimeout(() => {
      fitView({ padding: 0.15, duration: 400 });
      fitRef.current = true;
    }, 40);
    return () => clearTimeout(id);
  }, [rfNodes, fitView]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.id)}
      onPaneClick={() => {}}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.2}
      maxZoom={2}
      nodesDraggable
      nodesConnectable={false}
      elementsSelectable
      proOptions={{ hideAttribution: true }}
      defaultEdgeOptions={{ type: 'smoothstep' }}
    >
      <Background color="#1a1d26" gap={36} size={1} />
      <Controls showInteractive={false} position="top-right" />
      <MiniMap
        position="bottom-right"
        maskColor="rgba(10,12,16,0.75)"
        pannable
        zoomable
        nodeColor={(n) => TYPE_COLORS[n.data.group] || '#9ca3af'}
        style={{ background: '#0f1115', border: '1px solid #242833' }}
      />
    </ReactFlow>
  );
}

// Lower opacity / lighter stroke when an active node dims the rest.
function dimStroke(color, dim) {
  if (!dim) return color;
  if (color.startsWith('rgba')) return color;
  // Hex → rgba with 0.35 alpha
  const m = color.match(/^#([0-9a-f]{6})$/i);
  if (!m) return color;
  const int = parseInt(m[1], 16);
  const r = (int >> 16) & 0xff;
  const g = (int >> 8) & 0xff;
  const b = int & 0xff;
  return `rgba(${r},${g},${b},0.25)`;
}

export default function SequentialView(props) {
  return (
    <ReactFlowProvider>
      <ViewInner {...props} />
    </ReactFlowProvider>
  );
}
