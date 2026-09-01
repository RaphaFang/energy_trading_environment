# varmelast.dk — 大哥本哈根逐時區域供熱

來源:https://www.varmelast.dk/api/v1/heatdata/historical
     欄位定義:/api/v1/heatdata/dictionary(已快照成 varmelast_dictionary.json)
     其他端點:/api/v1/heatdata(廠級即時 + 業主容量)、/revisionplan(檢修計畫)

⚠️ 這是小型公用事業網站,抓取保持禮貌間隔(每季一次請求 + 2 秒延遲)。

## 為什麼關鍵
🔑 **全丹麥唯一的逐時熱資料。** DK1 沒有公開逐時 DH 需求,只能用度日代理。
涵蓋 2021-01 → 2026,49,379 列,單位 MJ/s = MW_th。2019/2020 沒有資料。
= 全國供熱的 26.0%(CTR + VEKS 兩張傳輸網)。

## 🔴 欄位分兩類,混用會造成循環論證
**① 消費(可以當 LP 的熱需求輸入)**
  BE-EO-CTR-EFF          CTR 傳輸網熱消費(均 709 MW_th)
  DAP-VEKS-FORBRUG-EFF   VEKS 傳輸網熱消費(均 287 MW_th;FORBRUG = 消費)

**② 生產(只能當驗證對照,絕不可當輸入)**
  TOTAL                  官方 title「Produktion i alt」= 總生產,不是需求
  BE-VL-KRAFTV-EF 熱電 · BE-VL-AFFALD-EF 焚化 · BE-VL-SPIDS-GAS/OLIE-EF 尖峰鍋爐
  BE-VL-VP-EF 熱泵(電>熱) · BE-VL-EVO-EF 電鍋爐 · BE-VL-IO-EF 工業餘熱
  BE-VL-OD-EF 資料中心餘熱 · BE-VL-BIO/BG/SOL-EF 生質/沼氣/太陽熱
  🔴 這些**已含蓄熱槽調度與經濟最佳化的結果** → 當熱需求就是拿模型輸出當輸入。

## 🔴 兩個欄位陷阱
**BE-VL-TOTAL-FAK 不是熱量** —— 官方 title「CO2 - Udledning」,單位 **Kg/GJ**(排放強度)。
  加進 MW_th 的分母會算錯佔比(STATUS.md 先前的 64.4/27.3 就是這樣來的)。
  🔑 這是整個 repo 唯一一欄排放資料。
**LOCAL 全期恆為 0** —— 有一部分熱直接送進配網不經傳輸網。
  → CTR+VEKS 是「傳輸層取用量」不是終端消費總量。論文要標明是傳輸層口徑。

## 生產 ≠ 消費
TOTAL 明寫「eksklusive op- og afladning på varmelagre」(不含蓄熱充放)。
實測 gap = 生產 − 消費:均 +29.6 MW · std 110 · **38% 小時為負** ·
月均 gap/消費 −3.7% ~ +13.3% = 蓄熱充放 + 傳輸網損失。
三座蓄熱槽(Amager 1,000 MWh / Avedøre 2,200 / Høje Taastrup 3,300)在 API 的
objects 裡有列但**沒有數值序列** → 重建蓄熱只能用 gap 扣掉損失近似。

⚠️ 這是 DK2,不是 DK1。當校準與驗證用,不是 DK1 的直接輸入。