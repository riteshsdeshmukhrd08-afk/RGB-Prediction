// Text for the active model, from GET /api/model.
const mg = (v) => (v == null ? null : `${Number(v).toFixed(1)} mg/L`);

// "ann_v2_clean" -> "ANN v2 clean"
export const annName = (version) => "ANN " + String(version || "").replace(/^ann_?/i, "").replace(/_/g, " ").trim();

// "Model: ANN v2 clean · ±17.8 mg/L"   or   "Model: linear (R, G) · ±12.5 mg/L"   or   "Model: linear · not trained yet"
export function modelLabel(model) {
  if (!model) return "";
  const err = mg(model.expected_error_mg_L);
  if (model.model_type === "ann") return `Model: ${annName(model.model_version)}${err ? ` · ±${err}` : ""}`;
  if (!model.model_version) return "Model: linear · not trained yet";
  return `Model: linear (${(model.features || []).join(", ")})${err ? ` · ±${err}` : ""}`;
}
