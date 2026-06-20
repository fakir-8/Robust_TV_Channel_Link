#!/usr/bin/env python3
"""
Ultra-lightweight IPTV Link Sync Machine (Pro Edition)
- Fetches upstream M3U/M3U8 playlists concurrently
- Flexible fuzzy keyword mapping engine supporting extensive channel arrays
- Hybrid HTTP validator (uses lightweight GET chunk requests to bypass HEAD blocks)
- Spoofs legitimate browser User-Agents to prevent anti-bot connection drops
- Outputs structured channels.json and valid multi-line playlist.m3u entries
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

# =============================================================================
# CONFIGURATION
# =============================================================================

# Expanded high-quality upstream playlist sources
SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",
    "https://iptv-org.github.io/iptv/countries/in.m3u",
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8",
]

# Robust fuzzy target map matching all user requested channel ecosystems
TARGETS: Dict[str, List[str]] = {
    "Star Jalsha":   ["star jalsha", "starjalsha"],
    "Zee Bangla":    ["zee bangla", "zeebangla"],
    "Sony Aath":     ["sony aath", "sonyaath", "sony ath"],
    "T Sports HD":   ["t sports", "tsports", "t sport"],
    "Somoy TV":      ["somoy", "somoytv", "somoy tv"],
    "Jamuna TV":     ["jamuna", "jamunatv", "jamuna tv"],
    "NTV News":      ["ntv news", "ntvnews", "ntv"],
    "Maasranga":     ["maasranga", "maasrangatv", "masranga"],
    "Asian TV":      ["asian tv", "asiantv", "asian news"],
    "Duranto TV":    ["duranto", "durantotv", "duranto tv"],
    "Nickelodeon":   ["nickelodeon", "nick", "nick hd"],
    "Sony Yay":      ["sony yay", "sonyyay"],
    "Sonic":         ["sonic", "sonic nickelodeon", "sonic nick"]
}

OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"

# Strict network thresholds to prevent hanging workflow runners
REQUEST_TIMEOUT = 5          
MAX_CONCURRENT_VALIDATIONS = 40
FETCH_TIMEOUT = 30           

# Standard browser headers to bypass strict streaming CDN firewalls
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# =============================================================================
# PARSING ENGINE
# =============================================================================

def clean_channel_name(name: str) -> str:
    """Normalize stream name strings by removing brackets, resolutions, and tracking details."""
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str) -> List[Tuple[str, str]]:
    """Extracts track identity properties and direct targets out of raw playlist feeds."""
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
    """Matches raw channel markers against targeted keyword boundaries gracefully."""
    normalized = name.lower()
    alphanumeric = re.sub(r'[^a-z0-9]', '', normalized)

    for canonical, keywords in TARGETS.items():
        for kw in keywords:
            if kw in normalized:
                return canonical
            if kw.replace(" ", "") in alphanumeric:
                return canonical
    return None


# =============================================================================
# HYBRID VALIDATION SYSTEM
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch raw playlist text from upstream endpoints."""
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """
    Validates streams by initializing a GET connection request but dropping 
    the socket immediately after reading metadata to bypass HEAD rejection limits.
    """
    async with semaphore:
        try:
            # Enforce micro timeouts at structural connection points to avoid infinite blocks
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=3)
            
            # Utilizing GET without reading data frames provides optimal compatibility with CDNs
            async with session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, ssl=False) as resp:
                return resp.status == 200
        except Exception:
            return False


# =============================================================================
# SYSTEM RUNNER
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    # Force continuous buffer flashing so logs are rendered inside GitHub workflows instantly
    print("[INFO] Launching IPTV Link Sync Machine Pipeline...", flush=True)

    async with aiohttp.ClientSession() as session:
        # 1. Fetch playlists simultaneously
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                print(f"[WARN] Failed to download a source stream source: {result}", file=sys.stderr, flush=True)
                continue
            all_entries.extend(parse_m3u(result))

        # 2. Map channel nodes
        matched_urls: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
        for raw_name, stream_url in all_entries:
            canonical = fuzzy_match(raw_name)
            if canonical:
                matched_urls[canonical].append(stream_url)

        # Remove duplicate source entries
        for canonical in matched_urls:
            matched_urls[canonical] = list(dict.fromkeys(matched_urls[canonical]))

        # 3. Handle asynchronous validation queue
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

        # 4. Filter verified functional links
        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # 5. Compile structured data schema payload (For HTML Custom Frontends)
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # 6. Generate explicit multi-line playlist structure (For Standard VLC Players)
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Sync execution complete. {total_working} secure target streams verified.", flush=True)
        print(f"[INFO] Structure mapping saved to: {OUTPUT_FILE}", flush=True)
        print(f"[INFO] Strict format M3U written to: {PLAYLIST_FILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
