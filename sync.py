#!/usr/bin/env python3
"""
IPTV Link Sync Machine - Advanced Semantic Scoring Edition
- Ingests global country files, genre repositories, and community BDIX registries
- Tokenized scoring engine with language preference prioritization (Bangla-First)
- Strict boundary exclusions to prevent structural collisions (e.g., matching tipsports to T Sports)
- Static Overrides Gateway for permanent, manual stream injection
- Self-cleaning automated output limiter (keeps the top 3 best channels)
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

# =============================================================================
# 1. EXPANDED REPOSITORY INGESTION MATRIX
# =============================================================================

SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",           # Bangladesh Base
    "https://iptv-org.github.io/iptv/countries/in.m3u",           # India Base
    "https://iptv-org.github.io/iptv/categories/animation.m3u",     # Kids/Cartoons
    "https://iptv-org.github.io/iptv/categories/documentary.m3u",   # Infotainment/Factory
    "https://iptv-org.github.io/iptv/categories/news.m3u",          # Global News
    "https://iptv-org.github.io/iptv/categories/sports.m3u",        # Global Sports
    "https://iptv-org.github.io/iptv/categories/lifestyle.m3u",     # Cooking/Food
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8",
    "https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/main/playlist.m3u",
    "https://raw.githubusercontent.com/saifbdislam/Live-TV/main/All_Channel.m3u",
    "https://raw.githubusercontent.com/Tariqul-Islam-Sajib/BDIX-IPTV/main/Playlist.m3u"
]

# =============================================================================
# 2. STATIC OVERRIDES GATEWAY (PASTE YOUR MANUAL LINKS HERE)
# =============================================================================

STATIC_OVERRIDES: Dict[str, List[str]] = {
    "Star Jalsha":      [],
    "Zee Bangla":       [],
    "Sony Aath":        [],
    "T Sports HD":      [],
    "GTV (Gazi TV)":    [],
    "Maasranga":        [],
    "Somoy TV":         [],
    "Jamuna TV":        [],
    "NTV News":         [],
    "Asian TV":         [],
    "Duranto TV":       [],
    "Nickelodeon":      [],
    "Sony Yay":         [],
    "Sonic":            [],
    "Sony BBC Earth":   [],
    "Discovery Bangla": [],
    "BBC World News":   [],
    "Sony Max":         [],
    "Food Cooking TV":  [],
    "Gopal Bhar TV":    [],
    "Motu Patlu":       []
}

# =============================================================================
# 3. CORE TARGET REGISTRY WITH PHONETIC ALIASES
# =============================================================================

TARGETS: Dict[str, List[str]] = {
    "Star Jalsha":      ["star jalsha", "starjalsha", "jalsha"],
    "Zee Bangla":       ["zee bangla", "zeebangla"],
    "Sony Aath":        ["sony aath", "sonyaath", "sony ath"],
    "T Sports HD":      ["t sports", "tsports", "t sport", "tsport", "t-sport"],
    "GTV (Gazi TV)":    ["gtv", "gazi tv", "gazitv", "gazi"],
    "Maasranga":        ["maasranga", "maasrangatv", "masranga"],
    "Somoy TV":         ["somoy", "somoytv", "somoy tv"],
    "Jamuna TV":        ["jamuna", "jamunatv", "jamuna tv"],
    "NTV News":         ["ntv news", "ntvnews", "ntv bd", "ntv"],
    "Asian TV":         ["asian tv", "asiantv"],
    "Duranto TV":       ["duranto", "durantotv", "duranto tv", "duranta"],
    "Nickelodeon":      ["nickelodeon", "nick", "nick hd", "nick bengal"],
    "Sony Yay":         ["sony yay", "sonyyay", "yay"],
    "Sonic":            ["sonic", "sonic nick", "sonic vids"],
    "Sony BBC Earth":   ["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
    "Discovery Bangla": ["discovery", "discovery channel", "discovery bangla", "discovery in"],
    "BBC World News":   ["bbc world", "bbc news", "bbc world news"],
    "Sony Max":         ["sony max", "sonymax", "max"],
    "Food Cooking TV":  ["food food", "foodfood", "tlc", "fox life", "masterchef", "cooking", "recipe"],
    "Gopal Bhar TV":    ["gopal bhar", "gopalbhar", "gopal"],
    "Motu Patlu":       ["motu patlu", "motupatlu", "motu"]
}

# Strict target exclusion matrices to drop collision noise instantly
EXCLUSIONS: Dict[str, List[str]] = {
    "T Sports HD":      ["tip", "tipsport", "tipsports", "fox", "sky", "star"],
    "GTV (Gazi TV)":    ["gtv2", "nagorik", "global tv", "green tv"],
    "NTV News":         ["telugu", "andhra", "india", "kannada", "aryan", "dheeran", "suriyan", "salvation", "ntv24"],
    "Asian TV":         ["malaysian", "caucasian", "central"],
    "Sonic":            ["panasonic", "sonicview", "sonic sound"],
    "Sony Max":         ["max 2", "max2", "cine", "action"]
}

# Output & Quality Control Configurations
OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"
MAX_STREAMS_PER_CHANNEL = 3   
REQUEST_TIMEOUT = 5          
MAX_CONCURRENT_VALIDATIONS = 50
FETCH_TIMEOUT = 30           

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# =============================================================================
# 4. ADVANCED SEMANTIC PROCESSING ENGINE
# =============================================================================

def clean_channel_name(name: str) -> str:
    """Strip standard distribution tags, quality tags, and bracket parameters."""
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str) -> List[Tuple[str, str]]:
    """Tokenize line structures to map raw playlist markers cleanly."""
    lines = content.splitlines()
    channels: List[Tuple[str, str]] = []
    pending_name: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            pending_name = None
            tvg_match = re.search(r'tvg-name="([^"]+)"', line, re.IGNORECASE)
            if tvg_match:
                pending_name = clean_channel_name(tvg_match.group(1))

            if not pending_name and "," in line:
                pending_name = clean_channel_name(line.split(",")[-1])

        elif not line.startswith("#") and pending_name:
            if line.startswith("http"):
                channels.append((pending_name, line))
            pending_name = None

    return channels


def score_and_match(name: str) -> Tuple[Optional[str], int]:
    """
    Advanced Multi-Tiered Semantic Matcher.
    Evaluates raw tokens against targeted configurations, tracks regional variants,
    applies strict exclusion barriers, and outputs an item relevance score.
    """
    normalized = name.lower().strip()
    
    # Isolate independent words to protect against substring collisions (like tipsports)
    words = re.findall(r'[a-z0-9]+', normalized)
    flat_candidate = "".join(words)
    
    best_canonical: Optional[str] = None
    max_score = -1
    
    for canonical, keywords in TARGETS.items():
        # Check explicit negative exclusion constraints immediately
        if canonical in EXCLUSIONS:
            if any(bad_word in normalized for bad_word in EXCLUSIONS[canonical]) or \
               any(bad_word in words for bad_word in EXCLUSIONS[canonical]):
                continue

        for kw in keywords:
            kw_clean = kw.lower().strip()
            kw_words = re.findall(r'[a-z0-9]+', kw_clean)
            flat_keyword = "".join(kw_words)
            
            # Tier 1: Perfect match equality check
            if flat_candidate == flat_keyword:
                score = 100
            # Tier 2: Sequence phrase boundary check
            elif re.search(rf'\b{re.escape(kw_clean)}\b', normalized):
                score = 80
            # Tier 3: Flattened contextual match check
            elif flat_keyword in flat_candidate:
                # Deduct matching priority points for fuzzy substring variances
                score = 50
            else:
                continue
                
            # LANGUAGE TUNING: Check for regional audio streams
            if canonical in ["Nickelodeon", "Sony Yay", "Sonic", "Sony BBC Earth", "Discovery Bangla", "Sony Max", "Food Cooking TV"]:
                if any(lang in normalized for lang in ["bangla", "bengali", "bd", "ben"]):
                    score += 30  # Add structural priority bonus for verified regional audio
                elif any(intl in normalized for intl in ["hindi", "telugu", "tamil", "malayalam", "english", "en"]):
                    score -= 40  # Deduct points if flagged explicitly as a non-local feed
                    
            if score > max_score:
                max_score = score
                best_canonical = canonical
                
    # Filter out weak background noise matches
    if max_score >= 50:
        return best_canonical, max_score
    return None, 0

# =============================================================================
# 5. ASYNCHRONOUS VALIDATION PIPELINE
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    """Download source feeds concurrently."""
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """Verify live connectivity without processing or saving large media payloads."""
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=3)
            async with session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, ssl=False) as resp:
                content_type = resp.headers.get("Content-Type", "").lower()
                if "html" in content_type or "text" in content_type:
                    if not any(ext in url.lower() for ext in ["m3u8", "ts", "mp4"]):
                        return False
                return resp.status == 200
        except Exception:
            return False

# =============================================================================
# 6. PIPELINE RUNNER
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    print("[INFO] Initiating Upgraded Semantic Scoring IPTV Sync Pipeline...", flush=True)

    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                continue
            all_entries.extend(parse_m3u(result))

        # Sort scraped items using our semantic scoring weights
        # Structure: structured_matches[canonical_name] = List of tuples: (score, url)
        structured_matches: Dict[str, List[Tuple[int, str]]] = {c: [] for c in TARGETS.keys()}
        
        for raw_name, stream_url in all_entries:
            canonical, score = score_and_match(raw_name)
            if canonical:
                structured_matches[canonical].append((score, stream_url))

        # Inject and prioritize manual Static Overrides
        for canonical, manual_urls in STATIC_OVERRIDES.items():
            for u in manual_urls:
                # Assign manual overrides an absolute top score priority
                structured_matches[canonical].append((999, u))

        # Sort and deduplicate URLs by score descending
        final_validation_queue: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
        for canonical, items in structured_matches.items():
            # Sort items so highest-scoring links (Static Overrides & Bangla Feeds) are verified first
            items.sort(key=lambda x: x[0], reverse=True)
            seen_urls = set()
            for score, url in items:
                if url not in seen_urls:
                    seen_urls.add(url)
                    final_validation_queue[canonical].append(url)

        # Run concurrent network validation passes
        validation_tasks = []
        metadata = []

        for canonical, urls in final_validation_queue.items():
            for u in urls:
                validation_tasks.append(validate_url(session, u, semaphore))
                metadata.append((canonical, u))

        if validation_tasks:
            results = await asyncio.gather(*validation_tasks)
        else:
            results = []

        # Map live verified URLs back to their categories
        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # Automated Purge: Trim stream arrays down to the top functional links
        for canonical in discovered:
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        # Export structured JSON payload
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Export line-broken M3U directory script map
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Pipeline sync successfully concluded. {total_working} channels mapped.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
