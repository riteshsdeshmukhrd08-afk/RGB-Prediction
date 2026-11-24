// Shown when the backend is unreachable, MongoDB is down, or the ANN model file could not be loaded.
export const MODEL_UNAVAILABLE_TEXT = "The ANN model is not loaded on the server, so no concentration can be predicted.";

export default function Banner({ health, healthError, onRecheck }) {
  let text = "";
  let detail = "";
  if (healthError) {
    text = healthError.message;
  } else if (health?.mongo === "error") {
    text = "Database not reachable. Check the backend terminal.";
    detail = health.mongo_error || "";
  } else if (health?.model === "unavailable") {
    text = MODEL_UNAVAILABLE_TEXT;
    detail = health.model_error || "";
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
