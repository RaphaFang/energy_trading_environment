import glob
from pathlib import Path

import duckdb
import pandas as pd

DB = "new_data/energy.duckdb"


def _one(prefix: str, sub: str = "") -> pd.DataFrame:
    """Read the single parquet whose name starts with prefix (date suffix varies)."""
    (f,) = glob.glob(f"new_data/entsoe/{sub}{prefix}_*.parquet")
    return pd.read_parquet(f)


def _col(df: pd.DataFrame, suffix: str) -> pd.Series:
    """Pick the one column whose name ends with suffix (strips zone prefix like 'se_3_')."""
    (c,) = [c for c in df.columns if c.endswith(suffix)]
    return df[c]


def build_entsoe() -> pd.DataFrame | None:
    """Assemble ENTSO-E Tier-2 features into one (timestamp_utc, area) frame.

    Area-aware: own load-fc + own SE neighbour + own borders go to that zone;
    German wind+solar is a shared external driver broadcast to BOTH zones.
    Every column is day-ahead / NTC-day-ahead → leak-free (known at D-1).
    """
    if not glob.glob("new_data/entsoe/*.parquet"):
        return None
    parts = []
    for area, z in (("DK1", "dk_1"), ("DK2", "dk_2")):
        se = "se_3" if area == "DK1" else "se_4"
        d = pd.DataFrame(index=_one(f"loadfc_{z}").index)
        d["loadfc_mwh"] = _col(_one(f"loadfc_{z}"), "Forecasted Load")
        d["nbr_wind_on_mwh"] = _col(_one(f"resfc_{se}"), "Wind Onshore")
        d["nbr_solar_mwh"] = _col(_one(f"resfc_{se}"), "Solar")
        # neighbour residual = load - wind - solar (net export pressure); own SE zone
        d["nbr_residual_mwh"] = _col(
            _one(f"residual_{se}", "derived/"), "_residual_mwh"
        )
        d["ntc_imp_de"] = _col(
            _one(f"ntc_de_lu_{z}"), "_0"
        )  # DE -> DK (rival supply in)
        d["ntc_exp_de"] = _col(_one(f"ntc_{z}_de_lu"), "_0")  # DK -> DE
        # offered capacity on Nordic/internal borders (hourly; both directions)
        d["oc_imp_se"] = _col(_one(f"oc_{se}_{z}"), "_0")
        d["oc_exp_se"] = _col(_one(f"oc_{z}_{se}"), "_0")
        other = "dk_2" if area == "DK1" else "dk_1"
        d["oc_imp_dk"] = _col(_one(f"oc_{other}_{z}"), "_0")  # from the other DK zone
        d["oc_exp_dk"] = _col(_one(f"oc_{z}_{other}"), "_0")
        if area == "DK1":  # NL cable + NO cable only land in DK1
            d["ntc_imp_nl"] = _col(_one("ntc_nl_dk_1"), "_0")
            d["ntc_exp_nl"] = _col(_one("ntc_dk_1_nl"), "_0")
            d["oc_imp_no"] = _col(_one("oc_no_2_dk_1"), "_0")
            d["oc_exp_no"] = _col(_one("oc_dk_1_no_2"), "_0")
        d["area"] = area
        parts.append(d)
    ent = pd.concat(parts)

    # German shared drivers (broadcast to both zones, join on time):
    de = _one("resfc_de_lu").resample("1h").mean()  # 15-min -> hourly
    de.columns = ["de_solar_mwh", "de_wind_off_mwh", "de_wind_on_mwh"]  # Solar, Off, On
    de["de_residual_mwh"] = _col(_one("residual_de_lu", "derived/"), "_residual_mwh")
    ent = ent.join(de, how="left")

    ent.index.name = "timestamp_utc"
    return ent.reset_index()


def build_fuel() -> pd.DataFrame | None:
    """Tier-3 daily fuel prices -> leak-safe hourly. gas (full) + carbon (2021-10+).

    Leak-safe: the day-ahead auction for delivery day D clears ~noon D-1, before that
    day's fuel settles. So each hour uses the last close on or before D-2 (merge_asof
    backward on a 2-day-lagged cutoff → also fills weekends/holidays). Shared by zones.
    """
    fuel = Path("new_data/fuel")

    def _series(name: str) -> pd.Series | None:
        fs = glob.glob(str(fuel / f"{name}_*.parquet"))
        return pd.read_parquet(fs[0]).iloc[:, 0] if fs else None

    gas = _series("ttf_gas_eur_mwh")
    if gas is None:
        return None
    co2 = _series("eua_co2_eur_t")
    man = _series("eua_co2_eur_t_manual")  # optional early-years backfill
    if man is not None and co2 is not None:
        co2 = pd.concat([man[man.index < co2.index.min()], co2]).sort_index()

    daily = pd.DataFrame({"ttf_gas_eur_mwh": gas})
    if co2 is not None:
        daily["eua_co2_eur_t"] = co2
    daily = daily.sort_index()
    daily.index = pd.to_datetime(daily.index)  # tz-naive dates
    daily = daily.reset_index(names="date")

    hours = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2019-01-01", "2025-10-01", freq="1h", tz="UTC"
            )
        }
    )
    hours["cutoff"] = (
        hours["timestamp_utc"].dt.tz_localize(None).dt.normalize()
        - pd.Timedelta(days=2)
    ).astype("datetime64[us]")
    daily["date"] = daily["date"].astype("datetime64[us]")
    out = pd.merge_asof(
        hours.sort_values("cutoff"),
        daily.sort_values("date"),
        left_on="cutoff",
        right_on="date",
        direction="backward",
    )
    return out.set_index("timestamp_utc")[list(daily.columns[1:])].reset_index()


def main():
    Path("new_data").mkdir(exist_ok=True)
    con = duckdb.connect(DB)
    g = "new_data"  # glob root; DK1+DK2 files union automatically

    con.execute(f"""
        CREATE OR REPLACE TABLE price AS
        SELECT HourUTC AS timestamp_utc, PriceArea AS area,
               SpotPriceEUR, SpotPriceDKK
        FROM read_parquet('{g}/price/price_*.parquet');

        CREATE OR REPLACE TABLE weather AS
        SELECT hour_utc AS timestamp_utc, area,
               wind_speed_100m, wind_gusts_10m, wind_direction_100m,
               shortwave_radiation, direct_radiation, diffuse_radiation,
               cloud_cover, temperature_2m
        FROM read_parquet('{g}/weather/weather_*.parquet');

        CREATE OR REPLACE TABLE residual AS
        SELECT hour_utc AS timestamp_utc, area,
               load_mwh, wind_mwh, solar_mwh, residual_mwh
        FROM read_parquet('{g}/residual/residual_*.parquet');

        CREATE OR REPLACE TABLE calendar AS
        SELECT * FROM read_parquet('{g}/calendar/calendar_*.parquet');

        -- forecast: long -> wide, keep only leak-free ForecastDayAhead
        CREATE OR REPLACE TABLE forecast AS
        SELECT HourUTC AS timestamp_utc, PriceArea AS area,
          MAX(CASE WHEN ForecastType='Offshore Wind' THEN ForecastDayAhead END) AS offshore_wind_da_mwh,
          MAX(CASE WHEN ForecastType='Onshore Wind'  THEN ForecastDayAhead END) AS onshore_wind_da_mwh,
          MAX(CASE WHEN ForecastType='Solar'         THEN ForecastDayAhead END) AS solar_da_mwh
        FROM read_parquet('{g}/forecast/forecast_*.parquet')
        GROUP BY 1, 2;
    """)

    # --- ENTSO-E Tier-2 (optional: only if pulled). Built in pandas, then registered. ---
    ent_df = build_entsoe()
    tables = ["price", "weather", "residual", "calendar", "forecast"]
    if ent_df is not None:
        con.register("ent_df", ent_df)
        con.execute("CREATE OR REPLACE TABLE entsoe AS SELECT * FROM ent_df")
        tables.append("entsoe")

    # --- Tier-3 fuel (keyed by timestamp only, shared across zones) ---
    fuel_df = build_fuel()
    if fuel_df is not None:
        con.register("fuel_df", fuel_df)
        con.execute("CREATE OR REPLACE TABLE fuel AS SELECT * FROM fuel_df")

    # --- one row per (timestamp_utc, area) in every table, or LEFT JOIN fans out ---
    for t in tables:
        dup = con.execute(
            f"SELECT count(*) FROM (SELECT timestamp_utc, area FROM {t} "
            f"GROUP BY 1,2 HAVING count(*)>1)"
        ).fetchone()[0]
        assert dup == 0, f"{t} has {dup} duplicate (timestamp_utc, area) keys"

    # --- wide training VIEW: calendar spine + LEFT JOINs; lags on the continuous
    #     spine so N rows == N hours (leak-safe: only >=24h old values) ---
    ent_cols = "e.* EXCLUDE (timestamp_utc, area)," if ent_df is not None else ""
    ent_join = (
        "LEFT JOIN entsoe e USING (timestamp_utc, area)" if ent_df is not None else ""
    )
    fuel_cols = "fu.* EXCLUDE (timestamp_utc)," if fuel_df is not None else ""
    fuel_join = "LEFT JOIN fuel fu USING (timestamp_utc)" if fuel_df is not None else ""
    con.execute(f"""
        CREATE OR REPLACE VIEW training AS
        SELECT
            c.*,
            w.wind_speed_100m, w.wind_gusts_10m, w.wind_direction_100m,
            w.shortwave_radiation, w.direct_radiation, w.diffuse_radiation,
            w.cloud_cover, w.temperature_2m,
            f.offshore_wind_da_mwh, f.onshore_wind_da_mwh, f.solar_da_mwh,
            {ent_cols}
            {fuel_cols}
            r.load_mwh, r.wind_mwh, r.solar_mwh, r.residual_mwh,
            LAG(r.load_mwh, 24)     OVER win AS load_lag24_mwh,
            LAG(r.residual_mwh, 24) OVER win AS residual_lag24_mwh,
            LAG(p.SpotPriceEUR, 24)  OVER win AS price_lag24_eur,
            LAG(p.SpotPriceEUR, 168) OVER win AS price_lag168_eur,
            p.SpotPriceEUR AS y_price_eur   -- TARGET
        FROM calendar c
        LEFT JOIN weather  w USING (timestamp_utc, area)
        LEFT JOIN forecast f USING (timestamp_utc, area)
        LEFT JOIN residual r USING (timestamp_utc, area)
        LEFT JOIN price    p USING (timestamp_utc, area)
        {ent_join}
        {fuel_join}
        WINDOW win AS (PARTITION BY c.area ORDER BY c.timestamp_utc);
    """)

    spine = con.execute("SELECT count(*) FROM calendar").fetchone()[0]
    view = con.execute("SELECT count(*) FROM training").fetchone()[0]
    assert view == spine, f"view rows {view} != spine {spine} (join fan-out!)"

    print(f"DB: {DB}")
    for t in tables + (["fuel"] if fuel_df is not None else []):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  table {t:10} {n:>7} rows")
    print(f"  view  training  {view:>7} rows")
    # trainable window = where target AND leak-free output-forecast both exist
    tr = con.execute("""
        SELECT min(timestamp_utc), max(timestamp_utc), count(*)
        FROM training
        WHERE y_price_eur IS NOT NULL AND solar_da_mwh IS NOT NULL
    """).fetchone()
    print(f"  trainable rows (y & forecast present): {tr[2]}  {tr[0]} -> {tr[1]}")
    con.close()


if __name__ == "__main__":
    main()
