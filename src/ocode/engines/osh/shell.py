"""PTY-backed shell session: spawn, resize, history, production guard (FR-OSH-001..008)."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

PROD_PATTERNS = ("prod", "production", "live", "main-db", "customer")


def is_production_db(db: str, patterns: tuple[str, ...] = PROD_PATTERNS) -> bool:
    low = db.lower()
    return any(p in low for p in patterns)


def history_path_for(db: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in db) or "default"
    d = Path.home() / ".local" / "state" / "ocode" / "shell_history"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.txt"


def shell_command(
    odoo_bin: str, python: str, conf: str, db: str,
    interface: str = "", extra: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Build `odoo-bin shell` argv (arg list, no shell)."""
    prog = python or odoo_bin
    argv: list[str] = [odoo_bin, "shell"] if python else ["shell"]
    if conf:
        argv += ["-c", conf]
    if db:
        argv += ["-d", db]
    if interface:
        argv.append(f"--shell-interface={interface}")
    argv += list(extra or [])
    return (prog, argv)


class ShellSession:
    """Interactive PTY session with pyte screen, scrollback and per-DB history."""

    def __init__(self, db: str = "", cols: int = 100, rows: int = 24) -> None:
        self.db = db
        self.cols = cols
        self.rows = rows
        self._pty: Any = None
        self._screen: Any = None
        self._stream: Any = None
        self.scrollback: list[str] = []
        self.history: list[str] = []
        self._hist_idx = 0
        self.started = False
        self._load_history()

    # -- lifecycle -----------------------------------------------------
    def start(
        self, argv: list[str], env: dict[str, str] | None = None, cwd: str | None = None
    ) -> None:
        import pyte
        from ptyprocess import PtyProcess  # type: ignore[import-untyped]

        merged = dict(os.environ)
        if env:
            merged.update(env)
        merged.setdefault("TERM", "xterm-256color")
        self._pty = PtyProcess.spawn(argv, env=merged, cwd=cwd or os.getcwd(),
                                     dimensions=(self.rows, self.cols))
        screen = pyte.Screen(self.cols, self.rows)
        screen.set_mode(pyte.modes.LNM)
        self._screen = screen
        self._stream = pyte.Stream(screen)
        self.started = True
        banner = f"— ocode shell — db: {self.db or '?'}"
        if is_production_db(self.db):
            banner += "  ⚠ PRODUCTION — commits are real!"
        else:
            banner += "  (rollback-on-exit unless you commit; env.cr.commit() is explicit)"
        self.scrollback.append(banner)

    @property
    def alive(self) -> bool:
        pty = self._pty
        if pty is None:
            return False
        try:
            return bool(pty.isalive())
        except OSError:
            return False

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = max(20, cols), max(5, rows)
        try:
            if self._pty is not None:
                self._pty.setwinsize(self.rows, self.cols)
        except OSError:
            pass
        screen = self._screen
        if screen is not None:
            try:
                screen.resize(self.rows, self.cols)
            except (TypeError, AttributeError):
                pass

    def stop(self) -> None:
        pty = self._pty
        self._pty = None
        self.started = False
        if pty is not None:
            try:
                pty.terminate(force=True)
            except OSError:
                pass
        self._save_history()

    # -- io ------------------------------------------------------------
    def poll(self, max_bytes: int = 65536) -> str:
        pty = self._pty
        if pty is None:
            return ""
        # non-blocking: only read when the fd is ready (never stall the UI loop)
        try:
            import select as _select

            fd = getattr(pty, "fd", None)
            if fd is None:
                return ""
            ready, _, _ = _select.select([fd], [], [], 0)
            if not ready:
                return ""
            data = pty.read(max_bytes)
        except (OSError, EOFError, ValueError):
            return ""
        except Exception:
            return ""
        if not data:
            return ""
        text = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
        stream = self._stream
        if stream is not None:
            try:
                stream.feed(text)
            except Exception:
                pass
        for line in text.splitlines():
            if line.strip():
                self.scrollback.append(line.rstrip()[-500:])
        self.scrollback = self.scrollback[-2000:]
        return text

    def send(self, text: str) -> None:
        pty = self._pty
        if pty is None:
            raise RuntimeError("shell not running")
        if not text.endswith("\n"):
            text += "\n"
        try:
            pty.write(text.encode())
        except OSError as exc:
            if exc.errno not in (errno.EIO, errno.EPIPE):
                raise
        stripped = text.strip()
        if stripped:
            if not self.history or self.history[-1] != stripped:
                self.history.append(stripped)
                self.history = self.history[-500:]
            self._hist_idx = len(self.history)
            self._save_history()

    def send_key(self, key: str) -> None:
        mapping = {"enter": "\r", "backspace": "\x7f", "tab": "\t", "escape": "\x1b",
                   "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D"}
        pty = self._pty
        if pty is None:
            return
        data = mapping.get(key, key if len(key) == 1 else "")
        if data:
            self.send_bytes(data.encode())

    def send_bytes(self, data: bytes) -> None:
        pty = self._pty
        if pty is None:
            return
        try:
            pty.write(data)
        except OSError:
            pass

    # -- screen --------------------------------------------------------
    def screen_lines(self) -> list[str]:
        screen = self._screen
        if screen is None:
            return list(self.scrollback[-self.rows :])
        try:
            lines = [ln.rstrip() for ln in screen.display]
        except Exception:
            return list(self.scrollback[-self.rows :])
        # cursor marker
        try:
            cx, cy = screen.cursor.x, screen.cursor.y
            if 0 <= cy < len(lines):
                row = lines[cy]
                lines[cy] = row[:cx] + "▊" + row[cx + 1 :] if cx < len(row) else row + "▊"
        except Exception:
            pass
        return lines

    # -- history -------------------------------------------------------
    def _load_history(self) -> None:
        try:
            path = history_path_for(self.db or "default")
            if path.is_file():
                self.history = [ln.rstrip("\n") for ln in
                                path.read_text(encoding="utf-8").splitlines() if ln.strip()][-500:]
        except OSError:
            self.history = []
        self._hist_idx = len(self.history)

    def _save_history(self) -> None:
        try:
            history_path_for(self.db or "default").write_text(
                "\n".join(self.history[-500:]) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def history_prev(self) -> str:
        if not self.history:
            return ""
        self._hist_idx = max(0, self._hist_idx - 1)
        return self.history[self._hist_idx]

    def history_next(self) -> str:
        if not self.history:
            return ""
        self._hist_idx = min(len(self.history), self._hist_idx + 1)
        if self._hist_idx >= len(self.history):
            return ""
        return self.history[self._hist_idx]
