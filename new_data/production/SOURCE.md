# Energinet EDS — 逐時分燃料出力 + 負載 + 跨境交換

來源:https://api.energidataservice.dk/dataset/ElectricityBalanceNonv

## 🔴🔴 這個 dataset 已經死了

**2026-01-06 12:15 停止發布。** 而且**是靜默停的** ——
檔名還寫 2026-08-21,抓取腳本不報錯,資料就停在半年前。
是 `new_src/data/coverage.py` 的稽核抓到的(2026-08-21 直接問 API 確認)。

🔴 **任何用這份算「最近一年」的結論都是錯的。**

## 它有而別人沒有的欄位
  TotalLoad                 總負載
  ExchangeContinent         對歐陸淨交換
  ExchangeGreatBelt         大貝爾特(DK1↔DK2)
  ExchangeNordicCountries   對北歐
  ExchangeGreatBritain      對英國
  HydroPower / OtherRenewable

→ **價格形成那條線(new_src/eda_price/)全靠這些。**
   `new_data/generation/`(ENTSO-E)有分燃料但**沒有這幾欄**,取代不了。

## 替代方案
- 分燃料出力 → `new_data/generation/`(ENTSO-E,活到 2026-08)
  ⚠️ 口徑不同(Energinet 結算後的丹麥口徑 vs ENTSO-E 的 TSO 申報)。
     重疊期 2019→2026-01 **尚未比對**,不要直接接成一條序列。
  🔴 而且 ENTSO-E 的 **DK2 Waste 欄 2025-04-09 起作廢**。
- 2026 之後的負載與交換 → `ProductionConsumptionSettlement`
  (欄位 GrossConsumptionMWh、ExchangeSE_MWh;`residual_demand.py` 已在用)

## ⚠️ 燃料欄不可信
Energinet 的 `Waste` 欄**每年**低估(2019-22 約 1.4×、2023-25 約 2.1–2.2×)。
🔴 **水準與燃料別一律用 EPT。** 這份只當逐時形狀。