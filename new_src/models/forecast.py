"""統計模型預測隔日電價 — baseline.py(準度報表)與 compare.py(錢的對照)共用的唯一一份。

以前這份程式碼在兩個檔各寫一份(同樣的 LEAK_COLS、同樣的 SPLIT、同樣的超參數),改一邊
忘了另一邊,兩邊數字就對不起來。現在只有這裡。

Leak-safe by construction:
  - LEAK_COLS 擋掉「同時刻實測」(load/wind/solar/residual 的當下值)——只有它們的 lag 能當特徵
  - 切分照時間(train < SPLIT ≤ test),不是隨機
  - LightGBM 的 early-stop valid 取訓練期**尾段**(是 train 的未來,不是 test)
"""

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoCV, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# ★ 2026-08-28 掃過 44 個設定之後的最佳組合(`experiments.py`,兩個價區一致)。
#   Ridge + Lasso + LightGBM 三者平均 · **只用最近 12 個月**重訓 · 目標改成「相對昨天同一小時的變化」
#   🔴 **2026-08-28 修正**:原本報的 17.10 / 18.10 含兩個關門後才知道的特徵(見 LEAK_COLS)。
#      去 leak 並加上合法替代之後的**正式數字**(跑 `baseline.py` 可重現):
#        DK1  基準 Lasso 20.09(rMAE 0.66) → BEST **17.60(0.58、R² 0.754)**  −12.4%
#        DK2  基準 Lasso 23.10(rMAE 0.72) → BEST **18.70(0.58、R² 0.736)**  −19.0%
#      配對按日 bootstrap 的 ΔMAE:DK1 [−3.09, −2.10]、DK2 [−3.94, −3.05],**都遠離 0**。
#   🔑 它勝出的理由不只是平均低,**它是唯一在 2025-10 制度斷點後不退化的設定**。
#      機制見 `experiments.py` 的說明。
BEST = {"refit": "roll12", "pooling": "pooled", "target": "detrend",
        "models": ("Ridge", "Lasso", "LightGBM")}

DB = "new_data/energy.duckdb"
SPLIT = "2024-07-01"  # train < SPLIT, test >= SPLIT (chronological, no leak)
TARGET = "y_price_eur"

# same-hour actuals + ids + target: using any as a feature would leak the answer
LEAK_COLS = {
    "timestamp_utc",
    "area",
    "holiday_name",
    TARGET,
    "load_mwh",
    "wind_mwh",
    "solar_mwh",
    "residual_mwh",
    # 🔴 2026-08-28 補上的兩個:**昨天同一小時的「實測」負載與殘餘**。
    #    日前投標在 D−1 12:00 關門,而這兩欄對「D 日下午的目標」指的是 D−1 下午
    #    —— 那是關門**之後**才量到的 → leak。
    #    ⚠️ 對照:`price_lag24_eur` / `price_lag168_eur` 是**日前價**,D−2 12:55 就公布,**合法**。
    #    實測代價:拿掉之後 BEST 的 MAE DK1 17.00 → 17.58、DK2 18.02 → 18.65,
    #    ΔMAE 的 CI 都遠離 0 → 它們確實在偷分。
    "load_lag24_mwh",
    "residual_lag24_mwh",
}

# 上面那兩欄的**合法替代**:再往前推一天 = D−2 同一小時,關門時一定已公布。
#   救回一部分:DK1 17.58 → 17.47(CI [−0.18, −0.04],顯著);DK2 18.65 → 18.57(不顯著)。
GATE_SAFE_LAGS = {"load_lag24_mwh": "load_lag48_mwh",
                  "residual_lag24_mwh": "residual_lag48_mwh"}


def load_training(zone: str | None = None) -> pd.DataFrame:
    """讀 duckdb 的 training view。zone=None 拿全部(baseline 逐區跑用)。"""
    # 🔴 `price_lag24_eur` 也要非空:它是 naive-24h 這把尺本身。
    #    2025-10 的夏令時那一小時 lag24 是 NULL,**一格 NaN 就把 MAE/RMSE/R2/rMAE 全毒成 NaN**
    #    (np.mean 不是 nanmean)。而且濾掉它才能保證四個模型評在**同一批列**上。
    q = (
        "SELECT * FROM training WHERE y_price_eur IS NOT NULL "
        "AND solar_da_mwh IS NOT NULL AND price_lag24_eur IS NOT NULL"
    )
    if zone:
        q += f" AND area='{zone}'"
    con = duckdb.connect(DB, read_only=True)
    df = con.execute(q + " ORDER BY area, timestamp_utc").fetchdf()
    con.close()
    # 合法替代:**逐區**再往前推 24 小時 → D−2 同一小時。
    # ⚠️ 一定要 groupby("area"),不然兩區的列交錯,shift 會跨區拿到別區的值。
    for src, dst in GATE_SAFE_LAGS.items():
        df[dst] = df.groupby("area")[src].shift(24)
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def _features(df: pd.DataFrame) -> list[str]:
    """非 leak、且這一區不是全 NaN 的欄(如 NL 邊界容量在 DK2 全空)。"""
    feats = [c for c in df.columns if c not in LEAK_COLS and df[c].notna().any()]
    assert not (set(feats) & LEAK_COLS), "leak column leaked into features"
    return feats


def fit_predict(df: pd.DataFrame) -> dict:
    """訓練四個模型,回傳 test 期的預測。
    回傳 dict:te_idx(時間索引)、actual(真實價)、preds({模型名: 預測價})、tr_price(訓練期價 Series)。
    naive-24h = 照抄昨天同一小時,是 rMAE 的分母(地板)。"""
    df = df.sort_values("timestamp_utc")
    feats = _features(df)
    for b in df[feats].select_dtypes("bool"):
        df[b] = df[b].astype(int)

    tr = df[df.timestamp_utc < SPLIT]
    te = df[df.timestamp_utc >= SPLIT]
    assert tr["timestamp_utc"].max() < te["timestamp_utc"].min(), (
        "split not chronological"
    )
    Xtr, ytr, Xte = tr[feats], tr[TARGET], te[feats]

    preds = {"naive-24h": te["price_lag24_eur"].to_numpy()}
    tscv = TimeSeriesSplit(n_splits=5)
    for name, est in {
        "Ridge": RidgeCV(alphas=np.logspace(-2, 4, 25), cv=tscv),
        "Lasso(LEAR)": LassoCV(cv=tscv, max_iter=5000, n_jobs=-1),
    }.items():
        pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), est)
        preds[name] = pipe.fit(Xtr, ytr).predict(Xte)

    cut = int(len(tr) * 0.9)  # 訓練尾段當 early-stop valid(是 train 的未來,不 leak)
    gbm = lgb.LGBMRegressor(
        n_estimators=3000,
        learning_rate=0.03,
        num_leaves=63,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=0,
        verbose=-1,
    )
    gbm.fit(
        Xtr.iloc[:cut],
        ytr.iloc[:cut],
        eval_set=[(Xtr.iloc[cut:], ytr.iloc[cut:])],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    preds["LightGBM"] = gbm.predict(Xte)

    return dict(
        te_idx=pd.DatetimeIndex(te["timestamp_utc"].to_numpy()),
        actual=te[TARGET].to_numpy(),
        preds=preds,
        tr_price=pd.Series(
            tr[TARGET].to_numpy(),
            index=pd.DatetimeIndex(tr["timestamp_utc"].to_numpy()),
        ),
        n_train=len(tr),
        n_test=len(te),
    )


def rmae(actual, preds: dict) -> dict:
    """預測準度尺:MAE(模型) / MAE(naive-24h)。<1 = 贏過「照抄昨天」的地板。"""
    mae_n = np.mean(np.abs(actual - preds["naive-24h"]))
    return {n: np.mean(np.abs(actual - p)) / mae_n for n, p in preds.items()}
