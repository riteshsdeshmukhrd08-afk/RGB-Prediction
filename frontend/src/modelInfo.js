// Text for the active model, from GET /api/model-info. The name shown for the ANN is this one constant.
// The expected error is not shown on screen (it stays in the backend response and in the CSV / XLSX downloads).
export const MODEL_DISPLAY_NAME = "RGB prediction model";

// "Model: RGB prediction model"   or   "Model: linear (R, G)"   or   "Model: linear · not trained yet"
export function modelLabel(model) {
  if (!model) return "";
  if (model.model_type === "ann") return `Model: ${MODEL_DISPLAY_NAME}`;
  if (!model.model_version) return "Model: linear · not trained yet";
  return `Model: linear (${(model.features || []).join(", ")})`;
}
