from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class GroupConfigRepo:
    path: str
    _cache: dict[str, Any] | None = None
    _mtime: float | None = None

    def load(self, path: str | None = None) -> dict[str, Any]:
        target_path = path or self.path
        if not os.path.exists(target_path):
            self._cache = {}
            self._mtime = None
            return {}

        mtime = os.path.getmtime(target_path)
        if self._cache is not None and self._mtime == mtime and (path is None or path == self.path):
            return self._cache

        with open(target_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        if path is None or path == self.path:
            self._cache = data
            self._mtime = mtime

        return data

    def save(self, data: dict[str, Any], path: str | None = None) -> None:
        target_path = path or self.path
        with open(target_path, "w", encoding="utf-8") as file_handle:
            json.dump(data, file_handle, ensure_ascii=False, indent=2)

        if path is None or path == self.path:
            self._cache = data
            try:
                self._mtime = os.path.getmtime(target_path)
            except OSError:
                self._mtime = None
