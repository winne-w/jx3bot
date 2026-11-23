"""Bounded public JX3BOX icon loading for equipment screenshots."""
import asyncio
import base64
import re
import struct
import zlib
from collections import OrderedDict
from time import monotonic
from typing import Dict, Iterable

import httpx

MAX_ICON_BYTES = 32768
MAX_ICONS = 128
MAX_CACHE = 256
ICON_TIMEOUT_SECONDS = 6.0
CACHE_TTL_SECONDS = 86400
_ALLOWED = re.compile(r"https://icon\.jx3box\.com/icon/[1-9][0-9]{0,7}\.png")
_cache = OrderedDict()


def _valid_png(data: bytes) -> bool:
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= 256 and 0 < height <= 256):
        return False
    offset = 8
    seen_idat = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            return False
        if offset == 8 and (kind != b"IHDR" or length != 13):
            return False
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            return length == 0 and end == len(data) and seen_idat
        offset = end
    return False


async def fetch_icon_data_uris(urls: Iterable[str]) -> Dict[str, str]:
    valid = list(dict.fromkeys(url for url in urls if isinstance(url, str) and _ALLOWED.fullmatch(url)))[:MAX_ICONS]
    result = {}
    pending = []
    now = monotonic()
    for url in valid:
        cached = _cache.get(url)
        if cached and cached[0] > now:
            result[url] = cached[1]
            _cache.move_to_end(url)
        else:
            _cache.pop(url, None)
            pending.append(url)
    if not pending:
        return result
    semaphore = asyncio.Semaphore(4)
    async def download():
        async with httpx.AsyncClient(timeout=4.5, follow_redirects=False,
                                     limits=httpx.Limits(max_connections=4, max_keepalive_connections=4)) as client:
            async def load(url):
                async with semaphore:
                    try:
                        async with client.stream("GET", url) as response:
                            if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "image/png":
                                return
                            chunks = []
                            size = 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > MAX_ICON_BYTES:
                                    return
                                chunks.append(chunk)
                            data = b"".join(chunks)
                            if not _valid_png(data):
                                return
                            uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
                            result[url] = uri
                            _cache[url] = (monotonic() + CACHE_TTL_SECONDS, uri)
                            _cache.move_to_end(url)
                            while len(_cache) > MAX_CACHE:
                                _cache.popitem(last=False)
                    except (httpx.HTTPError, ValueError, OSError):
                        return
            await asyncio.gather(*(load(url) for url in pending))
    try:
        await asyncio.wait_for(download(), timeout=ICON_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError, OSError):
        pass
    return result
