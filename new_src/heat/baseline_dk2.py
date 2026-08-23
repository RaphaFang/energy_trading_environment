"""`THESIS_DIRECTION.md` §5.1–5.3 的可重現版本 —— DK2 的電力/供熱現況與三面向衝擊。

**2026-08-22 建立。** 在這之前 §5 的數字是臨時腳本算的、沒進 repo,
結果就是 §5.4 的 `25.97` 現在**重現不出來**(`README.md` §⑨ 對 ARC 的老抱怨,又發生一次)。
`new_data/` 與 `figs/` 都 gitignored → **腳本是唯一的可重建憑證。**

━━━ 🔴 這支腳本存在的三個理由(= 舊數字錯在哪) ━━━━━━━━━━━━━━━━━━━━━

1. **燃料水準要校準。** `ElectricityBalanceNonv` 的燃料標籤是錯的 —— 見
   `fuel_calibration.py`。**Waste 低估 1.34–2.23×、Biomass 低估 1.34–1.43×、
   煤在 DK2 是幽靈欄。** 舊 §5.1 直接用原值。
2. 🔴 **年佔比不能套到尖峰。** 垃圾是 must-run,尖峰倍數只有 **0.87×**
   (熱需求本身是 2.6×)→ 年佔 27.4% 在尖峰只剩 **9.6%**。
   舊 §5.3 用 `27.7% × 2,556 × 30% = 212 MW_th`,而那個值**已經超過 DK2 垃圾的熱容量**。
   📌 **每個推導出來的量都要拿容量當上界檢查一次。**
3. 🔴 **「電力擺盪」必須兩側都算。** 舊 §5.3 的垃圾兩列只算「失去 CHP 發電」,
   生質那列卻算了兩側 → **一張表兩種口徑**。正確的是
   `擺盪 = 失去的發電 + 熱泵為了補那些熱要買的電`。

⚠️ **「尖峰」有兩個定義,而且不同時發生**:熱需求最高的 100 小時,電力負載反而**低 200 MW**
(那些是最冷的日子,不是電力最緊的日子)。**兩個都要報。**

用法:python new_src/heat/baseline_dk2.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chp  # noqa: E402
import fuel_calibration as FC  # noqa: E402

OUT = Path("figs/heat_baseline")
YEARS = range(2021, 2026)  # varmelast 從 2021-01 才有;2026 的 Energinet 已停發

# 這幾欄在丹麥幾乎都是熱電共生;風光不是。**煤與油刻意不列** —— DK2 是幽靈欄(見理由 1)。
GEN = [
    "Biomass",
    "Waste",
    "FossilGas",
    "SolarPower",
    "OnshoreWindPower",
    "OffshoreWindPower",
]
# 🔴 幽靈欄:EPT 說 DK2 2024/2025 的煤投入是 0 TJ,Energinet 卻每年報 92–141 MW。
#    **不列進 `GEN`**(不能當本地發電),但要留著 —— 它吸走的出力很可能就是生質,
#    所以 `Biomass + 煤 + 油` 是「真實生質出力」的第二條獨立重建(見 §5.3)。
GHOST = ["FossilHardCoal", "FossilOil"]
EXC = ["ExchangeContinent", "ExchangeGreatBelt", "ExchangeNordicCountries"]
CALIBRATED = ["Biomass", "Waste"]

# varmelast 的分項產熱。`BE-VL-TOTAL-FAK` 是 CO2 排放強度(Kg/GJ),**絕不能加進來**。
SRC = {
    "BE-VL-KRAFTV-EF": "熱電",
    "BE-VL-AFFALD-EF": "垃圾焚化",
    "BE-VL-SPIDS-GAS-EF": "尖峰氣",
    "BE-VL-SPIDS-OLIE-EF": "尖峰油",
    "BE-VL-IO-EF": "工業餘熱",
    "BE-VL-EVO-EF": "電鍋爐",
    "BE-VL-VP-EF": "熱泵",
    "BE-VL-BIO-EF": "生質尖峰",
    "BE-VL-BG-EF": "生質氣",
    "BE-VL-SOL-EF": "太陽能",
    "BE-VL-OD-EF": "資料中心",
}


def _one(pattern: str) -> str:
    """glob 之後**強制唯一** —— 檔名帶抓取窗口,寫死會掛、取 `[0]` 會靜默拿到舊檔。"""
    fs = sorted(glob.glob(pattern))
    assert len(fs) == 1, (
        f"{pattern} 匹配到 {len(fs)} 個檔:{fs}(見 new_src/data/window.py)"
    )
    return fs[0]


def load() -> pd.DataFrame:
    """電(Energinet,已校準)+ 熱(varmelast)+ 氣溫,逐時對齊。"""
    p = pd.read_parquet(_one("new_data/production/production_dk2_*.parquet"))
    p = p.set_index(pd.to_datetime(p["HourUTC"], utc=True)).sort_index()
    # 🔴 先 resample:2025-10 起是 15 分鐘制,不做會讓「最高 100 小時」偏向 15 分鐘尖峰
    p = p[GEN + GHOST + EXC + ["TotalLoad"]].resample("1h").mean()
    # 🔴 TotalLoad 有極端壞值(DK2:6,385 / 5,968 / 4,205 / 3,273 MW)。
    #    「3×中位數」太鬆(會放過 4,205 與 3,273)→ 用 1.2×99.9 分位。
    bad = p.TotalLoad > 1.2 * p.TotalLoad.quantile(0.999)
    # ⚠️ 不要用 `DataFrame.attrs` 帶這個 —— join 之後就掉了(我第一版就是這樣印出 None)
    print(f"📌 剔除的 TotalLoad 壞值:{sorted(p.loc[bad, 'TotalLoad'].round().tolist(), reverse=True)}")
    p.loc[bad, "TotalLoad"] = np.nan

    for c in CALIBRATED:
        p[c + "_raw"] = p[c]
        p[c] = FC.calibrate(p[c], "DK2", c)
    p["imp"] = p[EXC].sum(axis=1)
    p["local"] = p[GEN].sum(axis=1)
    p["bio_ghost"] = p["Biomass_raw"] + p[GHOST].sum(axis=1)  # 第二條重建

    v = pd.read_parquet(_one("new_data/heat/varmelast_*.parquet"))
    v = v.set_index(pd.to_datetime(v["timestamp"], utc=True)).sort_index()
    v = v[list(SRC) + ["BE-EO-CTR-EFF", "DAP-VEKS-FORBRUG-EFF"]].resample("1h").mean()
    v["dem"] = v["BE-EO-CTR-EFF"] + v["DAP-VEKS-FORBRUG-EFF"]

    w = pd.read_parquet(_one("new_data/weather/weather_dk2_*.parquet"))
    tk = [
        c for c in w.columns if c.lower() in ("time", "date", "hour_utc", "timestamp")
    ][0]
    tc = [c for c in w.columns if "temperature" in c][0]
    temp = (
        w.set_index(pd.to_datetime(w[tk], utc=True))[tc]
        .resample("1h")
        .mean()
        .rename("tair")
    )

    d = p.join(v, how="inner").join(temp, how="left")
    d = d[d.index.year.isin(YEARS)].dropna(subset=["TotalLoad", "dem"])
    d["cop"] = chp.cop_from_temp(d["tair"].to_numpy())
    return d


def s51(d: pd.DataFrame) -> None:
    print("=" * 92)
    print(
        f"§5.1 DK2 電力現況({d.index.year.min()}–{d.index.year.max()},{len(d):,} 小時)"
    )
    print("=" * 92)
    for lab, x in [("全年", d), ("負載最高 100 小時", d.nlargest(100, "TotalLoad"))]:
        L, loc = x.TotalLoad.mean(), x.local.mean()
        print(
            f"\n【{lab}】負載 {L:,.0f} MW | 淨進口 {x.imp.mean():,.0f} ({x.imp.mean() / L:.1%})"
            f" | 本地發電 {loc:,.0f} ({loc / L:.1%})"
        )
        for c in GEN:
            star = " ←校準" if c in CALIBRATED else ""
            print(
                f"   {c:18} {x[c].mean():7.1f} MW  佔本地 {x[c].mean() / loc:6.1%}"
                f"  佔負載 {x[c].mean() / L:6.1%}{star}"
            )
        print(
            f"   生質÷垃圾:原值 {x.Biomass_raw.mean() / x.Waste_raw.mean():.1f}×"
            f" | **校準後 {x.Biomass.mean() / x.Waste.mean():.1f}×**"
        )
    print(
        "\n⚠️ 「尖峰靠進口 X%」對**窗口**很敏感 —— 這裡是 2021–2025;"
        "\n   `price_formation.py` 用 2019→2026-01 得到 34.7%(前 100 名有 16 小時在 2026-01)。"
        "\n   **兩個都對,引用時一定要帶窗口。**"
    )


def s52(d: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 92)
    print("§5.2 DK2 供熱現況 —— 🔴 年佔比 vs 尖峰佔比(舊 §5.3 就是混用這兩個)")
    print("=" * 92)
    top = d.nlargest(100, "dem")
    py, pp = d[list(SRC)].sum(axis=1), top[list(SRC)].sum(axis=1)
    r = pd.DataFrame(
        [
            dict(
                來源=n,
                年均MW=d[c].mean(),
                年佔生產=d[c].mean() / py.mean(),
                尖峰MW=top[c].mean(),
                尖峰佔生產=top[c].mean() / pp.mean(),
                尖峰倍數=top[c].mean() / max(d[c].mean(), 1e-9),
            )
            for c, n in SRC.items()
        ]
    ).sort_values("年均MW", ascending=False)
    print(
        f"熱需求:年均 {d.dem.mean():,.0f} MW_th、最高 100 小時 {top.dem.mean():,.0f} MW_th"
        f"(= {top.dem.mean() / d.dem.mean():.1f}×)"
    )
    print(r.round(3).to_string(index=False))
    print(
        "🔑 **垃圾在最冷時不但沒變多,還略微變少(0.87×)** —— must-run。"
        "真正扛尖峰的是熱電與尖峰氣鍋爐。"
    )
    return top


def s53(d: pd.DataFrame) -> None:
    print("\n" + "=" * 92)
    print("§5.3 三面向衝擊 —— **一律兩側:失去的發電 + 熱泵新增買電**")
    print("=" * 92)
    # 垃圾的實測 Cb(淨交付/熱交付,EPT 2024 的 DK2 垃圾廠合計)
    e = pd.read_parquet(FC.EPT)
    e = e[
        (e["aar"] == 2024) & (e["vaerk_postnr"] < 5000) & (e["affald_TJ"].fillna(0) > 0)
    ]
    cb = e["ellev_TJ"].sum() / e["varmelev_TJ"].sum()
    argo = e[e["selskab_navn"].str.contains("ARGO", na=False)]
    tj = 1000 / 3.6 / 8784
    argo_th, argo_el = argo["varmelev_TJ"].sum() * tj, argo["ellev_TJ"].sum() * tj

    for lab, x in [
        ("熱需求最高 100 小時", d.nlargest(100, "dem")),
        ("負載最高 100 小時", d.nlargest(100, "TotalLoad")),
    ]:
        L, cop = x.TotalLoad.mean(), x.cop.mean()
        aff, kv = x["BE-VL-AFFALD-EF"], x["BE-VL-KRAFTV-EF"]
        print(
            f"\n【{lab}】負載 {L:,.0f} MW,氣溫 {x.tair.mean():.1f}°C,COP {cop:.2f},"
            f"熱需求 {x.dem.mean():,.0f} MW_th"
        )
        rows = []
        for nm, q_th, lost in [
            ("ARGO 一座關(死亡名單)", pd.Series(argo_th, index=x.index), argo_el),
            ("全垃圾 −30%", 0.30 * aff, (0.30 * aff).mean() * cb),
            # 生質:兩條獨立重建。① Energinet 原值 ×EPT 因子 ② Biomass+煤+油 合併
            #      (既然煤在 DK2 是幽靈欄,它吸走的很可能就是生質)
            ("生質 CHP 全換熱泵(×EPT 校準)", kv, x.Biomass.mean()),
            ("生質 CHP 全換熱泵(煤油合併重建)", kv, x.bio_ghost.mean()),
        ]:
            add = (q_th / x.cop).mean()
            rows.append(
                dict(
                    情境=nm,
                    熱缺口MW_th=q_th.mean(),
                    佔尖峰熱=q_th.mean() / x.dem.mean(),
                    失去發電MW=lost,
                    熱泵買電MW=add,
                    淨擺盪MW=lost + add,
                    佔尖峰負載=(lost + add) / L,
                )
            )
        t = pd.DataFrame(rows)
        print(t.round(3).to_string(index=False))
        lo, hi = t.iloc[2]["淨擺盪MW"], t.iloc[3]["淨擺盪MW"]
        print(f"   → **生質那一列的區間:{min(lo, hi):,.0f}–{max(lo, hi):,.0f} MW"
              f" = {min(lo, hi) / L:.0%}–{max(lo, hi) / L:.0%} 尖峰負載**"
              f"  (Energinet 原值只會給 {x.Biomass_raw.mean() + (kv / x.cop).mean():,.0f} MW,那是低估的)")
        print(
            f"   📌 垃圾的實測 Cb(淨/熱)= {cb:.3f};"
            f"生質在這些小時的實現電熱比 = {x.Biomass.mean() / kv.mean():.3f}"
            f"(年均 {d.Biomass.mean() / d['BE-VL-KRAFTV-EF'].mean():.3f})"
        )
    print(
        "\n🔴 **銘牌不能當尖峰出力**:AMV1+AMV4+AVV1+AVV2 登記電容量合計 1,020 MW_e,"
        "\n   但抽汽機組在最大熱出力時會壓低發電 —— 重建值應低於它。**這是一個要跑的檢查。**"
    )


def main() -> None:
    pd.set_option("display.width", 240)
    OUT.mkdir(parents=True, exist_ok=True)
    d = load()
    s51(d)
    s52(d)
    s53(d)
    d.to_parquet(OUT / "dk2_baseline_hourly.parquet")
    print(f"\n已存:{OUT}/dk2_baseline_hourly.parquet(逐時,含校準後的 Biomass/Waste)")


if __name__ == "__main__":
    main()
