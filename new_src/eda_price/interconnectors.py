"""丹麥聯絡線的容量真值 —— 第三份資料(先前缺的那一份)。

🔴 三個量必須分開,先前的分析把後兩個混用了:

  ① 實體/熱容量        導體本身承受得住的上限
                       → **公開文件沒有,而且對交流邊界根本不是單一數字**
                          (限制來自系統安全與穩定,不是導體發熱)
  ②a 最大商業容量      扣掉網損、安全標準、技術限制後的**上限**,固定值
                       → **這份檔案。** Energistyrelsen AF25 表 3
  ②b 逐時商業容量      每小時真正提供給日前市場的量,≤ ②a(檢修/故障會壓低)
                       → `new_data/entsoe/ntc_*.parquet`、`oc_*.parquet`
  ③  實際流量          量測值
                       → `new_data/production/production_*.parquet` 的 `Exchange*`
                          (已用 15 分鐘制驗證:同一小時內四筆有變動 98–100% → 是量測)

來源:Energistyrelsen,《Analyseforudsætninger til Energinet 2025 —
Eltransmissionsforbindelser til udlandet (interkonnektorer)》,Baggrundsnotat
(høringsudgave), 24. september 2025, J.nr. 2025-3657, 表 3(第 9 頁)。
https://ens.dk/  (PDF: prodstoragehoeringspo.blob.core.windows.net/...)

方向慣例(與該表一致):`imp` = 進入 `zone` 的容量,`exp` = 離開 `zone` 的容量。
"""
from __future__ import annotations
import pandas as pd

# 表 3 逐字轉錄。cap 單位 MW。
RATINGS = pd.DataFrame([
    # zone, 對手, 名稱,             imp,  exp, 型式, 註
    ("DK1", "NO2",   "Skagerrak 1-4",   1632, 1632, "HVDC", "四條直流電纜"),
    ("DK1", "SE3",   "Konti-Skan 1-2",   715,  715, "HVDC", "兩條直流電纜"),
    ("DK1", "DE",    "Jylland-Tyskland",2500, 2500, "AC",   "四條交流線;2027 初升到 3500"),
    ("DK1", "NL",    "COBRAcable",       700,  700, "HVDC", "一條直流電纜"),
    ("DK1", "UK",    "Viking Link",     1400, 1400, "HVDC", "名目 1400;Vestkyst 完工前實際 1100進/1000出"),
    ("DK1", "DK2",   "Storebælt",        600,  590, "HVDC", "國內,但市場上與國際線同規則"),
    ("DK2", "SE4",   "Øresund",         1300, 1700, "AC",   "兩套交流系統;2026 原容量再投資"),
    ("DK2", "DE",    "Kontek",           600,  585, "HVDC", "一條直流電纜"),
    ("DK2", "DE",    "Kriegers Flak",    400,  400, "AC",   "🔴 交流,且容量受風場實際出力限制"),
    ("DK2", "DK1",   "Storebælt",        590,  600, "HVDC", "同上,方向相反"),
], columns=["zone", "counterpart", "name", "imp", "exp", "type", "note"])

# Energinet 的 Exchange* 欄是聚合的,對映到上表的哪幾條
AGG = {
    ("DK2", "ExchangeNordicCountries"): ["Øresund"],
    ("DK2", "ExchangeContinent"):       ["Kontek", "Kriegers Flak"],
    ("DK2", "ExchangeGreatBelt"):       ["Storebælt"],
    ("DK1", "ExchangeNordicCountries"): ["Skagerrak 1-4", "Konti-Skan 1-2"],
    ("DK1", "ExchangeContinent"):       ["Jylland-Tyskland", "COBRAcable"],
    ("DK1", "ExchangeGreatBelt"):       ["Storebælt"],
    ("DK1", "ExchangeGreatBritain"):    ["Viking Link"],
}


def cap(zone: str, col: str) -> tuple[float, float]:
    """回傳該聚合欄位的 (進入 zone 的容量, 離開 zone 的容量),MW。"""
    r = RATINGS[RATINGS.zone == zone].set_index("name")
    names = AGG[(zone, col)]
    return float(r.loc[names, "imp"].sum()), float(r.loc[names, "exp"].sum())


# 🔴 兩個會改變分析設計的事實,也在同一份文件裡:
#
# 1. Kriegers Flak 由德國 TSO 50Hertz 營運,**Energinet 沒有該連線的資料**
#    (AF25 第 7 頁註 4)。→ 這就是 ENTSO-E 的 `ntc_dk_2_de_lu` 出口序列
#    最大只到 649 MW(≈Kontek 585 + 一點)、而實際流量到 1,038 MW 的原因。
#    **不是抓取錯誤,是資料源本身就沒有。**
#
# 2. **北歐 Flow-Based Market Coupling 於 2024-10 上線**(AF25 §2.1.5),
#    取代逐邊界的固定 NTC。→ `oc_*` 系列在 2024-10-29 結束**不是抓取上限**,
#    是那個產品停止發布。**2024-10 之後「這條線滿了沒」不再是正確的問法。**
#    → 所有壅塞分析的有效窗口 = **2019-10 → 2024-10**。
FBMC_START = pd.Timestamp("2024-10-01", tz="UTC")
