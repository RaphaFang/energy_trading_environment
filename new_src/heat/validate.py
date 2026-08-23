"""用 varmelast 的**分項產熱**驗 `chp.py` 的排程行為 —— 不是驗熱需求水準,是驗**時點**。

為什麼需要這個檔:先前的驗證都停在「水準對不對」(年佔比、單位供熱成本)。
但 2026-08-05 的教訓是**驗證要挑有識別力的標的**,而水準這個標的識別力很弱 ——
本檔第一個結果就證明了這件事:**尖峰鍋爐的年佔比對得極好(模型 5.95% vs 實測 5.12%),
但日內時點的符號是反的**。只看年佔比會誤判成「模型驗證通過」。

`BE-VL-*-EF` 的分類幾乎一對一對應 LP 的變數區塊,所以可以逐項對照:

    BE-VL-KRAFTV-EF     熱電產熱        ↔  Qc
    BE-VL-AFFALD-EF     垃圾焚化產熱    ↔  Qc(背壓式機組)
    BE-VL-SPIDS-GAS-EF  尖峰氣鍋爐      ↔  Qpb
    BE-VL-EVO-EF        電鍋爐          ↔  Qe
    BE-VL-VP-EF         熱泵            ↔  Qh

🔴 **三個診斷刻意都是「尺度無關」的**(相關係數、開機率、ΔR²),不是水準。
   理由:DK2 六台機組只有 2 台跑得動(生質燃料價缺,見 `dk2_fleet.runnable()`),
   所以模型端**不可能**在水準上重現 DK2 車隊。但行為簽名可以比,而且更有識別力。

## 三個診斷,以及各自擋掉什麼假象

① `day_fe_response()` — **日固定效果**回歸,同時控制日內熱需求變動。
   識別來源 = 同一天各小時的價格差。這擋掉**季節性**:垃圾與 CHP 在原始資料上
   「高價時出力更高」,但那純粹是冬天同時有高需求與高價,同日內看符號是反的。
   (這正是 2026-08-05 那次「用 CHP 發電量驗熱需求代理」踩的同一個坑。)

② `intraday_rho()` — 先移除「月×時」平均日內形狀,再做日內 Spearman。
   這擋掉**兩條固定形狀互相對齊**的假象:電價與熱需求各自有穩定的日內形狀,
   直接相關會把「形狀碰巧錯開」讀成價格反應。移除後垃圾從 −0.190 衰減到 −0.100,
   電鍋爐只從 −0.409 到 −0.261 → 電鍋爐的反應是真的,垃圾那個大半是形狀假象。

③ `daily_decomp()` — 日總量分別對「當日均價」與「當日熱需求」做 Spearman。
   這回答的是**價格決定「開多少」還是「在哪幾小時開」**。結果:實測是熱需求決定量
   (ρ=+0.42)、價格只決定時點(ρ=−0.25);LP 則完全相反(ρ=−0.84 對價格、≈0 對需求)。

用法:python new_src/heat/validate.py    (實測簽名 + LP 對照 + self-check)
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(__file__))

VARMELAST = "new_data/heat/varmelast_ckb_2021_2026.parquet"


def _one(pattern: str) -> str:
    """檔名裡帶抓取窗口 → **不能寫死**。glob 之後**強制唯一**。

    🔴 2026-08-21 修:窗口改成「2019 → 今天」之後,原本寫死的
    `price_dk2_2019-01-01_2026-07-08.parquet` 直接不存在,`load_dk2()` 全掛。
    但**不要退回 `glob(...)[0]`** —— `data/window.py` 的 docstring 講得很清楚:
    舊檔沒退場時取 `[0]` 會**靜默拿到舊檔**。寧願炸也不要靜默換掉資料。
    """
    import glob as _glob

    fs = sorted(_glob.glob(pattern))
    assert len(fs) == 1, (
        f"{pattern} 匹配到 {len(fs)} 個檔:{fs}\n"
        "  0 個 → 資料還沒抓;>1 個 → 舊檔沒退場,見 new_src/data/window.py 的 retire_superseded()"
    )
    return fs[0]


PRICE_H = _one("new_data/price/price_dk2_*.parquet")
PRICE_15 = _one("new_data/price/price15_dk2_*.parquet")

# 消費欄(唯一可當 LP 輸入的兩欄,見 data/varmelast_heat.py)
DEMAND_COLS = ["BE-EO-CTR-EFF", "DAP-VEKS-FORBRUG-EFF"]

# 生產分項 → LP 變數區塊。**只列對得上的**;BE-VL-TOTAL-FAK 是 CO2 排放強度不是熱量,
# 絕不能進來(那是舊記錄 64.4/27.3 佔比錯誤的成因)。
SOURCES = {
    "BE-VL-KRAFTV-EF": ("熱電 CHP", "Qc"),
    "BE-VL-AFFALD-EF": ("垃圾焚化", "Qc(背壓)"),
    "BE-VL-SPIDS-GAS-EF": ("尖峰氣", "Qpb"),
    "BE-VL-SPIDS-OLIE-EF": ("尖峰油", "Qpb"),
    "BE-VL-EVO-EF": ("電鍋爐", "Qe"),
    "BE-VL-VP-EF": ("熱泵", "Qh"),
    "BE-VL-IO-EF": ("工業餘熱", "(無對應)"),
}

# 必發:不由電價決定的產熱,拿來算「還剩多少空間可以放 power-to-heat」
MUSTRUN_COLS = ["BE-VL-AFFALD-EF", "BE-VL-IO-EF", "BE-VL-BG-EF", "BE-VL-OD-EF"]


def load_dk2(year_from: int = 2021) -> pd.DataFrame:
    """varmelast 分項 + DK2 電價 + 燃料價/氣溫,逐時對齊。

    電價**跨越 2025-09-30 的制度改變**:逐時 `Elspotprices` 到 2025-09-30 21:00 UTC,
    之後接 15 分鐘的 `DayAheadPrices`。價格是**強度量** → 聚合成逐時用 `mean` 不是 `sum`
    (見 README 的「已知的坑」)。兩份檔案間隙 0 分鐘、無重疊,所以直接接起來。

    燃料價與氣溫來自 `energy.duckdb`(缺就留 NaN,不編值)。
    """
    v = pd.read_parquet(VARMELAST)
    v["timestamp"] = pd.to_datetime(v["timestamp"], utc=True)

    ph = pd.read_parquet(PRICE_H)
    ph["t"] = pd.to_datetime(ph["HourUTC"], utc=True)
    ph = ph[["t", "SpotPriceEUR"]].rename(columns={"SpotPriceEUR": "price"})
    p15 = pd.read_parquet(PRICE_15)
    p15["t"] = pd.to_datetime(p15["TimeUTC"], utc=True)
    # 🔴 mean 不是 sum:價格是強度量
    p15 = (
        p15.set_index("t")["DayAheadPriceEUR"]
        .resample("1h")
        .mean()
        .rename("price")
        .reset_index()
    )
    cut = p15["t"].min()
    price = pd.concat([ph[ph["t"] < cut], p15]).sort_values("t")
    assert not price["t"].duplicated().any(), "逐時與 15 分鐘電價有重疊"

    d = v.merge(price, left_on="timestamp", right_on="t", how="left").drop(columns="t")
    d["dem"] = d[DEMAND_COLS].sum(axis=1)
    d["mustrun"] = d[MUSTRUN_COLS].sum(axis=1)
    d["room"] = d["dem"] - d["mustrun"]  # 還能放多少非必發的熱
    d["day"] = d["timestamp"].dt.floor("D")
    d["hm"] = d["timestamp"].dt.month * 100 + d["timestamp"].dt.hour

    if os.path.exists("new_data/energy.duckdb"):
        import duckdb

        con = duckdb.connect("new_data/energy.duckdb", read_only=True)
        f = con.execute(
            "select timestamp_utc as t, ttf_gas_eur_mwh as gas, "
            "eua_co2_eur_t as co2, temperature_2m as tair "
            "from training where area='DK2' order by t"
        ).fetchdf()
        con.close()
        f["t"] = pd.to_datetime(f["t"], utc=True)
        d = d.merge(f, left_on="timestamp", right_on="t", how="left").drop(columns="t")
        # ⚠️ 燃料價是日頻、氣溫偶有缺 → ffill 是合理的;但**不做 fillna(常數)**,
        #    duckdb 右界之後真的沒有資料,讓它留 NaN 由呼叫端決定要不要用。
        d[["gas", "co2", "tair"]] = d[["gas", "co2", "tair"]].ffill()

    d = d[d["timestamp"].dt.year >= year_from].reset_index(drop=True)
    assert d["price"].notna().all(), (
        f"有 {d['price'].isna().sum()} 小時沒有電價 —— 檢查兩份價格檔的銜接"
    )

    # 🔴 **消費側量測中斷被記成 0,不是真的沒有熱需求**(2026-08-12 發現):
    #    2024-04-01 08:00 → 04-02 22:00 連續 39 小時,`BE-EO-CTR-EFF` 與
    #    `DAP-VEKS-FORBRUG-EFF` **同時恰好為 0**,而生產欄完全正常
    #    (TOTAL 均 1,381 MW_th、熱電 917、垃圾 281)—— 熱網不可能在供暖季停擺兩天。
    #    只佔 0.08%,但它會毀掉任何用到最小值/分位數的東西
    #    (例:`chp.solve(committed=True)` 會因為「熱需求 0」而無解)。
    # ⚠️ 清理**在分析層做,不動 parquet**(專案慣例:原始資料存 raw)。
    bad = (d["dem"] <= 0) & (d["TOTAL"] > 0)
    d["demand_outage"] = bad
    if bad.any():
        d = d[~bad].reset_index(drop=True)
    return d


def _demean(d: pd.DataFrame, col: str, by: str) -> np.ndarray:
    return (d[col] - d.groupby(by)[col].transform("mean")).to_numpy(float)


def day_fe_response(d: pd.DataFrame, col: str, price: str = "price") -> dict:
    """診斷① 日固定效果 + 控制日內熱需求變動,看價格係數與 ΔR²。

    ΔR² 才是重點,不是係數大小:它回答「知道價格對預測這個來源的出力有多少幫助」。
    2026-08-05 的教訓就是係數看起來顯著、ΔR² 卻是 0.0005。
    """
    y = _demean(d, col, "day")
    P = _demean(d, price, "day")
    D = _demean(d, "dem", "day")
    ones = np.ones(len(d))

    def fit(X):
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ b
        return b, e @ e

    _, ss0 = fit(np.column_stack([ones, D]))
    X1 = np.column_stack([ones, D, P])
    b1, ss1 = fit(X1)
    tss = y @ y
    dof = len(y) - X1.shape[1]
    se = np.sqrt((ss1 / dof) * np.linalg.inv(X1.T @ X1)[-1, -1])
    return dict(beta=b1[-1], t=b1[-1] / se, d_r2=(ss0 - ss1) / tss)


def intraday_rho(d: pd.DataFrame, col: str, price: str = "price") -> dict:
    """診斷② 移除「月×時」平均日內形狀後,逐日算 Spearman(電價, 出力),回傳中位數。

    為什麼要移除形狀:電價與各熱源都有穩定的日內形狀,直接相關等於在比兩條
    固定曲線對不對齊,而不是在比「這一天價格比較高的那幾小時,它有沒有少跑」。
    """
    t = d[["day", "hm", price, col]].copy()
    t["pr"] = _demean(t, price, "hm")
    t["yr"] = _demean(t, col, "hm")
    r = []
    for _, g in t.groupby("day"):
        # 當天完全沒跑、或價格/出力沒有變異 → 這一天沒有識別力,跳過(不是補 0)
        if g[col].sum() < 5 or g["pr"].std() < 1e-6 or g["yr"].std() < 1e-9:
            continue
        r.append(spearmanr(g["pr"], g["yr"]).statistic)
    r = np.asarray(r, float)
    r = r[~np.isnan(r)]
    return dict(rho=float(np.median(r)) if len(r) else np.nan, days=len(r))


def daily_decomp(d: pd.DataFrame, col: str, price: str = "price") -> dict:
    """診斷③ 日總量 vs 當日均價 / 當日熱需求 —— 價格決定「開多少」還是「何時開」?"""
    g = d.groupby("day").agg(v=(col, "sum"), p=(price, "mean"), dm=("dem", "mean"))
    g = g[g["v"] > 0]
    if len(g) < 30:
        return dict(rho_price=np.nan, rho_dem=np.nan, days=len(g))
    return dict(
        rho_price=float(spearmanr(g["v"], g["p"]).statistic),
        rho_dem=float(spearmanr(g["v"], g["dm"]).statistic),
        days=len(g),
    )


def signature(d: pd.DataFrame, cols: dict, price: str = "price") -> pd.DataFrame:
    """把三個診斷合成一張「行為簽名」表。模型端與實測端跑同一個函式,才可比。"""
    rows = []
    for col, name in cols.items():
        if col not in d or d[col].sum() <= 0:
            continue
        a, b, c = (
            day_fe_response(d, col, price),
            intraday_rho(d, col, price),
            daily_decomp(d, col, price),
        )
        rows.append(
            dict(
                來源=name,
                均MW=d[col].mean(),
                日FE係數=a["beta"],
                t值=a["t"],
                ΔR2=a["d_r2"],
                日內ρ=b["rho"],
                有效天數=b["days"],
                日總ρ價=c["rho_price"],
                日總ρ需求=c["rho_dem"],
            )
        )
    return pd.DataFrame(rows)


def _fmt(df: pd.DataFrame) -> str:
    return df.to_string(
        index=False,
        float_format=lambda x: f"{x:.3f}",
        formatters={"均MW": lambda x: f"{x:8.1f}", "有效天數": lambda x: f"{x:5.0f}"},
    )


def run_model(
    d: pd.DataFrame,
    kappa: float,
    fuel: str = "gas",
    committed: bool = False,
    pb_max: float = None,
    fuel_price: float = None,
    theta_f: float = None,
) -> dict:
    """把同一段真實 DK2 熱需求與電價餵進 `chp.solve()`,回傳逐時排程。

    🔴 **機組設定的三個誠實聲明**:
      ① 用的是**背壓垃圾原型**放大到車隊規模,不是 DK2 的實際車隊 ——
         DK2 有 64.6% 的熱來自生質抽汽機組,而**生質燃料價缺**(`dk2_fleet.runnable()` 2/6)。
      ② `fuel="gas"` 那組是拿**真實 TTF 氣價**配垃圾原型的技術參數 = 刻意的**上下夾**,
         不是某台真實機組。垃圾處理費那組是另一端。兩端之間就是生質價的不確定性。
      ③ `eb_max`/`hp_max` 用 **DK2 實測出力上界**(98 / 25.9 MW,見 demo() 的推導),
         不是 DEA 的單台典型值 20/10 —— 那兩個值對 1,000 MW_th 的熱網明顯太小。
    """
    import assumptions as A
    import chp
    import dk2_fleet as F

    qmax = sum(v["mw_th"] for v in F.FLEET.values())  # 車隊熱容量合計(varmelast 真值)
    cb = chp.dea_plant("waste", p_max=1.0).cb
    smax = sum(v["mwh"] for v in F.STORAGE.values())  # 三座蓄熱槽真值
    srate = sum(v["mw"] for v in F.STORAGE.values())
    over = {} if pb_max is None else dict(pb_max=pb_max)
    pl = chp.dea_plant(
        "waste",
        p_max=cb * qmax,  # 背壓式:P_max = Cb·Q_max(derived_mw_e 的同一條式子)
        eb_max=EB_OBSERVED_MAX,
        hp_max=HP_OBSERVED_MAX,
        s_max=smax,
        s_rate=srate,
        **over,
    )
    gas = d["gas"].to_numpy()
    # `fuel_price` 明確傳純量時優先(燃料價掃描用),否則走 fuel 的兩端
    fp = (
        fuel_price
        if fuel_price is not None
        else (gas if fuel == "gas" else A.waste_fuel_price_eur_mwh())
    )
    # 🔴 **θ_h 必須跟著燃料走,不能吃預設值**(2026-08-15):
    #    `fuel="waste"` 這組是真的垃圾廠 → 課 θ_h;
    #    `fuel="gas"` 那組是拿垃圾原型的**技術參數**當「一般 CHP」的代理,
    #    它代表的是 DK2 那 64.6% 的**生質**機組,而生質**不繳垃圾熱側稅**。
    #    若讓它吃 θ_h 的預設值,尖峰鍋爐佔比會從 5.95% 暴衝到 71.65%(實測 5.21%)——
    #    那是把一筆不存在的稅課在代理上,不是模型發現了什麼。
    theta_h = A.THETA_HEAT_WASTE if fuel == "waste" and fuel_price is None else 0.0
    return chp.solve(
        d["price"].to_numpy(),
        d["dem"].to_numpy(),
        pl,
        fuel_price=fp,
        fuel_price_pb=gas,
        co2_price=d["co2"].to_numpy(),
        cop=chp.cop_from_temp(d["tair"].to_numpy()),
        kappa=kappa,
        committed=committed,
        theta_f=theta_f,
        theta_h=theta_h,
    )


# DK2 的 power-to-heat 裝置容量 —— **銘牌值查不到**(varmelast 只給出力不給容量),
# 所以用**實測出力上界**當下界估計。這不是猜:出力達到過的值,容量至少有那麼大。
# 由 demo() 從資料重新推導並驗證,不是硬編。
EB_OBSERVED_MAX = 98.0
HP_OBSERVED_MAX = 25.9


def theta_h_threshold(y: pd.DataFrame, kappa: float, grid=None) -> pd.DataFrame:
    """測試 2 — **θ_h 要多大,垃圾機組才不再永遠全開?**

    核心策略是「不問 θ 是多少,問 θ 要多大結論才會變」 —— 只有門檻落進合理稅負區間時,
    才值得去查真值。

    🔴 **關掉蓄熱槽**(`s_max=0`):燃料價是負的 → LP 會**把蓄熱槽的散熱當棄熱管道**,
    多燒多賺,`Qc` 因此可以到熱需求的 106–115%。θ_h 掛在 Qc 上會第一個殺掉這個行為,
    門檻會被它汙染。關掉之後 ARC/ARGO 的基準供熱成本 ≈ **−€47.5**/MWh_th。

    ⚠️ 熱需求用 **DK2 真實形狀縮到機組熱容量**(尖峰對齊 Q_max)—— 這是重建的設定,
    不是原始腳本(那支沒進 repo)。舊記錄的 −€49.95/−51.01 用這個設定重現不出來。
    """
    import chp
    import dk2_fleet as F

    grid = [0, 10, 20, 25, 30, 40, 50] if grid is None else grid
    gas, co2 = y["gas"].to_numpy(), y["co2"].to_numpy()
    cop = chp.cop_from_temp(y["tair"].to_numpy())
    import assumptions as A

    rows = []
    for key in F.runnable():
        pl = chp.dk2_plant(key, s_max=0.0, s_rate=0.0)
        dem = y["dem"].to_numpy() * ((pl.p_max / pl.cb) / y["dem"].max())
        for th in grid:
            r = chp.solve(
                y["price"].to_numpy(),
                dem,
                pl,
                fuel_price=A.waste_fuel_price_eur_mwh(),
                fuel_price_pb=gas,
                co2_price=co2,
                cop=cop,
                theta_h=float(th),
                kappa=kappa,
            )
            rows.append(
                dict(
                    機組=key,
                    θ_h=float(th),
                    DKK_per_GJ=th / 3.6 * DKK_PER_EUR_LOCAL,
                    供熱成本=r["heat_cost_per_mwh"],
                    Qc佔熱=r["Qc"].sum() / dem.sum(),
                    非全開=float(((r["Qpb"] + r["Qe"] + r["Qh"]) > 1.0).mean()),
                )
            )
    return pd.DataFrame(rows)


def theta_f_scan(y: pd.DataFrame, kappa: float, grid=None) -> pd.DataFrame:
    """測試 3 — θ_f(天然氣國內碳稅)會不會把尖峰鍋爐的日內 ρ 推正?

    ⚠️ **佔比必須跟 ρ 一起報**:燃料價掃描那次的教訓 —— 佔比 0.25% 的格子算出來的 ρ
    是雜訊不是估計值。`days` 欄就是檢定力,低於 ~30 天的 ρ 不要讀。
    """
    import assumptions as A
    import chp

    grid = [0, 25, 50, 75, 100, 125, 150] if grid is None else grid
    gas, co2 = y["gas"].to_numpy(), y["co2"].to_numpy()
    cop = chp.cop_from_temp(y["tair"].to_numpy())
    tot = y["dem"].sum()
    rows = []
    for tf in grid:
        r = run_model(y, kappa, theta_f=float(tf))
        z = y.copy()
        z["Qpb"] = r["Qpb"]
        a = intraday_rho(z, "Qpb")
        rows.append(
            dict(
                θ_f=float(tf),
                對尖峰鍋爐=tf * chp.Plant.ef_pb / chp.Plant.eta_pb,
                日內ρ=a["rho"],
                days=a["days"],
                尖峰佔熱=r["Qpb"].sum() / tot,
                P2H佔熱=(r["Qe"].sum() + r["Qh"].sum()) / tot,
            )
        )
    _ = A, gas, co2, cop  # 保持與 theta_h_threshold 對稱的簽名,實際由 run_model 取用
    return pd.DataFrame(rows)


DKK_PER_EUR_LOCAL = 7.46
"""換算到稅法自己的單位(kr/GJ_heat)用 —— 這樣門檻才能直接跟法定稅率比對。
與 `assumptions.DKK_PER_EUR` 同值,在這裡重複一次是為了讓表格自帶單位換算。"""


def demo() -> None:
    if not os.path.exists(VARMELAST):
        print("  (跳過:找不到 varmelast 資料)")
        return
    d = load_dk2()
    print(
        f"  資料 ok: {len(d):,} 小時 {d['timestamp'].min():%Y-%m} → {d['timestamp'].max():%Y-%m},"
        f"熱需求均 {d['dem'].mean():.0f} MW_th,電價 100% 對得上"
    )

    # ── ① 容量下界必須從資料重新推導(不是抄常數)────────────────────────
    eb, hp = d["BE-VL-EVO-EF"].max(), d["BE-VL-VP-EF"].max()
    assert abs(eb - EB_OBSERVED_MAX) < 1.0 and abs(hp - HP_OBSERVED_MAX) < 1.0, (
        f"P2H 實測出力上界漂了:電鍋爐 {eb:.1f}(常數 {EB_OBSERVED_MAX})、"
        f"熱泵 {hp:.1f}(常數 {HP_OBSERVED_MAX})—— 資料更新了就把常數一起改"
    )
    import chp

    print(
        f"  P2H 容量下界 ok: 電鍋爐 ≥{eb:.0f} MW_th、熱泵 ≥{hp:.0f}(實測出力上界)"
        f" —— 對照 chp.Plant 的 DEA 單台值 {chp.Plant.eb_max:.0f}/{chp.Plant.hp_max:.0f},"
        f"**低了 {eb / chp.Plant.eb_max:.1f}×/{hp / chp.Plant.hp_max:.1f}×**"
    )

    # ── ② 季節性陷阱必須真的存在(否則診斷①就沒有必要)───────────────────
    # 🔴 **只有熱電是這個陷阱**,垃圾不是(它在原始資料上就已經是負的)。
    #    2026-08-12 修:原本兩個都斷言,但資料不支持垃圾那一半 —— 寫成資料真正說的樣子。
    q = d["price"].quantile([0.25, 0.75])

    def raw_gap(col):
        return (
            d.loc[d["price"] >= q.iloc[1], col].mean()
            - d.loc[d["price"] <= q.iloc[0], col].mean()
        )

    raw_chp, fe_chp = raw_gap("BE-VL-KRAFTV-EF"), day_fe_response(d, "BE-VL-KRAFTV-EF")
    assert raw_chp > 0 > fe_chp["beta"], (
        f"熱電應該是「原始看正、日內看負」的季節性陷阱,"
        f"實得 原始差 {raw_chp:+.1f} MW、日FE係數 {fe_chp['beta']:+.4f}"
    )
    print(
        f"  季節性陷阱 ok: 熱電在原始資料上高價四分位比低價高 {raw_chp:+.0f} MW,"
        f"加日固定效果後係數翻成 {fe_chp['beta']:+.4f} → 診斷①擋掉的正是這個"
        f"\n     (垃圾焚化不是這個陷阱:原始差已經是 {raw_gap('BE-VL-AFFALD-EF'):+.1f} MW)"
    )

    # ── ③ 實測行為簽名 ─────────────────────────────────────────────────
    emp = signature(d, {k: v[0] for k, v in SOURCES.items()})
    print(f"\n=== DK2 實測行為簽名({d['timestamp'].dt.year.nunique()} 年)===")
    print(_fmt(emp))

    e = emp.set_index("來源")
    # 電鍋爐必須是所有熱源裡對價格最敏感的(ΔR² 與 |日內ρ| 都是)—— 這是 LP 的 Qe 該有的樣子
    assert e.loc["電鍋爐", "ΔR2"] == e["ΔR2"].max(), (
        f"電鍋爐應是最price-sensitive的熱源,實得 ΔR² 排序:\n{e['ΔR2'].sort_values()}"
    )
    assert e.loc["電鍋爐", "日內ρ"] < -0.15, "電鍋爐應明顯在便宜的小時跑"
    # 尖峰鍋爐與電鍋爐的日內符號必須相反 —— 這是「誰在邊際上供熱」的替代關係
    assert e.loc["尖峰氣", "日內ρ"] > 0 > e.loc["電鍋爐", "日內ρ"], (
        f"尖峰氣({e.loc['尖峰氣', '日內ρ']:+.3f})與電鍋爐"
        f"({e.loc['電鍋爐', '日內ρ']:+.3f})的日內符號應相反"
    )
    # 熱電產熱幾乎不隨價格動(熱是義務)—— 這是 LP 最該學會的一件事
    assert abs(e.loc["熱電 CHP", "日內ρ"]) < 0.1, "熱電產熱在日內應近乎不隨電價變動"
    print(
        f"  簽名 ok: 電鍋爐 ΔR²={e.loc['電鍋爐', 'ΔR2']:.4f} 為全場最高、日內ρ="
        f"{e.loc['電鍋爐', '日內ρ']:+.3f};尖峰氣 {e.loc['尖峰氣', '日內ρ']:+.3f} 符號相反"
        f"(替代關係);熱電 {e.loc['熱電 CHP', '日內ρ']:+.3f} ≈ 0(熱是義務)"
    )

    # ── ④ 負電價與熱需求的結構性錯位(C3 章的核心事實)──────────────────
    neg = d["price"] < 0
    hi_dem = d["dem"] >= d["dem"].quantile(0.9)
    lo_dem = d["dem"] <= d["dem"].quantile(0.1)
    share_hi = (d.loc[hi_dem, "price"] < 20).mean()
    share_lo = (d.loc[lo_dem, "price"] < 20).mean()
    assert share_lo > 5 * share_hi, "預期低熱需求時段才有便宜電"
    winter = d.loc[neg, "timestamp"].dt.month.isin([11, 12, 1, 2]).mean()
    print(
        f"\n  🔑 負電價 {neg.sum():,} 小時({neg.mean():.2%}),其中只有 {winter:.1%} 落在 11–2 月;"
        f"\n     那些小時的熱需求只有全期均的 {d.loc[neg, 'dem'].mean() / d['dem'].mean():.0%}。"
        f"\n     熱需求最高十分位有 {share_hi:.2%} 的小時電價<20,最低十分位 {share_lo:.2%}"
        f"(差 {share_lo / max(share_hi, 1e-9):.0f}×)"
        f"\n     → **power-to-heat 想吸收的便宜電,結構上不出現在有熱需求的時候**"
    )
    # 但「沒空間」解釋不了全部:負電價時仍有多少空間沒被用掉
    room = d.loc[neg, "room"].mean()
    used = (d.loc[neg, "BE-VL-EVO-EF"] + d.loc[neg, "BE-VL-VP-EF"]).mean()
    print(
        f"     ⚠️ 但不是「沒空間」:負電價時非必發空間仍有 {room:.0f} MW_th,"
        f"實際只用了 {used:.1f} MW_th 的 P2H"
    )

    # ── ⑤ 模型端:同一段資料、同一套診斷 ────────────────────────────────
    if not os.path.exists("new_data/DEA_data") or "gas" not in d:
        print("\n  (跳過模型對照:缺 DEA_data 或 energy.duckdb)")
        return
    import assumptions as A

    y = d[(d["timestamp"].dt.year == 2024) & d["gas"].notna()].reset_index(drop=True)
    if len(y) < 8000:
        print("\n  (跳過模型對照:2024 的燃料價覆蓋不足)")
        return
    print(f"\n=== 模型對照:同一段真實 DK2 資料({len(y):,} 小時,2024)===")
    tot = y["dem"].sum()
    # 🔴 **分母必須與 LP 同源**(2026-08-13 修):LP 的佔比分母是熱需求(= CTR+VEKS 消費),
    #    所以實測也要用消費當分母。先前用「生產分項加總」當分母 —— 生產比消費多 2.44%
    #    (蓄熱 + 網損),兩邊分母不同源時「對得很好」就是巧合。
    # ⚠️ 另一個混在一起的錯:LP 的 `Qpb` 是**單一尖峰鍋爐**,對應實測的**氣 + 油**;
    #    而文件裡那個 4.0% 是**尖峰氣單獨**。兩個量不同,不要互相對照。
    heat_cols = [c for c in y.columns if c.startswith("BE-VL-") and c.endswith("-EF")]
    real = dict(
        p2h=(y["BE-VL-EVO-EF"].sum() + y["BE-VL-VP-EF"].sum()) / tot,
        pb=(y["BE-VL-SPIDS-GAS-EF"].sum() + y["BE-VL-SPIDS-OLIE-EF"].sum()) / tot,
        pb_gas=y["BE-VL-SPIDS-GAS-EF"].sum() / tot,
        prod_over_dem=y[heat_cols].sum().sum() / tot,
    )

    out = []
    for fuel, lab in [("waste", "垃圾處理費(負)"), ("gas", "真實 TTF 氣價")]:
        for kappa, klab in [(0.0, "κ=0"), (A.KAPPA_NET, f"κ={A.KAPPA_NET:.2f}")]:
            r = run_model(y, kappa, fuel)
            out.append((f"{lab} {klab}", r))
            print(
                f"  {lab:16} {klab:8} P2H 佔熱 {(r['Qe'].sum() + r['Qh'].sum()) / tot:6.2%}"
                f"  尖峰鍋爐 {r['Qpb'].sum() / tot:6.2%}"
                f"  單位供熱 €{r['heat_cost_per_mwh']:7.1f}/MWh_th"
            )
    print(
        f"  {'🔴 DK2 實測':25} P2H 佔熱 {real['p2h']:6.2%}  尖峰鍋爐 {real['pb']:6.2%}"
        f"(氣+油;氣單獨 {real['pb_gas']:.2%})"
    )
    print(
        "     ⚠️ 分母一律用熱需求(CTR+VEKS 消費),與 LP 同源;"
        f"改用生產分項加總會多算 {real['prod_over_dem'] - 1:.2%}(蓄熱+網損)"
    )

    # 燃料價兩端把**佔比**(水準)拉開一個數量級以上 → 生質價缺擋住的是水準比對。
    # ⚠️ 這**不能**推論到時點:燃料價決定 merit order、merit order 決定誰在邊際上,
    #    而那正是 ρ 在量的東西。時點免不免疫要另外測 —— 見 ⑥b 的掃描。
    p2h = [(r["Qe"].sum() + r["Qh"].sum()) / tot for _, r in out]
    assert max(p2h) > 10 * max(min(p2h), 1e-6), (
        "預期燃料價兩端會把 P2H 佔比拉開一個數量級以上(這正是生質價缺的代價)"
    )
    print(
        f"  ⚠️ 燃料價兩端把 P2H 佔比從 {min(p2h):.2%} 拉到 {max(p2h):.2%}"
        f"(**{max(p2h) / max(min(p2h), 1e-9):.0f}×**)→ **水準比對在生質價到手前不可引用**。"
        "\n     (時點是否也被擋住是另一個問題,不能由這裡推論 —— 見下面的燃料價掃描。)"
    )

    # ── ⑥ 🔴 核心結果:年佔比對得上,時點卻是反的 ─────────────────────────
    mdl = None
    for lab, r in out:
        if "TTF" in lab and "κ=0" not in lab:
            z = y.copy()
            z["Qe"], z["Qh"], z["Qpb"], z["Qc"] = r["Qe"], r["Qh"], r["Qpb"], r["Qc"]
            mdl = signature(
                z, {"Qc": "LP 熱電 Qc", "Qpb": "LP 尖峰 Qpb", "Qe": "LP 電鍋爐 Qe"}
            )
    emp24 = signature(
        y,
        {
            "BE-VL-KRAFTV-EF": "實測 熱電",
            "BE-VL-SPIDS-GAS-EF": "實測 尖峰氣",
            "BE-VL-EVO-EF": "實測 電鍋爐",
        },
    )
    print(f"\n  行為簽名 — 實測 vs LP(真實氣價 + κ={A.KAPPA_NET:.2f} 真值):")
    print(_fmt(pd.concat([emp24, mdl], ignore_index=True)))

    m = mdl.set_index("來源")
    r24 = emp24.set_index("來源")
    # 🔴 這兩條 assert 就是本模組的結論。它們**現在會通過**,因為模型現在是錯的;
    #    等到模型改對了,它們會失敗 —— 那時候請把它們反過來寫,並更新 STATUS.md §7。
    assert r24.loc["實測 尖峰氣", "日內ρ"] > 0 > m.loc["LP 尖峰 Qpb", "日內ρ"], (
        "預期尖峰鍋爐的日內時點在模型裡是反的"
    )
    assert abs(m.loc["LP 電鍋爐 Qe", "日總ρ價"]) > 2 * abs(
        r24.loc["實測 電鍋爐", "日總ρ價"]
    ), "預期 LP 的電鍋爐日總量對價格過度反應"
    # ── ⑥b 🔑 **時點結論對燃料價免疫嗎?**(2026-08-13 補,審閱意見)──────────
    #    §8.3 用「水準對燃料價超敏感(654×)」證明水準不可引用,但那不代表**時點**
    #    也免疫 —— 燃料價決定 merit order,merit order 決定誰在邊際上,那正是 ρ 在量的。
    #    🔴 **不能用「垃圾處理費 vs 氣價」當兩端**:低端 CHP 太便宜,尖峰鍋爐全年只有
    #       6 天有出力、電鍋爐 2 天 → ρ 是用 2–6 天算的,不是估計值。改成掃描。
    print("\n  時點結論對燃料價免疫嗎?(掃 CHP 燃料價,看符號在哪裡才翻)")
    print(
        f"    {'燃料價':>8} {'尖峰ρ':>8}{'(天)':>6} {'電鍋爐ρ':>9}{'(天)':>6} {'尖峰%':>7}{'P2H%':>7}"
    )
    sweep = []
    for fp in (0.0, 10.0, 20.0, 30.0, 40.0, 60.0, 80.0):
        r = run_model(y, A.KAPPA_NET, fuel_price=fp)
        z = y.copy()
        z["Qpb"], z["Qe"] = r["Qpb"], r["Qe"]
        a, e = intraday_rho(z, "Qpb"), intraday_rho(z, "Qe")
        sh = r["Qpb"].sum() / tot
        sweep.append((fp, a["rho"], sh))
        print(
            f"    {fp:8.1f} {a['rho']:8.3f}{a['days']:6d} {e['rho']:9.3f}{e['days']:6d}"
            f" {sh:7.2%}{(r['Qe'].sum() + r['Qh'].sum()) / tot:7.2%}"
        )
    # 只在尖峰鍋爐**還是尖峰機**的區間內解讀:佔比一旦衝到 80%+,它就是基載了,
    # 那時 ρ 轉正不是「模型變對」而是「這個診斷失去意義」。
    peaker = [(f, r_, s) for f, r_, s in sweep if s < 0.5]
    assert all(r_ < 0 for _, r_, _ in peaker), (
        f"尖峰鍋爐仍是尖峰機(佔比<50%)的區間內,日內 ρ 應一律為負:{peaker}"
    )
    bio = None
    try:
        bio = A.biomass_fuel_price_eur_mwh(2025)
    except (KeyError, FileNotFoundError):
        pass
    print(
        f"    ✅ 尖峰鍋爐佔比 <50% 的整個區間內,日內 ρ **一律為負**"
        f"({min(r_ for _, r_, _ in peaker):.3f} ~ {max(r_ for _, r_, _ in peaker):.3f})。"
        f"\n       ρ 只在燃料價 80(佔比 {sweep[-1][2]:.0%})才轉正 —— 那時它已經是**基載不是尖峰機**,"
        "診斷本身失去意義,不算符號翻轉。"
        + (
            f"\n       📌 錨點:SØB25 木片 2025 = **€{bio:.1f}/MWh_fuel**,落在穩定區間中央"
            " → **時點結論不被生質價擋住**(水準仍然被擋)。"
            if bio
            else ""
        )
    )

    # ── ⑥c 尖峰鍋爐「無上限懲罰項」是不是把 ρ 的符號做出來的?(審閱意見)─────
    #    質疑很合理:無上限、無啟停成本的鍋爐在 LP 裡是**純價差套利工具**,
    #    在任何 spread 划算的小時都會開,跟需求脫鉤;真實尖峰機是**容量驅動**的。
    #    → 給它 varmelast 公布的真實尖峰容量,看 ρ 會不會回正。
    import dk2_fleet as F

    pb_real = F.PUBLISHED_TOTALS["peak_mw_th"]
    free = run_model(y, A.KAPPA_NET)
    capped = run_model(y, A.KAPPA_NET, pb_max=pb_real)
    zf, zc = y.copy(), y.copy()
    zf["Qpb"], zc["Qpb"] = free["Qpb"], capped["Qpb"]
    rf, rcp = intraday_rho(zf, "Qpb")["rho"], intraday_rho(zc, "Qpb")["rho"]
    bind = (free["Qpb"] > pb_real).sum()
    assert rcp < 0, "給真實容量後尖峰鍋爐 ρ 仍應為負(若回正,§8.3 要改寫)"
    print(
        f"\n  尖峰鍋爐給真實容量({pb_real:.0f} MW_th,varmelast 公布)後:"
        f"日內 ρ {rf:+.3f} → {rcp:+.3f}(**幾乎不動**)"
        f"\n     上限在 {bind} 小時({bind / len(y):.1%})綁到 → 檢定有 power 但很弱。"
        "\n     🔴 **真正該測的是啟動成本**(那才是「尖峰機 vs 套利工具」的分野),"
        "但目錄的 `44 Natural Gas DH Only` **沒有 Startup cost 欄**"
        "\n        (只有 min load 0.15 與啟動時間)→ **這個 confound 目前無法排除**,"
        "而且加啟停要整數變數。見 STATUS.md §8.6。"
    )

    # ── ⑥d θ_h:窗口區間有沒有跨過「垃圾機組不再全開」的門檻?──────────────
    #    🔑 2026-08-15 起 θ_h 有公布值,所以問題從「門檻在哪」變成
    #       「已知的區間有沒有跨過門檻」。**門檻必須用 κ 的真值算** ——
    #       κ 讓 P2H 變貴 → 更難擠掉垃圾 → 門檻往上移(κ=0 時 30,κ=8.50 時 35)。
    kap = A.KAPPA_NET
    #    🔴 **34 那一格是刻意加的**(≈70.5 DKK/GJ),而它一加進來就推翻了舊結論:
    #       這裡報的「門檻」定義是**格點裡第一個非全開 ≥5% 的 θ_h**,
    #       舊格點 30 與 35 之間是空的 → 報 35 (73 DKK/GJ);加了 34 之後報 34 (70)。
    #       → **73 是格點假象**,真正的穿越點在 30–34 之間(62–70 DKK/GJ),
    #         而代理上界 62 是**貼在下緣**,不是「低於門檻 18%」。
    #       🔑 教訓:門檻這種由格點決定的數字,加一格就會動 → 報門檻要一起報格點解析度,
    #         比較兩個 κ 的門檻時也**必須用同一組格點**。詳見 STATUS.md §9.4。
    th = theta_h_threshold(y, kappa=kap, grid=[0, 20, 24, 30, 34, 35, 40, 50])
    print(f"\n  測試 2 — θ_h 門檻(ARC/ARGO,關蓄熱槽,**κ={kap:.2f} 真值**)")
    print(_fmt(th[th["機組"] == "arc"].drop(columns="機組")))
    arc = th[th["機組"] == "arc"]
    hit = arc[arc["非全開"] >= 0.05]["θ_h"]
    thr = float(hit.min()) if len(hit) else float("inf")
    # 🔴 **報「穿越點落在哪兩格之間」而不是報單一數字** —— 單一數字是格點的性質不是模型的。
    below = arc[arc["非全開"] < 0.05]["θ_h"]
    lo_br = float(below.max()) if len(below) else float("nan")
    print(
        f"    🔑 **非全開 ≥5% 的穿越點落在 θ_h {lo_br:.0f} 與 {thr:.0f} EUR/MWh_th 之間"
        f"({lo_br / 3.6 * DKK_PER_EUR_LOCAL:.0f}–{thr / 3.6 * DKK_PER_EUR_LOCAL:.0f} DKK/GJ_heat)**"
        f"\n       ⚠️ **不要把上緣 {thr:.0f} 當成「門檻」單獨引用** —— 它只是格點裡第一個跨過去的格子,"
        "\n          加一格就會動(2026-08-15 加了 34 就把舊的 35 推翻了)。"
        "\n       ⚠️ **擠掉垃圾的是 power-to-heat,不是尖峰鍋爐**(尖峰佔熱全程 0.00%)"
        f"\n       → 所以穿越點由 κ 決定,κ 越大越往上移。**兩個參數是耦合的,不能各自判斷**"
        "(⚠️ 比較不同 κ 時必須用**同一組格點**)。"
    )
    # 🔑 **2026-08-15:θ_h 有公布值了,所以問題從「門檻在哪」變成「窗口區間有沒有跨過門檻」**
    lo, hi = A.THETA_HEAT_WASTE_LOW, A.THETA_HEAT_WASTE_HIGH
    ends = theta_h_threshold(y, kappa=kap, grid=[lo, hi])
    e = ends[ends["機組"] == "arc"].set_index("θ_h")
    print(
        f"\n  🔑 **θ_h 的窗口區間 {lo:.1f}–{hi:.1f} EUR/MWh_th "
        f"({lo / 3.6 * DKK_PER_EUR_LOCAL:.0f}–{hi / 3.6 * DKK_PER_EUR_LOCAL:.0f} DKK/GJ_heat)"
        f" 全部落在門檻 {thr:.0f} 之下**"
        f"\n     兩端的 ARC 調度:垃圾佔熱 {e.loc[lo, 'Qc佔熱']:.1%} → {e.loc[hi, 'Qc佔熱']:.1%}、"
        f"非全開 {e.loc[lo, '非全開']:.1%} → {e.loc[hi, '非全開']:.1%} "
        f"(供熱成本 {e.loc[lo, '供熱成本']:.2f} → {e.loc[hi, '供熱成本']:.2f})"
        "\n     🔴 **不可以寫成「兩端無差異」** —— 非全開小時是 6 倍(到 34 是 18 倍)。"
        "\n     ✅ 正確宣稱:**供熱佔比全區間 97.6–99.8%,實質 must-run**"
        " → **『垃圾焚化無策略調度邊際』這個結論對 θ_h 的真值不敏感**"
        "\n     (宣稱的是研究結論一樣,不是兩次跑的數字一樣)→ 不必再去挖 2021–2024 的真值。"
    )
    # 這三條鎖住結論:區間必須在門檻下、兩端的垃圾佔熱差距要小、
    # 而且**貼著門檻下緣的壓力測試也要撐得住**(這條才是「代理可能低估真值」的解答)
    assert hi < thr, (
        f"θ_h 上界 {hi:.1f} 若跨過門檻 {thr:.0f},垃圾機組的調度型態會變 → 結論要改寫"
    )
    assert abs(e.loc[lo, "Qc佔熱"] - e.loc[hi, "Qc佔熱"]) < 0.02, (
        "θ_h 兩端的垃圾供熱佔比若差超過 2 個百分點,就不能說『對真值不敏感』"
    )
    stress = th[(th["θ_h"] == 34) & (th["Qc佔熱"] < 0.95)]
    assert stress.empty, (
        "θ_h = 34(貼門檻下緣)時垃圾供熱佔比若跌破 95%,"
        "「即使真值比代理上界再高 13% 也仍是 must-run」這個宣稱就不成立了:\n"
        f"{stress}"
    )

    tf = theta_f_scan(y, kappa=kap)
    print("\n  測試 3 — θ_f 會不會把尖峰鍋爐的日內 ρ 推正?")
    print(_fmt(tf))
    # 只有檢定力足夠的格子可讀(佔比撐得住 → days 夠多)
    ok = tf[tf["days"] >= 30]
    assert (ok["日內ρ"] < 0).all(), (
        f"θ_f 若把 ρ 推正,STATUS §8.6 要改寫:{ok[['θ_f', '日內ρ', 'days']].to_dict('records')}"
    )
    print(
        f"    🔴 **θ_f 沒有把符號推正**(檢定力足夠的格子:ρ "
        f"{ok['日內ρ'].max():.3f} ~ {ok['日內ρ'].min():.3f},全為負)。"
        f"\n       而且它讓尖峰鍋爐**幾乎消失**:佔熱 {tf['尖峰佔熱'].iloc[0]:.2%} → "
        f"{tf['尖峰佔熱'].iloc[-1]:.2%},離實測 {real['pb']:.2%} **更遠**。"
        "\n       → 實測的 5.21% 本身就是「DK2 尖峰鍋爐沒有付大額國內碳稅」的旁證"
        "(⚠️ 在本模型結構下,而本模型的時點已知是錯的 → 不可當結論引用)。"
    )

    # ── ⑦ 最小負載補得了多少?(供熱季,機組持續併聯運轉才成立)────────────
    hs = y[y["timestamp"].dt.month.isin([1, 2, 3, 4, 10, 11, 12])].reset_index(
        drop=True
    )
    kap = A.KAPPA_NET
    free, comm = run_model(hs, kap, "gas"), run_model(hs, kap, "gas", committed=True)
    rows = []
    for lab, r in [("LP 自由", free), ("LP +最小負載", comm)]:
        z = hs.copy()
        z["Qpb"], z["Qe"] = r["Qpb"], r["Qe"]
        rows.append(signature(z, {"Qpb": f"{lab} 尖峰", "Qe": f"{lab} 電鍋爐"}))
    rows.append(
        signature(
            hs,
            {"BE-VL-SPIDS-GAS-EF": "🔴 實測 尖峰氣", "BE-VL-EVO-EF": "🔴 實測 電鍋爐"},
        )
    )
    print(f"\n  最小負載補得了多少?(2024 供熱季 {len(hs):,} 小時)")
    print(_fmt(pd.concat(rows, ignore_index=True)))
    g = pd.concat(rows, ignore_index=True).set_index("來源")
    got = g.loc["LP +最小負載 尖峰", "日內ρ"] - g.loc["LP 自由 尖峰", "日內ρ"]
    gap = g.loc["🔴 實測 尖峰氣", "日內ρ"] - g.loc["LP 自由 尖峰", "日內ρ"]
    # 方向要對(不然就是加錯了),但**補不滿**——這一條鎖住「別再說最小負載是主因」
    assert got > 0, f"最小負載應把尖峰鍋爐的日內 ρ 往正的推,實得 {got:+.3f}"
    assert got < 0.3 * gap, (
        f"若最小負載補了 30% 以上,§8.5 的結論要改寫:補了 {got:+.3f} / 缺口 {gap:+.3f}"
    )
    print(
        f"  ⚠️ 最小負載只補了缺口的 **{got / gap:.0%}**({got:+.3f} / {gap:+.3f}),"
        f"而且電鍋爐日總 ρ(價) {g.loc['LP 自由 電鍋爐', '日總ρ價']:+.3f} → "
        f"{g.loc['LP +最小負載 電鍋爐', '日總ρ價']:+.3f}(**幾乎沒動**,實測 "
        f"{g.loc['🔴 實測 電鍋爐', '日總ρ價']:+.3f})"
        "\n     → 「缺最小負載是主因」這個推測**只對了一小部分**,不要再重複它。"
    )

    print(
        f"\n  🔴 **結論**:年佔比對得上(尖峰鍋爐模型 vs 實測見上表),"
        f"但**日內時點的符號是反的** —— 實測尖峰氣 {r24.loc['實測 尖峰氣', '日內ρ']:+.3f}"
        f"(貴的小時才燒)vs LP {m.loc['LP 尖峰 Qpb', '日內ρ']:+.3f}(便宜的小時燒)。"
        f"\n     而且 LP 在每個維度都**對價格過度反應**:電鍋爐日總量 ρ 實測 "
        f"{r24.loc['實測 電鍋爐', '日總ρ價']:+.3f} vs LP {m.loc['LP 電鍋爐 Qe', '日總ρ價']:+.3f};"
        f"\n     實測的日總量主要由**熱需求**決定(ρ={r24.loc['實測 電鍋爐', '日總ρ需求']:+.3f}),"
        f"LP 幾乎只看價格(對需求 ρ={m.loc['LP 電鍋爐 Qe', '日總ρ需求']:+.3f})。"
        "\n     ❌ **不是燃料價或稅費**:κ 只改水準,簽名不動;而且 κ 是**能源費不隨小時變**,"
        "結構上就不可能改時點。"
        "\n     ❌ **也不主要是最小負載**:上面那組只補了 13% 的缺口(這是實測,不是推測)。"
        "\n     🔴 **主因仍未確定。** 最明確的候選是**輔助服務市場**"
        "(電鍋爐若靠調頻收入,調度就由啟動訊號而非現貨價決定)——"
        "\n        ⚠️ 未查證。可測的資料集見 DATA.md §9b(已確認存在,批量抓取卡 rate limit)。"
    )


if __name__ == "__main__":
    print("=== 用 varmelast 分項產熱驗 chp.py 的排程行為 ===\n")
    demo()
