"""用 varmelast(大哥本哈根 DK2)**實際逐時熱需求**校準度日代理。

**為什麼要這支**:2026-08-05 的檢驗證明「代理 vs CHP 發電量」驗不動 —— 發電量由熱約束
與電價共同決定,電價影響大得多,所以那個標的沒有識別力(見 [[heat-chp-track]] 的更正)。
這裡改用**真值直接比對**:varmelast 有 CTR+VEKS 的實際熱需求,可以問三個以前答不了的問題:

  1. 度日模型的參數該是多少?(T_base、基載比例)—— 之前 17°C / 0.18 是猜的
  2. 日內形狀長什麼樣?—— 之前我假設早7/晚19 雙尖峰,那也是猜的
  3. **一個度日代理到底能解釋實際熱需求的多少變異?** ← 這才是真正的 kill criterion

⚠️ 這是 DK2(大哥本哈根)。DK1 沒有公開逐時熱需求,所以做法是:**在 DK2 校準函數形式,
移轉到 DK1,並在論文中明說這個外推假設**。形式(T_base、日內形狀)在丹麥境內可合理移轉,
規模(年熱量)必須用 DK1 自己的統計。

用法:python new_src/heat/calibrate.py
"""

import glob
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

DEMAND_COLS = ["BE-EO-CTR-EFF", "DAP-VEKS-FORBRUG-EFF"]  # CTR + VEKS 實際熱需求
# varmelast 官方公告:2026-07-10~29 的歷史資料有誤
BAD = (pd.Timestamp("2026-07-10", tz="UTC"), pd.Timestamp("2026-07-30", tz="UTC"))


def load_actual() -> pd.DataFrame:
    """實際熱需求(MW_th)+ 對齊的 DK2 氣溫。已清掉 0 值與官方公告的錯誤區間。"""
    fs = glob.glob("new_data/heat/varmelast_*.parquet")
    assert fs, "先跑 python new_src/data/varmelast_heat.py"
    v = pd.read_parquet(fs[0])
    v["t"] = pd.to_datetime(v["timestamp"], utc=True)
    have = [c for c in DEMAND_COLS if c in v]
    v["heat"] = v[have].fillna(0).sum(axis=1)

    n0 = len(v)
    v = v[(v["heat"] > 0) & ~v["t"].between(*BAD)]
    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    w = con.execute(
        "SELECT timestamp_utc, temperature_2m AS temp FROM training "
        "WHERE area='DK2' AND temperature_2m IS NOT NULL ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    w["t"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    m = v[["t", "heat"]].merge(w[["t", "temp"]], on="t").dropna()
    print(f"  實際熱需求 {len(m):,} 小時(原始 {n0:,},清掉 0 值/錯誤區間/無氣溫)")
    return m.reset_index(drop=True)


def fit_degree_day(m: pd.DataFrame) -> dict:
    """網格搜尋 T_base,對每個候選跑 OLS `heat ~ a + b·max(0, T_base−T)`,取 R² 最高。"""
    t, y = m["temp"].to_numpy(), m["heat"].to_numpy()
    best = None
    for tb in np.arange(8.0, 22.1, 0.5):
        dd = np.maximum(0.0, tb - t)
        X = np.column_stack([dd, np.ones(len(t))])
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        r2 = 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        if best is None or r2 > best["r2"]:
            best = {
                "t_base": float(tb),
                "slope": float(b[0]),
                "base": float(b[1]),
                "r2": float(r2),
            }
    # 基載比例 = 與氣溫無關的部分佔總熱量
    best["base_share"] = float(best["base"] * len(y) / y.sum())
    return best


def fit_diurnal(m: pd.DataFrame, fit: dict) -> pd.Series:
    """扣掉氣溫模型後,剩下的日內型態(乘數形式,均值 1)。這是**估出來**的,不是假設的。"""
    dd = np.maximum(0.0, fit["t_base"] - m["temp"].to_numpy())
    pred = fit["base"] + fit["slope"] * dd
    ratio = m["heat"].to_numpy() / np.maximum(pred, 1e-6)
    s = (
        pd.Series(ratio, index=m["t"].dt.tz_convert("Europe/Copenhagen").dt.hour)
        .groupby(level=0)
        .median()
    )
    return s / s.mean()


def r2_of(y, pred) -> float:
    return float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def main() -> None:
    print("=== 用 varmelast(大哥本哈根)實際熱需求校準度日代理 ===\n")
    m = load_actual()
    y = m["heat"].to_numpy()
    print(
        f"  熱需求 MW_th: 均 {y.mean():,.0f}  尖峰 {y.max():,.0f}  最低 {y.min():,.0f}"
        f"  年熱量 ≈ {y.mean() * 8760 / 1e6:.2f} TWh_th\n"
    )

    fit = fit_degree_day(m)
    print("--- ① 度日參數:猜的 vs 校準出來的 ---")
    print(f"  T_base      我假設 17.0°C   →  校準 {fit['t_base']:.1f}°C")
    print(f"  基載比例     我假設 0.18     →  校準 {fit['base_share']:.2f}")
    print(f"  斜率        {fit['slope']:.1f} MW_th/°C,基載 {fit['base']:.0f} MW_th")
    print(f"  **只有氣溫的 R² = {fit['r2']:.3f}**")

    dd = np.maximum(0.0, fit["t_base"] - m["temp"].to_numpy())
    pred_t = fit["base"] + fit["slope"] * dd

    diu = fit_diurnal(m, fit)
    hh = m["t"].dt.tz_convert("Europe/Copenhagen").dt.hour.to_numpy()
    pred_td = pred_t * diu.reindex(hh).to_numpy()
    print("\n--- ② 日內形狀:估出來的(不是假設的)---")
    print("  " + " ".join(f"{h:02d}h={diu[h]:.2f}" for h in range(0, 24, 3)))
    print(
        f"  尖峰 {diu.idxmax()}h ({diu.max():.2f})、低谷 {diu.idxmin()}h ({diu.min():.2f})、"
        f"振幅 {(diu.max() - diu.min()) * 100:.0f}%"
    )
    print(f"  → 我先前假設早 7h 尖峰;實際尖峰在 {diu.idxmax()}h")

    print("\n--- ③ 真正的 kill criterion:代理能解釋實際熱需求多少變異? ---")
    print(f"  只有氣溫(度日)        R² = {fit['r2']:.3f}")
    print(f"  氣溫 + 估出的日內形狀   R² = {r2_of(y, pred_td):.3f}")
    # 對照:我原本猜的參數,套在真實需求上表現如何
    dd_old = np.maximum(0.0, 17.0 - m["temp"].to_numpy())
    X = np.column_stack([dd_old, np.ones(len(y))])
    b = np.linalg.lstsq(X, y, rcond=None)[0]  # 規模仍需擬合(否則比的是單位不是形狀)
    print(f"  我原本的 T_base=17     R² = {r2_of(y, X @ b):.3f}  ← 形狀差多少")
    corr = float(np.corrcoef(pred_td, y)[0, 1])
    print(f"\n  逐時相關 corr(校準代理, 實際熱需求) = {corr:+.3f}")
    ok = r2_of(y, pred_td) > 0.6
    print(
        f"\n  → {'✅ 度日代理站得住(在有真值處驗證)' if ok else '⚠️ 代理解釋力不足,需要更多輸入(風速/濕度/社會行為)'}"
    )

    print("\n--- ④ 移轉到 DK1 的規模錨點 ---")
    print(f"  大哥本哈根(CTR+VEKS)年熱量 = {y.mean() * 8760 / 1e6:.2f} TWh_th")
    print(f"  `demand.ANNUAL_TWH_DK1 = 19.0` 是佔位值 → 需用能源署 DK1 統計替換;")
    print(f"  本數字可當合理性檢查(丹麥全國 DH 約 30 TWh 量級)。")


if __name__ == "__main__":
    main()
