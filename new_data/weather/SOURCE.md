# Open-Meteo Historical **Forecast** API — 天氣特徵

來源:https://historical-forecast-api.open-meteo.com/v1/forecast
座標:DK1 (56.0, 9.0) · DK2 (55.7, 12.3)
涵蓋:2019-01-01 → 2026-08-21

## 🔴🔴 為什麼一定要用 historical-**forecast**-api

它存的是**當時的模型預報**,不是事後的實測。
7 月 1 日那一列裝的是「當時預報 7 月 1 日會怎樣」,不是「7 月 1 日實際怎樣」。

🔴 **用一般的 archive-api(ERA5 再分析)會 LEAK。**
ERA5 是事後同化實測產生的,日前競價當下拿不到。

## ⚠️ 一個已知的不完美
前置期**沒有釘在日前 12:00 的關門時間**,取的是「最新的短前置預報」。
第一版可以接受,但如果回測分數看起來太好,要升級成釘住 model-run
(Open-Meteo 的 previous-runs / model-runs API)。

## 欄位
  hour_utc · area
  temperature_2m · cloud_cover(**整數百分比**)
  wind_speed_100m · wind_gusts_10m · wind_direction_100m(**整數**)
  shortwave_radiation · direct_radiation · diffuse_radiation

## 🔴 風速的單位存疑(2026-09-01 實測)
  DK1 wind_speed_100m 最大 **95.3** · wind_gusts_10m 最大 **126.7**
  DK2 分別是 83.2 / 118.8

95 m/s = 342 km/h,丹麥不可能。**95 km/h = 26 m/s 則很合理。**
→ 高度懷疑 API 回的是 **km/h 不是 m/s**。
🔴 **沒確認之前不要拿去算風機出力** —— 差 3.6 倍。