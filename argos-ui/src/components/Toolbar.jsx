// Floating bottom toolbar. Keep the state lifted in App.jsx; this is a
// stateless view that just emits onChange callbacks.

const LAYOUTS_2D = [
  { id: 'force', label: 'force' },
  { id: 'lr', label: 'left→right' },
  { id: 'td', label: 'top↓down' },
  { id: 'radialout', label: 'radial' },
];

// 3D has one extra mode that only makes sense in 3 dimensions.
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
  const layouts = mode === '3d' ? LAYOUTS_3D : LAYOUTS_2D;

  return (
    <div className="toolbar">
      <Segmented
        options={[
          { id: '2d', label: '2D' },
          { id: '3d', label: '3D' },
        ]}
        value={mode}
        onChange={setMode}
        ariaLabel="Render mode"
      />

      <div className="tb-divider" />

      <Segmented
        options={layouts}
        value={layout}
        onChange={setLayout}
        ariaLabel="Layout"
      />

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
