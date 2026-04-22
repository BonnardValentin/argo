// Floating bottom toolbar. State lives in App.jsx; this is stateless.

const MODE_OPTIONS = [
  { id: 'sequential', label: 'sequential' },
  { id: '2d', label: '2D' },
  { id: '3d', label: '3D' },
];

// Layout choices depend on mode. Sequential supports LR/TB; the force
// engines support the wider dagMode set plus an unconstrained "force" mode.
const LAYOUTS_SEQ = [
  { id: 'lr', label: 'left→right' },
  { id: 'td', label: 'top↓down' },
];

const LAYOUTS_2D = [
  { id: 'force', label: 'force' },
  { id: 'lr', label: 'left→right' },
  { id: 'td', label: 'top↓down' },
  { id: 'radialout', label: 'radial' },
];

const LAYOUTS_3D = [
  ...LAYOUTS_2D,
  { id: 'zout', label: 'z-depth' },
];

function Segmented({ options, value, onChange, ariaLabel }) {
  return (
    <div className="seg" role="group" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={opt.id}
          type="button"
          className={`seg-btn ${value === opt.id ? 'active' : ''}`}
          onClick={() => onChange(opt.id)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function Toolbar({
  mode,
  setMode,
  layout,
  setLayout,
  showLabels,
  setShowLabels,
  bloom,
  setBloom,
  stats,
}) {
  const layouts =
    mode === 'sequential' ? LAYOUTS_SEQ : mode === '3d' ? LAYOUTS_3D : LAYOUTS_2D;

  return (
    <div className="toolbar">
      <Segmented
        options={MODE_OPTIONS}
        value={mode}
        onChange={(next) => {
          setMode(next);
          // Sequential only supports LR/TB — nudge the layout if the user
          // had e.g. "radial" selected in a force mode.
          if (next === 'sequential' && !['lr', 'td'].includes(layout)) {
            setLayout('lr');
          }
        }}
        ariaLabel="Render mode"
      />

      <div className="tb-divider" />

      <Segmented options={layouts} value={layout} onChange={setLayout} ariaLabel="Layout" />

      <div className="tb-divider" />

      <button
        type="button"
        className={`seg-btn solo ${showLabels ? 'active' : ''}`}
        onClick={() => setShowLabels(!showLabels)}
      >
        labels
      </button>

      {mode === '3d' && (
        <button
          type="button"
          className={`seg-btn solo ${bloom ? 'active' : ''}`}
          onClick={() => setBloom(!bloom)}
        >
          bloom
        </button>
      )}

      {stats && (
        <>
          <div className="tb-divider" />
          <div className="tb-stats">
            {stats.nodes}n · {stats.edges}e
          </div>
        </>
      )}
    </div>
  );
}
