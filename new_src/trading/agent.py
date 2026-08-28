"""階段 0 的交易 agent 骨架 —— 用日前關門時真的看得到的東西,決定押哪一邊。

━━━ 交割日 D 的完整時刻表(誰對哪一天、誰在哪一天發布)━━━━━━━━━━━━━

    D−2 12:55  D−1 的日前價出清並公布      ← 所以「落後 1 天的現貨價」在關門時已知
    D−1 12:00  **投標關門**,agent 在此刻決定 D 日全部 96 格的部位  ★ 決策時點
    D−1 12:55  D 日的日前價才公布(15 分制上路後從 12:45 改成 12:55)
    D   00:00  D 日開始交割
    D   逐格後 不平衡價陸續公布(缺陷期驗價失敗的格要**隔個工作日 15:00**)

🔑 **D 日的日前價在關門後 55 分鐘才出來 → 它不是特徵,它是目標的一半。**

━━━ 決策時點決定了特徵能用什麼 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

agent 在 D−1 12:00 替 D 日的每一格決定部位,交割後全部以不平衡價反向結算:

    每格報酬 = 部位(±P MW) × (不平衡價 − 日前價) × 0.25h

🔑 **日前價本身不是特徵** —— 關門時還沒出清。它是目標的一半。
🔑 **價格衍生的特徵一律落後 ≥ 2 天。** 綁死的是**不平衡價**這一側:
   D−1 那天的不平衡價要交割完才有,關門(D−1 12:00)時只到大約 D−1 11:00
   → 目標若是 D 日下午的格,落後 1 天會去拿「還沒發生」的值 = leak。落後 2 天最壞情況
   (目標 D 23:45 → 取 D−2 23:45)仍有 12 小時餘裕。
   缺陷期還要再加一層:驗價失敗的格**隔個工作日 15:00** 才補發(見 `imbalance_regimes.py`)。
   ⚪ 現貨價其實落後 1 天就安全(D−1 的價在 D−2 12:55 就公布了),這裡一起用 2 天只是從嚴。
🔑 **天氣/再生能源只准用 `ForecastDayAhead`**;`Forecast5Hour`/`Forecast1Hour` 是日內欄位,
   在這裡用就是 leak(見 repo 的無 leak 規矩)。這也是留在日前的已知代價:
   arXiv 2510.16021 權重最大的 `forecast_delta` 我們用不了。

━━━ 為什麼看「錢」不看「準」━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

套利只需要**方向對**。預測 dev 差 €5 但方向對,錢全拿;差 €0.5 但方向錯,錢全賠。
所以 `ablation()` 排序用**回收上界的百分比**,不用 MAE —— 這正是 arXiv 2510.16021 沒做的事。
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imbalance_regimes import D_DA15, D_FIX, load_new  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "new_data", ROOT / "figs" / "trading"

P_MW = 10.0
DT_H = 0.25
LAG2D = 2 * 96          # 兩天 = 192 格
WEEK = 7 * 96

# 特徵分組 —— ablation 一次抽掉一組,看少賺多少錢。
GROUPS = {
    "行事曆": ["qod_sin", "qod_cos", "dow", "month", "is_weekend"],
    "再生能源日前預測": ["solar_da", "wind_da", "wind_ramp", "solar_ramp",
                         "wind_rel30", "solar_rel30"],
    "不平衡歷史": ["dev_q7", "dev_roll7", "absdev_roll7", "dir_share7", "dev_l2d"],
    "現貨歷史": ["spot_l2d", "spot_q7", "spot_roll7"],
    # 🔴 本地負載:來自 ENTSO-E 的 Forecasted Load —— **發布時點沒有保證在關門前**,見 BID_TIME_SAFE
    "本地負載日前預測": ["load_da", "load_ramp", "own_residual"],
    # 🔴 鄰國殘餘 = 鄰國的「日前負載預測 − 日前風光預測」(`entsoe/derived/`,**不是**
    # `new_data/residual/` —— 後者是用**實測**算的,拿來當特徵會 leak)。
    # 電池線的紀錄:加了鄰國資料,價格預測的 rMAE 才從 0.76 掉到 0.54,`de_residual` 是分裂次數第一。
    # **但發布時點沒有保證在關門前**,見 BID_TIME_SAFE。
    "鄰國殘餘(ENTSO-E 日前)": ["nb_de", "nb_se3", "nb_se4", "nb_de_ramp"],
}

# 🔴 **ENTSO-E 的日前預測不保證在投標關門前就發布。**
#    法規(EU 543/2013)只要求日前負載預測與日前風光預測在 **D−1 18:00 CET 之前**公布
#    —— 那比 12:00 的關門**晚六小時**。實務上多數 TSO 早上就發了,但那是慣例不是保證,
#    而且我們存下來的 parquet 只有「對哪一格」沒有「何時發布」,**在地端驗不了**。
#    → `True` = 只用確定在關門前拿得到的特徵(19 個);`False` = 全部 26 個,較寬鬆。
#    ⚠️ 兩種設定的結論一樣(回收都跟 0 分不開),所以這個風險不影響階段 0 的負面結果 ——
#      它只代表那個結果**偏保守**(給了 agent 可能不該有的資訊,它還是學不動)。
#    📌 Energinet 自己的 `ForecastDayAhead` 風險低得多(它存在的目的就是服務中午那場拍賣),
#      但同樣沒有發布時戳可證。要釘死就得去拉 ENTSO-E API 的 createdDateTime。
BID_TIME_SAFE = True
UNSAFE_GROUPS = ("本地負載日前預測", "鄰國殘餘(ENTSO-E 日前)")
FEATS = [c for g, cols in GROUPS.items() for c in cols
         if not (BID_TIME_SAFE and g in UNSAFE_GROUPS)]


def _forecast_15min(area: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Energinet 官方隔日風光預測(逐時)→ 攤到 15 分鐘格。只取 `ForecastDayAhead`。"""
    import glob
    (f,) = glob.glob(str(DATA / f"forecast/forecast_{area.lower()}_*.parquet"))
    d = pd.read_parquet(f)
    p = d.pivot_table(index="HourUTC", columns="ForecastType", values="ForecastDayAhead")
    p.index = pd.DatetimeIndex(p.index)
    p = p.reindex(p.index.union(idx)).sort_index().ffill(limit=3).reindex(idx)
    return pd.DataFrame({
        "solar_da": p.get("Solar"),
        "wind_da": p.get("Onshore Wind").fillna(0) + p.get("Offshore Wind").fillna(0),
    }, index=idx)


def _entsoe_15min(area: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """ENTSO-E 的日前負載預測與鄰國殘餘(逐時)→ 攤到 15 分鐘格。

    ⚠️ 鄰國殘餘只能用 `new_data/entsoe/derived/`(= 日前負載預測 − 日前風光預測)。
    `new_data/residual/` 是同名但**用實測算的**,那個會 leak。"""
    import glob

    def _one(pat: str) -> pd.Series:
        (f,) = glob.glob(str(DATA / pat))
        d = pd.read_parquet(f)
        s = d.iloc[:, 0]
        s.index = pd.DatetimeIndex(s.index)
        return s.reindex(s.index.union(idx)).sort_index().ffill(limit=3).reindex(idx)

    z = "dk_1" if area == "DK1" else "dk_2"
    return pd.DataFrame({
        "load_da": _one(f"entsoe/loadfc_{z}_*.parquet"),
        "nb_de": _one("entsoe/derived/residual_de_lu_*.parquet"),
        "nb_se3": _one("entsoe/derived/residual_se_3_*.parquet"),
        "nb_se4": _one("entsoe/derived/residual_se_4_*.parquet"),
    }, index=idx)


def build_panel(area: str, dev_source: pd.DataFrame | None = None) -> pd.DataFrame:
    """建 15 分鐘面板:目標 dev + 全部特徵。

    `dev_source` 只給 self-check 用 —— 傳一份「關門後的資料被挖空」的價格進來,
    特徵不該有任何變化。正常呼叫傳 None。"""
    n = load_new(area) if dev_source is None else dev_source
    idx = pd.date_range(n.index.min(), n.index.max(), freq="15min", tz="UTC")
    spot = n["SpotPriceEUR"].reindex(idx)
    imb = n["ImbalancePriceEUR"].reindex(idx)
    dev = imb - spot

    df = pd.DataFrame({"dev": dev, "spot": spot}, index=idx)
    qod = idx.hour * 4 + idx.minute // 15

    # ── 價格衍生:一律先落後兩天,之後所有 rolling 都建在落後值上 ──
    dev_l, spot_l = dev.shift(LAG2D), spot.shift(LAG2D)
    df["dev_l2d"], df["spot_l2d"] = dev_l, spot_l
    for name, base in (("dev", dev_l), ("spot", spot_l)):
        # 同一個時刻(quarter-of-day)過去 7 天的均值 —— 不平衡有很強的時段結構
        df[f"{name}_q7"] = base.groupby(qod).transform(
            lambda s: s.rolling(7, min_periods=3).mean())
        df[f"{name}_roll7"] = base.rolling(WEEK, min_periods=96).mean()
    df["absdev_roll7"] = dev_l.abs().rolling(WEEK, min_periods=96).mean()
    df["dir_share7"] = (dev_l > 0).where(dev_l.notna()).rolling(WEEK, min_periods=96).mean()

    # ── 再生能源:目標時段的隔日預測(關門時就有),以及它相對近月的高低 ──
    fc = _forecast_15min(area, idx)
    df["solar_da"], df["wind_da"] = fc["solar_da"], fc["wind_da"]
    df["wind_ramp"] = fc["wind_da"].diff()
    df["solar_ramp"] = fc["solar_da"].diff()
    for c in ("wind", "solar"):
        # 相對值用**落後兩天**的滾動基準,免得用到未來的月均
        base = fc[f"{c}_da"].shift(LAG2D).rolling(30 * 96, min_periods=96).mean()
        df[f"{c}_rel30"] = fc[f"{c}_da"] / base.replace(0, np.nan)

    # ── 本地負載與鄰國殘餘(都是日前發布的預測)──
    e = _entsoe_15min(area, idx)
    df["load_da"] = e["load_da"]
    df["load_ramp"] = e["load_da"].diff()
    # 本地殘餘 = 自己的負載預測 − 自己的風光日前預測(關門時三個都有)
    df["own_residual"] = e["load_da"] - fc["wind_da"].fillna(0) - fc["solar_da"].fillna(0)
    for c in ("nb_de", "nb_se3", "nb_se4"):
        df[c] = e[c]
    df["nb_de_ramp"] = e["nb_de"].diff()

    # ── 行事曆:關門時當然知道 ──
    df["qod_sin"] = np.sin(2 * np.pi * qod / 96)
    df["qod_cos"] = np.cos(2 * np.pi * qod / 96)
    df["dow"] = idx.dayofweek
    df["month"] = idx.month
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    return df


# ─────────────────────────── 策略 ───────────────────────────

def money(pos: np.ndarray, dev: np.ndarray) -> float:
    """部位(±1,會乘上 P_MW)與實際 dev 結算成歐元。"""
    return float(np.nansum(pos * P_MW * dev * DT_H))


def oracle_money(dev: np.ndarray) -> float:
    return money(np.sign(dev), dev)


def fit_lgbm(tr: pd.DataFrame, te: pd.DataFrame, feats: list[str]) -> np.ndarray:
    """回歸 dev,再取符號當部位。**不加樣本權重** —— 這件事踩過一次:

    ±P 的部位只有兩個選擇,最適決策是 `sign(E[dev|x])`,而**無權重**的平方誤差回歸
    估的正是 `E[dev|x]`。拿 `|dev|` 當權重看起來像「讓貴的格更重要」,實際上估到的是被
    大尾巴拉過去的東西,**符號就偏了**:dev 的上調側平均比下調側大兩倍以上,加權後模型
    幾乎永遠猜「缺電」。實測代價 —— DK2 回收從 **8.7% 掉到 1.6%**、DK1 從 +0.6% 掉到 −0.3%。

    🔑 **「用錢」屬於評分,不屬於損失函數。** 決策是個符號,把錢塞進權重反而害了符號。"""
    cut = int(len(tr) * 0.9)                      # 訓練尾段當 early-stop valid(是 train 的未來)
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, num_leaves=63,
                          subsample=0.8, colsample_bytree=0.8, random_state=0, verbose=-1)
    m.fit(tr[feats].iloc[:cut], tr["dev"].iloc[:cut],
          eval_set=[(tr[feats].iloc[cut:], tr["dev"].iloc[cut:])],
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return m.predict(te[feats])


def walk_forward(df: pd.DataFrame, feats: list[str],
                 train_start: pd.Timestamp, test_start: pd.Timestamp) -> pd.DataFrame:
    """逐月重訓的前推驗證。訓練集只用該測試月之前的資料 —— 切分照時間,不是隨機。

    🔑 **可用列一律用「全部特徵」判定,不是用這次要餵的那幾個**。否則抽掉再生能源那組
    會憑空多出 962 列(它們是缺 solar/wind 預測的格),ablation 就不是同一個樣本、
    連分母(完美預知上界)都不一樣了 —— 那種「少賺 pp」是假的。"""
    d = df.dropna(subset=["dev"] + FEATS)
    d = d[d.index >= train_start]
    months = sorted({p for p in d.index.tz_convert(None).to_period("M")})
    out = []
    for m in months:
        lo = m.to_timestamp().tz_localize("UTC")
        hi = (m + 1).to_timestamp().tz_localize("UTC")
        if lo < test_start:
            continue
        tr, te = d[d.index < lo], d[(d.index >= lo) & (d.index < hi)]
        if len(tr) < 30 * 96 or len(te) == 0:
            continue
        pred = fit_lgbm(tr, te, feats)
        out.append(pd.DataFrame({"dev": te["dev"].values,
                                 "pred": pred,
                                 "dev_q7": te["dev_q7"].values}, index=te.index))
    return pd.concat(out) if out else pd.DataFrame()


def score(r: pd.DataFrame) -> dict:
    """一張錢的成績單。分母是完美預知上界。"""
    dev = r["dev"].values
    orc = oracle_money(dev)
    strat = {
        "永遠押缺電(long imbalance)": np.ones(len(dev)),
        "永遠押電多(short imbalance)": -np.ones(len(dev)),
        "持續性(同時段近 7 天均值的符號)": np.sign(np.nan_to_num(r["dev_q7"].values)),
        "LightGBM(日前特徵)": np.sign(r["pred"].values),
    }
    res = {"完美預知上界 k€": orc / 1e3,
           "預測與實際的相關": float(np.corrcoef(r["pred"], dev)[0, 1])}
    for k, pos in strat.items():
        eur = money(pos, dev)
        hit = float(np.mean(np.sign(pos) == np.sign(dev)))
        lo, hi = recovery_ci(r, pos)
        res[k] = {"k€": eur / 1e3, "回收 %": eur / orc * 100, "方向命中 %": hit * 100,
                  "CI": (lo, hi)}
    return res


def recovery_ci(r: pd.DataFrame, pos: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple:
    """回收率的 95% 信賴區間 —— **按日的區塊 bootstrap**。

    為什麼非做不可:相關只有 ~0.03 的時候,ablation 的「少賺 2 pp」很可能只是抽樣噪音。
    沒有這條噪音底線,那張 ablation 表會被讀成排序,而它其實排不出東西。
    按日重抽是因為 15 分鐘的 dev 有強自我相關,逐格重抽會低估標準誤好幾倍。"""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"pos": pos, "dev": r["dev"].values}, index=r.index)
    days = [g for _, g in df.groupby(df.index.date)]
    out = []
    for _ in range(n_boot):
        b = pd.concat([days[i] for i in rng.integers(0, len(days), len(days))])
        orc = oracle_money(b["dev"].values)
        out.append(money(b["pos"].values, b["dev"].values) / orc * 100 if orc else np.nan)
    return tuple(np.nanpercentile(out, [2.5, 97.5]))


def ablation(df: pd.DataFrame, train_start, test_start) -> pd.DataFrame:
    """一次抽掉一組特徵,**用錢排序**。"""
    full = walk_forward(df, FEATS, train_start, test_start)
    base = money(np.sign(full["pred"].values), full["dev"].values) / oracle_money(full["dev"].values)
    rows = [{"特徵組": "(全部)", "回收 %": base * 100, "少賺 pp": 0.0}]
    for g, cols in GROUPS.items():
        if not (set(cols) & set(FEATS)):    # BID_TIME_SAFE 關掉的組不用再抽一次
            continue
        keep = [c for c in FEATS if c not in cols]
        r = walk_forward(df, keep, train_start, test_start)
        rec = money(np.sign(r["pred"].values), r["dev"].values) / oracle_money(r["dev"].values)
        rows.append({"特徵組": f"抽掉「{g}」", "回收 %": rec * 100,
                     "少賺 pp": (base - rec) * 100})
    return pd.DataFrame(rows).sort_values("少賺 pp", ascending=False)


def target_ladder(df: pd.DataFrame, train_start, test_start) -> pd.DataFrame:
    """**同一批特徵、同一段期間、同一個模型,只換目標。** 這支回答的是
    「資料不是都在嗎,為什麼學不出東西」。

        日前價 spot          → 學得動(R² ~0.5)
        不平衡價 imb         → 幾乎學不動(R² ~0.05,而且那一點點是因為 imb 跟著 spot 走)
        價差 dev = imb − spot → **完全學不動(R² ~0.00)**

    🔑 **減掉 spot 等於把可預測的那一塊剛好扣掉**,剩下的是「實時到底出了什麼意外」。
       所以問題不是資料不夠、也不是模型不好,**是這個目標本身就是別人的預測誤差**。"""
    d = df.copy()
    d["imb"] = d["spot"] + d["dev"]
    d = d.dropna(subset=["dev", "spot"] + FEATS)
    d = d[d.index >= train_start]
    rows = []
    for target, label in (("spot", "日前價 spot"), ("imb", "不平衡價 imb"),
                          ("dev", "價差 dev = imb − spot")):
        out = []
        for m in sorted({q for q in d.index.tz_convert(None).to_period("M")}):
            lo = m.to_timestamp().tz_localize("UTC")
            hi = (m + 1).to_timestamp().tz_localize("UTC")
            if lo < test_start:
                continue
            tr, te = d[d.index < lo], d[(d.index >= lo) & (d.index < hi)]
            if len(tr) < 30 * 96 or not len(te):
                continue
            cut = int(len(tr) * 0.9)
            mdl = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, num_leaves=63,
                                    subsample=0.8, colsample_bytree=0.8,
                                    random_state=0, verbose=-1)
            mdl.fit(tr[FEATS].iloc[:cut], tr[target].iloc[:cut],
                    eval_set=[(tr[FEATS].iloc[cut:], tr[target].iloc[cut:])],
                    callbacks=[lgb.early_stopping(50, verbose=False)])
            out.append(pd.DataFrame({"y": te[target].values, "p": mdl.predict(te[FEATS])},
                                    index=te.index))
        r = pd.concat(out)
        y, q = r["y"].values, r["p"].values
        rows.append({"目標": label, "R²": 1 - np.sum((y - q) ** 2) / np.sum((y - y.mean()) ** 2),
                     "MAE": float(np.mean(np.abs(y - q))),
                     "相關": float(np.corrcoef(q, y)[0, 1]),
                     "實際 sd": float(y.std())})
    return pd.DataFrame(rows)


def horizon_probe(area: str) -> pd.DataFrame:
    """**訊號是不存在,還是關門之後才出現?** —— 這支診斷回答的就是這個。

    用**再生能源預測誤差**(某一代預測 − 隔日預測)當唯一特徵,規則簡單到不用訓練:
    **發電比隔日預期少 → 系統缺電 → 不平衡價高於現貨** → 押「缺電」。

    🔴 **這是故意 leak 的對照組,不可以進 agent。** 它的用途是把「日前 agent 回收 ~0」
       解釋清楚:如果連交割當下的誤差都預測不動,那是市場真的隨機;如果它明顯有用,
       那**綁住 agent 的是資訊集不是模型**,而那正是階段 1–3 存在的理由。"""
    import glob

    n = load_new(area)
    n = n[n.index >= D_FIX]
    (f,) = glob.glob(str(DATA / f"forecast/forecast_{area.lower()}_*.parquet"))
    d = pd.read_parquet(f)
    d = d[d.HourUTC >= D_FIX]
    piv = lambda col: d.pivot_table(index="HourUTC", columns="ForecastType", values=col).sum(axis=1)
    da = piv("ForecastDayAhead")
    dev = (n["ImbalancePriceEUR"] - n["SpotPriceEUR"]).resample("1h").mean().rename("dev")

    rows = []
    for col, when in (("Forecast5Hour", "交割前 5 小時"), ("ForecastCurrent", "交割當下")):
        x = pd.concat([dev, (piv(col) - da).rename("err")], axis=1).dropna()
        pos = -np.sign(x["err"].values)          # 誤差為負(發電變少)→ 押缺電
        eur = float(np.nansum(pos * P_MW * x["dev"].values))
        orc = float(np.nansum(np.abs(x["dev"].values)) * P_MW)
        rows.append({"誤差看到的時點": when, "n(小時)": len(x),
                     "與 dev 的相關": float(np.corrcoef(x["err"], x["dev"])[0, 1]),
                     "照它押的回收 %": eur / orc * 100})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = ["# 階段 0:日前交易 agent(10 MW)", "",
           "決策時點 = 日前關門 D−1 12:00 CET。價格特徵落後 ≥2 天,再生能源只用 `ForecastDayAhead`。",
           f"訓練從 {D_DA15.date()}(日前也轉 15 分)起,測試只在乾淨窗口。", ""]
    test_start = pd.Timestamp("2026-03-01", tz="UTC")   # 訓練至少 5 個月,且全落在 D_FIX 之後
    for area in ("DK1", "DK2"):
        df = build_panel(area)
        r = walk_forward(df, FEATS, D_DA15, test_start)
        s = score(r)
        rep += [f"## {area}", "",
                f"測試 {r.index.min():%Y-%m-%d} → {r.index.max():%Y-%m-%d},{len(r):,} 格。",
                f"完美預知上界 **{s.pop('完美預知上界 k€'):,.0f} k€**,"
                f"前推預測與實際 dev 的相關 **{s.pop('預測與實際的相關'):+.4f}**", "",
                "| 策略 | k€ | 回收上界 % | 95% CI(按日 bootstrap) | 方向命中 % |",
                "|---|---|---|---|---|"]
        for k, v in s.items():
            rep.append(f"| {k} | {v['k€']:,.0f} | {v['回收 %']:.1f} | "
                       f"[{v['CI'][0]:.1f}, {v['CI'][1]:.1f}] | {v['方向命中 %']:.1f} |")
        lo, hi = s["LightGBM(日前特徵)"]["CI"]
        rep += ["", f"🔴 **噪音底線 = CI 寬度 {hi - lo:.1f} pp。** 下面 ablation 的「少賺 pp」"
                "只要小於這個,就**排不出順序**,不可以拿來宣稱哪組特徵重要。", "",
                "### 特徵 ablation(用錢排序,不是用準度)", "",
                ablation(df, D_DA15, test_start).to_markdown(index=False, floatfmt=",.1f"), ""]
        rep += ["### 🔑 對照一:資料都在,換個目標就學得動", "",
                target_ladder(df, D_DA15, test_start).to_markdown(index=False, floatfmt=",.3f"), "",
                "**同一批特徵、同一段期間、同一個模型。** 日前價學得動;不平衡價幾乎學不動"
                "(那一點點是因為它跟著日前價走);**減掉日前價之後什麼都不剩**。"
                " → 減掉 spot 剛好把可預測的那一塊扣光,剩下的是**實時的意外**。", "",
                "### 🔴 對照二:訊號是不存在,還是關門之後才出現(**故意 leak**,只當診斷)", "",
                horizon_probe(area).to_markdown(index=False, floatfmt=",.3f"), "",
                "**預測誤差只有交割前才知道,而它單獨一條規則就贏過全部日前特徵。**"
                " → 綁住階段 0 的是**資訊集**,不是模型;這正是階段 1–3(自己的產出、彈性)"
                "存在的理由,也是為什麼階段 0 沒有 RL 的位置。", ""]
        r.to_csv(OUT / f"agent_walkforward_{area.lower()}.csv")
        print("\n".join(rep[-14:]))
    (OUT / "AGENT_STAGE0.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"\n→ 已寫出 {OUT/'AGENT_STAGE0.md'}")


def selfcheck() -> None:
    """leak canary:把**日前關門之後**才知道的價格全部挖掉,某一天的特徵不該有任何變化。
    這是重新推導「特徵只用得到關門前的資訊」,不是比對抄來的數字。"""
    area = "DK2"
    full = build_panel(area)
    n = load_new(area)

    day = pd.Timestamp("2026-06-15", tz="UTC")          # 隨便挑一個測試期內的交割日
    gate = day - pd.Timedelta(hours=12)                  # D−1 12:00 UTC ≈ 關門(CET 更晚,更保守)
    blind = n.copy()
    blind.loc[blind.index >= gate, ["ImbalancePriceEUR", "SpotPriceEUR"]] = np.nan
    masked = build_panel(area, dev_source=blind)

    rows = (full.index >= day) & (full.index < day + pd.Timedelta("1D"))
    a, b = full.loc[rows, FEATS], masked.loc[rows, FEATS]
    diff = ~((a - b).abs().fillna(0) < 1e-9).all()
    assert not diff.any(), f"{area}: 這些特徵用到了關門後的資訊 → {list(diff[diff].index)}"
    print(f"✓ {area}: 挖掉 {gate:%Y-%m-%d %H:%M} 之後的價格,{day:%Y-%m-%d} 全部 "
          f"{len(FEATS)} 個特徵不變 → 沒有 leak")

    # 「作弊」對照:在測試期內訓練。**負面結果的可信度靠這個** —— 如果連 in-sample 都
    # 學不動,那是特徵/管線壞了;in-sample 學得動而 out-of-sample 不動,才是真的預測不了。
    d = full.dropna(subset=["dev"] + FEATS)
    te = d[d.index >= pd.Timestamp("2026-03-01", tz="UTC")]
    m = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.05, num_leaves=63,
                          random_state=0, verbose=-1).fit(te[FEATS], te["dev"])
    rec = money(np.sign(m.predict(te[FEATS])), te["dev"].values) / oracle_money(te["dev"].values)
    assert rec > 0.5, f"{area}: 連 in-sample 都只回收 {rec:.1%} → 是管線壞了,不是市場不可預測"
    print(f"✓ {area}: in-sample 作弊回收 {rec:.1%} → 管線可用,前推的低回收是真的預測不動")

    # 押對邊的上界必須 ≥ 任何固定策略(它們都是 oracle 的可行解)
    dev = full["dev"].dropna().values
    assert oracle_money(dev) >= abs(money(np.ones(len(dev)), dev)) - 1e-6
    print("✓ 完美預知上界 ≥ 固定單邊策略")


if __name__ == "__main__":
    selfcheck()
    print()
    main()
