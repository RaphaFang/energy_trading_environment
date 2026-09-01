# 丹麥能源署 SØB25 + 稅費費率(外部參數的單一收斂點)

| 檔 | 內容 | 誰在讀 |
| --- | --- | --- |
| `soeb25_params.csv` | 丹麥能源署 **Samfundsøkonomiske beregningsforudsætninger 2025**:燃料價、排放係數、熱值、物價指數 | ✅ `assumptions.py` |
| `dk_tax_and_tariff_params.csv` | 🔴 **稅費的出處憑證**:帶 URL、法條編號、抓取日期、警告 | ❌ 沒程式讀,但**絕不能刪** |
| `gaps.csv` | 已知缺口清單 | ✅ `assumptions.py` |
| `build_external_params.py` | 產生器 | — |

## 🔴 `dk_tax_and_tariff_params.csv` 是最容易誤刪的一個
`assumptions.py` **硬編**了四個稅費參數的數值,而這個 csv 是**唯一能回答
「這個數字哪來的」的東西**。每一列帶:
  param · year · value · unit · source_name · source_url · source_ref ·
  retrieved_date · note

例:`elafgift_dh_producer_net` = 0.4 øre/kWh,出處 Skatteforvaltningen
《Den juridiske vejledning 2025-1》E.A.4.3.6.2,法源 ELAL §11 stk.1 與 §11c
(lov 2225 of 29-12-2020 修正),抓取日 2026-08-09。

⚠️ note 欄還帶警告,例如 ARC 的 gate fee「**已含 ARC 自己的垃圾稅,
不要再另外加 CO2 稅項,會重複計算**」。

🔴 **SØB25 的生質價只從 2025 開始** —— 2021–2024 的缺口靠
`new_data/fuel/` 的 DST + 瑞典能源署兩個代理(見那邊的 SOURCE.md)。

## 不寫 schema
四個小 csv,不會變,只有 `assumptions.py` 讀一個。
**該有的是 self-check,而 `assumptions.py` 已經有 `warn_placeholders()`。**