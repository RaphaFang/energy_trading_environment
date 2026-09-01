# Danmarks Statistik BYGB40 — 建築存量 × 供暖方式

來源:https://api.statbank.dk/v1/data  ·  表 `BYGB40`
單位代碼:50 = Kvadratmeter(1000 m2)· 45 = Antal(棟數)

| 檔 | 用途 |
| --- | --- |
| bygb40_m2    | ✅ new_src/heat/demand_trend.py 在用 |
| bygb40_antal | ❌ 目前沒人讀 |

**用面積不用棟數**:熱需求跟面積成比例,跟棟數不成比例。

## 這份在回答什麼
**有多少 m² 現在燒瓦斯?** —— 那是熱泵替代的分母。

## 🔴 兩個坑
**① 檔名寫 2019,資料其實從 2011 開始**(TID: 2011–2026)。
   假設「2019 起」會多算八年。
**② INDHOLD 有 −1**:1 列(Albertslund / 2026 /「Ingen eller uoplyst opvarmning」)。
   是**缺值哨兵**不是負面積。另有 502 列真的是 0。

## ⚠️ 抓取時的取捨
`anvendelse` 與 `opførelsesår` 取合計(*),否則「全年份 × 全市 × 全用途 × 全建造年」會爆量。
要細分時再單獨抓。