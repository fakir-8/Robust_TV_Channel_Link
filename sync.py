#!/usr/bin/env python3
"""
Ultra-lightweight IPTV Link Sync Machine (Strict Filter Edition)
- Fetches upstream M3U/M3U8 playlists concurrently
- Tokenized boundary matching engine to eliminate word-collision bugs
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

SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",
    "https://iptv-org.github.io/iptv/countries/in.m3u",
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8",
]

# Refined target map with safe matching variants
TARGETS: Dict[str, List[str]] = {
    "Star Jalsha":   ["star jalsha", "starjalsha"],
    "Zee Bangla":    ["zee bangla", "zeebangla"],
    "Sony Aath":     ["sony aath", "sonyaath", "sony ath"],
    "T Sports HD":   ["t sports", "tsports", "t sport"],
    "Somoy TV":      ["somoy", "somoytv", "somoy tv"],
    "Jamuna TV":     ["jamuna", "jamunatv", "jamuna tv"],
    "NTV News":      ["ntv news", "ntvnews", "ntv"],
    "Maasranga":     ["maasranga", "maasrangatv", "masranga"],
    "Asian TV":      ["asian tv", "asiantv"],
    "Duranto TV":    ["duranto", "durantotv", "duranto tv"],
    "Nickelodeon":   ["nickelodeon", "nick", "nick hd"],
    "Sony Yay":      ["sony yay", "sonyyay"],
    "Sonic":         ["sonic"]
}

OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"

REQUEST_TIMEOUT = 5          
MAX_CONCURRENT_VALIDATIONS = 40
FETCH_TIMEOUT = 30           

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# =============================================================================
# PARSING ENGINE & BOUNDARY FILTER
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
    """
    Highly secure boundary matching system.
    Eliminates word-collision loops (e.g., stops 'ntv' from matching 'dheerantv').
    """
    normalized = name.lower().strip()
    # Replace punctuation with spaces to keep word blocks isolated
    cleaned_spaces = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    cleaned_spaces = re.sub(r'\s+', ' ', cleaned_spaces).strip()
    
    for canonical, keywords in TARGETS.items():
        for kw in keywords:
            kw_clean = kw.lower().strip()
            
            # Strategy 1: Strict word boundary phrase matching (e.g., "\bntv\b" matches "ntv news" but NOT "dheerantv")
            if re.search(rf'\b{re.escape(kw_clean)}\b', cleaned_spaces):
                return canonical
            
            # Strategy 2: Absolute exact match for compressed tokens (e.g., "starjalsha" == "starjalsha")
            if cleaned_spaces.replace(" ", "") == kw_clean.replace(" ", ""):
                return canonical
                
            # Strategy 3: Handle safe prefix extensions (e.g., individual word block starts with "ntv" like "ntvhd")
            words = cleaned_spaces.split()
            kw_flat = kw_clean.replace(" ", "")
            for word in words:
                if len(kw_flat) >= 3 and word.startswith(kw_flat) and len(word) <= len(kw_flat) + 4:
                    # Matches "ntvhd" or "somoytv", but safely drops "dheerantv" or "malaysiantv"
                    return canonical
                    
    return None


# =============================================================================
# VALIDATION SYSTEM
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
    """Validates streams using a lightweight GET connect request that ignores video byte downloading."""
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=3)
            async with session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, ssl=False) as resp:
                return resp.status == 200
        except Exception:
            return False


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    print("[INFO] Launching Refactored Safe-Filter Sync Pipeline...", flush=True)

    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                print(f"[WARN] Source download failure skipped: {result}", file=sys.stderr, flush=True)
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

        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # Output UI-compatible JSON structure
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Output strict line-broken M3U playlist format
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Sync complete. {total_working} perfectly isolated target streams verified.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
