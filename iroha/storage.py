import asyncio
import json
from pathlib import Path
from typing import Any


class JsonStore:
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, path: Path, default: Any):
        self.path = path
        self.default = default
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _clone_default(self) -> Any:
        return json.loads(json.dumps(self.default))

    def _get_lock(self) -> asyncio.Lock:
        key = str(self.path)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def read(self) -> Any:
        lock = self._get_lock()
        async with lock:
            if not self.path.exists():
                data = self._clone_default()
                self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return data
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = self._clone_default()
                self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return data

    async def write(self, data: Any) -> None:
        lock = self._get_lock()
        async with lock:
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def update(self, updater):
        lock = self._get_lock()
        async with lock:
            if not self.path.exists():
                data = self._clone_default()
            else:
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    data = self._clone_default()
            new_data = updater(data)
            self.path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
            return new_data
