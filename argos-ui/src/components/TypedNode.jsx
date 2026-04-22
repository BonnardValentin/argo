import { Handle, Position } from 'reactflow';
import { TYPE_COLORS } from './GraphView.jsx';

// Card-style node for the sequential layout. Colored left-border carries
// the type, title wraps, id shown muted below. Handles on left+right so
// dagre's LR layout can route edges horizontally; ReactFlow auto-switches
// to top/bottom handles when rankdir is TB.
export default function TypedNode({ data, selected }) {
  const color = TYPE_COLORS[data.group] || '#9ca3af';
  return (
    <div
      className={`typed-node${selected ? ' selected' : ''}${data.dim ? ' dim' : ''}`}
      style={{ borderLeftColor: color }}
    >
      <Handle type="target" position={Position.Left} className="rf-handle" />
      <Handle type="target" position={Position.Top} className="rf-handle" />

      <div className="tn-head">
        <span className="tn-type" style={{ color }}>
          {data.group}
        </span>
        <span className="tn-id">{shortId(data.id)}</span>
      </div>
      <div className="tn-title">{data.name}</div>

      <Handle type="source" position={Position.Right} className="rf-handle" />
      <Handle type="source" position={Position.Bottom} className="rf-handle" />
    </div>
  );
}

function shortId(id) {
  // Keep labels compact: drop the long hash-like suffix slug extractor emits.
  if (!id) return '';
  const parts = id.split('--');
  return parts.length > 1 ? parts[0] : id;
}
