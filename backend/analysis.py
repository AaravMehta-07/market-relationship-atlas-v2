import csv
import io
import re
from collections import Counter
from datetime import date

import networkx as nx
import numpy as np
import pandas as pd


MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_ASSETS = 60
MIN_RETURN_OVERLAP = 30
MIN_PRICE_ROWS = MIN_RETURN_OVERLAP + 1
MAX_PRICE_ROWS = 20_000


class DataProblem(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().casefold())


def _find_column(columns: list[str], *names: str) -> str | None:
    aliases = {_normalise_header(name) for name in names}
    return next((column for column in columns if _normalise_header(column) in aliases), None)


def _category(value: object, name: str) -> str:
    text = str(value or "").strip().casefold()
    if any(token in text for token in ("crypto", "digital asset", "bitcoin")):
        return "Cryptocurrency"
    if any(token in text for token in ("commod", "metal", "energy")):
        return "Commodities"
    if any(token in text for token in ("currenc", "forex", "fx", "forex")):
        return "Currencies"
    if any(token in text for token in ("equity", "stock", "index", "indices")):
        return "Equities"
    label = name.casefold()
    if any(token in label for token in ("bitcoin", "ethereum", "solana", "crypto", "btc", "eth")):
        return "Cryptocurrency"
    if any(token in label for token in ("gold", "silver", "crude", "oil", "commodity")):
        return "Commodities"
    if any(token in label for token in ("eur/", "usd/", "gbp/", "jpy", "currency", "forex")):
        return "Currencies"
    if any(token in label for token in ("s&p", "nasdaq", "stoxx", "nikkei", "index", "msci", "ftse")):
        return "Equities"
    return "Other"


def parse_prices(raw: bytes) -> tuple[pd.DataFrame, dict[str, str]]:
    if not raw:
        raise DataProblem("ERR_EMPTY_FILE", "Choose a non-empty CSV file.")
    if len(raw) > MAX_CSV_BYTES:
        raise DataProblem("ERR_FILE_TOO_LARGE", "CSV files must be 50 MB or smaller.")

    try:
        text = raw.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error, StopIteration):
        raise DataProblem("ERR_CSV_ENCODING", "Use a valid UTF-8 CSV file.") from None

    headers = [value.strip() for value in header]
    if not headers or any(not value for value in headers):
        raise DataProblem("ERR_HEADERS", "Every CSV column needs a name.")
    normalised = [_normalise_header(value) for value in headers]
    if len(set(normalised)) != len(normalised):
        raise DataProblem("ERR_DUPLICATE_HEADERS", "CSV column names must be unique.")

    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, on_bad_lines="error")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError):
        raise DataProblem("ERR_CSV_FORMAT", "The CSV rows do not match the header.") from None

    frame.columns = headers
    date_column = _find_column(headers, "date", "datetime", "timestamp")
    if date_column is None:
        raise DataProblem("ERR_DATE_COLUMN", "Include a Date, datetime, or timestamp column.")

    symbol_column = _find_column(headers, "symbol", "ticker", "asset", "asset name", "instrument")
    close_column = _find_column(headers, "close", "adj close", "adjusted close", "closing price")
    categories: dict[str, str] = {}

    try:
        parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    except (ValueError, TypeError):
        raise DataProblem("ERR_DATES", "Dates must use a consistent, valid date format.") from None
    if parsed_dates.isna().any():
        raise DataProblem("ERR_DATES", "Dates must use a consistent, valid date format.")
    dates = parsed_dates.dt.tz_convert(None).dt.normalize()

    if symbol_column and close_column:
        if date_column == symbol_column or date_column == close_column:
            raise DataProblem("ERR_COLUMNS", "Date, asset identifier, and Close must be separate columns.")
        category_column = _find_column(headers, "asset type", "category", "asset class", "type")
        names = frame[symbol_column].astype(str).str.strip()
        if names.eq("").any() or names.str.len().gt(80).any():
            raise DataProblem("ERR_ASSET_NAMES", "Asset identifiers must be non-empty and at most 80 characters.")
        frame["__date"] = dates
        frame["__asset"] = names
        if frame.duplicated(["__date", "__asset"]).any():
            raise DataProblem("ERR_DUPLICATE_OBSERVATIONS", "Each asset can have only one closing price per date.")
        prices = pd.to_numeric(frame[close_column].replace("", np.nan), errors="coerce")
        invalid = frame[close_column].ne("") & prices.isna()
        if invalid.any():
            raise DataProblem("ERR_PRICE_VALUES", "Closing prices must be numeric or blank.")
        if (prices.dropna() <= 0).any():
            raise DataProblem("ERR_PRICE_VALUES", "Closing prices must be greater than zero.")
        frame["__close"] = prices
        price_table = frame.pivot(index="__date", columns="__asset", values="__close").sort_index()
        if category_column:
            category_values = frame[["__asset", category_column]].drop_duplicates("__asset").set_index("__asset")[category_column]
            categories = {name: _category(value, name) for name, value in category_values.items()}
    else:
        excluded = {date_column}
        metadata_columns = {_find_column(headers, "asset type", "region", "volume", "open", "high", "low")}
        excluded.update(value for value in metadata_columns if value)
        asset_columns = [column for column in headers if column not in excluded]
        if close_column and not symbol_column:
            raise DataProblem("ERR_LONG_FORMAT", "Long-form data needs both an asset identifier column and Close.")
        if not asset_columns:
            raise DataProblem("ERR_ASSET_COLUMNS", "Include one price column per asset.")
        frame["__date"] = dates
        if frame["__date"].duplicated().any():
            raise DataProblem("ERR_DUPLICATE_DATES", "Wide-format CSV data must have one row per date.")
        for column in asset_columns:
            values = pd.to_numeric(frame[column].replace("", np.nan), errors="coerce")
            if (frame[column].ne("") & values.isna()).any() or (values.dropna() <= 0).any():
                raise DataProblem("ERR_PRICE_VALUES", "Prices must be numeric, blank, and greater than zero when present.")
            frame[column] = values
            categories[column] = _category("", column)
        price_table = frame.set_index("__date")[asset_columns].sort_index()

    if price_table.empty:
        raise DataProblem("ERR_NO_DATA", "The CSV does not contain price observations.")
    if len(price_table.index) > MAX_PRICE_ROWS:
        raise DataProblem("ERR_TOO_MANY_ROWS", "The analysis supports up to 20,000 distinct dates.")
    if price_table.columns.duplicated().any() or len(price_table.columns) < 2:
        raise DataProblem("ERR_ASSET_COUNT", "Include prices for at least two distinct assets.")
    if len(price_table.columns) > MAX_ASSETS:
        raise DataProblem("ERR_ASSET_COUNT", "The analysis supports at most 60 assets.")
    for asset in price_table.columns:
        if int(price_table[asset].count()) < MIN_PRICE_ROWS:
            raise DataProblem("ERR_INSUFFICIENT_HISTORY", "Each asset needs at least 31 valid price observations.")

    price_table.columns = [str(value).strip() for value in price_table.columns]
    if any(not value or len(value) > 80 for value in price_table.columns):
        raise DataProblem("ERR_ASSET_NAMES", "Asset identifiers must be non-empty and at most 80 characters.")
    categories = {
        name: categories.get(name, _category("", name))
        for name in price_table.columns
    }
    price_table.index.name = "Date"
    return price_table.astype(float), categories


def analyze_prices(
    prices: pd.DataFrame,
    categories: dict[str, str],
    threshold: float = 0.4,
    start: str | None = None,
    end: str | None = None,
    selected_categories: list[str] | None = None,
    source: str = "Uploaded CSV",
) -> dict:
    if not np.isfinite(threshold) or threshold < 0 or threshold > 1:
        raise DataProblem("ERR_THRESHOLD", "Correlation threshold must be between 0 and 1.")

    try:
        start_date = pd.Timestamp(date.fromisoformat(start)) if start else None
        end_date = pd.Timestamp(date.fromisoformat(end)) if end else None
    except ValueError:
        raise DataProblem("ERR_DATE_RANGE", "Choose valid start and end dates.") from None
    if start_date is not None and end_date is not None and start_date > end_date:
        raise DataProblem("ERR_DATE_RANGE", "Start date must not be after end date.")

    sliced = prices
    if start_date is not None:
        sliced = sliced.loc[sliced.index >= start_date]
    if end_date is not None:
        sliced = sliced.loc[sliced.index <= end_date]
    if len(sliced) < MIN_PRICE_ROWS:
        raise DataProblem("ERR_PERIOD_TOO_SHORT", "The selected period needs at least 31 price dates.")

    returns = sliced.pct_change(fill_method=None)
    correlations = returns.corr(min_periods=MIN_RETURN_OVERLAP)
    pair_counts = returns.notna().astype(int).T.dot(returns.notna().astype(int))

    active_categories = set(selected_categories or [])
    asset_names = [name for name in prices.columns if not active_categories or categories.get(name, "Other") in active_categories]
    if len(asset_names) < 2:
        raise DataProblem("ERR_FILTER_ASSETS", "Select at least two assets to analyze.")

    ids = {name: f"asset-{index}" for index, name in enumerate(asset_names)}
    graph = nx.Graph()
    node_values: dict[str, dict] = {}
    for name in asset_names:
        graph.add_node(ids[name], name=name, category=categories.get(name, "Other"))

    all_pairs: list[tuple[str, str, float, int]] = []
    for index, first in enumerate(asset_names):
        for second in asset_names[index + 1 :]:
            value = correlations.loc[first, second]
            count = int(pair_counts.loc[first, second])
            if pd.notna(value) and np.isfinite(value) and count >= MIN_RETURN_OVERLAP:
                correlation = float(np.clip(value, -1, 1))
                all_pairs.append((first, second, correlation, count))
                if abs(correlation) >= threshold:
                    strength = max(abs(correlation), 1e-6)
                    graph.add_edge(ids[first], ids[second], correlation=correlation, strength=strength, distance=1 / strength)

    communities = []
    if graph.number_of_edges():
        try:
            communities = list(nx.community.greedy_modularity_communities(graph, weight="strength"))
        except ZeroDivisionError:
            communities = [{node} for node in graph.nodes]
    else:
        communities = [{node} for node in graph.nodes]
    community_by_id = {node: index + 1 for index, members in enumerate(communities) for node in members}

    degrees = dict(graph.degree())
    degree_centrality = nx.degree_centrality(graph) if graph.number_of_nodes() > 1 else {node: 0.0 for node in graph.nodes}
    clustering = nx.clustering(graph, weight="strength") if graph.number_of_nodes() else {}
    betweenness = nx.betweenness_centrality(graph, weight="distance", normalized=True) if graph.number_of_nodes() > 2 else {node: 0.0 for node in graph.nodes}

    by_asset: dict[str, list[tuple[str, float]]] = {name: [] for name in asset_names}
    for first, second, correlation, _count in all_pairs:
        by_asset[first].append((second, correlation))
        by_asset[second].append((first, correlation))

    for name in asset_names:
        node_id = ids[name]
        related = by_asset[name]
        positive = sorted((item for item in related if item[1] > 0), key=lambda item: item[1], reverse=True)[:3]
        negative = sorted((item for item in related if item[1] < 0), key=lambda item: item[1])[:3]
        node_values[name] = {
            "id": node_id,
            "name": name,
            "category": categories.get(name, "Other"),
            "degree": int(degrees[node_id]),
            "degree_centrality": float(degree_centrality[node_id]),
            "clustering": float(clustering.get(node_id, 0)),
            "betweenness": float(betweenness.get(node_id, 0)),
            "community": int(community_by_id[node_id]),
            "strongest_positive": [{"name": other, "correlation": value} for other, value in positive],
            "strongest_negative": [{"name": other, "correlation": value} for other, value in negative],
        }

    edges = []
    for first, second, correlation, count in all_pairs:
        if abs(correlation) >= threshold:
            edges.append({
                "id": f"{ids[first]}-{ids[second]}",
                "source": ids[first],
                "target": ids[second],
                "correlation": correlation,
                "observations": count,
            })
    edges.sort(key=lambda edge: (-abs(edge["correlation"]), edge["source"], edge["target"]))

    graph_components = [sorted((graph.nodes[node]["name"] for node in component), key=str.casefold) for component in nx.connected_components(graph)]
    graph_components.sort(key=lambda group: (-len(group), [name.casefold() for name in group]))
    degrees_by_count = Counter(degrees.values())
    degree_distribution = [
        {"degree": degree, "assets": count}
        for degree, count in sorted(degrees_by_count.items())
    ]

    matrix = []
    for first in asset_names:
        row = []
        for second in asset_names:
            value = correlations.loc[first, second]
            row.append(float(np.clip(value, -1, 1)) if pd.notna(value) and np.isfinite(value) else None)
        matrix.append(row)

    positive_count = sum(edge["correlation"] > 0 for edge in edges)
    negative_count = len(edges) - positive_count
    components_with_edges = [component for component in graph_components if len(component) > 1]
    average_clustering = float(nx.average_clustering(graph, weight="strength")) if graph.number_of_nodes() else 0.0

    return {
        "source": source,
        "category_options": [
            category for category in ("Equities", "Commodities", "Currencies", "Cryptocurrency", "Other")
            if category in {categories.get(name, "Other") for name in prices.columns}
        ],
        "period": {"start": sliced.index.min().strftime("%Y-%m-%d"), "end": sliced.index.max().strftime("%Y-%m-%d")},
        "price_dates": int(len(sliced)),
        "return_observations": int(len(returns)),
        "threshold": float(threshold),
        "assets": [node_values[name] for name in asset_names],
        "edges": edges,
        "matrix": matrix,
        "stats": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "density": float(nx.density(graph)) if graph.number_of_nodes() > 1 else 0.0,
            "components": len(graph_components),
            "connected_groups": components_with_edges,
            "average_clustering": average_clustering,
            "mean_degree": float(np.mean(list(degrees.values()))) if degrees else 0.0,
            "positive_edges": positive_count,
            "negative_edges": negative_count,
            "degree_distribution": degree_distribution,
            "communities": [
                {"id": index + 1, "assets": sorted((graph.nodes[node]["name"] for node in members), key=str.casefold)}
                for index, members in enumerate(communities)
            ],
        },
    }
