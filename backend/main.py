from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.access_policy import AccessDenied, AccessPolicy
from backend.analysis import DataProblem, MAX_CSV_BYTES, analyze_prices, parse_prices
from backend.source_data import load_public_dataset


app = FastAPI(title="Market Relationship Atlas", docs_url=None, redoc_url=None)
access_policy = AccessPolicy(Path(__file__).resolve().parent.parent / "dist")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _csv_size_limit() -> tuple[int, str]:
    if os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV"):
        return 3_500_000, "3.5 MB"
    return MAX_CSV_BYTES, "50 MB"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    })
    return response


def _raise_problem(problem: DataProblem) -> None:
    raise HTTPException(status_code=422, detail={"code": problem.code, "message": str(problem)}) from None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    try:
        return FileResponse(access_policy.asset("index.html"))
    except AccessDenied:
        raise HTTPException(status_code=404, detail="Built frontend not found.") from None


@app.get("/assets/{name:path}", include_in_schema=False)
def asset(name: str) -> FileResponse:
    try:
        return FileResponse(access_policy.asset(f"assets/{name}"))
    except AccessDenied:
        raise HTTPException(status_code=404, detail="Asset not found.") from None


@app.get("/api/sample")
def sample(
    threshold: float = Query(default=0.4, ge=0, le=1),
    start: str | None = None,
    end: str | None = None,
    categories: list[str] = Query(default=[]),
) -> dict:
    try:
        prices, category_map, metadata = load_public_dataset()
        result = analyze_prices(
            prices,
            category_map,
            threshold,
            start,
            end,
            categories,
            f"Kaggle snapshot v{metadata['version']}",
        )
        result["dataset"] = metadata
        return result
    except DataProblem as problem:
        _raise_problem(problem)


@app.post("/api/analyze")
async def analyze(
    request: Request,
    threshold: float = Query(default=0.4, ge=0, le=1),
    start: str | None = None,
    end: str | None = None,
    categories: list[str] = Query(default=[]),
) -> dict:
    max_csv_bytes, max_csv_label = _csv_size_limit()
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_csv_bytes:
        raise HTTPException(status_code=413, detail={"code": "ERR_FILE_TOO_LARGE", "message": f"CSV files must be {max_csv_label} or smaller."})
    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_csv_bytes:
            raise HTTPException(status_code=413, detail={"code": "ERR_FILE_TOO_LARGE", "message": f"CSV files must be {max_csv_label} or smaller."})
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        prices, category_map = parse_prices(raw)
        return analyze_prices(prices, category_map, threshold, start, end, categories, "Uploaded CSV")
    except DataProblem as problem:
        _raise_problem(problem)

