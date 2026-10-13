from __future__ import annotations
import hashlib
from html import escape
import io
import shutil
from pathlib import Path
from PIL import Image
from .core import atomic_json, now_iso
from .net import fetch


def text_card(title: str) -> str:
    lines = [title[i:i+22] for i in range(0,min(len(title),44),22)]
    text = "".join(f'<text x="48" y="{320+i*34}" font-size="28">{escape(line)}</text>' for i,line in enumerate(lines))
    initials=escape(title[:2].upper())
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="420" viewBox="0 0 720 420"><rect width="720" height="420" rx="24" fill="#eee8ff"/><g fill="#6535cd" font-family="sans-serif"><text x="48" y="60" font-size="20" letter-spacing="4">TR ZIP</text><text x="42" y="258" font-size="180" font-weight="800">{initials}</text>{text}<text x="48" y="398" font-size="16">자동 텍스트 카드 · 현장 사진이 아닙니다</text></g></svg>'


def company_image(company: dict, root: Path) -> dict | None:
    if not company.get("homepage") or shutil.disk_usage(root).free<5*1024**3:
        return None
    from trzip.company_logo_assets import resolve_company_logo
    try:
        logo = resolve_company_logo(company["homepage"],timeout_seconds=4)
        if logo.get("status")!="verified":
            return None
        # Re-fetch: a historical catalogue entry is only a discovery hint.
        response = fetch(logo["asset_url"],max_bytes=4_000_000,timeout=8)
        with Image.open(io.BytesIO(response.body)) as image:
            if image.width*image.height>16_000_000:
                return None
            image.thumbnail((800,800))
            output = io.BytesIO()
            image.convert("RGBA").save(output,format="PNG")
        body = output.getvalue()
        digest = hashlib.sha256(body).hexdigest()
        media = root/"media"
        media.mkdir(exist_ok=True)
        path = media/(digest+".png")
        if not path.exists():
            path.write_bytes(body)
        metadata = {"kind":"official_logo","url":"/api/media/"+digest+".png","source_url":logo["source_page_url"],
                    "original_url":response.url,"attribution":company["name"]+" 공식 로고 · 상표권은 해당 기업에 있습니다",
                    "rights":"기업 식별용 공식 로고","verified_at":now_iso(),"sha256":digest}
        atomic_json(media/(digest+".json"),metadata)
        return metadata
    except Exception:
        return None
