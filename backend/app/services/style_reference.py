"""
style_reference.py
Reads a reference website's visual language — colors, fonts, type sizes,
corner radii, shadows, CSS variables — so a PM can say "make it feel like
this site" without describing it by hand. The extracted "style tags" feed the
Platform Blueprint prompt (ai/text/ux_prompt_generator.py).

Static parsing only: BeautifulSoup over the page's HTML plus the stylesheets
it links, with regexes over the CSS text. A site that styles itself at
runtime (heavy JavaScript / CSS-in-JS) yields thinner results; extraction
says so in `notes` rather than guessing.

SECURITY — this makes the server fetch a URL a user typed, so it is a
server-side-request-forgery surface (on AWS Fargate, the task-credentials
endpoint is reachable from inside the container). Every request, including
each redirect hop, is checked: http/https only, ports 80/443 only, no
credentials in the URL, and every address the host resolves to must be
globally routable — private, loopback, link-local and metadata addresses are
refused. Responses are capped in size and time. One residual risk is DNS
rebinding (a host that resolves to a public address at check time and a
private one at connect time); it needs an attacker-controlled DNS name and a
signed-in user, and is accepted for this internal tool.
"""

import colorsys
import ipaddress
import re
import socket
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from config import (
    STYLE_FETCH_MAX_BYTES,
    STYLE_FETCH_MAX_REDIRECTS,
    STYLE_FETCH_MAX_STYLESHEETS,
    STYLE_FETCH_TIMEOUT_SECONDS,
    STYLE_FETCH_USER_AGENT,
)


class StyleFetchError(ValueError):
    """The URL was refused or could not be read. The message is safe to show the PM."""


# ── Safe fetching ────────────────────────────────────────────────────────────

_ALLOWED_PORTS = {80, 443}


def assert_public_url(url: str) -> None:
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise StyleFetchError("That doesn't look like a valid web address.")
    if parts.scheme not in ("http", "https"):
        raise StyleFetchError("Only http:// and https:// addresses can be read.")
    if not parts.hostname:
        raise StyleFetchError("That doesn't look like a valid web address.")
    if parts.username or parts.password:
        raise StyleFetchError("Addresses containing a username or password are not allowed.")
    if port is not None and port not in _ALLOWED_PORTS:
        raise StyleFetchError("Only standard web ports (80 and 443) are allowed.")

    try:
        infos = socket.getaddrinfo(parts.hostname, port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise StyleFetchError(f"Could not find the website {parts.hostname}.")
    if not infos:
        raise StyleFetchError(f"Could not find the website {parts.hostname}.")
    for info in infos:
        address = info[4][0].split("%")[0]
        if not ipaddress.ip_address(address).is_global:
            raise StyleFetchError("That address points to a private or internal network and can't be read.")


def _http_get(url: str):
    """The only function that touches the network — tests replace it."""
    return requests.get(
        url,
        headers={"User-Agent": STYLE_FETCH_USER_AGENT, "Accept": "text/html,text/css,*/*;q=0.5"},
        timeout=STYLE_FETCH_TIMEOUT_SECONDS,
        stream=True,
        allow_redirects=False,
    )


def _read_capped(response) -> str:
    # requests' timeout applies per socket read, so a server that trickles a
    # few bytes at a time could keep a read going far longer — cap the total.
    deadline = time.monotonic() + STYLE_FETCH_TIMEOUT_SECONDS
    chunks, size = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        size += len(chunk)
        if size > STYLE_FETCH_MAX_BYTES:
            raise StyleFetchError("That page is too large to read.")
        if time.monotonic() > deadline:
            raise StyleFetchError("The website took too long to respond.")
        chunks.append(chunk)
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def _safe_get(url: str) -> tuple[str, str]:
    """GET with per-hop validation and manual redirects. Returns (final_url, text)."""
    current = url
    for _ in range(STYLE_FETCH_MAX_REDIRECTS + 1):
        assert_public_url(current)
        try:
            response = _http_get(current)
        except requests.exceptions.Timeout:
            raise StyleFetchError("The website took too long to respond.")
        except requests.exceptions.RequestException:
            raise StyleFetchError("The website could not be reached.")
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise StyleFetchError("The website redirected without saying where.")
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise StyleFetchError(f"The website returned an error ({response.status_code}).")
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not content_type.startswith("text/") and "xml" not in content_type:
                raise StyleFetchError("That address is not a web page.")
            return current, _read_capped(response)
        finally:
            response.close()
    raise StyleFetchError("The website redirected too many times.")


# ── Extraction ───────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+%?)[\s,]+([\d.]+%?)[\s,]+([\d.]+%?)(?:[\s,/]+([\d.]+%?))?\s*\)")
_HSL_RE = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%(?:[\s,/]+([\d.]+%?))?\s*\)")
_VAR_RE = re.compile(r"--([\w-]+)\s*:\s*([^;}{]+)")
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([\d.]+)(px|rem|em)\b", re.I)
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;}{]+)", re.I)
_SHADOW_RE = re.compile(r"box-shadow\s*:\s*([^;}{]+)", re.I)
_TOKEN_VAR_NAME_RE = re.compile(
    r"(color|colour|bg|background|text|font|radius|space|spacing|shadow|primary|accent|brand|border|surface)", re.I
)
_GENERIC_FONTS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
    "ui-monospace", "inherit", "initial", "unset", "emoji", "math", "-apple-system", "blinkmacsystemfont",
    "segoe ui", "roboto", "helvetica neue", "helvetica", "arial",
}
_ICON_FONT_HINTS = ("icon", "awesome", "glyph", "symbol")


def _alpha(raw: Optional[str]) -> float:
    if raw is None:
        return 1.0
    return float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)


def _channel(raw: str) -> int:
    return round(float(raw[:-1]) * 2.55) if raw.endswith("%") else round(float(raw))


def _hex(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, v)) for v in (r, g, b)))


def _colors_in(text: str) -> list[str]:
    found: list[str] = []
    for m in _HEX_RE.finditer(text):
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        elif len(h) == 8:
            if int(h[6:], 16) < 128:
                continue
            h = h[:6]
        found.append("#" + h.upper())
    for m in _RGB_RE.finditer(text):
        if _alpha(m.group(4)) < 0.5:
            continue
        found.append(_hex(_channel(m.group(1)), _channel(m.group(2)), _channel(m.group(3))))
    for m in _HSL_RE.finditer(text):
        if _alpha(m.group(4)) < 0.5:
            continue
        r, g, b = colorsys.hls_to_rgb(float(m.group(1)) / 360 % 1, float(m.group(3)) / 100, float(m.group(2)) / 100)
        found.append(_hex(round(r * 255), round(g * 255), round(b * 255)))
    return found


def _hls(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)  # h, lightness, saturation


def _clean_family(raw: str) -> Optional[str]:
    first = raw.split(",")[0].strip().strip("'\"").strip()
    if not first or first.lower() in _GENERIC_FONTS or first.startswith("var("):
        return None
    if any(hint in first.lower() for hint in _ICON_FONT_HINTS):
        return None
    return first


def _google_fonts(soup: BeautifulSoup) -> list[str]:
    families: list[str] = []
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if "fonts.googleapis.com" not in href:
            continue
        query = parse_qs(urlsplit(href).query)
        for value in query.get("family", []):
            for part in value.split("|"):
                name = part.split(":")[0].replace("+", " ").strip()
                if name and name not in families:
                    families.append(name)
    return families


def extract_style_tags(css_text: str, soup: Optional[BeautifulSoup] = None) -> dict[str, Any]:
    """Pure function: CSS text (inline + linked, concatenated) -> compact style tags."""
    colors = Counter(_colors_in(css_text))
    # A color defined as a CSS variable is a deliberate design token — weigh it up.
    variables: dict[str, str] = {}
    for name, value in _VAR_RE.findall(css_text):
        value = value.strip()
        if _TOKEN_VAR_NAME_RE.search(name) and name not in variables and len(variables) < 30:
            variables[name] = value[:60]
        for c in _colors_in(value):
            colors[c] += 3

    palette = []
    for hex_color, count in colors.most_common(10):
        _, lightness, saturation = _hls(hex_color)
        kind = "neutral" if saturation < 0.12 or lightness < 0.06 or lightness > 0.96 else "accent"
        palette.append({"hex": hex_color, "count": count, "kind": kind})

    accents = [p for p in palette if p["kind"] == "accent"]
    neutrals = [p for p in palette if p["kind"] == "neutral"]
    neutrals_by_light = sorted(neutrals, key=lambda p: _hls(p["hex"])[1])

    families = Counter()
    for raw in _FONT_FAMILY_RE.findall(css_text):
        family = _clean_family(raw)
        if family:
            families[family] += 1

    sizes = Counter()
    for value, unit in _FONT_SIZE_RE.findall(css_text):
        px = float(value) * (16 if unit.lower() in ("rem", "em") else 1)
        if 9 <= px <= 96:
            sizes[round(px, 1)] += 1

    radii = Counter()
    for raw in _RADIUS_RE.findall(css_text):
        token = raw.strip().split()[0].lower()
        if token not in ("0", "0px", "inherit", "initial") and not token.startswith("var("):
            radii[token] += 1

    shadows = Counter()
    for raw in _SHADOW_RE.findall(css_text):
        value = " ".join(raw.split())
        if value.lower() not in ("none", "inherit", "initial") and not value.startswith("var("):
            shadows[value[:90]] += 1

    return {
        "palette": palette,
        "accent_guess": accents[0]["hex"] if accents else None,
        "background_guess": neutrals_by_light[-1]["hex"] if neutrals_by_light else None,
        "text_guess": neutrals_by_light[0]["hex"] if neutrals_by_light else None,
        "fonts": [f for f, _ in families.most_common(4)],
        "google_fonts": _google_fonts(soup) if soup is not None else [],
        "font_sizes_px": sorted(s for s, _ in sizes.most_common(8)),
        "radii": [r for r, _ in radii.most_common(5)],
        "shadows": [s for s, _ in shadows.most_common(3)],
        "css_variables": variables,
    }


def fetch_style_reference(url: str) -> dict[str, Any]:
    """
    Fetch `url` and return {"url", "title", "theme_color", "style_tags",
    "stylesheets_read", "notes", "fetched_at"}. Raises StyleFetchError with a
    PM-readable message when the page can't be read.
    """
    final_url, html = _safe_get(url.strip())
    soup = BeautifulSoup(html, "html.parser")

    css_parts = [tag.get_text() for tag in soup.find_all("style")]
    # An inline style="…" value has no closing ';' or '}', so wrap it — otherwise
    # its last declaration would run into whatever CSS comes next.
    css_parts += ["{" + tag["style"] + "}" for tag in soup.find_all(style=True)]

    notes: list[str] = []
    hrefs = [
        urljoin(final_url, link["href"])
        for link in soup.find_all("link", href=True)
        if "stylesheet" in " ".join(link.get("rel", [])).lower()
    ]
    read = 0
    for href in hrefs[:STYLE_FETCH_MAX_STYLESHEETS]:
        try:
            _, css = _safe_get(href)
            css_parts.append(css)
            read += 1
        except Exception:
            # Linked stylesheets are best-effort: one that can't be fetched or decoded
            # (for any reason) must not lose what the page itself already told us.
            notes.append("Some stylesheets could not be read.")
    if len(hrefs) > STYLE_FETCH_MAX_STYLESHEETS:
        notes.append(f"Only the first {STYLE_FETCH_MAX_STYLESHEETS} stylesheets were read.")

    tags = extract_style_tags("\n".join(css_parts), soup)
    if not tags["palette"] and not tags["fonts"]:
        notes.append(
            "Very little styling was found in the page's HTML and CSS — the site probably styles itself "
            "with JavaScript. Describe its look in the brief as well."
        )

    theme = soup.find("meta", attrs={"name": "theme-color"})
    title = soup.title.get_text().strip() if soup.title else ""
    return {
        "url": final_url,
        "title": title[:120],
        "theme_color": theme.get("content") if theme else None,
        "style_tags": tags,
        "stylesheets_read": read,
        "notes": sorted(set(notes)),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
