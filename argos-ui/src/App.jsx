import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import GraphView, { TYPE_COLORS } from './components/GraphView.jsx';
import NodePanel from './components/NodePanel.jsx';
import SequentialView from './components/SequentialView.jsx';
import Toolbar from './components/Toolbar.jsx';
import { loadGraph } from './graph/loader.js';
import { buildAdjacency, toGraphData } from './graph/transform.js';

const HISTORY_CAP = 20;

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export default function App() {
  const [raw, setRaw] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [history, setHistory] = useState([]); // stack of visited ids, current at end
  const [search, setSearch] = useState('');
  const [activeResult, setActiveResult] = useState(0);
  const searchInputRef = useRef(null);

  // Viz state. Default "sequential" — layered DAG via dagre + ReactFlow.
  // 2D/3D force-graph remain available as toggles.
  const [mode, setMode] = useState('sequential');
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

  // Ranked search: titles rank above ids, starts-with above contains-substring,
  // exact above everything. Returns up to 8 matches.
  const searchResults = useMemo(() => {
    if (!search.trim() || !data) return [];
    const q = search.trim().toLowerCase();
    const scored = [];
    for (const n of data.nodes) {
      const title = (n.name || '').toLowerCase();
      const id = n.id.toLowerCase();
      let score = 0;
      if (title === q || id === q) score = 1000;
      else if (title.startsWith(q)) score = 600;
      else if (id.startsWith(q)) score = 450;
      else if (new RegExp(`\\b${escapeRegex(q)}`).test(title)) score = 400; // word boundary
      else if (title.includes(q)) score = 250;
      else if (id.includes(q)) score = 100;
      if (score > 0) scored.push({ n, score });
    }
    scored.sort(
      (a, b) => b.score - a.score || a.n.name.localeCompare(b.n.name)
    );
    return scored.slice(0, 8).map((s) => s.n);
  }, [search, data]);

  useEffect(() => {
    setActiveResult(0);
  }, [searchResults]);

  const pickResult = (node) => {
    navigate(node.id);
    setSearch('');
    searchInputRef.current?.blur();
  };

  const handleSearchKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveResult((i) => Math.min(i + 1, Math.max(searchResults.length - 1, 0)));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveResult((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === 'Enter') {
      const pick = searchResults[activeResult];
      if (pick) pickResult(pick);
      return;
    }
    if (e.key === 'Escape') {
      if (search) {
        e.stopPropagation();
        setSearch('');
      }
    }
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
            placeholder="search  —  press /  to focus,  ↑↓  to pick,  Enter"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleSearchKey}
          />
          {search && (
            <div className="search-results">
              {searchResults.length === 0 ? (
                <div className="search-result empty">
                  no match for <code>{search}</code>
                </div>
              ) : (
                searchResults.map((n, i) => (
                  <div
                    key={n.id}
                    className={`search-result ${i === activeResult ? 'active' : ''}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      pickResult(n);
                    }}
                    onMouseEnter={() => setActiveResult(i)}
                  >
                    <span
                      className="sr-type"
                      style={{ color: TYPE_COLORS[n.group] || 'var(--muted)' }}
                    >
                      {n.group}
                    </span>
                    <span className="sr-title" title={n.name}>
                      {n.name}
                    </span>
                    <span className="sr-id" title={n.id}>
                      {n.id.split('--')[0]}
                    </span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {mode === 'sequential' ? (
          <SequentialView
            data={data}
            direction={layout === 'td' ? 'TB' : 'LR'}
            showLabels={showLabels}
            onSelect={navigate}
            selectedId={selectedId}
          />
        ) : (
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
        )}

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
