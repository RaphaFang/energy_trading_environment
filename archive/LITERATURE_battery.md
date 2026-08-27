> # 🔴 2026-08-27:**整份過時,待重寫**
>
> 下面那句「本專案 = 丹麥 DA 市場多 agent 儲能競爭(λ 價格衝擊 + 輪流最佳反應解 Nash)」
> 是 **2026-08-04 就關掉的電池線**的定義。λ 已量定 ≈0.005 且該路線結案。
>
> **現行方向見 [`HANDOVER.md`](HANDOVER.md)** —— 單體交易 agent、無對手模型、
> 15 分鐘改制。要找的文獻是 **intraday/day-ahead 交易的 RL**、**預測誤差的經濟價值**、
> **不平衡結算**,不是儲能賽局。⚠️ 重寫前不要引用這份裡的任何主題分類。

# 文獻筆記(Literature Log)

> 論文查閱庫。每篇一段**中文 abstract** + **跟本專案的關係** + 連結,方便日後調閱。
> 本專案 = 丹麥 DA 市場多 agent 儲能競爭(λ 價格衝擊 + 輪流最佳反應解 Nash)。
> 每次查文獻都往這裡加,不要散在對話裡。

---

## 主題 A:儲能套利的賽局模型(多 agent、內生電價)

這一主題直接對應我們的第 2 層:多顆電池因「共同市場價」而耦合,建成 non-cooperative game。

### A1. Strategic Storage Investment in Electricity Markets

- **連結**:https://arxiv.org/pdf/2201.02290
- **中文 abstract**:多個投資人可投資**異質**儲能、互相競爭套利收益。因為市場價由「所有投資人的儲能操作」共同決定,各家的儲能決策彼此**耦合**,故建模成非合作賽局;可用市場資料刻畫「儲能對市場價的衝擊」(= 我們的 λ),據此用一個集中式最佳化問題算出 Nash 均衡。
- **跟我們的關係**:**幾乎是我們的原型**。異質儲能 + 價格耦合 + 用資料估價格衝擊 + 算 Nash,四點全中。是「λ 該怎麼從資料估」和「異質 agent」兩個下一步的直接參考。

### A2. Modeling Stochastic Multi-Agent Interaction in Intraday BESS Dispatch with Market Power

- **連結**:https://arxiv.org/html/2605.01178
- **中文 abstract**:日內(intraday)電網級電池的隨機賽局模型。每個電池營運商競爭性地管理 SoC 以最大化套利收益,而電價是**內生的**——**等於所有人充電率的總和**推動。所得的有限玩家「線性-二次微分賽局」的 Nash 均衡,用一組 Riccati 方程刻畫。
- **跟我們的關係**:內生電價 = 充電率總和,**正是我們 `歷史價 + λ×淨量` 的連續時間版**。若之後想要 Nash 的「精確解」對照(不只靠迭代),它的 Riccati/LQ 框架是路線。

### A3. Bidding Strategies for Energy Storage Players in 100% Renewable Electricity Market: A Game-Theoretical Approach

- **連結**:https://arxiv.org/html/2509.26568
- **中文 abstract**:在 100% 再生能源電力市場中,用賽局論方法設計儲能玩家的報價策略。
- **跟我們的關係**:報價策略層面的參考(我們目前是量的競爭,不是報價階梯);高再生能源情境跟丹麥 DK1/DK2 高風電吻合。

### A4.(發現)同質電池正面對撞常常不是均衡

- **來源**:上述搜尋中一篇指出——**同質**電池頭對頭競爭常常**不是**均衡,因為它把套利價差壓垮;實務上會形成**非對稱的 leader-follower(領導-跟隨)均衡**。
- **跟我們的關係**:**直接印證**我們 λ=12「大家擠到虧錢、租值 100% 消散」的結果,並且說明**為什麼該做異質 agent**——同質互撞是退化情況,異質才有結構。

---

## 主題 B:方法論——連續策略賽局怎麼解 Nash

回答「我的策略是連續的,有限賽局那套(payoff matrix / Lemke-Howson)不適用」。

### B1. Rosen (1965) — Existence and Uniqueness of Equilibrium for Concave n-Person Games

- **關鍵字**:concave n-person game、diagonal strict concavity、variational inequality
- **中文 abstract(經典結果)**:給連續策略、報酬對自己策略是凹函數的 n 人賽局,證明 Nash 均衡**存在**;在「對角嚴格凹」條件下**唯一**。這是連續策略賽局的存在唯一性基石,對應的求解框架是變分不等式(VI)。
- **跟我們的關係**:**這是我們該引的理論靠山**——說明我們的賽局(每人選 48 個連續實數、報酬對自己是凹的)Nash 存在,不必套有限賽局那套。待補精確引用。

### B2. Monderer & Shapley (1996) — Potential Games

- **中文 abstract(經典結果)**:定義 potential game(位勢賽局);其中「最佳反應動態(best-response dynamics)」**保證收斂到 Nash 均衡**。
- **跟我們的關係**:**這是我們輪流最佳反應會收斂的理論保證**。要在論文裡論證「為什麼迭代能收斂到 Nash」就引它。待補精確引用。

---

## 主題 C:丹麥電力市場結構(情境設定的依據)

回答「市場裡有幾隻鯨魚、該設幾個 agent、長尾要不要當 agent」。**直接決定我們設幾個玩家、體量怎麼分。**

### C1. 丹麥發電/批發端集中度(整理自官方報告)

- **來源**:Forsyningstilsynet(DUR,監管機構)National Report / Wholesale Market Report;Energinet(TSO,有 BRP 清單);Danmarks Statistik。(**數字待一手核對**,部分 CHP/PV 座數為 2014–2016 年。)
- **中文 abstract**:
  - 全國年發電量約 **32.6 TWh**(2023)。
  - **兩大發電商 Ørsted + Vattenfall 合計僅約 35%**(歐洲標準算分散,非壓倒性主導)。歷史對照:2004 年發電端 HHI 曾 >5,000(高度寡占),再生能源+自由化把它稀釋掉了。
  - 中型玩家:RWE、European Energy、Better Energy、Eurowind、Verdo(地區型)。
  - 零售端另計:2023 約 56 家供電商,前三大 >50%、最大約 25%,零售 HHI ≈ 1,200(低集中)。
  - **小電廠長尾(丹麥特色,極度分散)**:風機約 6,974 台 / 7.3 GW(離岸約 630 台);太陽能 ≈ 3.5 GW、數萬個小系統;分散式 CHP 約 1,000 座;大型中央電廠僅約 20 座。
- **對本專案最關鍵一點**:**physical plant count ≠ strategic bidding agent count**。那幾千台風機、上萬個 PV 幾乎都是**近零邊際成本的 price-taker**(以 ≈0 報價,不會策略性保留產能),不該當 agent。真正有市場力、能隱性勾結的是**少數有可調度組合的大玩家**(Ørsted、Vattenfall、RWE…)+ 跨區進出口。
- **對建模的直接含義**:
  1. **small-N 寡占(約 3–8 個策略性 agent)反而比「幾千個 agent」更貼近丹麥真實價格形成**;正當性論述:collusion 只在能設價的少數 portfolio 之間才有意義。長尾再生能源當**外生的、近零成本 residual demand shifter**,不是 agent。
  2. DK1(西)與 DK2(東)是**兩個獨立競價區**,且丹麥是夾在水電北歐與火電歐陸間的 **transit country**,interconnector 進出口對出清價影響很大。**baseline 先鎖單一競價區封閉系統,互聯當敏感度分析**,否則進出口會 confound 掉 collusion 訊號。
- **待查 TODO**:去 Energinet / DUR Market Report 挖 **BRP 實際數量** 和發電端最新 **HHI** = 「到底有幾隻鯨魚真正報價」的精準答案。

---

## 待查(TODO)

- [ ] **BRP 實際數量 + 發電端最新 HHI**(Energinet / DUR)→ 用來定 10 個玩家的體量分布。
- [ ] λ 的實證估計:merit-order effect / residual-demand 斜率,控制 gas+EUA 的文獻。
- [ ] Rosen 1965、Monderer-Shapley 1996 補上正式引用資訊(期刊、頁碼)。
- [ ] 丹麥 DK1/DK2 具體的儲能/市場結構文獻(Energinet、Nord Pool)。

---

## 🔴 主題 D:內生價格與市場力的實證方法(2026-08-19 新增)

> ⚠️ **這一整節憑既有知識寫的,還沒讀原文。引用前必須自己核對。**
> 起因:重新檢視論文路徑時問「我不會是第一個想做多 agent 交易員的人,別人怎麼繞過 λ?」
> **答案是:沒有人繞過。只有三種活法。**

### 🔑 前提:多 agent 競爭 ≡ λ

agent 報高於成本,只有在「壓低出力能推高價格」時才有利,而那就是 λ>0。
**λ=0 時最佳策略就是照成本報。** → **不能靠多加 agent 繞過 λ,多 agent 正是產生 λ 的機制。**
⚠️ 對應的實作區分:**按「成本」排序的 merit order = 中央調度 / 完全競爭基準**;
**按「報價」排序才是多 agent 市場。兩者之差就是市場力。**

### D1. 模擬整場拍賣(agent-based computational economics)

`PowerACE`(Fraunhofer ISI / KIT)、`AMES`(Tesfatsion & Sun)、`EMCAS`(Argonne)、`MASCEM`。
**做法**:agent 報價 → 跑真的出清演算法 → 價格掉出來。**λ 內生,不需要估。**
**代價**:必須建市場裡的每一台機組。
🔴 **對本專案是壞消息**:PowerACE 之所以同時模擬多個歐洲市場,**正是因為單一小國建了也沒用**
—— 而那正是 DK2 的處境(見 `DATA.md` §9.5:DK2 88.4% 的小時價格與至少一個鄰國相同)。

### D2. 不估 λ,用「讀」的

Wolfram (1999) 英格蘭與威爾斯;Borenstein, Bushnell & Wolak (2002) 加州。
**做法**:用其他所有參與者**已公布的報價曲線**直接畫出自己面對的殘餘需求曲線,
**λ 就是那條曲線在出清點的斜率** —— 用讀的不是用迴歸估的,**循環論證從源頭不存在**。
🔴 **待查(高價值)**:**Nord Pool 有公布逐時的聚合供需曲線。若 DK2 分區的拿得到,λ 根本不用估。**

### D3. 測加價,不要反事實價格

`市場力 = 價格 − 邊際成本`(Lerner 指數)。**完全不需要 λ**,因為要的不是「沒有我的話價格會是多少」,
而是「當時邊際那一台的成本」。
🔑 **這正是本專案的 CHP 成本模型已經在做的事** —— 用 DEA 技術目錄 + 燃料價建成本曲線,不碰價格。
簡報頁 8 的「要打破循環,p₀ 必須從成本結構推出來」**就是這一支文獻,只是當時不知道它有名字。**

### D4. 供給函數均衡(SFE)

Klemperer & Meyer (1989) 理論;Green & Newbery (1992) 應用到英格蘭與威爾斯電力池。
agent 選的是整條**供給函數**。**需要:成本結構已知、參與者少、而且市場相對封閉。**
→ **對 DK2 不適用**(開放小價區),但值得在文獻回顧交代為什麼不用。

---

⚠️ **主題 A/B 是電池線的**(儲能賽局、內生電價、Nash)。CHP 線的範圍應該是
**區域供熱電氣化 / 適足性 / 部門耦合**,加上這裡的主題 D。**整份仍待重寫。**
