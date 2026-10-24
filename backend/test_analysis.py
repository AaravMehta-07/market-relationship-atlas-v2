import asyncio

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from backend.access_policy import AccessDenied, AccessPolicy
from backend.analysis import DataProblem, analyze_prices, parse_prices
from backend.main import app
from backend.sample_data import ASSET_SPECS, make_sample_prices


def api_request(method: str, path: str, **kwargs):
    async def send():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def sample_prices() -> tuple[pd.DataFrame, dict[str, str]]:
    frame = make_sample_prices()
    frame.index = pd.to_datetime(frame.pop("Date"))
    return frame, {name: category for name, category, _loadings, _noise in ASSET_SPECS}


def test_synthetic_sample_produces_signed_graph_and_matrix():
    prices, categories = sample_prices()
    result = analyze_prices(prices, categories, threshold=0.35, source="Synthetic sample")

    assert result["source"] == "Synthetic sample"
    assert result["category_options"] == ["Equities", "Commodities", "Currencies", "Cryptocurrency"]
    assert result["stats"]["nodes"] == 12
    assert result["stats"]["edges"] == len(result["edges"])
    assert len(result["matrix"]) == 12
    assert all(len(row) == 12 for row in result["matrix"])
    assert any(edge["correlation"] > 0 for edge in result["edges"])
    assert any(edge["correlation"] < 0 for edge in result["edges"])
    assert all(abs(edge["correlation"]) >= 0.35 for edge in result["edges"])


def test_wide_csv_and_date_window():
    rows = ["Date,Alpha,Beta"]
    for index in range(35):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)
        rows.append(f"{day:%Y-%m-%d},{100 + index},{90 + index * 0.5}")
    raw = "\n".join(rows).encode()
    prices, categories = parse_prices(raw)
    assert list(prices.columns) == ["Alpha", "Beta"]
    assert categories["Alpha"] == "Other"

    with pytest.raises(DataProblem) as caught:
        analyze_prices(prices, categories, start="2024-01-06")
    assert caught.value.code == "ERR_PERIOD_TOO_SHORT"


def test_long_csv_pivots_and_preserves_documented_categories():
    rows = ["Date,Symbol,Close,Asset type"]
    for index in range(35):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)
        rows.extend((
            f"{day:%Y-%m-%d},IDX,100,Stock Index",
            f"{day:%Y-%m-%d},BTC,200,Cryptocurrency",
        ))
    prices, categories = parse_prices("\n".join(rows).encode())
    assert prices.shape == (35, 2)
    assert categories == {"IDX": "Equities", "BTC": "Cryptocurrency"}


def test_duplicate_long_observation_is_rejected():
    raw = b"Date,Symbol,Close\n2024-01-01,A,100\n2024-01-01,A,101\n"
    with pytest.raises(DataProblem) as caught:
        parse_prices(raw)
    assert caught.value.code == "ERR_DUPLICATE_OBSERVATIONS"


def test_long_symbols_infer_category_when_metadata_is_absent():
    rows = ["Date,Symbol,Close"]
    for index in range(35):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)
        rows.extend((f"{day:%Y-%m-%d},BTC-USD,{100 + index}", f"{day:%Y-%m-%d},S&P 500,{200 + index}"))
    _prices, categories = parse_prices("\n".join(rows).encode())
    assert categories == {"BTC-USD": "Cryptocurrency", "S&P 500": "Equities"}


def test_csv_does_not_echo_invalid_price_contents():
    raw = b"Date,Alpha,Beta\n2024-01-01,secret,90\n"
    with pytest.raises(DataProblem) as caught:
        parse_prices(raw)
    assert caught.value.code == "ERR_PRICE_VALUES"
    assert "secret" not in str(caught.value)


def test_sample_api_uses_versioned_kaggle_snapshot():
    response = api_request("GET", "/api/sample?threshold=0.4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "Kaggle snapshot v204"
    assert payload["dataset"]["name"] == "Global Financial Markets Dataset (2000-Present)"
    assert payload["dataset"]["license"].startswith("CC0")
    assert payload["dataset"]["raw_rows"] == 191385
    assert payload["dataset"]["raw_assets"] == 34
    assert payload["dataset"]["analyzed_assets"] == 33
    assert payload["dataset"]["excluded_assets"] == ["CL=F"]
    assert payload["period"] == {"start": "2000-01-03", "end": "2026-10-21"}
    assert payload["stats"]["edges"] == 48
    assert payload["stats"]["positive_edges"] > 0
    assert payload["stats"]["negative_edges"] == 0


def test_api_accepts_csv_in_memory_and_returns_safe_validation_error():
    rows = ["Date,Alpha,Beta"]
    for index in range(35):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)
        rows.append(f"{day:%Y-%m-%d},{100 + index},{90 + index * 0.5}")
    accepted = api_request("POST", "/api/analyze", content="\n".join(rows), headers={"Content-Type": "text/csv"})
    rejected = api_request("POST", "/api/analyze", content="Date,Alpha,Beta\n2024-01-01,secret,90\n", headers={"Content-Type": "text/csv"})

    assert accepted.status_code == 200
    assert accepted.json()["source"] == "Uploaded CSV"
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "ERR_PRICE_VALUES"
    assert "secret" not in rejected.text


def test_hosted_api_enforces_payload_safe_csv_limit(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.delenv("VERCEL", raising=False)
    response = api_request(
        "POST",
        "/api/analyze",
        content=b"x" * 3_500_001,
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "ERR_FILE_TOO_LARGE"
    assert response.json()["detail"]["message"] == "CSV files must be 3.5 MB or smaller."


def test_access_policy_only_allows_built_frontend_assets(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<main>synthetic test</main>", encoding="utf-8")
    (tmp_path / "secret.csv").write_text("synthetic only", encoding="utf-8")
    policy = AccessPolicy(root)

    assert policy.asset("index.html").read_text(encoding="utf-8") == "<main>synthetic test</main>"
    for relative in ("../secret.csv", "missing.js", "index.html/child.js"):
        with pytest.raises(AccessDenied):
            policy.asset(relative)


def test_static_routes_read_only_files_permitted_by_access_policy(monkeypatch, tmp_path):
    from backend import main

    root = tmp_path / "dist"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text("<title>synthetic test</title>", encoding="utf-8")
    (assets / "app.css").write_text("body { color: green; }", encoding="utf-8")
    monkeypatch.setattr(main, "access_policy", AccessPolicy(root))

    page = api_request("GET", "/")
    asset = api_request("GET", "/assets/app.css")
    denied = api_request("GET", "/assets/missing.js")

    assert page.status_code == 200 and "synthetic test" in page.text
    assert asset.status_code == 200 and "color: green" in asset.text
    assert denied.status_code == 404
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cache-control"] == "no-store"

