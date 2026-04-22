import { useEffect, useMemo, useState } from 'react';
import GraphView, { TYPE_COLORS } from './components/GraphView.jsx';
import NodePanel from './components/NodePanel.jsx';
import Toolbar from './components/Toolbar.jsx';
import { loadGraph } from './graph/loader.js';
import { buildAdjacency, toGraphData } from './graph/transform.js';

export default function App() {
  const [raw, setRaw] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [search, setSearch] = useState('');

  // Viz state.
  const [mode, setMode] = useState('2d');        // "2d" | "3d"
  const [layout, setLayout] = useState('lr');    // "force" | "lr" | "td" | "radialout" | "zout"
  const [showLabels, setShowLabels] = useState(true);
  const [bloom, setBloom] = useState(true);

  useEffect(() => {
    loadGraph()
      .then(setRaw)
      .catch((e) => setError(e.message));
  }, []);

  const data = useMemo(() => (raw ? toGraphData(raw) : null), [raw]);
  const adj = useMemo(() => (data ? buildAdjacency(data.links) : null), [data]);

  const selected = data?.nodes.find((n) => n.id === selectedId) || null;
  const outgoing = (selectedId && adj?.out.get(selectedId)) || [];
  const incoming = (selectedId && adj?.inc.get(selectedId)) || [];

  const navigate = (id) => {
    setSelectedId(id);
    setFocusId(id);
    // Reset so selecting the same node again still retriggers the recenter.
    setTimeout(() => setFocusId(null), 50);
  };

  const handleSearch = (e) => {
    if (e.key !== 'Enter' || !search.trim() || !data) return;
    const q = search.trim().toLowerCase();
    const match =
      data.nodes.find((n) => n.id.toLowerCase() === q) ||
      data.nodes.find((n) => n.id.toLowerCase().startsWith(q)) ||
      data.nodes.find((n) => n.id.toLowerCase().includes(q)) ||
      data.nodes.find((n) => n.name.toLowerCase().includes(q));
    if (match) navigate(match.id);
  };

  if (error) {
    return (
      <div className="empty-state">
        <p>Failed to load <code>graph.json</code>.</p>
        <p style={{ fontFamily: 'monospace', color: '#e17c74' }}>{error}</p>
        <p>
          From the Argos project root, run:&nbsp;
          <code>kb export</code>
        </p>
      </div>
    );
  }

  if (!data) return <div className="empty-state">Loading graph…</div>;

  if (data.nodes.length === 0) {
    return (
      <div className="empty-state">
        <p>No nodes in the graph.</p>
        <p>
          Run <code>kb ingest</code>, then <code>kb index</code>, then{' '}
          <code>kb export</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="graph-pane">
        <div className="search-bar">
          <input
            type="text"
            placeholder="search — press Enter to focus"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleSearch}
          />
        </div>

        <GraphView
          data={data}
          mode={mode}
          layout={layout}
          showLabels={showLabels}
          bloom={bloom}
          onSelect={setSelectedId}
          selectedId={selectedId}
          focusId={focusId}
        />

        <div className="legend">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <div key={type}>
              <span className="swatch" style={{ background: color }} />
              {type}
            </div>
          ))}
        </div>

        <Toolbar
          mode={mode}
          setMode={setMode}
          layout={layout}
          setLayout={setLayout}
          showLabels={showLabels}
          setShowLabels={setShowLabels}
          bloom={bloom}
          setBloom={setBloom}
          stats={{ nodes: data.nodes.length, edges: data.links.length }}
        />
      </div>

      {selected && (
        <NodePanel
          node={selected}
          outgoing={outgoing}
          incoming={incoming}
          nodes={data.nodes}
          onNavigate={navigate}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
