from datetime import UTC, datetime, timedelta
import json
import socket
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from trzip.runtime import collectors, net
from trzip.runtime.core import connect, event_id, parse_time, decode
from trzip.runtime.enrichment import company_links, contains
from trzip.runtime.media import text_card
from trzip.runtime.pipeline import run, status


@pytest.fixture(autouse=True)
def isolated_disk_capacity(monkeypatch):
    # Unit cases must not depend on unrelated apps filling the host volume.
    # The production reserve guard is exercised explicitly below, unchanged.
    import shutil
    monkeypatch.setattr(shutil,'disk_usage',lambda path:SimpleNamespace(total=10*1024**3,used=2*1024**3,free=8*1024**3))


def adapter(title="테스트 트렌드",position=1,frame="google_page_test"):
    return lambda: ([{"event_id":event_id(title),"title":title,"position":position,"source_url":"https://trends.google.com/",
                     "articles":[],"related_terms":[],"rank_basis":"observed"}],
                    {"sampling_frame":frame,"coverage":"complete","scope_label":"test","rank_basis":"observed"})


def failure():
    raise TimeoutError("secret must never appear")


def test_failed_collection_preserves_observations_without_refreshing_time(tmp_path):
    at="2026-10-14T00:00:00+00:00"
    run(tmp_path,at=at,adapters={"google":adapter()},force=True)
    result=run(tmp_path,at="2026-10-14T00:40:00+00:00",adapters={"google":failure},force=True)
    assert result["status"]=="failed"
    with connect(tmp_path) as db:
        payload=decode(db.execute("SELECT payload FROM publications WHERE id=?",(result["publication_id"],)).fetchone()[0])
        assert payload["observed_at"]==at
        assert payload["items"][0]["fresh"] is False
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]==1
        assert "secret" not in db.execute("SELECT detail FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    recovery=run(tmp_path,at="2026-10-14T00:50:00+00:00",adapters={"google":adapter("복구 항목")},force=True)
    assert recovery["status"]=="ok"


def test_history_never_mixes_sampling_frames(tmp_path):
    for minute,frame in [(0,"page"),(10,"page"),(20,"rss")]:
        result=run(tmp_path,at=f"2026-10-14T00:{minute:02d}:00+00:00",adapters={"google":adapter(frame=frame)},force=True)
    with connect(tmp_path) as db:
        payload=decode(db.execute("SELECT payload FROM publications WHERE id=?",(result["publication_id"],)).fetchone()[0])
    assert len(payload["items"][0]["history"])==1
    assert payload["items"][0]["change"] is None


def test_duplicate_observations_fail_closed(tmp_path):
    rows,meta=adapter()()
    result=run(tmp_path,adapters={"google":lambda:(rows+rows,meta)},force=True)
    assert result["status"]=="failed"
    assert result["items"]==0


def test_official_rss_is_explicitly_limited():
    xml=b'<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>example</title><pubDate>Tue, 13 Oct 2026 12:00:00 +0000</pubDate><ht:approx_traffic>1000+</ht:approx_traffic></item></channel></rss>'
    rows,meta=collectors.google_rss(xml)
    assert meta["coverage"]=="limited"
    assert rows[0]["source_created_at"]=="2026-10-13T12:00:00+00:00"
    assert rows[0]["rank_basis"]=="rss_feed_position"
    with pytest.raises(Exception):
        collectors.google_rss(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>')


def test_api_pins_editions_and_rejects_writes(tmp_path,monkeypatch):
    monkeypatch.setenv("TRZIP_RUNTIME_HOME",str(tmp_path))
    a=run(tmp_path,adapters={"google":adapter("첫 게시본")},force=True)
    b=run(tmp_path,adapters={"google":adapter("다음 게시본")},force=True)
    from trzip.runtime.api import app
    client=TestClient(app)
    assert client.get('/api/trends').json()['publication_id']==b['publication_id']
    detail=client.get(f'/api/trends/{event_id("첫 게시본")}?publication={a["publication_id"]}')
    assert detail.status_code==200
    assert detail.json()['item']['title']=='첫 게시본'
    assert client.get('/api/trends?publication=../../bad').status_code==400
    assert client.post('/api/trends',json={'title':'injected'}).status_code==405
    assert client.get('/api/media/abc.png').status_code==404
    assert client.get('/.env.local').status_code==404
    assert client.get('/.vercel/project.json').status_code==404
    assert client.get('/health/ready').status_code==200
    assert client.get('/api/trends').headers['cache-control']=='no-store'


def test_missing_scheduled_runs_reduce_release_coverage(tmp_path):
    start="2026-10-10T00:00:00+00:00"
    run(tmp_path,at=start,adapters={"google":adapter()},force=True)
    with connect(tmp_path) as db:
        result=status(db,"2026-10-13T00:00:00+00:00")
    assert result['observation_hours']==72
    assert result['scheduled_slot_coverage']<0.01
    assert result['release_gate']['automatic_checks_pass'] is False


def test_font_mime_is_portable_without_exposing_private_files(tmp_path,monkeypatch):
    import mimetypes
    from trzip.runtime import api
    # A Windows MIME registry can report a different type than Linux.
    monkeypatch.setattr(mimetypes,'guess_type',lambda *args,**kwargs:('application/octet-stream',None))
    monkeypatch.setattr(api,'web',tmp_path)
    (tmp_path/'wanted-sans.woff2').write_bytes(b'wOF2-test-font')
    (tmp_path/'.env.local').write_text('private-test-value')
    with TestClient(api.app) as client:
        font=client.get('/wanted-sans.woff2')
        assert font.status_code==200
        assert font.headers['content-type']=='font/woff2'
        assert font.headers['x-content-type-options']=='nosniff'
        assert "script-src 'self'" in font.headers['content-security-policy']
        assert client.get('/.env.local').status_code==404
        assert client.get('/other-font.woff2').status_code==404


def test_low_disk_reserve_stops_before_collecting_or_publishing(tmp_path,monkeypatch):
    import shutil
    monkeypatch.setattr(shutil,'disk_usage',lambda path:SimpleNamespace(total=10*1024**3,used=6*1024**3,free=4*1024**3))
    with pytest.raises(RuntimeError,match='disk_reserve_below_5_GiB'):
        run(tmp_path,at='2026-10-14T00:00:00+00:00',adapters={'google':adapter()},force=True)
    with connect(tmp_path) as db:
        assert db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM publications').fetchone()[0]==0


def test_company_requires_listing_and_relation():
    now="2026-10-14T00:00:00+00:00"
    company={"name":"Apple Inc.","ticker":"AAPL","exchange":"Nasdaq","country":"US","listing_source":"https://www.sec.gov/","listing_observed_at":now}
    def proof(url,**kwargs):return net.Response(url,b'<html>Apple makes iPhone.</html>',"text/html")
    assert company_links('아이폰',[company],proof)[0]['ticker']=='AAPL'
    assert company_links('아이폰',[],proof)==[]
    assert company_links('apple pie',[company],proof)==[]
    assert company_links('아이폰 사망 사고',[company],proof)==[]
    assert company_links('반도체 산업',[company],proof)==[]
    def missing(url,**kwargs):return net.Response(url,b'Nothing relevant',"text/html")
    assert company_links('아이폰',[company],missing)==[]
    assert contains('삼성전자 실적','삼성전자')
    assert not contains('신세계인터내셔날','신세계')


@pytest.mark.parametrize('address',['127.0.0.1','10.1.2.3','169.254.169.254','::1','192.168.0.1'])
def test_http_rejects_private_dns_answers(monkeypatch,address):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,0,'',(address,443))])
    with pytest.raises(ValueError):net.public_addresses('https://public.example/path')


def test_text_image_cannot_inject_svg_script():
    svg=text_card('<script>alert(1)</script> & "hello"')
    assert '<script>' not in svg
    assert '&lt;script&gt;' in svg
    with pytest.raises(ValueError):parse_time('2026-10-14T00:00:00')


def test_maintenance_archives_then_restores_backup(tmp_path):
    from trzip.runtime.maintenance import maintain
    import gzip
    import sqlite3
    old=(datetime.now(UTC)-timedelta(days=16)).isoformat()
    run(tmp_path,at=old,adapters={"google":adapter()},force=True)
    report=maintain(tmp_path)
    archive=list((tmp_path/'archive').glob('*-observations-*.jsonl.gz'))
    assert len(archive)==1
    assert json.loads(gzip.decompress(archive[0].read_bytes()).decode().splitlines()[0])['observed_at']==old
    with sqlite3.connect(tmp_path/'backups'/report['backup']) as source, sqlite3.connect(tmp_path/'restored.sqlite3') as restored:
        source.backup(restored)
        assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert restored.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
        assert restored.execute('SELECT COUNT(*) FROM publications').fetchone()[0]==1
