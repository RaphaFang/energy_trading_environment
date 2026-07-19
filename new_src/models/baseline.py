"""預測準度報表:seasonal-naive vs Ridge vs Lasso(LEAR) vs LightGBM,逐區(DK1/DK2)。

只回答「預測準不準」(MAE/RMSE/rMAE)。「預測拿去交易賺多少錢」是另一把尺,在 compare.py。
建模本身全在 forecast.py(唯一一份),這裡只做評估與印表。

用法:python new_src/models/baseline.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from forecast import fit_predict, load_training, rmae  # noqa: E402


def _metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return np.mean(np.abs(y - p)), np.sqrt(np.mean((y - p) ** 2))


def run_zone(df, zone: str):
    r = fit_predict(df)
    rm = rmae(r["actual"], r["preds"])
    print(f"\n=== {zone}  (train {r['n_train']} rows, test {r['n_test']} rows) ===")
    print(f"{'model':<14}{'MAE':>9}{'RMSE':>9}{'rMAE':>8}")
    for name, p in r["preds"].items():
        mae, rmse = _metrics(r["actual"], p)
        print(f"{name:<14}{mae:>9.2f}{rmse:>9.2f}{rm[name]:>8.2f}")


def main():
    df = load_training()
    for zone in sorted(df["area"].unique()):
        run_zone(df[df["area"] == zone].copy(), zone)
    print("\nrMAE < 1.00 means the model beats the seasonal-naive floor.")


if __name__ == "__main__":
    main()
