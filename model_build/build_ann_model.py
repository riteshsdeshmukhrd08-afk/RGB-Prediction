import warnings; warnings.filterwarnings("ignore")
import json, datetime as dt
from pathlib import Path
import numpy as np, joblib
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.compose import TransformedTargetRegressor
from sklearn.model_selection import GroupKFold, GridSearchCV, cross_val_predict

# OFFLINE ONLY. The web app never imports or runs this file. Paths are relative to this folder (see README.md).
HERE = Path(__file__).resolve().parent
ns = {}
exec(compile(open(HERE / "cod_plsr_colab_cell.py").read()
             .split("# ============================ RUN IT")[0], "cell", "exec"), ns)
OUT = HERE / "outputs"                      # holds accuracy_summary.json; the bundle is written here too
OUT.mkdir(exist_ok=True)
raw, info = ns["load_dataset"](str(HERE / "dataset.csv"))
flag, _ = ns["screen_readings"](raw)
df = raw[~flag]
df = df[(df["Concentration_ppm"] >= 100) & (df["Concentration_ppm"] <= 1250)].reset_index(drop=True)
y = df["Concentration_ppm"].to_numpy(float)
X = df[["R", "G"]].to_numpy(float)
g = y.copy()

def make_ann(hidden, alpha, lr):
    mlp = MLPRegressor(hidden_layer_sizes=hidden, activation="relu", solver="lbfgs",
                       alpha=alpha, learning_rate_init=lr, max_iter=3000, random_state=0)
    return TransformedTargetRegressor(regressor=make_pipeline(StandardScaler(), mlp),
                                      transformer=StandardScaler())

ANN_GRID = {"regressor__mlpregressor__hidden_layer_sizes": [(8,), (16,), (16, 8)],
            "regressor__mlpregressor__alpha": [1e-3, 1e-2, 1e-1, 1.0]}

def tuned():
    base = make_ann((16,), 1e-2, 0.001)
    return GridSearchCV(base, ANN_GRID, cv=GroupKFold(3),
                        scoring="neg_root_mean_squared_error", n_jobs=-1)

# nested CV: outer GroupKFold(5) for honest error, inner tuning inside each fold
outer_pred = np.zeros_like(y)
for tr, te in GroupKFold(5).split(X, y, groups=g):
    m = tuned().fit(X[tr], y[tr], groups=g[tr])
    outer_pred[te] = m.predict(X[te])
err = outer_pred - y
rmse = float(np.sqrt(np.mean(err**2))); mae = float(np.mean(np.abs(err))); bias = float(np.mean(err))
print(f"ANN nested CV: RMSE {rmse:.1f} | MAE {mae:.1f} | bias {bias:.1f}")

summ = json.load(open(OUT / "accuracy_summary.json"))["nested"]
print("GB nested CV reference RMSE:", round(summ["GradientBoosting"]["RMSE"], 1))

# final model: tune on all screened data, refit
gs = tuned().fit(X, y, groups=g)
final = gs.best_estimator_
print("final ANN params:", {k.split("__",1)[1]: v for k, v in gs.best_params_.items()},
      "| inner CV RMSE:", round(-gs.best_score_, 1))

ad = ns["fit_applicability"](X); ad["features"] = ["R", "G"]
bundle = {
    "model_version": "COD-ANN-RG-v1.0",
    "configuration": "MLP neural network (R, G), tuned by nested CV, target standardised",
    "pipeline": final,
    "features": ["R", "G"],
    "n_components": None,
    "applicability_features": ["R", "G"],
    "applicability": ad,
    "calibration_nominal_range_mg_L": [100.0, 1250.0],
    "calibration_observed_range_mg_L": [float(y.min()), float(y.max())],
    "expected_error_mg_L_test_RMSEP": rmse,
    "test_metrics": {"RMSE": rmse, "MAE": mae, "Bias": bias},
    "cv_metrics": {"RMSE": rmse},
    "training_rows": int(len(y)),
    "source_file": info["file"],
    "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "note": f"Expected error is the nested outer-CV RMSE ({rmse:.1f} mg/L). Refitted on all screened readings 100-1250 mg/L.",
}
joblib.dump(bundle, OUT / "cod_ann_model_bundle.joblib")
print("saved", OUT / "cod_ann_model_bundle.joblib")
for args in [(219.9, 167, 0), (228, 165.8, 0)]:
    r = ns["predict_cod"](*args, bundle)
    print(args, "->", r["predicted_COD_mg_L"], r["status"], r["warnings"])
