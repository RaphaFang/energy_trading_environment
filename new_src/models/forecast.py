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
}


def load_training(zone: str | None = None) -> pd.DataFrame:
    """讀 duckdb 的 training view。zone=None 拿全部(baseline 逐區跑用)。"""
    q = (
        "SELECT * FROM training WHERE y_price_eur IS NOT NULL "
        "AND solar_da_mwh IS NOT NULL"
    )
    if zone:
        q += f" AND area='{zone}'"
    con = duckdb.connect(DB, read_only=True)
    df = con.execute(q + " ORDER BY timestamp_utc").fetchdf()
    con.close()
    return df


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
