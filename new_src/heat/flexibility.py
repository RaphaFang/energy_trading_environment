"""彈性的價值拆解 — 回答「這個 agent 到底靠什麼賺錢/省錢,各值多少?」

**先講清楚一件事(很重要)**:丹麥區域供熱受《熱供應法》規範,採**成本回收原則**
(hvile-i-sig-selv),熱不是利潤中心 —— 熱價必須等於成本。所以這個 agent
**不是在「賺套利利潤」,而是在「用最低成本履行供熱義務」**。

在模型裡這件事是自動成立的:熱需求外生且必須每小時滿足 → 熱收入是常數 → 從最佳化式
中消掉 → 剩下的目標就是「最小化淨供熱成本」,其中賣電是抵減、買電是支出。
所以唯一有意義的指標是 **€/MWh_th 的淨供熱成本**,不是「利潤」。

那「套利」在哪?在於**每小時選哪個熱源最便宜**,而這個排序會隨電價翻轉:
  1. 負電價/低電價 → 電鍋爐、熱泵吃電產熱(電價為負時等於「被付錢吃電」)
  2. 高電價        → CHP 多發電賣掉,熱是副產品;抽汽式還能少抽汽多發電
  3. 蓄熱槽        → 把「何時產熱」和「何時需要熱」脫鉤,才能等到價格對的時候才動
  4. 尖峰鍋爐      → 純燒燃料的後備,是其他選項的成本上限
本檔逐一關掉這些選項,看淨供熱成本上升多少 = 每個機制值多少錢。

用法:python new_src/heat/flexibility.py [年份]   (預設 2024)
"""

import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from chp import cop_from_temp, dea_plant, solve  # noqa: E402
from demand import heat_demand  # noqa: E402

# 代表性 DH 系統的規模:取 DK1 全區熱需求的 8%(≈一個中型丹麥城市)。
# ⚠️ 佔位值,與 demand.ANNUAL_TWH_DK1 一樣待能源署統計校準。
SYSTEM_SHARE = 0.08


def load_year(year: int, area: str = "DK1"):
    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, temperature_2m AS temp, "
        "ttf_gas_eur_mwh AS gas, api2_coal_eur_mwh AS coal, "
        "eua_co2_eur_t AS co2 FROM training "
        f"WHERE area='{area}' AND y_price_eur IS NOT NULL AND temperature_2m IS NOT NULL "
        f"AND timestamp_utc >= TIMESTAMP '{year}-01-01' "
        f"AND timestamp_utc < TIMESTAMP '{year + 1}-01-01' ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    ts = pd.to_datetime(d["timestamp_utc"], utc=True)  # duckdb 可能已帶時區
    hour = ts.dt.tz_convert("Europe/Copenhagen").dt.hour.to_numpy()
    q = heat_demand(d["temp"].to_numpy(), hour=hour) * SYSTEM_SHARE
    gas = d["gas"].ffill().bfill().to_numpy()
    coal = d["coal"].ffill().bfill().to_numpy()  # API2,2026-08-07 才進 duckdb
    # 真實 EUA 碳價(2026-08-06 接上,2026-08-07 換 ICAP 後全期覆蓋;先前寫死 70 €/t)
    co2 = d["co2"].ffill().bfill().to_numpy()
    # 明確傳該機組的 cop_ref:所有原型的熱泵都是目錄同一台(40 Comp. hp, airsource 10 MW),
    # 但**不要靠預設值** —— 2026-08-10 修掉的 bug 就是 cop_from_temp 預設 3.2 ≠ 目錄 2.8。
    cop = cop_from_temp(d["temp"].to_numpy(), cop_ref=dea_plant("gas_cc").cop_ref)
    return d, q, gas, coal, co2, cop


def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    d, q, gas, coal, co2, cop = load_year(year)
    p = d["price"].to_numpy()
    print(f"=== 彈性價值拆解 DK1 {year}(代表性 DH 系統,{len(d):,} 小時)===")
    print(
        f"  熱需求 均 {q.mean():.0f} / 尖峰 {q.max():.0f} MW_th,年熱量 {q.sum() / 1e6:.2f} TWh_th"
    )
    print(
        f"  電價 均 €{p.mean():.0f},負電價時數 {(p < 0).mean():.1%},"
        f"瓦斯 均 €{gas.mean():.0f}/MWh_fuel,**真實 EUA 碳價 均 €{co2.mean():.0f}/t**"
        f"(先前寫死 70)\n"
    )

    def variants_for(arch: str) -> dict:
        """同一台 DEA 目錄機組,逐一關掉彈性選項。**技術參數全是目錄真值**(2026-08-07)。"""
        return {
            "① 全部都有(基準)": dea_plant(arch),
            "② 拿掉蓄熱槽": dea_plant(arch, s_max=0.0, s_rate=0.0),
            "③ 拿掉電鍋爐": dea_plant(arch, eb_max=0.0),
            "④ 拿掉熱泵": dea_plant(arch, hp_max=0.0),
            "⑤ 拿掉全部 power-to-heat": dea_plant(arch, eb_max=0.0, hp_max=0.0),
            "⑥ 只剩 CHP + 尖峰鍋爐(零彈性)": dea_plant(
                arch, s_max=0.0, s_rate=0.0, eb_max=0.0, hp_max=0.0
            ),
        }

    # 燃料原型:同一套熱需求與電價,只換 CHP 的技術/燃料/排放因子。
    # **原型與燃料價必須配對**——先前生質欄用天然氣價當代理,跑出負的基準成本,
    # 那個水準不可用。現在只跑燃料價有真值的兩個;尖峰鍋爐一律燒氣(見 ARCHETYPES)。
    FUEL_OF = {"gas_cc": gas, "coal": coal}
    all_res = {}
    for arch, fp in FUEL_OF.items():
        all_res[arch] = {
            lab: solve(
                p, q, pl, fuel_price=fp, fuel_price_pb=gas, co2_price=co2, cop=cop
            )
            for lab, pl in variants_for(arch).items()
        }

    print(f"  {'情境':<34}" + "".join(f"{a:>12}" for a in all_res))
    for lab in variants_for("gas_cc"):
        row = "".join(
            f"€{all_res[a][lab]['heat_cost_per_mwh']:>11.2f}" for a in all_res
        )
        print(f"  {lab:<34}{row}")
    print(
        f"\n  {'→ 彈性總價值(⑥−①)':<34}"
        + "".join(
            f"€{all_res[a]['⑥ 只剩 CHP + 尖峰鍋爐(零彈性)']['heat_cost_per_mwh'] - all_res[a]['① 全部都有(基準)']['heat_cost_per_mwh']:>11.2f}"
            for a in all_res
        )
    )
    print(
        f"  {'→ P2H 價值(⑤−①)':<34}"
        + "".join(
            f"€{all_res[a]['⑤ 拿掉全部 power-to-heat']['heat_cost_per_mwh'] - all_res[a]['① 全部都有(基準)']['heat_cost_per_mwh']:>11.2f}"
            for a in all_res
        )
    )
    print(
        "\n  ← 兩欄的差距 = 燃料/碳假設對彈性估值的影響程度。"
        "\n  ⚠️ 生質(木片/顆粒)沒有燃料價來源,無法列入 —— 但它是 DK 熱電最大燃料。"
    )

    res = all_res["gas_cc"]  # 下面的細部行為沿用天然氣原型
    print("\n【以下細部行為 = 天然氣原型】")

    # 錢實際上從哪些小時來?
    r = res["① 全部都有(基準)"]
    neg, cheap, exp = (
        p < 0,
        (p >= 0) & (p < np.percentile(p, 25)),
        p > np.percentile(p, 75),
    )
    print("\n--- 各價格區間的行為(基準情境)---")
    print(f"  {'區間':<22}{'時數%':>7}{'CHP發電':>10}{'P2H買電':>10}{'蓄熱淨':>9}")
    for lab, msk in (("負電價", neg), ("低價(0~P25)", cheap), ("高價(>P75)", exp)):
        print(
            f"  {lab:<22}{msk.mean():>6.1%}{r['P'][msk].mean():>9.0f}"
            f"{r['p_buy'][msk].mean():>10.0f}{(r['ch'] - r['dis'])[msk].mean():>9.0f}"
        )
    # el_net = 賣電 − 買電 − 燃料  →  燃料 = 賣電 − 買電 − el_net
    rev, buy = (p * r["P"]).sum(), (p * r["p_buy"]).sum()
    fuel_cost = rev - buy - r["el_net"]
    print(
        f"\n  賣電收入 €{rev:,.0f}  −  買電支出 €{buy:,.0f}  −  燃料+CO2 €{fuel_cost:,.0f}"
        f"  =  €{r['el_net']:,.0f}"
    )
    print(f"  電力市場淨額 €{r['el_net']:,.0f}(負 = 供熱的淨成本,不是虧損)")

    # 冬夏對比:核心假說的第一個檢查
    mon = pd.to_datetime(d["timestamp_utc"]).dt.month.to_numpy()
    win, sm = np.isin(mon, [12, 1, 2]), np.isin(mon, [6, 7, 8])
    print("\n--- 冬 vs 夏:彈性在何時被熱義務吃掉?(核心假說)---")
    for lab, msk in (("冬(12-2月)", win), ("夏(6-8月)", sm)):
        # 「被綁住」的程度:CHP 出力的變異係數越低 = 越沒得選
        chp = r["P"][msk]
        room = 1 - (
            r["Qc"][msk].mean() / max(q[msk].mean(), 1e-9)
        )  # 熱需求中非 CHP 供應的比例
        print(
            f"  {lab:<12}熱需求 {q[msk].mean():>5.0f} MW_th   CHP發電 {chp.mean():>5.0f} MW_e"
            f"   蓄熱槽用量 {r['S'][msk].mean():>6.0f} MWh_th   非CHP供熱佔比 {room:>5.1%}"
        )


if __name__ == "__main__":
    main()
