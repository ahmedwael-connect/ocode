"""Document model: buffer + encoding/EOL + atomic save + dirty (FR-OTE-002/003/070/073)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from ocode.engines.ote.buffer import PieceTable
from ocode.engines.ote.history import EditOp, UndoStack

LARGE_FILE_BYTES = 50 * 1024 * 1024


def detect_newline(raw: bytes) -> str:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf > 0 and crlf >= lf:
        return "\r\n"
    return "\n"


def decode_bytes(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return (raw.decode(enc), "utf-8" if enc == "utf-8-sig" else enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (raw.decode("latin-1"), "latin-1")


class Document:
    def __init__(self, path: Path | None = None, text: str = "") -> None:
        self.path = path
        self.buffer = PieceTable(text)
        self.encoding = "utf-8"
        self.newline = "\n"
        self.ensure_final_newline = True
        self.readonly = False
        self._saved_hash = self._hash()
        self._disk_mtime: float | None = None
        self.history = UndoStack()
        self.large_file_mode = len(text.encode("utf-8", "ignore")) >= LARGE_FILE_BYTES

    @classmethod
    def from_file(cls, path: Path) -> Document:
        raw = path.read_bytes()
        text, enc = decode_bytes(raw)
        newline = detect_newline(raw)
        # normalize to \n internally
        text = text.replace("\r\n", "\n")
        doc = cls(path=path, text=text)
        doc.encoding = enc
        doc.newline = newline
        try:
            doc._disk_mtime = path.stat().st_mtime
            doc.readonly = not os.access(path, os.W_OK)
        except OSError:
            doc._disk_mtime = None
        doc._saved_hash = doc._hash()
        return doc

    # -- state ---------------------------------------------------------
    def _hash(self) -> str:
        return hashlib.sha256(self.buffer.text.encode("utf-8", "ignore")).hexdigest()

    @property
    def dirty(self) -> bool:
        return self._hash() != self._saved_hash

    @property
    def text(self) -> str:
        return self.buffer.text

    def external_changed(self) -> bool:
        if self.path is None or not self.path.exists():
            return False
        try:
            return self.path.stat().st_mtime != self._disk_mtime
        except OSError:
            return False

    # -- edits (recorded for undo) -------------------------------------
    def insert(self, offset: int, text: str) -> None:
        self.buffer.insert(offset, text)
        self.history.push(EditOp("insert", offset, text))

    def delete(self, offset: int, length: int) -> str:
        removed = self.buffer.delete(offset, length)
        if removed:
            self.history.push(EditOp("delete", offset, removed))
        return removed

    def apply_undo_group(self, group: list[EditOp]) -> None:
        for op in reversed(group):
            if op.kind == "insert":
                self.buffer.delete(op.offset, len(op.text))
            else:
                self.buffer.insert(op.offset, op.text)

    def apply_redo_group(self, group: list[EditOp]) -> None:
        for op in group:
            if op.kind == "insert":
                self.buffer.insert(op.offset, op.text)
            else:
                self.buffer.delete(op.offset, len(op.text))

    def undo(self) -> bool:
        group = self.history.pop_undo()
        if not group:
            return False
        self.apply_undo_group(group)
        return True

    def redo(self) -> bool:
        group = self.history.pop_redo()
        if not group:
            return False
        self.apply_redo_group(group)
        return True

    # -- save ----------------------------------------------------------
    def serialize(self) -> bytes:
        text = self.buffer.text
        if self.ensure_final_newline and text and not text.endswith("\n"):
            text += "\n"
        if self.newline != "\n":
            text = text.replace("\n", self.newline)
        try:
            return text.encode(self.encoding)
        except (UnicodeEncodeError, LookupError):
            return text.encode("utf-8")

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("no path to save to")
        if self.readonly and path is None:
            raise PermissionError(f"read-only file: {target}")
        data = self.serialize()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".ocode-tmp-")
        try:
            with open(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass
        self.path = target
        try:
            self._disk_mtime = target.stat().st_mtime
        except OSError:
            self._disk_mtime = None
        self._saved_hash = self._hash()
        return target
