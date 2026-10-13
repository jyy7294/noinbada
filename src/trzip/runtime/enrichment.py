"""Current official registers plus narrow, revalidated relation evidence."""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
import html
import hashlib
import json
from pathlib import Path
import re
import shutil

from .core import atomic_json, connect, encode, home, key, now_iso, parse_time, writer_lock
from .net import fetch
from .pipeline import lane, publish

KRX = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
SEC = "https://www.sec.gov/files/company_tickers_exchange.json"
NASDAQ = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NYSE = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# These are discovery rules. A rule alone is never published as proof: current
# listing and the cited official page must both pass during enrichment.
RELATIONS = [
    ("005930", ["삼성전자", "갤럭시", "galaxy"], "https://www.samsung.com/sec/", "Galaxy", "삼성전자의 Galaxy 제품"),
    ("035420", ["네이버", "naver"], "https://www.navercorp.com/", "NAVER", "NAVER 서비스 운영 기업"),
    ("035720", ["카카오톡"], "https://www.kakaocorp.com/page/service/service/KakaoTalk", "카카오톡", "카카오톡 서비스 운영 기업"),
    ("AAPL", ["애플", "아이폰", "iphone", "apple"], "https://www.apple.com/iphone/", "iPhone", "Apple 기업·iPhone 제품 직접 언급"),
    ("MSFT", ["마이크로소프트", "microsoft", "엑스박스", "xbox"], "https://www.microsoft.com/en-us/", "Xbox", "Microsoft의 Xbox 제품·서비스"),
    ("NVDA", ["엔비디아", "nvidia", "지포스", "geforce"], "https://www.nvidia.com/en-us/geforce/", "GeForce", "NVIDIA의 GeForce 제품"),
    ("TSLA", ["테슬라", "tesla"], "https://www.tesla.com/", "Tesla", "Tesla 기업 직접 언급"),
    ("NFLX", ["넷플릭스", "netflix"], "https://ir.netflix.net/", "Netflix", "Netflix 기업·서비스 직접 언급"),
    ("GOOGL", ["유튜브", "youtube"], "https://abc.xyz/", "YouTube", "Alphabet이 공시한 YouTube 사업"),
]
PRODUCT_TERMS={"갤럭시","galaxy","카카오톡","아이폰","iphone","엑스박스","xbox","지포스","geforce","유튜브","youtube"}
# Similar group names or third-party associations do not imply ownership.


def plain(document: str) -> str:
    document = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", document, flags=re.S|re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", document)).split())


@lru_cache(maxsize=20000)
def matcher(term: str):
    term = key(term)
    if re.search(r"[a-z0-9]", term):
        return re.compile(r"(?<![a-z0-9])"+re.escape(term)+r"(?![a-z0-9])")
    return re.compile(r"(?<![가-힣])"+re.escape(term)+r"(?![가-힣])")


def contains(text: str, term: str) -> bool:
    return matcher(term).search(key(text)) is not None


def parse_krx(document: str, at: str) -> list[dict]:
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", document, re.S|re.I):
        cells = [plain(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S|re.I)]
        if len(cells)<3 or not re.fullmatch(r"\d{6}", cells[2]):
            continue
        exchange = {"유가":"KOSPI","유가증권":"KOSPI","코스피":"KOSPI","코스닥":"KOSDAQ","코넥스":"KONEX"}.get(cells[1])
        if not exchange:
            continue
        urls = re.findall(r'https?://[^\s<>"\']+', html.unescape(row))
        homepage = next((u for u in urls if "krx.co.kr" not in u), None)
        rows.append({"name":cells[0],"ticker":cells[2],"exchange":exchange,"country":"KR","homepage":homepage,
                     "listing_source":KRX,"listing_observed_at":at})
    if len(rows)<1000 or len({r["ticker"] for r in rows}) != len(rows):
        raise ValueError("incomplete KRX register")
    return rows


def parse_sec(payload: dict, at: str) -> list[dict]:
    fields = payload["fields"]
    rows = []
    for values in payload["data"]:
        record = dict(zip(fields, values))
        if str(record.get("exchange")).lower() not in {"nasdaq","nyse","cboe"}:
            continue
        rows.append({"name":record["name"],"ticker":record["ticker"],"exchange":record["exchange"],"country":"US",
                     "cik":str(record["cik"]).zfill(10),"homepage":None,"listing_source":SEC,"listing_observed_at":at})
    if len(rows)<1000:
        raise ValueError("incomplete SEC register")
    return rows


def parse_nasdaq(document: str, source: str, at: str) -> list[dict]:
    lines = document.strip().splitlines()
    fields = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        r = dict(zip(fields,line.split("|")))
        ticker = r.get("Symbol") or r.get("ACT Symbol")
        if not ticker or r.get("Test Issue") != "N" or r.get("ETF") != "N":
            continue
        if source == NYSE and r.get("Exchange") != "N":
            continue
        name = r["Security Name"].split(" - ")[0]
        rows.append({"name":name,"ticker":ticker,"exchange":"NASDAQ" if source==NASDAQ else "NYSE","country":"US",
                     "homepage":None,"listing_source":source,"listing_observed_at":at})
    if len(rows)<500:
        raise ValueError("incomplete Nasdaq register")
    return rows


def universe(root: Path, at: str) -> tuple[list[dict],dict]:
    cache = root/"company-register.json"
    try:
        previous = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {"items":[],"sources":{}}
    items, sources = [], {}
    for country in ("KR","US"):
        last = previous["sources"].get(country,{})
        age = (parse_time(at)-parse_time(last["observed_at"])).total_seconds() if last.get("observed_at") else 999999
        if 0 <= age < 86400:
            items.extend(r for r in previous["items"] if r["country"]==country)
            sources[country] = last
            continue
        try:
            if country=="KR":
                response = fetch(KRX,max_bytes=8_000_000,timeout=20)
                records = parse_krx(response.body.decode("euc-kr"), at)
            else:
                try:
                    records = parse_sec(json.loads(fetch(SEC,max_bytes=4_000_000).body),at)
                except Exception:
                    records = parse_nasdaq(fetch(NASDAQ).text(),NASDAQ,at)+parse_nasdaq(fetch(NYSE).text(),NYSE,at)
            items.extend(records)
            sources[country] = {"status":"verified","observed_at":at,"count":len(records)}
        except Exception as exc:
            sources[country] = {"status":"unavailable","reason":type(exc).__name__,"observed_at":None}
    atomic_json(cache,{"items":items,"sources":sources})
    return items,sources


def company_links(title: str, records: list[dict], evidence_fetch=fetch) -> list[dict]:
    if lane(title)=="issue":
        return []
    result = {}
    for company in records:
        name = company["name"]
        # Only full legal names; abbreviated English issuer names are ambiguous.
        if len(name)>=3 and contains(title,name):
            result[company["ticker"]] = {**company,"relation":"기업명 직접 언급","evidence_url":company["listing_source"],
                                          "evidence_text":name,"evidence_sha256":hashlib.sha256(name.encode()).hexdigest(),"relation_verified_at":company["listing_observed_at"]}
    by_ticker = {r["ticker"]:r for r in records}
    for ticker, terms, url, marker, description in RELATIONS:
        matched = [t for t in terms if contains(title,t)]
        if ticker not in by_ticker or not matched:
            continue
        # Apple alone is ambiguous in English; require another technology marker.
        if matched==["apple"] and not any(contains(title,t) for t in ("iphone","mac","ios","aapl","apple inc")):
            continue
        try:
            document = plain(evidence_fetch(url,max_bytes=3_000_000).text())
            index = document.casefold().find(marker.casefold())
            if index<0:
                continue
            relation = description if any(t in PRODUCT_TERMS for t in matched) else "기업·브랜드 직접 언급"
            result[ticker] = {**by_ticker[ticker],"homepage":url,"relation":relation,"matched_terms":matched,"evidence_sha256":hashlib.sha256(document.encode()).hexdigest(),
                              "evidence_url":url,"evidence_text":document[max(0,index-40):index+120],"relation_verified_at":now_iso()}
        except Exception:
            continue
    return list(result.values())


def run_enrichment(root: Path | None = None, limit: int = 12) -> dict:
    from .media import company_image
    root = root or home()
    with writer_lock(root), connect(root) as db:
        if shutil.disk_usage(root).free < 5*1024**3:
            return {"status":"deferred_disk_reserve"}
        at = now_iso()
        records, sources = universe(root,at)
        # Bound work to recent observed events; never backlog an unlimited archive.
        jobs = db.execute("SELECT j.* FROM jobs j JOIN (SELECT event_id,MAX(observed_at) last_seen FROM observations GROUP BY event_id) o ON o.event_id=j.event_id WHERE j.status='pending' AND j.next_at<=? AND o.last_seen>=? ORDER BY o.last_seen DESC,j.attempts,j.rowid LIMIT 500",(at,(parse_time(at)-timedelta(hours=2)).isoformat())).fetchall()
        def priority(job):
            direct = any(len(r["name"])>=3 and contains(job["title"],r["name"]) for r in records)
            known = any(contains(job["title"],t) for _,terms,*_ in RELATIONS for t in terms)
            return not(direct or known)
        jobs = sorted(jobs,key=priority)[:limit]
        for job in jobs:
            try:
                companies = company_links(job["title"],records)
                for company in companies:
                    company["logo"] = company_image(company,root)
                payload = {"companies":companies,"company_status":"verified" if companies else "no_verified_relation" if records else "register_unavailable",
                           "company_checked_at":at,"company_sources":sources}
                if companies and companies[0].get("logo"):
                    payload["image"] = companies[0]["logo"]
                with db:
                    db.execute("INSERT OR REPLACE INTO enrichment VALUES (?,?,?)",(job["event_id"],at,encode(payload)))
                    db.execute("UPDATE jobs SET status='done',attempts=attempts+1,updated_at=? WHERE event_id=?",(at,job["event_id"]))
            except Exception:
                with db:
                    db.execute("UPDATE jobs SET attempts=attempts+1,next_at=?,updated_at=? WHERE event_id=?",((parse_time(at)+timedelta(minutes=min(120,5*2**min(job["attempts"],5)))).isoformat(),at,job["event_id"]))
        edition = publish(db,root)
        return {"processed":len(jobs),"registers":sources,"publication_id":edition["publication_id"]}
