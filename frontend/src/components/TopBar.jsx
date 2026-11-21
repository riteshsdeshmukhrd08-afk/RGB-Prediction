function Chip({ tone, children }) {
  return (
    <span className={"chip " + tone}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

// The header shows the title and, only when something is wrong with the backend or database, a red chip.
export default function TopBar({ dbDown, backendError }) {
  return (
    <header className="topbar">
      <div className="brand">
        <h1>RGB measurement</h1>
        <p className="subtitle">Colour readings of liquid in vial photos, with an optional concentration estimate</p>
      </div>
      <div className="chips">
        {backendError && <Chip tone="bad">{backendError.message}</Chip>}
        {dbDown && <Chip tone="bad">Database not reachable</Chip>}
      </div>
    </header>
  );
}
