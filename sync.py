#!/usr/bin/env python3
"""
================================================================================
FORTRESS v4.0 — ZERO-HALLUCINATION IPTV SYNC MACHINE
================================================================================
Architecture: Golden Source Override + 3-Tier Validation + Health Tracking
Language Priority: Bengali (Bangla) > English
Anti-Hallucination: Source-scoped matching, language guards, exclusion vectors,
                    confidence thresholds, signature verification, URL proof
Output: channels.json, playlist.m3u, bengali.m3u, english.m3u, kids.m3u, news.m3u,
        sports.m3u, health.json
================================================================================
"""

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

# =============================================================================
# 0. CONFIGURATION
# =============================================================================

@dataclass
class ChannelProfile:
    """Zero-hallucination confidence profile for each target channel."""
    canonical: str
    primary: List[str] = field(default_factory=list)
    secondary: List[str] = field(default_factory=list)
    tertiary: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    lang_required: List[str] = field(default_factory=list)
    country_preferred: List[str] = field(default_factory=list)
    min_confidence: float = 0.75
    category: str = "entertainment"
    notes: str = ""


# =============================================================================
# 1. CHANNEL TARGETS — Research-Validated Names (15 Premium Channels)
# =============================================================================
# All names verified via Wikipedia, official sources, and JioTV listings

CHANNEL_PROFILES: List[ChannelProfile] = [
    # --- BENGALI ENTERTAINMENT ---
    ChannelProfile("Star Jalsha",
        primary=["star jalsha", "starjalsha"],
        secondary=["star jalsha hd", "jalsha hd", "starjalsha hd"],
        tertiary=["jalsha"],
        exclude=["star jalsha movies", "jalsha movies", "jalsha cinema", "movies jalsha",
                 "star jalsha josh", "jalsha josh", "star jalsa", "jalsa"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment",
        notes="Indian Bengali GEC, owned by JioStar (Disney Star)"),

    ChannelProfile("Jalsha Movies",
        primary=["jalsha movies", "jalshamovies", "star jalsha movies", "starjalshamovies"],
        secondary=["jalsha movies hd", "jalsha cinema", "star jalsha movies hd"],
        tertiary=["jalsha film", "jalsha movie"],
        exclude=["star jalsha", "jalsha hd", "jalsha tv", "jalsha entertainment"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["IN"],
        category="entertainment",
        notes="Bengali movie channel, sister of Star Jalsha, launched Dec 2012"),

    ChannelProfile("Zee Bangla",
        primary=["zee bangla", "zeebangla"],
        secondary=["zee bangla hd", "zeebangla hd", "zee bangala"],
        tertiary=["zeebang"],
        exclude=["zee telugu", "zee marathi", "zee tamil", "zee kannada",
                 "zee malayalam", "zee sarthak", "zee punjabi", "zee cinemalu",
                 "zee thirai", "zee keralam", "zee cinema", "zee classic",
                 "zee action", "zee bollywood", "zee anmol", "zee tv"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment",
        notes="Indian Bengali GEC, owned by Zee Entertainment"),

    ChannelProfile("Zee Bangla Sonar",
        primary=["zee bangla sonar", "zeebanglasonar", "zee bangla cinema", "zeebanglacinema"],
        secondary=["zee bangla sonar hd", "zee bangla cinema hd", "bangla sonar"],
        tertiary=["sonar", "zee sonar"],
        exclude=["zee bangla", "zeebangla", "sonar sansar", "sonar award"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["IN"],
        category="entertainment",
        notes="Bengali movie channel, replaced Zee Bangla Cinema in 2025"),

    ChannelProfile("Sony Aath",
        primary=["sony aath", "sonyaath", "sony ath"],
        secondary=["sony aath hd", "sonyaath hd", "sony 8", "sony eight"],
        tertiary=["aath"],
        exclude=["sony tv", "sony max", "sony pix", "sony sab", "sony ten",
                 "sony six", "sony wah", "sony cricket", "sony sports",
                 "sony yay", "sony bbc", "sony marathi", "sony kal",
                 "sony bengali", "sony bangla", "sony hd", "sony entertainment"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment",
        notes="Indian Bengali GEC, owned by Sony Pictures Networks"),

    ChannelProfile("Duronto TV",
        primary=["duronto tv", "durontotv", "duranta tv", "durantatv"],
        secondary=["duronto", "duranta", "duronto television", "duranta television"],
        tertiary=["duronto kids", "duronto children"],
        exclude=["duronto movies", "duronto cinema", "duranta movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="kids",
        notes="Bangladeshi children's channel, first of its kind in BD, launched Oct 2017"),

    # --- BENGALI NEWS ---
    ChannelProfile("Somoy TV",
        primary=["somoy tv", "somoytv", "somoy television"],
        secondary=["somoy", "somoy news", "somoytv bd"],
        tertiary=["shomoy", "shomoy tv"],
        exclude=["somoy cinema", "somoy movies", "somoy music", "somoy sports"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news",
        notes="Bangladeshi news channel"),

    ChannelProfile("Jamuna TV",
        primary=["jamuna tv", "jamunatv", "jamuna television"],
        secondary=["jamuna", "jamuna news", "jamunatv bd"],
        tertiary=["jamuna channel"],
        exclude=["jamuna cinema", "jamuna movies", "jamuna sports"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news",
        notes="Bangladeshi news channel"),

    ChannelProfile("NTV News",
        primary=["ntv bd", "ntv bangladesh", "ntv dhaka"],
        secondary=["ntv news", "ntvnews", "ntv channel"],
        tertiary=["ntv"],
        exclude=["ntv telugu", "ntv kannada", "ntv tamil", "ntv marathi",
                 "ntv malayalam", "ntv hindi", "ntv24", "ntv india",
                 "ntv andhra", "ntv kerala", "ntv gujarat", "ntv punjab",
                 "ntv rajasthan", "ntv bihar", "ntv mp", "ntv up",
                 "ntv haryana", "ntv chhattisgarh", "ntv jharkhand",
                 "ntv odisha", "ntv assam", "ntv north east", "ntv urdu",
                 "ntv bangla", "ntv bengali", "ntv uk", "ntv usa",
                 "ntv europe", "ntv middle east", "ntv australia",
                 "ntv canada", "ntv new zealand"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news",
        notes="Bangladeshi news channel, NOT to be confused with Indian NTV variants"),

    # --- SPORTS ---
    ChannelProfile("T Sports HD",
        primary=["t sports", "tsports", "t sport", "tsport", "t-sports", "t-sport"],
        secondary=["t sports hd", "tsports hd", "t sport hd", "tsport hd",
                   "t-sports hd", "t-sport hd"],
        tertiary=["ts hd", "t sports channel"],
        exclude=["t sports india", "t sports uk", "t sports usa",
                 "t sports europe", "t sports cricket", "t sports football",
                 "t series", "t-series"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD"],
        category="sports",
        notes="Bangladeshi sports channel"),

    # --- KIDS (Bengali/English) ---
    ChannelProfile("Nickelodeon",
        primary=["nickelodeon", "nick", "nick hd"],
        secondary=["nickelodeon hd", "nick hd plus", "nick india"],
        tertiary=["nick tv", "nick channel"],
        exclude=["nickelodeon hindi", "nickelodeon tamil", "nickelodeon telugu",
                 "nickelodeon marathi", "nickelodeon kannada", "nickelodeon malayalam",
                 "nickelodeon gujarati", "nickelodeon punjabi", "nickelodeon urdu",
                 "nickelodeon odia", "nickelodeon assamese", "nickelodeon nepali",
                 "nickelodeon sri lanka", "nickelodeon pakistan",
                 "nickelodeon afghanistan", "nickelodeon arab",
                 "nickelodeon uk", "nickelodeon usa", "nickelodeon australia",
                 "nick jr hindi", "nick jr tamil", "nick jr telugu",
                 "nick jr marathi", "nick jr kannada", "nick jr malayalam",
                 "nick jr gujarati", "nick jr punjabi", "nick jr urdu",
                 "nick jr odia", "nick jr assamese", "nick jr nepali",
                 "nick jr sri lanka", "nick jr pakistan", "nick jr afghanistan",
                 "nicktoons", "teen nick", "nick at nite"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids",
        notes="Has Bengali audio feed in India"),

    ChannelProfile("Sony YAY!",
        primary=["sony yay", "sonyyay", "sony yay!", "sony yay bangla", "sony yay bengali"],
        secondary=["sony yay hd", "sonyyay hd", "sony yay! hd",
                   "sony yay bangla hd", "sony yay bengali hd"],
        tertiary=["yay", "sony yay channel", "sony yay tv"],
        exclude=["sony yay hindi", "sony yay tamil", "sony yay telugu",
                 "sony yay marathi", "sony yay kannada", "sony yay malayalam",
                 "sony yay gujarati", "sony yay punjabi", "sony yay urdu",
                 "sony yay odia", "sony yay assamese", "sony yay nepali",
                 "sony yay sri lanka", "sony yay pakistan",
                 "sony yay afghanistan", "sony yay english",
                 "sony yay jr", "sony yay junior"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids",
        notes="Has dedicated Bengali feed (Sony YAY! Bangla)"),

    ChannelProfile("Sonic",
        primary=["sonic", "sonic tv", "sonictv", "nickelodeon sonic"],
        secondary=["sonic hd", "sonic nick", "sonic channel", "sonic india"],
        tertiary=["sonic kids", "sonic children"],
        exclude=["sonic hindi", "sonic tamil", "sonic telugu", "sonic marathi",
                 "sonic kannada", "sonic malayalam", "sonic gujarati",
                 "sonic punjabi", "sonic urdu", "sonic odia", "sonic assamese",
                 "sonic nepali", "sonic sri lanka", "sonic pakistan",
                 "sonic afghanistan", "sonicview", "panasonic", "sonic boom",
                 "sonic the hedgehog"],
        lang_required=["Bengali", "Bangla", "English", "Hindi"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids",
        notes="Nickelodeon Sonic India, has Bengali audio"),

    # --- ENGLISH INFOTAINMENT ---
    ChannelProfile("Sony BBC Earth",
        primary=["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
        secondary=["sony bbc earth hd", "bbc earth hd", "sony earth hd"],
        tertiary=["sony bbc channel", "bbc earth channel"],
        exclude=["sony bbc earth hindi", "sony bbc earth tamil",
                 "sony bbc earth telugu", "sony bbc earth marathi",
                 "sony bbc earth kannada", "sony bbc earth malayalam",
                 "sony bbc earth gujarati", "sony bbc earth punjabi",
                 "sony bbc earth urdu", "sony bbc earth odia",
                 "sony bbc earth assamese", "sony bbc earth nepali",
                 "sony bbc earth sri lanka", "sony bbc earth pakistan",
                 "sony bbc earth afghanistan", "sony bbc earth bangla",
                 "sony bbc earth bengali", "bbc earth india", "bbc earth uk",
                 "bbc earth usa", "bbc earth asia", "bbc earth europe"],
        lang_required=["English"],
        country_preferred=["IN", "UK", "US"],
        category="entertainment",
        notes="English-only (Hindi/Tamil/Telugu audio tracks exist, NO Bengali)"),
]

CANONICAL_TO_PROFILE: Dict[str, ChannelProfile] = {p.canonical: p for p in CHANNEL_PROFILES}


# =============================================================================
# 2. GOLDEN SOURCE OVERRIDE SYSTEM
# =============================================================================
# Rather than direct URLs, we define SEARCH LOGIC per channel per source.
# When the source playlist updates, new URLs are auto-discovered.

@dataclass
class GoldenChannelSearch:
    """Search configuration for a specific channel within a Golden Source."""
    search_terms: List[str]              # Terms to match in channel name
    url_must_contain: List[str] = field(default_factory=list)   # URL substrings
    url_must_not_contain: List[str] = field(default_factory=list)  # URL exclusions
    min_name_confidence: float = 0.85   # Higher threshold for Golden sources


@dataclass
class GoldenSource:
    """A curated playlist source with per-channel search logic."""
    name: str
    url: str
    reliability_bonus: int             # Added to stream quality score
    channels: Dict[str, GoldenChannelSearch]  # canonical -> search config


GOLDEN_SOURCES: List[GoldenSource] = [
    GoldenSource(
        name="iptv-org-bd",
        url="https://iptv-org.github.io/iptv/countries/bd.m3u",
        reliability_bonus=50,
        channels={
            "T Sports HD": GoldenChannelSearch(
                search_terms=["T Sports", "TSports", "T-Sports", "t sports", "tsports"],
                url_must_contain=["tsports", "t-sports", "t_sports"],
                url_must_not_contain=["india", "uk", "usa", "europe"],
            ),
            "Somoy TV": GoldenChannelSearch(
                search_terms=["Somoy TV", "SomoyTV", "Somoy", "Shomoy"],
                url_must_contain=["somoy"],
                url_must_not_contain=["cinema", "movies", "music"],
            ),
            "Jamuna TV": GoldenChannelSearch(
                search_terms=["Jamuna TV", "JamunaTV", "Jamuna"],
                url_must_contain=["jamuna"],
                url_must_not_contain=["cinema", "movies"],
            ),
            "NTV News": GoldenChannelSearch(
                search_terms=["NTV", "NTV News", "NTV BD", "NTV Bangladesh"],
                url_must_contain=["ntv"],
                url_must_not_contain=["telugu", "kannada", "tamil", "marathi",
                                       "hindi", "india", "24", "andhra"],
            ),
            "Duronto TV": GoldenChannelSearch(
                search_terms=["Duronto TV", "DurontoTV", "Duronto", "Duranta"],
                url_must_contain=["duronto", "duranta"],
                url_must_not_contain=["movies", "cinema"],
            ),
        }
    ),
    GoldenSource(
        name="iptv-org-in",
        url="https://iptv-org.github.io/iptv/countries/in.m3u",
        reliability_bonus=50,
        channels={
            "Star Jalsha": GoldenChannelSearch(
                search_terms=["Star Jalsha", "StarJalsha", "Star Jalsha HD"],
                url_must_contain=["jalsha", "starjalsha"],
                url_must_not_contain=["movies", "cinema", "josh"],
            ),
            "Jalsha Movies": GoldenChannelSearch(
                search_terms=["Jalsha Movies", "JalshaMovies", "Star Jalsha Movies"],
                url_must_contain=["jalsha", "movies"],
                url_must_not_contain=["starjalsha", "entertainment"],
            ),
            "Zee Bangla": GoldenChannelSearch(
                search_terms=["Zee Bangla", "ZeeBangla", "Zee Bangla HD"],
                url_must_contain=["zee", "bangla"],
                url_must_not_contain=["telugu", "marathi", "tamil", "kannada",
                                       "malayalam", "punjabi", "sartha", "cinema",
                                       "sonar", "movies"],
            ),
            "Zee Bangla Sonar": GoldenChannelSearch(
                search_terms=["Zee Bangla Sonar", "ZeeBanglaSonar",
                              "Zee Bangla Cinema", "ZeeBanglaCinema"],
                url_must_contain=["zee", "bangla"],
                url_must_not_contain=["zeebangla", "zee bangla hd"],
            ),
            "Sony Aath": GoldenChannelSearch(
                search_terms=["Sony Aath", "SonyAath", "Sony Ath", "Sony 8"],
                url_must_contain=["sony", "aath"],
                url_must_not_contain=["sony tv", "sony max", "sony pix",
                                       "sony sab", "sony ten", "sony yay",
                                       "sony bbc", "sony hd"],
            ),
            "Nickelodeon": GoldenChannelSearch(
                search_terms=["Nickelodeon", "Nick", "Nick HD"],
                url_must_contain=["nick"],
                url_must_not_contain=["hindi", "tamil", "telugu", "marathi",
                                       "kannada", "malayalam", "gujarati",
                                       "punjabi", "urdu", "jr", "toons",
                                       "teen", "uk", "usa", "australia"],
            ),
            "Sony YAY!": GoldenChannelSearch(
                search_terms=["Sony YAY", "SonyYAY", "Sony Yay", "SonyYay",
                              "Sony YAY Bangla", "Sony Yay Bangla",
                              "Sony YAY Bengali", "Sony Yay Bengali"],
                url_must_contain=["sony", "yay"],
                url_must_not_contain=["hindi", "tamil", "telugu", "marathi",
                                       "kannada", "malayalam", "gujarati",
                                       "punjabi", "urdu", "jr", "junior"],
            ),
            "Sonic": GoldenChannelSearch(
                search_terms=["Sonic", "Sonic TV", "Nickelodeon Sonic"],
                url_must_contain=["sonic"],
                url_must_not_contain=["hindi", "tamil", "telugu", "marathi",
                                       "kannada", "malayalam", "view",
                                       "panasonic", "boom", "hedgehog"],
            ),
            "Sony BBC Earth": GoldenChannelSearch(
                search_terms=["Sony BBC Earth", "SonyBBC", "BBC Earth",
                              "Sony BBC Earth HD"],
                url_must_contain=["bbc", "earth"],
                url_must_not_contain=["hindi", "tamil", "telugu", "marathi",
                                       "kannada", "malayalam", "bangla",
                                       "bengali", "india", "uk", "usa"],
            ),
        }
    ),
]

# =============================================================================
# 3. GENERAL SOURCES (Silver Layer — fallback)
# =============================================================================

GENERAL_SOURCES = [
    ("https://iptv-org.github.io/iptv/countries/bd.m3u", 30),
    ("https://iptv-org.github.io/iptv/countries/in.m3u", 30),
    ("https://iptv-org.github.io/iptv/countries/uk.m3u", 15),
    ("https://iptv-org.github.io/iptv/countries/us.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/entertainment.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/movies.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/kids.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/animation.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/news.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/sports.m3u", 10),
    ("https://iptv-org.github.io/iptv/index.m3u", 5),
    ("https://raw.githubusercontent.com/Shadmanislam/bdiptv/master/BD%20IPTV.m3u", 40),
    ("https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/main/playlist.m3u", 40),
    ("https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8", 5),
]

# =============================================================================
# 4. STATIC FALLBACKS (Bronze Layer — direct URLs)
# =============================================================================
# Only use if you have stable direct links. These expire frequently.

STATIC_FALLBACKS: Dict[str, List[str]] = {
    # "Star Jalsha": [],
    # "T Sports HD": [],
    # Add your direct URLs here if you have them
}

# =============================================================================
# 5. QUALITY CONTROL
# =============================================================================

MAX_STREAMS_PER_CHANNEL = 3
REQUEST_TIMEOUT = 5
FETCH_TIMEOUT = 30
MAX_CONCURRENT_VALIDATIONS = 40
MAX_CONCURRENT_FETCHES = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
}

LANG_WHITELIST = {"Bengali", "Bangla", "English", "bengali", "bangla", "english", "en", "bn"}
COUNTRY_WHITELIST = {"BD", "IN", "UK", "US", "GB"}

NEGATIVE_KEYWORDS = [
    "telugu", "marathi", "tamil", "kannada", "malayalam", "gujarati",
    "punjabi", "odia", "oriya", "assamese", "nepali", "sinhala", "urdu",
    "bhojpuri", "rajasthani", "haryanvi", "chhattisgarhi", "maithili",
    "sanskrit", "konkani", "tulu", "kashmiri", "dogri", "sindhi",
    "bodo", "santhali", "meitei", "mizo", "khasi", "garo", "tripuri",
    "naga", "manipuri",
]

# =============================================================================
# 6. DATA STRUCTURES
# =============================================================================

@dataclass
class M3UEntry:
    name: str
    url: str
    tvg_name: Optional[str] = None
    tvg_id: Optional[str] = None
    tvg_language: Optional[str] = None
    tvg_country: Optional[str] = None
    tvg_logo: Optional[str] = None
    group_title: Optional[str] = None
    user_agent: Optional[str] = None
    referrer: Optional[str] = None
    source_url: str = ""
    raw_extinf: str = ""


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
    tier: str = ""  # GOLD, SILVER, BRONZE


@dataclass
class ChannelResult:
    canonical: str
    tier: str  # GOLD, SILVER, BRONZE, OFFLINE
    streams: List[ValidationResult] = field(default_factory=list)


# =============================================================================
# 7. M3U PARSING
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


def parse_m3u(content: str, source_url: str) -> List[M3UEntry]:
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
                entry = _parse_extinf(current_extinf, line, source_url)
                if entry:
                    entries.append(entry)
            current_extinf = ""

    return entries


def _parse_extinf(extinf_line: str, url: str, source_url: str) -> Optional[M3UEntry]:
    tvg_name = _extract_attr(extinf_line, 'tvg-name')
    tvg_id = _extract_attr(extinf_line, 'tvg-id')
    tvg_language = _extract_attr(extinf_line, 'tvg-language')
    tvg_country = _extract_attr(extinf_line, 'tvg-country')
    tvg_logo = _extract_attr(extinf_line, 'tvg-logo')
    group_title = _extract_attr(extinf_line, 'group-title')
    user_agent = _extract_attr(extinf_line, 'user-agent')
    referrer = _extract_attr(extinf_line, 'referrer')

    display_name = ""
    if "," in extinf_line:
        display_name = clean_channel_name(extinf_line.split(",")[-1])

    final_name = tvg_name if tvg_name else display_name
    if not final_name:
        return None

    return M3UEntry(
        name=final_name,
        url=url.strip(),
        tvg_name=tvg_name,
        tvg_id=tvg_id,
        tvg_language=tvg_language,
        tvg_country=tvg_country,
        tvg_logo=tvg_logo,
        group_title=group_title,
        user_agent=user_agent,
        referrer=referrer,
        source_url=source_url,
        raw_extinf=extinf_line,
    )


def _extract_attr(line: str, attr: str) -> Optional[str]:
    pattern = rf'{attr}="([^"]*)"'
    match = re.search(pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# =============================================================================
# 8. MATCHING ENGINE
# =============================================================================

def compute_match_score(entry: M3UEntry, profile: ChannelProfile) -> float:
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)

    # Exclusion check
    for exclude_kw in profile.exclude:
        flat_exclude = re.sub(r'[^a-z0-9]', '', exclude_kw.lower().strip())
        if flat_exclude in flat_name or flat_exclude == flat_name:
            return -1.0

    # Negative keyword check
    group_lower = (entry.group_title or "").lower()
    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return -1.0

    # Language guard
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
            return -1.0

    # Scoring
    score = 0.0
    matched = False

    for kw in profile.primary:
        flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
        if flat_kw == flat_name or flat_kw in flat_name:
            score += 1.0
            matched = True
            break

    if not matched:
        for kw in profile.secondary:
            flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
            if flat_kw in flat_name:
                score += 0.6
                matched = True
                break

    if not matched:
        for kw in profile.tertiary:
            flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
            if flat_kw in flat_name:
                score += 0.3
                matched = True
                break

    if not matched:
        return 0.0

    if entry.tvg_language and profile.lang_required:
        lang_lower = entry.tvg_language.lower().strip()
        if any(req.lower() in lang_lower for req in profile.lang_required):
            score += 0.2

    if entry.tvg_country and profile.country_preferred:
        country_upper = entry.tvg_country.upper().strip()
        if country_upper in {c.upper() for c in profile.country_preferred}:
            score += 0.1

    if entry.group_title:
        group_lower = entry.group_title.lower()
        if any(req.lower() in group_lower for req in profile.lang_required):
            score += 0.05
        for neg in NEGATIVE_KEYWORDS:
            if neg in group_lower:
                score -= 0.5

    return score


def match_entry(entry: M3UEntry) -> Optional[Tuple[str, float]]:
    best_match = None
    best_score = 0.0

    for profile in CHANNEL_PROFILES:
        score = compute_match_score(entry, profile)
        if score < 0:
            continue
        if score >= profile.min_confidence and score > best_score:
            best_score = score
            best_match = profile.canonical

    if best_match:
        return (best_match, best_score)
    return None


# =============================================================================
# 9. GOLDEN SOURCE MATCHING
# =============================================================================

def golden_match(entry: M3UEntry, search: GoldenChannelSearch) -> bool:
    """Strict matching for Golden Sources — higher confidence, URL validation."""
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)
    url_lower = entry.url.lower()

    # Name must match one of the search terms
    name_matched = False
    for term in search.search_terms:
        flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
        if flat_term in flat_name or flat_term == flat_name:
            name_matched = True
            break

    if not name_matched:
        return False

    # URL must contain required substrings
    for req in search.url_must_contain:
        if req.lower() not in url_lower:
            return False

    # URL must NOT contain excluded substrings
    for exc in search.url_must_not_contain:
        if exc.lower() in url_lower:
            return False

    return True


# =============================================================================
# 10. URL NORMALIZATION
# =============================================================================

def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        qsl = parse_qs(parsed.query, keep_blank_values=True)
        tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                          'utm_content', 'tracking', 'source', 'ref', 'referrer'}
        filtered = {k: v for k, v in qsl.items() if k.lower() not in tracking_params}
        new_query = urlencode(filtered, doseq=True)
        path = parsed.path.rstrip('/')
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            new_query,
            '',
        ))
    except Exception:
        return url


# =============================================================================
# 11. DEEP STREAM VALIDATION
# =============================================================================

async def validate_url_deep(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    source_bonus: int = 0,
    tier: str = "SILVER"
) -> ValidationResult:
    async with semaphore:
        start_time = time.monotonic()
        result = ValidationResult(url=url, tier=tier)

        try:
            # Tier 1: HEAD Probe
            head_timeout = aiohttp.ClientTimeout(total=3, sock_connect=2, sock_read=2)
            async with session.head(
                url, headers=HEADERS, timeout=head_timeout,
                allow_redirects=True, ssl=False
            ) as resp:
                if resp.status not in (200, 301, 302, 307, 308):
                    result.error = f"HEAD status: {resp.status}"
                    return result

                ct = resp.headers.get("Content-Type", "").lower()
                result.content_type = ct

                if "text/html" in ct and not any(ext in url.lower() for ext in [".m3u8", ".ts", ".mp4"]):
                    result.error = "HTML response (dead link)"
                    return result
        except Exception:
            pass

        # Tier 2: Signature Verification
        try:
            get_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=4)
            headers = dict(HEADERS)
            headers["Range"] = "bytes=0-2047"

            async with session.get(
                url, headers=headers, timeout=get_timeout,
                allow_redirects=True, ssl=False
            ) as resp:
                if resp.status not in (200, 206):
                    result.error = f"GET status: {resp.status}"
                    return result

                chunk = await resp.content.read(2048)
                if not chunk:
                    result.error = "Empty response body"
                    return result

                if not _verify_signature(chunk, url):
                    result.error = "Signature verification failed"
                    return result

                result.signature_valid = True

                # Tier 3: Performance Benchmark
                result.ttfb_ms = (time.monotonic() - start_time) * 1000
                elapsed = time.monotonic() - start_time
                if elapsed > 0:
                    result.speed_kbps = (len(chunk) / 1024) / elapsed

                ttfb_score = max(0, 1000 - result.ttfb_ms) / 10
                speed_score = min(result.speed_kbps * 10, 100)
                result.score = ttfb_score + speed_score + source_bonus
                result.is_valid = True

        except asyncio.TimeoutError:
            result.error = "Timeout during GET/validation"
        except Exception as e:
            result.error = f"Exception: {str(e)[:50]}"

        return result


def _verify_signature(chunk: bytes, url: str) -> bool:
    if not chunk:
        return False

    url_lower = url.lower()

    if ".m3u8" in url_lower or chunk.startswith(b"#EXTM3U"):
        return chunk.startswith(b"#EXTM3U") or b"#EXTM3U" in chunk[:100]

    if ".ts" in url_lower or url_lower.endswith(".ts"):
        for i in range(min(188, len(chunk))):
            if chunk[i] == 0x47:
                return True
        return False

    if ".mp4" in url_lower:
        return b"ftyp" in chunk[:100] or b"moov" in chunk[:100]

    if chunk.startswith(b"#EXTM3U"):
        return True
    if b"#EXTM3U" in chunk[:100]:
        return True

    for i in range(min(200, len(chunk))):
        if chunk[i] == 0x47:
            return True

    try:
        text_preview = chunk[:200].decode('utf-8', errors='ignore').lower()
        if '<html' in text_preview or '<!doctype' in text_preview:
            return False
    except Exception:
        pass

    return True


# =============================================================================
# 12. NETWORK
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str, timeout: int = FETCH_TIMEOUT) -> str:
    async with session.get(
        url, headers=HEADERS,
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as resp:
        resp.raise_for_status()
        return await resp.text()


# =============================================================================
# 13. M3U WRITING (FIXED — proper escaping)
# =============================================================================

def escape_m3u_attr(value: str) -> str:
    """Escape quotes in M3U attribute values."""
    return value.replace('"', '\\"')


def write_m3u_entry(f, channel_name: str, profile: ChannelProfile, result: ValidationResult) -> None:
    """Write a single properly-formatted M3U entry."""
    safe_name = escape_m3u_attr(channel_name)
    lang = escape_m3u_attr(",".join(profile.lang_required))
    country = escape_m3u_attr(",".join(profile.country_preferred))
    group = escape_m3u_attr(profile.category.capitalize())
    tier = escape_m3u_attr(result.tier)

    f.write(f'#EXTINF:-1 tvg-name="{safe_name}" '
            f'tvg-language="{lang}" '
            f'tvg-country="{country}" '
            f'group-title="{group}" '
            f'tvg-tier="{tier}",'
            f'{safe_name}\n')
    f.write(f'{result.url}\n')


# =============================================================================
# 14. MAIN ORCHESTRATION
# =============================================================================

async def main() -> None:
    # Results per channel: list of ValidationResult
    discovered: Dict[str, List[ValidationResult]] = {p.canonical: [] for p in CHANNEL_PROFILES}
    validation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    print("[INFO] Fortress v4.0 — Zero-Hallucination IPTV Sync Machine", flush=True)
    print(f"[INFO] Targeting {len(CHANNEL_PROFILES)} premium channels", flush=True)

    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True,
        force_close=False,
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        # =====================================================================
        # PHASE 1: GOLDEN SOURCE EXTRACTION
        # =====================================================================
        print("[INFO] Phase 1: Golden Source extraction...", flush=True)

        golden_tasks = []
        for gs in GOLDEN_SOURCES:
            golden_tasks.append(_fetch_golden(session, gs, fetch_semaphore))

        golden_results = await asyncio.gather(*golden_tasks, return_exceptions=True)

        for gs, result in zip(GOLDEN_SOURCES, golden_results):
            if isinstance(result, Exception):
                print(f"[WARN] Golden source '{gs.name}' failed: {result}", flush=True)
                continue

            content = result
            if not content:
                continue

            entries = parse_m3u(content, gs.url)
            print(f"[INFO] Golden '{gs.name}': parsed {len(entries)} entries", flush=True)

            for entry in entries:
                for canonical, search in gs.channels.items():
                    if golden_match(entry, search):
                        # Validate immediately
                        val_result = await validate_url_deep(
                            session, entry.url, validation_semaphore,
                            source_bonus=gs.reliability_bonus, tier="GOLD"
                        )
                        if val_result.is_valid:
                            discovered[canonical].append(val_result)
                            print(f"[GOLD] {canonical} found in {gs.name}", flush=True)

        # =====================================================================
        # PHASE 2: SILVER — General source scan for missing channels
        # =====================================================================
        missing_after_gold = [c for c, v in discovered.items() if not v]
        if missing_after_gold:
            print(f"[INFO] Phase 2: Silver scan for {len(missing_after_gold)} missing channels...", flush=True)

            async def fetch_with_limit(url: str, bonus: int) -> Tuple[str, int, str]:
                async with fetch_semaphore:
                    try:
                        content = await fetch_source(session, url)
                        return (url, bonus, content)
                    except Exception:
                        return (url, bonus, "")

            fetch_tasks = [fetch_with_limit(url, bonus) for url, bonus in GENERAL_SOURCES]
            fetch_results = await asyncio.gather(*fetch_tasks)

            all_entries: List[M3UEntry] = []
            for source_url, source_bonus, content in fetch_results:
                if not content:
                    continue
                entries = parse_m3u(content, source_url)
                for entry in entries:
                    entry.source_url = source_url
                all_entries.extend(entries)

            print(f"[INFO] Silver: parsed {len(all_entries)} total entries", flush=True)

            # Match only missing channels
            matched_urls: Dict[str, List[Tuple[str, int, float]]] = {c: [] for c in missing_after_gold}

            for entry in all_entries:
                match_result = match_entry(entry)
                if match_result:
                    canonical, confidence = match_result
                    if canonical in missing_after_gold:
                        source_bonus = 0
                        for url, bonus, _ in fetch_results:
                            if url == entry.source_url:
                                source_bonus = bonus
                                break
                        matched_urls[canonical].append((entry.url, source_bonus, confidence))

            # Deduplicate
            for canonical in matched_urls:
                seen = set()
                deduped = []
                for url, bonus, confidence in matched_urls[canonical]:
                    norm = normalize_url(url)
                    if norm not in seen:
                        seen.add(norm)
                        deduped.append((url, bonus, confidence))
                matched_urls[canonical] = deduped

            # Validate
            validation_tasks = []
            metadata = []
            for canonical, items in matched_urls.items():
                for url, source_bonus, confidence in items:
                    validation_tasks.append(
                        validate_url_deep(session, url, validation_semaphore, source_bonus, tier="SILVER")
                    )
                    metadata.append((canonical, url))

            if validation_tasks:
                results = await asyncio.gather(*validation_tasks)
                for (canonical, url), result in zip(metadata, results):
                    if result.is_valid and result.signature_valid:
                        discovered[canonical].append(result)

        # =====================================================================
        # PHASE 3: BRONZE — Static fallbacks
        # =====================================================================
        missing_after_silver = [c for c, v in discovered.items() if not v]
        if missing_after_silver and STATIC_FALLBACKS:
            print(f"[INFO] Phase 3: Bronze static fallbacks for {len(missing_after_silver)} channels...", flush=True)

            bronze_tasks = []
            bronze_meta = []
            for canonical in missing_after_silver:
                if canonical in STATIC_FALLBACKS:
                    for url in STATIC_FALLBACKS[canonical]:
                        bronze_tasks.append(
                            validate_url_deep(session, url, validation_semaphore, source_bonus=100, tier="BRONZE")
                        )
                        bronze_meta.append((canonical, url))

            if bronze_tasks:
                results = await asyncio.gather(*bronze_tasks)
                for (canonical, url), result in zip(bronze_meta, results):
                    if result.is_valid:
                        discovered[canonical].append(result)
                        print(f"[BRONZE] {canonical} from static fallback", flush=True)

        # =====================================================================
        # PHASE 4: Rank and trim
        # =====================================================================
        print("[INFO] Phase 4: Ranking streams...", flush=True)
        for canonical in discovered:
            if len(discovered[canonical]) > 1:
                discovered[canonical].sort(key=lambda x: x.score, reverse=True)
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        # =====================================================================
        # PHASE 5: Generate outputs
        # =====================================================================
        print("[INFO] Phase 5: Generating output files...", flush=True)

        # channels.json
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_channels": len(CHANNEL_PROFILES),
            "working_channels": sum(1 for v in discovered.values() if v),
            "channels": []
        }

        for profile in CHANNEL_PROFILES:
            canonical = profile.canonical
            streams = discovered[canonical]
            output["channels"].append({
                "name": canonical,
                "category": profile.category,
                "language_required": profile.lang_required,
                "country_preferred": profile.country_preferred,
                "notes": profile.notes,
                "stream_count": len(streams),
                "tier": streams[0].tier if streams else "OFFLINE",
                "streams": [
                    {
                        "url": r.url,
                        "tier": r.tier,
                        "ttfb_ms": round(r.ttfb_ms, 2),
                        "speed_kbps": round(r.speed_kbps, 2),
                        "score": round(r.score, 2),
                        "content_type": r.content_type,
                    }
                    for r in streams
                ]
            })

        with open("channels.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Master playlist.m3u
        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                canonical = profile.canonical
                for r in discovered[canonical]:
                    write_m3u_entry(f, canonical, profile, r)

        # bengali.m3u
        with open("bengali.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if "Bengali" in profile.lang_required or "Bangla" in profile.lang_required:
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        write_m3u_entry(f, canonical, profile, r)

        # english.m3u
        with open("english.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if "English" in profile.lang_required and "Bengali" not in profile.lang_required and "Bangla" not in profile.lang_required:
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        write_m3u_entry(f, canonical, profile, r)

        # kids.m3u
        with open("kids.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "kids":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        write_m3u_entry(f, canonical, profile, r)

        # news.m3u
        with open("news.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "news":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        write_m3u_entry(f, canonical, profile, r)

        # sports.m3u
        with open("sports.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "sports":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        write_m3u_entry(f, canonical, profile, r)

        # health.json
        health = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": {}
        }
        for profile in CHANNEL_PROFILES:
            canonical = profile.canonical
            streams = discovered[canonical]
            health["channels"][canonical] = {
                "tier": streams[0].tier if streams else "OFFLINE",
                "stream_count": len(streams),
                "urls": [r.url for r in streams],
            }

        with open("health.json", "w", encoding="utf-8") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)

        # Summary
        total_working = sum(len(v) for v in discovered.values())
        working_channels = sum(1 for v in discovered.values() if v)
        gold_count = sum(1 for v in discovered.values() if v and v[0].tier == "GOLD")
        silver_count = sum(1 for v in discovered.values() if v and v[0].tier == "SILVER")
        bronze_count = sum(1 for v in discovered.values() if v and v[0].tier == "BRONZE")

        print(f"\n{'='*60}")
        print(f"FORTRESS v4.0 SYNC COMPLETE")
        print(f"{'='*60}")
        print(f"Working channels : {working_channels}/{len(CHANNEL_PROFILES)}")
        print(f"  GOLD   (community playlist) : {gold_count}")
        print(f"  SILVER (general scan)       : {silver_count}")
        print(f"  BRONZE (static fallback)    : {bronze_count}")
        print(f"Total streams    : {total_working}")
        print(f"\nOutput files:")
        print(f"  channels.json  — Full metadata with tiers")
        print(f"  playlist.m3u   — Master playlist")
        print(f"  bengali.m3u    — Bengali channels only")
        print(f"  english.m3u    — English channels only")
        print(f"  kids.m3u       — Kids channels")
        print(f"  news.m3u       — News channels")
        print(f"  sports.m3u     — Sports channels")
        print(f"  health.json    — Health status snapshot")
        print(f"{'='*60}")


async def _fetch_golden(session: aiohttp.ClientSession, gs: GoldenSource, semaphore: asyncio.Semaphore) -> str:
    async with semaphore:
        return await fetch_source(session, gs.url)


if __name__ == "__main__":
    asyncio.run(main())
