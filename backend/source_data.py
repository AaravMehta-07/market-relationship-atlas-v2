from functools import lru_cache
from io import BytesIO
from pathlib import Path

import pandas as pd

from backend.access_policy import AccessDenied, AccessPolicy
from backend.analysis import DataProblem, parse_prices


DATASET_FILENAME = "global_financial_markets_2000_Now.csv"
DATASET_NAME = "Global Financial Markets Dataset (2000-Present)"
DATASET_URL = "https://www.kaggle.com/datasets/belbino/global-financial-markets-dataset-2010-present"
DATASET_INFO = {
    "name": DATASET_NAME,
    "publisher": "BELBIN BENO R M",
    "source_url": DATASET_URL,
    "license": "CC0: Public Domain (as labeled by the Kaggle publisher)",
    "version": 204,
    "snapshot_date": "2026-10-22",
    "file": DATASET_FILENAME,
    "raw_rows": 191385,
    "raw_assets": 34,
    "raw_categories": {
        "Stock Index": 10,
        "Commodity": 8,
        "Currency": 8,
        "Cryptocurrency": 8,
    },
    "source_price_field": "close",
    "live_data": False,
}

_DATA_POLICY = AccessPolicy(
    Path(__file__).resolve().parent.parent / "public_data",
    allowed_suffixes={".csv"},
)


@lru_cache(maxsize=1)
def load_public_dataset() -> tuple[pd.DataFrame, dict[str, str], dict]:
    try:
        raw = _DATA_POLICY.asset(DATASET_FILENAME).read_bytes()
    except AccessDenied:
        raise DataProblem("ERR_SOURCE_DATA", "The built-in public dataset is unavailable.") from None

    try:
        frame = pd.read_csv(
            BytesIO(raw),
            usecols=["date", "symbol", "close", "asset_type"],
            dtype={"date": str, "symbol": str, "asset_type": str},
        )
    except (UnicodeDecodeError, ValueError, pd.errors.ParserError):
        raise DataProblem("ERR_SOURCE_DATA", "The built-in public dataset could not be read.") from None

    invalid_assets = sorted(
        frame.loc[pd.to_numeric(frame["close"], errors="coerce").le(0), "symbol"].dropna().unique()
    )
    # A series crossing zero does not support conventional percentage returns.
    frame = frame.loc[~frame["symbol"].isin(invalid_assets)]
    normalized = frame.rename(
        columns={"date": "Date", "symbol": "Symbol", "close": "Close", "asset_type": "Asset type"}
    )

    try:
        prices, categories = parse_prices(normalized.to_csv(index=False).encode("utf-8"))
    except DataProblem:
        raise DataProblem("ERR_SOURCE_DATA", "The built-in public dataset failed validation.") from None

    metadata = {
        **DATASET_INFO,
        "analyzed_assets": len(prices.columns),
        "excluded_assets": invalid_assets,
        "period": {
            "start": prices.index.min().strftime("%Y-%m-%d"),
            "end": prices.index.max().strftime("%Y-%m-%d"),
        },
    }
    return prices, categories, metadata
