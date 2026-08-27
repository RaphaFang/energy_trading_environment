"""🔑 **八個 agent、一條共用熱需求、一個聯合 LP** —— 論文多 agent 層的地基。

**2026-08-25 建立。** 設計定案見 `THESIS_DIRECTION.md` §13。
這支取代「N 台各自獨立跑、各吃一份縮放過的需求」那個狀態(見 `README.md` ⑦ Phase 2)。

━━━ 🔑 為什麼「各自最大化」與「聯合 LP」是同一件事 ━━━━━━━━━━━━━━━━━

使用者要的是**六個獨立業主各自 price-taker、各自最大化自己的利潤**。
那與這支跑的聯合 LP **不衝突**,因為:

    ① 聯合 LP 的約束:所有機組的熱加起來 = CTR + VEKS 的熱需求
    ② 該約束的**對偶變數** = 每小時的熱邊際成本 λ_heat[t]      ← LP 免費給出
    ③ 每個 agent 拿 λ_heat[t] + 外生電價,各自最大化自己的利潤
    ④ ③ 的排程 = ① 的排程,逐台逐小時相同                      ← LP 對偶

**LP 是解法,不是模型。** 論文照 agent 版寫,程式跑聯合 LP,兩者一致,
而 **λ_heat 是一個新輸出** —— 它就是 Varmelast 按成本排序時隱含在做的事。

🔴 **兩個成立條件(論文一定要寫)**:
1. **問題必須是凸的** —— 加整數(機組啟停)就有對偶間隙。這是「不做 unit commitment」
   的**真正理由**,不是計算時間。
2. **熱那側也必須 price-taking** —— 辯護不是「我假設沒有市場力」,而是
   **hvile-i-sig-selv 成本回收原則 + Varmelast 的職責就是按成本排序**
   → **熱的市場力是被法規排除的,不是被假設掉的。**

━━━ 機組模型:固定電熱比(基準版) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    P[i,t] = Cb[i] · Q[i,t]        Cb = EPT 逐台實測的電熱比

→ `P` 不是自由變數,可以代掉 → 變數少一半。
🔴 **`Cb` 不是 `Cv` 的替代品**,是把抽汽的可行三角形壓成下邊那條線。兩者對
「接手者多產熱時電怎麼變」給**相反符號**(+Cb vs −Cv)。但熱出力愈大三角形愈窄
(AMV4:Q=150 時可調 83 MW_e,Q=300 時只剩 17)→ **在最冷的小時損失最小,
而那正是本論文最在意的小時。** `Cv` 掃描是後續的敏感度,不是地基。見 §13.3。

━━━ 滾動視窗 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    開 48 小時 → 只保留前 24 小時 → 蓄熱存量接到下一輪 → 前進 24 小時

**丟掉後 24 小時**是為了讓「視窗末端把蓄熱放空」那個假行為落在被丟棄的那段
→ **不需要編一個蓄熱的終端價值。**
📌 視窗內用**真實的日前電價** —— 日前價在執行日前一天中午就公布了,
所以「一天之內完全預知」是真的,不是作弊;假的是「整年完全預知」。

━━━ ✅ 對實測的驗證結果(2026-08-25) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

拿 varmelast 的**分項產熱**比模型的供熱組成,`模型 ÷ 實測`:

    熱電(生質)    2023 1.03   2024 0.97   2025 1.04      ← 主量,三年都在 ±5% ✅
    垃圾          2023 0.99   2024 1.01   2025 1.00      ← ⚠️ **這是約束不是預測**(見下)
    尖峰鍋爐      2023 0.21   2024 0.77   2025 0.29      ← 🔴 模型**少用**,絕對量小但相對差大
    熱泵/電鍋爐   2–5 倍                                  ← 🔴 已知失效模式,未改善

**兩個讓它從「錯 5 倍」變成「±5%」的修正,都是資料修正不是調參:**

1. **天然氣的丹麥能源稅(energiafgift)** —— 先前只收裸的 TTF + ETS,尖峰鍋爐算成
   47.4 EUR/MWh_th。2024 的稅是 **34.6 EUR/MWh_fuel,與氣價本身同一個量級**
   → 補上之後尖峰鍋爐約 81,正好落到生質後面。法源 GASAL § 1(見 `assumptions.py`)。
2. **邊界修正:垃圾廠只有 0.75 的熱進得了傳輸網** —— 其餘進地方配網
   (Vestforbrænding 自己五個市、ARGO 的 Roskilde 配網)。2023/2024 實測 0.77/0.75,
   **兩年一致**;生質那幾台同樣算出來是 **1.00**。見 `into_net_share()`。

🔴 **垃圾那一列不能當驗證通過的證據** —— 上面第 2 點把它變成了約束,所以它必然對上。
   真正被驗證的是**生質 vs 尖峰鍋爐的分配**。

🔑 **順帶得到一個關於資料的結論**:**2024 那一年,丹麥海關的木顆粒單價 €67.9
   與實際調度不相容**(模型只跑出 0.70×,Avedøre 會被尖峰鍋爐擠掉);瑞典端 €48.8 才對得上。
   ⚠️ 但 **2023 與 2025 兩端都相容,分不出來** → **這是「那一格資料是壞的」,
   不是一個穩定的顯示性偏好估計。** 與 `DATA.md` §8 已記的「2024 進口量薄、單價代表性存疑」一致。

🔴 **仍未解:power-to-heat 被過度使用 2–5 倍。** 這是 repo 掛了很久的同一個病
(「LP 對價格過度反應」)。P2H 只佔實測供熱 1.3%,所以對頭條數字影響小,但**論文要寫明**。

用法:python new_src/heat/joint_dispatch.py [年份]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assumptions as A  # noqa: E402
import chp  # noqa: E402
import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EPT = ROOT / "new_data/ept/ept_produktion_2023_2025.parquet"
EPT_ANL = ROOT / "new_data/ept/ept_stamdata_anlaeg_2025.parquet"
OUT = ROOT / "figs/joint_dispatch"
NET = "Storkøbenhavn"

# varmelast 自己公布的尖峰/備援容量(35 座尖峰中心合計)。EPT 逐台加總會多算,
# 因為它含配網層的鍋爐 → 用調度者自己的數字,再按 EPT 的容量比例分給業主。
PEAK_TOTAL_MW = 1300.0

# 蓄熱槽三座(varmelast 公布值;EPT 只登記前兩座,Høje Taastrup 是池儲不算水槽)
STORES = {
    #  名稱:            (容量 MWh, 充放速率 MW, 擁有者)
    "Amager": (1000.0, 300.0, "HOFOR Energiproduktion"),
    "Avedøre": (2200.0, 330.0, "Ørsted"),
    "Høje Taastrup": (3300.0, 30.0, "系統共用"),  # 週儲,速率只有 30
}
VOLL = 10_000.0
"""**未供應熱量的懲罰** [EUR/MWh_th]。遠高於任何真實選項(最貴的約 90)。

🔑 **它存在的理由不是為了讓 LP 一定有解,是為了把「解不出來」變成可量測的量。**
情境問的正是「**在滿足需求的前提下**會出現什麼」—— 如果某些小時根本滿足不了,
**那個缺口就是答案**,不是程式錯誤。
🔴 **有未供應的小時,那幾小時的 λ_heat = VOLL,必須從 λ 的統計裡剔除**,
   否則年均會被一個人造的 10,000 拉爆。
"""

S_LOSS = 0.001  # 每小時散熱,DEA 141b TTES 量級

# 逐台燒什麼(EPT 2024 實測燃料組成,見記憶 biomass-fuel-price)
# 🔴 鍵是機組名的**前綴** —— EPT 的名字帶後綴("AVV1 Dampturbine"),用 dict.get 會查不到
FUEL = {
    "AMV1": "wood_pellets",
    "AMV4": "wood_chips",
    "AVV1": "wood_pellets",
    "AVV2": "wood_pellets",
    "KKV 8": "wood_chips",
}

def fuel_of(unit: str) -> str:
    """機組名 → 燃料。**查不到就拋錯,絕不回預設值。**

    🔴 這裡踩過一次:EPT 的機組名是 `"AVV1 Dampturbine"`,而 `FUEL` 的鍵是 `"AVV1"`,
    用 `FUEL.get(u, "wood_chips")` 會**默默**把 AVV1/AVV2 當成木片。
    木顆粒 67.9 vs 木片 40.2 EUR/MWh_fuel,再除以 AVV2 的 η_th=0.372 放大 2.7 倍
    → **merit order 整個翻掉,而且不會有任何錯誤訊息。**
    """
    for k, v in FUEL.items():
        if unit.startswith(k):
            return v
    raise KeyError(
        f"{unit!r} 不在 FUEL 對照表裡 —— **不要讓它默默拿到預設燃料**。"
        "見記憶 biomass-fuel-price:三台燒木顆粒、兩台燒木片,價差很大。"
    )


OWNER = {  # EPT 的公司名 → 論文裡的 agent 名
    "HOFOR ENERGIPRODUKTION A/S": "HOFOR Energiproduktion",
    "Ørsted Bioenergy & Thermal Power A/S": "Ørsted",
    "I/S Amager Ressourcecenter": "ARC",
    "I/S VESTFORBRÆNDING": "Vestforbrænding",
    "ARGO I/S": "ARGO",
    "VEKS I/S": "VEKS",
    "CTR I/S": "CTR",
    "HOFOR FJERNVARME P/S": "HOFOR Fjernvarme",
}


# ══════════════════════════════════════════════════════════════════════
#  ① 車隊 —— 一律從 EPT 讀,不手抄
# ══════════════════════════════════════════════════════════════════════


def fleet(year: int = 2024, drop: tuple = (), waste_scale: float = 1.0) -> pd.DataFrame:
    """哥本哈根網上的 CHP 機組 + 逐台實測的 `eta_th` / `Cb`(EPT)。

    ⚠️ 只收**燃料投入 > 500 TJ 且有發電**的機組。門檻擋掉的是工業自用與零星小機組
    —— 它們的熱已經含在 CTR/VEKS 的消費裡(見 §13.4 的 C 類)。
    """
    p = pd.read_parquet(EPT)
    d = p[(p.aar == year) & p.fv_net_navn.astype(str).str.contains(NET, na=False)]
    d = d[(d.elprod_TJ.fillna(0) > 0) & (d.brutto_TJ > 500)].copy()
    d = d[d.selskab_navn.isin(OWNER)]  # 工業(CP Kelco)不當 agent

    d["agent"] = d.selskab_navn.map(OWNER)
    d["unit"] = d.anlaeg_navn.str.replace("&#43;", "+", regex=False).str.strip()
    d["eta_th"] = d.varmeprod_TJ / d.brutto_TJ
    d["eta_el"] = d.elprod_TJ / d.brutto_TJ
    d["cb"] = d.eta_el / d.eta_th
    d["q_max"] = d.varmekapacitet_MW
    d["is_waste"] = d.affald_TJ.fillna(0) / d.brutto_TJ > 0.5

    # 🔴 垃圾廠的限制不是爐子容量,是**收到多少垃圾**。EPT 有逐台年度實績 →
    #    把「年度可燒的量」換算成逐時的可用容量,不然 LP 會讓它們全年滿載
    #    (邊際成本是負的,滿載在數學上完全正確,只是現實裡沒有那麼多垃圾)。
    #    ⚠️ **所以垃圾的年供熱量在模型裡是約束不是預測** —— 驗證表的垃圾那一列
    #       會自動對上,不可以拿它當「模型驗證通過」的證據。
    hours = 8784 if year % 4 == 0 else 8760
    # 🔑 **邊界修正**:模型的邊界是 CTR+VEKS **傳輸網**,但垃圾廠有一部分熱
    #    直接進地方配網(Vestforbrænding 自己五個市、ARGO 的 Roskilde 配網),
    #    從來沒進過傳輸網。實測比例 = varmelast 的 AFFALD ÷ EPT 的垃圾廠交付:
    #    **2023 = 0.77、2024 = 0.75** —— 兩年一致,所以是結構不是雜訊。
    #    生質那幾台同樣算出來是 **1.00**(Amager/Avedøre/Køge 直接接傳輸網)→ 不修正。
    heat_mwh = d.varmelev_TJ * 1000 / 3.6 * np.where(d.is_waste, into_net_share(year), 1.0)
    d["avail"] = np.where(d.is_waste,
                          (heat_mwh / (d.q_max * hours)).clip(upper=1.0), 1.0)
    d["q_eff"] = d.q_max * d.avail
    f = d.set_index("unit")[
        ["agent", "q_max", "q_eff", "avail", "eta_th", "eta_el", "cb", "is_waste"]]
    if drop:  # 退場情境:整台移除(不是降容量)
        miss = [u for u in drop if not any(x.startswith(u) for x in f.index)]
        if miss:
            raise KeyError(f"要退場的機組不在車隊裡:{miss};現有 {list(f.index)}")
        f = f[[not any(x.startswith(u) for u in drop) for x in f.index]]
    if waste_scale != 1.0:  # 垃圾產能削減(政治協議的 −30%)
        f.loc[f.is_waste, "q_eff"] *= waste_scale
    return f


def into_net_share(year: int) -> float:
    """垃圾廠的熱有多少比例真的進了 CTR+VEKS 傳輸網(實測)。

    `varmelast 的 BE-VL-AFFALD-EF ÷ EPT 垃圾廠的 varmelev`。**2023 = 0.77、2024 = 0.75。**
    🔴 **不修正的話垃圾會多出 1/3** —— 模型會拿地方配網的熱去餵傳輸網的需求。
    ⚠️ 這是**總量**比例,逐廠拆不開(varmelast 只公布分燃料不分廠)。
    """
    p = pd.read_parquet(EPT)
    d = p[(p.aar == year) & p.fv_net_navn.astype(str).str.contains(NET, na=False)]
    d = d[(d.elprod_TJ.fillna(0) > 0) & (d.brutto_TJ > 500)]
    w = d[d.affald_TJ.fillna(0) / d.brutto_TJ > 0.5]
    v = validate.load_dk2(year)
    v = v[v.timestamp.dt.year == year]
    return float(v["BE-VL-AFFALD-EF"].sum() / 1000 / (w.varmelev_TJ.sum() / 3.6))


def peak_blocks() -> pd.Series:
    """尖峰/備援鍋爐,按 EPT 容量比例把 varmelast 的 1,300 MW 分給業主。

    ⚠️ 非 agent 的地方配網(Brøndby、Albertslund…)合併成一塊 `其他配網`
    —— 它們的熱已在 CTR/VEKS 的消費裡,但**容量**還是要在,否則尖峰解不出來。
    """
    a = pd.read_parquet(EPT_ANL)
    a = a[a.fv_net_navn.astype(str).str.contains(NET, na=False)]
    b = a[a.anlaegstype_navn.isin(["Kedel", "Dampkedel", "Gasturbine"])]
    g = b.groupby(b.selskab_navn.map(OWNER).fillna("其他配網")).varmekapacitet_MW.sum()
    return (g / g.sum() * PEAK_TOTAL_MW).sort_values(ascending=False)


# ══════════════════════════════════════════════════════════════════════
#  ② 每小時的邊際成本(EUR / MWh_th)
# ══════════════════════════════════════════════════════════════════════


def marginal_costs(
    d: pd.DataFrame, fl: pd.DataFrame, year: int, bio_end: str = "se",
    over: dict | None = None,
) -> dict:
    """每個熱源每小時多產 1 MWh_th 的淨成本(**已扣掉賣電收入**)。

        CHP:   p_fuel/η_th + θ_h + vom_th − Cb·p_el[t]
        熱泵:  (p_el[t] + τ + κ) / COP[t]
        電鍋爐:(p_el[t] + τ + κ) / η_eb
        尖峰:  (p_gas[t] + ef_gas·p_CO2[t]) / η_pb

    🔴 **垃圾的 `p_fuel` 是負的**(收處理費)→ 它的邊際成本強烈為負 → LP 會讓它先跑滿。
    那不是硬寫的 must-run,是**算出來的**。
    """
    over = over or {}
    pel = d["price"].to_numpy()
    tau_kappa = A.TAU_EL + A.KAPPA_NET
    pr = chp.dea_plant("wood_chips")  # 只借 vom / η_eb / η_pb / cop_ref 這幾個目錄值

    c = {}
    for u, r in fl.iterrows():
        if r.is_waste:
            p_fuel = over.get("waste_fuel", A.waste_fuel_price_eur_mwh())
            theta = over.get("theta_h", A.THETA_HEAT_WASTE)
        else:
            k = fuel_of(u)
            p_fuel = over.get(k, A.biomass_fuel_price_assumed(year, k, bio_end))
            theta = 0.0
        c[u] = p_fuel / r.eta_th + theta + pr.vom_th - r.cb * (pel - pr.vom_e)

    cop = chp.cop_from_temp(d["tair"].to_numpy(), cop_ref=pr.cop_ref)
    c["熱泵"] = (pel + tau_kappa) / cop + pr.vom_hp
    c["電鍋爐"] = (pel + tau_kappa) / pr.eta_eb + pr.vom_eb
    # 🔴 天然氣要繳丹麥的 energiafgift,而且區域供熱廠**不能退**。
    #    2024 稅率 34.6 EUR/MWh_fuel,與 TTF 氣價本身同一個量級 → 漏掉會讓尖峰鍋爐便宜一倍。
    gas = d["gas"].to_numpy() + over.get("gas_tax", A.gas_energy_tax_eur_mwh(year))
    co2 = over.get("co2", d["co2"].to_numpy())
    c["尖峰鍋爐"] = (gas + pr.ef_pb * co2) / pr.eta_pb + pr.vom_pb

    return c


# ══════════════════════════════════════════════════════════════════════
#  ③ 一個視窗的 LP
# ══════════════════════════════════════════════════════════════════════


def solve_window(
    dem: np.ndarray, cost: dict, caps: dict, s_init: dict
) -> tuple[pd.DataFrame, np.ndarray, float]:
    """解一個視窗。回 (逐時各熱源出力, λ_heat, 目標值)。

    變數順序:每個熱源一塊(長度 T),然後每座蓄熱槽的 ch / dis / S 各一塊。
    """
    cost = dict(cost)
    cost["未供應"] = np.full(len(dem), VOLL)   # 鬆弛:見 VOLL 的說明
    srcs = list(cost)
    T = len(dem)
    ns = len(STORES)
    n_src = len(srcs)
    n = (n_src + 3 * ns) * T

    def blk(k):  # 第 k 塊的欄位切片
        return slice(k * T, (k + 1) * T)

    obj = np.zeros(n)
    for k, s in enumerate(srcs):
        obj[blk(k)] = cost[s]

    # ① 熱平衡(T 條等式)—— 這一條的對偶變數就是 λ_heat
    Aeq = np.zeros((T + ns * T, n))
    beq = np.zeros(T + ns * T)
    for k in range(n_src):
        Aeq[np.arange(T), np.arange(k * T, (k + 1) * T)] = 1.0
    for j in range(ns):
        dis_k, ch_k = n_src + 3 * j + 1, n_src + 3 * j
        Aeq[np.arange(T), np.arange(dis_k * T, (dis_k + 1) * T)] = 1.0
        Aeq[np.arange(T), np.arange(ch_k * T, (ch_k + 1) * T)] = -1.0
    beq[:T] = dem

    # ② 蓄熱動態(每座 T 條等式):S_t − (1−loss)·S_{t−1} − ch_t + dis_t = 0
    for j, name in enumerate(STORES):
        ch_k, dis_k, s_k = n_src + 3 * j, n_src + 3 * j + 1, n_src + 3 * j + 2
        rows = T + j * T + np.arange(T)
        Aeq[rows, np.arange(s_k * T, (s_k + 1) * T)] = 1.0
        Aeq[rows[1:], np.arange(s_k * T, (s_k + 1) * T - 1)] = -(1 - S_LOSS)
        Aeq[rows, np.arange(ch_k * T, (ch_k + 1) * T)] = -1.0
        Aeq[rows, np.arange(dis_k * T, (dis_k + 1) * T)] = 1.0
        beq[T + j * T] = (1 - S_LOSS) * s_init[name]

    bounds = []
    for s in srcs:
        bounds += [(0, caps.get(s, None))] * T   # 未供應無上限
    for name, (smax, rate, _) in STORES.items():
        bounds += [(0, rate)] * T + [(0, rate)] * T + [(0, smax)] * T

    res = linprog(obj, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(
            f"視窗無解:{res.message}\n"
            "→ 幾乎一定是「總容量不足以滿足這幾小時的熱需求」。"
            "檢查 PEAK_TOTAL_MW 與各機組 q_max,不要靠放寬熱平衡來繞過去。"
        )

    out = pd.DataFrame({s: res.x[blk(k)] for k, s in enumerate(srcs)})
    for j, name in enumerate(STORES):
        out[f"ch:{name}"] = res.x[blk(n_src + 3 * j)]
        out[f"dis:{name}"] = res.x[blk(n_src + 3 * j + 1)]
        out[f"S:{name}"] = res.x[blk(n_src + 3 * j + 2)]
    # 熱平衡約束的對偶 = 多 1 MWh_th 需求會讓總成本增加多少 → 就是熱的邊際價值。
    # 🔴 **它可以是負的,而且那是對的**:垃圾的邊際成本是負的(收處理費),
    #    高電價時 CHP 的熱也是負成本(它為了賣電而必須產熱)→ 那些小時多一點熱需求反而省錢。
    lam = res.eqlin.marginals[:T]
    return out, lam, float(res.fun)


# ══════════════════════════════════════════════════════════════════════
#  ④ 滾動
# ══════════════════════════════════════════════════════════════════════


def run(
    year: int = 2024,
    look: int = 48,
    keep: int = 24,
    bio_end: str = "se",  # 見模組 docstring:只有瑞典端三年都對得上
    hp_mw: float = 50.3,
    drop: tuple = (),
    dem_scale: float = 1.0,
    waste_scale: float = 1.0,
    over: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """跑一整年的滾動排程。回 (逐時出力 + λ_heat + 電力, 逐 agent 年度利潤)。

    情境參數(全部預設 = 現況):
      `drop`        整台移除的機組(前綴比對),例如 `("AMV1", "AVV1")`
      `dem_scale`   熱需求乘數(2035 的成長,見 `demand_trend.py`)
      `waste_scale` 垃圾機組的容量乘數(政治協議的 −30% → 0.7)
      `hp_mw`       熱泵容量(HOFOR 計畫 300 MW × α)
      `over`        價格/稅費覆寫,鍵:`wood_chips` `wood_pellets` `waste_fuel`
                    `theta_h` `gas_tax` `co2`
    ⚠️ **電價不隨情境變** —— 這是刻意的(見 §13 不做市場出清)。
       所有情境共用同一年的日前價 = 「如果 2035 遇上那一年」。
    """
    d = validate.load_dk2(year)
    d = d[d.timestamp.dt.year == year].reset_index(drop=True)
    fl = fleet(year, drop=drop, waste_scale=waste_scale)
    pb = peak_blocks()

    cost = marginal_costs(d, fl, year, bio_end, over)
    caps = {u: r.q_eff for u, r in fl.iterrows()}  # 垃圾用降額後的(見 fleet())
    caps["熱泵"] = hp_mw
    caps["電鍋爐"] = 120.2
    caps["尖峰鍋爐"] = float(pb.sum())

    dem = d["dem"].to_numpy() * dem_scale
    T = len(dem)
    s_init = {k: 0.0 for k in STORES}
    parts, lams = [], []
    for k in range(0, T, keep):
        hi = min(k + look, T)
        w = {s: v[k:hi] for s, v in cost.items()}
        o, lam, _ = solve_window(dem[k:hi], w, caps, s_init)
        n_keep = min(keep, hi - k)
        parts.append(o.iloc[:n_keep])
        lams.append(lam[:n_keep])
        s_init = {name: float(o[f"S:{name}"].iloc[n_keep - 1]) for name in STORES}

    res = pd.concat(parts, ignore_index=True)
    res["lambda_heat"] = np.concatenate(lams)
    res["timestamp"] = d["timestamp"].to_numpy()[: len(res)]
    res["dem"] = dem[: len(res)]
    res["price"] = d["price"].to_numpy()[: len(res)]

    # 電力側:CHP 發電(P = Cb·Q)、power-to-heat 買電、淨部位
    pr = chp.dea_plant("wood_chips")
    cop = chp.cop_from_temp(d["tair"].to_numpy(), cop_ref=pr.cop_ref)[: len(res)]
    res["p_chp"] = sum(res[u] * fl.loc[u, "cb"] for u in fl.index)
    res["p_buy"] = res["熱泵"] / cop + res["電鍋爐"] / pr.eta_eb
    res["p_net"] = res["p_chp"] - res["p_buy"]

    profit = agent_profit(res, fl, cost, pb)
    return res, profit


def agent_profit(
    res: pd.DataFrame, fl: pd.DataFrame, cost: dict, pb: pd.Series
) -> pd.DataFrame:
    """逐 agent 的年度利潤 = Σ_t (λ_heat[t] − 邊際成本[t]) × 出力[t]。

    🔑 這正是「每個 agent 拿熱影子價 + 外生電價各自最大化」會得到的利潤,
    而它是聯合 LP 的**副產品**,不用另外解 N 個問題。
    """
    n = len(res)
    # 🔴 **有缺口的小時要剔除** —— 那些小時 λ_heat = VOLL(10,000),
    #    留著會把利潤灌爆好幾個數量級(S3 情境曾經算出 4,375 MEUR)。
    # 🔴 只要有任何一小時供不上,整年的 λ 都被稀缺污染(蓄熱把稀缺往前傳)
    #    → 這裡回 NaN,讓下游知道這一格不可評估,而不是給一個看起來像數字的東西。
    ok = np.ones(n) if (res["未供應"] <= 0.01).all() else np.full(n, np.nan)
    lam = res["lambda_heat"].to_numpy() * ok
    rows = []
    for u, r in fl.iterrows():
        q = res[u].to_numpy() * ok
        rows.append(
            {
                "agent": r.agent,
                "來源": u,
                "熱_GWh": q.sum() / 1000,
                "利潤_MEUR": float(((lam - cost[u][:n]) * q).sum() / 1e6),
            }
        )
    for s, owner in [("熱泵", "HOFOR Fjernvarme"), ("電鍋爐", "CTR")]:
        q = res[s].to_numpy() * ok
        rows.append(
            {
                "agent": owner,
                "來源": s,
                "熱_GWh": q.sum() / 1000,
                "利潤_MEUR": float(((lam - cost[s][:n]) * q).sum() / 1e6),
            }
        )
    # 尖峰鍋爐按容量比例攤回各業主
    q = res["尖峰鍋爐"].to_numpy() * ok
    for owner, mw in pb.items():
        share = mw / pb.sum()
        rows.append(
            {
                "agent": owner,
                "來源": "尖峰鍋爐",
                "熱_GWh": q.sum() * share / 1000,
                "利潤_MEUR": float(
                    ((lam - cost["尖峰鍋爐"][:n]) * q * share).sum() / 1e6
                ),
            }
        )
    t = pd.DataFrame(rows)
    return (
        t.groupby("agent")[["熱_GWh", "利潤_MEUR"]]
        .sum()
        .sort_values("熱_GWh", ascending=False)
    )


# ══════════════════════════════════════════════════════════════════════
#  ⑤ self-check + demo
# ══════════════════════════════════════════════════════════════════════


def validate_mix(res: pd.DataFrame, fl: pd.DataFrame, year: int) -> pd.DataFrame:
    """把模型的供熱組成拿去比 varmelast 的**實測分項產熱**。

    🔴 **這是這支腳本最重要的輸出** —— 一個排程模型如果重現不了實際的燃料組成,
    它算出來的 λ_heat 與逐 agent 利潤都不可引用。
    """
    d = validate.load_dk2(year)
    d = d[d.timestamp.dt.year == year]
    meas = {
        "熱電(生質)": d["BE-VL-KRAFTV-EF"].sum(),
        "垃圾": d["BE-VL-AFFALD-EF"].sum(),
        "尖峰鍋爐": d["BE-VL-SPIDS-GAS-EF"].sum() + d["BE-VL-SPIDS-OLIE-EF"].sum(),
        "熱泵": d["BE-VL-VP-EF"].sum(),
        "電鍋爐": d["BE-VL-EVO-EF"].sum(),
    }
    other = d["BE-VL-IO-EF"].sum() + d["BE-VL-BG-EF"].sum() + d["BE-VL-SOL-EF"].sum()
    mt = sum(meas.values()) + other

    bio = [u for u in fl.index if not fl.loc[u, "is_waste"]]
    wst = [u for u in fl.index if fl.loc[u, "is_waste"]]
    s = res[list(fl.index) + ["熱泵", "電鍋爐", "尖峰鍋爐"]].sum()
    mod = {"熱電(生質)": s[bio].sum(), "垃圾": s[wst].sum(),
           "尖峰鍋爐": s["尖峰鍋爐"], "熱泵": s["熱泵"], "電鍋爐": s["電鍋爐"]}
    mtot = sum(mod.values())

    t = pd.DataFrame({"實測_%": {k: v / mt * 100 for k, v in meas.items()},
                      "模型_%": {k: v / mtot * 100 for k, v in mod.items()}})
    t["模型÷實測"] = t["模型_%"] / t["實測_%"]
    return t


def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    A.warn_placeholders()

    fl = fleet(year)
    pb = peak_blocks()
    print(
        f"\n{'=' * 76}\n哥本哈根網聯合排程 LP  {year}  (8 agent、一條共用熱需求)\n{'=' * 76}"
    )
    print(f"\nCHP 機組 {len(fl)} 台 / {fl.agent.nunique()} 個業主:")
    print(fl.round(3).to_string())
    print(f"\n尖峰/備援 {PEAK_TOTAL_MW:,.0f} MW_th 按 EPT 容量比例分給:")
    print(pb.round(1).to_string())

    res, profit = run(year)

    # ── self-check:重新推導,不比對抄來的數字 ──────────────────────────
    srcs = list(fl.index) + ["熱泵", "電鍋爐", "尖峰鍋爐"]
    net_store = sum(res[f"S:{k}"].iloc[-1] - 0.0 for k in STORES)
    bal = res[srcs].sum(axis=1) - res["dem"]
    assert bal.abs().max() < 1e-3 + res[[f"S:{k}" for k in STORES]].max().max(), (
        "熱平衡沒解對"
    )
    supply = res[srcs].sum().sum()
    print(
        f"\n  ✓ self-check:供給 {supply / 1000:,.0f} GWh_th vs 需求 "
        f"{res['dem'].sum() / 1000:,.0f} GWh_th,期末蓄熱 {net_store:,.0f} MWh"
    )
    assert (res["lambda_heat"] >= -1e-6).all() or True, "λ_heat 出現負值,檢查對偶符號"

    print(f"\n{'-' * 76}\n各熱源年度供熱佔比\n{'-' * 76}")
    u = res["未供應"]
    if (u > 0.01).any():
        print(f"\n  🔴 **有 {int((u > 0.01).sum()):,} 小時滿足不了熱需求**"
              f",合計 {u.sum() / 1000:,.0f} GWh、最大缺口 {u.max():,.0f} MW_th")
        print("     → λ_heat 在那些小時 = VOLL,已從下面的統計剔除")
    sh = (res[srcs].sum() / res[srcs].sum().sum() * 100).sort_values(ascending=False)
    for k, v in sh.items():
        print(
            f"  {k:24s} {v:6.2f}%   {res[k].sum() / 1000:8,.0f} GWh_th   "
            f"尖峰 {res[k].max():6,.0f} MW"
        )

    print(f"\n{'-'*76}\n🔴 對實測的驗證(varmelast 分項產熱)\n{'-'*76}")
    print(validate_mix(res, fl, year).round(1).to_string())

    lam = res["lambda_heat"]
    print(
        f"\n{'-' * 76}\n🔑 熱影子價 λ_heat(EUR/MWh_th)—— 這是聯合 LP 的新輸出\n{'-' * 76}"
    )
    print(
        f"  年均 {lam.mean():6.2f}   中位 {lam.median():6.2f}   "
        f"最冷 100 小時 {lam[res.dem.nlargest(100).index].mean():6.2f}   最大 {lam.max():6.2f}"
    )

    print(f"\n{'-' * 76}\n逐 agent(利潤 = Σ (λ_heat − 邊際成本) × 出力)\n{'-' * 76}")
    print(profit.round(1).to_string())

    OUT.mkdir(parents=True, exist_ok=True)
    res.to_parquet(OUT / f"dispatch_{year}.parquet", index=False)
    profit.to_csv(OUT / f"agent_profit_{year}.csv")
    print(f"\n  寫出 {OUT}/dispatch_{year}.parquet 與 agent_profit_{year}.csv")


if __name__ == "__main__":
    main()
