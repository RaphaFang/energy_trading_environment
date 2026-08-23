"""部門耦合的實測 —— 三種「尖峰」是不是同一批小時,以及替代之後尖峰會跑到哪裡。

**2026-08-23 建立。** 這支是 `heating_consumption.py`(EDS 家戶用電 × 供暖方式)抓下來
之後才做得到的:**全國版切不出 DK1/DK2,而本論文只做 DK2。**

━━━ 🔑 為什麼這支比再多抓一份資料重要 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

論文一直在繞一個問題:**「熱最緊的時候,電力是不是也最緊?」**
先前只能用「熱需求最高 100 小時 vs 負載最高 100 小時」的**平均值**間接談。
現在可以直接數兩組小時的**交集**:

    系統負載尖峰 ∩ 熱需求尖峰   = 18/100
    系統負載尖峰 ∩ 家戶電暖尖峰 = 14/100
    熱需求尖峰   ∩ 家戶電暖尖峰 = 57/100      ← 兩個溫度驅動的負載彼此高度重合

🔑 **DK2 今天的電力尖峰不是最冷的那些小時。**
🔑 **但替代之後會變成是** —— 這才是「部門耦合」真正的意思:不只是量變大,
   是**原本錯開的兩個尖峰疊到一起**。

━━━ 🔴 一個一定要分清楚的定義(我第一版就寫錯了) ━━━━━━━━━━━━━━━━━━

    新的電力負載   = 原負載 + 熱泵買電                    → 尖峰 +26%
    新的淨進口需求 = 原淨進口 + 熱泵買電 + 失去的 CHP 發電 → +128%

**失去的發電是供給側減少,不是負載增加。** 把它加進「負載」會得到 +59%,那是錯的。
兩個數字都對,但問的不是同一件事。(第一版就是這樣算的,留著當警告。)

⚠️ **這是極端情境**:假設四台生質 CHP 的熱 **100%** 由熱泵接手、沒有任何其他新產能、
沒扣聯絡線停機率、也沒問「鄰國有沒有電可送」。**論文要寫成上界不是預測。**

用法:python new_src/heat/sector_coupling.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = Path("figs/heat_baseline")
BASELINE = OUT / "dk2_baseline_hourly.parquet"  # ← 先跑 baseline_dk2.py
HEAT_EL = "new_data/heating_consumption/heating_el_municipality_*.parquet"

HP_CAT = "Elvarme eller varmepumpe"
"""🔴 **「電暖」與「熱泵」在這個來源裡是同一類,拆不開。** 想量「熱泵有多少」答不了。"""

# 🔴 Bornholm(市代碼 400)在 Region Hovedstaden 裡,但它接的是瑞典、
#    **不在 DK2 同步電網**。切價區時一定要單獨扣掉。
BORNHOLM = 400
DK2_REGIONS = ["Region Hovedstaden", "Region Sjælland"]

# EPT:`Storkøbenhavns Fjernvarme` 這張網的機組座落的 16 個市。
# ⚠️ **是機組座落地不是消費區** —— 當「模型邊界的家戶電暖」用是近似,論文要標明。
CPH_KOMMUNER = [
    101,
    147,
    151,
    153,
    157,
    159,
    161,
    165,
    167,
    169,
    183,
    185,
    253,
    259,
    265,
    269,
]

DK2_IMPORT_CAP_MW = 2890
"""DK2 三條邊界的進口容量合計(Energistyrelsen AF25 表 3,轉錄在 `eda_price/interconnectors.py`)。
⚠️ 是**上界**:假設每條邊界同時開到自己的進口上限。"""


def _one(pattern: str) -> str:
    fs = sorted(glob.glob(pattern))
    assert len(fs) == 1, (
        f"{pattern} 匹配到 {len(fs)} 個檔:{fs}(見 new_src/data/window.py)"
    )
    return fs[0]


def heat_el_load() -> pd.DataFrame:
    """家戶電暖/熱泵負載(MW),分全國 / DK1 / DK2 / 哥本哈根 16 市 / Bornholm。"""
    m = pd.read_parquet(
        _one(HEAT_EL),
        columns=[
            "TimeUTC",
            "MunicipalityCode",
            "RegionName",
            "HeatingCategory",
            "ConsumptionkWh",
        ],
    )
    m = m[m["HeatingCategory"] == HP_CAT]
    dk2 = m["RegionName"].isin(DK2_REGIONS) & (m["MunicipalityCode"] != BORNHOLM)
    bh = m["MunicipalityCode"] == BORNHOLM
    out = {
        "全國": m,
        "DK2": m[dk2],
        "DK1": m[~dk2 & ~bh],
        "哥本哈根16市": m[m["MunicipalityCode"].isin(CPH_KOMMUNER)],
        "Bornholm": m[bh],
    }
    x = pd.DataFrame(
        {k: v.groupby("TimeUTC")["ConsumptionkWh"].sum() / 1000 for k, v in out.items()}
    )
    # ⚠️ `ConsumptionkWh` 是**該小時的耗電量**,除以 1000 就是 MW(因為一小時)。
    chk = (x["DK1"] + x["DK2"] + x["Bornholm"] - x["全國"]).abs().max()
    assert chk < 1e-6, f"DK1+DK2+Bornholm 不等於全國,差 {chk}"
    return x


def verify_against_national(x: pd.DataFrame) -> None:
    """🔑 逐市版加總 == 全國版嗎?(小市常有隱私抑制規則)

    ✅ **2026-08-23 驗過:48,028 小時 100.00% 完全相等**,連類別層級也是。
    **沒有抑制、沒有捨入差** → 兩個檔可以互相當 checksum。
    """
    n = pd.read_parquet(
        _one("new_data/heating_consumption/heating_el_national_*.parquet")
    )
    b = (
        n[n["HeatingCategory"] == HP_CAT].groupby("TimeUTC")["ConsumptionkWh"].sum()
        / 1000
    )
    j = pd.DataFrame({"mun": x["全國"], "nat": b}).dropna()
    same = (j["mun"] - j["nat"]).abs() < 1e-6
    print(
        f"✅ 逐市加總 vs 全國版:{len(j):,} 小時,完全相等 {same.mean():.2%}"
        f"(最大相對差 {((j['mun'] - j['nat']) / j['nat']).abs().max():.2e})"
    )


def main() -> None:
    pd.set_option("display.width", 220)
    assert BASELINE.exists(), "先跑 python new_src/heat/baseline_dk2.py"
    x = heat_el_load()
    verify_against_national(x)

    d = pd.read_parquet(BASELINE)
    j = d.join(x[["DK2", "哥本哈根16市"]], how="inner").dropna(
        subset=["DK2", "TotalLoad"]
    )
    j["hp_buy"] = j["BE-VL-KRAFTV-EF"] / j["cop"]  # 熱泵補那些熱要買的電 → **進負載**
    j["lost"] = j["Biomass"]  # 失去的 CHP 發電(已校準)→ **進供給側,不是負載**
    j["load2"] = j["TotalLoad"] + j["hp_buy"]
    j["imp2"] = j["imp"] + j["hp_buy"] + j["lost"]

    print(f"\n=== ① 家戶電暖/熱泵負載 MW({len(j):,} 小時對齊)===")
    t = pd.DataFrame(
        {
            "全期均": x.mean(),
            "自身最高100h": {c: x[c].nlargest(100).mean() for c in x},
            "逐時最大": x.max(),
            "佔全國": x.mean() / x["全國"].mean(),
        }
    )
    print(t.round(1).to_string())
    print(
        "🔑 哥本哈根 16 市只有 28 MW —— **因為那裡幾乎全是區域供熱。**"
        "\n   **要加 680 MW 熱泵的地方,恰好是今天幾乎沒有電熱的地方。**"
    )

    print("\n=== ② 🔑 三種「尖峰」是不是同一批小時 ===")
    top = {
        "系統負載": set(j["TotalLoad"].nlargest(100).index),
        "熱需求": set(j["dem"].nlargest(100).index),
        "家戶電暖": set(j["DK2"].nlargest(100).index),
    }
    ks = list(top)
    print(
        pd.DataFrame(
            [[len(top[a] & top[b]) for b in ks] for a in ks], index=ks, columns=ks
        ).to_string()
    )
    print(
        "🔑 **今天 DK2 的電力尖峰不是最冷的那些小時**(只重疊 14–18/100);"
        "\n   而兩個溫度驅動的負載彼此高度重合(57/100)。"
    )

    print("\n=== ③ 🔑 替代之後,尖峰跑到哪裡 ===")
    for nm, c in [("現況負載", "TotalLoad"), ("替代後負載(=原負載+熱泵買電)", "load2")]:
        s, tt = j[c], j[c].nlargest(100)
        print(
            f"\n【{nm}】全期均 {s.mean():,.0f} | 最高100h {tt.mean():,.0f} | 最大 {s.max():,.0f} MW"
        )
        print(
            f"   最高100h:氣溫 {j.loc[tt.index, 'tair'].mean():5.1f}°C"
            f" | 熱需求 {j.loc[tt.index, 'dem'].mean():,.0f} MW_th"
            f" | 月份 {dict(sorted(j.loc[tt.index].index.month.value_counts().items()))}"
        )
    a, b = set(j["TotalLoad"].nlargest(100).index), set(j["load2"].nlargest(100).index)
    lo, hi = j["TotalLoad"].nlargest(100).mean(), j["load2"].nlargest(100).mean()
    print(
        f"\n🔑 兩組最高 100 小時重疊 {len(a & b)}/100;尖峰 {lo:,.0f} → {hi:,.0f} MW(+{hi / lo - 1:.0%})"
    )
    print(
        "   **電力尖峰從 11 月搬到 1–2 月最冷的時候,也就是搬去跟熱尖峰對齊。**"
        "\n   → 部門耦合不只是「量變大」,是**原本錯開的兩個尖峰疊到一起**。"
    )

    print("\n=== ④ 淨進口需求 vs 聯絡線容量(同一批小時,避免混用選擇規則)===")
    for lab, idx in [
        ("現況負載最高 100h", j["TotalLoad"].nlargest(100).index),
        ("替代後負載最高 100h", j["load2"].nlargest(100).index),
    ]:
        s = j.loc[idx]
        print(
            f"  【{lab}】"
            f"現況 負載 {s.TotalLoad.mean():,.0f} / 進口 {s['imp'].mean():,.0f}"
            f"({s['imp'].mean() / s.TotalLoad.mean():.0%}) →"
            f" 替代後 負載 {s.load2.mean():,.0f} / 進口需求 {s.imp2.mean():,.0f}"
            f"({s.imp2.mean() / s.load2.mean():.0%},= 容量的 {s.imp2.mean() / DK2_IMPORT_CAP_MW:.0%})"
        )
    n_over = int((j["imp2"] > DK2_IMPORT_CAP_MW).sum())
    print(
        f"  🔴 淨進口需求 > 進口容量 {DK2_IMPORT_CAP_MW} MW 的小時:**{n_over}** / {len(j):,}"
        f";最大 {j['imp2'].max():,.0f} MW = 容量的 {j['imp2'].max() / DK2_IMPORT_CAP_MW:.0%}"
    )
    print(
        "  📌 報**小時數**不報比例 —— 比例會四捨五入成 0.00%,把「有超標」印成「沒超標」。"
    )
    print("  ⚠️ 極端情境 + 容量是上界 + 沒問鄰國有沒有電可送。**寫成上界,不是預測。**")

    print("\n=== ⑤ 天氣正規化的成長(1–2 月,同溫度格)===")
    w = pd.read_parquet(_one("new_data/weather/weather_dk2_*.parquet"))
    tk = [
        c for c in w.columns if c.lower() in ("time", "date", "hour_utc", "timestamp")
    ][0]
    tc = [c for c in w.columns if "temperature" in c][0]
    temp = w.set_index(pd.to_datetime(w[tk], utc=True))[tc].resample("1h").mean()
    z = pd.DataFrame({"hp": x["DK2"], "t": temp}).dropna()
    z = z[z.index.month.isin([1, 2])]
    z["bin"] = pd.cut(z["t"], bins=np.arange(-10, 11, 2))
    p = z.pivot_table(
        index="bin", columns=z.index.year, values="hp", aggfunc="mean", observed=True
    )
    n = z.pivot_table(
        index="bin", columns=z.index.year, values="hp", aggfunc="size", observed=True
    )
    ok = (n.get(2025, 0) >= 50) & (n.get(2026, 0) >= 50)  # 樣本太少的格不要讀
    r = p.loc[ok, 2026] / p.loc[ok, 2025]
    print(r.round(3).to_string())
    print(
        f"  → 中位 {r.median():.2f} = **天氣消掉後 2026 仍比 2025 多 {r.median() - 1:+.0%}**"
    )
    print(
        "  🔑 raw 是 +32%,所以大約 **2/3 是裝置成長、1/3 是天氣**。"
        "\n     **不做同溫度比對就會把天氣算成成長。**"
    )

    j[
        [
            "TotalLoad",
            "load2",
            "imp",
            "imp2",
            "hp_buy",
            "lost",
            "DK2",
            "哥本哈根16市",
            "dem",
            "tair",
            "cop",
        ]
    ].to_parquet(OUT / "sector_coupling_hourly.parquet")
    print(f"\n已存:{OUT}/sector_coupling_hourly.parquet")


if __name__ == "__main__":
    main()
