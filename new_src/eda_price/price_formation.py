"""價格形成診斷 — DK1 / DK2

回答三件事:
  A. 「尖峰靠進口 X%」到底怎麼算的,對「尖峰」的定義有多敏感
  B. D1 — 每一條互聯多少小時貼在容量上限(= 這個價區有多少小時真的與鄰國隔開)
  C. D2 — 本地殘餘需求推不推得動本地價格,分「隔開 / 沒隔開」兩群
        兩個版本:只有固定效果(naive) vs 再控制鄰國殘餘需求(ctrl)

🔴 三個已修的資料陷阱(不修會得到錯的數字):
  1. production 從 2025-10 起變成 15 分鐘制 → 混解析度會讓「最高 100 小時」偏向 15 分鐘尖峰
     → 全部先 resample 成逐時
  2. Energinet 的 TotalLoad 有極端壞值(DK1 出現過 964,623 MW)→ 用 >3×中位數 剔除並記錄
  3. 各邊界的容量檔涵蓋期間不同(ntc_*_dk_2 只到 2024-02)→ 每個價區各自取交集並標明

慣例(已用能量平衡驗證):Energinet 的 Exchange* 正值 = 進口進本價區。
"""
from __future__ import annotations
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import interconnectors as ic   # 第三份資料:AF25 表 3 的最大商業容量

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "price_formation"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

GEN = ["Biomass","FossilGas","FossilHardCoal","FossilOil","HydroPower",
       "OtherRenewable","SolarPower","Waste","OnshoreWindPower","OffshoreWindPower"]
EX  = ["ExchangeContinent","ExchangeGreatBelt","ExchangeNordicCountries","ExchangeGreatBritain"]

# 邊界 -> (Energinet 流量欄, 進口方向容量檔, 出口方向容量檔)
# ⚠️ DK1 的 ExchangeNordicCountries 把 NO2 與 SE3 併在一起 → 只能「合計流量 vs 合計容量」
# ⚠️ DK1 對英國(Viking Link, 2023-12-29 上線)沒有容量檔 → 見 VIKING
BORDERS = {
    "DK2": {
        "SE4": ("ExchangeNordicCountries", ["oc_se_4_dk_2"],   ["oc_dk_2_se_4"]),
        "DE":  ("ExchangeContinent",       ["ntc_de_lu_dk_2"], ["ntc_dk_2_de_lu"]),
        "DK1": ("ExchangeGreatBelt",       ["oc_dk_1_dk_2"],   ["oc_dk_2_dk_1"]),
    },
    "DK1": {
        "NO2+SE3": ("ExchangeNordicCountries", ["oc_no_2_dk_1","oc_se_3_dk_1"],
                                               ["oc_dk_1_no_2","oc_dk_1_se_3"]),
        # 🔴 DK1 的 ExchangeContinent = 德國(Jutland) + 荷蘭(COBRAcable) 合計。
        #    已查證:該欄最大 3,345 MW > DE 單獨容量 2,500,但 ≈ DE+NL 的 3,200。
        #    拆不開 -> 只能當成一條合併邊界(與 NO2+SE3 同樣處理)。
        "DE+NL":   ("ExchangeContinent",       ["ntc_de_lu_dk_1","ntc_nl_dk_1"],
                                               ["ntc_dk_1_de_lu","ntc_dk_1_nl"]),
        "DK2":     ("ExchangeGreatBelt",       ["oc_dk_2_dk_1"],   ["oc_dk_1_dk_2"]),
    },
}
NEIGHBOUR = {"DK2": ["se_4", "de_lu"], "DK1": ["se_3", "de_lu"]}   # 有殘餘需求資料的鄰居
SAT = 0.95                                   # 貼到容量上限的判定門檻
VIKING = pd.Timestamp("2023-12-29", tz="UTC")  # Viking Link 上線,之後 DK1 多一條沒資料的邊界


def load_zone(z: str) -> pd.DataFrame:
    lo = z.lower()
    p = pd.read_parquet(DATA/f"production/production_{lo}_2019-01-01_2026-07-08.parquet")
    p = p.rename(columns={"HourUTC":"t"}).set_index("t").sort_index()
    p = p[GEN + EX + ["TotalLoad"]].resample("1h").mean()          # 陷阱 1
    # 陷阱 2:Energinet 的 TotalLoad 有極端壞值。
    # 用 3×中位數 太鬆(DK2 median 1554 -> 門檻 4662,放過了 4205 與 3273,
    # 而真實尖峰約 2600 —— 排序到第 5 大才變平滑)。改用 1.2×99.9 分位。
    thr = 1.2 * p.TotalLoad.quantile(0.999)
    bad = p.TotalLoad > thr
    p.attrs["bad_load"] = sorted(p.loc[bad, "TotalLoad"].round(0).tolist(), reverse=True)
    p.loc[bad, "TotalLoad"] = np.nan
    p.attrs["n_bad_load"] = int(bad.sum())
    p["gen"] = p[GEN].sum(axis=1, min_count=1)
    p["imp"] = p[EX].sum(axis=1, min_count=1)
    pr = pd.read_parquet(DATA/f"price/price_{lo}_2019-01-01_2026-07-08.parquet")
    pr = pr.rename(columns={"HourUTC":"t","SpotPriceEUR":"price"}).set_index("t")[["price"]]
    rs = pd.read_parquet(DATA/f"residual/residual_{lo}_2019-01-01_2026-07-08.parquet")
    rs = rs.rename(columns={"hour_utc":"t"}).set_index("t")[["residual_mwh"]]
    d = p.join(pr.resample("1h").mean(), how="left").join(rs.resample("1h").mean(), how="left")
    for nb in NEIGHBOUR[z]:
        f = list((DATA/"entsoe/derived").glob(f"residual_{nb}_*.parquet"))
        if f:
            s = pd.read_parquet(f[0]).iloc[:, 0].resample("1h").mean()
            d[f"res_{nb}"] = s.reindex(d.index)
    d.attrs["n_bad_load"] = p.attrs["n_bad_load"]
    d.attrs["bad_load"] = p.attrs["bad_load"]
    return d


def cap_series(names: list[str]) -> pd.Series:
    out = None
    for n in names:
        f = list((DATA/"entsoe").glob(f"{n}_*.parquet"))
        if not f:
            return pd.Series(dtype=float)
        s = pd.read_parquet(f[0]).iloc[:, 0].resample("1h").mean()
        out = s if out is None else out.add(s, fill_value=np.nan)
    return out


# ---------- A ----------
def import_table(d: pd.DataFrame, zone: str) -> pd.DataFrame:
    d = d.dropna(subset=["TotalLoad","imp"])
    win = d[d.index.month.isin([11,12,1,2])]
    defs = {
        "全期(所有小時)":        d,
        "負載前 25%":            d[d.TotalLoad >= d.TotalLoad.quantile(.75)],
        "負載前 10%":            d[d.TotalLoad >= d.TotalLoad.quantile(.90)],
        "負載前 1%":             d[d.TotalLoad >= d.TotalLoad.quantile(.99)],
        "負載最高 100 小時":     d.nlargest(100, "TotalLoad"),
        "冬季(11-2月)全部":      win,
        "冬季負載最高 100 小時": win.nlargest(100, "TotalLoad"),
    }
    rows = [dict(價區=zone, 定義=k, 小時數=len(s),
                 平均負載_MW=s.TotalLoad.mean(), 平均淨進口_MW=s.imp.mean(),
                 進口佔負載=s.imp.mean()/s.TotalLoad.mean(),
                 淨進口的小時比例=(s.imp > 0).mean()) for k, s in defs.items()]
    return pd.DataFrame(rows)


# ---------- B ----------
def congestion(d: pd.DataFrame, zone: str, basis: str = "hourly"):
    """basis="hourly" → ②b 逐時公布容量(ENTSO-E);basis="max" → ②a 固定最大容量(AF25 表 3)。

    兩個都要跑:②b 概念上正確(市場是對著提供容量出清的),但 DK2 對德那一支
    漏了 Kriegers Flak;②a 完整但忽略檢修削減 → **拿來夾,不是拿來選**。
    """
    util, meta = {}, []
    for name, (col, imp_caps, exp_caps) in BORDERS[zone].items():
        if basis == "max":
            ai, ae = ic.cap(zone, col)
            ci = pd.Series(ai, index=d.index); ce = pd.Series(ae, index=d.index)
        else:
            ci, ce = cap_series(imp_caps), cap_series(exp_caps)
        if ci.empty or ce.empty:
            meta.append(dict(價區=zone, 邊界=name, 狀態="無容量資料")); continue
        f = d[col]
        ci, ce = ci.reindex(d.index), ce.reindex(d.index)
        cap = pd.Series(np.where(f >= 0, ci, ce), index=d.index).replace(0, np.nan)
        u = (f.abs() / cap).where(f.notna() & cap.notna())
        util[name] = u
        meta.append(dict(價區=zone, 邊界=name, 狀態="ok", 有容量資料的小時=int(u.notna().sum()),
                         涵蓋期間=f"{str(u.dropna().index.min())[:10]} → {str(u.dropna().index.max())[:10]}",
                         # 分母只能是「有容量資料」的小時,否則會被 NaN 稀釋
                         滿載小時佔比=float((u.dropna() >= SAT).mean())))
    U = pd.DataFrame(util)
    sat = (U >= SAT).astype(float); sat[U.isna()] = np.nan
    n_known = U.notna().sum(axis=1)
    full = n_known == U.shape[1]                       # 只在「每條邊界都有資料」的小時判定
    iso = (sat.sum(axis=1) == U.shape[1]).where(full)
    return U, iso, pd.DataFrame(meta)


# ---------- C ----------
def absorb(df: pd.DataFrame, cols, groups, n_iter=8) -> pd.DataFrame:
    x = df[cols].astype(float).copy()
    keys = [pd.Series(np.asarray(g), index=df.index) for g in groups]
    for _ in range(n_iter):
        for k in keys:
            x = x - x.groupby(k).transform("mean")
    return x


def within_ols(df: pd.DataFrame, y: str, xs: list[str]):
    """雙向固定效果(日 + 月×時)後的 OLS,標準誤以「日」群集。回傳第一個 x 的係數。"""
    df = df.dropna(subset=[y] + xs)
    if len(df) < 50:
        return np.nan, np.nan, len(df), df.index.normalize().nunique()
    day = df.index.normalize()
    mh = pd.Index(df.index.month.astype(str) + "_" + df.index.hour.astype(str))
    # 🔴 自由度防護:固定效果吸收掉的參數數量可能超過樣本數,那時估計是退化的。
    #    不擋的話會得到殘差≈0、標準誤假性極小、t 值虛高。
    k = day.nunique() + pd.Index(mh).nunique() + len(xs)
    if len(df) - k < 30:
        return np.nan, np.nan, len(df), day.nunique()
    z = absorb(df, [y] + xs, [day, mh])
    Y, X = z[y].values, z[xs].values
    XtX = X.T @ X
    if np.linalg.matrix_rank(XtX) < X.shape[1]:
        return np.nan, np.nan, len(df), day.nunique()
    inv = np.linalg.inv(XtX)
    b = inv @ (X.T @ Y)
    e = Y - X @ b
    g = pd.DataFrame(X * e[:, None], index=day).groupby(level=0).sum().values
    V = inv @ (g.T @ g) @ inv
    return float(b[0]), float(np.sqrt(V[0, 0])), len(df), day.nunique()


# ---------- D. 借過(transit) ----------
def transit(d: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """把交換拆成「毛進 / 毛出 / 淨 / 借過」。

    借過 = min(毛進, 毛出) —— 同一小時從一條邊界進、從另一條邊界出的量。
    ⚠️ 這是**分區層級的會計構造,不是物理歸屬**。電子不可分辨,
       「哪一度電是給丹麥用的」沒有事實可言。它是借過量的下界。
    """
    F = d[cols]
    I = F.clip(lower=0).sum(axis=1, min_count=1)
    E = (-F).clip(lower=0).sum(axis=1, min_count=1)
    return pd.DataFrame({"load": d.TotalLoad, "gross_in": I, "gross_out": E,
                         "net": I - E, "transit": np.minimum(I, E)}).dropna()


def transit_table(d: pd.DataFrame, cols: list[str], zone: str) -> pd.DataFrame:
    x = transit(d, cols)
    rows = []
    for name, s in [("全期", x), ("負載最高 100 小時", x.nlargest(100, "load"))]:
        rows.append(dict(價區=zone, 樣本=name, 平均負載=s.load.mean(),
                         毛進口=s.gross_in.mean(), 毛出口=s.gross_out.mean(),
                         淨進口=s.net.mean(), 借過=s.transit.mean(),
                         借過佔毛進口=s.transit.mean()/s.gross_in.mean(),
                         同時進出的小時比例=(np.minimum(s.gross_in, s.gross_out) > 10).mean()))
    return pd.DataFrame(rows)


def main():
    zones = {z: load_zone(z) for z in ("DK1", "DK2")}
    # 🔴 壅塞分析只在 FBMC 之前有效:2024-10 北歐改用 flow-based,逐邊界 NTC 不再發布
    zones = {z: d[(d.index >= "2019-10-01") & (d.index < ic.FBMC_START)] for z, d in zones.items()} \
            if False else zones
    rep = ["# 價格形成診斷 — DK1 / DK2", "",
           f"- 滿載門檻:|流量| ≥ **{SAT:.0%}** 的該方向提供容量",
           "- 慣例:Energinet `Exchange*` 正值 = 進口(已用能量平衡驗證,平均殘差 154 MW)",
           "- 已修:15 分鐘制混入(全部 resample 成逐時)",
           f"- TotalLoad 壞值剔除(門檻 = 1.2×99.9分位):DK1 {zones['DK1'].attrs['bad_load']}、"
           f"DK2 {zones['DK2'].attrs['bad_load']} (MW)", ""]

    ta = pd.concat([import_table(zones[z], z) for z in zones], ignore_index=True)
    rep += ["## A. 「尖峰靠進口 X%」對尖峰定義有多敏感", "",
            ta.to_markdown(index=False, floatfmt=".3f"), ""]

    lam_rows, meta_all, U_all, iso_all = [], [], {}, {}
    for z, d in zones.items():
        pre = d[(d.index >= "2019-10-01") & (d.index < ic.FBMC_START)]
        U, iso, meta = congestion(pre, z); meta_all.append(meta)
        U2, iso2, _ = congestion(pre, z, basis="max")
        U_all[z], iso_all[z] = U2, iso2   # 圖一律用 ②a:②b 的 DK2 對德序列漏 Kriegers Flak
        v, v2 = iso.dropna(), iso2.dropna()
        rep += [f"### {z} — 與鄰國隔開的小時", "",
                f"- 判定期間:{str(v.index.min())[:10]} → {str(v.index.max())[:10]}(取該價區所有邊界容量檔的交集)",
                f"- **②b 逐時公布容量:{v.sum():.0f} / {len(v)} = {v.mean():.3%}**",
                f"- **②a 固定最大容量(AF25 表 3):{v2.sum():.0f} / {len(v2)} = {v2.mean():.3%}**",
                f"- 🔑 **真值落在這兩者之間** —— ②b 概念正確但 DK2 對德漏 Kriegers Flak;②a 完整但忽略檢修"]
        if z == "DK1":
            pre = v[v.index < VIKING]
            rep += [f"- ⚠️ Viking Link(對英國)沒有容量檔。只看上線前({str(VIKING)[:10]} 之前):"
                    f"**{pre.sum():.0f} / {len(pre)} = {pre.mean():.2%}**"]
        rep += [""]

        dd = d.join(iso.rename("iso"))
        nb = [f"res_{n}" for n in NEIGHBOUR[z] if f"res_{n}" in d]
        for label, sub in [("與鄰國隔開", dd[dd.iso == True]), ("沒隔開", dd[dd.iso == False])]:
            b0, s0, n0, d0 = within_ols(sub, "price", ["residual_mwh"])
            b1, s1, n1, d1 = within_ols(sub, "price", ["residual_mwh"] + nb)
            lam_rows.append(dict(價區=z, 狀態=label,
                                 λ_只有固定效果=b0, se_naive=s0,
                                 λ_再控制鄰國=b1, se_ctrl=s1,
                                 t_ctrl=b1/s1 if s1 and s1 > 0 else np.nan,
                                 小時數=n1, 天數=d1, 平均價=sub.price.mean()))
    rep += ["## B. D1 — 各邊界滿載佔比", "",
            pd.concat(meta_all, ignore_index=True).to_markdown(index=False, floatfmt=".4f"), ""]
    tl = pd.DataFrame(lam_rows)
    rep += ["## C. D2 — 本地殘餘需求 → 本地價格", "",
            "固定效果:日 + 月×時(交替投影);標準誤以「日」群集。",
            f"控制變數 = 鄰國殘餘需求(DK2:SE4+DE / DK1:SE3+DE)。", "",
            tl.to_markdown(index=False, floatfmt=".4f"), "",
            "⚠️ 「天數」是檢定力的關鍵:日固定效果吸收掉日間變異後,識別只來自**同一天之內**的變動。",
            "⚠️ 這裡的 λ 與簡報頁 6 的 0.0053(S4,控制到邊界容量)**不是同一個量**,不可並列引用。", ""]

    # ---------- 圖 ----------
    plt.rcParams.update({"figure.dpi":140, "font.size":9, "axes.grid":True,
                         "grid.alpha":.25, "axes.spines.top":False, "axes.spines.right":False})
    C = {"DK1":"#1f77b4", "DK2":"#d62728"}

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    qs = np.arange(0, 100, 2)
    for z, d in zones.items():
        s = d.dropna(subset=["TotalLoad","imp"])
        thr = np.percentile(s.TotalLoad, qs)
        ax[0].plot(qs, [s.imp[s.TotalLoad>=t].mean()/s.TotalLoad[s.TotalLoad>=t].mean()*100 for t in thr], color=C[z], label=z)
        ax[1].plot(qs, [s.imp[s.TotalLoad>=t].mean() for t in thr], color=C[z], label=z)
    ax[0].set_ylabel("淨進口 / 負載 (%)"); ax[0].set_title("進口依賴度隨「尖峰」定義而變")
    ax[1].set_ylabel("平均淨進口 (MW)"); ax[1].set_title("絕對量")
    for a in ax: a.set_xlabel("只看負載高於第 q 百分位的小時"); a.axhline(0,color="k",lw=.6); a.legend(frameon=False)
    fig.tight_layout(); fig.savefig(OUT/"01_import_share_vs_peak.png"); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for i, z in enumerate(zones):
        U = U_all[z]; sat = (U >= SAT).astype(float); sat[U.isna()] = np.nan
        n = sat.sum(axis=1).where(U.notna().sum(axis=1) == U.shape[1]).dropna()
        vc = n.value_counts(normalize=True).sort_index()
        ax[i].bar(vc.index, vc.values*100, color=C[z])
        ax[i].set_title(f"{z} — 同時滿載的邊界數(共 {U.shape[1]} 條)")
        ax[i].set_xlabel("滿載邊界數"); ax[i].set_ylabel("小時佔比 (%)")
        for xx, yy in zip(vc.index, vc.values*100):
            ax[i].text(xx, yy, f"{yy:.1f}%", ha="center", va="bottom", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT/"02_n_saturated_borders.png"); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for i, z in enumerate(zones):
        for c in U_all[z].columns:
            s = U_all[z][c].dropna().sort_values(ascending=False).values
            ax[i].plot(np.linspace(0,100,len(s)), np.clip(s,0,1.3), label=c, lw=1.2)
        ax[i].axhline(SAT, color="k", ls="--", lw=.8)
        ax[i].set_title(f"{z} — 各邊界利用率延時曲線"); ax[i].set_xlabel("小時佔比 (%)")
        ax[i].set_ylabel("|流量| / 該方向容量"); ax[i].legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(OUT/"03_border_utilisation.png"); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    for i, z in enumerate(zones):
        d = zones[z].join(iso_all[z].rename("iso"))
        for st, col, mk in [(True,"#d62728","o"), (False,"#4477aa","s")]:
            sub = d[d.iso == st].dropna(subset=["price","residual_mwh"])
            if len(sub) < 100: continue
            day = sub.index.normalize()
            mh = pd.Index(sub.index.month.astype(str)+"_"+sub.index.hour.astype(str))
            zz = absorb(sub, ["price","residual_mwh"], [day, mh])
            g = zz.groupby(pd.qcut(zz.residual_mwh, 12, duplicates="drop"), observed=True).mean()
            ax[i].plot(g.residual_mwh, g.price, mk+"-", color=col, ms=4,
                       label=f"{'隔開' if st else '沒隔開'} (n={len(sub):,})")
        ax[i].set_title(f"{z} — 去掉日與月×時固定效果後"); ax[i].axhline(0,color="k",lw=.5)
        ax[i].axvline(0,color="k",lw=.5); ax[i].set_xlabel("本地殘餘需求偏離 (MW)")
        ax[i].set_ylabel("價格偏離 (EUR/MWh)"); ax[i].legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(OUT/"04_lambda_by_state.png"); plt.close(fig)

    # 圖 5(改)— 進口餘裕。原本的「隔離小時月份分布」在 ②a 下只剩 16 小時,畫了沒有意義。
    # 餘裕 = Σ(該邊界進口方向最大容量 − 目前淨流量);出口中的邊界,停止出口也算餘裕。
    # ⚠️ 這是**上界**:假設每條邊界都能同時開到自己的進口上限,實務上不保證同時可行。
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    for i, z in enumerate(zones):
        d = zones[z]
        cols = [c for c in EX if c in d and d[c].notna().any()]
        sp = sum(ic.cap(z, c)[0] - d[c] for c in cols)
        x = pd.DataFrame({"load": d.TotalLoad, "sp": sp}).dropna()
        for lab, s_, col in [("全期", x, "#888888"),
                             ("冬季 12-2 月", x[x.index.month.isin([12,1,2])], "#4477aa"),
                             ("負載最高 1000h", x.nlargest(1000, "load"), "#d62728")]:
            v = np.sort(s_.sp.values)[::-1]
            ax[i].plot(np.linspace(0, 100, len(v)), v, color=col, label=lab, lw=1.4)
        ax[i].axhspan(993, 1120, color="#d62728", alpha=.15)
        ax[i].text(50, 1057, "生質換熱泵的擺盪規模 993–1,120 MW", fontsize=7, ha="center", color="#a01010")
        ax[i].set_ylim(0, None)
        ax[i].set_title(f"{z} — 剩餘進口餘裕（②a 為分母，上界）")
        ax[i].set_xlabel("有百分之多少的小時餘裕高於此值"); ax[i].set_ylabel("MW")
        ax[i].legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(OUT/"05_import_headroom.png"); plt.close(fig)

    # 圖 6 — 借過隨尖峰定義而變
    tt = pd.concat([transit_table(zones[z], EX, z) for z in zones], ignore_index=True)
    rep += ["## D. 借過(transit)—— 進來的量有多少只是路過", "",
            "借過 = min(毛進口, 毛出口)。⚠️ 分區層級的**會計構造**,不是物理歸屬;是借過量的**下界**。", "",
            tt.to_markdown(index=False, floatfmt=".3f"), ""]
    tt.to_csv(OUT/"transit.csv", index=False)

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    # 尾巴要加密:「負載最高 100 小時」約在 q=99.84,只掃到 98 會看不到崩塌
    qs = np.concatenate([np.arange(0, 98, 2), [98.5, 99, 99.3, 99.6, 99.84]])
    for i, z in enumerate(zones):
        x = transit(zones[z], EX)
        thr = np.percentile(x.load, qs)
        for c, lab, col in [("gross_in","毛進口","#4477aa"), ("gross_out","毛出口","#cc8844"),
                            ("net","淨進口","#000000"), ("transit","借過","#d62728")]:
            ax[i].plot(qs, [x[c][x.load >= t].mean() for t in thr], color=col, label=lab,
                       lw=2 if c in ("net","transit") else 1.2,
                       ls="--" if c == "net" else "-")
        ax[i].axhline(0, color="k", lw=.5)
        ax[i].axvline(99.84, color="grey", ls=":", lw=.8)
        ax[i].text(99.84, ax[i].get_ylim()[1], " 最高\n 100h", fontsize=7, va="top", ha="right", color="grey")
        ax[i].set_title(f"{z} — 交換量的拆解"); ax[i].set_xlabel("只看負載高於第 q 百分位的小時")
        ax[i].set_ylabel("MW"); ax[i].legend(frameon=False, fontsize=8, loc="center left")
    fig.tight_layout(); fig.savefig(OUT/"06_transit_decomposition.png"); plt.close(fig)

    ta.to_csv(OUT/"import_share.csv", index=False)
    tl.to_csv(OUT/"lambda_by_state.csv", index=False)
    pd.concat(meta_all, ignore_index=True).to_csv(OUT/"border_saturation.csv", index=False)
    (OUT/"REPORT.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
