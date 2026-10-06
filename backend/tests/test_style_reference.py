"""
Tests for reading a reference website's style (services/style_reference.py):
the CSS/HTML extraction, and — more importantly — the server-side-request-
forgery guards, since this makes the server fetch a URL a user typed. No test
touches the network: _http_get is replaced and DNS is faked.
"""
import socket
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import style_reference as sr


class FakeResponse:
    def __init__(self, body="", status=200, headers=None, content_type="text/html"):
        self.status_code = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.encoding = "utf-8"
        self._body = body.encode() if isinstance(body, str) else body
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


@pytest.fixture
def web(monkeypatch):
    """A fake internet: web.pages maps url -> FakeResponse, web.dns maps host -> ip."""
    class Web:
        pages: dict = {}
        dns: dict = {}
        requested: list = []

    w = Web()
    w.pages, w.dns, w.requested = {}, {}, []

    def getaddrinfo(host, port, **kw):
        try:
            ip = w.dns.get(host, host)  # literals resolve to themselves
            socket.inet_pton(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
        except OSError:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    def http_get(url):
        w.requested.append(url)
        return w.pages[url]

    monkeypatch.setattr(sr.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(sr, "_http_get", http_get)
    return w


# ── SSRF guards ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://127.0.0.1/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://172.16.0.9/",
        "http://169.254.170.2/v2/credentials",  # ECS task credentials
        "http://169.254.169.254/latest/meta-data/",  # EC2/IMDS
        "http://[::1]/",
        "https://example.com:8443/",
        "https://user:pass@example.com/",
        "not a url",
        "",
    ],
)
def test_internal_and_malformed_urls_are_refused(web, url):
    web.dns["example.com"] = "93.184.216.34"
    with pytest.raises(sr.StyleFetchError):
        sr.assert_public_url(url)
    assert web.requested == []


def test_a_hostname_that_resolves_to_a_private_address_is_refused(web):
    web.dns["intranet.example.com"] = "10.1.2.3"
    with pytest.raises(sr.StyleFetchError, match="private or internal"):
        sr.assert_public_url("https://intranet.example.com/")


def test_a_public_address_is_allowed(web):
    web.dns["example.com"] = "93.184.216.34"
    sr.assert_public_url("https://example.com/")
    sr.assert_public_url("http://example.com:80/")


def test_unresolvable_host_gives_a_readable_error(web):
    with pytest.raises(sr.StyleFetchError, match="Could not find"):
        sr.assert_public_url("https://no-such-host.invalid/")


def test_a_redirect_to_an_internal_address_is_blocked(web):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse(status=302, headers={"Location": "http://169.254.170.2/v2/credentials"})
    with pytest.raises(sr.StyleFetchError, match="private or internal"):
        sr.fetch_style_reference("https://example.com/")
    assert web.requested == ["https://example.com/"]  # the internal URL was never requested


def test_redirects_are_followed_and_capped(web):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse(status=301, headers={"Location": "/home"})
    web.pages["https://example.com/home"] = FakeResponse("<html><title>Home</title></html>")
    assert sr.fetch_style_reference("https://example.com/")["url"] == "https://example.com/home"

    web.pages["https://example.com/loop"] = FakeResponse(status=302, headers={"Location": "/loop"})
    with pytest.raises(sr.StyleFetchError, match="too many times"):
        sr.fetch_style_reference("https://example.com/loop")


def test_oversized_and_non_text_responses_are_refused(web, monkeypatch):
    web.dns["example.com"] = "93.184.216.34"
    monkeypatch.setattr(sr, "STYLE_FETCH_MAX_BYTES", 100)
    web.pages["https://example.com/big"] = FakeResponse("x" * 500)
    with pytest.raises(sr.StyleFetchError, match="too large"):
        sr.fetch_style_reference("https://example.com/big")

    web.pages["https://example.com/img"] = FakeResponse(b"\x89PNG", content_type="image/png")
    with pytest.raises(sr.StyleFetchError, match="not a web page"):
        sr.fetch_style_reference("https://example.com/img")


def test_a_trickling_response_is_cut_off_by_the_overall_time_limit(web, monkeypatch):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/slow"] = FakeResponse("x" * 300)
    monkeypatch.setattr(sr, "STYLE_FETCH_TIMEOUT_SECONDS", 8)
    clock = iter(range(0, 1000, 5))  # every read "takes" 5 seconds
    monkeypatch.setattr(sr.time, "monotonic", lambda: next(clock))
    real_iter = FakeResponse.iter_content
    monkeypatch.setattr(FakeResponse, "iter_content", lambda self, chunk_size=65536: real_iter(self, chunk_size=10))
    with pytest.raises(sr.StyleFetchError, match="too long"):
        sr.fetch_style_reference("https://example.com/slow")


def test_the_extract_endpoint_does_not_hold_the_db_lock_while_fetching(monkeypatch):
    """Every DB session holds the app-wide lock; a slow website must not stall
    other requests, so the fetch has to run after the session is released."""
    from fastapi.testclient import TestClient

    from app.db import session as db_session
    from app.main import app
    from app.routers import ux_prompts as router

    seen = {}

    def fake_fetch(url):
        acquired = db_session._write_lock.acquire(blocking=False)
        seen["lock_free"] = acquired
        if acquired:
            db_session._write_lock.release()
        return {"url": url, "title": "", "theme_color": None, "style_tags": sr.extract_style_tags(""),
                "stylesheets_read": 0, "notes": [], "fetched_at": "2026-10-06T00:00:00+00:00"}

    monkeypatch.setattr(router, "fetch_style_reference", fake_fetch)
    with TestClient(app) as client:
        project_id = client.post("/projects", json={"name": "pytest-style-lock-project"}).json()["id"]
        r = client.post(f"/projects/{project_id}/ux-prompts/style-references/extract", json={"url": "https://example.com"})
        assert r.status_code == 200, r.text
        assert seen["lock_free"] is True
        assert client.post("/projects/does-not-exist/ux-prompts/style-references/extract",
                           json={"url": "https://example.com"}).status_code == 404


def test_http_errors_and_network_failures_are_readable(web, monkeypatch):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/gone"] = FakeResponse(status=404)
    with pytest.raises(sr.StyleFetchError, match="404"):
        sr.fetch_style_reference("https://example.com/gone")

    def boom(url):
        raise sr.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(sr, "_http_get", boom)
    with pytest.raises(sr.StyleFetchError, match="could not be reached"):
        sr.fetch_style_reference("https://example.com/")


# ── Extraction ───────────────────────────────────────────────────────────────

CSS = """
:root { --brand-primary: #0071e3; --surface: rgb(245, 245, 247); --radius-card: 18px; --unrelated-thing: 4; }
body { font-family: "SF Pro Display", -apple-system, sans-serif; color: #1d1d1f; background: #fff; font-size: 17px; }
h1 { font-size: 3rem; color: #1D1D1F; }
a { color: hsl(211, 100%, 45%); }
.btn { background: #0071e3; border-radius: 980px; box-shadow: 0 4px 12px rgba(0,0,0,.12); font-family: 'SF Pro Text', sans-serif; }
.card { border-radius: 18px; box-shadow: none; font-family: "Font Awesome 6 Free"; }
.ghost { background: rgba(0,0,0,0.02); }
@media (max-width: 600px) { .card { border-radius: 12px; font-size: 14px; } }
"""


def test_extract_style_tags_reads_colors_fonts_radii_shadows_and_variables():
    tags = sr.extract_style_tags(CSS)

    hexes = {p["hex"]: p for p in tags["palette"]}
    assert hexes["#0071E3"]["kind"] == "accent"
    assert hexes["#1D1D1F"]["kind"] == "neutral" and hexes["#FFFFFF"]["kind"] == "neutral"
    assert "#F5F5F7" in hexes  # rgb() converted
    assert "#000000" not in hexes  # near-transparent rgba skipped
    assert tags["accent_guess"] in ("#0071E3", "#0073E6")  # hsl() lands near the same blue
    assert tags["text_guess"] == "#1D1D1F" and tags["background_guess"] == "#FFFFFF"

    assert tags["fonts"][0] == "SF Pro Display" and "SF Pro Text" in tags["fonts"]
    assert all("Awesome" not in f and f.lower() != "sans-serif" for f in tags["fonts"])  # icon/generic fonts skipped

    assert 17.0 in tags["font_sizes_px"] and 48.0 in tags["font_sizes_px"] and 14.0 in tags["font_sizes_px"]
    assert {"18px", "980px", "12px"} <= set(tags["radii"])
    assert tags["shadows"] == ["0 4px 12px rgba(0,0,0,.12)"]  # 'none' skipped
    assert tags["css_variables"]["brand-primary"] == "#0071e3"
    assert "unrelated-thing" not in tags["css_variables"]


def test_a_color_defined_as_a_variable_is_weighted_up():
    tags = sr.extract_style_tags(":root{--brand:#ff3300} a{color:#3300ff} b{color:#3300ff}")
    assert tags["palette"][0]["hex"] == "#FF3300"  # 3 (token) > 2 (plain uses)


def test_google_fonts_are_read_from_link_tags():
    soup = BeautifulSoup(
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Fira+Code&display=swap" rel="stylesheet">',
        "html.parser",
    )
    assert sr.extract_style_tags("", soup)["google_fonts"] == ["Inter", "Fira Code"]


def test_fetch_style_reference_reads_inline_and_linked_css(web):
    web.dns["example.com"] = "93.184.216.34"
    web.dns["cdn.example.com"] = "93.184.216.35"
    web.pages["https://example.com/"] = FakeResponse(
        """<html><head><title> Example Co </title>
        <meta name="theme-color" content="#0071e3">
        <link rel="stylesheet" href="/site.css">
        <link rel="stylesheet" href="https://cdn.example.com/more.css">
        <style>.hero { color: #ff0066; }</style></head>
        <body style="font-family: Georgia"><h1>Hi</h1></body></html>"""
    )
    web.pages["https://example.com/site.css"] = FakeResponse(CSS, content_type="text/css")
    web.pages["https://cdn.example.com/more.css"] = FakeResponse(".x{border-radius:6px}", content_type="text/css")

    ref = sr.fetch_style_reference("https://example.com/")
    assert ref["title"] == "Example Co" and ref["theme_color"] == "#0071e3"
    assert ref["stylesheets_read"] == 2
    hexes = [p["hex"] for p in ref["style_tags"]["palette"]]
    assert "#FF0066" in hexes and "#0071E3" in hexes  # inline <style> + linked CSS
    assert "Georgia" in ref["style_tags"]["fonts"]    # inline style attribute
    assert "6px" in ref["style_tags"]["radii"]        # second stylesheet
    assert ref["notes"] == []


def test_an_unreadable_stylesheet_is_noted_not_fatal(web):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse(
        '<html><link rel="stylesheet" href="/missing.css"><style>a{color:#ff0066}</style></html>'
    )
    web.pages["https://example.com/missing.css"] = FakeResponse(status=404)
    ref = sr.fetch_style_reference("https://example.com/")
    assert "Some stylesheets could not be read." in ref["notes"]
    assert ref["style_tags"]["accent_guess"] == "#FF0066"


def test_a_stylesheet_pointing_at_an_internal_host_is_skipped(web):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse(
        '<html><link rel="stylesheet" href="http://169.254.170.2/v2/credentials"><style>a{color:#ff0066}</style></html>'
    )
    ref = sr.fetch_style_reference("https://example.com/")
    assert ref["stylesheets_read"] == 0 and "http://169.254.170.2/v2/credentials" not in web.requested


def test_a_page_with_no_styling_says_so(web):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse("<html><body><div id='root'></div></body></html>")
    ref = sr.fetch_style_reference("https://example.com/")
    assert ref["style_tags"]["palette"] == []
    assert any("JavaScript" in n for n in ref["notes"])


def test_stylesheet_count_is_capped(web, monkeypatch):
    monkeypatch.setattr(sr, "STYLE_FETCH_MAX_STYLESHEETS", 2)
    web.dns["example.com"] = "93.184.216.34"
    links = "".join(f'<link rel="stylesheet" href="/{i}.css">' for i in range(5))
    web.pages["https://example.com/"] = FakeResponse(f"<html>{links}</html>")
    for i in range(5):
        web.pages[f"https://example.com/{i}.css"] = FakeResponse("a{color:#ff0066}", content_type="text/css")
    ref = sr.fetch_style_reference("https://example.com/")
    assert ref["stylesheets_read"] == 2 and "Only the first 2 stylesheets were read." in ref["notes"]


def test_an_unexpected_error_in_one_stylesheet_does_not_lose_the_rest(web, monkeypatch):
    web.dns["example.com"] = "93.184.216.34"
    web.pages["https://example.com/"] = FakeResponse(
        '<html><link rel="stylesheet" href="/bad.css"><style>a{color:#ff0066}</style></html>'
    )
    real_get = sr._http_get

    def flaky(url):
        if url.endswith("bad.css"):
            raise RuntimeError("unexpected")
        return real_get(url)

    monkeypatch.setattr(sr, "_http_get", flaky)
    ref = sr.fetch_style_reference("https://example.com/")
    assert ref["style_tags"]["accent_guess"] == "#FF0066"
    assert "Some stylesheets could not be read." in ref["notes"]
