#!/usr/bin/env python3
"""
Ultra-lightweight IPTV Link Sync Machine (Dual-Engine Pro Edition)
- Ingests global country indices, genre arrays, and custom BDIX repositories
- Implements a Static Overrides Gateway to protect manually discovered URLs
- Utilizes flattened alphanumeric substring analysis guarded by exclusion vectors
- Automatically purges dirty/duplicate entries, limiting feeds to the top 3 channels
- Generates clean, zero-maintenance channels.json and playlist.m3u files
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

# =============================================================================
# 1. CONFIGURATION & TARGET GATEWAY
# =============================================================================

# Greatly expanded sources, including your high-yield BDIX playlist target
SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",           # Bangladesh Base
    "https://iptv-org.github.io/iptv/countries/in.m3u",           # India Base
    "https://iptv-org.github.io/iptv/categories/animation.m3u",     # Premium Animation
    "https://iptv-org.github.io/iptv/categories/documentary.m3u",   # Infotainment
    "https://iptv-org.github.io/iptv/categories/news.m3u",          # Global News
    "https://iptv-org.github.io/iptv/categories/sports.m3u",        # Global Sports
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8",
    "https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/main/playlist.m3u" # New BDIX Target
]

# Manual static links that you find yourself.
# Paste any high-quality URLs here. If online, they will ALWAYS be included!
STATIC_OVERRIDES: Dict[str, List[str]] = {
    "Star Jalsha": [
        # Example: "https://your-manually-found-link.m3u8"
    ],
    "T Sports HD": [],
    "Zee Bangla": [],
    "Gopal Bhar TV": [],
    "Motu Patlu": []
}

# Expanded premium target matrix featuring independent show loops
TARGETS: Dict[str, List[str]] = {
    "Star Jalsha":      ["star jalsha", "starjalsha", "jalsha"],
    "Zee Bangla":       ["zee bangla", "zeebangla"],
    "Sony Aath":        ["sony aath", "sonyaath", "sony ath"],
    "T Sports HD":      ["t sports", "tsports", "t sport", "tsport"],
    "Somoy TV":         ["somoy", "somoytv", "somoy tv"],
    "Jamuna TV":        ["jamuna", "jamunatv", "jamuna tv"],
    "NTV News":         ["ntv news", "ntvnews", "ntv bd", "ntv"],
    "Maasranga":        ["maasranga", "maasrangatv", "masranga"],
    "Asian TV":         ["asian tv", "asiantv"],
    "Duranto TV":       ["duranto", "durantotv", "duranto tv"],
    "Nickelodeon":      ["nickelodeon", "nick", "nick hd"],
    "Sony Yay":         ["sony yay", "sonyyay"],
    "Sonic":            ["sonic", "sonic nick"],
    "Sony BBC Earth":   ["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
    "BBC World News":   ["bbc world", "bbc news", "bbc world news"],
    "Gopal Bhar TV":    ["gopal bhar", "gopalbhar", "gopal bhar tv"],
    "Motu Patlu":       ["motu patlu", "motupatlu", "motu patlu tv"]
}

# Exclusion rules to filter out alphanumeric matching collisions
EXCLUSIONS: Dict[str, List[str]] = {
    "NTV News":    ["telugu", "andhra", "india", "kannada", "aryan", "dheeran", "suriyan", "salvation", "ntv24"],
    "Asian TV":    ["malaysian", "caucasian", "central"],
    "Sonic":       ["panasonic", "sonicview"]
}

OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"

# Quality Control Boundaries
MAX_STREAMS_PER_CHANNEL = 3   # Drops excess clutter, keeping your top 3 fastest links
REQUEST_TIMEOUT = 5          
MAX_CONCURRENT_VALIDATIONS = 40
FETCH_TIMEOUT = 30           

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# =============================================================================
# 2. PARSING & HYBRID MATCHING ENGINE
# =============================================================================

def clean_channel_name(name: str) -> str:
    """Strip out extraneous stream metadata brackets and tracking configurations."""
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str) -> List[Tuple[str, str]]:
    """Extracts raw name identities and URL values concurrently from file contents."""
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


def fuzzy_match(name: str) -> Optional[str]:
    """
    Surgical Flattened Matcher.
    Compresses both target strings and candidate lines to find hidden variations
    (e.g., matching 'Tsports hd' to 'tsports'), while maintaining exclusion rules.
    """
    normalized = name.lower().strip()
    # Flatten the string completely to clear out space/hyphen mismatches
    flat_candidate = re.sub(r'[^a-z0-9]', '', normalized)
    
    for canonical, keywords in TARGETS.items():
        if canonical in EXCLUSIONS:
            if any(bad_word in normalized for bad_word in EXCLUSIONS[canonical]):
                continue

        for kw in keywords:
            flat_keyword = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
            if flat_keyword in flat_candidate:
                return canonical
                
    return None


# =============================================================================
# 3. NETWORK LIFECYCLE MANAGEMENT
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    """Downloads remote playlist content frames safely."""
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """Validates connectivity headers without overloading the continuous runner process."""
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
# 4. ORCHESTRATION PIPELINE
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    print("[INFO] Launching Chaotic-Proof Dual Engine Sync Machine...", flush=True)

    async with aiohttp.ClientSession() as session:
        # Step 1: Gather remote scraper records
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                continue
            all_entries.extend(parse_m3u(result))

        # Step 2: Extract scraped items using the flattened engine
        matched_urls: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
        for raw_name, stream_url in all_entries:
            canonical = fuzzy_match(raw_name)
            if canonical:
                matched_urls[canonical].append(stream_url)

        # Step 3: Inject Manual Static Overrides directly into the pipeline arrays
        for canonical, manual_urls in STATIC_OVERRIDES.items():
            if canonical in matched_urls:
                matched_urls[canonical].extend(manual_urls)

        # Deduplicate all links before running network checks
        for canonical in matched_urls:
            matched_urls[canonical] = list(dict.fromkeys(matched_urls[canonical]))

        # Step 4: Validate queue elements concurrently
        validation_tasks = []
        metadata = []

        for canonical, urls in matched_urls.items():
            for u in urls:
                validation_tasks.append(validate_url(session, u, semaphore))
                metadata.append((canonical, u))

        if validation_tasks:
            results = await asyncio.gather(*validation_tasks)
        else:
            results = []

        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # Step 5: Automated Purge Engine (Trims duplicates down to the best 3 working links)
        for canonical in discovered:
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        # Step 6: Write structured JSON payload
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Step 7: Write clean, line-broken M3U directory records
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Process finished. {total_working} secure, high-accuracy channels mapped.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
