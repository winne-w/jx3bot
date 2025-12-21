from __future__ import annotations

import time

from config import texts


def suijitext() -> str:
    microseconds = int(time.time() * 1000000) % len(texts)
    return texts[microseconds]

