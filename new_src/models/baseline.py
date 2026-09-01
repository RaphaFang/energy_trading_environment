"""預測準度報表:seasonal-naive vs Ridge vs Lasso(LEAR) vs LightGBM,逐區(DK1/DK2)。

只回答「預測準不準」(MAE/RMSE/rMAE)。「預測拿去交易賺多少錢」是另一把尺,在 compare.py。
建模本身全在 forecast.py(唯一一份),這裡只做評估與印表。

用法:python new_src/models/baseline.py
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from forecast import SPLIT, TARGET, fit_predict, load_training, rmae  # noqa: E402


def _metrics(y, p):
    """MAE、RMSE、R²。R² = 1 − 殘差平方和/總變異 —— **分母是「永遠猜測試期平均價」**,
    所以 R² 是跟「不看任何資訊的常數預測」比,而 rMAE 是跟「照抄昨天」比。
    兩把尺的基準不同,rMAE 那把嚴格得多(照抄昨天已經很強)。"""
    y, p = np.asarray(y, float), np.asarray(p, float)
    ss_res = np.sum((y - p) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return np.mean(np.abs(y - p)), np.sqrt(ss_res / len(y)), 1 - ss_res / ss_tot


def run_zone(df, zone: str):
    r = fit_predict(df)
    rm = rmae(r["actual"], r["preds"])
    print(f"\n=== {zone}  (train {r['n_train']} rows, test {r['n_test']} rows) ===")
    print(f"  測試期 {r['te_idx'].min():%Y-%m-%d} → {r['te_idx'].max():%Y-%m-%d}"
          f"、實際價 平均 {r['actual'].mean():.2f} sd {r['actual'].std():.2f} EUR/MWh")
    print(f"{'model':<14}{'MAE':>9}{'RMSE':>9}{'R2':>8}{'rMAE':>8}")
    for name, p in r["preds"].items():
        mae, rmse, r2 = _metrics(r["actual"], p)
        print(f"{name:<14}{mae:>9.2f}{rmse:>9.2f}{r2:>8.3f}{rm[name]:>8.2f}")


def run_best(df, zone: str):
    """★ 最佳設定(`forecast.BEST`)—— 掃過 44 個設定挑出來的,兩個價區一致。
    這裡重跑一次讓它跟上面四個模型並排,免得「repo 裡最好的模型」只存在於實驗報告。"""
    import pandas as pd
    from experiments import run
    from forecast import BEST, _features

    feats = _features(df)
    for c in df[feats].select_dtypes("bool"):
        df[c] = df[c].astype(int)
    ts = pd.DatetimeIndex(df["timestamp_utc"])
    te = ts >= pd.Timestamp(SPLIT, tz=ts.tz)
    y = df.loc[te, TARGET].to_numpy()
    naive = df.loc[te, "price_lag24_eur"].to_numpy()
    ps = [run(df, feats, m, BEST["refit"], BEST["pooling"], BEST["target"]).to_numpy()
          for m in BEST["models"]]
    p = np.mean(ps, axis=0)
    mae, rmse, r2 = _metrics(y, p)
    print(f"{'★ BEST':<14}{mae:>9.2f}{rmse:>9.2f}{r2:>8.3f}"
          f"{mae / np.mean(np.abs(y - naive)):>8.2f}   "
          f"= {'+'.join(BEST['models'])} · {BEST['refit']} · {BEST['pooling']} · {BEST['target']}")


def main():
    df = load_training()
    for zone in sorted(df["area"].unique()):
        d = df[df["area"] == zone].copy()
        run_zone(d.copy(), zone)
        run_best(d, zone)
    print("\nrMAE < 1.00 means the model beats the seasonal-naive floor.")
    print("R2  is measured against a constant (the test-period mean), a much weaker baseline.")


if __name__ == "__main__":
    main()
