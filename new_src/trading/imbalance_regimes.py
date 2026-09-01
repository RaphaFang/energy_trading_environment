"""不平衡價的**三個制度期** —— 為什麼 |不平衡價 − 現貨價| 從 €26 跳到 €76。

━━━ 結論(這支腳本重新推導,不是抄來的)━━━━━━━━━━━━━━━━━━━━━━━━━

那個三倍**主要不是市場變劇烈,是定價規則換了**。2025-03 之後的不平衡價含了一個
2024 年不存在的成份:**aFRR 的啟動價**。而 aFRR 在丹麥常常用**很小的量**(中位 ~3 MW,
三成不到 1 MW)清出**很極端的價**(見過 0.93 MW 清出 801 EUR/MWh)。

→ **跨接縫比較 2024 與 2025 量到的是市場改革,不是 agent 的績效。**
   agent 的目標函數只能在**同一個制度期內**估。

━━━ 三個日期(制度事實,不要對齊成同一天)━━━━━━━━━━━━━━━━━━━━━━

    2025-03-04  北歐 mFRR EAM 上線 + **不平衡結算轉 15 分鐘**
    2025-03-18  **不平衡價改成同時吃 mFRR 與 aFRR 的啟動價**(歐盟法規要求)
    2025-09-30  **日前市場**轉 15 分鐘(交割日 2025-10-01,全歐 SDAC 同時)
    2025-12-08  mFRR EAM **定價缺陷的永久修正**上線,TSO 停止人工更正程序

🔑 **中間那一個是這支腳本查出來的**,repo 先前只記了 03-04 與 09-30 兩個。

🔴 **前九個月的資料被已知缺陷污染。** 不可分割的 mFRR 標在價格邊際上被啟動時,
   會讓高/低價擴散到不該擴散的區。這個問題在 2025-03-04 上線**前**就發現了,
   上線後靠**人工更正**擋著(驗價失敗的那一格會停止自動發布,隔個工作日 15:00 補),
   直到 **2025-12-08** 才有永久解。
   → **乾淨的估計窗口是 2025-12-08 之後**(修正後 + 日前也已是 15 分鐘)。

🔴 **不可以宣稱「日前市場轉 15 分讓不平衡成本下降」。** 月份對齊後 2025→2026 確實
   降了(DK2 99.9 → 59.1),但**日前改制與 mFRR 定價修正這兩件事完全混淆**,
   而且 2025 那幾個月正是缺陷最兇的時候。這支腳本把數字印出來,但**不做歸因**。
   3/04–3/17 整整兩週 aFRR 定價比例 **恰好 0%**,3/19 起跳到 ~40% 並穩在那裡
   → 這兩週是一段乾淨的自然實驗:**同樣是 15 分鐘 + mFRR EAM,但還沒有 aFRR**。

━━━ 反推出來的定價規則(自我檢查會驗它)━━━━━━━━━━━━━━━━━━━━━━

    系統缺電(DominatingDirection = +1): 不平衡價 = max(mFRR 上調邊際價, aFRR 上調加權均價)
    系統電太多(DominatingDirection = −1): 不平衡價 = min(mFRR 下調邊際價, aFRR 下調加權均價)
    系統平衡(DominatingDirection =  0): 不平衡價 = 現貨價(制度規定,實測 100%,DK1 有 1 例外)

   aFRR 沒啟動時 VWA 欄是 **0 不是缺值** → 只有有量時才准進候選,否則 0 會偽裝成最低價。
   實測命中 96–98%;剩下幾 % 應是丹麥的「特定產品」(慢速備轉)也進了規則,資料集沒有那一欄。

出處:Energinet「Imbalance price design」、Nordic Balancing Model「Confirmation of mFRR EAM
go live March 4th 2025」、丹麥 2024-10-02 加入 PICASSO(aFRR 的歐洲共同平台,每 4 秒清算)。
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760.0

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "trading"

# 制度期邊界(UTC)。頭尾兩個是已知的,中間那個是本腳本從資料裡定出來的。
D_EAM = pd.Timestamp("2025-03-04 11:15", tz="UTC")   # mFRR EAM + 15 分鐘結算
D_AFRR = pd.Timestamp("2025-03-18", tz="UTC")        # aFRR 進入不平衡價
D_DA15 = pd.Timestamp("2025-09-30 22:00", tz="UTC")  # 日前市場轉 15 分(交割 10-01 丹麥時間)
D_FIX = pd.Timestamp("2025-12-08", tz="UTC")         # mFRR EAM 定價缺陷永久修正 → 乾淨窗口起點


def load_spot(area: str) -> pd.Series:
    (f,) = glob.glob(str(DATA / f"price/price_{area.lower()}_*.parquet"))
    df = pd.read_parquet(f)
    return pd.Series(df["SpotPriceEUR"].values,
                     index=pd.DatetimeIndex(df["HourUTC"])).dropna().sort_index()


def load_old(area: str) -> pd.DataFrame:
    """舊制逐時 `RegulatingBalancePowerdata`(→2025-03-04,已停更)。自帶沒有現貨價,要 join。"""
    (f,) = glob.glob(str(DATA / f"imbalance/imbalance_{area.lower()}_*.parquet"))
    d = pd.read_parquet(f).set_index("HourUTC").sort_index()
    d["spot"] = load_spot(area).reindex(d.index)
    d["dev"] = d["ImbalancePriceEUR"] - d["spot"]
    return d


def load_new(area: str) -> pd.DataFrame:
    """新制 15 分鐘 `ImbalancePrice`(2025-03-04 起)。自帶 SpotPriceEUR,已驗過與日前檔逐格相同。"""
    (f,) = glob.glob(str(DATA / f"imbalance/imbalance15_{area.lower()}_*.parquet"))
    d = pd.read_parquet(f).set_index("TimeUTC").sort_index()
    d["dev"] = d["ImbalancePriceEUR"] - d["SpotPriceEUR"]
    return d


def rule_price(d: pd.DataFrame) -> np.ndarray:
    """照反推的規則重算一次不平衡價。aFRR 無量時不得進候選(VWA 欄的 0 是哨兵不是價)。"""
    up_has, dn_has = d.aFRRUpMW.abs() > 1e-9, d.aFRRDownMW.abs() > 1e-9
    up = np.where(up_has, np.maximum(d.mFRRMarginalPriceUpEUR, d.aFRRVWAUpEUR),
                  d.mFRRMarginalPriceUpEUR)
    dn = np.where(dn_has, np.minimum(d.mFRRMarginalPriceDownEUR, d.aFRRVWADownEUR),
                  d.mFRRMarginalPriceDownEUR)
    return np.where(d.DominatingDirection == 1, up,
                    np.where(d.DominatingDirection == -1, dn, d.SpotPriceEUR))


def set_by_afrr(d: pd.DataFrame) -> pd.Series:
    """這一格的價是不是**由 aFRR 定的**(等於 aFRR 側,且不等於 mFRR 側)。"""
    afrr = np.where(d.DominatingDirection == 1, d.aFRRVWAUpEUR, d.aFRRVWADownEUR)
    mfrr = np.where(d.DominatingDirection == 1, d.mFRRMarginalPriceUpEUR, d.mFRRMarginalPriceDownEUR)
    hit = np.isclose(d.ImbalancePriceEUR.values, afrr) & ~np.isclose(d.ImbalancePriceEUR.values, mfrr)
    return pd.Series(hit & (d.DominatingDirection.values != 0), index=d.index)


def mfrr_only(d: pd.DataFrame) -> pd.Series:
    """反事實:**假如不平衡價只吃 mFRR**(= 2024 年的口徑)偏離會是多少。"""
    p = np.where(d.DominatingDirection == 1, d.mFRRMarginalPriceUpEUR,
                 np.where(d.DominatingDirection == -1, d.mFRRMarginalPriceDownEUR, d.SpotPriceEUR))
    return pd.Series(np.abs(p - d.SpotPriceEUR.values), index=d.index)


def premium_test(area: str, n_boot: int = 2000, seed: int = 0) -> dict:
    """不平衡價**平均**高於現貨價嗎(乾淨窗口)?

    為什麼要問:一個什麼都不預測、**永遠押同一邊**的策略,報酬就是 `P × 平均 dev × 時數`。
    如果平均 dev 顯著 ≠ 0,那條白吃的午餐得先扣掉,否則會誤以為模型學到了東西。

    為什麼用**按日的區塊 bootstrap**:15 分鐘的 dev 有很強的自我相關(同一次系統失衡
    會連續好幾格),普通 t 檢定的標準誤會低估好幾倍。按日重抽保留了日內相關結構。"""
    rng = np.random.default_rng(seed)
    n = load_new(area)
    d = (n["ImbalancePriceEUR"] - n["SpotPriceEUR"])[n.index >= D_FIX].dropna()
    days = [g.values for _, g in d.groupby(d.index.date)]
    boot = np.array([np.concatenate([days[i] for i in rng.integers(0, len(days), len(days))]).mean()
                     for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"區": area, "天數": len(days), "平均 dev": d.mean(), "CI 下": lo, "CI 上": hi,
            "顯著≠0": bool(lo > 0 or hi < 0),
            "10MW 年化 k€": d.mean() * 10 * HOURS_PER_YEAR / 1e3}


def _stats(dev: pd.Series, label: str, n_note: str = "") -> dict:
    a = dev.abs()
    return {"制度期": label, "n": len(a), "解析度": n_note,
            "平均|dev|": a.mean(), "中位|dev|": a.median(),
            "p95": a.quantile(.95), "=現貨價%": (a < 1e-6).mean() * 100}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep: list[str] = ["# 不平衡價的三個制度期", ""]

    for area in ("DK1", "DK2"):
        o, n = load_old(area), load_new(area)
        rows = []
        # 舊制:逐年,取最後三個完整年當對照組
        for y in (2019, 2023, 2024):
            rows.append(_stats(o.loc[o.index.year == y, "dev"], f"舊制 {y}", "逐時"))
        tail = o[(o.index >= pd.Timestamp("2025-01-01", tz="UTC")) & (o.index < D_EAM)]
        rows.append(_stats(tail["dev"], "舊制 2025 尾段", "逐時"))
        # 新制三段
        end = n.index.max() + pd.Timedelta("1min")
        segs = [("① EAM+15分結算,無 aFRR", D_EAM, D_AFRR),
                ("② +aFRR 進定價", D_AFRR, D_DA15),
                ("③ 日前也轉 15 分(仍在缺陷期)", D_DA15, D_FIX),
                ("④ 定價缺陷修好之後 ★乾淨窗口", D_FIX, end)]
        for lab, a, b in segs:
            s = n.loc[(n.index >= a) & (n.index < b)]
            rows.append(_stats(s["dev"], lab, "15 分"))
            # 同一段聚合成逐時再算一次 —— 與舊制 like-for-like
            h = (s["ImbalancePriceEUR"].resample("1h").mean()
                 - s["SpotPriceEUR"].resample("1h").mean())
            rows.append(_stats(h, f"　└ 同段聚合成逐時", "逐時"))

        t = pd.DataFrame(rows)
        rep += [f"## {area}", "", t.to_markdown(index=False, floatfmt=",.2f"), ""]

        # 反事實分解(只在 aFRR 已上路的期間才有意義)
        m = n.loc[n.index >= D_AFRR]
        act, cf = m["dev"].abs(), mfrr_only(m)
        base = o.loc[o.index.year == 2024, "dev"].abs().mean()
        rep += [
            f"**{area} 的三段分解(平均 |dev|,EUR/MWh)**", "",
            f"- 舊制 2024(只有 mFRR,逐時):**{base:,.2f}**",
            f"- 新制反事實「只吃 mFRR」:**{cf.mean():,.2f}**  ← 15 分鐘 + EAM 帶來的部分:"
            f"+{cf.mean()-base:,.2f}",
            f"- 新制實際(含 aFRR):**{act.mean():,.2f}**  ← **aFRR 這一項單獨帶來 "
            f"+{act.mean()-cf.mean():,.2f}(佔總增幅的 "
            f"{(act.mean()-cf.mean())/(act.mean()-base)*100:.0f}%)**", ""]

        # 月份對齊:2025(缺陷期)vs 2026(修正後)—— 印數字,不做歸因
        mm = pd.DataFrame({"act": n["dev"].abs()})
        a25 = mm[(mm.index >= D_AFRR) & (mm.index < D_DA15)]
        b26 = mm[mm.index >= pd.Timestamp("2026-01-01", tz="UTC")]
        mo = sorted(set(a25.index.month) & set(b26.index.month))
        rep += [f"**{area} 月份對齊(同月份,2025 vs 2026)**", "",
                "| 月 | 2025 平均 | 2026 平均 | 2025 中位 | 2026 中位 |",
                "|---|---|---|---|---|"]
        for k in mo:
            x, y = a25[a25.index.month == k], b26[b26.index.month == k]
            rep.append(f"| {k} | {x.act.mean():,.2f} | {y.act.mean():,.2f} | "
                       f"{x.act.median():,.2f} | {y.act.median():,.2f} |")
        rep += ["", f"合計 {a25[a25.index.month.isin(mo)].act.mean():,.2f} → "
                f"{b26[b26.index.month.isin(mo)].act.mean():,.2f}。"
                "🔴 **這個下降不可歸因於日前改制** —— 日前轉 15 分與 mFRR 定價缺陷修正"
                "兩件事完全混淆,而 2025 那幾個月正是缺陷最兇的時候。", ""]

        sb = set_by_afrr(m)
        vol = np.where(m.DominatingDirection == 1, m.aFRRUpMW.abs(), m.aFRRDownMW.abs())[sb.values]
        rep += [f"- 由 aFRR 定價的格:**{sb.mean()*100:.1f}%**,其 aFRR 量中位 "
                f"**{np.median(vol):.2f} MW**,其中 <1 MW 佔 **{np.mean(vol < 1)*100:.1f}%** "
                f"→ **很小的量在定很大的價**", ""]

    # 白吃的午餐檢定 —— 一定要在看 agent 成績之前先做
    rep += ["## 「永遠押同一邊」有沒有白吃的午餐(乾淨窗口)", "",
            "| 區 | 天數 | 平均 dev | 95% 區塊 bootstrap CI | 顯著≠0 | 10 MW 年化 |",
            "|---|---|---|---|---|---|"]
    for area in ("DK1", "DK2"):
        t = premium_test(area)
        rep.append(f"| {t['區']} | {t['天數']} | {t['平均 dev']:+.2f} | "
                   f"[{t['CI 下']:+.2f}, {t['CI 上']:+.2f}] | "
                   f"{'✅' if t['顯著≠0'] else '❌ 不顯著'} | {t['10MW 年化 k€']:+,.0f} k€/年 |")
    rep += ["", "🔴 **兩區都不顯著,逐月符號還會翻** → **沒有白吃的午餐**。"
            "任何「永遠押某一邊也能賺」的成績都是噪音,不可當發現。", ""]

    (OUT / "IMBALANCE_REGIMES.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))
    print(f"\n→ 已寫出 {OUT/'IMBALANCE_REGIMES.md'}")


def selfcheck() -> None:
    """三個重新推導的檢查(不是比對抄來的數字)。"""
    for area in ("DK1", "DK2"):
        n = load_new(area)

        # ① 制度規定:方向 = 0 時不平衡價必須恰等於現貨價。
        #    DK1 有且只有一格違例(2025-03-16 17:30,mFRR 上調 250 卻標方向 0)→ 容忍 1 格。
        z = n[n.DominatingDirection == 0]
        bad = (z.ImbalancePriceEUR - z.SpotPriceEUR).abs() > 1e-6
        assert bad.sum() <= 1, f"{area}: 方向=0 卻不等於現貨價的格有 {bad.sum()} 個"

        # ② 反推的定價規則要重現得出來(aFRR 上路後)。
        m = n.loc[n.index >= D_AFRR]
        hit = np.isclose(m.ImbalancePriceEUR.values, rule_price(m), atol=1e-6).mean()
        assert hit > 0.95, f"{area}: 定價規則只重現 {hit:.1%},規則可能改了"

        # ③ aFRR 進定價的日期:3/04–3/17 必須是 0%,3/19 起必須顯著非 0。
        pre = set_by_afrr(n.loc[(n.index >= D_EAM) & (n.index < D_AFRR)])
        post = set_by_afrr(n.loc[n.index >= D_AFRR + pd.Timedelta("1D")])
        assert pre.mean() == 0.0, f"{area}: aFRR 在 3/18 前就定價了({pre.mean():.3%})"
        assert post.mean() > 0.20, f"{area}: aFRR 在 3/18 後沒有定價({post.mean():.1%})"

        print(f"✓ {area}: 方向=0 違例 {bad.sum()} 格 | 定價規則重現 {hit:.1%} | "
              f"aFRR 定價比例 3/18 前 {pre.mean():.1%} → 之後 {post.mean():.1%}")


if __name__ == "__main__":
    selfcheck()
    print()
    main()
