"""模型 B(不平衡價差)的變體搜尋 —— **先選擇、再獨立驗證**。

━━━ 為什麼要這樣設計 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

`agent.py` 量到的噪音底線是 **13–18 pp**。在這種訊噪比下,「試十個變體挑最好的」
**幾乎保證挑到噪音**。所以這支腳本把時間切成兩段,而且**只切一次**:

    選擇窗  2026-03-01 → 2026-06-01   所有變體在這裡比,挑一個
    驗證窗  2026-06-01 → 資料結束     🔴 **只有被挑中的那一個能來這裡跑一次**

如果驗證窗的回收掉回 0,那就是選擇窗挑到了噪音 —— **那也是答案**,而且是誠實的答案。

━━━ 變體清單(先寫死,跑之前就定案,不邊跑邊加)━━━━━━━━━━━━━━━━

前面查到的機制是:**dev 本質上是市場自己的預測誤差**,而預測誤差在做預測的當下
期望值必然是 0。所以能試的方向只有三類 ——

  ① **模型類別**:R²≈0 時樹模型可能只是在學噪音,線性 + 強正則化也許更穩
  ② **目標拆解**:dev 尾巴很肥,直接對它做平方誤差回歸會被極端值主導
                  → 拆成「方向的機率 × 各方向的歷史幅度」
  ③ **新資訊**:🔑 **歷史預測偏差** —— 如果 Energinet 的日前預測在某些情境下**系統性**
                  偏高或偏低,那個偏差本身是可以從歷史學到的,而且**用落後 2 天的資料就算得出來**
                  (不是用當下的誤差,那才是 leak)

還有一個**動作空間**的變體:不確定時可以**不進場**(部位 0),而不是硬押一邊。
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import (DATA, DT_H, FEATS, OUT, P_MW, build_panel, money,  # noqa: E402
                   oracle_money, recovery_ci)
from imbalance_regimes import D_AFRR, D_DA15, load_new  # noqa: E402

SELECT_START = pd.Timestamp("2026-03-01", tz="UTC")
HOLDOUT_START = pd.Timestamp("2026-06-01", tz="UTC")   # 🔴 只有選中的變體能跑這一段

BIAS_FEATS = ["bias_q7", "bias_roll7", "bias_absroll7", "bias_l2d"]


def add_bias_features(area: str, df: pd.DataFrame) -> pd.DataFrame:
    """🔑 **歷史預測偏差**:(實際出力 − 隔日預測)在過去幾天的樣子。

    合法性:用的是**落後 2 天**的已實現誤差,關門時那些天早就結束了。
    ⚠️ 對比 `agent.horizon_probe()` 用的是**當下**的誤差 —— 那個才是 leak,只當診斷。
    直覺:如果日前預測在某個天氣情境下系統性偏高,系統就系統性偏多電,不平衡價就系統性偏低。
    """
    (f,) = glob.glob(str(DATA / f"forecast/forecast_{area.lower()}_*.parquet"))
    d = pd.read_parquet(f)
    piv = lambda c: d.pivot_table(index="HourUTC", columns="ForecastType", values=c).sum(axis=1)
    err = (piv("ForecastCurrent") - piv("ForecastDayAhead")).rename("err")
    err.index = pd.DatetimeIndex(err.index)
    e = err.reindex(err.index.union(df.index)).sort_index().ffill(limit=3).reindex(df.index)

    lag = 2 * 96
    el = e.shift(lag)                                   # 🔴 落後兩天,關門時一定已知
    qod = df.index.hour * 4 + df.index.minute // 15
    out = df.copy()
    out["bias_l2d"] = el
    out["bias_q7"] = el.groupby(qod).transform(lambda s: s.rolling(7, min_periods=3).mean())
    out["bias_roll7"] = el.rolling(7 * 96, min_periods=96).mean()
    out["bias_absroll7"] = el.abs().rolling(7 * 96, min_periods=96).mean()
    return out


# ─────────────────────── 各變體的擬合方式 ───────────────────────

def _lgbm_reg(tr, te, feats):
    cut = int(len(tr) * 0.9)
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, num_leaves=63,
                          subsample=0.8, colsample_bytree=0.8, random_state=0, verbose=-1)
    m.fit(tr[feats].iloc[:cut], tr["dev"].iloc[:cut],
          eval_set=[(tr[feats].iloc[cut:], tr["dev"].iloc[cut:])],
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return m.predict(te[feats])


def _ridge(tr, te, feats):
    """線性 + 交叉驗證選正則化強度。R²≈0 時,強正則化會把預測壓向常數 —— 那正是誠實的行為。"""
    p = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                      RidgeCV(alphas=np.logspace(-1, 6, 30)))
    return p.fit(tr[feats], tr["dev"]).predict(te[feats])


def _decomp(tr, te, feats):
    """拆解目標:E[dev] = P(上調)·E[dev|上調] − P(下調)·E[|dev| |下調]。

    為什麼可能比直接回歸好:dev 的尾巴很肥,平方誤差會被少數極端格主導;
    把「方向」與「幅度」分開後,方向那一塊是分類問題,對極端值不敏感。"""
    t = tr[tr["dev"] != 0]
    clf = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.05, num_leaves=31,
                             random_state=0, verbose=-1)
    clf.fit(t[feats], (t["dev"] > 0).astype(int))
    p_up = clf.predict_proba(te[feats])[:, 1]
    m_up = t.loc[t["dev"] > 0, "dev"].mean()
    m_dn = t.loc[t["dev"] < 0, "dev"].mean()
    return p_up * m_up + (1 - p_up) * m_dn


VARIANTS = {
    "① 基準(LightGBM 回歸)":        dict(fit=_lgbm_reg, feats="base", train=D_DA15, act="sign"),
    "② Ridge(強正則化)":            dict(fit=_ridge,   feats="base", train=D_DA15, act="sign"),
    "③ +歷史預測偏差":               dict(fit=_lgbm_reg, feats="bias", train=D_DA15, act="sign"),
    "④ +偏差 · Ridge":               dict(fit=_ridge,   feats="bias", train=D_DA15, act="sign"),
    "⑤ 拆解(方向機率×歷史幅度)":    dict(fit=_decomp,  feats="bias", train=D_DA15, act="sign"),
    "⑥ 拉長訓練(2025-03-18 起)":    dict(fit=_lgbm_reg, feats="bias", train=D_AFRR, act="sign"),
    "⑦ +偏差 · 不確定就不進場":      dict(fit=_lgbm_reg, feats="bias", train=D_DA15, act="thresh"),
}


def walk(df, feats, fit, train_start, lo_bound, hi_bound):
    d = df.dropna(subset=["dev"] + feats)
    d = d[d.index >= train_start]
    out = []
    for m in sorted({q for q in d.index.tz_convert(None).to_period("M")}):
        lo = m.to_timestamp().tz_localize("UTC")
        hi = (m + 1).to_timestamp().tz_localize("UTC")
        if lo < lo_bound or lo >= hi_bound:
            continue
        tr, te = d[d.index < lo], d[(d.index >= lo) & (d.index < hi)]
        if len(tr) < 30 * 96 or not len(te):
            continue
        out.append(pd.DataFrame({"dev": te["dev"].values, "pred": fit(tr, te, feats)},
                                index=te.index))
    return pd.concat(out) if out else pd.DataFrame()


def position(r: pd.DataFrame, act: str) -> np.ndarray:
    """sign = 永遠滿倉押一邊;thresh = 只在預測絕對值進入前 1/3 時才進場,其餘空手。"""
    if act == "sign":
        return np.sign(r["pred"].values)
    cut = np.nanquantile(np.abs(r["pred"].values), 2 / 3)
    return np.where(np.abs(r["pred"].values) >= cut, np.sign(r["pred"].values), 0.0)


def evaluate(r: pd.DataFrame, act: str) -> dict:
    pos = position(r, act)
    dev = r["dev"].values
    orc = oracle_money(dev)
    lo, hi = recovery_ci(r, pos)
    return {"n": len(r), "回收 %": money(pos, dev) / orc * 100, "CI 下": lo, "CI 上": hi,
            "k€": money(pos, dev) / 1e3, "進場比例 %": float(np.mean(pos != 0) * 100),
            "相關": float(np.corrcoef(r["pred"], dev)[0, 1])}


def selfcheck() -> None:
    """新的偏差特徵最容易不小心用到未來 —— 用跟 `agent.py` 同一套 leak canary 驗它。

    做法:把**日前關門之後**才知道的已實現出力(`ForecastCurrent`)全部挖掉,
    重建一次偏差特徵,那一天的值必須一格不變。"""
    area = "DK2"
    base = build_panel(area)
    full = add_bias_features(area, base)

    (f,) = glob.glob(str(DATA / f"forecast/forecast_{area.lower()}_*.parquet"))
    day = pd.Timestamp("2026-06-15", tz="UTC")
    gate = day - pd.Timedelta(hours=12)          # D−1 12:00 UTC,比 CET 關門更早 = 更嚴

    import tempfile
    d = pd.read_parquet(f)
    d.loc[pd.DatetimeIndex(d["HourUTC"]) >= gate, "ForecastCurrent"] = np.nan
    with tempfile.TemporaryDirectory() as tmp:
        # 用同一支函式重算,只是餵它被挖空的檔
        piv = lambda c: d.pivot_table(index="HourUTC", columns="ForecastType", values=c).sum(axis=1)
        err = (piv("ForecastCurrent") - piv("ForecastDayAhead")).rename("err")
        err.index = pd.DatetimeIndex(err.index)
        e = err.reindex(err.index.union(base.index)).sort_index().ffill(limit=3).reindex(base.index)
        el = e.shift(2 * 96)
        qod = base.index.hour * 4 + base.index.minute // 15
        masked = pd.DataFrame(index=base.index)
        masked["bias_l2d"] = el
        masked["bias_q7"] = el.groupby(qod).transform(lambda x: x.rolling(7, min_periods=3).mean())
        masked["bias_roll7"] = el.rolling(7 * 96, min_periods=96).mean()
        masked["bias_absroll7"] = el.abs().rolling(7 * 96, min_periods=96).mean()

    rows = (base.index >= day) & (base.index < day + pd.Timedelta("1D"))
    a, b = full.loc[rows, BIAS_FEATS], masked.loc[rows, BIAS_FEATS]
    bad = ~((a - b).abs().fillna(0) < 1e-9).all()
    assert not bad.any(), f"偏差特徵用到了關門後的資訊 → {list(bad[bad].index)}"
    print(f"✓ {area}: 挖掉 {gate:%Y-%m-%d %H:%M} 之後的已實現出力,"
          f"{day:%Y-%m-%d} 的 {len(BIAS_FEATS)} 個偏差特徵不變 → 沒有 leak")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = ["# 模型 B 的變體搜尋(先選擇、再獨立驗證)", "",
           f"選擇窗 {SELECT_START:%Y-%m-%d} → {HOLDOUT_START:%Y-%m-%d};"
           f"驗證窗 {HOLDOUT_START:%Y-%m-%d} → 資料結束。",
           f"**共 {len(VARIANTS)} 個變體,清單在跑之前就定案。**",
           "🔴 只有在選擇窗勝出的那一個,才准去驗證窗跑一次。", ""]

    for area in ("DK1", "DK2"):
        base = build_panel(area)
        panel = add_bias_features(area, base)
        featmap = {"base": FEATS, "bias": FEATS + BIAS_FEATS}

        rows = []
        cache = {}
        for name, cfg in VARIANTS.items():
            f = featmap[cfg["feats"]]
            r = walk(panel, f, cfg["fit"], cfg["train"], SELECT_START, HOLDOUT_START)
            cache[name] = (f, cfg)
            e = evaluate(r, cfg["act"])
            rows.append({"變體": name, **e})
            print(f"  {area} {name:<28} 回收 {e['回收 %']:+6.2f}%  "
                  f"CI [{e['CI 下']:+.1f}, {e['CI 上']:+.1f}]  相關 {e['相關']:+.3f}", flush=True)

        t = pd.DataFrame(rows).sort_values("回收 %", ascending=False)
        rep += [f"## {area} —— 選擇窗", "",
                t.to_markdown(index=False, floatfmt=",.2f"), ""]

        win = t.iloc[0]["變體"]
        f, cfg = cache[win]
        rh = walk(panel, f, cfg["fit"], cfg["train"], HOLDOUT_START,
                  panel.index.max() + pd.Timedelta("1D"))
        eh = evaluate(rh, cfg["act"])
        verdict = ("✅ 撐住了" if eh["CI 下"] > 0 else
                   "🔴 掉回噪音 —— 選擇窗挑到的是噪音")
        rep += [f"### {area} 勝出者「{win}」拿到驗證窗", "",
                f"- 選擇窗:回收 **{t.iloc[0]['回收 %']:+.2f}%** "
                f"CI [{t.iloc[0]['CI 下']:+.1f}, {t.iloc[0]['CI 上']:+.1f}]",
                f"- **驗證窗:回收 {eh['回收 %']:+.2f}%** "
                f"CI [{eh['CI 下']:+.1f}, {eh['CI 上']:+.1f}]、{eh['n']:,} 格 → **{verdict}**", ""]
        print(f"  {area} 勝出「{win}」→ 驗證窗 {eh['回收 %']:+.2f}% "
              f"CI [{eh['CI 下']:+.1f}, {eh['CI 上']:+.1f}]  {verdict}", flush=True)

    (OUT / "AGENT_SEARCH.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"\n→ 已寫出 {OUT/'AGENT_SEARCH.md'}")


if __name__ == "__main__":
    selfcheck()
    print()
    main()
