#!/usr/bin/env python3
"""
================================================================================
FORTRESS v5.1 — OPTIMIZED TV SYNC MACHINE
================================================================================
Fixes: Single-fetch architecture, no redundant Phase 4 re-fetch,
       batch validation, optional fixed_channels.json, general search always runs
Architecture: Fetch Once → Parse All → Match Fixed → Match Dynamic → Validate Batch → Output
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
FETCH_TIMEOUT = 25
MAX_CONCURRENT_VALIDATIONS = 50
MAX_CONCURRENT_FETCHES = 15
MAX_DYNAMIC_CHANNELS = 20  # Limit bonus channels to prevent bloat

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
    tvg_language: Optional[str] = None
    tvg_country: Optional[str] = None
    group_title: Optional[str] = None
    source_url: str = ""
    source_bonus: int = 0


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
# 3. MATCHING ENGINE
# =============================================================================

def matches_golden(entry: M3UEntry, search_terms: List[str],
                   url_must_contain: List[str], url_must_not_contain: List[str],
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

    # URL guards
    for req in url_must_contain:
        if req.lower() not in url_lower:
            return False
    for exc in url_must_not_contain:
        if exc.lower() in url_lower:
            return False

    # Exclude terms
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


def fuzzy_match(entry: M3UEntry, search_terms: List[str], exclude_terms: List[str],
                required_langs: List[str]) -> float:
    """Returns confidence score (0.0 to ~1.3). 0.0 = no match."""
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)
    group_lower = (entry.group_title or "").lower()

    # Language guard
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
            return 0.0

    # Negative keyword guard
    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return 0.0

    # Exclude check
    for exc in exclude_terms:
        flat_exc = re.sub(r'[^a-z0-9]', '', exc.lower().strip())
        if flat_exc in flat_name or flat_exc == flat_name:
            return 0.0
        if exc.lower() in group_lower:
            return 0.0

    # Score calculation
    score = 0.0
    matched = False

    for term in search_terms:
        flat_term = re.sub(r'[^a-z0-9]', '', term.lower().strip())
        if flat_term == flat_name:
            score += 1.0
            matched = True
            break
        elif flat_term in flat_name:
            score += 0.6
            matched = True
            break

    if not matched:
        return 0.0

    # Language bonus
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        req_langs = [l.lower() for l in required_langs]
        if any(l in lang_lower for l in req_langs):
            score += 0.2

    # Country bonus
    if entry.tvg_country:
        country = entry.tvg_country.upper().strip()
        if country in {"BD", "IN"}:
            score += 0.1

    # Group bonus
    if entry.group_title:
        if any(l.lower() in group_lower for l in required_langs):
            score += 0.05

    return score


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
                    result.error = f"HEAD {resp.status}"
                    return result
                ct = resp.headers.get("Content-Type", "").lower()
                result.content_type = ct
                if "text/html" in ct and not any(ext in url.lower() for ext in [".m3u8", ".ts", ".mp4"]):
                    result.error = "HTML"
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
                    result.error = f"GET {resp.status}"
                    return result
                chunk = await resp.content.read(2048)
                if not chunk:
                    result.error = "Empty"
                    return result
                if not _verify_signature(chunk, url):
                    result.error = "BadSig"
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
            result.error = f"Err:{str(e)[:40]}"

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
# 7. M3U WRITING (CLEAN)
# =============================================================================

def escape_m3u_attr(value: str) -> str:
    return value.replace('"', '\\"')


def write_m3u_entry(f, channel_name: str, category: str, result: ValidationResult) -> None:
    safe_name = escape_m3u_attr(channel_name)
    safe_group = escape_m3u_attr(category.capitalize())
    f.write(f'#EXTINF:-1 tvg-name="{safe_name}" group-title="{safe_group}",{safe_name}\n')
    f.write(f'{result.url}\n')


# =============================================================================
# 8. MAIN ORCHESTRATION — OPTIMIZED SINGLE-FETCH
# =============================================================================

async def main() -> None:
    print("=" * 60)
    print("FORTRESS v5.1 — Optimized TV Sync")
    print("=" * 60)
    start_time = time.monotonic()

    # Load fixed_channels.json
    try:
        with open("fixed_channels.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("[FATAL] fixed_channels.json not found!")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[FATAL] Invalid JSON: {e}")
        sys.exit(1)

    fixed_channels = config.get("channels", [])
    general_sources_config = config.get("general_sources", [])

    if not fixed_channels:
        print("[FATAL] No channels in fixed_channels.json!")
        sys.exit(1)

    print(f"[INFO] {len(fixed_channels)} fixed channels, {len(general_sources_config)} sources")

    # Build source maps
    source_url_map = {s["name"]: s["url"] for s in general_sources_config}
    source_bonus_map = {s["name"]: s.get("reliability_bonus", 0) for s in general_sources_config}

    # Collect all unique source URLs to fetch (golden + general)
    all_source_names = set()
    for ch in fixed_channels:
        for gs in ch.get("golden_sources", []):
            if gs["source_name"] in source_url_map:
                all_source_names.add(gs["source_name"])
    for s in general_sources_config:
        all_source_names.add(s["name"])

    print(f"[INFO] Will fetch {len(all_source_names)} unique sources")

    validation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    connector = aiohttp.TCPConnector(
        limit=100, limit_per_host=30, ttl_dns_cache=300,
        use_dns_cache=True, enable_cleanup_closed=True, force_close=False,
    )

    async with aiohttp.ClientSession(connector=connector) as session:

        # =====================================================================
        # PHASE 1: FETCH ALL SOURCES ONCE (parallel)
        # =====================================================================
        print(f"\n[INFO] Phase 1: Fetching all sources...", flush=True)

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

        successful_fetches = sum(1 for c in fetched_data.values() if c)
        print(f"[INFO] {successful_fetches}/{len(all_source_names)} sources fetched successfully")

        # =====================================================================
        # PHASE 2: PARSE ALL SOURCES INTO ONE POOL
        # =====================================================================
        print(f"[INFO] Phase 2: Parsing all entries...", flush=True)
        all_entries: List[M3UEntry] = []

        for src_name, content in fetched_data.items():
            if not content:
                continue
            bonus = source_bonus_map.get(src_name, 0)
            url = source_url_map.get(src_name, "")
            entries = parse_m3u(content, url, bonus)
            all_entries.extend(entries)

        print(f"[INFO] Parsed {len(all_entries)} total entries from all sources")

        # =====================================================================
        # PHASE 3: COLLECT CANDIDATE URLs (no validation yet)
        # =====================================================================
        print(f"[INFO] Phase 3: Collecting candidate URLs...", flush=True)

        # Structure: {canonical: [(url, source_bonus, tier, confidence), ...]}
        candidates: Dict[str, List[Tuple[str, int, str, float]]] = {ch["canonical"]: [] for ch in fixed_channels}

        # 3A: PLATINUM — manual URLs (bypass source pool, user-verified)
        for ch in fixed_channels:
            canonical = ch["canonical"]
            for url in ch.get("manual_urls", []):
                if url.strip():
                    candidates[canonical].append((url.strip(), 100, "PLATINUM", 1.0))

        # 3B: GOLD — Golden source search (strict matching from parsed pool)
        for ch in fixed_channels:
            canonical = ch["canonical"]
            for gs in ch.get("golden_sources", []):
                src_name = gs["source_name"]
                content = fetched_data.get(src_name, "")
                if not content:
                    continue
                bonus = source_bonus_map.get(src_name, 0)
                url = source_url_map.get(src_name, "")
                entries = parse_m3u(content, url, bonus)

                for entry in entries:
                    if matches_golden(
                        entry,
                        gs.get("search_terms", []),
                        gs.get("url_must_contain", []),
                        gs.get("url_must_not_contain", []),
                        ch.get("exclude_terms", [])
                    ):
                        candidates[canonical].append((entry.url, bonus, "GOLD", 0.9))

        # 3C: SILVER — General fuzzy matching (from ALL entries, always runs)
        # This ensures channels are found even without golden_sources config
        for ch in fixed_channels:
            canonical = ch["canonical"]
            # Skip if already have PLATINUM or GOLD candidates
            has_better = any(tier in ("PLATINUM", "GOLD") for _, _, tier, _ in candidates[canonical])
            # Actually, we still collect SILVER as backup even if we have GOLD
            # But limit to avoid too many candidates
            silver_count = sum(1 for _, _, tier, _ in candidates[canonical] if tier == "SILVER")
            if silver_count >= 5:
                continue

            search_terms = []
            for gs in ch.get("golden_sources", []):
                search_terms.extend(gs.get("search_terms", []))
            search_terms.extend([ch["canonical"], ch.get("display_name", "")])
            search_terms = list(dict.fromkeys(search_terms))  # dedupe

            for entry in all_entries:
                score = fuzzy_match(
                    entry,
                    search_terms,
                    ch.get("exclude_terms", []),
                    ch.get("language", [])
                )
                if score >= 0.75:
                    candidates[canonical].append((entry.url, entry.source_bonus, "SILVER", score))

        # Deduplicate candidates per channel
        for canonical in candidates:
            seen = set()
            deduped = []
            for url, bonus, tier, confidence in candidates[canonical]:
                norm = normalize_url(url)
                if norm not in seen:
                    seen.add(norm)
                    deduped.append((url, bonus, tier, confidence))
            # Sort by tier priority, then confidence
            tier_order = {"PLATINUM": 0, "GOLD": 1, "SILVER": 2, "BRONZE": 3}
            deduped.sort(key=lambda x: (tier_order.get(x[2], 99), -x[3]))
            candidates[canonical] = deduped[:10]  # Keep top 10 max per channel

        total_candidates = sum(len(v) for v in candidates.values())
        print(f"[INFO] {total_candidates} candidate URLs collected for fixed channels")

        # =====================================================================
        # PHASE 4: BATCH VALIDATE ALL CANDIDATES AT ONCE
        # =====================================================================
        print(f"[INFO] Phase 4: Batch validating {total_candidates} URLs...", flush=True)

        validate_tasks = []
        validate_meta = []
        for canonical, items in candidates.items():
            for url, bonus, tier, confidence in items:
                validate_tasks.append(
                    validate_url(session, url, validation_semaphore, bonus, tier)
                )
                validate_meta.append((canonical, url))

        discovered: Dict[str, List[ValidationResult]] = {ch["canonical"]: [] for ch in fixed_channels}

        if validate_tasks:
            # Process in batches to avoid overwhelming
            batch_size = 50
            for i in range(0, len(validate_tasks), batch_size):
                batch_tasks = validate_tasks[i:i+batch_size]
                batch_meta = validate_meta[i:i+batch_size]
                results = await asyncio.gather(*batch_tasks)
                for (canonical, url), result in zip(batch_meta, results):
                    if result.is_valid and result.signature_valid:
                        discovered[canonical].append(result)
                print(f"  Validated batch {i//batch_size + 1}/{(len(validate_tasks)-1)//batch_size + 1}", flush=True)

        # Report fixed channel results
        for ch in fixed_channels:
            canonical = ch["canonical"]
            if discovered[canonical]:
                tier = discovered[canonical][0].tier
                print(f"  [{tier}] {canonical} ✓ ({len(discovered[canonical])} streams)", flush=True)

        # =====================================================================
        # PHASE 5: DYNAMIC CHANNELS (from remaining entries, limited)
        # =====================================================================
        print(f"\n[INFO] Phase 5: Dynamic bonus channels (max {MAX_DYNAMIC_CHANNELS})...", flush=True)

        # Find entries that don't match any fixed channel
        fixed_canonicals = {ch["canonical"] for ch in fixed_channels}
        dynamic_candidates: Dict[str, List[Tuple[str, int, float]]] = {}

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

            # Skip if matches any fixed channel
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
            for bonus_name, bonus_config in known_bonus.items():
                if bonus_name in dynamic_candidates and len(dynamic_candidates[bonus_name]) >= 5:
                    continue
                for search_term in bonus_config["search"]:
                    flat_search = re.sub(r'[^a-z0-9]', '', search_term.lower().strip())
                    if flat_search in flat_name or flat_search == flat_name:
                        if bonus_name not in dynamic_candidates:
                            dynamic_candidates[bonus_name] = []
                        dynamic_candidates[bonus_name].append((entry.url, entry.source_bonus, 0.8))
                        break

        # Deduplicate and limit dynamic candidates
        for name in list(dynamic_candidates.keys()):
            seen = set()
            deduped = []
            for url, bonus, score in dynamic_candidates[name]:
                norm = normalize_url(url)
                if norm not in seen:
                    seen.add(norm)
                    deduped.append((url, bonus, score))
            dynamic_candidates[name] = deduped[:5]

        # Limit total dynamic channels
        if len(dynamic_candidates) > MAX_DYNAMIC_CHANNELS:
            # Keep only those with most candidates
            sorted_names = sorted(dynamic_candidates.keys(), key=lambda n: len(dynamic_candidates[n]), reverse=True)
            dynamic_candidates = {n: dynamic_candidates[n] for n in sorted_names[:MAX_DYNAMIC_CHANNELS]}

        # Batch validate dynamic candidates
        dynamic_discovered: Dict[str, List[ValidationResult]] = {}
        dyn_tasks = []
        dyn_meta = []
        for name, items in dynamic_candidates.items():
            for url, bonus, score in items:
                dyn_tasks.append(validate_url(session, url, validation_semaphore, bonus, "DYNAMIC"))
                dyn_meta.append((name, url))

        if dyn_tasks:
            batch_size = 50
            for i in range(0, len(dyn_tasks), batch_size):
                batch = dyn_tasks[i:i+batch_size]
                batch_m = dyn_meta[i:i+batch_size]
                results = await asyncio.gather(*batch)
                for (name, url), result in zip(batch_m, results):
                    if result.is_valid:
                        if name not in dynamic_discovered:
                            dynamic_discovered[name] = []
                        dynamic_discovered[name].append(result)

        # =====================================================================
        # PHASE 6: Rank and trim
        # =====================================================================
        print(f"\n[INFO] Phase 6: Ranking and trimming...", flush=True)
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

        # channels.json — FRONTEND CONTRACT
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

        # playlist.m3u
        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in fixed_channels:
                for r in discovered[ch["canonical"]]:
                    write_m3u_entry(f, ch["canonical"], ch.get("category", "entertainment"), r)
            for name, streams in sorted(dynamic_discovered.items()):
                for r in streams:
                    bc = known_bonus.get(name, {})
                    write_m3u_entry(f, name, bc.get("cat", "entertainment"), r)

        # bengali.m3u
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

        # english.m3u
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

        # kids.m3u
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

        # news.m3u
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

        # sports.m3u
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
        for name, streams in dynamic_discovered.items():
            health["dynamic_channels"][name] = {
                "tier": streams[0].tier if streams else "OFFLINE",
                "status": "online" if streams else "offline",
                "stream_count": len(streams),
                "urls": [r.url for r in streams],
            }

        with open("health.json", "w", encoding="utf-8") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)

        # Summary
        elapsed = time.monotonic() - start_time
        fixed_working = sum(1 for c in fixed_channels if discovered[c["canonical"]])
        dynamic_working = sum(1 for v in dynamic_discovered.values() if v)

        platinum = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "PLATINUM")
        gold = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "GOLD")
        silver = sum(1 for c in fixed_channels for r in discovered[c["canonical"]] if r.tier == "SILVER")

        print(f"\n{'='*60}")
        print(f"FORTRESS v5.1 COMPLETE in {elapsed:.1f}s")
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
