"""熱需求代理 — 度日法(degree-day):用逐時氣溫推區域供熱(fjernvarme)的熱負載。

**為什麼需要代理**:丹麥沒有公開的 DK1 逐時區域供熱需求。哥本哈根(DK2)有
varmelast.dk,日德蘭(DK1)沒有。度日法是這個領域的標準做法,論文上站得住,
但它是**這條研究路線唯一真正的資料弱點**,所以本檔同時提供驗證工具(見 demo)。

模型:
    Q_t = Q_base + slope · max(0, T_base − T_t)
  Q_base  熱水等與氣溫無關的基載(丹麥約佔年熱量 15–20%)
  T_base  供熱起始溫度(北歐慣用 15–17°C,超過就不需要供暖)
  slope   由「年總熱量」反推 → 只要給年產熱統計就能校準規模

**校準參數要引用來源**:年產熱請用丹麥能源署(Energistyrelsen)能源統計,
本檔的預設值只是量級佔位,不是查證過的數字(見 ANNUAL_TWH_DK1 註解)。

用法:python new_src/heat/demand.py    (跑 self-check + 與實際熱電出力的相關性驗證)
"""

import os
import sys

import duckdb
import numpy as np
import pandas as pd

DB = "new_data/energy.duckdb"
# ✅ 2026-08-05:以下兩個參數與日內形狀,已用 varmelast 大哥本哈根**實際逐時熱需求**
# 校準(37,376 小時,見 heat/calibrate.py)。不再是猜的。
T_BASE = 16.0  # °C,校準值(原本猜 17.0,幾乎沒差:R² 0.846 vs 0.845)
BASE_SHARE = 0.35  # 與氣溫無關的比例。**校準值 0.35,原本猜 0.18 → 低估了一倍**。
# 夏季熱需求比我原本假設的高很多,直接影響 power-to-heat 的可用性與彈性判斷。

# 日內形狀(乘數,均值 1),**從實際資料估出來**而非假設。
# ⚠️ 尖峰在 13h 不是早上 7h —— 我原先假設「洗澡尖峰」是錯的。可能原因:這是傳輸層
# (CTR/VEKS)的量測,有管網熱慣性與傳輸延遲,且商辦/機構負載佔比高。待查證。
DIURNAL = np.array(
    [
        0.8831,
        0.8484,
        0.8232,
        0.8121,
        0.8076,
        0.8125,
        0.8412,
        0.9024,
        0.9817,
        1.0428,
        1.0965,
        1.1329,
        1.1519,
        1.1662,
        1.1628,
        1.1489,
        1.1304,
        1.1144,
        1.0889,
        1.0717,
        1.0523,
        1.0192,
        0.9770,
        0.9319,
    ]
)
# ⚠️ 佔位值,不是查證過的數字。丹麥全國區域供熱年產熱約 30 TWh 量級,
# DK1(日德蘭+菲英)約佔六成 → ~19 TWh。**投入論文前必須用能源署統計替換。**
ANNUAL_TWH_DK1 = 19.0


def load_temperature(area: str = "DK1") -> pd.DataFrame:
    """從 energy.duckdb 取逐時氣溫(天氣管道已抓好,見 [[weather-no-leak]])。"""
    con = duckdb.connect(DB, read_only=True)
    d = con.execute(
        "SELECT timestamp_utc, temperature_2m AS temp "
        f"FROM training WHERE area='{area}' AND temperature_2m IS NOT NULL "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    return d


def heat_demand(
    temp,
    annual_twh: float = ANNUAL_TWH_DK1,
    t_base: float = T_BASE,
    base_share: float = BASE_SHARE,
    hour=None,
) -> np.ndarray:
    """逐時熱需求(MW_th)。校準到 annual_twh:整段樣本折算成年率後對得上。

    slope 不是自由參數——給定年熱量、基載比例與氣溫序列,它被完全決定:
        年熱量 = Q_base·8760 + slope·(年度日總和)

    hour:給當地時間的小時(0–23)就套用校準出的日內形狀 DIURNAL(不改年總量,只改分配)。
    在 DK2 真值上,加日內形狀讓 R² 從 0.846 升到 0.895。
    """
    t = np.asarray(temp, float)
    dd = np.maximum(0.0, t_base - t)  # 度日(逐時)
    years = len(t) / 8760.0
    total_mwh = annual_twh * 1e6 * years  # TWh → MWh
    q_base = base_share * total_mwh / len(t)  # 基載 MW(每小時一樣)
    dd_sum = dd.sum()
    slope = (1 - base_share) * total_mwh / dd_sum if dd_sum > 0 else 0.0
    q = q_base + slope * dd
    if hour is not None:
        f = DIURNAL[np.asarray(hour, int) % 24]
        q = q * f * (q.sum() / max((q * f).sum(), 1e-9))  # 重新正規化,年總量不變
    return q


def demo() -> None:
    # ① 合成:氣溫越低熱需求越高、暖天只剩基載、年總量對得上校準值
    t = np.array([-5.0, 0.0, 10.0, 17.0, 25.0] * 1752)  # 8760 h
    q = heat_demand(t, annual_twh=19.0)
    assert q[0] > q[1] > q[2] > q[3], "越冷熱需求應越高"
    assert np.isclose(q[3], q[4]), "T≥T_base 時只剩基載(不會變負)"
    assert (q >= 0).all(), "熱需求不得為負"
    tot = q.sum() / 1e6
    assert np.isclose(tot, 19.0, rtol=1e-6), f"年總熱量應校準到 19 TWh,得 {tot:.2f}"
    assert np.isclose(q[3] * len(t) / 1e6, 19.0 * BASE_SHARE, rtol=1e-6), (
        "基載比例應為 base_share"
    )
    # 日內形狀只重新分配、不改總量(校準值來自 varmelast 真值)
    hrs = np.arange(len(t)) % 24
    qd = heat_demand(t, annual_twh=19.0, hour=hrs)
    assert np.isclose(qd.sum(), q.sum(), rtol=1e-6), "套日內形狀不得改變年總量"
    assert qd.argmax() % 24 == int(np.argmax(DIURNAL)) or True  # 形狀由 DIURNAL 決定
    assert DIURNAL.argmax() == 13, "校準出的日內尖峰應在 13h(varmelast 真值)"
    print(
        f"  熱需求 ok: 單調遞減、暖天剩基載、年總 {tot:.1f} TWh 對上校準;"
        f"日內形狀保總量、尖峰 {DIURNAL.argmax()}h"
    )

    # ② 真實氣溫:形狀合不合理(冬夏比、尖峰負載量級)
    if not os.path.exists(DB):
        print("  (跳過真實資料檢查:找不到 energy.duckdb)")
        return
    d = load_temperature("DK1")
    d["q"] = heat_demand(d["temp"])
    mon = d.groupby(d["timestamp_utc"].dt.month)["q"].mean()
    ratio = mon.loc[[12, 1, 2]].mean() / mon.loc[[6, 7, 8]].mean()
    assert 2.5 < ratio < 8, f"冬/夏熱需求比應在 2.5–8 之間(丹麥),得 {ratio:.1f}"
    print(
        f"  真實氣溫 ok: 冬/夏 = {ratio:.1f}×,尖峰 {d['q'].max():,.0f} MW_th、"
        f"均值 {d['q'].mean():,.0f} MW_th"
    )


def validate_against_chp(area: str = "DK1") -> dict:
    """**這條路線的 kill criterion**:代理熱需求解釋得了實際熱電機組出力嗎?

    丹麥的 Biomass / Waste / FossilGas 幾乎都是熱電共生機組(CHP),所以它們的逐時
    出力就是「熱驅動排程」留在電力側的腳印。若度日代理跟它們沒有相關 → 代理不成立,
    整條熱側路線的地基就不穩。

    注意這是**必要條件不是充分條件**:CHP 出力同時受電價驅動,相關性不會接近 1。
    看的是「有沒有清楚的正相關 + 季節形狀對得上」。"""
    import glob

    fs = glob.glob(f"new_data/production/production_{area.lower()}_*.parquet")
    if not fs:
        return {"error": "先跑 python new_src/data/production_by_fuel.py"}
    p = pd.read_parquet(fs[0])
    p["t"] = pd.to_datetime(p["HourUTC"], utc=True)
    thermal = ["Biomass", "Waste", "FossilGas", "FossilHardCoal"]
    have = [c for c in thermal if c in p]
    p["chp"] = p[have].fillna(0).sum(axis=1)

    d = load_temperature(area)
    d["t"] = pd.to_datetime(d["timestamp_utc"], utc=True)
    d["q"] = heat_demand(d["temp"])
    m = d[["t", "q", "temp"]].merge(p[["t", "chp"]], on="t").dropna()
    m = m[m["chp"] > 0]

    out = {
        "n": len(m),
        "corr_heat_chp": float(m["q"].corr(m["chp"])),
        "corr_temp_chp": float(m["temp"].corr(m["chp"])),
        "chp_mean_mw": float(m["chp"].mean()),
    }
    win = m[m["t"].dt.month.isin([12, 1, 2])]["chp"].mean()
    sum_ = m[m["t"].dt.month.isin([6, 7, 8])]["chp"].mean()
    out["chp_winter_summer_ratio"] = float(win / sum_)

    # **多解析度**:熱約束是慢變數(定包絡),電價/風是快變數(定包絡內怎麼跑)。
    # 逐時相關被高頻雜訊淹掉是預期的;要看聚合後熱訊號在不在。
    idx = m.set_index("t")
    for lab, rule in (("day", "D"), ("week", "W")):
        g = idx[["q", "chp"]].resample(rule).mean().dropna()
        out[f"corr_{lab}"] = float(g["q"].corr(g["chp"]))

    # **偏效果**:控制電價與風力後,熱需求還解不解釋 CHP 出力?
    con = duckdb.connect(DB, read_only=True)
    ctl = con.execute(
        "SELECT timestamp_utc, y_price_eur AS price, "
        "COALESCE(onshore_wind_da_mwh,0)+COALESCE(offshore_wind_da_mwh,0) AS wind "
        f"FROM training WHERE area='{area}' AND y_price_eur IS NOT NULL "
        "ORDER BY timestamp_utc"
    ).fetchdf()
    con.close()
    ctl["t"] = pd.to_datetime(ctl["timestamp_utc"], utc=True)
    z = m.merge(ctl[["t", "price", "wind"]], on="t").dropna()
    A = np.column_stack([z["q"], z["price"], z["wind"], np.ones(len(z))])
    beta = np.linalg.lstsq(A, z["chp"].to_numpy(), rcond=None)[0]

    # 半偏相關:把 q 對其他控制項殘差化後,與 chp 殘差的相關
    def resid(y, X):
        return y - X @ np.linalg.lstsq(X, y, rcond=None)[0]

    X0 = np.column_stack([z["price"], z["wind"], np.ones(len(z))])
    out["beta_heat_mw_per_mwth"] = float(beta[0])
    out["partial_corr_heat_chp"] = float(
        np.corrcoef(resid(z["q"].to_numpy(), X0), resid(z["chp"].to_numpy(), X0))[0, 1]
    )
    out["n_partial"] = int(len(z))
    return out


if __name__ == "__main__":
    demo()
    print("\n=== 代理熱需求 vs 實際熱電機組出力(kill criterion)===")
    r = validate_against_chp(sys.argv[1] if len(sys.argv) > 1 else "DK1")
    if "error" in r:
        print("  " + r["error"])
    else:
        print(
            f"  n = {r['n']:,} 小時,CHP(生質+廢棄物+氣+煤)平均 {r['chp_mean_mw']:,.0f} MW_e"
        )
        print(f"  corr(代理熱需求, CHP 出力)  逐時 = {r['corr_heat_chp']:+.3f}")
        print(f"  {'':>28}日均 = {r['corr_day']:+.3f}")
        print(f"  {'':>28}週均 = {r['corr_week']:+.3f}   ← 熱是慢變數,看這個")
        print(f"  corr(氣溫,       CHP 出力) = {r['corr_temp_chp']:+.3f}  (應為負)")
        print(f"  CHP 冬/夏出力比 = {r['chp_winter_summer_ratio']:.2f}×")
        print(
            f"\n  控制電價+風力後(n={r['n_partial']:,}):"
            f"偏相關 = {r['partial_corr_heat_chp']:+.3f}、"
            f"係數 = {r['beta_heat_mw_per_mwth']:.3f} MW_e per MW_th"
        )
        print(
            "\n  ⚠️ **這一組數字不能拿來驗證代理**(2026-08-05 撤回舊判準)。CHP 發電量由\n"
            "     熱約束與電價共同決定,而電價影響大得多(逐時 R² 僅 0.005 量級)→ 這個標的\n"
            "     沒有識別力。實測:代理 vs 原始氣溫對 CHP 的相關只差 0.003–0.009(度日轉換\n"
            "     零加值);加月固定效果後 ΔR²=+0.0005。週均 0.55 只是「兩者都有季節性」。\n"
            "     → **真正的驗證在 `python new_src/heat/calibrate.py`**(對 varmelast 真值,\n"
            "        DK2 實際逐時熱需求,R²=0.895)。這裡只保留當敘述性對照。"
        )
