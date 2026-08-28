"""**為什麼日前預測不了不平衡價差** —— 把「沒有訊號」與「訊號會漂移」分開。

━━━ 這支腳本要回答的問題 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

`agent.py` 量到日前 agent 回收 ≈ 0。但「學不動」有兩種病,意義完全不同:

    A **訊號不存在**  關門時看得到的東西裡就是沒有方向的資訊
                      → 換模型、換超參數都沒用,只能換**資訊集**(= 階段 1–3)
    B **訊號會漂移**  資訊在,但關係逐月變化,所以「用過去訓練、預測未來」必敗
                      → 有救:線上學習、更短的重訓週期、regime 偵測

⚠️ `agent.py` 的「in-sample 作弊回收 93.8%」**分不出這兩種** —— 那是**記憶**不是預測
   (同一批列訓練又測試)。要分開必須做**同一段期間內的交叉驗證**。

━━━ 判讀規則(跑之前就定好)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

同期交叉驗證做兩種切法:

    隨機 5 折    鄰近格會落到訓練集 → **偷得到局部自我相關** → 寬鬆上界
    連續區塊 5 折 不偷相鄰資訊 → **誠實的同期上界**

    連續區塊也 ≈ 0 或負  → **病 A:訊號不存在**
    連續區塊明顯 > 0     → **病 B:訊號會漂移**

實測結果是**病 A**,而且第 ① 項給了機制上的理由:dev 的記憶大約一小時就衰減完,
而日前關門在交割前 12–36 小時 —— **等我們被允許看的時候,東西已經不在那裡了。**
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import FEATS, OUT, build_panel, money, oracle_money  # noqa: E402
from imbalance_regimes import D_DA15, D_FIX, load_new  # noqa: E402

TEST = pd.Timestamp("2026-03-01", tz="UTC")
LAGS = [(1, "15 分鐘"), (4, "1 小時"), (96, "1 天"), (192, "2 天 ★可用的最近位置"), (672, "7 天")]


def _r2(y: np.ndarray, p: np.ndarray) -> float:
    return float(1 - np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2))


def _fit(tr, te, target):
    m = lgb.LGBMRegressor(n_estimators=800, learning_rate=0.05, num_leaves=63,
                          subsample=0.8, colsample_bytree=0.8, random_state=0, verbose=-1)
    m.fit(tr[FEATS], tr[target])
    return m.predict(te[FEATS])


def panel(area: str) -> pd.DataFrame:
    d = build_panel(area).dropna(subset=["dev"] + FEATS)
    return d[d.index >= D_DA15]


def acf_table(d: pd.DataFrame) -> pd.DataFrame:
    """dev 的自我相關。**關鍵不是 lag 1 有多大,是 lag 192 還剩多少** —— 那才是我們能用的位置。"""
    return pd.DataFrame([{"落後": lab, "格數": k, "ACF": d["dev"].autocorr(k)} for k, lab in LAGS])


def same_period_cv(d: pd.DataFrame) -> pd.DataFrame:
    """同一段期間內的交叉驗證。兩種切法的差距 = 局部自我相關被偷走的量。"""
    te = d[d.index >= TEST].copy()
    te["absdev"] = te["dev"].abs()
    rows = []
    for target in ("dev", "absdev"):
        oof_r = np.empty(len(te))
        for a, b in KFold(5, shuffle=True, random_state=0).split(te):
            oof_r[b] = _fit(te.iloc[a], te.iloc[b], target)
        n = len(te)
        edges = np.linspace(0, n, 6).astype(int)
        oof_b = np.empty(n)
        for i in range(5):
            m = np.zeros(n, bool)
            m[edges[i]:edges[i + 1]] = True
            oof_b[m] = _fit(te[~m], te[m], target)
        row = {"目標": {"dev": "價差 dev(方向+幅度)", "absdev": "幅度 abs(dev)"}[target],
               "隨機 5 折 R²(寬鬆上界)": _r2(te[target].values, oof_r),
               "連續區塊 5 折 R²(誠實)": _r2(te[target].values, oof_b)}
        row["照區塊版押的回收 %"] = (money(np.sign(oof_b), te["dev"].values)
                                    / oracle_money(te["dev"].values) * 100
                                    if target == "dev" else float("nan"))
        rows.append(row)
    return pd.DataFrame(rows)


def money_concentration(area: str) -> pd.DataFrame:
    """錢集中在多少格上 —— 決定「就算方向對一半也不夠」的程度。"""
    n = load_new(area)
    n = n[n.index >= D_FIX]
    dev = (n["ImbalancePriceEUR"] - n["SpotPriceEUR"]).dropna()
    a = dev.abs().sort_values(ascending=False)
    rows = [{"項目": "dev 恰好為 0(系統剛好平衡)", "值 %": float((dev == 0).mean() * 100)}]
    for k in (0.01, 0.05, 0.10):
        rows.append({"項目": f"最極端的 {k*100:.0f}% 格佔完美預知上界",
                     "值 %": float(a.head(int(len(a) * k)).sum() / a.sum() * 100)})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = ["# 為什麼日前預測不了不平衡價差", "",
           "判讀規則:**同期連續區塊交叉驗證 ≈ 0 → 訊號不存在(病 A);明顯 > 0 → 訊號會漂移(病 B)。**", ""]
    for area in ("DK1", "DK2"):
        d = panel(area)
        rep += [f"## {area}", "",
                "### ① dev 的記憶有多長", "",
                acf_table(d).to_markdown(index=False, floatfmt=",.4f"), "",
                "**記憶大約一小時就衰減完。** 日前關門在交割前 12–36 小時 —— "
                "等我們被允許看的時候(落後 2 天),ACF 已經是 0。", "",
                "### ② 同一段期間內的交叉驗證(決定性實驗)", "",
                same_period_cv(d).to_markdown(index=False, floatfmt=",.4f",
                                              missingval="—"), "",
                "**連續區塊版是負的** → 連同一段期間、同一個分佈、沒有 regime 變化的條件下都學不動。"
                "**→ 病 A:訊號不存在。** 隨機切之所以看起來有 R²,是因為它偷到了鄰近格的相關"
                "(見 ①(lag 1 的 ACF))—— 那個相關在日前用不到。", "",
                "### ③ 錢集中在哪裡", "",
                money_concentration(area).to_markdown(index=False, floatfmt=",.1f"), ""]
        print("\n".join(rep[-12:]))
    (OUT / "WHY_NOT_PREDICTABLE.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"\n→ 已寫出 {OUT/'WHY_NOT_PREDICTABLE.md'}")


def selfcheck() -> None:
    """重新推導兩件事,不是比對抄來的數字。"""
    for area in ("DK1", "DK2"):
        d = panel(area)
        a1, a192 = d["dev"].autocorr(1), d["dev"].autocorr(192)
        # ① 記憶必須是「短的」:15 分鐘的自我相關要遠大於 2 天的。
        assert abs(a1) > 10 * abs(a192), f"{area}: lag1 {a1:.3f} 沒有明顯大於 lag192 {a192:.3f}"
        # ② 2 天處的自我相關必須貼近 0(這是「日前拿不到東西」的直接證據)。
        assert abs(a192) < 0.02, f"{area}: lag192 ACF = {a192:+.4f},不像 0 —— 結論要重看"
        print(f"✓ {area}: ACF lag1 {a1:+.3f} → lag192 {a192:+.4f} → 記憶短、且在可用位置已歸零")


if __name__ == "__main__":
    selfcheck()
    print()
    main()
