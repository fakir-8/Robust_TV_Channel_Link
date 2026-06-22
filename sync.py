#!/usr/bin/env python3
"""
================================================================================
FORTRESS v5.0 — PROFESSIONAL TV SYNC MACHINE
================================================================================
Architecture: fixed_channels.json (UI manifest) → PLATINUM → GOLD → SILVER → BRONZE
Output: channels.json (frontend contract), playlist.m3u (clean), health.json
Frontend: Pure HTML/CSS/JS — reads channels.json, auto-failover on streams[]
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
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

# =============================================================================
# 0. CONFIGURATION
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

LANG_WHITELIST = {"Bengali", "Bangla", "English", "bengali", "bangla", "english", "en", "bn", "hi", "hindi"}
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
    tvg_id: Optional[str] = None
    tvg_language: Optional[str] = None
    tvg_country: Optional[str] = None
    tvg_logo: Optional[str] = None
    group_title: Optional[str] = None
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
    tier: str = ""


@dataclass
class ChannelOutput:
    canonical: str
    display_name: str
    logo_url: str
    category: str
    language: List[str]
    position: int
    tier: str = "OFFLINE"
    status: str = "offline"
    streams: List[ValidationResult] = field(default_factory=list)


# =============================================================================
# 2. M3U PARSING
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

    display_name = ""
    if "," in extinf_line:
        display_name = clean_channel_name(extinf_line.split(",")[-1])

    final_name = tvg_name if tvg_name else display_name
    if not final_name:
        return None

    return M3UEntry(
        name=final_name, url=url.strip(),
        tvg_name=tvg_name, tvg_id=tvg_id,
        tvg_language=tvg_language, tvg_country=tvg_country,
        tvg_logo=tvg_logo, group_title=group_title,
        source_url=source_url, raw_extinf=extinf_line,
    )


def _extract_attr(line: str, attr: str) -> Optional[str]:
    pattern = rf'{attr}="([^"]*)"'
    match = re.search(pattern, line, re.IGNORECASE)
    return match.group(1).strip() if match else None


# =============================================================================
# 3. MATCHING ENGINE
# =============================================================================

def matches_channel(entry: M3UEntry, search_terms: List[str], 
                     url_must_contain: List[str], 
                     url_must_not_contain: List[str],
                     exclude_terms: List[str]) -> bool:
    """Strict matching for Golden Source phase."""
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)
    url_lower = entry.url.lower()
    group_lower = (entry.group_title or "").lower()

    # Name must match one search term
    name_matched = False
    for term in search_terms:
        flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
        if flat_term in flat_name or flat_term == flat_name:
            name_matched = True
            break
    if not name_matched:
        return False

    # URL must contain required substrings
    for req in url_must_contain:
        if req.lower() not in url_lower:
            return False

    # URL must NOT contain excluded substrings
    for exc in url_must_not_contain:
        if exc.lower() in url_lower:
            return False

    # Exclude terms check (name + group)
    for exc in exclude_terms:
        flat_exc = re.sub(r'[^a-z0-9]', '', exc.lower().strip())
        if flat_exc in flat_name or flat_exc == flat_name:
            return False
        if exc.lower() in group_lower:
            return False

    # Language guard
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
            return False

    # Negative keyword guard
    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return False

    return True


def fuzzy_match_general(entry: M3UEntry, fixed_channels: List[Dict]) -> Optional[Tuple[str, float]]:
    """Silver-tier: confidence-based matching for channels not found in Golden phase."""
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)
    group_lower = (entry.group_title or "").lower()

    # Language guard
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
            return None

    # Negative keyword guard
    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return None

    best_match = None
    best_score = 0.0

    for ch in fixed_channels:
        canonical = ch["canonical"]
        all_terms = ch.get("exclude_terms", [])

        # Exclude check
        excluded = False
        for exc in all_terms:
            flat_exc = re.sub(r'[^a-z0-9]', '', exc.lower().strip())
            if flat_exc in flat_name or flat_exc == flat_name:
                excluded = True
                break
        if excluded:
            continue

        # Score calculation
        score = 0.0
        matched = False

        # Check golden source search terms as primary
        for gs in ch.get("golden_sources", []):
            for term in gs.get("search_terms", []):
                flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
                if flat_term == flat_name:
                    score += 1.0
                    matched = True
                    break
                elif flat_term in flat_name:
                    score += 0.6
                    matched = True
                    break
            if matched:
                break

        # Check canonical and display_name
        if not matched:
            for name in [canonical, ch.get("display_name", "")]:
                flat_n = re.sub(r'[^a-z0-9]', '', name.lower().strip())
                if flat_n == flat_name:
                    score += 1.0
                    matched = True
                    break
                elif flat_n in flat_name:
                    score += 0.5
                    matched = True
                    break

        if not matched:
            continue

        # Language bonus
        if entry.tvg_language:
            lang_lower = entry.tvg_language.lower().strip()
            ch_langs = [l.lower() for l in ch.get("language", [])]
            if any(l in lang_lower for l in ch_langs):
                score += 0.2

        # Country bonus
        if entry.tvg_country:
            country = entry.tvg_country.upper().strip()
            if country in {"BD", "IN"}:
                score += 0.1

        if score >= 0.75 and score > best_score:
            best_score = score
            best_match = canonical

    return (best_match, best_score) if best_match else None


# =============================================================================
# 4. URL NORMALIZATION
# =============================================================================

def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        qsl = parse_qs(parsed.query, keep_blank_values=True)
        tracking = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                    'utm_content', 'tracking', 'source', 'ref', 'referrer'}
        filtered = {k: v for k, v in qsl.items() if k.lower() not in tracking}
        new_query = urlencode(filtered, doseq=True)
        path = parsed.path.rstrip('/')
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(),
                           path, parsed.params, new_query, ''))
    except Exception:
        return url


# =============================================================================
# 5. DEEP STREAM VALIDATION
# =============================================================================

async def validate_url(
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
            # Tier 1: HEAD probe
            head_timeout = aiohttp.ClientTimeout(total=3, sock_connect=2, sock_read=2)
            async with session.head(url, headers=HEADERS, timeout=head_timeout,
                                    allow_redirects=True, ssl=False) as resp:
                if resp.status not in (200, 301, 302, 307, 308):
                    result.error = f"HEAD status: {resp.status}"
                    return result
                ct = resp.headers.get("Content-Type", "").lower()
                result.content_type = ct
                if "text/html" in ct and not any(ext in url.lower() for ext in [".m3u8", ".ts", ".mp4"]):
                    result.error = "HTML response"
                    return result
        except Exception:
            pass

        # Tier 2: Signature verification
        try:
            get_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=4)
            headers = dict(HEADERS)
            headers["Range"] = "bytes=0-2047"
            async with session.get(url, headers=headers, timeout=get_timeout,
                                   allow_redirects=True, ssl=False) as resp:
                if resp.status not in (200, 206):
                    result.error = f"GET status: {resp.status}"
                    return result
                chunk = await resp.content.read(2048)
                if not chunk:
                    result.error = "Empty body"
                    return result
                if not _verify_signature(chunk, url):
                    result.error = "Bad signature"
                    return result

                result.signature_valid = True
                result.ttfb_ms = (time.monotonic() - start_time) * 1000
                elapsed = time.monotonic() - start_time
                if elapsed > 0:
                    result.speed_kbps = (len(chunk) / 1024) / elapsed
                ttfb_score = max(0, 1000 - result.ttfb_ms) / 10
                speed_score = min(result.speed_kbps * 10, 100)
                result.score = ttfb_score + speed_score + source_bonus
                result.is_valid = True
        except asyncio.TimeoutError:
            result.error = "Timeout"
        except Exception as e:
            result.error = f"Error: {str(e)[:50]}"

        return result


def _verify_signature(chunk: bytes, url: str) -> bool:
    if not chunk:
        return False
    url_lower = url.lower()
    if ".m3u8" in url_lower or chunk.startswith(b"#EXTM3U"):
        return chunk.startswith(b"#EXTM3U") or b"#EXTM3U" in chunk[:100]
    if ".ts" in url_lower:
        for i in range(min(188, len(chunk))):
            if chunk[i] == 0x47:
                return True
        return False
    if ".mp4" in url_lower:
        return b"ftyp" in chunk[:100] or b"moov" in chunk[:100]
    if chunk.startswith(b"#EXTM3U") or b"#EXTM3U" in chunk[:100]:
        return True
    for i in range(min(200, len(chunk))):
        if chunk[i] == 0x47:
            return True
    try:
        text = chunk[:200].decode('utf-8', errors='ignore').lower()
        if '<html' in text or '<!doctype' in text:
            return False
    except Exception:
        pass
    return True


# =============================================================================
# 6. NETWORK
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str, timeout: int = FETCH_TIMEOUT) -> str:
    async with session.get(url, headers=HEADERS,
                           timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        resp.raise_for_status()
        return await resp.text()


# =============================================================================
# 7. M3U WRITING (CLEAN — no commas in attributes)
# =============================================================================

def escape_m3u_attr(value: str) -> str:
    return value.replace('"', '\\"')


def write_m3u_entry(f, channel_name: str, category: str, result: ValidationResult) -> None:
    safe_name = escape_m3u_attr(channel_name)
    safe_group = escape_m3u_attr(category.capitalize())
    f.write(f'#EXTINF:-1 tvg-name="{safe_name}" group-title="{safe_group}",{safe_name}\n')
    f.write(f'{result.url}\n')


# =============================================================================
# 8. MAIN ORCHESTRATION
# =============================================================================

async def main() -> None:
    print("=" * 60)
    print("FORTRESS v5.0 — TV Sync Machine")
    print("=" * 60)

    # Load fixed_channels.json
    try:
        with open("fixed_channels.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("[FATAL] fixed_channels.json not found! Create it first.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[FATAL] Invalid JSON in fixed_channels.json: {e}")
        sys.exit(1)

    fixed_channels = config.get("channels", [])
    general_sources_config = config.get("general_sources", [])

    if not fixed_channels:
        print("[FATAL] No channels defined in fixed_channels.json!")
        sys.exit(1)

    print(f"[INFO] Loaded {len(fixed_channels)} fixed channels")
    print(f"[INFO] Loaded {len(general_sources_config)} general sources")

    # Build source URL map
    source_url_map = {s["name"]: s["url"] for s in general_sources_config}
    source_bonus_map = {s["name"]: s.get("reliability_bonus", 0) for s in general_sources_config}

    # Initialize results
    discovered: Dict[str, List[ValidationResult]] = {ch["canonical"]: [] for ch in fixed_channels}
    validation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    connector = aiohttp.TCPConnector(
        limit=100, limit_per_host=30, ttl_dns_cache=300,
        use_dns_cache=True, enable_cleanup_closed=True, force_close=False,
    )

    async with aiohttp.ClientSession(connector=connector) as session:

        # =====================================================================
        # PHASE 1: PLATINUM — Manual URLs (your verified direct links)
        # =====================================================================
        print("\n[INFO] Phase 1: PLATINUM — Validating manual URLs...", flush=True)
        platinum_tasks = []
        platinum_meta = []

        for ch in fixed_channels:
            canonical = ch["canonical"]
            for url in ch.get("manual_urls", []):
                if url.strip():
                    platinum_tasks.append(
                        validate_url(session, url.strip(), validation_semaphore,
                                       source_bonus=100, tier="PLATINUM")
                    )
                    platinum_meta.append((canonical, url.strip()))

        if platinum_tasks:
            results = await asyncio.gather(*platinum_tasks)
            for (canonical, url), result in zip(platinum_meta, results):
                if result.is_valid:
                    discovered[canonical].append(result)
                    print(f"  [PLATINUM] {canonical} ✓", flush=True)
                else:
                    print(f"  [PLATINUM] {canonical} ✗ ({result.error})", flush=True)

        # =====================================================================
        # PHASE 2: GOLD — Golden Source playlist search
        # =====================================================================
        missing_after_platinum = [c for c, v in discovered.items() if not v]
        if missing_after_platinum:
            print(f"\n[INFO] Phase 2: GOLD — Searching {len(missing_after_platinum)} channels in playlists...", flush=True)

            # Collect unique golden sources to fetch
            sources_to_fetch = set()
            channel_to_sources = {}
            for ch in fixed_channels:
                if ch["canonical"] in missing_after_platinum:
                    channel_to_sources[ch["canonical"]] = []
                    for gs in ch.get("golden_sources", []):
                        src_name = gs["source_name"]
                        if src_name in source_url_map:
                            sources_to_fetch.add(src_name)
                            channel_to_sources[ch["canonical"]].append(gs)

            # Fetch golden sources
            async def fetch_golden(src_name: str) -> Tuple[str, str]:
                async with fetch_semaphore:
                    try:
                        content = await fetch_source(session, source_url_map[src_name])
                        return (src_name, content)
                    except Exception as e:
                        print(f"  [WARN] Failed to fetch {src_name}: {e}", flush=True)
                        return (src_name, "")

            golden_fetch_tasks = [fetch_golden(name) for name in sources_to_fetch]
            golden_contents = {name: content for name, content in await asyncio.gather(*golden_fetch_tasks)}

            # Parse and match
            for ch in fixed_channels:
                canonical = ch["canonical"]
                if canonical not in missing_after_platinum:
                    continue

                for gs in ch.get("golden_sources", []):
                    src_name = gs["source_name"]
                    content = golden_contents.get(src_name, "")
                    if not content:
                        continue

                    entries = parse_m3u(content, source_url_map.get(src_name, ""))
                    bonus = source_bonus_map.get(src_name, 0)

                    for entry in entries:
                        if matches_channel(
                            entry,
                            gs.get("search_terms", []),
                            gs.get("url_must_contain", []),
                            gs.get("url_must_not_contain", []),
                            ch.get("exclude_terms", [])
                        ):
                            # Validate
                            result = await validate_url(
                                session, entry.url, validation_semaphore,
                                source_bonus=bonus, tier="GOLD"
                            )
                            if result.is_valid:
                                discovered[canonical].append(result)
                                print(f"  [GOLD] {canonical} from {src_name} ✓", flush=True)
                                break  # Found one valid stream from this source

        # =====================================================================
        # PHASE 3: SILVER — Global source scan for remaining channels
        # =====================================================================
        missing_after_gold = [c for c, v in discovered.items() if not v]
        if missing_after_gold:
            print(f"\n[INFO] Phase 3: SILVER — Global scan for {len(missing_after_gold)} channels...", flush=True)

            async def fetch_general(src_url: str, bonus: int) -> Tuple[str, int, str]:
                async with fetch_semaphore:
                    try:
                        content = await fetch_source(session, src_url)
                        return (src_url, bonus, content)
                    except Exception:
                        return (src_url, bonus, "")

            general_tasks = [
                fetch_general(s["url"], s.get("reliability_bonus", 0))
                for s in general_sources_config
            ]
            general_results = await asyncio.gather(*general_tasks)

            all_entries = []
            for src_url, bonus, content in general_results:
                if content:
                    entries = parse_m3u(content, src_url)
                    for e in entries:
                        e.source_url = src_url
                    all_entries.extend(entries)

            print(f"  [SILVER] Parsed {len(all_entries)} entries from all sources", flush=True)

            # Match for missing channels only
            matched = {c: [] for c in missing_after_gold}
            for entry in all_entries:
                match = fuzzy_match_general(entry, fixed_channels)
                if match:
                    canonical, score = match
                    if canonical in missing_after_gold:
                        # Find source bonus
                        bonus = 0
                        for src_url, b, _ in general_results:
                            if src_url == entry.source_url:
                                bonus = b
                                break
                        matched[canonical].append((entry.url, bonus, score))

            # Deduplicate
            for canonical in matched:
                seen = set()
                deduped = []
                for url, bonus, score in matched[canonical]:
                    norm = normalize_url(url)
                    if norm not in seen:
                        seen.add(norm)
                        deduped.append((url, bonus, score))
                matched[canonical] = deduped

            # Validate
            silver_tasks = []
            silver_meta = []
            for canonical, items in matched.items():
                for url, bonus, score in items:
                    silver_tasks.append(
                        validate_url(session, url, validation_semaphore, bonus, "SILVER")
                    )
                    silver_meta.append((canonical, url))

            if silver_tasks:
                results = await asyncio.gather(*silver_tasks)
                for (canonical, url), result in zip(silver_meta, results):
                    if result.is_valid:
                        discovered[canonical].append(result)
                        print(f"  [SILVER] {canonical} ✓", flush=True)

        # =====================================================================
        # PHASE 4: DYNAMIC — Find bonus channels not in fixed list
        # =====================================================================
        print(f"\n[INFO] Phase 4: DYNAMIC — Scanning for bonus channels...", flush=True)
        dynamic_channels: Dict[str, List[ValidationResult]] = {}

        # Re-fetch general sources (or reuse if we have them)
        # For simplicity, we'll scan all general sources again for dynamic
        async def fetch_dynamic(src_url: str, bonus: int) -> Tuple[str, int, str]:
            async with fetch_semaphore:
                try:
                    content = await fetch_source(session, src_url)
                    return (src_url, bonus, content)
                except Exception:
                    return (src_url, bonus, "")

        dynamic_tasks = [
            fetch_dynamic(s["url"], s.get("reliability_bonus", 0))
            for s in general_sources_config
        ]
        dynamic_results = await asyncio.gather(*dynamic_tasks)

        dynamic_entries = []
        for src_url, bonus, content in dynamic_results:
            if content:
                entries = parse_m3u(content, src_url)
                for e in entries:
                    e.source_url = src_url
                dynamic_entries.extend(entries)

        # Look for known Bengali/English channels not in fixed list
        known_bonus_targets = {
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

        for entry in dynamic_entries:
            normalized = entry.name.lower().strip()
            flat_name = re.sub(r'[^a-z0-9]', '', normalized)
            group_lower = (entry.group_title or "").lower()

            # Skip if matches a fixed channel
            skip = False
            for ch in fixed_channels:
                for gs in ch.get("golden_sources", []):
                    for term in gs.get("search_terms", []):
                        flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
                        if flat_term in flat_name:
                            skip = True
                            break
                    if skip:
                        break
                if skip:
                    break
            if skip:
                continue

            # Language guard
            if entry.tvg_language:
                lang_lower = entry.tvg_language.lower().strip()
                if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
                    continue

            # Negative keyword guard
            for neg in NEGATIVE_KEYWORDS:
                if neg in normalized or neg in group_lower:
                    continue

            # Match against known bonus targets
            for bonus_name, bonus_config in known_bonus_targets.items():
                for search_term in bonus_config["search"]:
                    flat_search = re.sub(r'[^a-z0-9]', '', search_term.lower().strip())
                    if flat_search in flat_name or flat_search == flat_name:
                        if bonus_name not in dynamic_channels:
                            dynamic_channels[bonus_name] = []
                        # Find source bonus
                        bonus = 0
                        for src_url, b, _ in dynamic_results:
                            if src_url == entry.source_url:
                                bonus = b
                                break
                        # Validate
                        result = await validate_url(
                            session, entry.url, validation_semaphore, bonus, "DYNAMIC"
                        )
                        if result.is_valid:
                            dynamic_channels[bonus_name].append(result)
                        break

        # =====================================================================
        # PHASE 5: Rank and trim
        # =====================================================================
        print(f"\n[INFO] Phase 5: Ranking streams...", flush=True)
        for canonical in discovered:
            if len(discovered[canonical]) > 1:
                discovered[canonical].sort(key=lambda x: x.score, reverse=True)
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        for name in dynamic_channels:
            if len(dynamic_channels[name]) > 1:
                dynamic_channels[name].sort(key=lambda x: x.score, reverse=True)
            if len(dynamic_channels[name]) > MAX_STREAMS_PER_CHANNEL:
                dynamic_channels[name] = dynamic_channels[name][:MAX_STREAMS_PER_CHANNEL]

        # =====================================================================
        # PHASE 6: Generate outputs
        # =====================================================================
        print(f"\n[INFO] Phase 6: Generating output files...", flush=True)

        # Build channel lookup for fixed channels
        fixed_lookup = {ch["canonical"]: ch for ch in fixed_channels}

        # channels.json — THE FRONTEND CONTRACT
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fixed_total": len(fixed_channels),
            "fixed_working": sum(1 for c in fixed_channels if discovered[c["canonical"]]),
            "dynamic_total": len(dynamic_channels),
            "dynamic_working": sum(1 for v in dynamic_channels.values() if v),
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

        # Sort fixed by position
        output["fixed_channels"].sort(key=lambda x: x["position"])

        # Dynamic channels
        for name, streams in sorted(dynamic_channels.items()):
            if streams:
                output["dynamic_channels"].append({
                    "canonical": name,
                    "display_name": name,
                    "logo_url": "",
                    "category": known_bonus_targets.get(name, {}).get("cat", "entertainment"),
                    "language": known_bonus_targets.get(name, {}).get("lang", ["Bengali"]),
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

        # playlist.m3u — CLEAN, minimal attributes
        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                canonical = ch["canonical"]
                for r in discovered[canonical]:
                    write_m3u_entry(f, canonical, ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_channels.items()):
                for r in streams:
                    cat = known_bonus_targets.get(name, {}).get("cat", "entertainment")
                    write_m3u_entry(f, name, cat, r)

        # bengali.m3u
        with open("bengali.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if "Bengali" in ch.get("language", []) or "Bangla" in ch.get("language", []):
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_channels.items()):
                langs = known_bonus_targets.get(name, {}).get("lang", [])
                if "Bengali" in langs or "Bangla" in langs:
                    for r in streams:
                        cat = known_bonus_targets.get(name, {}).get("cat", "entertainment")
                        write_m3u_entry(f, name, cat, r)

        # english.m3u
        with open("english.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                langs = ch.get("language", [])
                if "English" in langs and "Bengali" not in langs and "Bangla" not in langs:
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_channels.items()):
                langs = known_bonus_targets.get(name, {}).get("lang", [])
                if "English" in langs and "Bengali" not in langs and "Bangla" not in langs:
                    for r in streams:
                        cat = known_bonus_targets.get(name, {}).get("cat", "entertainment")
                        write_m3u_entry(f, name, cat, r)

        # kids.m3u
        with open("kids.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "kids":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "Kids", r)
            for name, streams in sorted(dynamic_channels.items()):
                if known_bonus_targets.get(name, {}).get("cat") == "kids":
                    for r in streams:
                        write_m3u_entry(f, name, "Kids", r)

        # news.m3u
        with open("news.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "news":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "News", r)
            for name, streams in sorted(dynamic_channels.items()):
                if known_bonus_targets.get(name, {}).get("cat") == "news":
                    for r in streams:
                        write_m3u_entry(f, name, "News", r)

        # sports.m3u
        with open("sports.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                if ch.get("category") == "sports":
                    for r in discovered[ch["canonical"]]:
                        write_m3u_entry(f, ch["canonical"], "Sports", r)
            for name, streams in sorted(dynamic_channels.items()):
                if known_bonus_targets.get(name, {}).get("cat") == "sports":
                    for r in streams:
                        write_m3u_entry(f, name, "Sports", r)

        # health.json
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
        for name, streams in dynamic_channels.items():
            health["dynamic_channels"][name] = {
                "tier": streams[0].tier if streams else "OFFLINE",
                "status": "online" if streams else "offline",
                "stream_count": len(streams),
                "urls": [r.url for r in streams],
            }

        with open("health.json", "w", encoding="utf-8") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)

        # Summary
        fixed_working = sum(1 for c in fixed_channels if discovered[c["canonical"]])
        dynamic_working = sum(1 for v in dynamic_channels.values() if v)
        total_fixed_streams = sum(len(discovered[c["canonical"]]) for c in fixed_channels)
        total_dynamic_streams = sum(len(v) for v in dynamic_channels.values())

        platinum_count = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "PLATINUM")
        gold_count = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "GOLD")
        silver_count = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "SILVER")

        print(f"\n{'='*60}")
        print(f"FORTRESS v5.0 SYNC COMPLETE")
        print(f"{'='*60}")
        print(f"Fixed channels   : {fixed_working}/{len(fixed_channels)}")
        print(f"  PLATINUM       : {platinum_count}")
        print(f"  GOLD           : {gold_count}")
        print(f"  SILVER         : {silver_count}")
        print(f"Dynamic channels : {dynamic_working}/{len(dynamic_channels)}")
        print(f"Total streams    : {total_fixed_streams + total_dynamic_streams}")
        print(f"\nOutput files:")
        print(f"  channels.json  — Frontend contract (HTML/JS app reads this)")
        print(f"  playlist.m3u   — Master M3U (clean names)")
        print(f"  bengali.m3u    — Bengali only")
        print(f"  english.m3u    — English only")
        print(f"  kids.m3u       — Kids only")
        print(f"  news.m3u       — News only")
        print(f"  sports.m3u     — Sports only")
        print(f"  health.json    — Health snapshot")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
