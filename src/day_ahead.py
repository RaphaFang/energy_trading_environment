import requests
from pathlib import Path
import pandas as pd
import duckdb

RAW_DIR = Path("data/raw")
CLEANED_DIR = Path("data/cleaned")

DB_PATH = "data/warehouse.duckdb"
ENERGINET_URL = "https://api.energidataservice.dk/dataset/DayAheadPrices"


def fetch_prices(start: str, end: str, price_area: str) -> pd.DataFrame:
    params = {
        "start": start,
        "end": end,
        "filter": f'{{"PriceArea":["{price_area}"]}}',
        "sort": "TimeUTC ASC",
        "limit": 0,
    }

    resp = requests.get(ENERGINET_URL, params=params, timeout=60)
    resp.raise_for_status()

    try:
        records = resp.json()["records"]
    except (ValueError, KeyError) as e:
        raise RuntimeError(
            f"Unexpected response from Energinet "
            f"(HTTP {resp.status_code}): {resp.text[:200]}"
        ) from e

    print(f"  Received {len(records)} price records (15-min)")
    raw = pd.DataFrame(records)

    ts_utc = pd.to_datetime(raw["TimeUTC"], utc=True)

    df = pd.DataFrame({
        "timestamp_utc": ts_utc,
        "timestamp_dk": ts_utc.dt.tz_convert("Europe/Copenhagen"),
        "zone_code": raw["PriceArea"],
        "price_eur_mwh": raw["DayAheadPriceEUR"].astype("float64"),
        "price_dkk_mwh": raw["DayAheadPriceDKK"].astype("float64"),
        "source": "Energinet",
        "my_ingested_timestamp": pd.Timestamp.now(tz="UTC"),
    })
    return df


def save_data_raw_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    print(f"✓ Saved {len(df)} rows → {path}")


def build_hourly_prices(raw_input: Path, output_path: Path) -> None:
    """15-min raw → hourly aggregation (4 quarters averaged into 1 hour)."""
    con = duckdb.connect(DB_PATH)
    hourly = con.execute(f"""
        SELECT
            DATE_TRUNC('hour', timestamp_utc) AS hour_utc,
            zone_code,
            COUNT(*) AS quarters_in_hour,
            AVG(price_eur_mwh) AS avg_price_eur,
            MAX(price_eur_mwh) AS max_price_eur,
            MIN(price_eur_mwh) AS min_price_eur,
            STDDEV(price_eur_mwh) AS volatility_eur,
            AVG(price_dkk_mwh) AS avg_price_dkk,
            COUNT(*) FILTER (WHERE price_eur_mwh < 0) AS negative_quarters
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

    raw_file = f"price_{price_area.lower()}_{start_day}_{end_day}.parquet"
    hourly_file = f"price_{price_area.lower()}_hourly_{start_day}_{end_day}.parquet"

    raw_path = RAW_DIR / raw_file
    hourly_path = CLEANED_DIR / hourly_file

    df = fetch_prices(start=start_date, end=end_date, price_area=price_area)
    save_data_raw_parquet(df, raw_path)
    build_hourly_prices(raw_path, hourly_path)


if __name__ == "__main__":
    main()