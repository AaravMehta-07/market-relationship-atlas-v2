# Market Relationship Atlas V2.0

A React and FastAPI dashboard for exploring historical relationships across stock indices, commodities, currencies, and cryptocurrencies. It turns simple daily returns into a signed Pearson-correlation network and calculates thresholded connectivity and network statistics.

## Built-in dataset

The default view now uses a locally bundled snapshot of the Kaggle **Global Financial Markets Dataset (2000-Present)** by BELBIN BENO R M. The publisher labels it **CC0: Public Domain**. Dataset page: <https://www.kaggle.com/datasets/belbino/global-financial-markets-dataset-2010-present>.

- Snapshot version: 204, downloaded October 23, 2026; Kaggle file timestamp: October 22, 2026.
- File: `public_data/global_financial_markets_2000_Now.csv`.
- Snapshot contains 191,385 rows, 34 asset series, and daily OHLCV fields; observations run from January 3, 2000 through October 21, 2026.
- The analysis uses the source `close` field and labels assets by the source `asset_type`; no live market API is called.
- One series, WTI crude futures (`CL=F`), is excluded from the built-in return analysis because its source close is negative on April 20, 2020. A conventional percentage return is not meaningful across a sign change. The original source file is preserved unchanged.
- The resulting default network analyzes 33 series. It is a historical snapshot, not live data, investment advice, a forecast, or evidence of causation.

The synthetic generator in `backend/sample_data.py` remains only as a deterministic test fixture; it is not used by the production sample route. Uploaded CSV content is processed in memory and is not written by this application.

## Run locally

For development, use two PowerShell terminals from `D:\Code\Barca\DM\V2`.

Terminal 1, create the environment once and run the API:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

Terminal 2, install frontend dependencies once and run Vite:

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`. Both services bind to loopback.

For a single-origin local run, build the frontend and start the API:

```powershell
npm run build
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/`. Static reads are restricted by `AccessPolicy` to built UI assets under `dist/`; uploaded data is sent as request bytes and is never written by the backend. This policy is defense in depth, not an OS sandbox. For tests, install `requirements-dev.txt`, then run `python -m pytest backend -q`.

## Vercel deployment

Deploy from this `V2` directory. Vercel builds the Vite frontend into `dist/` and runs the FastAPI app from `index.py`. The versioned Kaggle snapshot is included in the function bundle and read through `AccessPolicy`. Hosted CSV uploads are sent to Vercel and processed in memory, with a 3.5 MB limit. The application does not write uploaded files, but this is not a guarantee about platform-level handling; only upload public, non-sensitive data.

## CSV format

Wide format has one date column and one closing-price column per asset:

```csv
Date,S&P 500,Gold,Bitcoin
2024-01-02,100,100,100
2024-01-03,101,99.8,102
```

Long format accepts `Date`, an asset identifier (`Symbol`, `Ticker`, `Asset`, `Asset name`, or `Instrument`), `Close`, and an optional category column (`Asset type`, `Category`, `Asset class`, or `Type`). Optional asset categories are mapped to Equities, Commodities, Currencies, Cryptocurrency, or Other.

The local parser accepts UTF-8 CSV files up to 50 MB; hosted Vercel uploads are limited to 3.5 MB to stay below the platform request-body cap. The parser supports up to 60 assets and 20,000 distinct dates. Each asset needs at least 31 valid, positive prices. Blank prices are kept missing; they are not imputed. A pair is included only when its return series overlap for at least 30 observations. Duplicate observations, invalid dates, non-numeric prices, zero prices, and inconsistent rows are rejected with fixed validation messages.

## Analysis

Simple percentage returns are computed from the selected price window. The graph includes an edge when the absolute Pearson correlation meets the selected threshold. Positive edges are green and negative edges are red and dashed. Degree, density, connected components, average weighted clustering, degree centrality and betweenness are computed on that thresholded undirected graph. Community detection uses absolute correlation strength; negative correlations are not treated as negative path lengths. The full matrix and strongest signed neighbors are shown alongside the filtered graph.

These are descriptive historical associations, not evidence of causation, forecasts, portfolio advice, or trading signals. A dataset's actual asset coverage depends on the imported file. The built-in snapshot documents stock indices, cryptocurrencies, commodities, and currency pairs; it does not include bonds or real estate.
