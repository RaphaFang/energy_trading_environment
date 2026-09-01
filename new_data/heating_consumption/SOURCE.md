# Energinet Energi Data Service — 家戶供暖用電(逐時)

來源:https://api.energidataservice.dk/dataset/
  heating_el_national      PrivateConsumptionHeatingNationalHour
  heating_el_municipality  PrivateConsumptionHeatingHour

涵蓋 2021-01-01(DK 時)起 —— **這是來源自己的起點,不是 window.START**。

| 檔 | 粒度 | 列數 |
| --- | --- | --- |
| national     | 5 住宅型態 × 3 供暖方式 | 481,384 |
| municipality | 上面 × 98 個市 | 31,064,864 |

## 這份在回答什麼
瓦斯戶改用熱泵之後,**電力尖峰會變多少、搬到哪個月**。
已得結論:天氣調整後年增 20%、尖峰 959 MW ≈ Amager+Avedøre 替代量的 1.4 倍。

## 🔴 三個坑
**① HeatingCategory 有三類不是兩類**:`Elvarme eller varmepumpe` / `Andet` / **`-`**
   寫 `!= "Andet"` 會把 `-` 混進來。
**② 「電暖」與「熱泵」在這個來源裡是同一類,拆不開** —— 問「熱泵有多少」答不了。
**③ national 是 municipality 的完美加總**(實測 481,384 列 100% 逐格相同,最大差 0.0 kWh)
   → 拿 national 去「驗證」municipality 是**同義反覆,永遠不會失敗**。
   `new_src/heat/sector_coupling.py:122` 的 verify_against_national() 就是這個問題。

## ⚠️ 只有 municipality 能切 DK2
需要 RegionName(Hovedstaden + Sjælland)+ **扣掉 Bornholm(市代碼 400,接瑞典、
不在 DK2 同步電網)**。national 做不到。

## 儲存
2026-09-01 起以 (HousingCategory, HeatingCategory, TimeUTC) 排序 + zstd,
逐市版 257 MB → 141 MB(−45%),讀取 0.28s → 0.22s,**內容一格未改**。
🔴 副作用:**TimeUTC 在整份檔上不再單調**(組內仍單調)。