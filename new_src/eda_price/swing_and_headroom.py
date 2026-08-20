"""兩件事的數字化:① 生質換熱泵的「擺盪」怎麼算出來 ② 逐時進口餘裕存成表。

① 擺盪 = 把 Amager + Avedøre 這兩台生質熱電廠換成熱泵之後,DK2 的淨用電變化:

      擺盪(t) = 少掉的發電(t)  +  熱泵為了補那些熱要買的電(t)
              = P_生質(t)      +  Q_熱電(t) / COP(t)

   兩項都是**實測**,不是銘牌:P 用 Energinet 的 DK2 Biomass 出力,
   Q 用 varmelast 的 `BE-VL-KRAFTV-EF`(熱電機組實際供進傳輸網的熱)。
   COP 用 `chp.cop_from_temp`(隨外氣溫變,供水溫 70°C 是佔位值)。

   ⚠️ 兩個口徑上的近似(論文要標):
     - DK2 `Biomass` 是整個價區的生質發電,不只這兩台(但這兩台佔絕大部分)
     - `BE-VL-KRAFTV-EF` 含 Køge(54 MW_th,小),不含不進傳輸網的部分

② 餘裕(t) = Σ_邊界 (該邊界進口方向最大容量 − 目前淨流量)。
   ⚠️ 是**上界**:假設每條邊界能同時開到自己的進口上限。
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd
from pathlib import Path
import interconnectors as ic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "new_src"))
from heat.chp import cop_from_temp  # noqa: E402

DATA, OUT = ROOT / "new_data", ROOT / "figs" / "price_formation"
EXC = {"DK2": ["ExchangeNordicCountries", "ExchangeContinent", "ExchangeGreatBelt"],
       "DK1": ["ExchangeNordicCountries", "ExchangeContinent", "ExchangeGreatBelt",
               "ExchangeGreatBritain"]}


def prod(z: str) -> pd.DataFrame:
    d = pd.read_parquet(next((DATA/"production").glob(f"production_{z.lower()}_*.parquet")))
    d = d.rename(columns={"HourUTC": "t"}).set_index("t").sort_index()
    d = d.resample("1h").mean(numeric_only=True)
    d.loc[d.TotalLoad > 1.2 * d.TotalLoad.quantile(.999), "TotalLoad"] = np.nan
    return d


def headroom_table() -> pd.DataFrame:
    rows, series = [], {}
    for z in ("DK1", "DK2"):
        d = prod(z)
        cols = [c for c in EXC[z] if d[c].notna().any()]
        cap = sum(ic.cap(z, c)[0] for c in cols)
        hr = sum(ic.cap(z, c)[0] - d[c] for c in cols)
        x = pd.DataFrame({"load": d.TotalLoad, "headroom": hr}).dropna()
        series[z] = x
        for lab, s in [("全期", x), ("冬季 12-2 月", x[x.index.month.isin([12, 1, 2])]),
                       ("負載最高 1000h", x.nlargest(1000, "load")),
                       ("負載最高 100h", x.nlargest(100, "load"))]:
            rows.append(dict(價區=z, 進口容量合計_MW=cap, 樣本=lab, 小時數=len(s),
                             餘裕_中位=s.headroom.median(), 餘裕_p05=s.headroom.quantile(.05),
                             餘裕_最小=s.headroom.min(),
                             低於1000MW的比例=(s.headroom < 1000).mean()))
    for z, x in series.items():
        x.to_csv(OUT / f"headroom_hourly_{z}.csv")
    return pd.DataFrame(rows)


def swing_table() -> tuple[pd.DataFrame, pd.Series]:
    d2 = prod("DK2")
    h = pd.read_parquet(DATA/"heat/varmelast_ckb_2021_2026.parquet")
    h = h.rename(columns={"timestamp": "t"}).set_index("t")
    q = h["BE-VL-KRAFTV-EF"].resample("1h").mean()          # 熱電機組實際供熱 MW_th
    w = pd.read_parquet(next((DATA/"weather").glob("weather_dk2_*.parquet")))
    tcol = [c for c in w.columns if "temperature" in c][0]
    tk = [c for c in w.columns if c.lower() in ("time", "date", "hour_utc", "timestamp")][0]
    temp = w.set_index(pd.to_datetime(w[tk], utc=True))[tcol].resample("1h").mean()

    x = pd.DataFrame({"p_bio": d2.Biomass, "q_chp": q, "temp": temp,
                      "load": d2.TotalLoad, "heat": h["BE-EO-CTR-EFF"].resample("1h").mean()
                      + h["DAP-VEKS-FORBRUG-EFF"].resample("1h").mean()}).dropna()
    x["cop"] = cop_from_temp(x.temp.values, cop_ref=2.8)
    x["hp_el"] = x.q_chp / x.cop                            # 熱泵補那些熱要買的電
    x["swing"] = x.p_bio + x.hp_el                          # 總擺盪

    rows = []
    for lab, s in [("全期", x), ("冬季 12-2 月", x[x.index.month.isin([12, 1, 2])]),
                   ("熱需求最高 1000h", x.nlargest(1000, "heat")),
                   ("熱需求最高 100h", x.nlargest(100, "heat")),
                   ("負載最高 100h", x.nlargest(100, "load"))]:
        rows.append(dict(樣本=lab, 小時數=len(s),
                         少掉的發電_MW=s.p_bio.mean(), 熱泵買電_MW=s.hp_el.mean(),
                         擺盪_平均=s.swing.mean(), 擺盪_p95=s.swing.quantile(.95),
                         擺盪_最大=s.swing.max(), COP平均=s.cop.mean()))
    return pd.DataFrame(rows), x.swing


if __name__ == "__main__":
    ht = headroom_table()
    st, sw = swing_table()
    print("=== ① 生質換熱泵的擺盪(MW,實測推導)===")
    print(st.to_markdown(index=False, floatfmt=".0f"))
    print(f"\n全期擺盪分位:p50 {sw.quantile(.5):.0f} | p90 {sw.quantile(.9):.0f} "
          f"| p99 {sw.quantile(.99):.0f} | max {sw.max():.0f} MW")
    print("\n=== ② 進口餘裕(MW)===")
    print(ht.to_markdown(index=False, floatfmt=".0f"))
    ht.to_csv(OUT/"headroom_summary.csv", index=False)
    st.to_csv(OUT/"swing_derivation.csv", index=False)
    print(f"\n已存:{OUT}/headroom_summary.csv、swing_derivation.csv、headroom_hourly_DK1.csv、headroom_hourly_DK2.csv")
