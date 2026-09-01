# Plandata.dk — 供熱規劃區(varmeplansområde)

來源:https://geoserver.plandata.dk/geoserver/wfs
      service=WFS&version=2.0.0&request=GetFeature

| 圖層 | 內容 |
| --- | --- |
| `theme_pdk_varmeplansomraade_vedtaget_v` | **已通過** 1,355 區(21.8 MB GeoJSON) |
| `theme_pdk_varmeplansomraade_aflyst_v`   | **已撤銷** 339 區(4.4 MB)← 🔑 計畫失敗的證據 |
| `varmeplansomraader.parquet`             | 抓取腳本產的彙總表(0.15 MB) |

## 為什麼需要
丹麥**沒有單一的全國熱網計畫**。全國性規劃是 2022 年政府與 KL 的協議
(各市 2023 年底前核准專案、**2028 完成**),由 **98 個市各自執行**。
Plandata 是那 98 份計畫**唯一匯總得到的地方**。
KF25/KF26 也明說它們的 pipeline 專案來源之一就是 plandata 的 varmeforsyningsprojekter。

## 🔑 最有用的三個欄位
  `vaerdi1207`   供熱方式:**Fjernvarme 904 區 vs Individuel varmeforsyning 790 區**
  `konvslutaar`  轉換完成年 —— 🔑 **288 區指向 2028**,正好對上 KL 協議的期限
  `virknavn`     負責的供應商(Vestforbrænding 23 區、VEKS 27 區…)

## ⚠️ 四個坑
1. **這是空間計畫,不是需求序列。** 它說「哪塊地哪一年改成什麼」,
   **不會**告訴你逐時熱需求。別當熱需求資料用。
2. `datovedt` / `datoaflyst` 是 **YYYYMMDD 的整數**,不是日期型別。
   直接 `to_datetime` 會變 1970。
3. `forvarme` **99% 是空的**,不要用。
4. 論文引用的結論(`demand_trend.py:35`「plandata 有一半的區劃成個別供暖」)
   是人讀出來的,**沒有程式在讀這些檔**。

## 不寫 schema
一次性下載、不會變、沒有程式讀 → 放 CI 永遠綠。