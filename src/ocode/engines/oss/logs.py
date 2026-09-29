"""Log records: parse, ring buffer, filters, traceback grouping (FR-OSS-030..036)."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

ODOO_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<rest>.*)$"
)
LOGGER_SPLIT_RE = re.compile(r"^(?P<db>\S+)\s+(?P<logger>[\w.]+):\s?(?P<msg>.*)$")
FILE_LINK_RE = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?')
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class LogRecord:
    raw: str
    level: str = "INFO"
    logger: str = ""
    db: str = ""
    ts: str = ""
    msg: str = ""
    traceback: bool = False


def parse_odoo_line(line: str) -> LogRecord:
    m = ODOO_LINE_RE.match(line)
    if not m:
        low = line.lower()
        level = "ERROR" if "traceback" in low or "error" in low else "INFO"
        return LogRecord(raw=line, level=level, msg=line)
    rest = m.group("rest")
    lm = LOGGER_SPLIT_RE.match(rest)
    if lm:
        return LogRecord(
            raw=line,
            level=m.group("level"),
            ts=m.group("ts"),
            db=lm.group("db"),
            logger=lm.group("logger"),
            msg=lm.group("msg"),
        )
    return LogRecord(raw=line, level=m.group("level"), ts=m.group("ts"), msg=rest)


@dataclass
class TraceBlock:
    start: int  # index in buffer of "Traceback ..." line
    end: int  # inclusive
    links: list[tuple[str, int]] = field(default_factory=list)


def extract_file_links(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in FILE_LINK_RE.finditer(text):
        try:
            out.append((m.group("file"), int(m.group("line"))))
        except ValueError:
            continue
    return out


def group_tracebacks(records: list[LogRecord]) -> list[TraceBlock]:
    blocks: list[TraceBlock] = []
    i = 0
    while i < len(records):
        if "Traceback (most recent call last)" in records[i].raw:
            start = i
            j = i + 1
            while j < len(records) and (
                records[j].raw.startswith(("  ", "\t", "File ", "    "))
                or records[j].raw.strip().startswith(("File ", "^", "~"))
                or "Error" in records[j].raw
            ):
                j += 1
                if j - start > 60:
                    break
            end = j - 1
            text = "\n".join(r.raw for r in records[start : end + 1])
            blocks.append(TraceBlock(start, end, extract_file_links(text)))
            i = j
        else:
            i += 1
    return blocks


@dataclass
class LogFilter:
    levels: set[str] = field(default_factory=lambda: set(LEVELS))
    logger_substr: str = ""
    text: str = ""
    use_regex: bool = False

    def matches(self, rec: LogRecord) -> bool:
        if rec.level not in self.levels:
            # always show tracebacks even if level filtered? No: respect levels
            return False
        if self.logger_substr and self.logger_substr not in rec.logger:
            return False
        if self.text:
            hay = rec.raw
            if self.use_regex:
                try:
                    if not re.search(self.text, hay):
                        return False
                except re.error:
                    return False
            elif self.text.lower() not in hay.lower():
                return False
        return True


class LogBuffer:
    """Ring buffer (default 20k lines, FR-OSS-035)."""

    def __init__(self, max_lines: int = 20000) -> None:
        self._buf: deque[LogRecord] = deque(maxlen=max_lines)
        self.max_lines = max_lines
        self.error_count = 0
        self.warn_count = 0

    def __len__(self) -> int:
        return len(self._buf)

    def append_raw(self, line: str) -> LogRecord:
        rec = parse_odoo_line(line.rstrip("\n"))
        if "Traceback (most recent call last)" in line:
            rec.traceback = True
            rec.level = "ERROR"
        self._buf.append(rec)
        if rec.level in ("ERROR", "CRITICAL"):
            self.error_count += 1
        elif rec.level == "WARNING":
            self.warn_count += 1
        return rec

    def extend_raw(self, text: str) -> list[LogRecord]:
        return [self.append_raw(ln) for ln in text.splitlines()]

    def records(self) -> list[LogRecord]:
        return list(self._buf)

    def filtered(self, flt: LogFilter | None = None) -> list[LogRecord]:
        if flt is None:
            return self.records()
        return [r for r in self._buf if flt.matches(r)]

    def clear(self) -> None:
        self._buf.clear()
        self.error_count = 0
        self.warn_count = 0

    def save_to(self, path: object) -> int:
        from pathlib import Path as _P

        p = _P(str(path))
        p.write_text("\n".join(r.raw for r in self._buf) + "\n", encoding="utf-8")
        return len(self._buf)
