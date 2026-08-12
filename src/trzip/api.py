from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .hourly_store import coverage, snapshot
from .curation import reconstructed_demo_feed
from .intelligence import KEYWORD_REGISTRY, build_intelligence, canonical_topic
from .company_adapters import company_profile, integration_status, opendart_company, pykrx_stock
from .related_keywords import x_related_keywords

app = FastAPI(title="TRZIP X + Google", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
web = Path(__file__).resolve().parents[2] / "web"
app.mount("/assets", StaticFiles(directory=web), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(web / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/hourly/coverage")
def hourly_coverage() -> dict:
    return coverage()


@app.get("/api/v1/hourly/snapshot")
def hourly_snapshot(at: datetime = Query(default_factory=lambda: datetime.now(UTC))) -> dict:
    return {"observed_at": at.isoformat(), "rows": snapshot(at)}


@app.get("/api/v1/hourly/audit")
def hourly_audit(at: datetime = Query(default_factory=lambda: datetime.now(UTC))) -> dict:
    from .hourly_store import connect, floor_hour
    stamp = floor_hour(at).isoformat()
    with connect() as connection:
        rows = connection.execute("SELECT * FROM collection_audit WHERE observed_at=? ORDER BY collector", (stamp,)).fetchall()
    return {"observed_at": stamp, "collectors": [dict(row) for row in rows]}


@app.get("/api/v1/korea/curated-feed")
def korea_curated_feed() -> dict:
    return build_intelligence(datetime.now(UTC), hours=24)


@app.get("/api/v1/demo/curated-feed")
def demo_curated_feed(at: datetime = Query(default=datetime(2026, 7, 31, 14, tzinfo=UTC))) -> dict:
    return reconstructed_demo_feed(at)


@app.get("/api/v1/intelligence")
def intelligence(at: datetime = Query(default=datetime(2026, 8, 12, 2, tzinfo=UTC)),
                 hours: int = Query(default=24, ge=1, le=2484)) -> dict:
    return build_intelligence(at, hours=hours)


@app.get("/api/v1/integrations")
def integrations() -> dict:
    return integration_status()


@app.get("/api/v1/companies/opendart-check")
def opendart_check(company: str = Query(min_length=1, max_length=80)) -> dict:
    return opendart_company(company)


@app.get("/api/v1/companies/pykrx-stock")
def pykrx_reference(stock_code: str = Query(pattern=r"^\d{6}$"), base_date: str | None = Query(default=None, pattern=r"^\d{8}$")) -> dict:
    return pykrx_stock(stock_code, base_date)


@app.get("/api/v1/companies/profile")
def verified_company_profile(company: str = Query(min_length=1, max_length=80),
                             stock_code: str = Query(pattern=r"^\d{6}$")) -> dict:
    return company_profile(company, stock_code)


@app.get("/api/v1/keywords/x-related")
def x_related(query: str = Query(min_length=1, max_length=100),
              topic: str | None = Query(default=None, max_length=100)) -> dict:
    canonical = canonical_topic(topic or query)
    return x_related_keywords(query, candidates=KEYWORD_REGISTRY.get(canonical, []))
