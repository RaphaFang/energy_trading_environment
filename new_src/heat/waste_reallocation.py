"""垃圾軸的**重分配規則校準** —— 用一次真實發生過的退場事件,測「量會流到誰身上」。

**2026-08-25 建立。這是整個 agent 互動裡唯一有實測可以校準的一環。**
設計脈絡見 `THESIS_DIRECTION.md` §13.6。

━━━ 為什麼是這支先寫 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

論文要問「某座廠退場之後,它的量由誰接走」。這個問題在**熱**那側**沒有歷史可驗**
—— 哥本哈根網 2021–2026 沒有任何主要業者退場(見 §13.6)。
但在**垃圾**那側**發生過**:2025-01-01 指定權廢除、焚化廠公司化、各市 2025-07 前完成招標,
而 EPT 逐台記錄了 2023 → 2025 的結果。

    退出 1,105 TJ  →  存活機組多燒 965 TJ  →  全國淨變 −140 TJ(−0.4%)
    **吸收率 87%。**

🔴 **2026-08-25 跑完的結論:校準失敗,而且失敗的方式本身是結果。**

    · 五條分配規則**全部**分不出勝負(最好的 R1 只解釋 7.7% 變異)—— 訊號/雜訊 0.20,
      **是「檢定不出來」不是「規則被否證」**。
    · **LP(成本最佳化)被決定性否證** —— 誤差是 naive 的 3.6 倍,而且它預測
      **12 台歸零、單台動 1,303 TJ**;實測 **0 台歸零、最大只動 372 TJ**。
      加上契約下界(誰都不准比 2023 少燒)也救不回來(β=1.0 時 MAE 仍 143 vs naive 96)。
    · 實測最接近的是 **R1 按現有規模等比例成長** —— **大家都長一點,不是最好的吃光。**

🔑 **LP 為什麼一定會壞:線性目標在多面體上必落於頂點 = 贏者全拿。**
   而它缺的不是求解技巧,是**來源側** —— 每個 I/S 服務的是自己的會員市,
   垃圾從哪來決定它能去哪。沒有「逐市垃圾產生量 + 運距」就無法識別,而那份資料不在手上。
   → **垃圾軸做不成最佳化模型,只能做描述性的。**

🔑 **這個失敗不會傳染到熱側**,理由是結構性的而不是安慰話:
   熱側**沒有來源側問題**(一張網、一條熱需求、管線實體相連),
   而且 **Varmelast 的職責明文就是按成本排序** —— 在熱側「贏者全拿」是**制度規定的正確行為**。

📌 **所以垃圾軸的角色要改**:不是「校準規則的訓練場」,而是一個**關於政策的觀察** ——
   **指定權廢除三年後,垃圾在焚化廠之間仍然沒有依成本重新分配。**

━━━ 🔴 一個一定要用機組唯一碼的理由(踩過了) ━━━━━━━━━━━━━━━━━━━━

用 `selskab_navn`(公司名)判定退場會**憑空生出一座關掉的廠**:

    I/S KRAFTVARMEVÆRK THISTED   572 TJ (2023) → 0 (2025)      ← 看起來關了
    THISTED VARMEFORSYNING AMBA    0 TJ (2023) → 639 (2025)    ← 其實是同一台

`vrkanl_ny = 699-1`、`anlaeg_navn = "I/S Kraftvarmeværk Thisted"`、容量 16.3 MW
**三個欄位完全相同** —— 那不是關廠,是 **2025-01-01 公司化**把資產換了法人。
🔑 **公司名會變,機組碼不會。退場判定一律用 `vrkanl_ny`。**
(這與記憶 `ept-national-fleet` 早就寫的「唯一識別碼是 `vrkanl_ny`」是同一條,
 只是先前只用在「機組名不唯一」的情境,沒想到公司名也會漂。)

差別:公司級判定 1,530 TJ vs 機組級 1,105 TJ,**多算 38%**,而且方向是誇大退場規模。

━━━ 規則家族 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

被騰出來的量 `D` 要分給存活機組。五條規則,各自對應一種現實機制:

    R0  不重分配        誰也不多燒(虛無假設,拿來當地板)
    R1  按現有量比例    大廠吃大口 —— 現狀延續
    R2  按容量餘裕      有空間的先吃 —— 物理限制主導
    R3  按效率排序      總效率高的先吃飽 —— 成本競爭主導(招標的形式)
    R4  區域優先        同一地區先吃,溢出才跨區 —— 運輸成本主導

**每條規則都只分配「實際被吸收的總量」`A`**,因為我們要測的是**分佈**不是水準
—— 水準受垃圾進口、分類率等外生因素影響,不是重分配規則能決定的。

━━━ ⚠️ 這個校準的限制(論文一定要寫) ━━━━━━━━━━━━━━━━━━━━━━━━━

- **樣本 = 4 台退出、3 年、36 台存活。** 只能區分粗糙的規則家族,**定不出精細參數**。
- **存活機組的量本來就會自己動**(合約、歲修、垃圾進口),那是雜訊,不是重分配。
- **2024 是過渡年**(SK Varme 475→174→0 是分兩年退的),所以只比 2023 與 2025 兩端。
- `indfyretkapacitet_MW` 是**額定輸入容量**,乘 8,760 小時是理論上限;
  真實可用率約 85–90%,所以「餘裕」是上界。

用法:python new_src/heat/waste_reallocation.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EPT = ROOT / "new_data/ept/ept_produktion_2023_2025.parquet"
OUT = ROOT / "figs/waste_reallocation"

Y0, Y1 = 2023, 2025
TJ_PER_MW_YEAR = 8760 * 3.6 / 1000  # MW → TJ/年(100% 可用率,是上界)
MWH_PER_TJ = 1000 / 3.6

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assumptions as A  # noqa: E402

# 垃圾對焚化廠是**收入**不是成本(收處理費),所以取負號
A_WASTE_REV = -A.waste_fuel_price_eur_mwh()          # EUR/MWh_fuel,正值
A_THETA_H = A.dkk_gj_to_eur_mwh_th(A.waste_heat_tax_dkk_gj(2026))  # EUR/MWh_th


# ══════════════════════════════════════════════════════════════════════
#  ① 讀資料 —— 機組級,鍵是 vrkanl_ny
# ══════════════════════════════════════════════════════════════════════


def panel() -> pd.DataFrame:
    """每台燒垃圾的機組一列,帶 2023/2025 的垃圾投入、容量、效率、地區。"""
    p = pd.read_parquet(EPT)
    w = p[p["affald_TJ"].fillna(0) > 0].copy()

    piv = w.pivot_table(
        index="vrkanl_ny", columns="aar", values="affald_TJ", aggfunc="sum"
    ).fillna(0.0)
    for y in (Y0, Y1):
        if y not in piv.columns:
            raise KeyError(f"EPT 沒有 {y} 年的資料,只有 {list(piv.columns)}")

    # 屬性取最近一年有值的那筆(公司名會漂,所以取最新的)
    attr = (
        w.sort_values("aar")
        .drop_duplicates("vrkanl_ny", keep="last")
        .set_index("vrkanl_ny")
    )

    # 佔用的是**全燃料**投入,不是垃圾單獨 —— 餘裕要用全燃料算
    brutto = w.pivot_table(
        index="vrkanl_ny", columns="aar", values="brutto_TJ", aggfunc="sum"
    ).fillna(0.0)

    d = pd.DataFrame(
        {
            "affald_y0": piv[Y0],
            "affald_y1": piv[Y1],
            "brutto_y0": brutto[Y0],
            "kap_MW": attr["indfyretkapacitet_MW"],
            "varmelev": attr["varmelev_TJ"],
            "ellev": attr["ellev_TJ"],
            "selskab": attr["selskab_navn"],
            "sted": attr["vaerk_postdistrikt"],
            "postnr": pd.to_numeric(attr["vaerk_postnr"], errors="coerce"),
            "net": attr["fv_net_navn"],
        }
    )
    d["kap_TJ"] = d["kap_MW"] * TJ_PER_MW_YEAR
    d["headroom"] = (d["kap_TJ"] - d["brutto_y0"]).clip(lower=0)
    # 總效率當「成本競爭」的代理 —— EPT 沒有成本,但效率高的每噸賺得多
    tot = attr["brutto_TJ"].replace(0, np.nan)
    d["eta_th"] = (attr["varmelev_TJ"] / tot).fillna(0)
    d["eta_el"] = (attr["ellev_TJ"] / tot).fillna(0)
    d["eta_tot"] = d["eta_th"] + d["eta_el"]
    d["region"] = d["postnr"].map(_region)
    return d


def network_heat(year: int = Y0) -> pd.Series:
    """每張熱網在 `year` 的熱交付總量(TJ)—— LP 的熱網吸收上限。

    ⚠️ 用**基準年**不用目標年,否則等於把答案餵給模型。
    """
    p = pd.read_parquet(EPT)
    return p[p["aar"] == year].groupby("fv_net_navn")["varmelev_TJ"].sum()


def area_prices(year: int = Y0) -> dict:
    """DK1 / DK2 在 `year` 的年均日前電價(EUR/MWh_e)。"""
    out = {}
    for a in ("dk1", "dk2"):
        (f,) = (ROOT / "new_data/price").glob(f"price_{a}_*.parquet")
        s = pd.read_parquet(f)
        s = s[s["HourUTC"].dt.year == year]["SpotPriceEUR"]
        out[a.upper()] = float(s.mean())
    return out


def _region(z) -> str:
    """郵遞區號 → 粗略地區。⚠️ 這是代理不是真實運距。"""
    if pd.isna(z):
        return "?"
    z = int(z)
    for hi, name in [
        (2999, "Storkøbenhavn"),
        (4999, "Sjælland/øer"),
        (5999, "Fyn"),
        (6999, "Sydjylland"),
        (7999, "Midt/Vestjylland"),
        (8999, "Østjylland"),
        (9999, "Nordjylland"),
    ]:
        if z <= hi:
            return name
    return "?"


def split(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """退出的機組 / 存活的機組。**退出 = 這台機組碼在 y1 不再燒垃圾。**"""
    exited = d[(d.affald_y0 > 0) & (d.affald_y1 == 0)]
    surv = d[(d.affald_y0 > 0) & (d.affald_y1 > 0)].copy()
    return exited, surv


# ══════════════════════════════════════════════════════════════════════
#  ② 規則家族 —— 每條回一個「存活機組 → 分到多少 TJ」的序列
# ══════════════════════════════════════════════════════════════════════


def _prorata(weight: pd.Series, total: float) -> pd.Series:
    w = weight.clip(lower=0)
    return w * total / w.sum() if w.sum() > 0 else w * 0


def _fill_by_rank(surv: pd.DataFrame, total: float, order: pd.Series) -> pd.Series:
    """按 `order` 由高到低,依序把餘裕填滿,直到 total 分完(招標式的貪婪配置)。"""
    got = pd.Series(0.0, index=surv.index)
    left = total
    for i in order.sort_values(ascending=False).index:
        if left <= 0:
            break
        take = min(surv.at[i, "headroom"], left)
        got[i] = take
        left -= take
    return got


def rules(
    surv: pd.DataFrame, exited: pd.DataFrame, total: float
) -> dict[str, pd.Series]:
    """五條規則。`total` = 要分配掉的量(用實測吸收量,見模組 docstring)。"""
    r = {
        "R0 不重分配": pd.Series(0.0, index=surv.index),
        "R1 按現有量比例": _prorata(surv.affald_y0, total),
        "R2 按容量餘裕": _prorata(surv.headroom, total),
        "R3 按效率排序": _fill_by_rank(surv, total, surv.eta_tot),
    }

    # R4 區域優先:退出量先分給同區的存活機組(按餘裕),溢出的才進全國池
    got = pd.Series(0.0, index=surv.index)
    overflow = 0.0
    for reg, grp in exited.groupby("region"):
        share = grp.affald_y0.sum() / exited.affald_y0.sum() * total
        local = surv[surv.region == reg]
        cap = local.headroom.sum()
        if cap <= 0:
            overflow += share
            continue
        take = min(share, cap)
        got.loc[local.index] += _prorata(local.headroom, take)
        overflow += share - take
    if overflow > 0:
        rest = (surv.headroom - got).clip(lower=0)
        got += _prorata(rest, overflow)
    r["R4 區域優先"] = got
    return r


# ══════════════════════════════════════════════════════════════════════
#  ③ 評分
# ══════════════════════════════════════════════════════════════════════


def lp_allocation(
    surv: pd.DataFrame,
    total_after: float,
    net_heat: pd.Series,
    p_heat: float,
    p_el: dict,
    rho: float = 1.0,
    avail: float = 1.0,
) -> pd.Series:
    """🔑 **LP 版的分配** —— 與規則的差別**不在於它是最佳化,而在於它多一條約束**。

    只有「總量守恆 + 容量上限」的 LP,數學上**等於貪婪的成本排序**(= R3),不是新東西。
    真正讓它不一樣的是**熱網吸收約束**:

        焚化廠能燒多少,不只受爐子限制,還受「它的熱網吃不吃得下那些熱」限制。

    R2 用的是**燃料容量餘裕**,所以判 ARC 餘裕 = 0(爐子滿了)→ 猜它不可能多燒。
    但 ARC 在哥本哈根,那張網只有 29% 的熱來自垃圾 → **網有空間**,它實際多燒 372 TJ。
    反過來 Maabjerg 爐子餘裕 1,846 TJ 全國最大,但它的網已經 62% 是垃圾熱 → 只多燒 121。

        max  Σᵢ xᵢ·mᵢ
        s.t. Σᵢ xᵢ = W                            全國可燒的垃圾總量
             xᵢ ≤ 爐子餘裕ᵢ                        (額定×8760×可用率 − 其他燃料)
             Σ_{i∈n} xᵢ·η_thᵢ ≤ ρ·H_n   ∀ 網 n     🔑 熱網吸收上限
             xᵢ ≥ 0

    每 MWh 垃圾的邊際利潤:

        mᵢ = 處理費收入 + η_thᵢ·(熱價 − θ_h) + η_elᵢ·電價(該區)

    ⚠️ `H_n` 用**基準年**的網熱交付,不用目標年 —— 否則等於偷看答案。
    ⚠️ `p_heat`(熱對該網的價值)全國一律,是簡化;真值逐網不同,拿來掃描。
    """
    from scipy.optimize import linprog

    idx = list(surv.index)
    n = len(idx)
    eta_th = surv.eta_th.reindex(idx).fillna(0).to_numpy()
    eta_el = surv.eta_el.reindex(idx).fillna(0).to_numpy()
    area = surv.postnr.map(lambda z: "DK2" if pd.notna(z) and z <= 4999 else "DK1")

    # 每 TJ 垃圾的邊際利潤(EUR)。1 TJ = 277.78 MWh
    margin = np.array(
        [
            (
                A_WASTE_REV
                + eta_th[k] * (p_heat - A_THETA_H)
                + eta_el[k] * p_el[area.iloc[k]]
            )
            * 277.78
            for k in range(n)
        ]
    )

    cap = (
        surv.kap_TJ.to_numpy() * avail
        - surv.brutto_y0.to_numpy()
        + surv.affald_y0.to_numpy()
    ).clip(min=0)  # 其他燃料照舊,餘裕給垃圾

    A_ub, b_ub = [], []
    for net, grp in surv.groupby("net"):
        if net not in net_heat.index:
            continue
        row = np.zeros(n)
        for j in grp.index:
            row[idx.index(j)] = eta_th[idx.index(j)]
        A_ub.append(row)
        b_ub.append(rho * float(net_heat[net]))

    res = linprog(
        c=-margin,
        A_ub=np.array(A_ub) if A_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=np.ones((1, n)),
        b_eq=[total_after],
        bounds=[(0, c) for c in cap],
        method="highs",
    )
    if not res.success:
        raise RuntimeError(
            f"LP 無解:{res.message}\n"
            "→ 通常是熱網吸收上限 + 爐子容量加起來裝不下 W,檢查 rho/avail"
        )
    return pd.Series(res.x, index=idx)


def power(surv: pd.DataFrame, absorbed: float) -> dict[str, float]:
    """🔴 **先量檢定力,再看規則對不對。**

    「規則被否證」與「檢定不出來」是兩件事(見 `THESIS_DIRECTION.md` §10 第 12 條)。
    要分配的量攤到每台機組,如果比機組自己的年際波動還小,**任何規則都測不出來**。
    """
    delta = surv.affald_y1 - surv.affald_y0
    signal = absorbed / len(surv)
    return {
        "訊號_TJ每台": signal,
        "雜訊_Δ標準差": float(delta.std()),
        "訊號雜訊比": signal / float(delta.std()),
    }


def by_region(
    surv: pd.DataFrame, exited: pd.DataFrame, absorbed: float
) -> pd.DataFrame:
    """區域級檢定 —— 聚合掉機組級的雜訊之後,吸收是不是在地的?

    兩個對立假設:
      在地   該區退出的量,由**該區**的存活機組吸收
      全國   不分地區,按存活機組的規模在全國攤平
    """
    lost = exited.groupby("region").affald_y0.sum()
    gained = (surv.affald_y1 - surv.affald_y0).groupby(surv.region).sum()
    size = surv.groupby("region").affald_y0.sum()
    rate = absorbed / exited.affald_y0.sum()

    t = pd.DataFrame(
        {"退出_TJ": lost, "存活台數": surv.groupby("region").size(), "實測Δ_TJ": gained}
    ).fillna(0.0)
    t["在地預測"] = (t["退出_TJ"] * rate).fillna(0.0)
    t["全國預測"] = size / size.sum() * absorbed
    t["在地誤差"] = (t["在地預測"] - t["實測Δ_TJ"]).abs()
    t["全國誤差"] = (t["全國預測"] - t["實測Δ_TJ"]).abs()
    return t


def score(surv: pd.DataFrame, pred: dict[str, pd.Series]) -> pd.DataFrame:
    """對每條規則,比「預測的增量」與「實測的增量」。"""
    actual = surv.affald_y1 - surv.affald_y0
    rows = []
    for name, p in pred.items():
        err = p - actual
        ss_res = float((err**2).sum())
        ss_tot = float(((actual - actual.mean()) ** 2).sum())
        rows.append(
            {
                "規則": name,
                "MAE_TJ": float(err.abs().mean()),
                "RMSE_TJ": float(np.sqrt((err**2).mean())),
                "R2": 1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
                "corr": float(np.corrcoef(p, actual)[0, 1]) if p.std() > 0 else np.nan,
                "最大單台誤差_TJ": float(err.abs().max()),
            }
        )
    return pd.DataFrame(rows).sort_values("MAE_TJ").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════
#  ④ self-check —— 重新推導,不比對抄來的數字
# ══════════════════════════════════════════════════════════════════════


def _self_check(d: pd.DataFrame, exited: pd.DataFrame, surv: pd.DataFrame) -> None:
    nat0, nat1 = d.affald_y0.sum(), d.affald_y1.sum()
    absorbed = (surv.affald_y1 - surv.affald_y0).sum()
    # 全國淨變 = 存活的增量 − 退出的量(沒有新進機組時恆等)
    assert abs((absorbed - exited.affald_y0.sum()) - (nat1 - nat0)) < 1.0, (
        "帳對不起來:存活增量 − 退出量 ≠ 全國淨變 → 可能有新進機組沒被歸類"
    )
    new = d[(d.affald_y0 == 0) & (d.affald_y1 > 0)]
    assert len(new) == 0, f"出現 {len(new)} 台新機組,上面那條恆等式要改寫"

    # 🔴 防迴歸:Thisted 那台不可以被判成退出(公司名漂移,不是關廠)
    thisted = d[d.sted.astype(str).str.contains("Thisted", na=False)]
    assert (thisted.affald_y1 > 0).any(), (
        "Thisted 被判成退出了 —— 退場判定又用回公司名了,見模組 docstring"
    )
    print("  ✓ self-check:帳平、無新進機組、Thisted 未被誤判為退出")


def main() -> None:
    d = panel()
    exited, surv = split(d)
    absorbed = float((surv.affald_y1 - surv.affald_y0).sum())

    print(f"\n{'=' * 72}\n垃圾軸重分配校準  {Y0} → {Y1}  (EPT,機組級)\n{'=' * 72}")
    print(f"\n燒垃圾的機組 {len(d)} 台 → 退出 {len(exited)} 台 / 存活 {len(surv)} 台")
    print(f"\n退出的機組:")
    print(
        exited[["selskab", "sted", "region", "affald_y0"]]
        .sort_values("affald_y0", ascending=False)
        .to_string(index=False, float_format=lambda x: f"{x:,.0f}")
    )
    D = float(exited.affald_y0.sum())
    print(f"\n  騰出來的量 D          = {D:8,.0f} TJ")
    print(f"  存活機組實際多燒 A     = {absorbed:8,.0f} TJ")
    print(f"  吸收率 A/D            = {absorbed / D:8.0%}")
    print(
        f"  全國 {Y0} → {Y1}        = {d.affald_y0.sum():,.0f} → {d.affald_y1.sum():,.0f} TJ "
        f"({d.affald_y1.sum() / d.affald_y0.sum() - 1:+.1%})"
    )

    _self_check(d, exited, surv)

    pw = power(surv, absorbed)
    print(f"\n{'-' * 72}\n🔴 先量檢定力(規則對不對之前要先問測不測得出來)\n{'-' * 72}")
    print(f"  要分配的訊號   {pw['訊號_TJ每台']:8,.1f} TJ/台")
    print(f"  機組年際波動   {pw['雜訊_Δ標準差']:8,.1f} TJ(存活機組 Δ 的標準差)")
    print(f"  訊號/雜訊      {pw['訊號雜訊比']:8.2f}")
    if pw["訊號雜訊比"] < 0.5:
        print("  🔴 **機組級檢定沒有 power** —— 下面任何規則贏不了地板,都不代表規則錯,")
        print("     只代表這個事件的規模測不出來。**不可以宣稱某條規則被否證。**")

    pred = rules(surv, exited, absorbed)
    pred["R_平均攤(naive)"] = pd.Series(absorbed / len(surv), index=surv.index)

    # LP:預測的是**水準** x[i],轉成增量才能跟規則比。總量鎖成與實測相同。
    nh, pel = network_heat(Y0), area_prices(Y0)
    W = float(surv.affald_y1.sum())
    for ph in (20.0, 30.0, 40.0):
        x = lp_allocation(surv, W, nh, p_heat=ph, p_el=pel)
        pred[f"LP 熱價={ph:.0f}"] = x - surv.affald_y0
    tab = score(surv, pred)
    print(
        f"\n{'-' * 72}\n規則比較(分配總量固定 = 實測吸收量 {absorbed:,.0f} TJ,所以比的是分佈)\n{'-' * 72}"
    )
    print(tab.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    best = tab.iloc[0]
    print(f"\n  → MAE 最小:{best['規則']}({best['MAE_TJ']:,.0f} TJ/台)")
    print(
        f"  → 地板(R0 不重分配)MAE = "
        f"{tab.loc[tab['規則'].str.startswith('R0'), 'MAE_TJ'].iloc[0]:,.0f} TJ/台"
    )

    reg = by_region(surv, exited, absorbed)
    print(f"\n{'-' * 72}\n區域級檢定(聚合掉機組雜訊之後,吸收是不是在地的?)\n{'-' * 72}")
    print(reg.to_string(float_format=lambda x: f"{x:,.0f}"))
    print(
        f"\n  在地假設 平均誤差 {reg['在地誤差'].mean():,.0f} TJ  |  "
        f"全國假設 平均誤差 {reg['全國誤差'].mean():,.0f} TJ"
    )
    won = "在地" if reg["在地誤差"].mean() < reg["全國誤差"].mean() else "全國"
    print(
        f"  → **{won}**假設較接近實測(⚠️ 只有 {len(reg)} 個地區、3 個有退出,方向可信、數值不可引用)"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    reg.to_csv(OUT / "region_test.csv")
    tab.to_csv(OUT / "rule_scores.csv", index=False)
    detail = surv[
        [
            "selskab",
            "sted",
            "region",
            "affald_y0",
            "affald_y1",
            "kap_MW",
            "headroom",
            "eta_tot",
        ]
    ].copy()
    detail["實測Δ"] = surv.affald_y1 - surv.affald_y0
    for name, p in pred.items():
        detail[name] = p
    detail.sort_values("實測Δ", ascending=False).to_csv(OUT / "survivor_detail.csv")
    print(
        f"\n  寫出 {OUT}/ 下三個檔:rule_scores.csv、region_test.csv、survivor_detail.csv"
    )

    print(f"\n{'-' * 72}\n⚠️ 限制(論文照抄)\n{'-' * 72}")
    print("  · 樣本 = 4 台退出 / 36 台存活 / 3 年 → 只能分規則家族,定不出參數")
    print("  · 存活機組的量本來就會自己動(合約、歲修、垃圾進口),那是雜訊")
    print("  · 餘裕用額定容量 × 8,760h 算,是上界(真實可用率約 85–90%)")
    print("  · 地區是郵遞區號代理,不是真實運距")


if __name__ == "__main__":
    sys.exit(main())
