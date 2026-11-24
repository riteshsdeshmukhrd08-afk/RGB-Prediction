# model_build - offline recipe for the COD model

**The web app never imports or runs anything in this folder.** It only loads the finished file
`backend/models/cod_ann_model_bundle.joblib`.

`build_ann_model.py` produced that bundle: an MLP neural network on the trimmed-mean `R` and `G` values
(StandardScaler -> MLPRegressor, target standardised), tuned with nested cross-validation and refitted on all
screened readings between 100 and 1250 mg/L.

## Files the script needs (put them in this folder)

| File | What it is |
|---|---|
| `cod_plsr_colab_cell.py` | the colab cell; defines `load_dataset`, `screen_readings`, `fit_applicability`, `predict_cod` (the script runs the part above the line `# ============================ RUN IT`) |
| `dataset.csv` | the training readings (`Concentration_ppm`, `R`, `G`, ...) |
| `outputs/accuracy_summary.json` | read for the reference RMSE of the gradient-boosting model (`["nested"]["GradientBoosting"]["RMSE"]`) |

These three files are **not in the repository yet** (they were only available as `/home/claude/...` paths).
Copy them here before running. The script writes `outputs/cod_ann_model_bundle.joblib`; copy that to
`backend/models/` to replace the model.

## Run

    pip install scikit-learn==1.9.1 numpy pandas joblib
    python model_build/build_ann_model.py

The bundle must be rebuilt (and `scikit-learn` re-pinned in `backend/requirements.txt`) together: a joblib file is
tied to the scikit-learn version that wrote it.

## The bundle

`pipeline` (`TransformedTargetRegressor`, returns mg/L), `features = ["R", "G"]`, `applicability`
(`mean`, `cov_inv`, `d2_threshold`, `min`, `max`, `n_train`), `calibration_nominal_range_mg_L = [100, 1250]`,
`calibration_observed_range_mg_L = [103, 1207]`, expected error (nested CV RMSE) 38.6 mg/L, built with
scikit-learn 1.9.1.
