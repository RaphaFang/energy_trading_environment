# Energinet Energi Data Service — 不平衡價

來源:https://api.energidataservice.dk/dataset/
  imbalance_dk*    RegulatingBalancePowerdata  逐時(舊制),2019 起
  imbalance15_dk*  ImbalancePrice              15 分,2025-03 起

## 🔴 這是論文主線的資料
不平衡價 = 交易 agent 的收益來源。日前承諾 10 MW,實際交割偏差,差額按這個價結算。
`new_src/trading/imbalance_regimes.py` 從這裡定義三個制度日期,
被 agent.py / agent_search.py / oracle.py / why_not_predictable.py 四支 import。

## 三個制度日期(乾淨窗口的由來)
  D_AFRR = 2025-03-18        aFRR 進入不平衡價的定價規則
  D_DA15 = 2025-09-30 22:00  日前市場轉 15 分(交割 10-01 丹麥時間)
  D_FIX  = 2025-12-08        mFRR EAM 定價缺陷永久修正 → 🔑 **乾淨窗口起點**

🔴 **跨接縫比 2024 vs 2025,量到的是市場改革,不是 agent 績效。**
€26→€76 的變化不是市場變劇烈,是 aFRR 在 2025-03-18 進了不平衡價的定價規則。

## 欄位
逐時(14 欄):ImbalancePrice{EUR,DKK} · BalancingPowerPrice{Up,Down}{EUR,DKK} ·
             mFRR{Up,Down}Act{Bal,Spec} · ImbalanceMWh
15 分(18 欄):上面加 SpotPriceEUR · SatisfiedDemand · DominatingDirection ·
             aFRR{Up,Down}MW · aFRRVWA{Up,Down}{EUR,DKK} · mFRRMarginalPrice*

⚠️ DominatingDirection 是 **float(-1 / 0 / 1)**,不是字串。