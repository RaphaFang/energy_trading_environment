# 政策文件(Klimaframskrivning / Klimaaftale / ENS 監測報告)

⚠️ **沒有任何程式讀這個資料夾。** PDF 是**出處憑證**,
真正被程式用的是 `new_src/heat/plant_lifetimes.py` 裡逐字轉錄的常數。
每份 PDF 旁邊有 `markitdown` 轉出的 `.md`,方便 grep。原始 PDF 在 `pdf/`。

## 檔案與下載連結

| 檔 | 下載 |
| --- | --- |
| `kf26_el_og_fjernvarme` | https://www.kefm.dk/Media/639058804066502895/7.%20KF26%20forudsaetningsnotat%20El%20og%20fjernvarme.pdf |
| `kf25_el_og_fjernvarme` | https://www.kefm.dk/Media/638835926226490298/7.%20KF25%20forudstningsnotat%20El%20og%20fjernvarme.pdf |
| `kf26_introduktion` | https://admin.kefm.dk/Media/639058804252441086/1.%20KF26%20forudsaetningsnotat%20Introduktion.pdf |
| `kf25_introduktion` | https://www.kefm.dk/Media/638743415001838643/1.%20KF25%20forudsætningsnotat%20Introduktion.pdf |
| `kf25_hoeringsnotat` | https://www.kefm.dk/Media/638917252048649856/KF25%20Hringsnotat.pdf |
| `kf25_kapitel26_affaldsforbraending` | https://www.kefm.dk/Media/638822888958253044/Kapitel%2026%20Affaldsforbrnding.pdf |
| `kf24_kapitel25_affaldsforbraending` | https://www.kefm.dk/Media/638500583574605267/KF24%20Kapitel%2025%20Affaldsforbrænding.pdf |
| `ens_monitorering_affaldsforbraending_2024` | https://ens.dk/media/6180/download |
| `klimaaftale_groen_stroem_og_varme_2022` | https://www.kefm.dk/Media/637920977082432693/Klimaaftale%20om%20grøn%20strøm%20og%20varme%202022.pdf |

## 🔴 哪些數字從哪裡抄出來的(論文會被問)

→ **這一段要你自己補**,我不知道每個數字對應第幾頁。
   `plant_lifetimes.py` 現在只記了「KF25/KF26 表 5.3/5.4」,
   建議補到「文件 + 表號 + 頁碼」的粒度:

| 轉錄到哪 | 數字 | 出處(文件 / 表 / 頁) |
| --- | --- | --- |
| `plant_lifetimes.py` | AMV1 = 2029 | kf25_el_og_fjernvarme 表 5.3,第 ? 頁 |
| `plant_lifetimes.py` | AVV1 = 2033 | 同上 |
| `plant_lifetimes.py` | HCV8 = 2026 | 同上 |

## 不寫 schema
PDF 沒有表格結構可驗。**要驗的是 `plant_lifetimes.py` 的 self-check。**

## ⚠️ 一個已知的誤用
`energinet_elforsyningssikkerhed_2025` 裡的「2030 缺電 178 分鐘」
**出處其實是 2020 年 Dansk Energi 批評草案的新聞稿**,不是 Energinet 預測 → **不要用**。