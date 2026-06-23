#!/usr/bin/env python3
"""
================================================================================
FORTRESS v5.2 — LENIENT DISCOVERY + TIERED TRUST (HARDENED)
================================================================================
Network layer hardened per Senior Video Streaming Engineer requirements:
  1. Strict 200/206 + signature validation only. No forced approvals.
  2. No Range headers on GET — HLS text servers reject them.
  3. normalize_url preserves query parameters (auth tokens intact).
  4. _verify_signature distinguishes HLS text vs TS binary via Content-Type.
================================================================================
"""

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse, urlunparse

import aiohttp

# =============================================================================
# 0. CONFIGURATION
# =============================================================================

MAX_STREAMS_PER_CHANNEL = 3
REQUEST_TIMEOUT = 8
FETCH_TIMEOUT = 35
HEAD_TIMEOUT = 5
MAX_CONCURRENT_VALIDATIONS = 60
MAX_CONCURRENT_FETCHES = 20
MAX_DYNAMIC_CHANNELS = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
}

NEGATIVE_KEYWORDS = [
    "telugu", "marathi", "tamil", "kannada", "malayalam", "gujarati",
    "punjabi", "odia", "oriya", "assamese", "nepali", "sinhala", "urdu",
    "bhojpuri", "rajasthani", "haryanvi", "chhattisgarhi", "maithili",
    "sanskrit", "konkani", "tulu", "kashmiri", "dogri", "sindhi",
    "bodo", "santhali", "meitei", "mizo", "khasi", "garo", "tripuri",
    "naga", "manipuri", "andhra", "kerala", "karnataka", "maharashtra",
]

# =============================================================================
# 1. DATA STRUCTURES
# =============================================================================

@dataclass
class M3UEntry:
    name: str
    url: str
    tvg_name: Optional[str] = None
    tvg_language: Optional[str] = None
    tvg_country: Optional[str] = None
    group_title: Optional[str] = None
    source_url: str = ""
    source_bonus: int = 0


@dataclass
class StreamCandidate:
    url: str
    source_bonus: int = 0
    tier: str = "UNVERIFIED"
    confidence: float = 0.0
    found_name: str = ""


@dataclass
class ValidationResult:
    url: str
    is_valid: bool = False
    ttfb_ms: float = 0.0
    speed_kbps: float = 0.0
    content_type: str = ""
    signature_valid: bool = False
    score: float = 0.0
    error: str = ""
    tier: str = "UNVERIFIED"


# =============================================================================
# 2. DEFAULT CHANNEL DEFINITIONS
# =============================================================================

DEFAULT_CHANNELS = [
    {
        "canonical": "Star Jalsha",
        "display_name": "Star Jalsha",
        "logo_url": "",
        "category": "entertainment",
        "language": ["Bengali"],
        "position": 1,
        "manual_urls": [],
        "search_terms": ["star jalsha", "starjalsha", "jalsha hd"],
        "url_hints": ["jalsha", "starjalsha"],
        "exclude_terms": ["star jalsha movies", "jalsha movies", "jalsha cinema", "josh", "jalsa"]
    },
    {
        "canonical": "Jalsha Movies",
        "display_name": "Jalsha Movies",
        "logo_url": "",
        "category": "entertainment",
        "language": ["Bengali"],
        "position": 2,
        "manual_urls": [],
        "search_terms": ["jalsha movies", "jalshamovies", "star jalsha movies"],
        "url_hints": ["jalsha", "movies"],
        "exclude_terms": ["star jalsha", "jalsha hd", "jalsha tv"]
    },
    {
        "canonical": "Zee Bangla",
        "display_name": "Zee Bangla",
        "logo_url": "",
        "category": "entertainment",
        "language": ["Bengali"],
        "position": 3,
        "manual_urls": [],
        "search_terms": ["zee bangla", "zeebangla", "zee bangala"],
        "url_hints": ["zee", "bangla"],
        "exclude_terms": ["zee telugu", "zee marathi", "zee tamil", "zee kannada", "zee malayalam", "zee sarthak", "zee punjabi", "zee cinemalu", "zee thirai", "zee keralam", "zee cinema", "zee classic", "zee action", "zee bollywood", "zee anmol", "zee tv"]
    },
    {
        "canonical": "Zee Bangla Sonar",
        "display_name": "Zee Bangla Sonar",
        "logo_url": "",
        "category": "entertainment",
        "language": ["Bengali"],
        "position": 4,
        "manual_urls": [],
        "search_terms": ["zee bangla sonar", "zeebanglasonar", "zee bangla cinema", "zeebanglacinema"],
        "url_hints": ["zee", "bangla"],
        "exclude_terms": ["zee bangla", "zeebangla", "sonar sansar", "sonar award"]
    },
    {
        "canonical": "Sony Aath",
        "display_name": "Sony Aath",
        "logo_url": "",
        "category": "entertainment",
        "language": ["Bengali"],
        "position": 5,
        "manual_urls": [],
        "search_terms": ["sony aath", "sonyaath", "sony ath", "sony 8", "sony eight"],
        "url_hints": ["sony", "aath"],
        "exclude_terms": ["sony tv", "sony max", "sony pix", "sony sab", "sony ten", "sony six", "sony wah", "sony cricket", "sony sports", "sony yay", "sony bbc", "sony marathi", "sony kal", "sony bengali", "sony bangla", "sony hd", "sony entertainment"]
    },
    {
        "canonical": "Duronto TV",
        "display_name": "Duronto TV",
        "logo_url": "",
        "category": "kids",
        "language": ["Bengali"],
        "position": 6,
        "manual_urls": [],
        "search_terms": ["duronto tv", "durontotv", "duranta tv", "durantatv", "duronto", "duranta"],
        "url_hints": ["duronto", "duranta"],
        "exclude_terms": ["duronto movies", "duronto cinema", "duranta movies"]
    },
    {
        "canonical": "Somoy TV",
        "display_name": "Somoy TV",
        "logo_url": "",
        "category": "news",
        "language": ["Bengali"],
        "position": 7,
        "manual_urls": [],
        "search_terms": ["somoy tv", "somoytv", "somoy", "somoy television", "shomoy", "shomoy tv"],
        "url_hints": ["somoy"],
        "exclude_terms": ["somoy cinema", "somoy movies", "somoy music", "somoy sports"]
    },
    {
        "canonical": "Jamuna TV",
        "display_name": "Jamuna TV",
        "logo_url": "",
        "category": "news",
        "language": ["Bengali"],
        "position": 8,
        "manual_urls": [],
        "search_terms": ["jamuna tv", "jamunatv", "jamuna", "jamuna television"],
        "url_hints": ["jamuna"],
        "exclude_terms": ["jamuna cinema", "jamuna movies", "jamuna sports"]
    },
    {
        "canonical": "NTV News",
        "display_name": "NTV News",
        "logo_url": "",
        "category": "news",
        "language": ["Bengali"],
        "position": 9,
        "manual_urls": [],
        "search_terms": ["ntv bd", "ntv bangladesh", "ntv dhaka", "ntv news", "ntvnews", "ntv channel"],
        "url_hints": ["ntv"],
        "exclude_terms": ["ntv telugu", "ntv kannada", "ntv tamil", "ntv marathi", "ntv malayalam", "ntv hindi", "ntv24", "ntv india", "ntv andhra", "ntv kerala", "ntv gujarat", "ntv punjab", "ntv rajasthan", "ntv bihar", "ntv mp", "ntv up", "ntv haryana", "ntv chhattisgarh", "ntv jharkhand", "ntv odisha", "ntv assam", "ntv north east", "ntv urdu", "ntv bangla", "ntv bengali", "ntv uk", "ntv usa", "ntv europe", "ntv middle east", "ntv australia", "ntv canada", "ntv new zealand"]
    },
    {
        "canonical": "T Sports HD",
        "display_name": "T Sports HD",
        "logo_url": "",
        "category": "sports",
        "language": ["Bengali", "English"],
        "position": 10,
        "manual_urls": [],
        "search_terms": ["t sports", "tsports", "t sport", "tsport", "t-sports", "t-sport"],
        "url_hints": ["tsports", "t-sports", "t_sports"],
        "exclude_terms": ["t sports india", "t sports uk", "t sports usa", "t sports europe", "t sports cricket", "t sports football", "t series", "t-series"]
    },
    {
        "canonical": "Nickelodeon",
        "display_name": "Nickelodeon",
        "logo_url": "",
        "category": "kids",
        "language": ["Bengali", "English"],
        "position": 11,
        "manual_urls": [],
        "search_terms": ["nickelodeon", "nick", "nick hd"],
        "url_hints": ["nick"],
        "exclude_terms": ["nickelodeon hindi", "nickelodeon tamil", "nickelodeon telugu", "nickelodeon marathi", "nickelodeon kannada", "nickelodeon malayalam", "nickelodeon gujarati", "nickelodeon punjabi", "nickelodeon urdu", "nickelodeon odia", "nickelodeon assamese", "nickelodeon nepali", "nickelodeon sri lanka", "nickelodeon pakistan", "nickelodeon afghanistan", "nickelodeon arab", "nick jr hindi", "nick jr tamil", "nick jr telugu", "nick jr marathi", "nick jr kannada", "nick jr malayalam", "nick jr gujarati", "nick jr punjabi", "nick jr urdu", "nick jr odia", "nick jr assamese", "nick jr nepali", "nick jr sri lanka", "nick jr pakistan", "nick jr afghanistan", "nicktoons", "teen nick", "nick at nite"]
    },
    {
        "canonical": "Sony YAY!",
        "display_name": "Sony YAY!",
        "logo_url": "",
        "category": "kids",
        "language": ["Bengali", "English"],
        "position": 12,
        "manual_urls": [],
        "search_terms": ["sony yay", "sonyyay", "sony yay!", "sony yay bangla", "sony yay bengali"],
        "url_hints": ["sony", "yay"],
        "exclude_terms": ["sony yay hindi", "sony yay tamil", "sony yay telugu", "sony yay marathi", "sony yay kannada", "sony yay malayalam", "sony yay gujarati", "sony yay punjabi", "sony yay urdu", "sony yay odia", "sony yay assamese", "sony yay nepali", "sony yay sri lanka", "sony yay pakistan", "sony yay afghanistan", "sony yay english", "sony yay jr", "sony yay junior"]
    },
    {
        "canonical": "Sonic",
        "display_name": "Sonic",
        "logo_url": "",
        "category": "kids",
        "language": ["Bengali", "English", "Hindi"],
        "position": 13,
        "manual_urls": [],
        "search_terms": ["sonic", "sonic tv", "sonictv", "nickelodeon sonic"],
        "url_hints": ["sonic"],
        "exclude_terms": ["sonic hindi", "sonic tamil", "sonic telugu", "sonic marathi", "sonic kannada", "sonic malayalam", "sonic gujarati", "sonic punjabi", "sonic urdu", "sonic odia", "sonic assamese", "sonic nepali", "sonic sri lanka", "sonic pakistan", "sonic afghanistan", "sonicview", "panasonic", "sonic boom", "sonic the hedgehog"]
    },
    {
        "canonical": "Sony BBC Earth",
        "display_name": "Sony BBC Earth",
        "logo_url": "",
        "category": "entertainment",
        "language": ["English"],
        "position": 14,
        "manual_urls": [],
        "search_terms": ["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
        "url_hints": ["bbc", "earth"],
        "exclude_terms": ["sony bbc earth hindi", "sony bbc earth tamil", "sony bbc earth telugu", "sony bbc earth marathi", "sony bbc earth kannada", "sony bbc earth malayalam", "sony bbc earth gujarati", "sony bbc earth punjabi", "sony bbc earth urdu", "sony bbc earth odia", "sony bbc earth assamese", "sony bbc earth nepali", "sony bbc earth sri lanka", "sony bbc earth pakistan", "sony bbc earth afghanistan", "sony bbc earth bangla", "sony bbc earth bengali", "bbc earth india", "bbc earth uk", "bbc earth usa", "bbc earth asia", "bbc earth europe"]
    },
]

# =============================================================================
# 3. SOURCE DEFINITIONS
# =============================================================================

DEFAULT_SOURCES = [
    {"name": "iptv-org-bd", "url": "https://iptv-org.github.io/iptv/countries/bd.m3u", "bonus": 50},
    {"name": "iptv-org-in", "url": "https://iptv-org.github.io/iptv/countries/in.m3u", "bonus": 50},
    {"name": "iptv-org-uk", "url": "https://iptv-org.github.io/iptv/countries/uk.m3u", "bonus": 15},
    {"name": "iptv-org-us", "url": "https://iptv-org.github.io/iptv/countries/us.m3u", "bonus": 15},
    {"name": "iptv-org-entertainment", "url": "https://iptv-org.github.io/iptv/categories/entertainment.m3u", "bonus": 10},
    {"name": "iptv-org-movies", "url": "https://iptv-org.github.io/iptv/categories/movies.m3u", "bonus": 10},
    {"name": "iptv-org-kids", "url": "https://iptv-org.github.io/iptv/categories/kids.m3u", "bonus": 10},
    {"name": "iptv-org-animation", "url": "https://iptv-org.github.io/iptv/categories/animation.m3u", "bonus": 10},
    {"name": "iptv-org-news", "url": "https://iptv-org.github.io/iptv/categories/news.m3u", "bonus": 10},
    {"name": "iptv-org-sports", "url": "https://iptv-org.github.io/iptv/categories/sports.m3u", "bonus": 10},
    {"name": "iptv-org-master", "url": "https://iptv-org.github.io/iptv/index.m3u", "bonus": 5},
    {"name": "bdiptv-shadman", "url": "https://raw.githubusercontent.com/Shadmanislam/bdiptv/master/BD%20IPTV.m3u", "bonus": 40},
    {"name": "bdiptv-mrgify", "url": "https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/main/playlist.m3u", "bonus": 40},
    {"name": "tvlink", "url": "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8", "bonus": 5},
]

# =============================================================================
# 4. M3U PARSING
# =============================================================================

def clean_channel_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'<.*?>', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str, source_url: str, source_bonus: int = 0) -> List[M3UEntry]:
    lines = content.splitlines()
    entries: List[M3UEntry] = []
    current_extinf = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            current_extinf = line
        elif not line.startswith("#") and line.startswith("http"):
            if current_extinf:
                entry = _parse_extinf(current_extinf, line, source_url, source_bonus)
                if entry:
                    entries.append(entry)
            current_extinf = ""
    return entries


def _parse_extinf(extinf_line: str, url: str, source_url: str, source_bonus: int) -> Optional[M3UEntry]:
    tvg_name = _extract_attr(extinf_line, 'tvg-name')
    tvg_language = _extract_attr(extinf_line, 'tvg-language')
    tvg_country = _extract_attr(extinf_line, 'tvg-country')
    group_title = _extract_attr(extinf_line, 'group-title')

    display_name = ""
    if "," in extinf_line:
        display_name = clean_channel_name(extinf_line.split(",")[-1])

    final_name = tvg_name if tvg_name else display_name
    if not final_name:
        return None

    return M3UEntry(
        name=final_name, url=url.strip(),
        tvg_name=tvg_name, tvg_language=tvg_language,
        tvg_country=tvg_country, group_title=group_title,
        source_url=source_url, source_bonus=source_bonus,
    )


def _extract_attr(line: str, attr: str) -> Optional[str]:
    pattern = rf'{attr}="([^"]*)"'
    match = re.search(pattern, line, re.IGNORECASE)
    return match.group(1).strip() if match else None


# =============================================================================
# 5. MATCHING ENGINE
# =============================================================================

def score_match(entry: M3UEntry, ch: Dict) -> float:
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)
    url_lower = entry.url.lower()
    group_lower = (entry.group_title or "").lower()

    for exc in ch.get("exclude_terms", []):
        flat_exc = re.sub(r'[^a-z0-9]', '', exc.lower().strip())
        if flat_exc in flat_name or flat_exc == flat_name:
            return 0.0
        if exc.lower() in group_lower:
            return 0.0

    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return 0.0

    score = 0.0
    matched = False

    for term in ch.get("search_terms", []):
        flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
        if flat_term == flat_name:
            score += 1.0
            matched = True
            break
        elif flat_term in flat_name:
            score += 0.7
            matched = True
            break

    if not matched:
        for name in [ch["canonical"], ch.get("display_name", "")]:
            flat_n = re.sub(r'[^a-z0-9]', '', name.lower().strip())
            if flat_n == flat_name:
                score += 0.9
                matched = True
                break
            elif flat_n in flat_name:
                score += 0.5
                matched = True
                break

    if not matched:
        return 0.0

    for hint in ch.get("url_hints", []):
        if hint.lower() in url_lower:
            score += 0.15
            break

    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        ch_langs = [l.lower() for l in ch.get("language", [])]
        if any(l in lang_lower for l in ch_langs):
            score += 0.1

    if entry.tvg_country:
        country = entry.tvg_country.upper().strip()
        if country in {"BD", "IN"}:
            score += 0.05

    return score


# =============================================================================
# 6. URL NORMALIZATION (HARDENED: preserves query parameters)
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize URL for deduplication WITHOUT stripping query parameters.
    Auth tokens (?source=, ?token=, ?ref=) are preserved. Only scheme and
    netloc are lowercased; path, query, and fragment remain untouched."""
    try:
        parsed = urlparse(url)
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,           # preserved exactly
            parsed.params,         # preserved exactly
            parsed.query,          # preserved exactly — auth tokens kept
            parsed.fragment,       # preserved exactly
        ))
    except Exception:
        return url


# =============================================================================
# 7. SIGNATURE VERIFICATION (HARDENED: Content-Type aware)
# =============================================================================

def _verify_signature(chunk: bytes, url: str, content_type: str = "") -> bool:
    """Verify stream signature. Distinguishes HLS text manifests from binary TS.

    Rules:
      - If Content-Type declares mpegurl, validate as HLS text: MUST contain
        #EXTM3U. HTML disguised as mpegurl is rejected.
      - .ts / video/mp2t → binary MPEG-TS sync byte 0x47 check.
      - .mp4 → ftyp/moov box check.
      - HTML responses → hard reject.
    """
    if not chunk:
        return False

    ct_lower = content_type.lower()
    url_lower = url.lower()

    # HLS text manifest — Content-Type or URL extension says m3u8
    if any(m in ct_lower for m in ["mpegurl", "x-mpegurl", "vnd.apple.mpegurl"]) or ".m3u8" in url_lower:
        text = chunk[:1024].decode("utf-8", errors="ignore")
        stripped = text.strip()
        if stripped.startswith("#EXTM3U") or "#EXTM3U" in stripped[:200]:
            return True
        # If it looks like HTML despite the content-type, reject
        lower_text = stripped.lower()
        if "<html" in lower_text or "<!doctype" in lower_text or "<body" in lower_text:
            return False
        return False

    # MPEG-TS binary stream
    if "mp2t" in ct_lower or "video/mp2t" in ct_lower or url_lower.endswith(".ts") or ".ts?" in url_lower:
        for i in range(min(376, len(chunk))):
            if chunk[i] == 0x47:
                return True
        return False

    # MP4
    if "mp4" in ct_lower or url_lower.endswith(".mp4"):
        return b"ftyp" in chunk[:200] or b"moov" in chunk[:200]

    # Generic fallback — try HLS text first
    try:
        text = chunk[:1024].decode("utf-8", errors="ignore")
        stripped = text.strip()
        if stripped.startswith("#EXTM3U") or "#EXTM3U" in stripped[:200]:
            return True
    except Exception:
        pass

    # Generic fallback — MPEG-TS sync byte
    for i in range(min(400, len(chunk))):
        if chunk[i] == 0x47:
            return True

    # Hard reject obvious HTML
    try:
        text = chunk[:512].decode("utf-8", errors="ignore").lower()
        if "<html" in text or "<!doctype" in text or "<body" in text:
            return False
    except Exception:
        pass

    return False


# =============================================================================
# 8. VALIDATION (HARDENED: strict 200/206, no Range header, no forced approvals)
# =============================================================================

async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    source_bonus: int = 0,
    tier: str = "UNVERIFIED"
) -> ValidationResult:
    """Strict validation: ONLY HTTP 200/206 + passing signature = valid.

    No forced approvals on 403, timeout, or any other error condition.
    Range headers are NOT used — HLS text servers reject them on manifests.
    """
    async with semaphore:
        start_time = time.monotonic()
        result = ValidationResult(url=url, tier=tier)

        # --- HEAD probe (informational only, does NOT set is_valid) ---
        try:
            head_timeout = aiohttp.ClientTimeout(total=HEAD_TIMEOUT, sock_connect=3, sock_read=3)
            async with session.head(url, headers=HEADERS, timeout=head_timeout,
                                    allow_redirects=True, ssl=False) as resp:
                ct = resp.headers.get("Content-Type", "").lower()
                result.content_type = ct
                if resp.status not in (200, 301, 302, 307, 308):
                    result.error = f"HEAD {resp.status}"
        except Exception as e:
            result.error = f"HEAD fail: {str(e)[:30]}"

        # --- GET probe (strict: must be 200 or 206) ---
        try:
            get_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=4, sock_read=5)
            # NO Range header — let aiohttp read the natural first chunk
            async with session.get(url, headers=HEADERS, timeout=get_timeout,
                                   allow_redirects=True, ssl=False) as resp:
                if resp.status not in (200, 206):
                    result.error = f"GET {resp.status}"
                    return result

                chunk = await resp.content.read(4096)
                if not chunk:
                    result.error = "Empty body"
                    return result

                ct = resp.headers.get("Content-Type", result.content_type).lower()
                result.content_type = ct

                if not _verify_signature(chunk, url, ct):
                    result.error = "Bad signature"
                    return result

                result.signature_valid = True
                result.ttfb_ms = (time.monotonic() - start_time) * 1000
                elapsed = time.monotonic() - start_time
                if elapsed > 0:
                    result.speed_kbps = (len(chunk) / 1024) / elapsed

                ttfb_score = max(0, 1500 - result.ttfb_ms) / 15
                speed_score = min(result.speed_kbps * 5, 50)
                result.score = ttfb_score + speed_score + source_bonus
                result.is_valid = True

        except asyncio.TimeoutError:
            result.error = "Timeout"
        except Exception as e:
            result.error = f"Err:{str(e)[:40]}"

        return result


# =============================================================================
# 9. NETWORK
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str, timeout: int = FETCH_TIMEOUT) -> str:
    async with session.get(url, headers=HEADERS,
                           timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        resp.raise_for_status()
        return await resp.text()


# =============================================================================
# 10. M3U WRITING (CLEAN)
# =============================================================================

def escape_m3u_attr(value: str) -> str:
    return value.replace('"', '\\"')


def write_m3u_entry(f, channel_name: str, category: str, result: ValidationResult) -> None:
    safe_name = escape_m3u_attr(channel_name)
    safe_group = escape_m3u_attr(category.capitalize())
    f.write(f'#EXTINF:-1 tvg-name="{safe_name}" group-title="{safe_group}",{safe_name}\n')
    f.write(f'{result.url}\n')


# =============================================================================
# 11. MAIN ORCHESTRATION
# =============================================================================

async def main() -> None:
    print("=" * 60)
    print("FORTRESS v5.2 — Hardened Network Layer")
    print("=" * 60)
    start_time = time.monotonic()

    try:
        with open("fixed_channels.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        fixed_channels = config.get("channels", [])
        general_sources = config.get("general_sources", [])
        print(f"[INFO] Loaded fixed_channels.json: {len(fixed_channels)} channels, {len(general_sources)} sources")
    except FileNotFoundError:
        print("[WARN] fixed_channels.json not found — using defaults")
        fixed_channels = DEFAULT_CHANNELS
        general_sources = DEFAULT_SOURCES
    except json.JSONDecodeError as e:
        print(f"[WARN] Invalid fixed_channels.json — using defaults. Error: {e}")
        fixed_channels = DEFAULT_CHANNELS
        general_sources = DEFAULT_SOURCES

    if not fixed_channels:
        print("[WARN] No channels defined — using defaults")
        fixed_channels = DEFAULT_CHANNELS

    if not general_sources:
        general_sources = DEFAULT_SOURCES

    source_url_map = {s["name"]: s["url"] for s in general_sources}
    source_bonus_map = {s["name"]: s.get("reliability_bonus", s.get("bonus", 0)) for s in general_sources}

    all_source_names = set()
    for ch in fixed_channels:
        for gs in ch.get("golden_sources", []):
            if gs["source_name"] in source_url_map:
                all_source_names.add(gs["source_name"])
    for s in general_sources:
        all_source_names.add(s["name"])

    print(f"[INFO] Will fetch {len(all_source_names)} unique sources")

    validation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    connector = aiohttp.TCPConnector(
        limit=120, limit_per_host=40, ttl_dns_cache=300,
        use_dns_cache=True, enable_cleanup_closed=True, force_close=False,
    )

    async with aiohttp.ClientSession(connector=connector) as session:

        # =====================================================================
        # PHASE 1: FETCH ALL SOURCES ONCE
        # =====================================================================
        print(f"\n[INFO] Phase 1: Fetching {len(all_source_names)} sources...", flush=True)

        async def fetch_one(name: str) -> Tuple[str, str]:
            async with fetch_semaphore:
                url = source_url_map.get(name, "")
                if not url:
                    return (name, "")
                try:
                    content = await fetch_source(session, url)
                    return (name, content)
                except Exception as e:
                    print(f"  [WARN] {name}: {str(e)[:60]}", flush=True)
                    return (name, "")

        fetch_tasks = [fetch_one(name) for name in all_source_names]
        fetched_data = {name: content for name, content in await asyncio.gather(*fetch_tasks)}

        successful = sum(1 for c in fetched_data.values() if c)
        print(f"[INFO] {successful}/{len(all_source_names)} sources fetched successfully")

        # =====================================================================
        # PHASE 2: PARSE ALL ENTRIES INTO ONE POOL
        # =====================================================================
        print(f"[INFO] Phase 2: Parsing entries...", flush=True)
        all_entries: List[M3UEntry] = []

        for src_name, content in fetched_data.items():
            if not content:
                continue
            bonus = source_bonus_map.get(src_name, 0)
            url = source_url_map.get(src_name, "")
            entries = parse_m3u(content, url, bonus)
            all_entries.extend(entries)

        print(f"[INFO] Parsed {len(all_entries)} total entries")

        # =====================================================================
        # PHASE 3: MATCH ALL CHANNELS — COLLECT CANDIDATES
        # =====================================================================
        print(f"[INFO] Phase 3: Matching {len(fixed_channels)} channels...", flush=True)

        candidates: Dict[str, List[StreamCandidate]] = {ch["canonical"]: [] for ch in fixed_channels}

        # 3A: PLATINUM — manual URLs
        for ch in fixed_channels:
            canonical = ch["canonical"]
            for url in ch.get("manual_urls", []):
                if url.strip():
                    candidates[canonical].append(StreamCandidate(
                        url=url.strip(), source_bonus=100, tier="PLATINUM",
                        confidence=1.0, found_name="manual"
                    ))

        # 3B: GOLDEN + SILVER — match from parsed pool
        for entry in all_entries:
            for ch in fixed_channels:
                canonical = ch["canonical"]
                score = score_match(entry, ch)
                if score >= 0.5:
                    tier = "GOLD" if score >= 0.9 else "SILVER"
                    candidates[canonical].append(StreamCandidate(
                        url=entry.url, source_bonus=entry.source_bonus,
                        tier=tier, confidence=score, found_name=entry.name
                    ))

        total_candidates = 0
        for canonical in candidates:
            seen = set()
            deduped = []
            for cand in candidates[canonical]:
                norm = normalize_url(cand.url)
                if norm not in seen:
                    seen.add(norm)
                    deduped.append(cand)
            tier_order = {"PLATINUM": 0, "GOLD": 1, "SILVER": 2, "UNVERIFIED": 3}
            deduped.sort(key=lambda x: (tier_order.get(x.tier, 99), -x.confidence))
            candidates[canonical] = deduped[:15]
            total_candidates += len(candidates[canonical])
            if candidates[canonical]:
                print(f"  {canonical}: {len(candidates[canonical])} candidates "
                      f"({candidates[canonical][0].tier}, conf={candidates[canonical][0].confidence:.2f})", flush=True)

        print(f"[INFO] {total_candidates} total candidates collected")

        # =====================================================================
        # PHASE 4: BATCH VALIDATE ALL CANDIDATES
        # =====================================================================
        print(f"[INFO] Phase 4: Validating {total_candidates} URLs...", flush=True)

        validate_tasks = []
        validate_meta = []
        for canonical, cands in candidates.items():
            for cand in cands:
                validate_tasks.append(
                    validate_url(session, cand.url, validation_semaphore,
                                 cand.source_bonus, cand.tier)
                )
                validate_meta.append((canonical, cand))

        discovered: Dict[str, List[ValidationResult]] = {ch["canonical"]: [] for ch in fixed_channels}

        if validate_tasks:
            batch_size = 60
            for i in range(0, len(validate_tasks), batch_size):
                batch_tasks = validate_tasks[i:i+batch_size]
                batch_meta = validate_meta[i:i+batch_size]
                results = await asyncio.gather(*batch_tasks)
                for (canonical, cand), result in zip(batch_meta, results):
                    if result.is_valid:
                        discovered[canonical].append(result)
                print(f"  Batch {i//batch_size + 1}/{(len(validate_tasks)-1)//batch_size + 1} done", flush=True)

        for ch in fixed_channels:
            canonical = ch["canonical"]
            if discovered[canonical]:
                tier = discovered[canonical][0].tier
                print(f"  [{tier}] {canonical}: {len(discovered[canonical])} working streams", flush=True)
            else:
                print(f"  [OFFLINE] {canonical}: no working streams found", flush=True)

        # =====================================================================
        # PHASE 5: DYNAMIC BONUS CHANNELS
        # =====================================================================
        print(f"\n[INFO] Phase 5: Dynamic bonus channels (max {MAX_DYNAMIC_CHANNELS})...", flush=True)

        fixed_canonicals = {ch["canonical"] for ch in fixed_channels}
        dynamic_candidates: Dict[str, List[StreamCandidate]] = {}

        known_bonus = {
            "Gazi TV": {"search": ["gazi tv", "gazitv", "gtv"], "cat": "sports", "lang": ["Bengali"]},
            "Channel i": {"search": ["channel i", "channeli"], "cat": "news", "lang": ["Bengali"]},
            "Independent TV": {"search": ["independent tv", "independenttv"], "cat": "news", "lang": ["Bengali"]},
            "Banglavision": {"search": ["banglavision", "bangla vision"], "cat": "news", "lang": ["Bengali"]},
            "Ekattor TV": {"search": ["ekattor tv", "ekattortv"], "cat": "news", "lang": ["Bengali"]},
            "DBC News": {"search": ["dbc news", "dbcnews"], "cat": "news", "lang": ["Bengali"]},
            "News24": {"search": ["news24 bd", "news24 bangladesh"], "cat": "news", "lang": ["Bengali"]},
            "Maasranga TV": {"search": ["maasranga tv", "maasrangatv"], "cat": "news", "lang": ["Bengali"]},
            "Asian TV": {"search": ["asian tv", "asiantv"], "cat": "news", "lang": ["Bengali"]},
            "Channel 9": {"search": ["channel 9", "channel9"], "cat": "entertainment", "lang": ["Bengali"]},
            "Boishakhi TV": {"search": ["boishakhi tv", "boishakhitv"], "cat": "entertainment", "lang": ["Bengali"]},
            "Mohona TV": {"search": ["mohona tv", "mohonatv"], "cat": "entertainment", "lang": ["Bengali"]},
            "My TV": {"search": ["my tv", "mytv"], "cat": "entertainment", "lang": ["Bengali"]},
            "Nagorik TV": {"search": ["nagorik tv", "nagoriktv"], "cat": "entertainment", "lang": ["Bengali"]},
            "RTV": {"search": ["rtv bd", "rtv bangladesh"], "cat": "entertainment", "lang": ["Bengali"]},
            "Colors Bangla": {"search": ["colors bangla", "colorsbangla"], "cat": "entertainment", "lang": ["Bengali"]},
            "Enterr10 Bangla": {"search": ["enterr10 bangla", "enterr10bangla"], "cat": "entertainment", "lang": ["Bengali"]},
            "Akash Aath": {"search": ["akash aath", "akashaath"], "cat": "entertainment", "lang": ["Bengali"]},
            "Bijoy TV": {"search": ["bijoy tv", "bijoytv"], "cat": "entertainment", "lang": ["Bengali"]},
            "Bangla TV": {"search": ["bangla tv", "banglatv"], "cat": "entertainment", "lang": ["Bengali"]},
            "Cartoon Network": {"search": ["cartoon network", "cartoonnetwork"], "cat": "kids", "lang": ["English"]},
            "Pogo": {"search": ["pogo", "pogo tv"], "cat": "kids", "lang": ["English", "Hindi"]},
            "Disney Channel": {"search": ["disney channel", "disneychannel"], "cat": "kids", "lang": ["English"]},
            "Gopal Bhar TV": {"search": ["gopal bhar", "gopalbhar"], "cat": "kids", "lang": ["Bengali"]},
            "Motu Patlu": {"search": ["motu patlu", "motupatlu"], "cat": "kids", "lang": ["Bengali", "Hindi"]},
            "Sony Max": {"search": ["sony max", "sonymax"], "cat": "movies", "lang": ["English", "Hindi"]},
            "Sony Pix": {"search": ["sony pix", "sonypix"], "cat": "movies", "lang": ["English"]},
            "HBO": {"search": ["hbo"], "cat": "movies", "lang": ["English"]},
            "Star Movies": {"search": ["star movies", "starmovies"], "cat": "movies", "lang": ["English"]},
            "Discovery": {"search": ["discovery", "discovery channel"], "cat": "movies", "lang": ["English"]},
            "National Geographic": {"search": ["national geographic", "nat geo", "natgeo"], "cat": "movies", "lang": ["English"]},
            "BBC World News": {"search": ["bbc world", "bbc world news", "bbc news"], "cat": "news", "lang": ["English"]},
            "Star Sports 1": {"search": ["star sports 1", "starsports1"], "cat": "sports", "lang": ["English"]},
        }

        for entry in all_entries:
            normalized = entry.name.lower().strip()
            flat_name = re.sub(r'[^a-z0-9]', '', normalized)
            group_lower = (entry.group_title or "").lower()

            skip = False
            for ch in fixed_channels:
                for term in ch.get("search_terms", []):
                    flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
                    if flat_term in flat_name:
                        skip = True
                        break
                if skip:
                    break
            if skip:
                continue

            for neg in NEGATIVE_KEYWORDS:
                if neg in normalized or neg in group_lower:
                    continue

            for bonus_name, bonus_config in known_bonus.items():
                if bonus_name in dynamic_candidates and len(dynamic_candidates[bonus_name]) >= 5:
                    continue
                for search_term in bonus_config["search"]:
                    flat_search = re.sub(r'[^a-z0-9]', '', search_term.lower().strip())
                    if flat_search in flat_name or flat_search == flat_name:
                        if bonus_name not in dynamic_candidates:
                            dynamic_candidates[bonus_name] = []
                        dynamic_candidates[bonus_name].append(StreamCandidate(
                            url=entry.url, source_bonus=entry.source_bonus,
                            tier="DYNAMIC", confidence=0.8, found_name=entry.name
                        ))
                        break

        for name in list(dynamic_candidates.keys()):
            seen = set()
            deduped = []
            for cand in dynamic_candidates[name]:
                norm = normalize_url(cand.url)
                if norm not in seen:
                    seen.add(norm)
                    deduped.append(cand)
            dynamic_candidates[name] = deduped[:5]

        if len(dynamic_candidates) > MAX_DYNAMIC_CHANNELS:
            sorted_names = sorted(dynamic_candidates.keys(), key=lambda n: len(dynamic_candidates[n]), reverse=True)
            dynamic_candidates = {n: dynamic_candidates[n] for n in sorted_names[:MAX_DYNAMIC_CHANNELS]}

        dynamic_discovered: Dict[str, List[ValidationResult]] = {}
        dyn_tasks = []
        dyn_meta = []
        for name, cands in dynamic_candidates.items():
            for cand in cands:
                dyn_tasks.append(validate_url(session, cand.url, validation_semaphore, cand.source_bonus, "DYNAMIC"))
                dyn_meta.append((name, cand))

        if dyn_tasks:
            batch_size = 60
            for i in range(0, len(dyn_tasks), batch_size):
                batch = dyn_tasks[i:i+batch_size]
                batch_m = dyn_meta[i:i+batch_size]
                results = await asyncio.gather(*batch)
                for (name, cand), result in zip(batch_m, results):
                    if result.is_valid:
                        if name not in dynamic_discovered:
                            dynamic_discovered[name] = []
                        dynamic_discovered[name].append(result)

        # =====================================================================
        # PHASE 6: Rank and trim
        # =====================================================================
        print(f"\n[INFO] Phase 6: Ranking streams...", flush=True)
        for canonical in discovered:
            if len(discovered[canonical]) > 1:
                discovered[canonical].sort(key=lambda x: x.score, reverse=True)
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        for name in dynamic_discovered:
            if len(dynamic_discovered[name]) > 1:
                dynamic_discovered[name].sort(key=lambda x: x.score, reverse=True)
            if len(dynamic_discovered[name]) > MAX_STREAMS_PER_CHANNEL:
                dynamic_discovered[name] = dynamic_discovered[name][:MAX_STREAMS_PER_CHANNEL]

        # =====================================================================
        # PHASE 7: Generate outputs
        # =====================================================================
        print(f"[INFO] Phase 7: Writing output files...", flush=True)

        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fixed_total": len(fixed_channels),
            "fixed_working": sum(1 for c in fixed_channels if discovered[c["canonical"]]),
            "dynamic_total": len(dynamic_discovered),
            "dynamic_working": sum(1 for v in dynamic_discovered.values() if v),
            "fixed_channels": [],
            "dynamic_channels": [],
        }

        for ch in fixed_channels:
            canonical = ch["canonical"]
            streams = discovered[canonical]
            best_tier = streams[0].tier if streams else "OFFLINE"

            output["fixed_channels"].append({
                "canonical": canonical,
                "display_name": ch.get("display_name", canonical),
                "logo_url": ch.get("logo_url", ""),
                "category": ch.get("category", "entertainment"),
                "language": ch.get("language", []),
                "position": ch.get("position", 999),
                "tier": best_tier,
                "status": "online" if streams else "offline",
                "stream_count": len(streams),
                "streams": [
                    {
                        "url": r.url,
                        "tier": r.tier,
                        "score": round(r.score, 2),
                        "ttfb_ms": round(r.ttfb_ms, 2),
                        "speed_kbps": round(r.speed_kbps, 2),
                        "is_primary": i == 0,
                    }
                    for i, r in enumerate(streams)
                ]
            })

        output["fixed_channels"].sort(key=lambda x: x["position"])

        for name, streams in sorted(dynamic_discovered.items()):
            if streams:
                bc = known_bonus.get(name, {})
                output["dynamic_channels"].append({
                    "canonical": name,
                    "display_name": name,
                    "logo_url": "",
                    "category": bc.get("cat", "entertainment"),
                    "language": bc.get("lang", ["Bengali"]),
                    "tier": streams[0].tier,
                    "status": "online",
                    "stream_count": len(streams),
                    "streams": [
                        {
                            "url": r.url,
                            "tier": r.tier,
                            "score": round(r.score, 2),
                            "ttfb_ms": round(r.ttfb_ms, 2),
                            "speed_kbps": round(r.speed_kbps, 2),
                            "is_primary": i == 0,
                        }
                        for i, r in enumerate(streams)
                    ]
                })

        with open("channels.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                for r in discovered[ch["canonical"]]:
                    write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_discovered.items()):
                for r in streams:
                    bc = known_bonus.get(name, {})
                    write_m3u_entry(f, name, bc.get("cat", "entertainment"), r)

        with open("bengali.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if "Bengali" in ch.get("language", []) or "Bangla" in ch.get("language", []):
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_discovered.items()):
                bc = known_bonus.get(name, {})
                if "Bengali" in bc.get("lang", []) or "Bangla" in bc.get("lang", []):
                    for r in streams:
                        write_m3u_entry(f, name, bc.get("cat", "entertainment"), r)

        with open("english.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                langs = ch.get("language", [])
                if "English" in langs and "Bengali" not in langs and "Bangla" not in langs:
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_discovered.items()):
                bc = known_bonus.get(name, {})
                langs = bc.get("lang", [])
                if "English" in langs and "Bengali" not in langs and "Bangla" not in langs:
                    for r in streams:
                        write_m3u_entry(f, name, bc.get("cat", "entertainment"), r)

        with open("kids.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "kids":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "Kids", r)
            for name, streams in sorted(dynamic_discovered.items()):
                if known_bonus.get(name, {}).get("cat") == "kids":
                    for r in streams:
                        write_m3u_entry(f, name, "Kids", r)

        with open("news.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "news":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "News", r)
            for name, streams in sorted(dynamic_discovered.items()):
                if known_bonus.get(name, {}).get("cat") == "news":
                    for r in streams:
                        write_m3u_entry(f, name, "News", r)

        with open("sports.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "sports":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "Sports", r)
            for name, streams in sorted(dynamic_discovered.items()):
                if known_bonus.get(name, {}).get("cat") == "sports":
                    for r in streams:
                        write_m3u_entry(f, name, "Sports", r)

        health = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fixed_channels": {},
            "dynamic_channels": {},
        }
        for ch in fixed_channels:
            canonical = ch["canonical"]
            streams = discovered[canonical]
            health["fixed_channels"][canonical] = {
                "tier": streams[0].tier if streams else "OFFLINE",
                "status": "online" if streams else "offline",
                "stream_count": len(streams),
                "urls": [r.url for r in streams],
            }
        for name, streams in dynamic_discovered.items():
            health["dynamic_channels"][name] = {
                "tier": streams[0].tier if streams else "OFFLINE",
                "status": "online" if streams else "offline",
                "stream_count": len(streams),
                "urls": [r.url for r in streams],
            }

        with open("health.json", "w", encoding="utf-8") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)

        elapsed = time.monotonic() - start_time
        fixed_working = sum(1 for c in fixed_channels if discovered[c["canonical"]])
        dynamic_working = sum(1 for v in dynamic_discovered.values() if v)

        platinum = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "PLATINUM")
        gold = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "GOLD")
        silver = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "SILVER")

        print(f"\n{'='*60}")
        print(f"FORTRESS v5.2 HARDENED COMPLETE in {elapsed:.1f}s")
        print(f"{'='*60}")
        print(f"Fixed channels   : {fixed_working}/{len(fixed_channels)}")
        print(f"  PLATINUM       : {platinum}")
        print(f"  GOLD           : {gold}")
        print(f"  SILVER         : {silver}")
        print(f"Dynamic channels : {dynamic_working}/{len(dynamic_discovered)}")
        print(f"Total time       : {elapsed:.1f}s")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
