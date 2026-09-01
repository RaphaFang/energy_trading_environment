"""階段 1 —— **裸機組**:AMV 在日前自我排程,沒有蓄熱槽。

━━━ 這一階問什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

> **在熱義務外生給定、沒有蓄熱的情況下,「每小時能選運轉點」這件事本身值多少錢?**

這是整條階梯的**底線**。它刻意不含:蓄熱(階 2)、備轉(階 3)、產出不確定性(階 4)。
🔑 **也刻意不含不平衡結算** —— 階 1 的機組可調度、熱義務已知,照投標走就不會有不平衡。
→ **因此階 1 不受「乾淨制度窗口只剩 8.6 個月」的限制**,可以用完整的 2024-07 → 2026-08。
   (研究路徑那條「把宣稱拆開」的規矩,在這裡第一次真的付現。)

━━━ 模型(抽汽式 CHP 的每小時決策)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

熱義務 Q_t 外生給定(見下面「熱義務怎麼來的」)。機組在 PQ 可行域裡選發電量 P:

    背壓線下界   P ≥ Cb·Q                 給定熱量下的最低發電量
    容量線上界   P + Cv·Q ≤ P_max         等效凝汽容量
    燃料         F = (P + Cv·Q) / η_el

每小時利潤 = p·P + λ_h·Q − c_fuel·F
           = P·(p − c_fuel/η_el) + (常數項,只跟 Q 有關)

🔑 **它對 P 是線性的 → 最適解一定在角點**,而且角點只看一個門檻:

    p > c_fuel/η_el  →  P = P_max − Cv·Q   (電價高於邊際發電成本,盡量發)
    p ≤ c_fuel/η_el  →  P = Cb·Q           (退到背壓線,只發熱逼出來的那些)

**這就是「階 1 沒有 RL 的位置」的證明** —— 決策逐期獨立、有封閉解,沒有跨期狀態。
⚠️ 熱義務 Q 是常數項,不影響 P 的選擇,但**兩台機組之間怎麼分 Q 是真的決策**
   (η 與燃料價都不同)→ 每小時仍有一個小最佳化,見 `_solve_hour()`。

━━━ 四個策略(這一階的成績單)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ① 完美預知        用實際日前價決策            = 上界(分母)
    ② 用模型 A 的預測  用 forecast.BEST 的預測價    = 真實 agent
    ③ 固定在背壓線     P = Cb·Q,永遠不選           = 沒有彈性的地板
    ④ 固定在容量線     P = P_max − Cv·Q,永遠不選   = 另一個地板

**回收率 = (② − 地板) / (① − 地板)**,地板取 ③④ 中較好的那個(對自己嚴格)。

🔑 **預期**:因為決策是個門檻,預測只在門檻附近才有影響 → 回收率應該很高。
   如果真是這樣,那就是階 1 的結論:**沒有跨期耦合時,預測誤差幾乎不花錢。**
   而階 2 加了蓄熱之後同一個量會掉多少,就是「蓄熱讓預測變得多重要」。

━━━ 🔴 熱義務怎麼來的(這是本階最大的建模假設)━━━━━━━━━━━━━━━━━━

varmelast **沒有 AMV 自己的逐時熱交付序列**(生產側只有全部熱電機組合計)。所以:

    Q_t = room_t × (AMV 該年實測年熱交付 ÷ room 該年總和),再夾到 [0, 熱容量]

    room_t = CTR+VEKS 消費 − 垃圾必發   = 可調度機組搶得到的那塊

🔑 **量是實測的(EPT `varmelev_TJ`),只有「形狀」是借來的** —— 而且是借同一張網的形狀,
   不是別的地方。self-check 會驗年總量還原得回去。
🔴 夏天 `room` 有 5.6% 的小時是負的(垃圾必發就吃掉全部需求)→ 那些小時 Q=0,
   AMV 沒有熱可賣。**結果一律分冬夏報**,不要只看年度總和。

用法:python new_src/trading/stage1_lp.py [--quick]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "new_src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = ROOT / "figs" / "trading"
ZONE = "DK2"                      # AMV 在西蘭島
SPLIT = "2024-07-01"              # 與模型 A 同一個切分,才能共用預測
SUMMER = (5, 6, 7, 8, 9)

# 兩台機組:銘牌與**實測**效率(來源見 agent_spec.py)
UNITS = {
    "AMV1": dict(fuel="wood_pellets", p_max=64.0, q_max=251.0),
    "AMV4": dict(fuel="wood_chips", p_max=150.0, q_max=400.0),
}
SPLIT_GRID = 101                  # 兩台之間分熱的網格(目標對 Q1 是分段線性 → 角點在網格上)


def _units_measured() -> pd.DataFrame:
    from agent_spec import load_units
    u = load_units()
    # 用**最後一個完整年**的實測 η;三年的散布留給敏感度掃描
    return u[u.aar == u.aar.max()].set_index("anlaeg_navn")


def build_panel(quick: bool = False) -> pd.DataFrame:
    """逐時面板:實際日前價、模型 A 的預測價、AMV 的熱義務 Q。"""
    from heat.validate import load_dk2
    h = load_dk2().set_index("timestamp").sort_index()
    h = h[["dem", "mustrun", "room", "price"]].copy()
    h["room"] = h["room"].clip(lower=0.0)          # 夏天必發過剩 → 可調度的那塊是 0

    # ── 模型 A 的預測價(BEST 設定),快取起來免得每次重跑 ──
    h["price_fc"] = _forecast_price(h.index, quick=quick)
    # 🔴 **先把用不了的小時丟掉,再解熱義務的比例** —— 反過來的話 scale 是在全部小時上
    #    解的,而評估只看得到活下來的小時,年總量就對不起來(第一版差 2.46%)。
    h = h.dropna(subset=["price", "price_fc"])

    # ── AMV 的熱義務:量用實測、形狀借 room ──
    u = _units_measured()
    q_cap = float(sum(v["q_max"] for v in UNITS.values()))
    year = int(u.aar.iloc[0])
    heat_tj = float(u.varmelev_TJ.sum()) if "varmelev_TJ" in u else np.nan
    if np.isnan(heat_tj):                           # load_units 沒帶出來就自己取
        p = pd.read_parquet(ROOT / "new_data/ept/ept_produktion_2023_2025.parquet")
        m = p[(p.selskab_navn == "HOFOR ENERGIPRODUKTION A/S") & (p.aar == year)]
        heat_tj = float(m.varmelev_TJ.sum())
    heat_mwh = heat_tj * 1000 / 3.6                 # TJ → MWh

    # 🔴 不能只用「總量比」當比例:冬季尖峰會撞到熱容量上限,夾掉之後年總量就少了
    #    (第一版少 7.1%,被 self-check ① 抓到)。改成解一個一維不動點:
    #    找 scale 使得 **夾過之後**的年總量 = EPT 實測。room ≥ 0 → 對 scale 單調 → 二分法。
    yr = h.index.year == year
    room_y = h.loc[yr, "room"].to_numpy()

    def clipped_total(sc: float) -> float:
        return float(np.minimum(room_y * sc, q_cap).sum())

    lo_s, hi_s = 0.0, 10.0
    assert clipped_total(hi_s) >= heat_mwh, "熱容量上限撐不住實測年熱交付,參數有問題"
    for _ in range(80):                              # 二分到機器精度綽綽有餘
        mid = 0.5 * (lo_s + hi_s)
        if clipped_total(mid) < heat_mwh:
            lo_s = mid
        else:
            hi_s = mid
    scale = 0.5 * (lo_s + hi_s)
    h["q_oblig"] = (h["room"] * scale).clip(upper=q_cap)
    h.attrs["scale"] = scale
    h.attrs["heat_mwh"] = heat_mwh
    h.attrs["year"] = year

    return h


def _forecast_price(idx: pd.DatetimeIndex, quick: bool = False) -> pd.Series:
    """模型 A 的 ★BEST 逐時預測。第一次跑會花幾分鐘,之後讀快取。

    🔑 **不要用實際價當預測** —— 那是策略 ①(完美預知),是分母不是 agent。
    """
    tag = "lasso" if quick else "best"
    cache = OUT / f"stage1_price_forecast_{ZONE}_{tag}.parquet"
    if cache.exists():
        s = pd.read_parquet(cache)["price_fc"]
        s.index = pd.DatetimeIndex(s.index)
        return s.reindex(idx)

    sys.path.insert(0, str(ROOT / "new_src" / "models"))
    from experiments import run
    from forecast import BEST, _features, load_training

    df = load_training(ZONE)
    feats = _features(df)
    for c in df[feats].select_dtypes("bool"):
        df[c] = df[c].astype(int)
    models = ("Lasso",) if quick else BEST["models"]
    ps = [run(df, feats, m, BEST["refit"], BEST["pooling"], BEST["target"]) for m in models]
    p = pd.concat(ps, axis=1).mean(axis=1).rename("price_fc")
    p.index = pd.DatetimeIndex(p.index)
    OUT.mkdir(parents=True, exist_ok=True)
    p.to_frame().to_parquet(cache)
    return p.reindex(idx)


# ─────────────────────────── 決策 ───────────────────────────

def _unit_arrays(u: pd.DataFrame, fuel_year: int,
                 cb_mult: float = 1.0, cv: float | None = None) -> dict:
    """每台機組的 PQ 可行域與邊際成本 —— **三個參數都要從實測推,目錄值不能直接套**。

    🔴🔴 **第一版在這裡錯了兩個地方,都是 self-check ② 抓到的**(記下來免得再犯):

    **錯誤一:兩個 η_el 是不同的東西。**
        `chp.py` 的燃料式  F = (P + Cv·Q) / η_el   裡的 η_el 是**凝汽模式**的電效率;
        EPT 量到的 `eta_el = elprod / brutto` 是**熱電聯產模式**的電效率,低得多
        (燃料同時做了熱)。把後者塞進前者的位置,燃料會被高估將近一倍。
        兩者的關係由同一條燃料式推出來:
            η_el_meas = P/F、η_th_meas = Q/F  ⇒  **η_el_cond = η_el_meas + Cv · η_th_meas**
        AMV1 0.182 + 0.14×0.772 = **0.290**;AMV4 0.270 + 0.14×0.841 = **0.388**。

    **錯誤二:`P_max` 不是銘牌電容量,是「等效凝汽容量」。**
        銘牌 64 MW_e 是**在額定熱出力下**的電出力,不是容量線的截距。
        令容量線通過銘牌點 (P=64, Q=251):  **P_max_cond = P_銘牌 + Cv · Q_銘牌**。
        不這樣接的話,銘牌點自己就落在可行域外面 —— 那正是第一版炸掉的原因。

    **Cb 用實測電熱比,不用目錄的 0.45。**
        🔑 目錄的 Cb=0.45 跟 AMV 的實測電熱比(AMV1 0.23 / AMV4 0.32)**互相矛盾**:
        Cb 是 P/Q 的**下界**,而實測的 P/Q 已經低於 0.45 → 實測點在目錄可行域外。
        熱驅動的 CHP 絕大多數時間就貼著背壓線跑,所以取 Cb = 實測電熱比。
        ⚠️ 這是**有向下偏誤的假設**(真正的 Cb 可能更低 = 彈性更大),要做敏感度掃描。

    Cv 仍然只有目錄值(背壓機組有實測母體,抽汽的 Cv 沒有)—— 這是已知的缺口。
    """
    from heat.assumptions import biomass_fuel_price_eur_mwh
    from heat.chp import dea_plant
    cv = dea_plant("wood_chips").cv if cv is None else float(cv)
    out = {}
    for name, cfg in UNITS.items():
        eta_el_meas = float(u.loc[name, "eta_el"])
        eta_th_meas = float(u.loc[name, "eta_th"])
        eta_cond = eta_el_meas + cv * eta_th_meas          # 見上面「錯誤一」
        eh = float(u.loc[name, "e_h"])                     # 實測電熱比(歷史行為)
        cb = eh * cb_mult                                  # 背壓線斜率(掃描時往下移)
        p_max_cond = cfg["p_max"] + cv * cfg["q_max"]      # 見上面「錯誤二」
        c_fuel = biomass_fuel_price_eur_mwh(fuel_year, cfg["fuel"])
        out[name] = dict(p_plate=cfg["p_max"], q_max=cfg["q_max"], p_max=p_max_cond,
                         eta_el=eta_cond, eta_el_meas=eta_el_meas, cb=cb, cv=cv,
                         eh_meas=eh, c_fuel=c_fuel, mc=c_fuel / eta_cond)
    return out


def _p_star(unit: dict, q: np.ndarray, p_signal: np.ndarray, mode: str) -> np.ndarray:
    """給定熱量 q 與**決策用的價格訊號**,回傳發電量 P(向量化)。

    可行域:  Cb·q ≤ P ≤ P_max − Cv·q
    `mode`:  'opt' 照門檻選角點;'hist' 永遠貼著**實測電熱比**;'lo' 永遠背壓線;'hi' 上界。

    🔑 **'hist' 與 'lo' 的差別是敏感度掃描的關鍵**:
       'lo' 會跟著 Cb 動(Cb 調低,地板就跟著掉,差額被灌水);
       'hist' 釘在實測電熱比上,**與參數無關** → 它才是「這座廠實際上怎麼跑」的對照組。
       所以回收率的分母一律用 'hist',不用 'lo'。
    """
    lo = unit["cb"] * q
    # 🔴 上界有**兩條**,取小的那條:
    #    ① 容量線(蒸汽路徑):P + Cv·Q ≤ P_max_cond
    #    ② 發電機銘牌:P ≤ P_銘牌 —— 不管蒸汽怎麼走,發電機就是只有那麼大。
    #    只用 ① 的話,熱義務 Q=0 的夏天會讓 AMV4 發到 206 MW_e(銘牌只有 150),
    #    夏季的彈性價值就被灌水。②在低熱時binding、①在高熱時binding。
    hi = np.minimum(unit["p_plate"], unit["p_max"] - unit["cv"] * q)
    hi = np.maximum(hi, lo)                       # 熱太多時可行域退化成一點
    if mode == "hist":
        return np.clip(unit["eh_meas"] * q, lo, hi)
    if mode == "lo":
        return lo
    if mode == "hi":
        return hi
    return np.where(p_signal > unit["mc"], hi, lo)


def _profit(unit: dict, p: np.ndarray, q: np.ndarray, price: np.ndarray) -> np.ndarray:
    """電力側毛利 = p·P − c_fuel·F。**熱收入不算** —— 熱義務外生,四個策略完全一樣,
    算進去只會在四邊加同一個常數,還會讓「回收率」的分母被稀釋。"""
    fuel = (p + unit["cv"] * q) / unit["eta_el"]
    return price * p - unit["c_fuel"] * fuel


def run_strategy(h: pd.DataFrame, units: dict, mode: str, signal: str = "price") -> pd.DataFrame:
    """在兩台機組之間掃熱量分配,取每小時最好的那個分法。

    🔑 為什麼要掃:兩台的 η_el 與燃料價都不同(AMV1 木顆粒 η 0.18、AMV4 木片 η 0.27),
    「哪一台來扛這個小時的熱」本身就是決策。目標對分配比例是**分段線性**,
    角點落在網格上,所以掃網格等於解那個小 LP(self-check 會用更細的網格驗)。
    """
    q_tot = h["q_oblig"].to_numpy()
    sig = h[signal].to_numpy()
    price = h["price"].to_numpy()                 # 結算一律用**實際**價
    a, b = units["AMV1"], units["AMV4"]

    best_pi = np.full(len(h), -np.inf)
    best = {k: np.zeros(len(h)) for k in ("p1", "q1", "p2", "q2")}
    for w in np.linspace(0.0, 1.0, SPLIT_GRID):
        q1 = np.minimum(q_tot * w, a["q_max"])
        q2 = np.minimum(q_tot - q1, b["q_max"])
        feasible = (q1 + q2) >= q_tot - 1e-6      # 分不完就不是合法分法
        p1 = _p_star(a, q1, sig, mode)
        p2 = _p_star(b, q2, sig, mode)
        pi = _profit(a, p1, q1, price) + _profit(b, p2, q2, price)
        pi = np.where(feasible, pi, -np.inf)
        take = pi > best_pi
        best_pi = np.where(take, pi, best_pi)
        for k, v in (("p1", p1), ("q1", q1), ("p2", p2), ("q2", q2)):
            best[k] = np.where(take, v, best[k])
    return pd.DataFrame({**best, "profit": best_pi}, index=h.index)


def score(h: pd.DataFrame, units: dict) -> pd.DataFrame:
    res = {
        "① 完美預知(用實際日前價)": run_strategy(h, units, "opt", "price"),
        "② 用模型 A 的預測": run_strategy(h, units, "opt", "price_fc"),
        "③ 歷史行為基準(貼實測電熱比)": run_strategy(h, units, "hist"),
        "④ 固定在容量線(無彈性)": run_strategy(h, units, "hi"),
    }
    rows = []
    floor = max(res["③ 歷史行為基準(貼實測電熱比)"].profit.sum(),
                res["④ 固定在容量線(無彈性)"].profit.sum())
    top = res["① 完美預知(用實際日前價)"].profit.sum()
    yrs = (h.index.max() - h.index.min()).days / 365.25
    sm = h.index.month.isin(SUMMER)
    # 🔴 **主指標是「比地板多賺多少」,不是毛利的絕對值。**
    #    絕對值深度為負是因為**熱收入沒算進來**而燃料全記在電這一側 —— 熱義務外生、
    #    四個策略完全相同,所以它在四邊是同一個常數,差額才是這一階要量的東西。
    for k, r in res.items():
        tot = r.profit.sum()
        rows.append({
            "策略": k,
            "比地板多賺 k€/年": (tot - floor) / yrs / 1e3,
            "冬季 k€/年": (r.profit[~sm].sum() - res["③ 歷史行為基準(貼實測電熱比)"].profit[~sm].sum()) / yrs / 1e3,
            "夏季 k€/年": (r.profit[sm].sum() - res["③ 歷史行為基準(貼實測電熱比)"].profit[sm].sum()) / yrs / 1e3,
            "回收 %": 100 * (tot - floor) / (top - floor) if top > floor else np.nan,
            "平均出力 MW_e": (r.p1 + r.p2).mean(),
        })
    return pd.DataFrame(rows), res


# ─────────────────────────── self-check ───────────────────────────

def selfcheck(h: pd.DataFrame, units: dict, res: dict) -> None:
    # ① 熱義務要還原得回 EPT 的實測年總量(形狀是借的,量必須是自己的)
    year = h.attrs.get("year")
    got = h.loc[h.index.year == year, "q_oblig"].sum()
    want = h.attrs["heat_mwh"]
    assert abs(got - want) / want < 0.01, (
        f"{year} 年熱義務還原 {got:,.0f} vs EPT 實測 {want:,.0f} MWh,差 "
        f"{100 * abs(got - want) / want:.2f}% —— 二分法沒收斂,查 room 或熱容量")

    # ② 可行域:每一格都要滿足背壓線與容量線
    for name, key in (("AMV1", ("p1", "q1")), ("AMV4", ("p2", "q2"))):
        u = units[name]
        for r in res.values():
            p, q = r[key[0]].to_numpy(), r[key[1]].to_numpy()
            assert (p >= u["cb"] * q - 1e-6).all(), f"{name} 跌破背壓線"
            assert (p + u["cv"] * q <= u["p_max"] + 1e-6).all(), f"{name} 超過容量線"
            assert (p <= u["p_plate"] + 1e-6).all(), f"{name} 超過發電機銘牌"

    # ③ 🔑 完美預知必須是上界 —— 它用實際價決策,不可能輸給任何策略
    top = res["① 完美預知(用實際日前價)"].profit.sum()
    for k, r in res.items():
        assert r.profit.sum() <= top + 1e-6, f"{k} 贏過完美預知 → 管線壞了"

    # ④ 🔑 網格夠不夠細:對抽樣的一週用 10 倍細的網格重算,差距要 <0.1%
    global SPLIT_GRID
    wk = h[(h.index >= h.index.min()) & (h.index < h.index.min() + pd.Timedelta("7D"))]
    coarse = run_strategy(wk, units, "opt", "price").profit.sum()
    SPLIT_GRID, keep = 1001, SPLIT_GRID
    fine = run_strategy(wk, units, "opt", "price").profit.sum()
    SPLIT_GRID = keep
    den = max(abs(fine), 1.0)
    assert abs(fine - coarse) / den < 1e-3, (
        f"分熱網格太粗:{keep} 點 {coarse:,.0f} vs 1001 點 {fine:,.0f}")

    # ⑤ 預測不可以偷看:預測價與實際價不該完全相同
    assert not np.allclose(h["price"], h["price_fc"]), "price_fc 等於實際價 —— 快取抓錯了"


def main(quick: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    h = build_panel(quick=quick)
    h = h[h.index >= pd.Timestamp(SPLIT, tz=h.index.tz)]
    u = _units_measured()
    units = _unit_arrays(u, int(h.attrs.get("year", u.aar.iloc[0])))
    tab, res = score(h, units)
    selfcheck(h, units, res)

    print(f"\n═══ 階段 1:裸機組(AMV1+AMV4,無蓄熱)  {h.index.min():%Y-%m-%d} → "
          f"{h.index.max():%Y-%m-%d}、{len(h):,} 小時 ═══")
    print(f"熱義務:{h.attrs['heat_mwh'] / 1e3:,.0f} GWh_th/年(EPT 實測),"
          f"中位 {h.q_oblig.median():.0f} MW_th、Q=0 的小時 "
          f"{100 * (h.q_oblig <= 0).mean():.1f}%")
    print(f"邊際發電成本:AMV1 €{units['AMV1']['mc']:.1f} / AMV4 €{units['AMV4']['mc']:.1f} /MWh_e"
          f"  (實際日前價中位 €{h.price.median():.1f})")
    print()
    print(tab.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))

    # 🔴 **一個必須講出來的循環**:策略 ③ 的「地板」是「永遠貼著背壓線跑」,
    #    而 Cb 正是用**實測電熱比**校準的 → ③ 的平均出力會**依照構造**接近實際出力。
    #    所以 ①−③ 不是「這座廠每年少賺了這麼多」,而是「若真正的 Cb 低於實測平均比,
    #    最多可能有這麼多的操作空間」。**要相信這個水準,得先掃 Cb 與 Cv 的敏感度。**
    _p = pd.read_parquet(ROOT / "new_data/ept/ept_produktion_2023_2025.parquet")
    _m = _p[(_p.selskab_navn == "HOFOR ENERGIPRODUKTION A/S") & (_p.aar == h.attrs["year"])]
    meas_mw = float(_m.elprod_TJ.sum()) * 1000 / 3.6 / 8760
    print(f"\n⚠️ EPT 實測平均電出力 {meas_mw:.1f} MW_e vs 策略③ "
          f"{(res['③ 歷史行為基準(貼實測電熱比)'].p1 + res['③ 歷史行為基準(貼實測電熱比)'].p2).mean():.1f} MW_e"
          " —— **這是構造出來的,不是驗證**(Cb 就是用實測電熱比校準的)。")
    print("   → ①−③ 的水準對 Cb / Cv 敏感,**回收 % 才是這一階穩健的產出**。")

    p = OUT / "stage1_scores.csv"
    tab.to_csv(p, index=False)
    print(f"\n✓ 寫出 {p}")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
