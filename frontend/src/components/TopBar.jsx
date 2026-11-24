import { modelLabel } from "../modelInfo.js";

function Chip({ tone, children }) {
  return (
    <span className={"chip " + tone}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

// The header shows the title, the active model ("Model: ANN v1.1 · ±33.9 mg/L", read from the backend) and, when something is wrong
// with the backend or database, a red chip.
export default function TopBar({ dbDown, backendError, model }) {
  return (
    <header className="topbar">
      <div className="brand">
        <h1>RGB measurement</h1>
        <p className="subtitle">Colour readings of liquid in vial photos, with the predicted concentration</p>
      </div>
      <div className="chips">
        {model && <Chip tone="model">{modelLabel(model)}</Chip>}
        {backendError && <Chip tone="bad">{backendError.message}</Chip>}
        {dbDown && <Chip tone="bad">Database not reachable</Chip>}
      </div>
    </header>
  );
}
