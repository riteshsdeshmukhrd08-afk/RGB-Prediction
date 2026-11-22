// Shown when the backend is unreachable, MongoDB is down, or the server could not load the COD model.
export const MODEL_MISSING_TEXT = "The COD model is not loaded on the server.";
export const MODEL_MISSING_DETAIL = "Photos are still measured (R, G, B), but no COD is shown until the model file is loaded. Check the backend log.";

export default function Banner({ health, healthError, onRecheck }) {
  let text = "";
  let detail = "";
  if (healthError) {
    text = healthError.message;
  } else if (health?.mongo === "error") {
    text = "Database not reachable. Check the backend terminal.";
    detail = health.mongo_error || "";
  } else if (health?.model === "missing") {
    text = MODEL_MISSING_TEXT;
    detail = MODEL_MISSING_DETAIL;
  }
  if (!text) return null;
  return (
    <div className="banner" role="alert">
      <strong>{text}</strong>
      {detail && <span className="muted mono"> {detail}</span>}
      <button onClick={onRecheck}>Check again</button>
    </div>
  );
}
