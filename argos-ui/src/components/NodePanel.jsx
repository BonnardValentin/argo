import ReactMarkdown from 'react-markdown';

// Render relations in a stable, spec-aligned order regardless of the
// emission order in edges.json.
const RELATION_ORDER = [
  'depends_on',
  'contradicts',
  'refines',
  'caused_by',
  'related_to',
];

function groupByType(edges) {
  const groups = {};
  for (const e of edges) {
    (groups[e.label] ||= []).push(e);
  }
  for (const k of Object.keys(groups)) {
    groups[k].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  }
  return groups;
}

function RelationList({ groups, direction, nodes, onNavigate }) {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const types = RELATION_ORDER.filter((t) => groups[t]);
  if (types.length === 0) return null;
  const arrow = direction === 'out' ? '→' : '←';

  return (
    <>
      {types.map((t) => (
        <div key={t} className="rel-group">
          <div className="rel-type">
            {arrow} {t}
          </div>
          {groups[t].map((e, i) => {
            const other = nodeById.get(e.other);
            return (
              <div
                key={`${t}-${e.other}-${i}`}
                className="rel-node"
                onClick={() => onNavigate(e.other)}
                role="button"
                tabIndex={0}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') onNavigate(e.other);
                }}
              >
                <span>
                  <span className="type-tag">[{other?.group || '?'}]</span>
                  {other?.name || e.other}
                </span>
                <span className="conf">{(e.confidence || 0).toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}

export default function NodePanel({
  node,
  outgoing,
  incoming,
  nodes,
  onNavigate,
  onClose,
}) {
  if (!node) return null;

  const outGroups = groupByType(outgoing);
  const inGroups = groupByType(incoming);
  const hasRelations =
    Object.keys(outGroups).length > 0 || Object.keys(inGroups).length > 0;

  return (
    <aside className="node-panel">
      <button className="close-btn" onClick={onClose} aria-label="Close">
        ×
      </button>
      <h1>{node.name}</h1>
      <div className="meta">
        {node.group}
        {node.timestamp ? ` · ${node.timestamp.slice(0, 10)}` : ''}
        {' · '}
        <code>{node.id}</code>
      </div>

      {node.content ? (
        <div className="md">
          <ReactMarkdown>{node.content}</ReactMarkdown>
        </div>
      ) : (
        <div className="md" style={{ color: 'var(--muted)' }}>
          (no body)
        </div>
      )}

      {hasRelations && (
        <>
          {Object.keys(outGroups).length > 0 && <h3>Outgoing</h3>}
          <RelationList
            groups={outGroups}
            direction="out"
            nodes={nodes}
            onNavigate={onNavigate}
          />

          {Object.keys(inGroups).length > 0 && <h3>Incoming</h3>}
          <RelationList
            groups={inGroups}
            direction="in"
            nodes={nodes}
            onNavigate={onNavigate}
          />
        </>
      )}
    </aside>
  );
}
