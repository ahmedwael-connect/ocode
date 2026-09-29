"""Rotation-aware external log tailer (FR-OSS-031: tail -f + inode rotation)."""

from __future__ import annotations

from pathlib import Path


class LogTailer:
    """Poll-based tailer. Call poll() periodically; returns new lines."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ino: int | None = None
        self._pos = 0
        self._buf = ""

    def _stat(self) -> tuple[int | None, int]:
        try:
            st = self.path.stat()
            return (st.st_ino, st.st_size)
        except OSError:
            return (None, 0)

    def poll(self) -> list[str]:
        ino, size = self._stat()
        if ino is None:
            return []
        if self._ino is None:
            # first poll: start at end (tail -f semantics)
            self._ino, self._pos = ino, size
            return []
        if ino != self._ino or size < self._pos:
            # rotated/truncated → reread from start
            self._ino, self._pos = ino, 0
            self._buf = ""
        if size == self._pos:
            return []
        try:
            with self.path.open("rb") as f:
                f.seek(self._pos)
                chunk = f.read(size - self._pos)
                self._pos = size
        except OSError:
            return []
        text = self._buf + chunk.decode("utf-8", errors="ignore")
        lines = text.split("\n")
        self._buf = lines.pop()
        return [ln for ln in lines if ln]

    def read_all(self, max_bytes: int = 1_000_000) -> list[str]:
        try:
            data = self.path.read_bytes()[-max_bytes:]
        except OSError:
            return []
        return data.decode("utf-8", errors="ignore").splitlines()
