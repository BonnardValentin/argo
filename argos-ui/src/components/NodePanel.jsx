import ReactMarkdown from 'react-markdown';
import { TYPE_COLORS } from './GraphView.jsx';

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

// Strip the leading `# H1` from the markdown body so it doesn't duplicate
// the title we're already showing in the panel header.
function stripLeadingTitle(md, title) {
  if (!md) return md;
  const lines = md.split('\n');
  // Skip leading blank lines.
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i++;
  if (i >= lines.length) return md;
  const first = lines[i].trim();
  if (!first.startsWith('# ') || first.startsWith('## ')) return md;
  // Optional: only strip when it actually matches the node title, so we
  // don't accidentally swallow an intentionally-different leading header.
  const headerText = first.slice(2).trim();
  if (title && headerText !== title.trim()) return md;
  // Drop the H1 line + any blank lines immediately after it.
  let j = i + 1;
  while (j < lines.length && lines[j].trim() === '') j++;
  return lines.slice(j).join('\n');
}

// Pull a one-sentence summary: first non-heading paragraph of the `## Decision`
// section if present, else `## Context`, else the first paragraph of the body.
function deriveSummary(md) {
  if (!md) return '';
  const sections = splitSections(md);
  const candidates = ['Decision', 'Context', 'Why'];
  for (const name of candidates) {
    const text = sections[name];
    if (text) {
      const first = firstSentence(text);
      if (first) return first;
    }
  }
  // Fallback: first paragraph after any H1.
  const lines = md.split('\n').filter((l) => !l.startsWith('#'));
  const joined = lines.join('\n').trim();
  return firstSentence(joined);
}

function splitSections(md) {
  const out = {};
  let current = null;
  let buf = [];
  for (const raw of md.split('\n')) {
    const line = raw.trimEnd();
    const m = line.match(/^##\s+(.+?)\s*$/);
    if (m) {
      if (current) out[current] = buf.join('\n').trim();
      current = m[1];
      buf = [];
    } else if (current != null) {
      buf.push(line);
    }
  }
  if (current) out[current] = buf.join('\n').trim();
  return out;
}

function firstSentence(text) {
  const paragraph = text
    .split(/\n\s*\n/)[0]
    ?.replace(/\n/g, ' ')
    .trim();
  if (!paragraph) return '';
  const m = paragraph.match(/^(.+?[.!?])(\s|$)/);
  return (m ? m[1] : paragraph).trim();
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
  historyDepth = 0,
  onNavigate,
  onBack,
  onClose,
}) {
  if (!node) return null;

  const outGroups = groupByType(outgoing);
  const inGroups = groupByType(incoming);
  const hasRelations =
    Object.keys(outGroups).length > 0 || Object.keys(inGroups).length > 0;

  const body = stripLeadingTitle(node.content || '', node.name);
  const summary = deriveSummary(body);
  const typeColor = TYPE_COLORS[node.group] || '#9ca3af';
  const shortId = node.id.split('--')[0];

  return (
    <aside className="node-panel">
      <div className="panel-header">
        {historyDepth > 1 && (
          <button
            type="button"
            className="nav-btn"
            onClick={onBack}
            title="Back (Backspace)"
            aria-label="Back"
          >
            ← back
          </button>
        )}
        <button
          type="button"
          className="close-btn"
          onClick={onClose}
          aria-label="Close (Esc)"
          title="Close (Esc)"
        >
          ×
        </button>
      </div>

      <div className="type-badge" style={{ color: typeColor, borderColor: typeColor }}>
        {node.group}
      </div>
      <h1>{node.name}</h1>

      {summary && <p className="summary">{summary}</p>}

      <div className="meta">
        {node.timestamp && (
          <span className="meta-item">{node.timestamp.slice(0, 10)}</span>
        )}
        <span className="meta-item" title={node.id}>
          <code>{shortId}</code>
        </span>
      </div>

      {body.trim() ? (
        <div className="md">
          <ReactMarkdown>{body}</ReactMarkdown>
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
