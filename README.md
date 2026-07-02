./
├── config/
│   └── settings.py                      # Global parameters, weights, and mappings
├── data/                                # Local database and parameters
│   ├── economic_stress.db               # SQLite database
│   └── stress_model_params.json         # Reference global median/IQR parameters
├── src/                                 # Source code
│   ├── analytics/
│   │   └── stress_engine.py             # Robust Scoring Engine
│   ├── api/
│   │   ├── app.py                       # FastAPI Application
│   │   └── routers/                     # Route endpoints (countries, stress, trends)
│   ├── collectors/
│   │   └── base_collector.py            # API Scrapers (World Bank, IMF, FRED)
│   ├── dashboard/
│   │   ├── app.py                       # Streamlit UI
│   │   └── pages/                       # Multi-page views (World Map, Country analysis)
│   ├── database/
│   │   ├── connection.py                # SQL dialect connection pool
│   │   └── loader.py                    # Bulk ETL database writer
│   └── transformer/
│       └── data_transformer.py          # Vectorized Pandas transformer
└── tests/                               # Pytest test suite
