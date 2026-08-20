"""鄰國會不會在 DK2 最緊的時候同時緊?

問題來源:進口餘裕算出「電纜容得下生質換熱泵的 993–1,120 MW 擺盪」,
但**容量 ≠ 電力** —— 電纜容得下不代表鄰國有電可送。這支就是在答那個。

方法:
  1. 用「殘餘需求」(負載 − 風 − 光)定義「緊」。DK2 用實測,鄰國用日前預測。
  2. 🔴 **必須去季節性**。DK2 冬天緊、SE4 冬天也緊 → 生的相關必然好看,那是套套邏輯。
     做法:把每個價區的殘餘需求換成**同一個「月×時」格子內的百分位**,
     再問「DK2 在自己格子裡排前 10% 時,鄰國在自己格子裡排第幾」。
  3. 除了統計,也看**實際結果**:那些小時的逐邊界流量與剩餘進口餘裕。

⚠️ 口徑不一致(要寫進論文):DK2 是事後實測,鄰國是日前預測。
   預測噪音會**稀釋**相關 → 若仍看到訊號,那是保守的下界。
"""
from __future__ import annotations
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import interconnectors as ic

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "price_formation"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.dpi": 140, "font.size": 9, "axes.grid": True, "grid.alpha": .25,
                     "axes.spines.top": False, "axes.spines.right": False})

NB = {"SE4": "residual_se_4", "DE": "residual_de_lu"}     # DK2 的兩個外國鄰居,就這兩個
EXC = ["ExchangeNordicCountries", "ExchangeContinent", "ExchangeGreatBelt"]


def pct_within_month_hour(s: pd.Series) -> pd.Series:
    """同一個「月×時」格子內的百分位(0–1)。去掉季節與日內形狀。"""
    g = pd.Series(s.index.month.astype(str) + "_" + s.index.hour.astype(str), index=s.index)
    return s.groupby(g).rank(pct=True)


def load() -> pd.DataFrame:
    r = pd.read_parquet(next((DATA/"residual").glob("residual_dk2_*.parquet")))
    r = r.rename(columns={"hour_utc": "t"}).set_index("t")[["residual_mwh", "load_mwh"]]
    r = r.rename(columns={"residual_mwh": "dk2_res", "load_mwh": "dk2_load"}).resample("1h").mean()
    p = pd.read_parquet(next((DATA/"production").glob("production_dk2_*.parquet")))
    p = p.rename(columns={"HourUTC": "t"}).set_index("t").sort_index().resample("1h").mean(numeric_only=True)
    p.loc[p.TotalLoad > 1.2 * p.TotalLoad.quantile(.999), "TotalLoad"] = np.nan
    d = r.join(p[EXC + ["TotalLoad"]], how="outer")
    for k, stem in NB.items():
        f = next((DATA/"entsoe/derived").glob(f"{stem}_*.parquet"))
        d[k] = pd.read_parquet(f).iloc[:, 0].resample("1h").mean().reindex(d.index)
    d["imp_net"] = d[EXC].sum(axis=1, min_count=1)
    d["headroom"] = sum(ic.cap("DK2", c)[0] - d[c] for c in EXC)
    return d.dropna(subset=["dk2_res"] + list(NB))


def main():
    d = load()
    for c in ["dk2_res"] + list(NB):
        d[c + "_p"] = pct_within_month_hour(d[c])
    d["dk2_raw_p"] = d.dk2_res.rank(pct=True)
    for k in NB:
        d[k + "_raw_p"] = d[k].rank(pct=True)

    rep = ["# 鄰國會不會在 DK2 最緊的時候同時緊?", "",
           f"樣本:{str(d.index.min())[:10]} → {str(d.index.max())[:10]},{len(d):,} 小時",
           "「緊」= 殘餘需求(負載 − 風 − 光)。DK2 用實測,鄰國(SE4 / DE_LU)用日前預測。",
           "⚠️ 口徑不一致:預測噪音會**稀釋**相關 → 看到的訊號是**保守的下界**。", ""]

    # ---- 1. 條件平均百分位 ----
    rows = []
    for lab, m in [("全部小時", slice(None)),
                   ("DK2 前 25%", d.dk2_res >= d.dk2_res.quantile(.75)),
                   ("DK2 前 10%", d.dk2_res >= d.dk2_res.quantile(.90)),
                   ("DK2 前 1%",  d.dk2_res >= d.dk2_res.quantile(.99)),
                   ("DK2 最緊 100h", d.index.isin(d.nlargest(100, "dk2_res").index))]:
        s = d[m] if not isinstance(m, slice) else d
        rows.append(dict(樣本=lab, 小時數=len(s),
                         SE4_生的百分位=s.SE4_raw_p.mean(), DE_生的百分位=s.DE_raw_p.mean(),
                         SE4_去季節後=s.SE4_p.mean(), DE_去季節後=s.DE_p.mean()))
    t1 = pd.DataFrame(rows)
    rep += ["## 1. DK2 越緊,鄰國排在自己分布的第幾位?", "",
            "(0.5 = 鄰國處在自己的中位數,也就是「沒有特別緊」)", "",
            t1.to_markdown(index=False, floatfmt=".3f"), ""]

    # ---- 2. 聯合尾端的 lift ----
    rows = []
    for q in [.90, .95, .99]:
        dk_hi = d.dk2_res >= d.dk2_res.quantile(q)
        dk_hi_ds = d.dk2_res_p >= q
        for k in NB:
            raw = (d[k + "_raw_p"] >= q)[dk_hi].mean()
            ds = (d[k + "_p"] >= q)[dk_hi_ds].mean()
            rows.append(dict(門檻=f"前 {(1-q)*100:.0f}%", 鄰國=k,
                             生的條件機率=raw, 生的lift=raw/(1-q),
                             去季節後條件機率=ds, 去季節後lift=ds/(1-q)))
    t2 = pd.DataFrame(rows)
    rep += ["## 2. 聯合尾端:DK2 在自己尾端時,鄰國也在自己尾端的機率", "",
            "lift = 條件機率 ÷ 無條件機率。**lift=1 代表完全獨立;lift>1 代表同時緊。**", "",
            t2.to_markdown(index=False, floatfmt=".3f"), ""]

    # ---- 3. 實際結果:那些小時的流量與餘裕 ----
    rows = []
    for lab, s in [("全部小時", d), ("DK2 最緊 10%", d[d.dk2_res >= d.dk2_res.quantile(.90)]),
                   ("DK2 最緊 100h", d.nlargest(100, "dk2_res"))]:
        rows.append(dict(樣本=lab, 小時數=len(s),
                         SE4流量=s.ExchangeNordicCountries.mean(),
                         DE流量=s.ExchangeContinent.mean(),
                         DK1流量=s.ExchangeGreatBelt.mean(),
                         淨進口=s.imp_net.mean(),
                         餘裕中位=s.headroom.median(), 餘裕p05=s.headroom.quantile(.05),
                         餘裕最小=s.headroom.min()))
    t3 = pd.DataFrame(rows)
    rep += ["## 3. 實際結果(正 = 進口進 DK2;餘裕以 ②a 為分母,是上界)", "",
            t3.to_markdown(index=False, floatfmt=".0f"), ""]

    # ---- 圖 ----
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    for i, (tag, suf) in enumerate([("生的(含季節)", "_raw_p"), ("去季節後(月×時內百分位)", "_p")]):
        xcol = "dk2_raw_p" if suf == "_raw_p" else "dk2_res_p"
        q = pd.qcut(d[xcol], 20, duplicates="drop")
        for k, col in [("SE4", "#4477aa"), ("DE", "#d62728")]:
            g = d.groupby(q, observed=True)[k + suf].mean()
            ax[i].plot([x.mid for x in g.index], g.values, "o-", ms=3, color=col, label=k)
        ax[i].axhline(.5, color="k", ls="--", lw=.8)
        ax[i].set_xlabel("DK2 殘餘需求百分位"); ax[i].set_ylabel("鄰國殘餘需求百分位")
        ax[i].set_title(tag); ax[i].legend(frameon=False, fontsize=8); ax[i].set_ylim(.2, .8)
    v = d.nlargest(1000, "dk2_res")
    ax[2].hist([v.SE4_p, v.DE_p], bins=20, label=["SE4", "DE"], color=["#4477aa", "#d62728"])
    ax[2].axvline(.5, color="k", ls="--", lw=.8)
    ax[2].set_title("DK2 最緊 1000 小時中,鄰國的去季節百分位分布")
    ax[2].set_xlabel("鄰國殘餘需求百分位(去季節)"); ax[2].set_ylabel("小時數")
    ax[2].legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(OUT/"07_neighbour_stress.png"); plt.close(fig)

    t1.to_csv(OUT/"neighbour_stress_percentiles.csv", index=False)
    t2.to_csv(OUT/"neighbour_stress_lift.csv", index=False)
    t3.to_csv(OUT/"neighbour_stress_flows.csv", index=False)
    (OUT/"NEIGHBOUR_STRESS.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
