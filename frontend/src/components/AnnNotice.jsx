// Shown instead of the Train card while the ANN is the active model: it is fixed, so it is never trained here.
export default function AnnNotice({ model }) {
  return (
    <section className="card ann-notice">
      <h2>Concentration model</h2>
      <p className="muted">
        The ANN model ({model?.model_name || "ANN"}) is fixed and cannot be trained here. To train the linear
        model from a CSV or XLSX of known values, set <span className="mono">MODEL_TYPE=linear</span> in
        <span className="mono"> backend/.env</span> and restart the backend.
      </p>
    </section>
  );
}
