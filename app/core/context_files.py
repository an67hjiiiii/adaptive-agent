"""Safe, product-only preparation for small textual context files.

This module deliberately does not create an upload directory or execute an
uploaded file.  The browser sends file bytes as base64, the server decodes and
validates UTF-8 text, and the resulting text is passed to the existing bounded
context pipeline.
"""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any


# This ordered tuple is the canonical Product V1 format contract. The set is
# retained for safe membership validation; clients receive the ordered list
# through /api/config rather than maintaining a second, drifting allow-list.
PRODUCT_CONTEXT_EXTENSIONS = (
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".css", ".csv",
)
SUPPORTED_CONTEXT_EXTENSIONS = frozenset(PRODUCT_CONTEXT_EXTENSIONS)
CONTEXT_FILE_PARSER = "utf-8-text-v1"
MAX_CONTEXT_FILE_BYTES = 100_000
MAX_CONTEXT_FILENAME_CHARS = 255
MAX_CONTEXT_FILES = 20
_SOURCE_ID_RE = re.compile(r"^ctx_[0-9a-f]{16}$")
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ContextFileError(ValueError):
    """A safe, user-facing context-file validation or parsing failure."""

    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _safe_filename(value: Any, *, require_supported: bool) -> str:
    if not isinstance(value, str):
        raise ContextFileError("INVALID_FILENAME", "Tên tệp không hợp lệ.", status_code=400)
    filename = unicodedata.normalize("NFC", value).strip()
    windows_basename = filename.split(".", 1)[0].rstrip(" .").upper()
    if (
        not filename
        or len(filename) > MAX_CONTEXT_FILENAME_CHARS
        or filename in {".", ".."}
        or filename.rstrip(" .") != filename
        or any(unicodedata.category(char).startswith("C") for char in filename)
        or any(char in _INVALID_FILENAME_CHARS for char in filename)
        or windows_basename in _WINDOWS_RESERVED_NAMES
        or Path(filename).name != filename
    ):
        raise ContextFileError(
            "INVALID_FILENAME",
            "Tên tệp không hợp lệ hoặc chứa đường dẫn không an toàn.",
            status_code=400,
        )
    extension = Path(filename).suffix.lower()
    if require_supported and extension not in SUPPORTED_CONTEXT_EXTENSIONS:
        raise ContextFileError(
            "UNSUPPORTED_FORMAT",
            f"Định dạng {extension or 'không xác định'} chưa được hỗ trợ.",
            status_code=415,
        )
    return filename


def normalize_relative_path(value: Any) -> str:
    """Return a safe project-relative source identity, never a local path."""

    if not isinstance(value, str):
        raise ContextFileError("INVALID_RELATIVE_PATH", "Đường dẫn tương đối không hợp lệ.", status_code=400)
    path = unicodedata.normalize("NFC", value).strip().replace("\\", "/")
    if (
        not path
        or len(path) > MAX_CONTEXT_FILENAME_CHARS
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or any(unicodedata.category(char).startswith("C") for char in path)
    ):
        raise ContextFileError("INVALID_RELATIVE_PATH", "Đường dẫn tương đối không an toàn.", status_code=400)
    parts = path.split("/")
    if any(not part or part in {".", ".."} or any(char in _INVALID_FILENAME_CHARS for char in part) for part in parts):
        raise ContextFileError("INVALID_RELATIVE_PATH", "Đường dẫn tương đối không an toàn.", status_code=400)
    if _safe_filename(parts[-1], require_supported=True) != parts[-1]:
        raise ContextFileError("INVALID_RELATIVE_PATH", "Đường dẫn tương đối không an toàn.", status_code=400)
    return "/".join(parts)


def _decode_content(*, content: str | None, content_base64: str | None) -> bytes:
    if (content is None) == (content_base64 is None):
        raise ContextFileError(
            "INVALID_CONTENT",
            "Request phải chứa đúng một dạng nội dung tệp.",
            status_code=400,
        )
    if content_base64 is not None:
        max_encoded = ((MAX_CONTEXT_FILE_BYTES + 2) // 3) * 4
        if len(content_base64) > max_encoded:
            raise ContextFileError(
                "FILE_TOO_LARGE",
                f"Tệp vượt giới hạn {MAX_CONTEXT_FILE_BYTES:,} byte.",
                status_code=413,
            )
        try:
            return base64.b64decode(content_base64.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            raise ContextFileError(
                "DECODE_FAILED",
                "Không thể đọc nội dung tệp.",
            ) from None
    if not isinstance(content, str):
        raise ContextFileError("INVALID_CONTENT", "Nội dung tệp không hợp lệ.", status_code=400)
    try:
        return content.encode("utf-8")
    except UnicodeError:
        raise ContextFileError("DECODE_FAILED", "Không thể đọc nội dung tệp.") from None


def _normalize_text(raw: bytes) -> str:
    if len(raw) > MAX_CONTEXT_FILE_BYTES:
        raise ContextFileError(
            "FILE_TOO_LARGE",
            f"Tệp vượt giới hạn {MAX_CONTEXT_FILE_BYTES:,} byte.",
            status_code=413,
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ContextFileError("DECODE_FAILED", "Tệp phải là văn bản UTF-8.") from None
    if "\x00" in text:
        raise ContextFileError(
            "PARSER_FAILED",
            "Tệp chứa byte không phù hợp với parser văn bản.",
        )
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\ufeff", "", 1).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ContextFileError("EMPTY_FILE", "Tệp không có nội dung văn bản.")
    if len(text.encode("utf-8")) > MAX_CONTEXT_FILE_BYTES:
        raise ContextFileError(
            "FILE_TOO_LARGE",
            f"Tệp vượt giới hạn {MAX_CONTEXT_FILE_BYTES:,} byte sau khi chuẩn hóa.",
            status_code=413,
        )
    return text


def prepare_context_file(
    *, filename: str, content: str | None = None, content_base64: str | None = None,
    relative_path: str | None = None,
) -> dict[str, Any]:
    """Validate one small text file and return context-safe metadata."""

    safe_name = _safe_filename(filename, require_supported=True)
    raw = _decode_content(content=content, content_base64=content_base64)
    text = _normalize_text(raw)
    extension = Path(safe_name).suffix.lower()
    safe_relative_path = normalize_relative_path(relative_path) if relative_path is not None else None
    if safe_relative_path is not None and safe_relative_path.rsplit("/", 1)[-1] != safe_name:
        raise ContextFileError("INVALID_RELATIVE_PATH", "Tên tệp không khớp đường dẫn tương đối.", status_code=400)
    source_id = "ctx_" + hashlib.sha256(
        f"{safe_relative_path or safe_name}\0{text}".encode("utf-8")
    ).hexdigest()[:16]
    source = {
        "source_id": source_id,
        "filename": safe_name,
        "format": extension.removeprefix("."),
        "parser": CONTEXT_FILE_PARSER,
        "char_count": len(text),
        "byte_count": len(text.encode("utf-8")),
        "line_count": text.count("\n") + 1,
    }
    if safe_relative_path is not None:
        source["relative_path"] = safe_relative_path
    return {
        "status": "ready",
        "filename": safe_name,
        "format": source["format"],
        "parser": CONTEXT_FILE_PARSER,
        "text": text,
        "source": source,
    }


def normalize_context_sources(sources: list[Any] | None) -> list[dict[str, Any]]:
    """Keep only safe, server-shaped source identity for product evidence."""

    if sources and len(sources) > MAX_CONTEXT_FILES:
        raise ContextFileError(
            "TOO_MANY_FILES",
            f"Chỉ hỗ trợ tối đa {MAX_CONTEXT_FILES} tệp trong một lượt.",
            status_code=413,
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sources or []:
        raw = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        if not isinstance(raw, dict):
            raise ContextFileError("INVALID_SOURCE", "Thông tin source không hợp lệ.", status_code=400)
        filename = _safe_filename(raw.get("filename"), require_supported=True)
        relative_path = raw.get("relative_path")
        if relative_path is not None:
            relative_path = normalize_relative_path(relative_path)
            if relative_path.rsplit("/", 1)[-1] != filename:
                raise ContextFileError("INVALID_RELATIVE_PATH", "Tên tệp không khớp đường dẫn tương đối.", status_code=400)
        identity = relative_path or filename
        if identity in seen:
            continue
        seen.add(identity)
        source: dict[str, Any] = {
            "filename": filename,
            "format": Path(filename).suffix.lower().removeprefix("."),
            "parser": CONTEXT_FILE_PARSER,
        }
        if relative_path is not None:
            source["relative_path"] = relative_path
        source_id = raw.get("source_id")
        if isinstance(source_id, str) and _SOURCE_ID_RE.fullmatch(source_id):
            source["source_id"] = source_id
        char_count = raw.get("char_count")
        if isinstance(char_count, int) and 0 < char_count <= MAX_CONTEXT_FILE_BYTES:
            source["char_count"] = char_count
        byte_count = raw.get("byte_count")
        if isinstance(byte_count, int) and 0 < byte_count <= MAX_CONTEXT_FILE_BYTES:
            source["byte_count"] = byte_count
        line_count = raw.get("line_count")
        if isinstance(line_count, int) and 0 < line_count <= MAX_CONTEXT_FILE_BYTES:
            source["line_count"] = line_count
        normalized.append(source)
    return normalized
