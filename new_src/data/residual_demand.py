import requests
import pandas as pd

URL = "https://api.energidataservice.dk/dataset/ProductionConsumptionSettlement"


def fetch(start="2021-01-01", end="2026-07-01", area="DK1") -> pd.DataFrame:
    """Load + wind + solar + residual demand (= load - wind - solar), hourly."""
    r = requests.get(
        URL,
        params={
            "start": start,
            "end": end,
            "filter": f'{{"PriceArea":["{area}"]}}',
            "sort": "HourUTC ASC",
            "limit": 0,
        },
        timeout=120,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["records"])

    num = lambda cols: cols.apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    out = pd.DataFrame(
        {
            "hour_utc": pd.to_datetime(df["HourUTC"], utc=True),
            "area": area,
            "load_mwh": pd.to_numeric(df["GrossConsumptionMWh"], errors="coerce"),
            "wind_mwh": num(df.filter(like="Wind")),
            "solar_mwh": num(df.filter(like="Solar")),
        }
    )
    # ponytail: residual = load - wind - solar; ignores must-run CHP/hydro, good enough for a first stack
    out["residual_mwh"] = out["load_mwh"] - out["wind_mwh"] - out["solar_mwh"]
    return out.sort_values("hour_utc").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from window import END, START, paths_for, retire_superseded
    # 🔴 2026-08-21 修:原本寫成 Path("new_data"),但既有資料在 new_data/residual/
    #    → 腳本重跑會把檔丟到根目錄,而下游 glob 找的是子目錄。
    out_dir = Path("new_data/residual")
    out_dir.mkdir(parents=True, exist_ok=True)

    for area in ("DK1", "DK2"):
        d = fetch(START, END, area)
        assert (
            d["residual_mwh"] == d["load_mwh"] - d["wind_mwh"] - d["solar_mwh"]
        ).all()
        path, _old = paths_for(out_dir, f"residual_{area.lower()}")
        d.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
        retire_superseded(path, _old, "hour_utc")
        print(
            f"✓ {area}: {len(d)} rows  {d['hour_utc'].min()} → {d['hour_utc'].max()}  → {path}"
        )
