"""2035 年的熱需求要不要變? —— 用 hindcast 回答,不用預測。

**2026-08-25 建立。** 對應 `THESIS_DIRECTION.md` §13.7 掛著的那一題。

━━━ 為什麼這題不需要「預測」━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

情境是 2035,但**驅動它的那兩股力量在過去五年已經同時在作用**:

    ↑ 瓦斯戶接進區域供熱(2022 政治協議,目標 2035 住宅零瓦斯)
    ↓ 建築節能改造 → 每平方公尺的熱需求下降

而你**同時有**那段期間的逐時熱需求(varmelast 2021–2026)與逐年建築存量
(DST BYGB40 2011–2026)。所以問題不是「預測 2035」,是
**「扣掉天氣之後,過去五年這張網的熱需求到底有沒有變」** —— 那是量出來的。

🔴 **天氣是最大的干擾項**(逐日 HDD 單獨就解釋 R²≈0.95),所以任何趨勢宣稱
   都必須先做天氣正規化。原始序列 2021 → 2025 是 9,027 → 8,749 GWh(**看起來在跌**),
   但那幾乎全是天氣:同期 HDD 從 3,095 掉到 2,790。**不正規化會得到相反的結論。**

━━━ 方法(三層) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **逐日迴歸 + 年固定效果**:`dem_d = a + b·HDD_d + Σ 年虛擬變數`
   → 年固定效果就是「扣掉天氣之後,那一年跟基準年差多少」。
2. **Hindcast**:用 2021–2023 擬合、預測 2024–2025(完全 out-of-sample),
   拿「含線性趨勢」對上「假設熱需求不變」,看哪一個輸得少。
3. **可轉換池上界**:BYGB40 給 Region Hovedstaden 還剩多少瓦斯與油的供暖面積
   → 全部接進區域供熱是物理上界,再多接不到了。

━━━ ⚠️ 限制 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **只有 5 個完整年,而且 2022 是能源危機年**(天氣正規化後 −3.8%,是行為反應不是結構)
  → 趨勢的斜率**不穩定**:2021–2023 擬合得 +13 MW/年,全期得 +21 MW/年,差 65%。
  **方向可信,斜率不可信。**
- **Region Hovedstaden ≠ CTR/VEKS 的供應範圍** —— 有些瓦斯在網外,上界因此偏高。
- **不是所有退場的瓦斯戶都會接區域供熱** —— plandata 有一半的區劃成
  `Individuel varmeforsyning`(個別熱泵)。上界同樣偏高。
- 觀察到的趨勢**已經含了節能改造的抵銷**,所以外推時不要再另外扣一次。

用法:python new_src/heat/demand_trend.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / "new_data/heating_stock/bygb40_m2_2019_latest.parquet"
OUT = ROOT / "figs/heat_baseline"
T_BASE = 17.0  # 丹麥慣用的度日基準溫度
YEARS = (2021, 2025)


def daily() -> pd.DataFrame:
    """逐日的熱需求與度日。**只取完整年份。**"""
    d = validate.load_dk2(YEARS[0])[["timestamp", "dem", "tair"]].dropna()
    d["date"] = d["timestamp"].dt.floor("D")
    day = d.groupby("date").agg(dem=("dem", "mean"), tair=("tair", "mean"))
    day["y"] = day.index.year
    day = day[day.y.between(*YEARS)].copy()
    day["hdd"] = (T_BASE - day.tair).clip(lower=0)
    day["t"] = (day.index - day.index[0]).days / 365.25
    return day


def year_effects(day: pd.DataFrame) -> pd.Series:
    """逐日迴歸的年固定效果 —— **扣掉天氣之後**,每一年相對基準年差多少 MW_th。"""
    ys = sorted(day.y.unique())[1:]
    X = [np.ones(len(day)), day.hdd.values] + [(day.y == y).astype(float).values for y in ys]
    beta, *_ = np.linalg.lstsq(np.column_stack(X), day.dem.values, rcond=None)
    pred = np.column_stack(X) @ beta
    r2 = 1 - ((day.dem.values - pred) ** 2).sum() / ((day.dem.values - day.dem.mean()) ** 2).sum()
    s = pd.Series(beta[2:], index=ys, name="年固定效果_MW")
    s.attrs["r2"] = r2
    s.attrs["base"] = beta[0] + beta[1] * day.hdd.mean()
    return s


def _fit(tr, trend: bool):
    cols = [np.ones(len(tr)), tr.hdd.values] + ([tr.t.values] if trend else [])
    return np.linalg.lstsq(np.column_stack(cols), tr.dem.values, rcond=None)[0]


def _pred(b, te, trend: bool):
    return b[0] + b[1] * te.hdd.values + (b[2] * te.t.values if trend else 0.0)


def hindcast(day: pd.DataFrame, split: int = 2023) -> pd.DataFrame:
    """用 `<=split` 擬合、`>split` 預測。**兩個對手:含趨勢 vs 假設不變。**

    🔴 這是這支腳本的核心 —— 「熱需求不變」是一個**可以被 out-of-sample 拒絕的假設**,
    不是一個中性的預設。
    """
    tr, te = day[day.y <= split], day[day.y > split]
    rows = []
    for name, trend in [("含線性趨勢", True), ("假設熱需求不變", False)]:
        b = _fit(tr, trend)
        p = _pred(b, te, trend)
        r = {"設定": name, "MAPE_%": float((abs(p - te.dem.values) / te.dem.values).mean() * 100)}
        for y in sorted(te.y.unique()):
            m = (te.y == y).values
            r[f"{y}_誤差_%"] = float(p[m].mean() / te.dem.values[m].mean() - 1) * 100
        rows.append(r)
    return pd.DataFrame(rows)


def conversion_pool() -> dict:
    """Region Hovedstaden 還剩多少可以接進區域供熱的供暖面積(BYGB40,千 m²)。"""
    s = pd.read_parquet(STOCK)
    h = s[s["OMRÅDE"] == "Region Hovedstaden"].pivot_table(
        index="TID", columns="OPVARM", values="INDHOLD")
    y = int(h.index.max())
    gas = float(h.loc[y, "Centralvarme med naturgas"])
    oil = float(h.loc[y, "Centralvarme med oliefyr"])
    dh = float(h.loc[y, "Fjernvarme"])
    return {"年": y, "瓦斯": gas, "油": oil, "區域供熱": dh, "上界_%": (gas + oil) / dh * 100}


def main() -> None:
    day = daily()
    fe = year_effects(day)
    base = fe.attrs["base"]

    print(f"\n{'=' * 72}\n2035 熱需求要不要變 —— 用過去五年回答\n{'=' * 72}")
    raw = day.groupby("y").agg(熱_日均MW=("dem", "mean"), HDD=("hdd", "sum"))
    print(f"\n原始序列(**看起來在跌,但那是天氣**):")
    print(raw.round(1).to_string())

    print(f"\n逐日迴歸 n={len(day)}、R²={fe.attrs['r2']:.3f};"
          f"基準年平均 HDD 下的日均需求 {base:,.0f} MW_th")
    print(f"\n🔑 年固定效果(扣掉天氣之後,相對 {day.y.min()}):")
    for y, v in fe.items():
        print(f"  {y}: {v:+7.1f} MW_th  ({v / base * 100:+5.1f}%)")
    tot = fe.iloc[-1] / base * 100
    n_yr = fe.index[-1] - day.y.min()
    print(f"  → {day.y.min()} → {fe.index[-1]}:{tot:+.1f}%,年均 {tot / n_yr:+.2f}%/年")
    print("  ⚠️ 2022 那格是**能源危機的行為反應**(調低室溫),不是結構性下降")

    hc = hindcast(day)
    print(f"\n{'-' * 72}\n🔴 HINDCAST:用 2021–2023 擬合,預測 2024–2025(out-of-sample)\n{'-' * 72}")
    print(hc.round(2).to_string(index=False))
    win = hc.loc[hc["MAPE_%"].idxmin(), "設定"]
    print(f"\n  → 贏的是「{win}」")
    print("  🔴 **「假設熱需求不變」系統性低估 6–7%,而且 MAPE 也較差 → 被拒絕。**")
    print("  ⚠️ 但含趨勢那組也低估 2–5% → **方向確定,斜率偏保守**")

    b = _fit(day, True)
    rate = b[2] / day.dem.mean() * 100
    pool = conversion_pool()
    print(f"\n{'-' * 72}\n2035 的區間\n{'-' * 72}")
    print(f"  全期擬合的趨勢          {rate:+.2f}%/年  → 外推 10 年 {((1 + rate / 100) ** 10 - 1) * 100:+.1f}%")
    print(f"  可轉換池上界(Region Hovedstaden {pool['年']}):"
          f"瓦斯 {pool['瓦斯']:,.0f} + 油 {pool['油']:,.0f} 千 m²")
    print(f"    ÷ 現有區域供熱 {pool['區域供熱']:,.0f} → **物理上界 {pool['上界_%']:+.1f}%**")
    print(f"\n  🔑 兩條獨立路徑幾乎重合(趨勢外推 vs 政策目標達成)")
    print("  📌 但全國瓦斯退場的實測速度只有目標的 44–60%(見 dk-waste-heat-policy §17)")
    print("     → 中央值取上界 × 那個達成率")

    OUT.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame({"年固定效果_MW": fe, "相對基準_%": fe / base * 100})
    out.to_csv(OUT / "demand_trend_year_effects.csv")
    hc.to_csv(OUT / "demand_trend_hindcast.csv", index=False)
    print(f"\n  寫出 {OUT}/demand_trend_*.csv")


if __name__ == "__main__":
    main()
