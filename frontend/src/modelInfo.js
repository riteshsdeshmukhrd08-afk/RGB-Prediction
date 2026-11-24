// Text for the active model, from GET /api/model-info.
const mg = (v) => (v == null ? null : `${Number(v).toFixed(1)} mg/L`);

// "Model: ANN v1.1 · ±33.9 mg/L" (the name and the error come from the backend)   or   "Model: linear (R, G) · ±12.5 mg/L"   or   "Model: linear · not trained yet"
export function modelLabel(model) {
  if (!model) return "";
  const err = mg(model.expected_error_mg_L);
  if (model.model_type === "ann") return `Model: ${model.model_name || "ANN"}${err ? ` · ±${err}` : ""}`;
  if (!model.model_version) return "Model: linear · not trained yet";
  return `Model: linear (${(model.features || []).join(", ")})${err ? ` · ±${err}` : ""}`;
}
