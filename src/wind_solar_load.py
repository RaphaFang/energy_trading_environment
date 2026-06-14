import requests
from pathlib import Path
import pandas as pd
import duckdb

RAW_DIR = Path("data/raw")
CLEANED_DIR = Path("data/cleaned")

DB_PATH = "data/warehouse.duckdb"
PRODUCTION_URL = "https://api.energidataservice.dk/dataset/ProductionConsumptionSettlement"


def save_data_raw_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    print(f"✓ Saved {len(df)} rows → {path}")


def fetch_energinet_features(start: str, end: str, price_area: str) -> pd.DataFrame:
    params = {
        "start": start,
        "end": end,
        "filter": f'{{"PriceArea":["{price_area}"]}}',
        "sort": "HourUTC ASC",
        "limit": 0,
    }
    resp = requests.get(PRODUCTION_URL, params=params, timeout=60)
    resp.raise_for_status()
    records = resp.json()["records"]
    print(f"  Received {len(records)} feature records (hourly)")

    raw = pd.DataFrame(records)
    ts_utc = pd.to_datetime(raw["HourUTC"], utc=True)

    df = pd.DataFrame({
        "timestamp_utc": ts_utc,
        "zone_code": raw["PriceArea"],
        "wind_mwh": (
            raw["OffshoreWindGe100MW_MWh"].astype("float64").fillna(0) +
            raw["OffshoreWindLt100MW_MWh"].astype("float64").fillna(0) +
            raw["OnshoreWindGe50kW_MWh"].astype("float64").fillna(0) +
            raw["OnshoreWindLt50kW_MWh"].astype("float64").fillna(0)
        ),
        "solar_mwh": (
            raw["SolarPowerLt10kW_MWh"].astype("float64").fillna(0) +
            raw["SolarPowerGe10Lt40kW_MWh"].astype("float64").fillna(0) +
            raw["SolarPowerGe40kW_MWh"].astype("float64").fillna(0) +
            raw["SolarPowerSelfConMWh"].astype("float64").fillna(0)
        ),
        "load_mwh": raw["GrossConsumptionMWh"].astype("float64").fillna(0),
        "source": "Energinet",
    })
    return df


def build_hourly_features(raw_input: Path, output_path: Path) -> None:
    """Raw is already hourly; aggregate to enforce one row per hour."""
    con = duckdb.connect(DB_PATH)
    hourly = con.execute(f"""
        SELECT
            DATE_TRUNC('hour', timestamp_utc) AS hour_utc,
            zone_code,
            COUNT(*) AS rows_in_hour,
            SUM(wind_mwh) AS wind_mwh,
            SUM(solar_mwh) AS solar_mwh,
            SUM(load_mwh) AS load_mwh
        FROM read_parquet('{raw_input}')
        GROUP BY hour_utc, zone_code
        ORDER BY hour_utc
    """).df()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_parquet(output_path, index=False, engine="pyarrow", compression="snappy")
    print(f"✓ Saved {len(hourly)} hourly rows → {output_path}")
    con.close()


def main():
    start_date = "2026-03-16T00:00"
    end_date = "2026-06-16T00:00"
    price_area = "DK2"

    start_day = start_date[:10]
    end_day = end_date[:10]

    raw_file = f"feature_{price_area.lower()}_{start_day}_{end_day}.parquet"
    hourly_file = f"feature_{price_area.lower()}_hourly_{start_day}_{end_day}.parquet"

    raw_path = RAW_DIR / raw_file
    hourly_path = CLEANED_DIR / hourly_file

    df = fetch_energinet_features(start=start_date, end=end_date, price_area=price_area)
    save_data_raw_parquet(df, raw_path)
    build_hourly_features(raw_path, hourly_path)


if __name__ == "__main__":
    main()