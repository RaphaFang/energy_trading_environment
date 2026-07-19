"""λ 的估計與診斷 — 證明「單一純量 λ」不夠,並給出狀態相依的 λ_h(x)。

**範圍(重要,別誤讀):這是診斷腳本,不是模擬器的一部分。** v2-v4 目前用純量
λ=0.037 當保守基準;這裡估出的 λ_h(x) 是論文裡「純量夠不夠」的證據,沒有接進模擬器
(接進去要處理大車隊的非線性,見下面「未做」)。

背景:市場機制寫成 dominant firm–competitive fringe。需求無彈性 x(殘餘負載),fringe
照供給曲線 S(p) 投標,agent 淨買 Q,出清 S(p)=x+Q。在出清點線性化:
    p = S⁻¹(x) + (1/S')·Q = p₀(x) + λ(x)·Q
所以 λ(x) = dp₀/dx = fringe 斜率的倒數。p₀ 這裡是**擬合 act 得到的**(不是從成本結構
推出來的)→ 循環仍在,故本檔不宣稱任何反事實/市場力結果,只談 λ 的量級與形狀。

做四件事(全用歷史 actual 校準環境,不是預測):
  1. 重現舊的純量 λ(裸 + 控燃料)= 單一 OLS,證明它就是一條直線
  2. p₀(x) 用**保序迴歸**(強制單調遞增 = 供給曲線的經濟約束),再微分得 λ(x)。
     不用「分箱中位數再差分」:那會把雜訊放大成負斜率(40 箱有 8 箱 λ<0,
     經濟上不可能——供給曲線不會向下傾斜)。保序迴歸從源頭排除這件事。
  3. λ 隨燃料 regime 變:gas 低/中/高 → 斜率 0.010/0.019/0.044(merit order 隨燃料旋轉)。
     **這個維度的變異比 x 維度的還大**,是純量 λ 最大的失真來源。
  4. act 被基本面解釋多少:R² 逐步(殘餘→+gas→+co2→+德residual),全步驟鎖同一批樣本。
     剩下的 23% 是「市場力 + 進口 + 天氣 + 未納入變數」的**上界**,不是市場力本身。

未做(知道但不在本檔範圍):
  - 接進模擬器。λ(x) 是**局部**斜率,車隊小(≤100MW)時線性近似成立;GW 級會沿曲線
    跑很長一段,得改成 p = p₀(x+Q) 直接查曲線(非線性,要動 perfect() 的 LP)。
  - act−p₀ **不能**當市場力:p₀ 是 act 的擬合,兩者相減必然是零均值噪音。真的市場力
    要拿「全員出邊際成本」的競爭反事實比 act,那需要成本型 fringe(不在這裡)。

用法:python new_src/agents/fringe.py [DK1|DK2]   (預設 DK1)
"""

import os
import sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

DB = "new_data/energy.duckdb"
FIGDIR = "figs"
NGRID = 60  # λ(x) 取樣格點數

# structural_lambda 的特徵集設計:x(本地殘餘負載)必須是本地供需的**唯一**管道。
# 拿掉 x 的成分(load/wind/solar 預測):x = load − wind − solar,三者留在特徵集裡的話,
# 「固定它們、只動 x」是矛盾的反事實,樹在那個方向沒資訊 → 偏導數假性趨近 0(實測過)。
# 拿掉價格 lag:會讓模型變自迴歸、把價格水平吸走,估不到結構關係。
_DROP = {
    "timestamp_utc",
    "area",
    "holiday_name",
    "y_price_eur",
    "load_mwh",
    "wind_mwh",
    "solar_mwh",
    "residual_mwh",  # 同時刻實測
    "loadfc_mwh",
    "onshore_wind_da_mwh",
    "offshore_wind_da_mwh",
    "solar_da_mwh",  # x 的成分
    "price_lag24_eur",
    "price_lag168_eur",
    "load_lag24_mwh",
    "residual_lag24_mwh",  # 自迴歸
    "wind_speed_100m",
    "wind_gusts_10m",  # 風速 → 風出力 → x 的成分
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",  # 輻射 → 光出力 → 同上
}
FD_STEP = 300.0  # 有限差分步長(MW):樹是階梯函數,步長太小會落在同一葉子得到 0


def load_state(area: str = "DK1") -> pd.DataFrame:
    """殘餘負載 x、真實出清價 act、燃料、德國殘餘(當外生 shifter)。用 actual 校準環境。"""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, residual_mwh AS x, "
        "ttf_gas_eur_mwh AS gas, eua_co2_eur_t AS co2, de_residual_mwh AS de_x "
        f"FROM training WHERE area='{area}' "
        "AND y_price_eur IS NOT NULL AND residual_mwh IS NOT NULL "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    return df


def structural_lambda(area: str = "DK1", step: float = FD_STEP) -> pd.DataFrame:
    """**這是給模擬器用的 λ。** 多變數偏導數:控制鄰國/燃料/邊界/日曆後,本地殘餘負載
    對價格的偏效果 ∂p/∂x,在每小時自己的完整狀態向量上求值。

    為什麼偏導數才對:λ 要回答「我的電池多買 1 MW,價格漲多少」——那個實驗裡德國的風、
    天然氣價、瑞典的水**都不變**,正是 ceteris paribus。單變數 OLS 斜率回答的是另一個
    問題:「當本地殘餘剛好高 1 MW 時(通常因為德國也剛好缺電),價格高多少」,那裡面
    混著鄰國效應 → 系統性高估。實測差一個數量級(0.034 vs 0.0035)。

    做法:LightGBM 配 p ~ (x, 燃料, 德/瑞殘餘, 邊界, 日曆, 氣溫),再對 x 做中央差分。
    步長 300MW(見 FD_STEP);特徵集見 _DROP 的理由。

    ⚠️ 觀察性估計,不是因果識別。控制了可觀察的混淆,沒處理不可觀察的。嚴謹版該用
    風當工具變數(風外生、只透過殘餘負載進價格)——資料齊,沒做。

    回傳每小時:timestamp / x / gas / price / lam。"""
    import lightgbm as lgb

    con = duckdb.connect(DB, read_only=True)
    d = con.execute(
        f"SELECT * FROM training WHERE area='{area}' AND y_price_eur IS NOT NULL "
        "AND residual_mwh IS NOT NULL AND ttf_gas_eur_mwh IS NOT NULL "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()

    d["x"] = d["residual_mwh"]
    feats = [c for c in d.columns if c not in _DROP and c != "x" and d[c].notna().any()]
    feats.append("x")
    for b in d[feats].select_dtypes("bool"):
        d[b] = d[b].astype(int)
    X, y = d[feats], d["y_price_eur"]
    m = lgb.LGBMRegressor(
        n_estimators=600, learning_rate=0.05, num_leaves=63, verbose=-1, random_state=0
    ).fit(X, y)

    Xp, Xm = X.copy(), X.copy()
    Xp["x"] += step
    Xm["x"] -= step
    lam = (m.predict(Xp) - m.predict(Xm)) / (2 * step)
    return pd.DataFrame(
        {
            "timestamp_utc": d["timestamp_utc"],
            "x": d["x"],
            "gas": d["ttf_gas_eur_mwh"],
            "price": d["y_price_eur"],
            "lam": lam,
        }
    )


def scalar_lambda(df: pd.DataFrame) -> dict:
    """重現舊的純量 λ:裸斜率(price~x)與控 gas+co2 後的殘餘斜率。就是單一 OLS。"""
    m = df.dropna(subset=["price", "x"])
    naive = float(np.polyfit(m["x"], m["price"], 1)[0])
    f = df.dropna(subset=["price", "x", "gas", "co2"])
    X = np.column_stack([f["x"], f["gas"], f["co2"], np.ones(len(f))])
    coef, *_ = np.linalg.lstsq(X, f["price"].values, rcond=None)
    return {"naive": naive, "fuel_controlled": float(coef[0])}


def fit_fringe(df: pd.DataFrame, ngrid: int = NGRID) -> pd.DataFrame:
    """p₀(x) 用保序迴歸(單調遞增),再微分得局部 λ(x)。回傳格點上的 x / p₀ / lam_local。

    為什麼不用「分箱中位數再差分」:那是對雜訊取微分,40 箱會有 8 箱跑出 λ<0。
    供給曲線向下傾斜在經濟上不可能,所以那不是訊號是雜訊,而且它剛好污染最稀缺、
    樣本最薄、我們最在意的那一端。保序迴歸把「單調遞增」當硬約束丟給估計式,
    雜訊被投影掉,得到的曲線可以直接微分。

    保序迴歸的解是**階梯函數**(平台+跳點),所以微分完是尖刺的,有些格點會剛好落在
    平台上得到 λ=0——那是估計式的結構假象,不是「這裡價格衝擊真的是零」。故對 λ 做
    一次窄窗滾動平均;p₀ 不動(它本身就該是階梯,單調性要保住)。

    ponytail: 端點用 0.5% / 99.5% 分位裁掉,尾巴樣本太薄、保序迴歸在那裡會出長平段。"""
    m = df.dropna(subset=["price", "x"])
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(
        m["x"], m["price"]
    )
    grid = np.linspace(m["x"].quantile(0.005), m["x"].quantile(0.995), ngrid)
    p0 = iso.predict(grid)
    # 平段上 np.gradient 會吐 -0.0/-1e-17;負斜率在這裡永遠是誤差不是訊號
    lam = np.clip(np.gradient(p0, grid), 0.0, None)
    lam = pd.Series(lam).rolling(5, center=True, min_periods=1).mean().to_numpy()
    return pd.DataFrame({"x": grid, "p0": p0, "lam_local": lam})


def lambda_at(x, fringe: pd.DataFrame):
    """給殘餘負載 x,回傳該點的局部 λ(x)(線性內插,超出範圍夾到端點)。

    注意這是**局部**斜率:p ≈ p₀ + λ(x)·Q 只在 Q 小到不會沿曲線跑遠時成立。
    GW 級車隊要改成直接查 p₀(x+Q)(見模組 docstring「未做」)。"""
    return np.interp(x, fringe["x"].values, fringe["lam_local"].values)


def fringe_by_fuel(df: pd.DataFrame) -> pd.DataFrame:
    """λ 隨燃料 regime 怎麼變:gas 三分位各自估一條 fringe,回傳各自的斜率。
    這是純量 λ 最大的失真來源——merit order 隨燃料價旋轉,不只是平移。"""
    d = df.dropna(subset=["price", "x", "gas"]).copy()
    d["gt"] = pd.qcut(d["gas"], 3, labels=["gas 低", "gas 中", "gas 高"])
    rows = []
    for lab, s in d.groupby("gt", observed=True):
        fr = fit_fringe(s)
        rows.append(
            {
                "regime": lab,
                "gas_median": s["gas"].median(),
                "ols_slope": float(np.polyfit(s["x"], s["price"], 1)[0]),
                "lam_median": float(np.median(fr["lam_local"])),
                "lam_max": float(fr["lam_local"].max()),
            }
        )
    return pd.DataFrame(rows)


def explained_variance(df: pd.DataFrame) -> dict:
    """act 被基本面解釋多少:R² 逐步加特徵。剩下的 = 市場力/進口/天氣候選。
    全步驟鎖同一批樣本(所有欄都非空)→ R² 巢狀可比、單調(否則 co2 只從 2021 起,
    每步 dropna 樣本不同,R² 會假性下降)。"""
    steps = [
        ("殘餘 x", ["x"]),
        ("+gas", ["x", "gas"]),
        ("+co2", ["x", "gas", "co2"]),
        ("+德residual", ["x", "gas", "co2", "de_x"]),
    ]
    m = df.dropna(subset=["price", "x", "gas", "co2", "de_x"])  # 一次固定樣本
    y = m["price"].values
    out = {}
    for name, cols in steps:
        X = np.column_stack([m[c] for c in cols] + [np.ones(len(m))])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[name] = 1 - (y - X @ coef).var() / y.var()
    return out


def _figures(df: pd.DataFrame, fringe: pd.DataFrame, lam: dict, area: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(FIGDIR, exist_ok=True)
    m = df.dropna(subset=["price", "x"])

    # fig1: 散佈 + fringe p₀(x) + 純量 λ 直線(看直線近似有多爛)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(m["x"], m["price"], s=2, alpha=0.05, color="gray")
    ax.plot(
        fringe["x"], fringe["p0"], "-", lw=2, color="C0", label="fringe p0(x) isotonic"
    )
    xr = np.array([m["x"].min(), m["x"].max()])
    p_at0 = np.interp(0, fringe["x"], fringe["p0"])
    ax.plot(
        xr,
        p_at0 + lam["fuel_controlled"] * xr,
        "--",
        color="C3",
        label=f"scalar lambda={lam['fuel_controlled']:.3f}",
    )
    ax.set(
        xlabel="residual load x (MW)",
        ylabel="price (EUR/MWh)",
        title=f"{area} fringe: hockey-stick vs scalar-lambda line",
        ylim=(-100, 400),
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{FIGDIR}/fringe_{area}.png", dpi=110)

    # fig2: 局部 λ_h(斜率的曲棍球桿)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(fringe["x"], fringe["lam_local"], "-", lw=2, color="C2")
    ax.axhline(
        lam["fuel_controlled"],
        ls="--",
        color="C3",
        label=f"scalar lambda={lam['fuel_controlled']:.3f}",
    )
    ax.set(
        xlabel="residual load x (MW)",
        ylabel="local lambda(x) = dp0/dx",
        title=f"{area} local slope (isotonic): the scalar flattens it",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{FIGDIR}/lambda_local_{area}.png", dpi=110)

    # fig3: fringe 隨 gas 三分位平移
    fig, ax = plt.subplots(figsize=(8, 5))
    fg = df.dropna(subset=["price", "x", "gas"]).copy()
    fg["gt"] = pd.qcut(fg["gas"], 3, labels=["gas low", "gas mid", "gas high"])
    for lab, sub in fg.groupby("gt", observed=True):
        fr = fit_fringe(sub)
        ax.plot(fr["x"], fr["p0"], "-", lw=2, label=lab)
    ax.set(
        xlabel="residual load x (MW)",
        ylabel="p0(x) (EUR/MWh)",
        title=f"{area} same residual, higher fuel -> fringe shifts up",
        ylim=(-50, 300),
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{FIGDIR}/fringe_by_gas_{area}.png", dpi=110)

    plt.close("all")


def demo() -> None:
    # 合成一條凸的 fringe(曲棍球桿)+ 大雜訊,驗證估計式抓得回真斜率、且不吐負值
    rng = np.random.default_rng(0)
    x = rng.uniform(-2000, 3500, 20000)
    price = 20 + 0.01 * x + 8e-6 * np.clip(x, 0, None) ** 2 + rng.normal(0, 25, len(x))
    df = pd.DataFrame({"price": price, "x": x, "gas": 30.0, "co2": 70.0, "de_x": 0.0})
    fr = fit_fringe(df)
    # ① 供給曲線不會向下傾斜。這條就是舊版分箱差分掛掉的地方(40 箱有 8 箱 λ<0)。
    assert (fr["lam_local"] >= -1e-9).all(), (
        f"λ 不得為負,最小 {fr['lam_local'].min():.4f}(供給曲線向下傾斜=估計壞了)"
    )
    assert fr["p0"].is_monotonic_increasing, "p₀(x) 必須單調遞增"
    # ② 曲棍球桿:高殘餘端斜率應顯著大於低殘餘端(真值 0.01 → 0.066)
    lo = fr[fr["x"] < 0]["lam_local"].mean()
    hi = fr[fr["x"] > 2000]["lam_local"].mean()
    assert hi > 2 * lo, f"曲棍球桿:高殘餘 {hi:.3f} 應遠大於低殘餘 {lo:.3f}"
    # ③ 純量 λ 被夾在中間 = 它是平均、兩端都失真(這正是本檔要證明的事)
    sca = scalar_lambda(df)["naive"]
    assert lo < sca < hi, f"純量 λ {sca:.3f} 應夾在局部 [{lo:.3f},{hi:.3f}] 之間"
    assert lambda_at(2500, fr) > sca, "稀缺點局部 λ 應高於全期純量"
    print(
        f"  fringe ok: λ 全域非負、單調;局部 低{lo:.3f} < 純量{sca:.3f} < 高{hi:.3f}(純量抹平兩端)"
    )
    _demo_confounding()


def _demo_confounding() -> None:
    """守住 structural_lambda 的核心主張:單變數斜率會把鄰國效應算到本地頭上。

    合成一個**真值已知**的世界:丹麥風 w 與德國風 z 同源(同一片天氣系統,相關 0.8)。
    價格幾乎完全由德國決定,本地殘餘只有微小的真實效果 TRUE_LAM。
    → 單變數 OLS 應嚴重高估;控制 z 後應收斂回 TRUE_LAM。
    這個測試會在有人把 z(鄰國變數)從特徵集拿掉時失敗。"""
    rng = np.random.default_rng(1)
    n = 20000
    TRUE_LAM = 0.003
    z = rng.normal(0, 1000, n)  # 德國殘餘
    x = 0.8 * z + rng.normal(0, 600, n)  # 本地殘餘:與德國同源
    price = 50 + 0.03 * z + TRUE_LAM * x + rng.normal(0, 5, n)  # 價幾乎由德國定
    naive = float(np.polyfit(x, price, 1)[0])  # 單變數:混淆
    A = np.column_stack([x, z, np.ones(n)])
    partial = float(np.linalg.lstsq(A, price, rcond=None)[0][0])  # 偏效果:控制 z
    assert naive > 4 * TRUE_LAM, f"單變數應嚴重高估,得 {naive:.4f}"
    assert abs(partial - TRUE_LAM) < 5e-4, f"控制鄰國後應收斂回真值,得 {partial:.4f}"
    print(
        f"  混淆 ok: 真值 {TRUE_LAM:.4f} → 單變數 {naive:.4f}"
        f"(高估 {naive / TRUE_LAM:.0f}×)、控制鄰國 {partial:.4f}"
    )


def main() -> None:
    demo()
    area = (sys.argv[1] if len(sys.argv) > 1 else "DK1").upper()
    df = load_state(area)
    lam = scalar_lambda(df)
    fringe = fit_fringe(df)
    ev = explained_variance(df)

    print(
        f"\n=== {area}  {len(df):,} 小時  {df.timestamp_utc.min().date()} → "
        f"{df.timestamp_utc.max().date()} ===\n"
    )
    print("【單變數 λ(舊估計,有混淆)】")
    print(f"  裸斜率 price~x            : {lam['naive']:.4f} €/MWh per MW")
    note = "  ← v2-v4 舊版用的 0.037 就是這個" if area == "DK1" else ""
    print(f"  控 gas+co2 後殘餘斜率     : {lam['fuel_controlled']:.4f}{note}")
    print("  只控燃料,沒控鄰國 → 把丹麥/德國的天氣相關性算到本地頭上。\n")

    sl = structural_lambda(area)
    print("【結構 λ(多變數偏導數)← 模擬器該用的】")
    print(
        f"  中位 {sl['lam'].median():.4f}   IQR [{sl['lam'].quantile(0.25):.4f}, "
        f"{sl['lam'].quantile(0.75):.4f}]   p95 {sl['lam'].quantile(0.95):.4f}"
    )
    print(
        f"  比單變數小 {lam['fuel_controlled'] / sl['lam'].median():.0f} 倍。"
        "差額是混淆:丹麥風大的日子北德通常也風大(同一片天氣系統),\n"
        "  單變數把德國的效果全記到本地殘餘負載頭上。偏導數固定鄰國/燃料才是\n"
        "  「我多買 1MW」該問的 ceteris paribus 實驗。\n"
    )
    sl_g = sl.assign(gt=pd.qcut(sl["gas"], 3, labels=["gas 低", "gas 中", "gas 高"]))
    print("  分燃料:", end="")
    for g, s in sl_g.groupby("gt", observed=True):
        print(f"  {g} {s['lam'].median():.4f}", end="")
    print("\n")

    print("【λ(x):沿殘餘負載的局部斜率】保序迴歸,x 分位取樣")
    print(f"  {'x (MW)':>12}{'p₀ €':>9}{'λ(x)':>9}{'vs 純量':>9}")
    m = df.dropna(subset=["x"])
    for q in (0.05, 0.25, 0.50, 0.75, 0.90, 0.97):
        xq = m["x"].quantile(q)
        i = int(np.argmin(np.abs(fringe["x"].values - xq)))
        r = fringe.iloc[i]
        print(
            f"  {r['x']:>12,.0f}{r['p0']:>9.1f}{r['lam_local']:>9.4f}"
            f"{r['lam_local'] / lam['fuel_controlled']:>8.1f}×   (x 的 {q:.0%} 分位)"
        )
    print(
        f"  λ(x) 範圍 [{fringe['lam_local'].min():.4f}, {fringe['lam_local'].max():.4f}]"
        f",純量 {lam['fuel_controlled']:.4f} 是它的一個平均。\n"
    )

    print("【λ 隨燃料 regime 變】← 比 x 維度更大的失真來源")
    fb = fringe_by_fuel(df)
    print(
        f"  {'regime':<8}{'gas 中位 €':>11}{'OLS 斜率':>10}{'λ 中位':>9}{'λ 最陡':>9}"
    )
    for _, r in fb.iterrows():
        print(
            f"  {r['regime']:<8}{r['gas_median']:>11.1f}{r['ols_slope']:>10.4f}"
            f"{r['lam_median']:>9.4f}{r['lam_max']:>9.4f}"
        )
    lo, hi = fb["ols_slope"].iloc[0], fb["ols_slope"].iloc[-1]
    print(
        f"  燃料貴時 fringe 陡 {hi / lo:.1f} 倍(火力在邊際、merit order 陡段)。\n"
        "  純量 λ 同時抹平 x 與燃料兩個維度,而抹掉的主要是燃料那個。\n"
    )

    print("【act 被基本面解釋多少(R²)】固定樣本,巢狀可比")
    prev = 0.0
    for name, r2 in ev.items():
        print(f"  {name:<12} R²={r2:.3f}  (+{r2 - prev:.3f})")
        prev = r2
    print(
        f"  → 基本面解釋 {prev:.0%},剩 {1 - prev:.0%}。注意這 {1 - prev:.0%} 是"
        "「市場力+進口+天氣+未納入變數」的**上界**,不是市場力。\n"
    )

    _figures(df, fringe, lam, area)
    print(
        f"圖存到 {FIGDIR}/: fringe_{area}.png / lambda_local_{area}.png / fringe_by_gas_{area}.png"
    )


if __name__ == "__main__":
    main()
