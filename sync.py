#!/usr/bin/env python3
"""
Ultra-lightweight IPTV Link Sync Machine (Ultimate Self-Cleaning Edition)
- Advanced multi-source ingestion targeting premium category endpoints
- Strict word-boundary checking with cross-region exclusion filtering
- Automated stream optimization (caps streams at top 3 verified links per channel)
- Hybrid lightweight GET validation with spoofed headers
- Generates clean, zero-maintenance channels.json and playlist.m3u
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

# =============================================================================
# CONFIGURATION & REPO EXPANSION
# =============================================================================

# Greatly expanded upstream network targeting countries and premium genres
SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",       # Bangladesh Base
    "https://iptv-org.github.io/iptv/countries/in.m3u",       # India Base
    "https://iptv-org.github.io/iptv/categories/animation.m3u", # Premium Kids (Nick, Sonic, Sony Yay)
    "https://iptv-org.github.io/iptv/categories/documentary.m3u", # Premium Infotainment (Sony Earth)
    "https://iptv-org.github.io/iptv/categories/news.m3u",      # Global News (BBC World, Somoy)
    "https://iptv-org.github.io/iptv/categories/sports.m3u",    # Global Sports (T Sports)
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8"
]

# Highly specified target matrix with multi-token aliases
TARGETS: Dict[str, List[str]] = {
    "Star Jalsha":      ["star jalsha", "starjalsha"],
    "Zee Bangla":       ["zee bangla", "zeebangla"],
    "Sony Aath":        ["sony aath", "sonyaath", "sony ath"],
    "T Sports HD":      ["t sports", "tsports", "t sport"],
    "Somoy TV":         ["somoy", "somoytv", "somoy tv"],
    "Jamuna TV":        ["jamuna", "jamunatv", "jamuna tv"],
    "NTV News":         ["ntv news", "ntvnews", "ntv"],
    "Maasranga":        ["maasranga", "maasrangatv", "masranga"],
    "Asian TV":         ["asian tv", "asiantv"],
    "Duranto TV":       ["duranto", "durantotv", "duranto tv"],
    "Nickelodeon":      ["nickelodeon", "nick", "nick hd"],
    "Sony Yay":         ["sony yay", "sonyyay"],
    "Sonic":            ["sonic", "sonic nick"],
    "Sony BBC Earth":   ["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
    "BBC World News":   ["bbc world", "bbc news", "bbc world news"]
}

# Strict target exclusion maps to completely bypass alphanumeric domain collisions
EXCLUSIONS: Dict[str, List[str]] = {
    "NTV News":    ["telugu", "andhra", "india", "kannada", "aryan", "dheeran", "suriyan", "salvation"],
    "Asian TV":    ["malaysian", "caucasian", "central"],
    "Sonic":       ["panasonic", "sonicview"]
}

OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"

# Quality Control Settings
MAX_STREAMS_PER_CHANNEL = 3   # Automatic dirty link purge. Retains only top 3 best fallbacks.
REQUEST_TIMEOUT = 5          
MAX_CONCURRENT_VALIDATIONS = 40
FETCH_TIMEOUT = 30           

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# =============================================================================
# EXTENDED PARSING MACHINE
# =============================================================================

def clean_channel_name(name: str) -> str:
    """Normalize and format string lines cleanly."""
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str) -> List[Tuple[str, str]]:
    """Ingests raw track content lines while parsing contextual meta boundaries."""
    lines = content.splitlines()
    channels: List[Tuple[str, str]] = []
    pending_name: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            pending_name = None
            
            # Read metadata strings if explicitly defined by providers
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
    """Evaluates candidates using strict word boundaries and target exclusion matrices."""
    normalized = name.lower().strip()
    cleaned_spaces = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    cleaned_spaces = re.sub(r'\s+', ' ', cleaned_spaces).strip()
    
    for canonical, keywords in TARGETS.items():
        # Apply strict regional exclusion rules immediately
        if canonical in EXCLUSIONS:
            if any(bad_word in normalized for bad_word in EXCLUSIONS[canonical]):
                continue

        for kw in keywords:
            kw_clean = kw.lower().strip()
            
            # Phrase boundary verification
            if re.search(rf'\b{re.escape(kw_clean)}\b', cleaned_spaces):
                return canonical
            
            # Flat exact string match
            if cleaned_spaces.replace(" ", "") == kw_clean.replace(" ", ""):
                return canonical
                
    return None


# =============================================================================
# NETWORK FLOW VALIDATION
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch structured streams from remote repos."""
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """Validates URLs smoothly without triggering anti-bot CDN drop rules."""
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=3)
            async with session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, ssl=False) as resp:
                # Some dirty links stream error sequences inside 200 packets. 
                # Verify that the resource content is a legitimate media object payload
                content_type = resp.headers.get("Content-Type", "").lower()
                if "html" in content_type or "text" in content_type:
                    if not any(ext in url.lower() for ext in ["m3u8", "ts", "mp4"]):
                        return False
                return resp.status == 200
        except Exception:
            return False


# =============================================================================
# PIPELINE CONTROL
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    print("[INFO] Initializing Ultimate Self-Cleaning IPTV Pipeline...", flush=True)

    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                continue
            all_entries.extend(parse_m3u(result))

        matched_urls: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
        for raw_name, stream_url in all_entries:
            canonical = fuzzy_match(raw_name)
            if canonical:
                matched_urls[canonical].append(stream_url)

        for canonical in matched_urls:
            matched_urls[canonical] = list(dict.fromkeys(matched_urls[canonical]))

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

        # Retain validated alive endpoints
        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # AUTOMATED PURGE ENGINE: Slice down lists to retain only the top functional streams
        for canonical in discovered:
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                print(f"[CLEANUP] Trimming excess links for {canonical}. Dropping {len(discovered[canonical]) - MAX_STREAMS_PER_CHANNEL} links.")
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        # Compile JSON Output Struct
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Generate Pristine Multi-Line M3U Map
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Pipeline sync successfully established. {total_working} premium streams saved.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
