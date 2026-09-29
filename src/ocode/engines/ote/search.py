"""In-file find/replace (FR-OTE-060/061, M1 core). Headless + streaming-ready."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FindOptions:
    pattern: str
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    multiline: bool = False


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    line: int
    col: int


def _compile(opt: FindOptions) -> re.Pattern[str] | None:
    if not opt.pattern:
        return None
    pat = opt.pattern if opt.regex else re.escape(opt.pattern)
    if opt.whole_word:
        pat = rf"\b(?:{pat})\b"
    flags = 0
    if not opt.case_sensitive:
        flags |= re.IGNORECASE
    if opt.multiline or "\n" in opt.pattern:
        flags |= re.MULTILINE | re.DOTALL
    try:
        return re.compile(pat, flags)
    except re.error:
        return None


class SearchEngine:
    def __init__(self, text_provider: object = None) -> None:
        self._text = ""
        self._compiled: re.Pattern[str] | None = None
        self._opt: FindOptions | None = None

    def set_text(self, text: str) -> None:
        self._text = text

    def find_all(self, opt: FindOptions, text: str | None = None) -> list[Match]:
        hay = self._text if text is None else text
        rx = _compile(opt)
        if rx is None:
            return []
        out: list[Match] = []
        for m in rx.finditer(hay):
            s = m.start()
            line = hay.count("\n", 0, s)
            col = s - (hay.rfind("\n", 0, s) + 1)
            out.append(Match(s, m.end(), line, col))
        return out

    def count(self, opt: FindOptions, text: str | None = None) -> int:
        return len(self.find_all(opt, text))

    def next_match(
        self, opt: FindOptions, from_offset: int, text: str | None = None, wrap: bool = True
    ) -> Match | None:
        matches = self.find_all(opt, text)
        for m in matches:
            if m.start >= from_offset:
                return m
        return matches[0] if wrap and matches else None

    def prev_match(
        self, opt: FindOptions, from_offset: int, text: str | None = None, wrap: bool = True
    ) -> Match | None:
        matches = self.find_all(opt, text)
        prev: Match | None = None
        for m in matches:
            if m.start >= from_offset:
                break
            prev = m
        if prev is not None:
            return prev
        return matches[-1] if wrap and matches else None

    @staticmethod
    def replace_all_text(text: str, opt: FindOptions, repl: str) -> tuple[str, int]:
        rx = _compile(opt)
        if rx is None:
            return (text, 0)
        try:
            out, n = rx.subn(repl, text)
        except re.error:
            return (text, 0)
        return (out, n)
