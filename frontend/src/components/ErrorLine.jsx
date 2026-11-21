// Shows the backend's own text; the HTTP code is only a small secondary detail.
export default function ErrorLine({ error }) {
  if (!error) return null;
  const message = typeof error === "string" ? error : error.message;
  const status = typeof error === "string" ? 0 : error.status;
  return (
    <p className="error" role="alert">
      {message} {status ? <span className="badge">HTTP {status}</span> : null}
    </p>
  );
}
