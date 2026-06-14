# A minimal pipeline for monday demo

1. Download/Clone the repository.

2. Start the container via Docker.

3. Navigate to http://127.0.0.1:8888/lab to view the Jupyter Notebook.

After getting the API-Key, it will be able to add 'Generation Forecasts for Wind and Solar' from ENTSO-E Transparency Platform.

Which will help this environment feature with more comprehensive forecast data, improving the model building.

Layout of directory with data as below:
```
.
├── Dockerfile
├── README.md
├── data
│   ├── cleaned
│   │   ├── feature_dk1_hourly_2026-03-16_2026-06-16.parquet
│   │   ├── feature_dk2_hourly_2026-03-16_2026-06-16.parquet
│   │   ├── price_dk1_hourly_2026-03-16_2026-06-16.parquet
│   │   ├── price_dk2_hourly_2026-03-16_2026-06-16.parquet
│   │   └── weather_dk1_2026-03-16_2026-06-16.parquet
│   ├── holi
│   │   └── holiday.parquet
│   ├── raw
│   │   ├── feature_dk1_2026-03-16_2026-06-16.parquet
│   │   ├── feature_dk2_2026-03-16_2026-06-16.parquet
│   │   ├── price_dk1_2026-03-16_2026-06-16.parquet
│   │   └── price_dk2_2026-03-16_2026-06-16.parquet
│   └── warehouse.duckdb
├── dk1_forecast.ipynb
├── dk1_forecast.py
├── docker-compose.yml
├── requirements.txt
└── src
    ├── day_ahead.py
    ├── dk_holidays.py
    ├── weather_forcecast_meteo.py
    └── wind_solar_load.py
```
