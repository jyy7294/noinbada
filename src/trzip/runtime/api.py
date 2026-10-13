from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import re
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse

from .core import ROOT, home, parse_time, decode
from .media import text_card
from .pipeline import FRESH_MINUTES, status

app = FastAPI(title="TR ZIP",docs_url=None,redoc_url=None,openapi_url=None)


@contextmanager
def reader():
    path = home()/"runtime.sqlite3"
    if not path.exists():
        raise HTTPException(503,"아직 수집된 데이터가 없습니다.")
    db = sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def edition(publication: str | None = None):
    if publication and not re.fullmatch(r"[a-f0-9]{24}",publication):
        raise HTTPException(400,"잘못된 게시 식별자입니다.")
    with reader() as db:
        if publication is None:
            current = db.execute("SELECT value FROM settings WHERE key='current_publication'").fetchone()
            if not current:
                raise HTTPException(503,"첫 수집을 기다리고 있습니다.")
            publication = current[0]
        row = db.execute("SELECT payload FROM publications WHERE id=?",(publication,)).fetchone()
        if not row:
            raise HTTPException(404,"게시본이 만료되었습니다. 목록을 새로 고쳐 주세요.")
    payload = decode(row[0])
    now = datetime.now(UTC)
    for source in payload["sources"]:
        source["fresh"] = 0 <= (now-parse_time(source["observed_at"])).total_seconds()/60 <= FRESH_MINUTES[source["source"]]
    for item in payload["items"]:
        for source in item["sources"]:
            source["fresh"] = 0 <= (now-parse_time(source["observed_at"])).total_seconds()/60 <= FRESH_MINUTES[source["source"]]
        item["fresh"] = any(s["fresh"] for s in item["sources"])
        if item.get("company_checked_at") and (now-parse_time(item["company_checked_at"])).total_seconds()>86400:
            item["companies"] = []
            item["company_status"] = "pending"
    payload["mode"] = os.environ.get("TRZIP_RELEASE_MODE","candidate")
    return payload


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options":"nosniff","Referrer-Policy":"strict-origin-when-cross-origin",
                             "Permissions-Policy":"camera=(), microphone=(), geolocation=()",
                             "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/","/health")) else "public, max-age=300"
    return response


@app.get("/health")
def health():
    return {"service":"trzip","status":"running","data_readiness":"/api/status"}


@app.get("/api/status")
def runtime_status():
    with reader() as db:
        return status(db)


@app.get("/health/ready")
def ready():
    with reader() as db:
        result = status(db)
    return JSONResponse(result,status_code=200 if result["sources"][0]["status"]=="fresh" else 503)


@app.get("/api/trends")
def trends(publication: str | None = None, q: str = Query("",max_length=100), lane: str = Query("all",pattern="^(all|general|issue|company)$"), limit: int=Query(250,ge=1,le=500)):
    payload = edition(publication)
    items = payload["items"]
    if q.strip():
        items = [r for r in items if q.casefold() in r["title"].casefold() or any(q.casefold() in c["name"].casefold() for c in r["companies"])]
    if lane in {"general","issue"}:
        items = [r for r in items if r["lane"]==lane]
    elif lane=="company":
        items = [r for r in items if r["companies"]]
    payload["total"] = len(items)
    payload["items"] = [{k:v for k,v in item.items() if k not in {"history","articles","related_terms","company_sources"}} for item in items[:limit]]
    return payload


@app.get("/api/trends/{event}")
def detail(event: str, publication: str | None = None):
    payload = edition(publication)
    item = next((r for r in payload["items"] if r["event_id"]==event),None)
    if not item:
        raise HTTPException(404,"이 게시본에서 찾을 수 없는 트렌드입니다.")
    return {"publication_id":payload["publication_id"],"published_at":payload["published_at"],"item":item}


@app.get("/api/companies/{ticker}")
def company(ticker: str, publication: str | None = None):
    payload = edition(publication)
    for row in payload["items"]:
        for company in row["companies"]:
            if company["ticker"]==ticker:
                return {"publication_id":payload["publication_id"],"company":company}
    raise HTTPException(404,"현재 게시본에 검증된 기업 연결이 없습니다.")


@app.get("/api/media/card/{event}.svg")
def card(event: str):
    if not re.fullmatch(r"(?:evt_[a-f0-9]{20}|yt_[A-Za-z0-9_-]{1,30})",event):
        raise HTTPException(404)
    with reader() as db:
        row = db.execute("SELECT title FROM jobs WHERE event_id=?",(event,)).fetchone()
    if not row:
        raise HTTPException(404)
    return Response(text_card(row[0]),media_type="image/svg+xml")


@app.get("/api/media/{filename}")
def media(filename: str):
    if not re.fullmatch(r"[a-f0-9]{64}\.png",filename):
        raise HTTPException(404)
    path = home()/"media"/filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path,media_type="image/png")


web = Path(os.environ.get("TRZIP_WEB_ROOT",ROOT/"web"))


@app.get("/")
def index():
    return FileResponse(web/"index.html")


@app.get("/{asset}")
def static_asset(asset: str):
    # Vercel's local link can create .env.local here. Never expose a directory.
    if asset not in {"index.html","app.js","app.css","icon.svg"}:
        raise HTTPException(404)
    return FileResponse(web/asset)
