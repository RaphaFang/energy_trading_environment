"""2035 的情境層 —— 退場 × 熱泵完成度 α × 熱需求成長,以及每個 agent 的 Δ利潤。

**2026-08-25 建立。** 設計定案見 `THESIS_DIRECTION.md` §13;
排程引擎是 `joint_dispatch.py`(已通過對實測的驗證,生質三年 ±5%)。

━━━ 這一支在回答什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. 官方假設的退場(AMV1 2029、AVV1 2033)在 2035 造成多大的電力擺盪?
    2. 熱泵要蓋到多少(α)才不會把尖峰鍋爐逼出來?
    3. 每個業主在每個退場情境下賺多少 / 賠多少?  ← **投票層的輸入**

━━━ 🔑 「天氣年重放」是什麼意思 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**這不是預測 2035。** 是拿 2024 真實的氣溫、熱需求形狀、**以及日前電價**,
套到「2035 的機組組合與建築存量」上,問:**如果 2035 遇上 2024 那種年,會怎樣。**
→ 政策是唯一改變的東西,因果乾淨。
🔴 **電價不隨情境變** —— 這是刻意的(§13 不做市場出清)。
   理由:DK2 有 88.4% 的小時價格與至少一個鄰國完全相同,本地行為推不動它。
   ⚠️ **但這在「全歐洲都在電氣化」的 2035 是偏保守的假設,論文要寫明。**

━━━ 退場情境(全部錨在官方文件,不自己編) ━━━━━━━━━━━━━━━━━━━━━━

`plant_lifetimes.DK2_CHP`(KF25/KF26 表 5.4,Energistyrelsen 逐廠假設的最後運轉年):

    AMV1 2029 · AVV1 2033 · AVV2 2045 · AMV4 2049 · HCV8 2026

🔑 **一個先講的發現**:把官方年份**提前或延後 5 年,2035 的機組集合不會變**
(AVV2 2045−5=2040、AMV4 2049−5=2044,兩個都還在 2035 之後)。
→ **官方時程在 2035 這個時點是「黏」的**,所以情境軸改成用**政策強度**分層,
   而不是用 ±5 年的擾動。

⚠️ **署方自己註明這些年份「不代表業者的最終決定」** —— 引用要照抄這句免責。

━━━ 2035 的參數(逐項有出處) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

| 參數 | 值 | 出處 |
| --- | --- | --- |
| 木片(到廠) | 32.67 EUR/MWh_fuel | SØB25 Tabel 2 `an kraftværk`,2035 |
| 木顆粒(到廠) | 39.76 | 同上 |
| 天然氣能源稅 | **凍結在 2027 的 17.55** | GASAL 只立法到 2027;**外插會錯,見 §13 第 9 條** |
| θ_h 垃圾熱稅 | 掃 26.84 / 30.0 | `assumptions` 的公布值與代理上界 |
| 電價、碳價、氣價 | **重放 2024** | 天氣年重放的一部分 |

🔴 **兩個已知的低估**(方向都一致,論文要寫):
① **2025 起大幅調高的天然氣 CO2-afgift 沒進來** → 尖峰鍋爐偏便宜
② 電價重放 2024 → 沒有反映 2035 更高的電氣化需求

用法:python new_src/heat/scenarios.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assumptions as A  # noqa: E402
import joint_dispatch as J  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figs/scenarios"
WEATHER_YEAR = 2024
HP_PLAN_MW = 300.0  # HOFOR 公布的計畫規模

# ── 退場情境:按政策強度分層,每一層都指得到一份文件 ──────────────────
EXITS = {
    "S0 現況": (),
    "S1 官方 2035": ("AMV1", "AVV1"),  # KF26 表 5.4:2029 / 2033
    "S2 生質加速": ("AMV1", "AVV1", "AVV2"),  # AVV2 提前 10 年
    "S3 生質全退": ("AMV1", "AVV1", "AVV2", "AMV4", "KKV 8"),  # Klimarådet 的方向
}
WASTE_CUTS = {"垃圾不動": 1.0, "垃圾 −30%": 0.7}  # 2020 政治協議
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)  # 熱泵完成度
DEMANDS = {"低 +10%": 1.10, "中 +17%": 1.17, "高 +24%": 1.24}  # 見 demand_trend.py


def params_2035(theta_h: float | None = None) -> dict:
    """2035 的價格與稅費覆寫。**逐項可追到出處,見模組 docstring。**"""
    soeb = pd.read_csv(A.SOEB25_CSV)

    def p(param):
        v = soeb[(soeb.param == param) & (soeb.year == 2035)].value
        if not len(v):
            raise KeyError(f"SØB25 沒有 {param} 的 2035 值")
        return float(v.iloc[0]) * 3.6 / A.DKK_PER_EUR

    return {
        "wood_chips": p("fuel_price_traeflis_an_kraftvaerk"),
        "wood_pellets": p("fuel_price_traepiller_industri_an_kraftvaerk"),
        # 🔴 天然氣能源稅只立法到 2027 → **凍結**,不外插(2024→2025 有結構斷點)
        "gas_tax": A.gas_energy_tax_eur_mwh(2027),
        "theta_h": theta_h if theta_h is not None else A.THETA_HEAT_WASTE,
    }


def one(exit_key: str, alpha: float, dem_key: str, waste_key: str, over: dict) -> dict:
    """跑一格,回這一格的摘要。"""
    res, profit = J.run(
        WEATHER_YEAR,
        drop=EXITS[exit_key],
        hp_mw=HP_PLAN_MW * alpha if alpha > 0 else 50.3,
        dem_scale=DEMANDS[dem_key],
        waste_scale=WASTE_CUTS[waste_key],
        over=over,
    )
    cold = res["dem"].nlargest(100).index  # 最冷的 100 小時
    u = res["未供應"]
    gap_h = int((u > 0.01).sum())
    # 🔴 **只要有任何一小時供不上,整格的 λ 與利潤都不可用。**
    #    不是只有缺口那幾小時壞掉 —— 蓄熱會把稀缺往前傳,缺口**之前**的小時
    #    λ_heat 也會被推向 VOLL(那在經濟上是對的:現在多一單位熱 = 之後多一單位缺口)。
    #    → 部分清洗救不回來,只能整格標成不可評估。
    ev = gap_h == 0
    nan = float("nan")
    return {
        "退場": exit_key,
        "α": alpha,
        "熱需求": dem_key,
        "垃圾": waste_key,
        "尖峰鍋爐_%": float(res["尖峰鍋爐"].sum() / res["dem"].sum() * 100),
        "可評估": ev,
        "缺口_小時": gap_h,
        "缺口_GWh": float(u.sum() / 1000),
        "缺口_最大MW": float(u.max()),
        "λ_年均": float(res["lambda_heat"].mean()) if ev else nan,
        "λ_最冷100h": float(res.loc[cold, "lambda_heat"].mean()) if ev else nan,
        "CHP發電_GWh": float(res["p_chp"].sum() / 1000),
        "P2H買電_GWh": float(res["p_buy"].sum() / 1000),
        "淨部位_最冷100h_MW": float(res.loc[cold, "p_net"].mean()),
        "_res": res,
        "_profit": profit,
    }


def run_grid(theta_h: float | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """跑整個網格。回 (每格摘要, 每格每 agent 的利潤)。"""
    over = params_2035(theta_h)
    rows, profits = [], []
    ref = None
    for wk in WASTE_CUTS:
        for dk in DEMANDS:
            for ek in EXITS:
                for a in ALPHAS:
                    r = one(ek, a, dk, wk, over)
                    res, pf = r.pop("_res"), r.pop("_profit")
                    if ek == "S0 現況" and a == ALPHAS[0]:
                        ref = r  # 同一格 (需求, 垃圾) 下的不退場基準
                    r["淨擺盪_vs_S0_MW"] = (
                        ref["淨部位_最冷100h_MW"] - r["淨部位_最冷100h_MW"]
                        if ref
                        else 0.0
                    )
                    rows.append(r)
                    for ag, v in pf.iterrows():
                        if not r["可評估"]:
                            continue          # 有缺口 → 利潤不可比,不收
                        profits.append(
                            {
                                "退場": ek,
                                "α": a,
                                "熱需求": dk,
                                "垃圾": wk,
                                "agent": ag,
                                "利潤_MEUR": v["利潤_MEUR"],
                            }
                        )
    return pd.DataFrame(rows), pd.DataFrame(profits)


def main() -> None:
    print(f"\n{'=' * 84}\n2035 情境層 —— 天氣年重放 {WEATHER_YEAR}\n{'=' * 84}")
    over = params_2035()
    print("\n2035 參數:")
    for k, v in over.items():
        print(f"  {k:16s} {v:8.2f}")
    print(
        f"\n網格:{len(EXITS)} 退場 × {len(ALPHAS)} α × {len(DEMANDS)} 熱需求 "
        f"× {len(WASTE_CUTS)} 垃圾 = "
        f"{len(EXITS) * len(ALPHAS) * len(DEMANDS) * len(WASTE_CUTS)} 格"
    )

    grid, prof = run_grid()
    OUT.mkdir(parents=True, exist_ok=True)
    grid.to_csv(OUT / "grid_2035.csv", index=False)
    prof.to_csv(OUT / "agent_profit_2035.csv", index=False)

    mid = grid[(grid.熱需求 == "中 +17%") & (grid.垃圾 == "垃圾不動")]
    print(f"\n{'-' * 84}\n中位情境(熱需求 +17%、垃圾不動)\n{'-' * 84}")
    show = [
        "退場",
        "α",
        "缺口_小時",
        "缺口_最大MW",
        "尖峰鍋爐_%",
        "λ_最冷100h",
        "CHP發電_GWh",
        "P2H買電_GWh",
        "淨部位_最冷100h_MW",
        "淨擺盪_vs_S0_MW",
    ]
    print(mid[show].to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

    print(
        f"\n{'-' * 84}\n🔑 熱泵要蓋多少才不把尖峰鍋爐逼出來(尖峰鍋爐佔比 %)\n{'-' * 84}"
    )
    piv = mid.pivot(index="退場", columns="α", values="尖峰鍋爐_%")
    print(piv.round(2).to_string())
    print(f"  📌 對照:2024 實測的尖峰鍋爐佔比是 5.1%")

    print(
        f"\n{'-' * 84}\n🔑 逐 agent 利潤(中位情境、α=1.0),以及相對 S0 的變化\n{'-' * 84}"
    )
    pm = prof[(prof.熱需求 == "中 +17%") & (prof.垃圾 == "垃圾不動") & (prof.α == 1.0)]
    t = pm.pivot(index="agent", columns="退場", values="利潤_MEUR")
    for c in [c for c in t.columns if c != "S0 現況"]:
        t[f"Δ {c}"] = t[c] - t["S0 現況"]
    print(t.round(1).to_string())
    print("\n  🔴 Δ利潤是投票層的輸入。**但有熱缺口的情境不能拿來投票** ——")
    print("     那些情境根本滿足不了需求,利潤只算了「供得上的那些小時」,不可比。")
    gap = mid.set_index(["退場", "α"])["缺口_小時"]
    print(f"     中位情境有缺口的格子:{int((gap > 0).sum())}/{len(gap)}")
    print(f"\n  寫出 {OUT}/grid_2035.csv 與 agent_profit_2035.csv")


if __name__ == "__main__":
    main()
