> # 🔴 2026-08-27:**五支程式碼已從工作區移除**
>
> `v2_multi.py` · `v3_cournot.py` · `v4_wind.py` · `experiment.py` · `compare.py`
> —— Cournot / λ / 多 agent 最佳反應那一套。**λ 量定 ≈0.005,該路線結案。**
>
> **拿回來**:`git show battery-track-final:new_src/battery/v3_cournot.py`
> 或 `git restore --source=battery-track-final new_src/battery/`
>
> ✅ **留在工作區的兩支是交易線的地基**:`v1_single.py`(資訊階梯)、`fringe.py`(殘餘需求曲線)。
> 🔑 **這份文件現在的用途:交易線的前情提要** —— λ 為什麼是 0、預測管道長什麼樣。
> 現行方向見 [`HANDOVER.md`](HANDOVER.md)。

# 電池線 + 預測管道 — 設計、結果、結案理由

> 合併自舊的 `SIMULATOR_OVERVIEW.md` + `MULTI_AGENT_MARKET.md` + `MODEL_MATH.md`(2026-08-07)。
> **狀態:2026-08-04 結案(park)。** 程式碼在 `new_src/battery/`(原 `new_src/agents/`)。
> 現行主線是熱側(CHP/區域供熱),見 `STATUS.md`。

**為什麼保留這份**:電池線的結論本身是有效的研究產出(DK1 是 price-taking 價區),
而且預測管道(`new_src/models/`)是**獨立資產**,兩條線都能用。丹麥市場的事實(§6)也可重用。

---

## 1. 結案理由(先講結論)

> **λ 的機制沒有壞,它給出了正確答案,而那個答案是「≈0」。**

DK1 本質是強互聯的 **price-taking 價區**(對外 ~6,000+ MW 連接容量、風佔 54%),
本地供需衝擊被進出口吸收 → **「儲能 agent 在 DK1 日前市場行使市場力」的答案是「幾乎不存在」**。

這是乾淨的結構性結果,不是失敗;但 null result 撐不起碩論引擎。加上丹麥全國併網電池僅
10–30 MW,GW 級車隊是虛構的反事實 → 轉向 CHP/區域供熱。

### λ 的最終定案(控制強度階梯,工具 = 丹麥隔日風力預測)

| 規格                 | OLS        | IV         |
| -------------------- | ---------- | ---------- |
| S1 只控 gas/co2/小時 | 0.0259     | 0.0320     |
| S2 +德國殘餘         | 0.0134     | 0.0220     |
| S3 +德風光分開+鄰居  | 0.0068     | 0.0122     |
| **S4 +邊界容量**     | **0.0053** | **0.0092** |

- **控制一變嚴,高估計群全部塌掉** → 「λ=0.037」那類高值是鄰國混淆的產物。
  `structural_lambda` 的 0.0042 與 S4 的 0.0053 一致 → **修正是對的**。
- **IV/OLS 在每個規格都穩定 ~1.7×** = 量測誤差(EIV)修正。直接驗證:x 換成**隔日預測殘餘**
  (市場清算時真正看到的量)→ λ 從 0.0134 跳到 **0.0179**。
- ⚠️ **`fit_fringe` 是零控制的雙變數保序迴歸**(中位 0.0224 ≈ 裸 OLS)→ 落在被鄰國汙染的高群,
  **非線性 impact 用的曲線系統性太陡 3–4 倍**。

---

## 2. 模型設定:LP 與電池規格

### `perfect` = 完美預知的 LP(所有 % 的分母)

```
決策:每小時充 c_t、放 d_t(一週 168h → 336 個變數)
目標:max Σ p_t·(d_t − c_t)
限制:0 ≤ c_t, d_t ≤ P
     0 ≤ SoC_t ≤ E
     SoC_t = SoC_{t−1} + √η·c_t − d_t/√η
     SoC_{t−1} + √η·c_t ≤ E        ← 充電當下也不能爆容量(見 §5 的 bug)
     SoC_窗末 = 0
```

scipy HiGHS 幾毫秒解出全域最佳。**它拿真實未來價 → 是「這週最多能賺多少」的上限。**

### 電池規格:哪些有根據、哪些是簡化

| 設定       | 值                   | 有根據嗎                                        |
| ---------- | -------------------- | ----------------------------------------------- |
| P / E      | 1 MW / 4 MWh(4 小時) | ✅ 「4 小時時長」是併網電池的業界標準規格       |
| 往返效率 η | 0.90                 | ✅ 鋰電併網系統典型 85–92%                      |
| 結算窗     | 一週(168h)           | ✅ 已驗證月窗 ≈ 週窗(每週折算只多 ~1%,排名不變) |

⚠️ **最大的簡化**:丹麥真正的大玩家不是電池,是風電 + 生質/垃圾 CHP + 燃煤。
「10 顆電池競爭」是研究「套利 + 價格衝擊」的**乾淨玩具模型**,不是丹麥發電的字面寫照。
這個定位問題最終促成了轉向熱側。

---

## 3. 版本階梯

| 版本     | 檔案                   | agent 設定            | 內化自身衝擊 | 資訊            |
| -------- | ---------------------- | --------------------- | ------------ | --------------- |
| v1       | `v1_single.py`         | 1 顆,price-taker      | —            | perfect / naive |
| v2.1     | `v2_multi.py`          | N 家同質              | ❌           | 上帝視角        |
| v2.2     | `v2_multi.py`          | N 家同質              | ❌           | 共用一份預測    |
| v2.2-het | `experiment.py hetero` | 10 家同體量、異質預測 | ❌           | **每家一份**    |
| v2.3     | `experiment.py v2.3`   | 體量連續掃 10MW→10GW  | ❌           | 每家一份        |
| v3       | `v3_cournot.py`        | 10 家異質體量         | ✅ Cournot   | 上帝視角        |
| v3-CNM   | `experiment.py scales` | 三把尺 C≤N≤M          | ✅           | 上帝視角        |
| v4       | `v4_wind.py`           | 風商 + 電池採用率     | 可選         | 上帝視角        |

**依賴單向 `v4 → v3 → v2 → v1`**。v3 不改 v2,只把最佳反應用 `solve_day(..., br=cournot_br)` 傳進去。

`solve_day` 支援**三個異質維度**:`weights`(體量)、`belief`(資訊)、`br`(策略),
每個都可以「全員共用」或「每家一份」。⚠️ **異質策略(br 傳函式列表)從沒跑過**,是免費的缺口。

### v3 的 Cournot 怎麼解

目標多一項 `−λ·w_i·Σ(自己淨量)²` → LP 變 QP。沒裝 QP solver,用 **Frank–Wolfe 重用
`perfect()` 的 LP 當 oracle**(有效邊際價 = seen + 2λw_i·淨量,閉式線搜)。

三把尺都是 Cournot 的特例:

- **M 卡特爾** = 規劃者內化全體 λ·ΣW(= own weight 設成總體量),一個 QP 解完
- **N Nash** = `solve_day(..., br=cournot_br)`
- **C 競爭** = 把總體量拆成 n 個對稱小廠跑 Cournot(廠越多 → 每廠市場力 → 0)

恆有 `C ≤ N ≤ M`;勾結指標 `Δ = (Π_obs − Π_N)/(Π_M − Π_N)`。

---

## 4. 預測管道(獨立資產,兩條線都能用)

程式在 `new_src/models/`:`forecast.py`(建模唯一一份)+ `baseline.py`(準度報表)。

### 三個模型的算式

**naive-24h(地板)**:`ŷ = price_lag24`。零學習,存在的意義是**當一把尺**。

**Ridge / Lasso(LEAR)**:`ŷ = b + Σ wᵢ·xᵢ`,訓練 = 找那些 wᵢ:

```
Ridge:  min Σ(y−ŷ)² + α·Σwᵢ²      逼權重別太大
Lasso:  min Σ(y−ŷ)² + α·Σ|wᵢ|     絕對值 → 把沒用的壓成 0 = 自動挑特徵(LEAR)
```

權重有物理意義:**風力預測權重為負**(風多→電多→價跌)、**週末為負**。數學自己從資料長出來的。

**LightGBM**:`ŷ = 基準 + Σ fₖ(x)`,每棵樹只修前面樹沒修好的殘差(gradient boosting)。

### 指標

```
MAE  = (1/N)Σ|y−ŷ|                 平均差幾歐
RMSE = √((1/N)Σ(y−ŷ)²)             重罰大失誤 → RMSE≫MAE 表示有尖峰爆走
rMAE = MAE_模型 / MAE_naive        <1 才及格
```

> 🔴 **2026-08-28 重測:下面這張表已經過時,排名翻掉了。**
> 當時測試期只到 2025 年中;資料延到 2026-08-21 後,同一個切分點的測試期變成 18,598 小時,
> **LightGBM 的 MAE 從 17.20 升到 25.54(rMAE 0.54 → 0.84),被 Lasso 反超。**
>
> 🔑 **原因查清楚了,而且不是「樹比較差」**:斷點正好在 **2025-10(日前市場轉 15 分鐘)**。
> 之後電價水準上移(DK1 月均 79 → 97),**LightGBM 系統性低估 €23.3,連逐月重訓都救不了**
> —— 樹的葉子值是歷史目標的平均,而擴張式訓練窗把新制度稀釋在七年舊資料裡;
> 線性模型靠燃料價係數就把整條預測抬高了(Lasso 逐月重訓偏誤只有 −2.0)。
> **前半期 LightGBM 其實是全場最強(DK1 MAE 16.67)。**
>
> ✅ **對症修法有效**:只用最近 12 個月 + 改預測「相對昨天同一小時的變化」
> → LightGBM 17.71、三模型平均 **17.10(rMAE 0.562)**。
> **現行數字跑 `python new_src/models/baseline.py`;完整網格見 `new_src/models/experiments.py`。**

### 結果進程(LightGBM,€/MWh)

| 階段                            | DK1 MAE   | DK1 rMAE | DK2 MAE   | DK2 rMAE |
| ------------------------------- | --------- | -------- | --------- | -------- |
| 只有本地 5 源                   | 24.36     | 0.76     | 23.48     | 0.70     |
| + ENTSO-E 鄰居風光/負載/NTC     | 23.52     | 0.73     | 21.71     | 0.65     |
| **+ 殘差 + offered-cap + 燃料** | **17.20** | **0.54** | **17.63** | **0.53** |

**線性模型也跟著跳**(DK1 Ridge 24.75 → 19.90)→ 證明是**真新資訊**,不是樹在湊特徵。

### 無 leak 驗證

LightGBM 分裂次數 top:`de_residual`(3764,第一)、`ttf_gas`(3204)、`price_lag24`、`eua_co2`(2410)。
**全部是自迴歸 / 隔日預報 / 已 shift −2 天的燃料價,沒有一個是同時刻實測。**
理論預測會重要的東西資料證實了 = 最強的反 leak 證據。

---

## 5. 關鍵發現

1. **單週會騙人**:單週排名 Ridge>LightGBM,掃 63 週後翻盤 = LightGBM 93% > Ridge/Lasso 91%(佔單顆基準)。
   **任何結論都要掃全期。**
2. **rMAE ≠ 錢**:rMAE 0.54 吃到 93% 的錢(套利只需**排序**對,不需價格準)。
   但平均藏尾巴:naive-24h 平均 79%、**最差週僅 12%**;冬天所有模型一起掉 10pp。
3. **「天花板」正名 = 「單顆基準」(per-battery numeraire),不是上限**:
   10 顆各拿 99% → 車隊 = 9.9× 單顆。會被超過 10 倍的東西不叫天花板,它是**計量單位**。
4. **真正的旋鈕是體量不是 λ**:`λ×淨量` 才是關鍵(λ=3.7×1MW ≡ λ=0.037×100MW)。
5. **真 λ 下市場不慘**:10 顆 1MW 只削 1%(99%)。之前 λ=6/12 崩盤是灌 100–300× 的 artifact。
6. **預測誤差成本 ≫ 價格衝擊成本**:v2.1(上帝視角)99% → v2.2(用預測)92%,
   而 v2.1 距單顆基準只差 1pp。
7. **修過的真 bug(天花板虛高)**:舊 `perfect()` LP 只管小時**結束時** SoC≤E,負價時會
   「同小時先充爆再放掉」偷分,而 `settle` 會夾掉 → agent 竟「贏過天花板」(107%)。
   修法:LP 加 `soc_{t−1}+√η·c_t ≤ E`,讓 LP 可行集 == settle 可行集。順便改稀疏 LP,
   720h 窗從數秒降到 0.01s。
8. **v2 的會計不對稱**:優化時看 `act+λ·別人`(不含自己),結算時 `cleared=act+λ·全體`(含自己)
   → 用「假裝動不了價」排程、被「自己壓過的價」結算。v3 Cournot 修掉它。
9. **乾淨的 C 怎麼做**:Walrasian tâtonnement(震盪)、representative-agent(發散)、
   ½-penalty QP(失真)全部不行。**正解 = 拆成 n 個對稱小廠跑 Cournot**,
   Gauss-Seidel 逐一更新自帶阻尼 → 穩定、聯合利潤 ≥0。

### 撤回的結論(留著避免重蹈)

❌ **「非線性 impact 讓預測優勢的門檻左移 7×」是錯的。** 四臂拆解證明那幾乎全是 λ 水準差異:
A(λ=.004 線性)2954MW → B(λ=.0224 線性)488MW → D(非線性)438MW。
**水準效應 6.1×、形狀效應只有 1.12×。** 錯因:線性臂用 λ=0.004、曲線臂中位 0.0224,
**同時差在水準與形狀**,比較被混淆了。

---

## 5.5 觀念釐清(從舊 `RECAP_2026-07-20.md` 保留;這幾個曾經一直卡住)

### `act` 是什麼

`act` = 歷史上真實的 day-ahead 出清價。**它是一個結果,不是一個輸入。**
裡面已經攪在一起:燃料成本、每個發電商的加價策略(市場力!)、鄰國透過連接線壓進來的價、
風光出力、需求。**沒辦法從 act 裡把任何一項單獨拆出來。**

`p = act + λ·Q` 的意思是:「拿歷史上真的發生過的價格,把我想像出來的電池隊的影響加上去。」

### 市場力是什麼

**不是「互相 bidding」這個動作,是「有能力靠報高價賺到錢」。** 小機組報高價沒人理它
(不被調度)= 沒有市場力;pivotal 機組(沒有它就湊不滿需求)報高價,市場**必須付** = 有市場力。
衡量方式是「價格 vs 邊際成本」或「實際價 vs 大家都照成本報價的價」——**兩種都需要成本資料**。

丹麥實況:DK1 對外 6,000+ MW 連接線、本地尖峰才 ~3.5 GW,進口隨時取代本地機組
→ **丹麥本地幾乎沒人是 pivotal。**

### ⭐ 混淆 vs 循環:兩個不同的病,可治程度完全不同

| 病       | 內容                                                  | 治得好嗎                                         |
| -------- | ----------------------------------------------------- | ------------------------------------------------ |
| **混淆** | 殘差裡混著德國、燃料、本地需求,分不清誰是誰           | **治得好** — 加控制變數、工具變數(§1 就是治這個) |
| **循環** | p₀ 是**用 act 擬合出來的**,act 減掉它必然是零均值噪音 | **加再多變數都治不好**                           |

循環的比喻:想知道一家店有沒有超收,要查它的**進貨成本**。若把「合理價」定義成
「這家店的平均售價」,那它在數學上**永遠不可能超收**,賣十倍也一樣。

**結論**:本模型可以做**相對比較**(A agent vs B agent,面對同一個 p₀),**不能宣稱絕對市場力**。
要打破循環,p₀ 必須**從成本結構推出來**(燃料÷效率 + 碳價×排放強度 + 機組容量),不能從價格擬合。

👉 **這正是熱側路線在做的事** —— 用 Technology Catalogue 的技術參數 + 燃料價建成本型供給曲線,
而不是從 act 擬合。見 `STATUS.md`。

---

## 6. 丹麥市場事實(有出處,可重用)

### 發電結構(2022,佔發電量)

風電 **54%**、生質+垃圾 **23%**、燃煤 **13%**、太陽能 **6.3%**、天然氣+油 **3.8%**。總發電 ~35 TWh。
兩大發電商 **Ørsted、Vattenfall**(精確 MW/市佔仍是 TODO,需查 Energinet BRP 清單 + DUR)。

### 併網電池:很少

最大案例約 10 MW(Better Energy Hoby)、30 MW/43 MWh(EWII Bornholm)、200 MWh 光儲
(European Energy Kvosted)。北歐到 2030 預估才 ~1,800 MW。→ **電池不是丹麥的價格制定者。**

### 跨國連接線 = DK 價格的真正主導

| 從      | 到   | 容量                                      | 備註                |
| ------- | ---- | ----------------------------------------- | ------------------- |
| **DK1** | 德國 | 1,780 MW(南向)/ 1,500(北向)               | 最大單一連接        |
| DK1     | 挪威 | 1,700 MW(Skagerrak 1–4)                   | 挪威水力 = 靈活調節 |
| DK1     | 瑞典 | 740 MW(Konti-Skan)                        |                     |
| DK1     | 荷蘭 | 700 MW(COBRAcable, 2019)                  |                     |
| DK1     | 英國 | 1,400 MW(Viking Link, 2023;目前限 800 MW) | 世界最長陸海 HVDC   |
| **DK2** | 瑞典 | 1,700 MW(Øresund)                         |                     |
| DK2     | 德國 | 600 MW(Kontek)                            |                     |

光 DK1 對外就有 ~6,000+ MW 連接容量,**遠超本地尖峰需求** → 價格常常是被進出口流決定的。
**這就是 λ 一控制鄰國就塌掉的物理原因**,也是整個結案結論的根據。

**出處**:

- [Electricity sector in Denmark — Wikipedia](https://en.wikipedia.org/wiki/Electricity_sector_in_Denmark)
- [Viking Link — Wikipedia](https://en.wikipedia.org/wiki/Viking_Link) / [Energinet: Viking Link](https://en.energinet.dk/infrastructure-projects/finished-projects/viking-link/)
- [Nordic battery storage outlook — Nordic Energy Research](https://pub.norden.org/nordicenergyresearch2024-05/more-flexible-storage-needed.html)
- [Better Energy 10 MW BESS](https://www.renewableenergymagazine.com/storage/better-energy-to-install-10-mw-battery-20240321)

---

## 7. 怎麼跑

```bash
python new_src/battery/v1_single.py      # 各檔自己的 self-check
python new_src/battery/v2_multi.py
python new_src/battery/v3_cournot.py
python new_src/battery/v4_wind.py
python new_src/battery/fringe.py         # λ 估計與診斷

python new_src/battery/compare.py W      # 統一比較表(W=週 / M=月)
python new_src/battery/experiment.py v3       # Cournot vs price-taker
python new_src/battery/experiment.py scales   # 三把尺 C/N/M
python new_src/battery/experiment.py hetero   # 異質預測品質
python new_src/battery/experiment.py v2.3     # 體量連續掃描
python new_src/battery/experiment.py v2.3-nl  # 同上但用非線性 impact
python new_src/battery/experiment.py v3-nl    # Cournot + 非線性 + 局部曲率自制
python new_src/battery/experiment.py iv       # λ 的 IV 識別檢查
```

⚠️ **全部從專案根目錄跑**(資料路徑是相對的)。
⚠️ 標「外推,勿引用」的結果來自 fringe 曲線的資料支撐範圍外(見 `fringe.out_of_support`)。
