"""階段 0 的**完美預知上界** —— 純交易員 10 MW,日前 vs 不平衡價,每期押對邊。

━━━ 這個數字是什麼、不是什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

一個沒有實體資產的交易員,在日前市場建一個部位(買或賣 P MW),交割時全部以不平衡價
反向結算。**完美預知**代表他事前就知道兩個價,於是每一期都押對邊:

    每期利潤 = P × |不平衡價 − 日前價| × Δt

⚠️ 這是**分母不是收益**。真實 agent 押錯邊要付一樣大的代價,所以真實績效是
   「回收了上界的幾 %」。對照 arXiv 2510.16021:10 MW 太陽電廠 DK1 回收 38%、DK2 30%。

━━━ 為什麼要報兩種解析度 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

論文問題是「15 分鐘改制值多少錢」。**比較必須用同一段時間、兩種解析度**
(把 15 分自己聚合成逐時),不能拿改制前後比 —— 那會混進燃料價、裝置量、需求的變化。

逐時版的意思是:agent 一小時只能決定一個部位,所以那小時的報酬是
`P × |該小時不平衡價均值 − 該小時日前價均值| × 1h`。

🔑 **恆等式**:`|mean(dev)| ≤ mean(|dev|)`(三角不等式)→ **15 分版必然 ≥ 逐時版**,
   差額就是「能在小時內換邊」值多少錢。self-check 驗的就是這個,不是驗抄來的數字。

━━━ 用哪一段資料 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

制度期見 `imbalance_regimes.py`。**主結果用乾淨窗口(2025-12-08 起)**:
mFRR EAM 的定價缺陷已永久修好、日前市場也已是 15 分鐘。
更早的期間一併印出來當敏感度,但**不要當主數字**。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from imbalance_regimes import D_AFRR, D_DA15, D_FIX, load_new  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figs" / "trading"

P_MW = 10.0          # 部位大小,對齊 arXiv 2510.16021 的 10 MW 太陽電廠
HOURS_PER_YEAR = 8760.0


def oracle(dev: pd.Series, dt_h: float, p_mw: float = P_MW) -> dict:
    """完美預知的總利潤與年化值。dev = 不平衡價 − 日前價(EUR/MWh)。"""
    a = dev.abs().dropna()
    total = p_mw * a.sum() * dt_h                      # EUR
    span_h = len(a) * dt_h
    return {"n": len(a), "涵蓋小時": span_h,
            "平均|dev|": a.mean(),
            "總利潤 k€": total / 1e3,
            "年化 k€": total / span_h * HOURS_PER_YEAR / 1e3}


def windows(n: pd.DataFrame) -> dict[str, pd.DataFrame]:
    end = n.index.max() + pd.Timedelta("1min")
    return {
        "★乾淨窗口 2025-12-08→": n[(n.index >= D_FIX) & (n.index < end)],
        "日前轉 15 分之後 2025-10-01→": n[(n.index >= D_DA15) & (n.index < end)],
        "aFRR 進定價之後 2025-03-18→": n[(n.index >= D_AFRR) & (n.index < end)],
    }


def both_resolutions(d: pd.DataFrame) -> tuple[dict, dict]:
    """同一段資料的 15 分版與逐時版。逐時版是**先把兩個價各自聚合成逐時再相減**
    —— 價格是強度量,聚合用 mean;先相減再聚合會得到同樣的值但語意較不清楚。"""
    dev15 = d["ImbalancePriceEUR"] - d["SpotPriceEUR"]
    imb_h = d["ImbalancePriceEUR"].resample("1h").mean()
    spot_h = d["SpotPriceEUR"].resample("1h").mean()
    cnt = d["ImbalancePriceEUR"].resample("1h").count()
    full = cnt == 4                                     # 只留完整的小時,免得夏令時/缺格灌權重
    return oracle(dev15, 0.25), oracle((imb_h - spot_h)[full], 1.0)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = ["# 階段 0:完美預知上界(純交易員 10 MW)", "",
           f"部位 {P_MW:.0f} MW,每期押對邊,年化 = 總利潤 ÷ 涵蓋小時 × 8760。",
           "**這是分母不是收益。**", ""]
    rows = []
    for area in ("DK1", "DK2"):
        n = load_new(area)
        for label, d in windows(n).items():
            o15, oh = both_resolutions(d)
            rows.append({
                "區": area, "窗口": label,
                "格數": o15["n"], "涵蓋小時": round(o15["涵蓋小時"]),
                "平均|dev| 15分": o15["平均|dev|"], "平均|dev| 逐時": oh["平均|dev|"],
                "年化 k€ 15分": o15["年化 k€"], "年化 k€ 逐時": oh["年化 k€"],
                "15 分多賺 %": (o15["年化 k€"] / oh["年化 k€"] - 1) * 100})
    t = pd.DataFrame(rows)
    rep += [t.to_markdown(index=False, floatfmt=",.1f"), ""]

    main_rows = t[t["窗口"].str.startswith("★")]
    rep += ["## 主結果(乾淨窗口)", ""]
    for _, r in main_rows.iterrows():
        rep.append(f"- **{r['區']}**:15 分版 **{r['年化 k€ 15分']:,.0f} k€/年** vs "
                   f"逐時版 **{r['年化 k€ 逐時']:,.0f} k€/年** → **+{r['15 分多賺 %']:.1f}%**"
                   f"(涵蓋 {r['涵蓋小時']:,.0f} 小時)")
    rep += ["", "🔴 更早的窗口數字明顯更大,但那段有 mFRR EAM 的定價缺陷"
            "(見 `imbalance_regimes.py`),**不要當主數字**。", ""]

    (OUT / "ORACLE_STAGE0.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))
    print(f"\n→ 已寫出 {OUT/'ORACLE_STAGE0.md'}")


def selfcheck() -> None:
    for area in ("DK1", "DK2"):
        n = load_new(area)
        d = windows(n)["★乾淨窗口 2025-12-08→"]
        o15, oh = both_resolutions(d)

        # ① 三角不等式:小時內能換邊,只可能賺更多,不可能更少。
        assert o15["年化 k€"] >= oh["年化 k€"] - 1e-6, \
            f"{area}: 15 分版 {o15['年化 k€']:.1f} < 逐時版 {oh['年化 k€']:.1f},違反 |mean| ≤ mean|·|"

        # ② 年化的定義要自洽:重算一次總利潤。
        dev = (d["ImbalancePriceEUR"] - d["SpotPriceEUR"]).abs().dropna()
        assert np.isclose(o15["總利潤 k€"], P_MW * dev.sum() * 0.25 / 1e3)

        # ③ 完美預知必須弱優於「永遠只押一邊」的固定策略(它是 oracle 的一個可行解)。
        one_side = abs(P_MW * (d["ImbalancePriceEUR"] - d["SpotPriceEUR"]).sum() * 0.25) / 1e3
        assert o15["總利潤 k€"] >= one_side - 1e-6, f"{area}: oracle 竟輸給固定單邊策略"

        print(f"✓ {area}: 15分 {o15['年化 k€']:,.0f} ≥ 逐時 {oh['年化 k€']:,.0f} k€/年 | "
              f"固定單邊只有 {one_side / o15['總利潤 k€'] * 100:.1f}% → 押對邊才是全部價值")


if __name__ == "__main__":
    selfcheck()
    print()
    main()
