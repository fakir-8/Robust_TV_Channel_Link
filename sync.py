#!/usr/bin/env python3
"""
Ultra-lightweight IPTV Link Sync Machine
- Fetches upstream M3U/M3U8 playlists concurrently
- Parses channel names and stream URLs with a flexible, fungible engine
- Fuzzy-matches target premium channels
- Validates links asynchronously via aiohttp HEAD requests
- Outputs a structured channels.json with verified streams
- Generates a standard playlist.m3u file
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

# Upstream playlist sources
SOURCES = [
    "https://iptv-org.github.io/iptv/countries/bd.m3u",
    "https://iptv-org.github.io/iptv/countries/in.m3u",
    "https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8",
]

# Target channels and their fuzzy keyword aliases (all lowercased)
TARGETS: Dict[str, List[str]] = {
    "Star Jalsha": ["star jalsha", "starjalsha"],
    "Zee Bangla":  ["zee bangla", "zeebangla"],
    "Sony Aath":   ["sony aath", "sonyaath"],
    "T Sports":    ["t sports", "tsports"],
}

OUTPUT_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u"
REQUEST_TIMEOUT = 5          # seconds for HEAD validation
MAX_CONCURRENT_VALIDATIONS = 50
FETCH_TIMEOUT = 30           # seconds for downloading playlists

# =============================================================================
# PARSING ENGINE
# =============================================================================

def clean_channel_name(name: str) -> str:
    """
    Normalize channel names by stripping whitespace, collapsing spaces,
    and removing common bracket annotations like [BD], (HD), etc.
    """
    if not name:
        return ""
    # Remove text inside brackets/parentheses
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    # Collapse multiple whitespace characters into a single space
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str) -> List[Tuple[str, str]]:
    """
    Fungible M3U/M3U8 parser.
    Extracts (channel_name, stream_url) pairs from raw playlist text.
    Handles standard #EXTINF metadata lines with tvg-name or comma-delimited names.
    """
    lines = content.splitlines()
    channels: List[Tuple[str, str]] = []
    pending_name: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Metadata line containing channel info
        if line.startswith("#EXTINF"):
            pending_name = None

            # Strategy 1: Extract tvg-name attribute
            tvg_match = re.search(r'tvg-name="([^"]+)"', line, re.IGNORECASE)
            if tvg_match:
                pending_name = clean_channel_name(tvg_match.group(1))

            # Strategy 2: Fallback to text after the last comma
            if not pending_name and "," in line:
                pending_name = clean_channel_name(line.split(",")[-1])

        # URL line (non-comment, non-empty, starts with http)
        elif not line.startswith("#") and pending_name:
            if line.startswith("http"):
                channels.append((pending_name, line))
            # Reset pending name so it doesn't bleed into subsequent lines
            pending_name = None

    return channels


def fuzzy_match(name: str) -> Optional[str]:
    """
    Fuzzy keyword matcher.
    Checks if the cleaned channel name contains any target keyword.
    Supports both spaced and concatenated variants (e.g., 'star jalsha' vs 'starjalsha').
    """
    normalized = name.lower()
    # Alphanumeric-only version for concatenated keyword matching
    alphanumeric = re.sub(r'[^a-z0-9]', '', normalized)

    for canonical, keywords in TARGETS.items():
        for kw in keywords:
            # Standard substring match
            if kw in normalized:
                return canonical
            # Concatenated match (e.g., "starjalsha")
            if kw.replace(" ", "") in alphanumeric:
                return canonical
    return None


# =============================================================================
# ASYNC VALIDATION
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch raw playlist text from an upstream source."""
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def validate_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """
    Perform an asynchronous HTTP HEAD request with a strict timeout.
    Returns True ONLY if the response status is exactly 200.
    Any exception, 403, 404, or other non-200 status is treated as dead.
    """
    async with semaphore:
        try:
            async with session.head(
                url,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=True
            ) as resp:
                return resp.status == 200
        except Exception:
            # Timeout, DNS failure, SSL error, connection reset, etc.
            return False


# =============================================================================
# ORCHESTRATION
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)

    async with aiohttp.ClientSession() as session:
        # ---------------------------------------------------------------------
        # 1. Fetch all upstream sources concurrently
        # ---------------------------------------------------------------------
        fetch_tasks = [fetch_source(session, url) for url in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_entries: List[Tuple[str, str]] = []
        for result in fetch_results:
            if isinstance(result, Exception):
                print(f"[WARN] Failed to fetch source: {result}", file=sys.stderr)
                continue
            all_entries.extend(parse_m3u(result))

        # ---------------------------------------------------------------------
        # 2. Fuzzy-match entries against target channels
        # ---------------------------------------------------------------------
        matched_urls: Dict[str, List[str]] = {c: [] for c in TARGETS.keys()}
        for raw_name, stream_url in all_entries:
            canonical = fuzzy_match(raw_name)
            if canonical:
                matched_urls[canonical].append(stream_url)

        # Deduplicate URLs to avoid redundant network checks
        for canonical in matched_urls:
            matched_urls[canonical] = list(dict.fromkeys(matched_urls[canonical]))

        # ---------------------------------------------------------------------
        # 3. Validate all matched URLs concurrently
        # ---------------------------------------------------------------------
        validation_tasks = []
        metadata = []  # Parallel list of (canonical_name, url)

        for canonical, urls in matched_urls.items():
            for u in urls:
                validation_tasks.append(validate_url(session, u, semaphore))
                metadata.append((canonical, u))

        if validation_tasks:
            results = await asyncio.gather(*validation_tasks)
        else:
            results = []

        # ---------------------------------------------------------------------
        # 4. Build structured output
        # ---------------------------------------------------------------------
        for (canonical, url), is_alive in zip(metadata, results):
            if is_alive:
                discovered[canonical].append(url)

        # ---------------------------------------------------------------------
        # 5. Save channels.json
        # ---------------------------------------------------------------------
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"name": name, "streams": discovered[name]}
                for name in TARGETS.keys()
            ]
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # ---------------------------------------------------------------------
        # 6. Generate playlist.m3u
        # ---------------------------------------------------------------------
        # Iterate through the discovered dictionary and write a properly
        # formatted M3U playlist with standard #EXTINF:-1,Channel Name entries.
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for channel_name in TARGETS.keys():
                for stream_url in discovered[channel_name]:
                    # Standard M3U format: #EXTINF:-1,Channel Name
                    f.write(f"#EXTINF:-1,{channel_name}\n")
                    f.write(f"{stream_url}\n")

        total_working = sum(len(v) for v in discovered.values())
        print(f"[INFO] Sync complete. {total_working} working stream(s) verified.")
        print(f"[INFO] Output written to {OUTPUT_FILE}")
        print(f"[INFO] Playlist written to {PLAYLIST_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
