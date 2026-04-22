import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import GraphView, { TYPE_COLORS } from './components/GraphView.jsx';
import NodePanel from './components/NodePanel.jsx';
import Toolbar from './components/Toolbar.jsx';
import { loadGraph } from './graph/loader.js';
import { buildAdjacency, toGraphData } from './graph/transform.js';

const HISTORY_CAP = 20;

export default function App() {
  const [raw, setRaw] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [history, setHistory] = useState([]); // stack of visited ids, current at end
  const [search, setSearch] = useState('');
  const searchInputRef = useRef(null);

  // Viz state. Default 2D + lr + labels + no bloom — most readable starting point.
  const [mode, setMode] = useState('2d');
  const [layout, setLayout] = useState('lr');
  const [showLabels, setShowLabels] = useState(true);
  const [bloom, setBloom] = useState(false);

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

  // navigate(): push onto history (unless revisiting the head), focus the camera.
  const navigate = useCallback((id) => {
    setSelectedId(id);
    setFocusId(id);
    setHistory((h) => {
      const tail = h[h.length - 1];
      if (tail === id) return h;
      const next = [...h, id];
      return next.slice(-HISTORY_CAP);
    });
    // Reset focusId so re-selecting the same node retriggers the recenter.
    setTimeout(() => setFocusId(null), 50);
  }, []);

  const goBack = useCallback(() => {
    setHistory((h) => {
      if (h.length < 2) return h;
      const next = h.slice(0, -1);
      const target = next[next.length - 1];
      setSelectedId(target);
      setFocusId(target);
      setTimeout(() => setFocusId(null), 50);
      return next;
    });
  }, []);

  const closePanel = useCallback(() => {
    setSelectedId(null);
    setHistory([]);
  }, []);

  const focusSearch = useCallback(() => {
    searchInputRef.current?.focus();
    searchInputRef.current?.select();
  }, []);

  // Keyboard: `/` focus search, `Escape` close panel / blur search,
  // `Backspace` go back one hop (when not typing).
  useEffect(() => {
    const isTyping = (el) =>
      el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);

    const onKey = (ev) => {
      const typing = isTyping(document.activeElement);
      if (ev.key === '/' && !typing) {
        ev.preventDefault();
        focusSearch();
        return;
      }
      if (ev.key === 'Escape') {
        if (typing) {
          document.activeElement.blur();
          return;
        }
        if (selectedId) closePanel();
        return;
      }
      if ((ev.key === 'Backspace' || ev.key === 'u') && !typing && selectedId) {
        ev.preventDefault();
        goBack();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedId, goBack, closePanel, focusSearch]);

  const handleSearchKey = (e) => {
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
            ref={searchInputRef}
            type="text"
            placeholder="search  —  press /  or  Enter to focus"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleSearchKey}
          />
        </div>

        <GraphView
          data={data}
          mode={mode}
          layout={layout}
          showLabels={showLabels}
          bloom={bloom}
          onSelect={navigate}
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
          <div className="legend-hint">
            <kbd>/</kbd> search · <kbd>⌫</kbd> back · <kbd>esc</kbd> close
          </div>
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
          historyDepth={history.length}
          onNavigate={navigate}
          onBack={goBack}
          onClose={closePanel}
        />
      )}
    </div>
  );
}
