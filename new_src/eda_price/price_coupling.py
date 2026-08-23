"""DK1/DK2 的價格是不是外部決定的 —— **直接測量**,不是用「電纜滿載」推論。

市場耦合的規則:只要兩區之間沒塞滿,日前價格就會**完全相等**(同一個數字)。
→ 「價格一模一樣的小時佔幾成」是測量。先前用的「三條線同時滿載」是間接代理,
   而且已經證明太寬鬆(它給 99%+ 綁定,直接測 DK1↔DK2 只有 66%)。

⚠️ 一個口徑問題:DK1/DK2 的 EUR 價來自 Energinet(由 DKK 換算),
   鄰國來自 ENTSO-E(原生 EUR)→ 可能有換算/進位的微小差異。
   所以主指標用**容差 0.01 EUR/MWh**,並附上不同容差的敏感度。
"""
from __future__ import annotations
import glob
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "price_formation"
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.dpi": 140, "font.size": 9, "axes.grid": True, "grid.alpha": .25,
                     "axes.spines.top": False, "axes.spines.right": False})

TOL = 0.01                                  # 主容差 EUR/MWh
NB = {"DK2": ["SE4", "DE", "DK1"],          # DK2 的三個鄰居
      "DK1": ["SE3", "NO2", "DE", "DK2"]}   # DK1 的四個(英國無 ENTSO-E 拉,見下)


def load() -> pd.DataFrame:
    d = {}
    for z in ("dk1", "dk2"):
        f = glob.glob(str(DATA/f"price/price_{z}_*.parquet"))[0]
        d[z.upper()] = pd.read_parquet(f).set_index("HourUTC")["SpotPriceEUR"]
    for z, lab in [("se_3", "SE3"), ("se_4", "SE4"), ("de_lu", "DE"), ("no_2", "NO2")]:
        f = glob.glob(str(DATA/f"entsoe/price_{z}_*.parquet"))[0]
        d[lab] = pd.read_parquet(f).iloc[:, 0]
    p = pd.DataFrame(d).resample("1h").mean()
    r = pd.read_parquet(glob.glob(str(DATA/"residual/residual_dk2_*.parquet"))[0])
    p["dk2_res"] = r.set_index("hour_utc")["residual_mwh"].resample("1h").mean()
    return p.dropna(subset=["DK1", "DK2", "SE3", "SE4", "DE", "NO2"])


def main():
    p = load()
    rep = ["# DK1/DK2 的價格與鄰國一致嗎 —— 直接測量", "",
           f"樣本 {str(p.index.min())[:10]} → {str(p.index.max())[:10]},**{len(p):,} 小時**",
           f"「一致」= 兩區日前價差 ≤ **{TOL} EUR/MWh**。", ""]

    # --- 容差敏感度 ---
    rows = []
    for tol in [0.0, 0.01, 0.05, 0.5, 1.0]:
        r = dict(容差=tol)
        for z in ("DK1", "DK2"):
            for n in NB[z]:
                r[f"{z}={n}"] = ((p[z] - p[n]).abs() <= tol).mean()
        rows.append(r)
    t0 = pd.DataFrame(rows)
    rep += ["## 0. 容差敏感度(確認不是換算誤差造成的)", "",
            t0.to_markdown(index=False, floatfmt=".3f"), ""]

    # --- 逐對 + 至少一個 + 一個都沒有 ---
    for z in ("DK1", "DK2"):
        eq = pd.DataFrame({n: (p[z] - p[n]).abs() <= TOL for n in NB[z]})
        p[f"{z}_n_eq"] = eq.sum(axis=1)
        p[f"{z}_any"] = eq.any(axis=1)
        rows = [dict(對象=n, 一致的小時比例=eq[n].mean()) for n in NB[z]]
        rows.append(dict(對象="**至少一個鄰居**", 一致的小時比例=eq.any(axis=1).mean()))
        rows.append(dict(對象="🔴 **一個都不一致(真正的隔離)**", 一致的小時比例=(~eq.any(axis=1)).mean()))
        rep += [f"## 1. {z} 與各鄰居的價格一致率", "",
                pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), ""]
        if z == "DK1":
            rep += ["⚠️ DK1 還有英國(Viking Link,2023-12 起),ENTSO-E 的 GB 價未抓 → "
                    "DK1 的「隔離」是**上界**(可能其實與英國一致)。", ""]

    # --- 逐年 ---
    yr = p.groupby(p.index.year).agg(
        DK2_至少一個=("DK2_any", "mean"), DK1_至少一個=("DK1_any", "mean"),
        DK2_對SE4=("SE4", lambda s: 0)).drop(columns="DK2_對SE4")
    for z in ("DK1", "DK2"):
        for n in NB[z]:
            yr[f"{z}={n}"] = ((p[z] - p[n]).abs() <= TOL).groupby(p.index.year).mean()
    rep += ["## 2. 逐年(北歐 flow-based 市場耦合 2024-10 上線)", "",
            yr.to_markdown(floatfmt=".3f"), ""]

    # --- 緊的時候會不會斷開 ---
    q = pd.qcut(p.dk2_res.dropna(), 10, labels=False, duplicates="drop")
    g = p.loc[q.index].groupby(q).agg(DK2_至少一個=("DK2_any", "mean"),
                                      DK2_對SE4=("DK2", "size"))
    for n in NB["DK2"]:
        g[f"DK2={n}"] = ((p[z] * 0 + (p["DK2"] - p[n]).abs() <= TOL)).loc[q.index].groupby(q).mean()
    g = g.drop(columns="DK2_對SE4")
    g.index = [f"第 {i+1} 十分位" for i in g.index]
    rep += ["## 3. 🔑 DK2 越吃緊,價格還跟鄰國綁著嗎?(依 DK2 殘餘需求分十等分)", "",
            g.to_markdown(floatfmt=".3f"), "",
            "第 10 十分位 = DK2 殘餘需求最高的那 10% 小時 —— **適足性真正在問的那些小時。**", ""]

    # --- 圖 ---
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    for z, c in [("DK2", "#d62728"), ("DK1", "#1f77b4")]:
        s = p.groupby(p.index.year)[f"{z}_any"].mean()
        ax[0].plot(s.index, s.values * 100, "o-", color=c, label=z)
    ax[0].set_title("與「至少一個鄰居」價格一致的比例"); ax[0].set_xlabel("年")
    ax[0].set_ylabel("%"); ax[0].legend(frameon=False); ax[0].set_ylim(0, 100)
    for n, c in [("SE4", "#4477aa"), ("DE", "#d62728"), ("DK1", "#44aa77")]:
        s = ((p["DK2"] - p[n]).abs() <= TOL).groupby(p.index.year).mean()
        ax[1].plot(s.index, s.values * 100, "o-", color=c, label=f"DK2 = {n}")
    ax[1].set_title("DK2 逐對一致率"); ax[1].set_xlabel("年"); ax[1].set_ylabel("%")
    ax[1].legend(frameon=False, fontsize=8); ax[1].set_ylim(0, 100)
    gg = p.loc[q.index].groupby(q)["DK2_any"].mean() * 100
    ax[2].bar(range(1, len(gg) + 1), gg.values, color="#d62728")
    ax[2].set_title("DK2 越吃緊,還跟鄰國綁著嗎"); ax[2].set_xlabel("DK2 殘餘需求十分位(10=最緊)")
    ax[2].set_ylabel("與至少一個鄰居一致 %"); ax[2].set_ylim(0, 100)
    fig.tight_layout(); fig.savefig(OUT/"08_price_coupling.png"); plt.close(fig)

    t0.to_csv(OUT/"coupling_tolerance.csv", index=False)
    yr.to_csv(OUT/"coupling_by_year.csv")
    g.to_csv(OUT/"coupling_by_tightness.csv")
    (OUT/"PRICE_COUPLING.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
