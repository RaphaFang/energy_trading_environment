"""CHP + 區域供熱系統的排程 LP — 熱側 agent 的地基(對應電池線的 v1_single.perfect)。

一個 DH 業者:熱電共生機組(CHP)+ 蓄熱槽 + 電鍋爐 + 熱泵 + 尖峰鍋爐。
**熱需求必須每小時滿足**(義務,無彈性);電價是外生訊號;業者選怎麼配置。

為什麼是 LP:抽汽式 CHP 的可行域是**多邊形**(背壓線 + 容量線),蓄熱槽是線性動態,
所以整個問題是線性的。機組啟停(最小負載、啟動成本)才需要整數 —— **第一版刻意不做**,
先把「熱約束 × 電價」的經濟學跑出來。

決策(每小時):
  P_chp  CHP 發電 (MW_e)        Q_chp  CHP 產熱 (MW_th)
  Q_eb   電鍋爐產熱 (MW_th)      Q_hp   熱泵產熱 (MW_th)      ← 這兩個是 power-to-heat,吃電
  Q_pb   尖峰鍋爐產熱 (MW_th)    ch/dis 蓄熱槽充/放 (MW_th)   S 蓄熱量 (MWh_th)

技術關係(見 Technology Catalogue):
  燃料 F = (P_chp + Cv·Q_chp) / η_el      抽汽式:多產 1 MW_th 熱要少發 Cv MW_e 電
  背壓線 P_chp ≥ Cb·Q_chp                  給定熱量下的最低發電量
  容量線 P_chp + Cv·Q_chp ≤ P_max          等效凝汽容量
  電鍋爐 Q_eb = η_eb·買電                  熱泵 Q_hp = COP·買電(COP 隨氣溫變,見下)

**核心經濟學**:CHP 的電力邊際成本不是燃料成本,而是「燃料成本 − 熱的機會價值」。
熱反正要產,若不用 CHP 產就得用鍋爐燒錢 → CHP 發電的增量成本可能很低甚至為負。
蓄熱槽讓業者選**何時**產熱 → 等於把電力供給曲線在時間上搬移。
電價為負時,電鍋爐/熱泵反過來吃電產熱 → 這是 power-to-heat 吸收負電價的機制。

⚠️ **參數是量級佔位值,不是查證數字**(見 DEFAULT 的註解)。投論文前必須換成
丹麥能源署 Technology Catalogue("Technology Data for Generation of Electricity and
District Heating")的實際值。

用法:python new_src/heat/chp.py    (self-check + 真實 DK1 電價的示範排程)
"""

import os
import sys
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

sys.path.insert(0, os.path.dirname(__file__))


@dataclass
class Plant:
    """一個 DH 系統的技術與成本參數。

    ⚠️ 全部是**量級佔位值**,待 Technology Catalogue 校準。標 [TC] 的是該文件有的欄位。
    """

    p_max: float = 400.0  # [TC] CHP 等效凝汽容量 MW_e
    cb: float = 0.75  # [TC] 背壓係數(功熱比下界),大型丹麥 CHP 約 0.5–1.0
    cv: float = 0.15  # [TC] 抽汽損失係數:每產 1MW_th 熱少發 0.15MW_e 電
    eta_el: float = 0.45  # [TC] 凝汽模式發電效率
    # 排放因子 tCO2/MWh_fuel,**熱電機組與尖峰鍋爐分開設**(2026-08-06 拆開)。
    # 原本共用一個 ef=0.20 → 對生質機組課了不存在的碳成本,系統性高估 CHP 成本、
    # 低估 CHP 競爭力,進而**高估 power-to-heat 的價值**。量級參考 heat/fuelmix.py:
    # DK1 2025 出力加權隱含 ef ≈ 0.149(生質 32.8% / 煤 27.8% / 氣 23.7% / 廢棄物 13.2%)。
    # 單一機組應該用**單一燃料**的值,不是隊伍平均——見 ARCHETYPES。
    ef_chp: float = 0.20  # 預設:天然氣機組
    ef_pb: float = 0.20  # 尖峰鍋爐(丹麥常見天然氣或輕油)
    eb_max: float = 100.0  # 電鍋爐熱容量 MW_th
    eta_eb: float = 0.99  # 電鍋爐效率
    hp_max: float = 50.0  # 熱泵熱容量 MW_th
    cop_ref: float = 3.2  # 熱泵 COP 參考值(@ 7°C);實際隨氣溫變,見 cop_from_temp
    pb_max: float = 1e4  # 尖峰鍋爐(保證可行性;真實系統一定有備援)
    eta_pb: float = 0.95  # 尖峰鍋爐效率
    s_max: float = 3000.0  # 蓄熱槽容量 MWh_th(丹麥大型槽 ~10–20 小時尖峰負載)
    s_rate: float = 300.0  # 蓄熱槽充/放速率 MW_th
    s_loss: float = 0.002  # 每小時散熱損失比例(槽保溫很好,~0.2%/h)


# 依燃料別的原型機組。**一台機組燒一種燃料**,所以排放因子要用該燃料的值,
# 不能用 heat/fuelmix.py 算出的隊伍加權平均(那是虛構的「平均機組」)。
# ⚠️ 排放因子是量級值,待 Technology Catalogue 校準;其餘技術參數仍是佔位值。
# ⚠️ 燃料**價格**不在這裡(它隨時間變,由 solve(fuel_price=) 傳入)。
ARCHETYPES = {
    "gas": dict(ef_chp=0.20, ef_pb=0.20),  # 天然氣熱電 + 天然氣尖峰鍋爐
    "biomass": dict(ef_chp=0.0, ef_pb=0.20),  # 生質熱電(EU ETS 零碳)+ 天然氣尖峰鍋爐
    "coal": dict(ef_chp=0.34, ef_pb=0.20),  # 燃煤熱電;DK1 2025 仍佔 27.8%
}


def cop_from_temp(temp, cop_ref: float = 3.2, t_ref: float = 7.0) -> np.ndarray:
    """熱泵 COP 隨外氣溫下降 —— **這是熱側的關鍵物理耦合**。

    天冷時熱需求最高,但熱泵效率最低 → 彈性在最需要的時候最貴。這正是
    [[heat-chp-track]] 核心假說「相關的熱義務侵蝕稀缺時的彈性」的物理來源之一。
    用簡化的 Carnot 比例式:COP ∝ T_hot/(T_hot − T_cold),供水溫固定 70°C。
    """
    t = np.asarray(temp, float)
    t_hot = 70.0 + 273.15
    carnot = t_hot / np.maximum(t_hot - (t + 273.15), 1.0)
    carnot_ref = t_hot / (t_hot - (t_ref + 273.15))
    return cop_ref * carnot / carnot_ref


def solve(
    price,
    heat_demand,
    plant: Plant = None,
    fuel_price=30.0,
    co2_price=70.0,
    fuel_price_pb=None,
    cop=None,
    s_init: float = 0.0,
):
    """解一段期間的最適排程。回傳 dict:各項出力陣列 + 利潤(€)。

    price        逐時電價 €/MWh_e
    heat_demand  逐時熱需求 MW_th(必須滿足,等式約束)
    fuel_price   CHP 燃料價 €/MWh_fuel(純量或逐時);fuel_price_pb 預設同 CHP
    cop          熱泵 COP(純量或逐時);None → 用 plant.cop_ref

    蓄熱槽預設從空的開始(s_init=0)且不加期末條件:因為 S≥0 與動態式已保證
    「放出來的必定先充進去」,不會憑空生熱,所以不需要期末歸零(對照電池線的週窗歸零)。
    """
    pl = plant or Plant()
    p = np.asarray(price, float)
    d = np.asarray(heat_demand, float)
    T = len(p)
    assert len(d) == T, f"價格 {T} 與熱需求 {len(d)} 長度不一致"
    fp = (
        np.full(T, fuel_price, float)
        if np.isscalar(fuel_price)
        else np.asarray(fuel_price, float)
    )
    fpb = (
        fp
        if fuel_price_pb is None
        else (
            np.full(T, fuel_price_pb, float)
            if np.isscalar(fuel_price_pb)
            else np.asarray(fuel_price_pb, float)
        )
    )
    c_hp = np.full(T, pl.cop_ref, float) if cop is None else np.asarray(cop, float)
    # 碳價可以是純量或逐時陣列(接真實 EUA 價用)
    cp = (
        np.full(T, co2_price, float)
        if np.isscalar(co2_price)
        else np.asarray(co2_price, float)
    )

    # 變數區塊:P, Qc, Qe, Qh, Qpb, ch, dis, S  → 8 個長度 T 的區塊
    nb = 8
    n = nb * T
    sl = {
        k: slice(i * T, (i + 1) * T)
        for i, k in enumerate(["P", "Qc", "Qe", "Qh", "Qpb", "ch", "dis", "S"])
    }

    # 目標:最小化 −利潤。燃料成本 = (燃料價 + CO2價×排放因子) × 燃料量
    cost_fuel = fp + cp * pl.ef_chp  # CHP 的 €/MWh_fuel(含碳)
    c = np.zeros(n)
    c[sl["P"]] = -p + cost_fuel / pl.eta_el  # 賣電收入 − 發電的燃料成本
    c[sl["Qc"]] = cost_fuel * pl.cv / pl.eta_el  # 抽汽產熱的燃料代價
    c[sl["Qe"]] = p / pl.eta_eb  # 電鍋爐:買電
    c[sl["Qh"]] = p / c_hp  # 熱泵:買電(COP 越高越便宜)
    c[sl["Qpb"]] = (fpb + cp * pl.ef_pb) / pl.eta_pb  # 尖峰鍋爐燒燃料(自己的排放因子)

    I = sp.eye(T, format="csr")
    Z = sp.csr_matrix((T, T))

    # 等式①熱平衡:Qc + Qe + Qh + Qpb + dis − ch = 熱需求
    heat = sp.hstack([Z, I, I, I, I, -I, I, Z], format="csr")
    # 等式②蓄熱槽動態:S_t − (1−loss)·S_{t−1} − ch_t + dis_t = 0(t=0 用 s_init)
    shift = sp.diags([np.ones(T - 1)], [-1], shape=(T, T), format="csr")
    D = I - (1 - pl.s_loss) * shift
    stor = sp.hstack([Z, Z, Z, Z, Z, -I, I, D], format="csr")
    b_stor = np.zeros(T)
    b_stor[0] = (1 - pl.s_loss) * s_init
    A_eq = sp.vstack([heat, stor], format="csr")
    b_eq = np.concatenate([d, b_stor])

    # 不等式①背壓線:Cb·Qc − P ≤ 0     ②容量線:P + Cv·Qc ≤ P_max
    bp = sp.hstack([-I, pl.cb * I, Z, Z, Z, Z, Z, Z], format="csr")
    cap = sp.hstack([I, pl.cv * I, Z, Z, Z, Z, Z, Z], format="csr")
    A_ub = sp.vstack([bp, cap], format="csr")
    b_ub = np.concatenate([np.zeros(T), np.full(T, pl.p_max)])

    hi = {
        "P": pl.p_max,
        "Qc": None,
        "Qe": pl.eb_max,
        "Qh": pl.hp_max,
        "Qpb": pl.pb_max,
        "ch": pl.s_rate,
        "dis": pl.s_rate,
        "S": pl.s_max,
    }
    bounds = [(0.0, hi[k]) for k in sl for _ in range(T)]

    r = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )
    assert r.status == 0, f"LP 失敗:{r.message}"
    x = r.x
    out = {k: x[s] for k, s in sl.items()}
    out["p_buy"] = out["Qe"] / pl.eta_eb + out["Qh"] / c_hp  # power-to-heat 的買電量
    out["p_net"] = out["P"] - out["p_buy"]  # 對電網的淨部位(正=賣)
    out["fuel"] = (out["P"] + pl.cv * out["Qc"]) / pl.eta_el
    # ⚠️ 這是**電力市場淨收益,未計熱收入**(賣電 − 燃料 − 買電)。熱在本模型是義務不是商品。
    # 通常為負:業者燒燃料是為了供熱,電只是副產品 → 負值不是模型錯。
    out["el_net"] = float(-r.fun)
    # 這才是可比、可解讀的指標:單位供熱的淨成本(扣掉賣電收入後)。
    # DH 業者實際追蹤的就是它,也是熱費率的基礎。熱需求外生固定 → 熱收入是常數,
    # 不影響最適排程,所以把它排除在最佳化外是對的。
    out["heat_cost_per_mwh"] = float(-out["el_net"] / max(d.sum(), 1e-9))
    out["cop"] = c_hp
    return out


def demo() -> None:
    pl = Plant()
    T = 48
    # 兩天:每天前 12 小時便宜(含負價)、後 12 小時貴
    p = np.tile(np.r_[np.full(12, -20.0), np.full(12, 120.0)], 2)
    d = np.full(T, 200.0)  # 固定熱需求 200 MW_th

    r = solve(p, d, pl)
    # ① 熱平衡必須完全滿足(這是義務,不是目標)
    bal = r["Qc"] + r["Qe"] + r["Qh"] + r["Qpb"] + r["dis"] - r["ch"]
    assert np.allclose(bal, d, atol=1e-6), "熱平衡未滿足"
    # ② 可行域:背壓線與容量線都不得違反
    assert (r["P"] + 1e-6 >= pl.cb * r["Qc"]).all(), "違反背壓線"
    assert (r["P"] + pl.cv * r["Qc"] <= pl.p_max + 1e-6).all(), "違反容量線"
    assert (r["S"] >= -1e-6).all() and (r["S"] <= pl.s_max + 1e-6).all(), "蓄熱量超界"
    # ③ 負電價時段應該用 power-to-heat 吃電(這是 C3 的機制)
    cheap, exp = p < 0, p > 0
    assert r["p_buy"][cheap].sum() > 10 * r["p_buy"][exp].sum() + 1, (
        f"負電價時應大量 power-to-heat,得便宜時段買 {r['p_buy'][cheap].sum():.0f} MWh"
    )
    # ④ 高電價時段 CHP 應該發電、便宜時段應該少發
    assert r["P"][exp].mean() > r["P"][cheap].mean(), "高價時段應多發電"
    print(
        f"  CHP LP ok: 熱平衡滿足、可行域守住;負價時買電 {r['p_buy'][cheap].sum():,.0f} MWh_e"
        f"、高價時 CHP 均 {r['P'][exp].mean():.0f} MW_e(低價 {r['P'][cheap].mean():.0f})"
    )

    # ⑤ 蓄熱槽是**彈性**:容量越大利潤不可能變差(單調性,守住模型沒寫反)
    small = solve(p, d, Plant(s_max=0.0, s_rate=0.0))["el_net"]
    big = solve(p, d, Plant(s_max=6000.0, s_rate=600.0))["el_net"]
    assert big >= r["el_net"] - 1e-6 >= small - 1e-6, (
        f"蓄熱槽越大淨收益應不減:0槽 {small:.0f} / 預設 {r['el_net']:.0f} / 大槽 {big:.0f}"
    )
    print(
        f"  蓄熱槽 ok: 無槽 €{small:,.0f} ≤ 預設 €{r['el_net']:,.0f} ≤ 大槽 €{big:,.0f}(彈性有價)"
    )

    # ⑥ 熱泵 COP 隨氣溫下降(冷天彈性更貴 —— 核心假說的物理來源)
    cold, mild = cop_from_temp(-10.0), cop_from_temp(10.0)
    assert cold < mild, f"冷天 COP 應較低,得 {cold:.2f} vs {mild:.2f}"
    print(
        f"  COP ok: −10°C {cold:.2f} < +10°C {mild:.2f}(冷天熱泵最不划算,而那時熱需求最高)"
    )


def _real_demo() -> None:
    """用真實 DK1 電價 + 度日熱需求跑一個月,看行為合不合理。"""
    import glob

    import duckdb
    import pandas as pd
    from demand import heat_demand

    if not os.path.exists("new_data/energy.duckdb"):
        print("  (跳過:找不到 energy.duckdb)")
        return
    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, temperature_2m AS temp, "
        "ttf_gas_eur_mwh AS gas FROM training WHERE area='DK1' "
        "AND y_price_eur IS NOT NULL AND temperature_2m IS NOT NULL "
        "AND timestamp_utc >= TIMESTAMP '2024-01-01' AND timestamp_utc < TIMESTAMP '2024-02-01' "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    # 熱需求:用全期校準的度日代理,取這個月;再縮到單一 DH 系統的規模(佔 DK1 的 8%)
    q_all = heat_demand(d["temp"].to_numpy())
    q = q_all * 0.08
    gas = d["gas"].fillna(d["gas"].median()).to_numpy()
    cop = cop_from_temp(d["temp"].to_numpy())
    r = solve(d["price"].to_numpy(), q, Plant(), fuel_price=gas, cop=cop)

    p = d["price"].to_numpy()
    neg = p < 0
    print(f"\n=== 真實 DK1 2024-01(單一 DH 系統,{len(d)} 小時)===")
    print(
        f"  熱需求 {q.mean():.0f} MW_th 均值(尖峰 {q.max():.0f}),氣溫 {d['temp'].mean():.1f}°C"
    )
    print(
        f"  CHP 發電均 {r['P'].mean():.0f} MW_e,尖峰鍋爐佔熱量 {r['Qpb'].sum() / q.sum():.0%}"
    )
    print(
        f"  power-to-heat 買電 {r['p_buy'].sum():,.0f} MWh_e"
        f"(其中負電價時段 {r['p_buy'][neg].sum():,.0f},佔 {r['p_buy'][neg].sum() / max(r['p_buy'].sum(), 1e-9):.0%})"
    )
    print(
        f"  負電價時數 {neg.mean():.1%};蓄熱槽平均 {r['S'].mean():.0f}/{Plant().s_max:.0f} MWh_th"
    )
    print(
        f"  電力市場淨收益 €{r['el_net']:,.0f}(未計熱收入 → 負值正常:燒燃料是為了供熱)"
    )
    print(
        f"  **單位供熱淨成本 €{r['heat_cost_per_mwh']:.1f}/MWh_th**"
        "  ← 可比指標;丹麥 DH 生產成本量級 €20–50,扣電收入後更低"
    )
    hi, lo = p > np.percentile(p, 75), p < np.percentile(p, 25)
    print(
        f"  CHP 發電:高價四分位 {r['P'][hi].mean():.0f} MW_e vs 低價四分位 {r['P'][lo].mean():.0f} MW_e"
        "  ← 熱約束下仍跟著價格走 = 蓄熱槽在搬移熱的生產時點"
    )


if __name__ == "__main__":
    demo()
    _real_demo()
