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

✅ **技術參數已是 DEA Technology Catalogue 真值**(2026-08-07,經 `heat/dea.py`)。
仍不是目錄值的兩類:①**排放因子**(目錄沒有,是燃料屬性,見 ARCHETYPES)②**容量與熱網
規模的對齊**(目錄給的是單一機組典型值)。

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

    **預設值 = DEA Technology Catalogue 的木片抽汽式機組**
    (`09a Wood Chips extract. plant`, year=2020, est=ctrl),2026-08-07 從佔位值換掉。
    要別的燃料或敏感度區間用 `dea_plant()`,不要手改這裡。

    佔位值錯得最離譜的是 `cb`:原本猜 0.75,目錄真值 0.45(木片)/0.59(顆粒)/
    0.84(煤)/1.80(氣 CC)—— **不只高估一倍,而且真值隨技術差 4 倍**,不存在一個
    「通用 Cb」。cb 是背壓線斜率 → 直接決定給定熱量下機組能少發多少電 = 彈性大小。

    ⚠️ **容量欄位(p_max/eb_max/hp_max/pb_max/s_max/s_rate)是目錄的「單一機組典型值」**,
    不是熱網的實際裝置量。真實 DH 系統是多台機組併聯,而且機組尺寸要跟熱需求規模對齊。
    這些值與熱需求的匹配問題**尚未解決**(見 STATUS.md §7 第 5 點)。
    """

    p_max: float = 258.2  # [TC] CHP 等效凝汽容量 MW_e(單一機組)
    cb: float = 0.45  # [TC] 背壓係數(功熱比下界)
    cv: float = 0.14  # [TC] 抽汽損失係數:每產 1MW_th 熱少發 0.14MW_e 電
    eta_el: float = 0.409  # [TC] 電效率(net, annual average)
    # 排放因子 tCO2/MWh_fuel,**熱電機組與尖峰鍋爐分開設**(2026-08-06 拆開)。
    # 原本共用一個 ef=0.20 → 對生質機組課了不存在的碳成本,系統性高估 CHP 成本、
    # 低估 CHP 競爭力,進而**高估 power-to-heat 的價值**。量級參考 heat/fuelmix.py:
    # DK1 2025 出力加權隱含 ef ≈ 0.149(生質 32.8% / 煤 27.8% / 氣 23.7% / 廢棄物 13.2%)。
    # 單一機組應該用**單一燃料**的值,不是隊伍平均——見 ARCHETYPES。
    ef_chp: float = 0.0  # 生質(EU ETS 零碳);目錄裡沒有排放因子,見 ARCHETYPES
    ef_pb: float = 0.20  # 尖峰鍋爐(丹麥常見天然氣或輕油)
    eb_max: float = 20.0  # [TC] 電鍋爐熱容量 MW_th(41 Electric boiler, large,單台)
    eta_eb: float = 0.99  # [TC] 電鍋爐效率
    hp_max: float = 10.0  # [TC] 熱泵熱容量 MW_th(40 Comp. hp, airsource 10 MW,單台)
    cop_ref: float = 2.8  # [TC] 熱泵 COP 參考值(@ 7°C);隨氣溫變,見 cop_from_temp
    # 尖峰鍋爐**刻意不用目錄值**:'44 Natural Gas DH Only' 的單台容量只有 5.25 MW_th,
    # 拿它當 pb_max 會讓 LP 在寒冬直接無解。這個變數在模型裡的角色是**可行性後備**
    # (真實熱網一定有足夠備援鍋爐,只是台數多),不是某一台機組的銘牌值。
    pb_max: float = 1e4
    eta_pb: float = 1.03  # [TC] 尖峰鍋爐效率(>1 是因為目錄以低位發熱值 LHV 計)
    s_max: float = 2880.0  # [TC] 蓄熱槽容量 MWh_th(141b Large TTES)
    s_rate: float = 288.0  # [TC] 蓄熱槽充/放速率 MW_th
    s_loss: float = 0.0025  # [TC] 每小時散熱損失比例(目錄給 %/day ÷ 24)


# 依燃料別的**排放因子** tCO2/MWh_fuel。**目錄裡沒有這個**(排放是燃料屬性不是技術
# 屬性)→ 這三個仍是量級值,不是目錄真值。一台機組燒一種燃料,所以要用該燃料的值,
# 不能用 heat/fuelmix.py 的隊伍加權平均(那是虛構的「平均機組」)。
# ⚠️ 燃料**價格**不在這裡(它隨時間變,由 solve(fuel_price=) 傳入)。
ARCHETYPES = {
    "gas": dict(ef_chp=0.20, ef_pb=0.20),  # 天然氣熱電 + 天然氣尖峰鍋爐
    "biomass": dict(ef_chp=0.0, ef_pb=0.20),  # 生質熱電(EU ETS 零碳)+ 天然氣尖峰鍋爐
    "coal": dict(ef_chp=0.34, ef_pb=0.20),  # 燃煤熱電;DK1 2025 仍佔 27.8%
}

# DEA 技術原型 → 燃料別(決定排放因子)。鍵對應 dea.CHP_ARCHETYPES。
_ARCH_FUEL = {
    "wood_chips": "biomass",
    "wood_pellets": "biomass",
    "gas_cc": "gas",
    "coal": "coal",
}


def dea_plant(arch: str = "wood_chips", est: str = "ctrl", **over) -> Plant:
    """直接從 Technology Catalogue 建一個 Plant(技術參數全是目錄真值)。

    `est='lower'/'upper'` 就是目錄自帶的區間 → **敏感度分析不用另外設計情境**。
    `**over` 覆寫個別欄位(例如把容量對齊到熱網規模)。

    `pb_max` 一律保留 Plant 的可行性後備值,不用目錄的單台 5.25 MW_th(理由見上)。
    排放因子來自 ARCHETYPES,不是目錄。
    """
    import dea  # 延後匯入:chp.py 不該因為缺 new_data/DEA_data 就 import 失敗

    p = dea.plant_params(dea.CHP_ARCHETYPES[arch], est=est)
    p.pop("pb_max")
    return Plant(**{**p, **ARCHETYPES[_ARCH_FUEL[arch]], **over})


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

    # ⑦ Plant 的預設值必須真的等於目錄值 —— 上面那些數字是手抄的,這行防止它們默默漂掉
    if os.path.exists("new_data/DEA_data"):
        want = dea_plant("wood_chips")
        drift = {
            f: (getattr(pl, f), getattr(want, f))
            for f in pl.__dataclass_fields__
            if abs(getattr(pl, f) - getattr(want, f)) > 1e-9
        }
        assert not drift, f"Plant 預設值與 DEA 目錄不一致(手抄漂掉了):{drift}"
        # 背壓係數隨技術差 4 倍 → 不存在「通用 Cb」,原本猜 0.75 高估木片近一倍
        cbs = {a: dea_plant(a).cb for a in _ARCH_FUEL}
        assert max(cbs.values()) / min(cbs.values()) > 3, f"Cb 應隨技術大幅變動:{cbs}"
        print(
            "  DEA ok: Plant 預設 == 目錄木片抽汽值;各原型 Cb = "
            + ", ".join(f"{a} {v:.2f}" for a, v in cbs.items())
        )


def _real_demo() -> None:
    """用真實 DK1 電價 + 度日熱需求跑一個月,看行為合不合理。

    **原型與燃料價必須配對**:燒天然氣的機組要配 TTF、燒煤的要配 API2。
    生質(木片/顆粒)**沒有燃料價來源**(無國際期貨,需丹麥能源署統計)→ 目前無法跑,
    硬拿天然氣價代打會讓成本水準完全失真(曾跑出負的單位供熱成本)。
    """
    import duckdb
    from demand import heat_demand

    if not os.path.exists("new_data/energy.duckdb"):
        print("  (跳過:找不到 energy.duckdb)")
        return
    con = duckdb.connect("new_data/energy.duckdb", read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, temperature_2m AS temp, "
        "ttf_gas_eur_mwh AS gas, api2_coal_eur_mwh AS coal, eua_co2_eur_t AS co2 "
        "FROM training WHERE area='DK1' "
        "AND y_price_eur IS NOT NULL AND temperature_2m IS NOT NULL "
        "AND timestamp_utc >= TIMESTAMP '2024-01-01' AND timestamp_utc < TIMESTAMP '2024-02-01' "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    # 熱需求:用全期校準的度日代理,取這個月;再縮到單一 DH 系統的規模(佔 DK1 的 8%)
    q = heat_demand(d["temp"].to_numpy()) * 0.08
    cop = cop_from_temp(d["temp"].to_numpy())
    gas = d["gas"].ffill().bfill().to_numpy()
    co2 = d["co2"].ffill().bfill().to_numpy()  # 真實 EUA(2026-08-07 起全期覆蓋)
    fuels = {  # 原型 → 該燒的燃料價(EUR/MWh_fuel)
        "gas_cc": gas,
        "coal": d["coal"].ffill().bfill().to_numpy(),
    }
    r = solve(
        d["price"].to_numpy(),
        q,
        dea_plant("gas_cc"),
        fuel_price=gas,
        co2_price=co2,
        cop=cop,
    )

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
    hi, lo = p > np.percentile(p, 75), p < np.percentile(p, 25)
    print(
        f"  CHP 發電:高價四分位 {r['P'][hi].mean():.0f} MW_e vs 低價四分位 {r['P'][lo].mean():.0f} MW_e"
        "  ← 熱約束下仍跟著價格走 = 蓄熱槽在搬移熱的生產時點"
    )
    # 燃料價有真值的兩個原型並排(碳價已是真實 EUA)。生質缺價,故意不列。
    print("\n  單位供熱淨成本(原型 × 對應燃料價 × 真實 EUA):")
    for a, fp in fuels.items():
        # 尖峰鍋爐一律燒天然氣(見 ARCHETYPES 的 ef_pb)→ 煤機組也要用氣價當 pb 燃料
        rr = solve(
            d["price"].to_numpy(),
            q,
            dea_plant(a),
            fuel_price=fp,
            fuel_price_pb=gas,
            co2_price=co2,
            cop=cop,
        )
        pl = dea_plant(a)
        print(
            f"    {a:8} 燃料均 €{fp.mean():5.1f}/MWh_fuel → "
            f"**€{rr['heat_cost_per_mwh']:6.1f}/MWh_th**(CHP 均 {rr['P'].mean():.0f} MW_e,"
            f"機組 {pl.p_max:.0f} MW_e / 熱網均 {q.mean():.0f} MW_th = {pl.p_max / q.mean():.1f}×)"
        )
    print("    biomass  ✗ 無燃料價來源(木片/顆粒無國際期貨)→ 目前跑不了,不是模型問題")


if __name__ == "__main__":
    demo()
    _real_demo()
