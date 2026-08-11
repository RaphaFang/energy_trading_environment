"""DK1 熱電機組的燃料組成 — 決定原型機組該設成生質還是天然氣。

**為什麼要這支**:`chp.Plant` 原本用單一排放因子 `ef=0.20` 套用到所有燃料。丹麥大型
CHP 已大量轉生質,而生質在 EU ETS 下算零碳 → 對生質機組課碳成本會**系統性高估 CHP
成本、低估 CHP 競爭力,進而高估 power-to-heat 的價值**。要修這個偏誤,得先知道
DK1 的熱電機組實際上燒什麼。

資料:Energinet `ElectricityBalanceNonv`(已抓在 new_data/production/),逐時分燃料出力。
⚠️ 這是**發電量**的燃料組成,不是**產熱量**的。CHP 的功熱比隨機組不同,所以發電量
佔比不等於產熱量佔比。當作原型選擇的依據可以,當作精確權重不行。

用法:python new_src/heat/fuelmix.py
"""

import glob
import sys

import pandas as pd

# 這些欄位在丹麥幾乎都是熱電共生機組(CHP);風、光、水不是
THERMAL = ["Biomass", "Waste", "FossilGas", "FossilHardCoal", "FossilOil"]
# EU ETS 下的排放因子(tCO2/MWh_fuel)量級。⚠️ 仍是量級值,待 Technology Catalogue。
EF_HINT = {
    "Biomass": 0.0,  # 永續生質在 EU ETS 下算零碳
    "Waste": 0.0,  # 廢棄物焚化的計算複雜(生物質佔比),暫記 0,待查證
    "FossilGas": 0.20,
    "FossilHardCoal": 0.34,
    "FossilOil": 0.27,
}


def load(area: str = "DK1") -> pd.DataFrame:
    """讀分燃料出力並**先重採樣成逐時平均**再回傳。

    ⚠️ 這一步不能省:歐洲 day-ahead 在 2025-09-30 從 60 分鐘改 15 分鐘 MTU,這份 dataset
    後段是 15 分鐘一筆。直接對 MW 欄位加總,會把 15 分鐘那段算成 4 倍權重,燃料佔比
    就會被那段的組成拉偏(我第一版就踩了這個坑)。重採樣成逐時平均後,每筆代表 1 小時
    → 加總才是 MWh。
    """
    fs = glob.glob(f"new_data/production/production_{area.lower()}_*.parquet")
    assert fs, "先跑 python new_src/data/production_by_fuel.py"
    d = pd.read_parquet(fs[0])
    d["t"] = pd.to_datetime(d["HourUTC"], utc=True)
    have = [c for c in THERMAL if c in d]
    h = d.set_index("t")[have].resample("1h").mean().dropna(how="all")
    h["year"] = h.index.year
    return h.reset_index()


def main() -> None:
    area = sys.argv[1] if len(sys.argv) > 1 else "DK1"
    d = load(area)
    have = [c for c in THERMAL if c in d]
    d[have] = d[have].fillna(0)
    d["thermal"] = d[have].sum(axis=1)

    print(f"=== {area} 熱電機組發電量的燃料組成(Energinet ElectricityBalanceNonv)===")
    print("  (已重採樣成逐時平均,避免 15 分鐘制度段被重複計權)\n")
    g = d.groupby("year")[have + ["thermal"]].sum()
    g["hours"] = d.groupby("year").size()  # 涵蓋時數:看得出哪一年不完整
    g = g[g["thermal"] > 0]
    print(
        f"  {'年':<6}"
        + "".join(f"{c:>16}" for c in have)
        + f"{'熱機 GWh':>11}{'涵蓋時數':>9}"
    )
    for y, row in g.iterrows():
        shares = "".join(f"{row[c] / row['thermal']:>15.1%}" for c in have)
        flag = "" if row["hours"] > 8000 else "  ← 不完整"
        print(
            f"  {y:<6}{shares}{row['thermal'] / 1e3:>11,.0f}{int(row['hours']):>9,}{flag}"
        )

    full = g[g["hours"] > 8000]
    last = full.index.max()
    r = full.loc[last]
    print(f"\n--- {last} 年組成(最近**涵蓋完整**的年度)---")
    for c in sorted(have, key=lambda x: -r[x]):
        print(
            f"  {c:<18}{r[c] / r['thermal']:>7.1%}   排放因子量級 {EF_HINT.get(c, float('nan')):.2f}"
        )

    # 出力加權的隱含排放因子:若把整個 DK1 熱機隊當一台機器,它的 ef 大概多少
    for y in (full.index.min(), last):
        rr = full.loc[y]
        implied = sum(rr[c] / rr["thermal"] * EF_HINT[c] for c in have)
        print(f"\n  {y} 年出力加權隱含排放因子 ≈ {implied:.3f} tCO2/MWh_fuel")
    print("  對照:chp.Plant 原本寫死 ef = 0.20 給所有燃料")

    print(
        "\n讀法:若生質+廢棄物佔比高,原型機組應設成**零碳燃料**,\n"
        "      並改用生質燃料價(非 TTF 天然氣價)。詳見 chp.Plant 的 ef_chp/ef_pb。"
    )


if __name__ == "__main__":
    main()
