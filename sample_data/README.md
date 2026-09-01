# sample_data/ — `new_data/` 的可攜切片

**用途**:讓程式在沒有完整資料的情況下跑得起來(CI、換電腦、給別人驗證)。
**不是**論文用的資料 —— 論文一律用 `new_data/`。

```
145 個檔 · 238.4 MB → 49.4 MB
```

## 窗口:2024-09-01 → 2026-09-01(UTC,兩年)

刻意包含全部四個制度日期,前面留半年改制前基準:

| 日期 | 事件 |
| --- | --- |
| 2025-03-18 | aFRR 進入不平衡價的定價規則(`D_AFRR`) |
| 2025-04-09 | ENTSO-E 的 DK2 `Waste` 欄開始作廢 |
| 2025-09-30 | 日前市場轉 15 分鐘制(`D_DA15`) |
| 2025-12-08 | mFRR EAM 定價缺陷永久修正 → 乾淨窗口起點(`D_FIX`) |
| 2026-01-06 | Energinet `ElectricityBalanceNonv` 靜默停發 |

四個 DST 切換(2024-10 / 2025-03 / 2025-10 / 2026-03)也都在裡面。

## 🔴 檔名還是原本的窗口,不代表內容

```
price_dk2_2019-01-01_2026-08-21.parquet     ← 內容其實是 2024-09 起
```

**保留原檔名是為了讓下游的 glob 不用改。** 但這正是這個 repo 踩過兩次的
「檔名騙人」坑 —— 用之前一定要看實際的時間範圍,不要信檔名。

## 例外

| 檔 | 差別 |
| --- | --- |
| `heating_consumption/heating_el_municipality_*` | 只切**一年**(2025-09 起)+ 只留 DK2 兩個 region、**扣掉 Bornholm**(市代碼 400,接瑞典、不在 DK2 同步電網)。原檔 141 MB,不這樣切放不下 |
| EPT · heating_stock · DEA · soeb25 · PDF | **沒有時間軸,全部照原樣複製** |

## 沒有進來的四項

| | 為什麼 |
| --- | --- |
| `energy.duckdb` | 🔴 **衍生檔**,`python new_src/data/load_duckdb.py` 重跑就有 |
| `_superseded/` | 已退場的舊檔 |
| `plandata/*.json`(26 MB) | 零程式引用,而且給的是**空間規劃**不是時序 |
| `generation/`(3.6 MB) | 零程式引用;DK2 `Waste` 欄 2025-04-09 起作廢 |

## 保真度(2026-09-01 實測)

- **逐格比對 71 個檔:70 個與 `new_data/` 對應窗口完全相同**
  剩 1 個是 `plandata/varmeplansomraader.parquet` 的 `doklink` / `systid_til`,
  **整欄 1,694/1,694 都是空值**,dtype 從 `object` 變 `float64` —— 沒有值可以損失。
- **53 個 parquet 對 pandera 契約驗證:失敗 0**
- 壓縮 zstd level 19,**無損**。

## 🔴 建這份時踩到的兩個坑

**① duckdb 的 `COPY ... TO parquet` 會丟掉 pandas 的 index 中繼資料。**
entsoe / fuel / generation 那些「時間軸在 index」的檔切完會變成 RangeIndex,
`timestamp_utc` 掉成普通欄位 —— 結構就跟原檔不一樣了。
→ 那些檔改走 pandas(它們都很小),欄位型的才用 duckdb。

**② duckdb 的 `TIMESTAMP '...'` 字面值是無時區的。**
跟 `TIMESTAMP WITH TIME ZONE` 的欄位比較時會用 **session 時區**
(本機是 Europe/Copenhagen)→ 整個窗口偏移 2 小時,**而且不會報錯**。
→ 連線後必須 `SET TimeZone='UTC'`。

🔑 **這兩個都是 pandera 契約驗證抓不到的** —— 偏移兩小時的窗口,
單調、唯一、值域三項全都合格。**只有跟原檔逐格比對才看得出來。**
