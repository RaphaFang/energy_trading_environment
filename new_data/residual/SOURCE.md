# Energinet EDS — 負載 / 風 / 光 / 殘餘負載(逐時)

來源:https://api.energidataservice.dk/dataset/ProductionConsumptionSettlement
涵蓋:2018-12-31 → 2026-08-12(**還活著**,不像 ElectricityBalanceNonv)

欄位:hour_utc · area · load_mwh · wind_mwh · solar_mwh · residual_mwh

## 🔴🔴 這份是**實測**,拿來當日前預測的特徵會 LEAK

`new_src/trading/agent.py:110` 明文警告:

> `new_data/residual/` 是同名但**用實測算的**,那個會 leak。

agent 用的 `own_residual` 是**當場算的**:

(`load_da` 來自 entsoe `loadfc_*`,`wind_da`/`solar_da` 來自 `forecast/`)

→ **這個資料夾只能當事後驗證,絕不能進 agent 的特徵。**
   同一個名字有兩個東西,而且一個會毀掉整個回測。

⚠️ 鄰國的 `entsoe/derived/residual_*` **是安全的**(用日前預測算的),
   agent.py:123–125 有在用。**別跟這個資料夾搞混。**

## 🔑 residual_mwh 是純算出來的
實測 `residual = load − wind − solar`,最大差 **0.00000000**。
→ 那一欄是恆等式,可以寫成 schema 的欄間檢查。

## ⚠️ 太陽有微負值
DK1 683 列 / DK2 568 列 `solar_mwh < 0`,最小 −0.60。
數值很小(可能是計量或四捨五入),但**物理上不該存在**。原因未查。