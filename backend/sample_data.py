import numpy as np
import pandas as pd


ASSET_SPECS = [
    ("S&P 500", "Equities", (1.00, 0.00, 0.00, 0.00), 0.0045),
    ("Nasdaq 100", "Equities", (1.08, 0.00, 0.10, 0.00), 0.0050),
    ("Euro Stoxx 50", "Equities", (0.86, 0.04, 0.00, 0.00), 0.0058),
    ("Nikkei 225", "Equities", (0.74, 0.02, 0.00, -0.05), 0.0060),
    ("Gold", "Commodities", (-0.20, 0.72, 0.00, -0.08), 0.0060),
    ("WTI Crude", "Commodities", (0.28, 1.02, 0.00, 0.04), 0.0090),
    ("Silver", "Commodities", (0.12, 0.70, 0.04, 0.00), 0.0070),
    ("EUR/USD", "Currencies", (-0.12, 0.00, 0.00, 0.95), 0.0025),
    ("USD/JPY", "Currencies", (0.12, 0.00, 0.00, -0.95), 0.0028),
    ("Bitcoin", "Cryptocurrency", (0.26, 0.00, 0.95, 0.00), 0.0100),
    ("Ethereum", "Cryptocurrency", (0.31, 0.00, 0.90, 0.00), 0.0110),
    ("Solana", "Cryptocurrency", (0.22, 0.02, 0.75, 0.00), 0.0140),
]


def make_sample_prices() -> pd.DataFrame:
    rng = np.random.default_rng(241021)
    periods = 260
    factor_scales = np.array([0.010, 0.009, 0.022, 0.0045])
    factors = rng.normal(0, factor_scales, size=(periods, len(factor_scales)))
    output: dict[str, object] = {
        "Date": pd.bdate_range("2024-01-02", periods=periods).strftime("%Y-%m-%d")
    }

    for name, _category, loadings, noise in ASSET_SPECS:
        daily_returns = factors @ np.asarray(loadings) + rng.normal(0.00015, noise, periods)
        daily_returns = np.clip(daily_returns, -0.18, 0.18)
        output[name] = (100 * np.cumprod(1 + daily_returns)).round(4)

    return pd.DataFrame(output)
