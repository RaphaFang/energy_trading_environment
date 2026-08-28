"""模型 A 的改進實驗 —— **重訓頻率 × 逐小時建模 × 模型類別**。

━━━ 為什麼要做這個 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

`baseline.py` 是**訓練一次、預測兩年**(切分固定在 2024-07-01)。那對誰都不公平,
對樹模型特別不公平 —— 2026-08-28 重測就看到 LightGBM 從當年的 rMAE 0.54 掉到 0.84,
被 Lasso 反超。合理的懷疑是**模型過期**,不是模型不好。這支腳本檢驗那個懷疑。

━━━ 三個維度 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    重訓   once      訓練一次(= baseline.py 的做法)
           monthly   每個測試月開始前,用它之前的**全部**資料重訓(expanding window)
           roll12    同樣逐月重訓,但**只用最近 12 個月**(rolling window)
    目標   level     直接預測價格
           detrend   預測**價格 − 昨天同一小時的價**,預測完再加回去
    建模   pooled   一個模型吃 24 個小時
           hourly   **逐小時 24 個模型**(電價預測文獻 LEAR 的標準做法)
    模型   Ridge / Lasso(LEAR) / LightGBM / 三者平均

━━━ 為什麼加 roll12 與 detrend(有機制根據,不是亂試)━━━━━━━━━━━━━

第一輪的前後半期拆解發現:**斷點正好在 2025-10(日前市場轉 15 分鐘)。**
之後電價水準上移(DK1 月均 79 → 97),而三個模型的偏誤分道揚鑣:

    Lasso  逐月重訓   偏誤 −2.0    跟得上
    Lasso  訓練一次   偏誤 −6.3    靠線性外推撐住
    LightGBM 逐月重訓 偏誤 −23.3   🔴 **連重訓都救不了**

原因:**樹的葉子值是歷史目標的平均,而擴張式訓練窗把新制度稀釋掉了**;線性模型
可以靠燃料價係數把預測整體抬高,樹只能重用看過的水準。所以兩個對症的修法:

    roll12    只用最近 12 個月 → 新制度不再被七年的舊資料稀釋
    detrend   改預測「相對昨天同一小時的變化」→ 目標本身變得平穩,樹不必外推水準

━━━ 一個查過的假警報 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

跑的時候會看到 `SimpleImputer` 警告 `oc_*` 六欄「沒有任何觀測值」。那是真的:
**北歐 FBMC 2024-10 上線後 offered capacity 停止發布,`oc_*` 從 2025 年起整年全空。**
⚠️ 但**實測沒有影響**:Lasso 去掉那六欄後 MAE 19.124 → 19.119(once)、18.462 → 18.500(monthly)
—— 線性模型自己把它們的係數壓掉了。**所以不必為此改特徵集**,但要知道那個警告的來源。

━━━ 🔴 怎麼判定「有改進」━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**不是看 MAE 小了就算贏。** 每個變體都跟基準做**配對的按日區塊 bootstrap**:
重抽「天」,每次算兩個模型在同一批天上的 MAE 差,取 95% 區間。**區間跨 0 就不算改進。**
配對(同一批天)很重要 —— 兩個模型共同的好日子壞日子會抵銷掉,剩下的才是真實差距。
按「天」重抽是因為電價日內高度相關,逐小時重抽會低估標準誤。

用法:python new_src/models/experiments.py [--quick]
"""
from __future__ import annotations

import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoCV, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from forecast import SPLIT, TARGET, _features, load_training  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "figs", "forecast")
TSCV = TimeSeriesSplit(n_splits=5)


def _make(name: str):
    if name == "Ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             RidgeCV(alphas=np.logspace(-2, 4, 25), cv=TSCV))
    if name == "Lasso":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LassoCV(cv=TSCV, max_iter=5000, n_jobs=-1, random_state=0))
    if name == "LightGBM":
        return "lgbm"                      # 走自己的 early-stopping 路徑
    raise ValueError(name)


def _fit_predict(name: str, Xtr, ytr, Xte) -> np.ndarray:
    """單次擬合。LightGBM 用訓練期尾段 10% 當 early-stop 驗證集(是 train 的未來,不 leak)。"""
    if name != "LightGBM":
        return _make(name).fit(Xtr, ytr).predict(Xte)
    cut = max(1, int(len(Xtr) * 0.9))
    m = lgb.LGBMRegressor(n_estimators=3000, learning_rate=0.03, num_leaves=63,
                          subsample=0.8, colsample_bytree=0.8, random_state=0, verbose=-1)
    if cut < len(Xtr):
        m.fit(Xtr.iloc[:cut], ytr.iloc[:cut],
              eval_set=[(Xtr.iloc[cut:], ytr.iloc[cut:])],
              callbacks=[lgb.early_stopping(50, verbose=False)])
    else:
        m.fit(Xtr, ytr)
    return m.predict(Xte)


ANCHOR = "price_lag24_eur"          # detrend 用的錨:昨天同一小時的價(關門時已知,不 leak)


def run(df: pd.DataFrame, feats: list[str], model: str,
        refit: str, pooling: str, target: str = "level") -> pd.Series:
    """回傳測試期的預測(index = timestamp)。切分一律照時間。"""
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    ts = pd.DatetimeIndex(df["timestamp_utc"])
    split = pd.Timestamp(SPLIT, tz=ts.tz)
    te_mask = ts >= split

    # 重訓的邊界:once = 只有一個;monthly = 每個測試月一個
    if refit == "once":
        bounds = [(split, ts.max() + pd.Timedelta("1h"))]
    else:
        months = sorted({p for p in ts[te_mask].tz_convert(None).to_period("M")})
        bounds = [(m.to_timestamp().tz_localize("UTC").tz_convert(ts.tz),
                   (m + 1).to_timestamp().tz_localize("UTC").tz_convert(ts.tz)) for m in months]

    y_all = df[TARGET]
    anchor = df[ANCHOR]
    fit_y = y_all - anchor if target == "detrend" else y_all

    pred = pd.Series(np.nan, index=ts)
    for lo, hi in bounds:
        tr_m = ts < lo
        if refit == "roll12":                    # 只用最近 12 個月
            tr_m &= ts >= lo - pd.DateOffset(months=12)
        te_m = (ts >= lo) & (ts < hi)
        if not te_m.any():
            continue
        groups = [None] if pooling == "pooled" else sorted(df["hour"].unique())
        for g in groups:
            gm = np.ones(len(df), bool) if g is None else (df["hour"] == g).to_numpy()
            a, b = tr_m & gm, te_m & gm
            if a.sum() < 200 or b.sum() == 0:
                continue
            out = _fit_predict(model, df.loc[a, feats], fit_y[a], df.loc[b, feats])
            if target == "detrend":
                out = out + anchor[b].to_numpy()
            pred.iloc[np.where(b)[0]] = out
    return pred[te_mask]


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    ss_res = np.sum((y - p) ** 2)
    return {"MAE": np.mean(np.abs(y - p)),
            "RMSE": np.sqrt(ss_res / len(y)),
            "R2": 1 - ss_res / np.sum((y - y.mean()) ** 2)}


def paired_boot(y: np.ndarray, pa: np.ndarray, pb: np.ndarray, days: np.ndarray,
                n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """配對的按日區塊 bootstrap,回傳 MAE(a) − MAE(b) 的 95% 區間。負值 = a 比較好。"""
    rng = np.random.default_rng(seed)
    ea, eb = np.abs(y - pa), np.abs(y - pb)
    uniq = np.unique(days)
    idx = {d: np.where(days == d)[0] for d in uniq}
    out = np.empty(n_boot)
    for i in range(n_boot):
        take = np.concatenate([idx[d] for d in rng.choice(uniq, len(uniq), replace=True)])
        out[i] = ea[take].mean() - eb[take].mean()
    return tuple(np.percentile(out, [2.5, 97.5]))


def main(quick: bool = False) -> None:
    os.makedirs(OUT, exist_ok=True)
    models = ["Lasso", "LightGBM"] if quick else ["Ridge", "Lasso", "LightGBM"]
    # pooled 便宜 → 三種重訓 × 兩種目標全掃;hourly 貴 → 只跑 monthly/roll12
    configs = [(r, "pooled", t) for r in ("once", "monthly", "roll12")
               for t in ("level", "detrend")]
    # hourly 很貴(LightGBM 逐小時一個設定要 ~20 分鐘)→ 只跑三個資訊量最高的:
    #   第一輪的對照點、第一輪的冠軍、以及對症修法的組合
    configs += [("once", "hourly", "level"), ("monthly", "hourly", "level"),
                ("roll12", "hourly", "detrend")]

    rep = ["# 模型 A 的改進實驗", "",
           f"測試期固定 {SPLIT} 起,所有變體評在**同一批列**上。",
           "🔴 判定標準:與基準(once+pooled 的同一個模型)配對按日 bootstrap,ΔMAE 區間跨 0 就不算改進。", ""]

    for area in ("DK1", "DK2"):
        df = load_training(area)
        feats = _features(df)
        for b in df[feats].select_dtypes("bool"):
            df[b] = df[b].astype(int)
        ts = pd.DatetimeIndex(df["timestamp_utc"])
        te = ts >= pd.Timestamp(SPLIT, tz=ts.tz)
        y = df.loc[te, TARGET].to_numpy()
        days = ts[te].tz_convert("UTC").date
        naive = df.loc[te, "price_lag24_eur"].to_numpy()
        mae_naive = np.mean(np.abs(y - naive))

        preds: dict[tuple, np.ndarray] = {}
        rows = []
        for model in models:
            for refit, pooling, target in configs:
                t0 = time.time()
                p = run(df, feats, model, refit, pooling, target).to_numpy()
                assert not np.isnan(p).any(), f"{area} {model} {refit}/{pooling}/{target} 有漏"
                preds[(model, refit, pooling, target)] = p
                m = metrics(y, p)
                rows.append({"模型": model, "重訓": refit, "建模": pooling, "目標": target,
                             **m, "rMAE": m["MAE"] / mae_naive, "秒": time.time() - t0})
                print(f"  {area} {model:<9} {refit:<8} {pooling:<7} {target:<8} "
                      f"MAE {m['MAE']:6.2f}  rMAE {m['MAE']/mae_naive:.3f}  "
                      f"({time.time()-t0:.0f}s)", flush=True)

        # 平均集成。兩種:全部三個 / 只有線性兩個
        #   ⚠️ 「只有線性」是**看到結果之後才加的**(LightGBM 明顯最弱),報告裡標成 post-hoc。
        for refit, pooling, target in configs:
            for tag, use in (("Ensemble", models), ("Ensemble(僅線性)", ["Ridge", "Lasso"])):
                avail = [preds[(m, refit, pooling, target)] for m in use
                         if (m, refit, pooling, target) in preds]
                if len(avail) < 2:
                    continue
                p = np.mean(avail, axis=0)
                preds[(tag, refit, pooling, target)] = p
                m = metrics(y, p)
                rows.append({"模型": tag, "重訓": refit, "建模": pooling, "目標": target,
                             **m, "rMAE": m["MAE"] / mae_naive, "秒": 0.0})

        t = pd.DataFrame(rows).sort_values("MAE")
        # 對照組固定成「baseline.py 的做法 + 當時最好的 Lasso」
        ref = preds[("Lasso", "once", "pooled", "level")]

        # 🔴 前後半期分開評 —— 排名是不是穩的,還是只在某一段成立。
        #    這是為了補上「最佳設定是在同一段測試期挑的」這個方法論漏洞。
        mid = ts[te].min() + (ts[te].max() - ts[te].min()) / 2
        h1, h2 = ts[te] < mid, ts[te] >= mid
        key = lambda r: (r["模型"], r["重訓"], r["建模"], r["目標"])
        t["前半 MAE"] = [metrics(y[h1], preds[key(r)][h1])["MAE"] for _, r in t.iterrows()]
        t["後半 MAE"] = [metrics(y[h2], preds[key(r)][h2])["MAE"] for _, r in t.iterrows()]
        ci = []
        for _, r in t.iterrows():
            lo, hi = paired_boot(y, preds[key(r)], ref, days)
            ci.append(f"[{lo:+.2f}, {hi:+.2f}]" + ("  ✅" if hi < 0 else ("  ❌" if lo > 0 else "  ~")))
        t["ΔMAE vs Lasso/once/pooled"] = ci

        pd.DataFrame({f"{m}|{r}|{pl}|{tg}": v for (m, r, pl, tg), v in preds.items()},
                     index=ts[te]).assign(actual=y).to_csv(
            os.path.join(OUT, f"predictions_{area.lower()}.csv"))
        rep += [f"## {area}(測試 {ts[te].min():%Y-%m-%d} → {ts[te].max():%Y-%m-%d}、"
                f"{te.sum():,} 小時、naive-24h MAE {mae_naive:.2f})", "",
                t.to_markdown(index=False, floatfmt=",.3f"), "",
                f"✅ = 顯著比基準好 · ❌ = 顯著比基準差 · ~ = 分不出來。"
                f"**前半 = {ts[te].min():%Y-%m} → {mid:%Y-%m},後半 = {mid:%Y-%m} 之後** ——"
                f"排名在兩半都成立才算穩。", ""]
        print("\n".join(rep[-4:]))

    with open(os.path.join(OUT, "EXPERIMENTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print(f"\n→ 已寫出 {os.path.join(OUT, 'EXPERIMENTS.md')}")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
