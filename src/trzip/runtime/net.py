"""Bounded public-only HTTP. DNS answers are pinned through connect, including redirects."""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import os
import socket
import ssl
from urllib.parse import urljoin, urlsplit


@dataclass
class Response:
    url: str
    body: bytes
    content_type: str

    def text(self) -> str:
        charset = self.content_type.partition("charset=")[2].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def public_addresses(url: str) -> tuple[str, int, list[str]]:
    p = urlsplit(url)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise ValueError("unsafe URL")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("unsafe port")
    addresses = sorted({x[4][0] for x in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise ValueError("non-public address")
    return p.hostname, port, addresses


def fetch(url: str, *, max_bytes: int = 3_000_000, timeout: float = 12, headers=None) -> Response:
    for _ in range(5):
        hostname, port, addresses = public_addresses(url)
        parsed = urlsplit(url)
        conn = http.client.HTTPConnection(hostname, port, timeout=timeout)
        sock = None
        for address in addresses:
            try:
                sock = socket.create_connection((address, port), timeout=timeout)
                if parsed.scheme == "https":
                    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=hostname)
                break
            except OSError:
                if sock:
                    sock.close()
                sock = None
        if sock is None:
            raise OSError("public host connection failed")
        conn.sock = sock
        try:
            agent = os.environ.get("TRZIP_USER_AGENT", "TRZIP/1.0 (+https://github.com/jyy7294/noinbada)")
            conn.request("GET", (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
                         headers={"User-Agent": agent, "Accept-Encoding": "identity", **(headers or {})})
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("redirect without location")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
            if int(response.getheader("Content-Length") or 0) > max_bytes:
                raise ValueError("response too large")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("response too large")
            return Response(url, body, response.getheader("Content-Type") or "")
        finally:
            conn.close()
    raise ValueError("too many redirects")
