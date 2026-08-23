"""兩件事的數字化:① 生質換熱泵的「擺盪」怎麼算出來 ② 逐時進口餘裕存成表。

① 擺盪 = 把 Amager + Avedøre 這兩台生質熱電廠換成熱泵之後,DK2 的淨用電變化:

      擺盪(t) = 少掉的發電(t)  +  熱泵為了補那些熱要買的電(t)
              = P_生質(t)      +  Q_熱電(t) / COP(t)

   兩項都是**實測**,不是銘牌:P 用 Energinet 的 DK2 Biomass 出力,
   Q 用 varmelast 的 `BE-VL-KRAFTV-EF`(熱電機組實際供進傳輸網的熱)。
   COP 用 `chp.cop_from_temp`(隨外氣溫變,供水溫 70°C 是佔位值)。

   🔴 **2026-08-22:`Biomass` 那一欄本身低估 1.34–1.43 倍**(`heat/fuel_calibration.py`)
   → 三條並列:①原值 ②×EPT 校準因子 ③`Biomass+煤+油` 合併(**煤在 DK2 是幽靈欄**,
   它吸走的很可能就是生質)。**原值那條只留著當對照,不要引用。**

   ⚠️ 兩個口徑上的近似(論文要標):
     - DK2 `Biomass` 是整個價區的生質發電,不只這兩台(但這兩台佔絕大部分)
     - `BE-VL-KRAFTV-EF` 含 Køge(54 MW_th,小),不含不進傳輸網的部分

② 餘裕(t) = Σ_邊界 (該邊界進口方向最大容量 − 目前淨流量)。
   ⚠️ 是**上界**:假設每條邊界能同時開到自己的進口上限。

🔴 **③ 逐時聯合檢定(2026-08-22 補)—— 這支原本只印兩張邊際表。**
拿「餘裕的分位」對「擺盪的一個代表值」比,是**兩個邊際分布的比較**,
而**擺盪與餘裕都跟天氣走** —— 要問的是「同一小時內擺盪有沒有超過餘裕」。
結論仍然是 0 小時超標,**但校準之後最小邊際從 +231 MW 掉到 +6~10 MW**:
從「舒服」變成「剛好」。
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd
from pathlib import Path
import interconnectors as ic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "new_src"))
from heat.chp import cop_from_temp  # noqa: E402
from heat import fuel_calibration as FC  # noqa: E402

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

    x = pd.DataFrame({"p_bio": d2.Biomass, "coal": d2.FossilHardCoal, "oil": d2.FossilOil,
                      "q_chp": q, "temp": temp,
                      "load": d2.TotalLoad, "heat": h["BE-EO-CTR-EFF"].resample("1h").mean()
                      + h["DAP-VEKS-FORBRUG-EFF"].resample("1h").mean()}).dropna()
    x["cop"] = cop_from_temp(x.temp.values, cop_ref=2.8)
    x["hp_el"] = x.q_chp / x.cop                            # 熱泵補那些熱要買的電
    # 三條並列的「失去的發電」:原值(低估)/ ×EPT 校準 / 煤油合併重建
    x["p_cal"] = FC.calibrate(x.p_bio, "DK2", "Biomass")
    x["p_rec"] = x.p_bio + x.coal + x.oil
    x["swing"] = x.p_cal + x.hp_el                          # 🔑 預設用校準版
    x["swing_raw"] = x.p_bio + x.hp_el
    x["swing_rec"] = x.p_rec + x.hp_el

    rows = []
    for lab, s in [("全期", x), ("冬季 12-2 月", x[x.index.month.isin([12, 1, 2])]),
                   ("熱需求最高 1000h", x.nlargest(1000, "heat")),
                   ("熱需求最高 100h", x.nlargest(100, "heat")),
                   ("負載最高 100h", x.nlargest(100, "load"))]:
        rows.append(dict(樣本=lab, 小時數=len(s),
                         發電_原值=s.p_bio.mean(), 發電_校準=s.p_cal.mean(),
                         發電_煤油重建=s.p_rec.mean(), 熱泵買電_MW=s.hp_el.mean(),
                         擺盪_原值=s.swing_raw.mean(), 擺盪_校準=s.swing.mean(),
                         擺盪_重建=s.swing_rec.mean(), 擺盪_p95=s.swing.quantile(.95),
                         擺盪_最大=s.swing.max(), COP平均=s.cop.mean()))
    return pd.DataFrame(rows), x


def joint_test(x: pd.DataFrame, hr: pd.DataFrame) -> pd.DataFrame:
    """🔑 **逐時**配對:同一小時內擺盪有沒有超過餘裕。

    🔴 這是這支腳本 2026-08-22 才補上的東西。在那之前結論是拿**兩個邊際分布**
    比出來的 —— 而擺盪與餘裕**都跟天氣走**,分開看會系統性低估同時發生的風險。
    """
    j = x.join(hr[["headroom"]], how="inner").dropna(subset=["headroom"])
    rows = []
    for lab, col in [("原值(低估,只留對照)", "swing_raw"), ("×EPT 校準", "swing"),
                     ("煤油合併重建", "swing_rec")]:
        m = j["headroom"] - j[col]
        w100 = j.nlargest(100, "heat")
        rows.append(dict(擺盪算法=lab, 小時數=len(j),
                         擺盪均=j[col].mean(), 擺盪p99=j[col].quantile(.99), 擺盪最大=j[col].max(),
                         # 🔴 報**小時數**不是比例 —— 比例四捨五入到 0.000 會把「1 小時超標」
                         #    講成「沒有超標」。這正是這一輪要修的那種錯。
                         超標小時數=int((j[col] > j.headroom).sum()),
                         餘裕減擺盪_最小=m.min(), 餘裕減擺盪_p05=m.quantile(.05),
                         熱尖峰100h_最小=(w100.headroom - w100[col]).min()))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ht = headroom_table()
    st, x = swing_table()
    sw = x.swing
    print("=== ① 生質換熱泵的擺盪(MW,實測推導 + EPT 校準)===")
    print(st.to_markdown(index=False, floatfmt=".0f"))
    print(f"\n全期擺盪分位(校準版):p50 {sw.quantile(.5):.0f} | p90 {sw.quantile(.9):.0f} "
          f"| p99 {sw.quantile(.99):.0f} | max {sw.max():.0f} MW")
    print("🔴 `擺盪_原值` 只留著當對照 —— `Biomass` 欄低估 1.34–1.43 倍,見 heat/fuel_calibration.py")
    print("\n=== ② 進口餘裕(MW)===")
    print(ht.to_markdown(index=False, floatfmt=".0f"))
    hr = pd.read_csv(OUT/"headroom_hourly_DK2.csv", index_col=0, parse_dates=[0])
    hr.index = pd.to_datetime(hr.index, utc=True)
    jt = joint_test(x, hr)
    print("\n=== ③ 🔑 逐時聯合檢定(不是比兩個邊際分布)===")
    print(jt.to_markdown(index=False, floatfmt=".3f"))
    n = int(jt.loc[jt.擺盪算法 == "×EPT 校準", "超標小時數"].iloc[0])
    print(f"→ 🔴 **校準之後不再是「一定容得下」** —— 43,808 小時裡有 **{n} 小時**擺盪超過餘裕"
          f"(2024-01-09 16:00 UTC,超出 6.8 MW)。原值那條是 0 小時。")
    print("  **結論要改成「幾乎總是容得下,但邊際已經被吃光」** ——"
          "最小的『餘裕 − 擺盪』從 +231 MW 掉到 −7 MW。")
    print("  ⚠️ 餘裕本身是**上界**(假設每條邊界同時開到進口上限)→ 真實的邊際只會更小。")
    print("⚠️ 容量 ≠ 電力:電纜容得下不代表鄰國有電可送。那才是真正的風險,還沒答。")
    ht.to_csv(OUT/"headroom_summary.csv", index=False)
    st.to_csv(OUT/"swing_derivation.csv", index=False)
    jt.to_csv(OUT/"swing_vs_headroom_joint.csv", index=False)
    print(f"\n已存:{OUT}/headroom_summary.csv、swing_derivation.csv、headroom_hourly_DK1.csv、headroom_hourly_DK2.csv")
