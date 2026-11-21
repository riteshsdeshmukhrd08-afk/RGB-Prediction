// Shown when the backend is unreachable or MongoDB is down.
export default function Banner({ health, healthError, onRecheck }) {
  let text = "";
  let detail = "";
  if (healthError) {
    text = healthError.message;
  } else if (health?.mongo === "error") {
    text = "Database not reachable. Check the backend terminal.";
    detail = health.mongo_error || "";
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
