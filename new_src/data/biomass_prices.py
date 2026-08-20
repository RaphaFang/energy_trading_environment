"""生質燃料價 — 木顆粒、木片、秸稈。**填 2021–2024 那個缺口。**

為什麼需要:CHP 模型的 merit order 由燃料價決定,而 DK2 佔供熱 **64.6%** 的三台
(Amager / Avedøre / Køge)燒的是生質。SØB25 的生質價**只從 2025 開始**,
所以 2021–2024 一直跑不動 —— `dk2_fleet.runnable()` 卡在 2/6。

⚠️ **煤/氣/碳沒有「丹麥價」是因為那些是全球或全歐單一市場;生質不是。**
生質是**區域性定價**,所以這裡要的就是北歐的在地價,不能拿國際指數代替。

━━━ 兩個來源,刻意都抓 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**A. Danmarks Statistik `KN8Y`** —— 丹麥官方,但它是**進口 CIF 單價**不是到廠合約價。
   逐年 1988+,KN 8 位碼 × 國別 × (Kilo | Kroner)。**兩個單位都存,不在這裡相除。**
   ✅ 顆粒:丹麥幾乎全靠進口 → 進口單價是好代理。
   ⚠️ 木片:**主要是國產**,進口單價只涵蓋進口的那部分;而且進口量 2024 崩到 552 kt
      (2021 是 1,269 kt)→ 2024/2025 的木片單價是**薄量算出來的**,代表性存疑。

**B. Energimyndigheten(瑞典能源署)PxWeb** —— 瑞典市場,但切分**更貼近我們要的量**:
   `Användare = Värmeverk`(熱力廠)的**平均採購價**,定義是「燃料採購成本 ÷ 能量含量」。
   逐季 **1993Q1+**,kr/MWh、**fritt förbrukare、不含稅**。
   ✅ **木片優先用這條。** ⚠️ 但它是跨國代理,論文要標明。

━━━ 為什麼可以信 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2025 是三個來源的**重疊年**,拿來交叉驗證(EUR/MWh_fuel):

    顆粒   DST 42.1  /  SE 46.1  /  SØB25 41.1     ← DST 與 SØB25 差 2.4%
    木片   DST 38.8  /  SE 34.0  /  SØB25 36.3     ← 兩條把 SØB25 夾在中間(±7%)

🔑 **順帶量化了「不要拿 2025 鋪滿前面」**:2021 的木片是 **18.9–23.3**,2025 是
**34.0–38.8** → 鋪滿會把 2021 的生質成本**高估 55–90%**,方向是把生質機組推出
merit order,而 2021–2022 正是最想研究的兩年。完整比較表見 `DATA.md` §8。

━━━ 儲存原則:raw ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**存來源回傳的原樣,不挑欄位、不換單位、不換幣別、不相除。**
  - DST 的 Kilo 與 Kroner **分開兩列存著**,「除出單價」是分析時才做的事
  - 瑞典的 SEK **不換成 EUR**(要換得走匯率序列,而且年均匯率是分析選擇不是資料)
  - 熱值(GJ/t)**完全不在這裡** —— 那是 `assumptions` 的事
  → 換算規則改了不用重抓。

⚠️ **這個模組只負責「把資料放進來」,沒有接進 `assumptions.py`。**
要不要拿它當機組的燃料價、用哪一條、怎麼辯護跨國代理,**是研究設計決定,留給使用者。**

用法:python new_src/data/biomass_prices.py
"""

import io
import json
import urllib.request
from pathlib import Path

import pandas as pd

FUEL = Path("new_data/fuel")  # 與其他燃料同層,一個來源一個檔
START_YEAR, END_YEAR = 2019, 2025  # 與 fuel_prices.py 的窗口一致

DST_URL = "https://api.statbank.dk/v1/data"
SE_URL = (
    "https://pxexternal.energimyndigheten.se/api/v1/sv"
    "/Energimyndighetens_statistikdatabas/Officiell_energistatistik"
    "/Tradbransle_och_torvpriser/1_EN0307_1.px"
)

# KN 8 位碼。**刻意抓整個 4401 家族 + 秸稈**,不是只抓「現在用得到的兩個」——
# 碼在 2022 年前後改過(顆粒 44013020 → 44013100),而且 AVV1 燒 halm。
DST_CODES = [
    "44011000",
    "44011100",
    "44011200",  # 薪材
    "44012100",
    "44012200",
    "44012210",
    "44012290",  # 木片 / 木屑
    "44013020",
    "44013040",
    "44013080",  # 顆粒與木廢(舊碼)
    "44013100",
    "44013900",
    "44013920",
    "44013990",  # 顆粒與木廢(新碼)
    "12130000",  # 秸稈(halm)—— AVV1 燒這個
]


def _post(url: str, payload: dict, timeout: int = 120) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _save(df: pd.DataFrame, name: str) -> Path:
    """先寫 `.tmp` 再 rename —— 中途失敗不會留下半個檔。"""
    FUEL.mkdir(parents=True, exist_ok=True)
    p = FUEL / f"{name}.parquet"
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, engine="pyarrow", compression="snappy")
    tmp.rename(p)
    return p


def pull_dst() -> None:
    """Danmarks Statistik KN8Y — 進出口 KN 8 位碼的**金額與重量**。

    ⚠️ 值的 id 不是人看的字:`INDUD` 1=Import / 2=Eksport、
    `ENHED` 98=Kilo / 99=Kroner、`LAND` TOT=I alt。傳中文或丹麥文字串會 404。
    """
    name = f"dst_kn8y_biomass_trade_raw_{START_YEAR}_{END_YEAR}"
    if (FUEL / f"{name}.parquet").exists():
        print(f"  · {name}: 已存在,跳過")
        return
    body = _post(
        DST_URL,
        {
            "table": "KN8Y",
            "format": "BULK",
            "lang": "da",
            "variables": [
                {"code": "VARE", "values": DST_CODES},
                {"code": "INDUD", "values": ["1", "2"]},  # 進口與出口都存
                {"code": "LAND", "values": ["*"]},  # 全部國別,不預先篩
                {"code": "ENHED", "values": ["98", "99"]},  # Kilo 與 Kroner
                {
                    "code": "Tid",
                    "values": [str(y) for y in range(START_YEAR, END_YEAR + 1)],
                },
            ],
        },
    )
    df = pd.read_csv(io.BytesIO(body), sep=";")
    df = df[df["INDHOLD"].astype(str).str.strip().str.len() > 0]
    p = _save(df, name)
    print(
        f"✓ DST KN8Y [Kilo + Kroner,**未相除**] {len(df):>6} 列  "
        f"{df['TID'].min()}–{df['TID'].max()}  {df['VARE'].nunique()} 個商品碼 → {p.name}"
    )


def pull_se() -> None:
    """Energimyndigheten — 木質燃料/泥炭價,逐季,kr/MWh 不含稅。

    Sortiment 0=Förädlade(精製,即顆粒) 1=Skogsflis(林地木片) 2=Biprodukter
              3=Stycketorv 4=Frästorv 5=Returträ
    Användare 0=Värmeverk(熱力廠,**我們要的**) 1=Industri
    **全部都抓**,篩選是分析時的事。
    """
    name = "se_energimyndigheten_tradbransle_sek_mwh_1993q1_latest"
    if (FUEL / f"{name}.parquet").exists():
        print(f"  · {name}: 已存在,跳過")
        return
    meta = json.loads(urllib.request.urlopen(SE_URL, timeout=60).read())
    var = {v["code"]: v for v in meta["variables"]}
    body = _post(
        SE_URL,
        {
            "query": [
                {
                    "code": c,
                    "selection": {"filter": "item", "values": var[c]["values"]},
                }
                for c in ("Kvartal", "Sortiment", "Användare")
            ],
            "response": {"format": "json-stat2"},
        },
    )
    d = json.loads(body)
    dim, val = d["dimension"], d["value"]
    ks, ss, us = (
        list(dim[c]["category"]["index"]) for c in ("Kvartal", "Sortiment", "Användare")
    )
    lab = {
        c: dim[c]["category"]["label"] for c in ("Kvartal", "Sortiment", "Användare")
    }
    rows = []
    for i, k in enumerate(ks):
        for j, so in enumerate(ss):
            for m, u in enumerate(us):
                v = val[(i * len(ss) + j) * len(us) + m]
                if v is not None:
                    rows.append(
                        {
                            "kvartal": lab["Kvartal"][k],
                            "sortiment": lab["Sortiment"][so],
                            "anvandare": lab["Användare"][u],
                            "sek_per_mwh": v,
                        }
                    )
    df = pd.DataFrame(rows)
    p = _save(df, name)
    print(
        f"✓ Energimyndigheten [SEK/MWh,不含稅,**未換匯**] {len(df):>6} 列  "
        f"{df['kvartal'].min()}–{df['kvartal'].max()}  → {p.name}"
    )


def demo() -> None:
    """self-check —— **重新推導,不比對抄來的數字**。

    重跑 2025 那年的三方交叉驗證:從 raw 檔自己算單價、自己換算,
    再跟 SØB25 的公布值比。對不上就是資料或口徑出問題了。
    """
    print("=== 生質燃料價 ===")
    pull_dst()
    pull_se()

    dst = pd.read_parquet(
        FUEL / f"dst_kn8y_biomass_trade_raw_{START_YEAR}_{END_YEAR}.parquet"
    )
    se = pd.read_parquet(
        FUEL / "se_energimyndigheten_tradbransle_sek_mwh_1993q1_latest.parquet"
    )

    # ── DST:自己從 Kilo 與 Kroner 相除(儲存層沒做,這裡才做)────────────
    d = dst[dst["INDUD"].str.startswith("Import") & (dst["LAND"] == "I alt")].copy()
    d["kode"] = d["VARE"].str.slice(0, 8)
    # ⚠️ DST 的 INDHOLD 是**字串**(缺值是 ".."),儲存層刻意原樣保留 → 這裡才轉數值
    d["v"] = pd.to_numeric(d["INDHOLD"], errors="coerce")
    piv = d.pivot_table(
        index=["kode", "TID"], columns="ENHED", values="v", aggfunc="sum"
    )
    # 熱值與匯率**只在這個 self-check 裡出現**,不進儲存層。⚠️ 兩個都是假設值。
    dkk, lhv = 7.46, {"44013100": 17.0, "44012290": 10.4}
    got = {}
    for kode, gj_t in lhv.items():
        r = piv.loc[kode]  # index 是 TID(int64,不是字串)
        got[kode] = (r["Kroner"] / r["Kilo"] * 1000 / dkk / (gj_t / 3.6)).round(1)

    # ── 瑞典:年均(四季平均),SEK→EUR 用年均匯率(⚠️ 粗值,只為對量級)──────
    sek = {2021: 10.15, 2022: 10.63, 2023: 11.48, 2024: 11.43, 2025: 11.05}
    v = se[se["anvandare"] == "Värmeverk"].copy()
    v["ar"] = v["kvartal"].str.slice(0, 4).astype(int)
    se_y = v.groupby(["sortiment", "ar"])["sek_per_mwh"].mean()

    print("\n  三方交叉驗證(EUR/MWh_fuel)—— **每次都重算,不是硬編**")
    print(f"  {'年':<6}{'DK顆粒':>9}{'SE顆粒':>9}{'DK木片':>9}{'SE木片':>9}")
    for y in range(2021, 2026):
        if y not in sek:
            continue
        print(
            f"  {y:<6}{got['44013100'].get(y, float('nan')):>9.1f}"
            f"{se_y.get(('Förädlade', y), float('nan')) / sek[y]:>9.1f}"
            f"{got['44012290'].get(y, float('nan')):>9.1f}"
            f"{se_y.get(('Skogsflis', y), float('nan')) / sek[y]:>9.1f}"
        )
    print("  SØB25 2025 對照:  顆粒 41.1   木片 36.3  (faktorpris,不含稅)")

    # 鎖住結論:2025 那年三方必須落在同一個量級,否則就是口徑錯了
    p25, c25 = got["44013100"].get(2025), got["44012290"].get(2025)
    assert abs(p25 - 41.1) / 41.1 < 0.15, (
        f"DST 顆粒 2025 = {p25:.1f} 與 SØB25 的 41.1 差超過 15% —— 口徑或熱值假設要重查"
    )
    assert abs(c25 - 36.3) / 36.3 < 0.20, (
        f"DST 木片 2025 = {c25:.1f} 與 SØB25 的 36.3 差超過 20%(木片進口量薄,容忍度放寬)"
    )
    # 鎖住「不可回填」:2021 必須明顯低於 2025,否則「鋪滿會高估」那個結論就垮了
    c21 = got["44012290"].get(2021)
    assert c21 < c25 * 0.75, (
        f"2021 木片 {c21:.1f} 若沒有明顯低於 2025 的 {c25:.1f},"
        "「拿 2025 鋪滿前面會高估 55–90%」這句話就要重寫"
    )
    print(
        f"\n  ✅ 2025 三方對得上;2021 木片 {c21:.1f} vs 2025 {c25:.1f} "
        f"= **低 {(1 - c21 / c25) * 100:.0f}%** → 回填禁令有數字撐著"
    )
    print(
        "\n  ⚠️ **本模組只把資料放進來,沒有接進 assumptions.py。**"
        "\n     用哪一條、怎麼辯護跨國代理,是研究設計決定 → 留給使用者。"
    )


if __name__ == "__main__":
    demo()
