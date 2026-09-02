from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import unicodedata


STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be",
    "this", "that", "và", "là", "của", "cho", "trong", "với", "một", "các", "những", "được", "hãy",
    "theo",
}
SNAPSHOT_VERSION = "simple-rag-v3"
RAG_CONFIG_ID = "RAG-LEXICAL-V1"
# The Pilot compares orchestration, not retrieval quality.  The previous
# defaults could silently drop declared benchmark sections before the model
# ever saw the frozen context.  These are one global, versioned retrieval
# policy (never a strategy-specific setting) and are recorded in every
# snapshot so the change is auditable.
RAG_SETTINGS_VERSION = "RAG-LEXICAL-V1@1.1"
DEFAULT_CHUNK_CHARS = 1400
DEFAULT_TOP_K = 32
DEFAULT_MAX_CHARS = 16000
SNAPSHOT_SEPARATOR = "\n\n--- retrieved chunk ---\n\n"
PROJECT_STRUCTURE_HEADER = "[PROJECT STRUCTURE]"
RETRIEVED_CONTEXT_HEADER = "[RETRIEVED CONTEXT]"
_PROJECT_SOURCE_RE = re.compile(r"(?m)^SOURCE: ([^\n]+)\n")


def normalize_source(source: str) -> str:
    """Normalize supported textual uploads without executing or interpreting them."""
    text = unicodedata.normalize("NFC", str(source or ""))
    text = text.replace("\ufeff", "", 1).replace("\x00", "")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def terms(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-zÀ-ỹ0-9_'-]{2,}", text.lower())
    expanded = {piece for token in raw for piece in (token, *re.split(r"[_'-]", token)) if len(piece) >= 2}
    return {term for term in expanded if term not in STOP}


def chunk_text(text: str, max_chars: int = DEFAULT_CHUNK_CHARS) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = normalize_source(text)
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) + 2 <= max_chars:
            buf = (buf + "\n\n" + part).strip()
        else:
            if buf:
                chunks.append(buf)
            if len(part) <= max_chars:
                buf = part
            else:
                for index in range(0, len(part), max_chars):
                    chunks.append(part[index:index + max_chars])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document_id(source: str) -> str:
    return "doc_" + _sha256(source)[:16]


def _snapshot_id(*, context_hash: str, source_document_ids: list[str], chunk_ids: list[str], settings: dict) -> str:
    identity = {
        "snapshot_version": SNAPSHOT_VERSION,
        "context_hash": context_hash,
        "source_document_ids": source_document_ids,
        "chunk_ids": chunk_ids,
        "retrieval_settings": settings,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "snap_" + _sha256(encoded)[:16]


def _chunk_records(source: str, document_id: str, chunk_size: int) -> list[dict]:
    return [
        {
            "chunk_id": f"{document_id}_chunk_{index:04d}",
            "source_document_id": document_id,
            "index": index,
            "text": chunk,
            "char_count": len(chunk),
        }
        for index, chunk in enumerate(chunk_text(source, max_chars=chunk_size))
    ]


def _selected_chunk_view(record: dict, score: float | None = None) -> dict:
    result = {
        "chunk_id": record["chunk_id"],
        "source_document_id": record["source_document_id"],
        "index": record["index"],
        "text": record["text"],
        "char_count": record["char_count"],
    }
    if score is not None:
        result["score"] = round(score, 8)
    if record.get("source_path"):
        result["source_path"] = record["source_path"]
    return result


def _safe_project_path(value: str) -> str | None:
    """Keep only a normalized relative source label from structured context."""

    candidate = value.strip().replace("\\", "/")
    if (
        not candidate
        or candidate.startswith("/")
        or re.match(r"^[A-Za-z]:", candidate)
        or any(part in {"", ".", ".."} for part in candidate.split("/"))
    ):
        return None
    return candidate


def _project_context(source: str, chunk_size: int) -> tuple[str, list[dict]] | None:
    """Parse the browser's small-project envelope without interpreting code."""

    if not source.startswith(PROJECT_STRUCTURE_HEADER + "\n"):
        return None
    marker = "\n\n" + RETRIEVED_CONTEXT_HEADER + "\n"
    if marker not in source:
        return None
    manifest, body = source[len(PROJECT_STRUCTURE_HEADER) + 1:].split(marker, 1)
    matches = list(_PROJECT_SOURCE_RE.finditer(body))
    if not matches:
        return None
    records: list[dict] = []
    for match_index, match in enumerate(matches):
        source_path = _safe_project_path(match.group(1))
        if source_path is None:
            return None
        text_end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(body)
        file_text = body[match.end():text_end].strip()
        if not file_text:
            continue
        document_id = _document_id(source_path + "\0" + file_text)
        for index, chunk in enumerate(chunk_text(file_text, max_chars=chunk_size)):
            records.append({
                "chunk_id": f"{document_id}_chunk_{index:04d}",
                "source_document_id": document_id,
                "index": len(records),
                "text": chunk,
                "char_count": len(chunk),
                "source_path": source_path,
            })
    return (manifest.strip(), records) if records else None


def frozen_snapshot(
    task: str,
    source: str,
    top_k: int = DEFAULT_TOP_K,
    max_chars: int = DEFAULT_MAX_CHARS,
):
    """Return deterministic context text plus inspectable frozen provenance.

    The timestamp is observational metadata only. Snapshot identity/hash are
    derived from normalized content, selected chunk IDs, and retrieval settings,
    so repeated calls with the same inputs produce the same identity.
    """
    if top_k < 1 or max_chars < 1:
        raise ValueError("top_k and max_chars must be positive")

    source = normalize_source(source)
    settings = {
        "retrieval_config_id": RAG_CONFIG_ID,
        "retrieval_settings_version": RAG_SETTINGS_VERSION,
        "method": "lexical-overlap-v1",
        "top_k": top_k,
        "chunk_chars": DEFAULT_CHUNK_CHARS,
        "max_chars": max_chars,
        "normalization": "unicode-nfc-line-endings-nul-stripped",
    }
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if not source:
        snapshot = "No external reference context was supplied."
        context_hash = _sha256(snapshot)
        snapshot_id = _snapshot_id(
            context_hash=context_hash,
            source_document_ids=[],
            chunk_ids=[],
            settings={**settings, "method": "none"},
        )
        return snapshot, {
            "snapshot_version": SNAPSHOT_VERSION,
            "retrieval_config_id": RAG_CONFIG_ID,
            "retrieval_settings_version": RAG_SETTINGS_VERSION,
            "snapshot_id": snapshot_id,
            "snapshot_hash": context_hash,
            "context_hash": context_hash,
            "source_document_ids": [],
            "source_documents": [],
            "chunk_ids": [],
            "available_chunk_ids": [],
            "selected_chunks": [],
            "method": "none",
            "chunks_total": 0,
            "chunks_selected": 0,
            "selected_indices": [],
            "retrieval_settings": {**settings, "method": "none"},
            "truncation": {
                "applied": False,
                "reason": None,
                "original_chars": 0,
                "assembled_chars": len(snapshot),
                "context_chars": len(snapshot),
                "dropped_chars": 0,
            },
            "retrieval_omissions": {
                "applied": False,
                "omitted_chunk_ids": [],
                "omitted_chunk_count": 0,
                "reason": None,
            },
            "created_at": created_at,
        }

    project = _project_context(source, DEFAULT_CHUNK_CHARS)
    is_project = project is not None
    if project is not None:
        project_structure, records = project
        document_id = None
        source_hash = _sha256(source)
    else:
        document_id = _document_id(source)
        source_hash = _sha256(source)
        records = _chunk_records(source, document_id, DEFAULT_CHUNK_CHARS)
    scored_records: list[tuple[float | None, dict]] = [(None, record) for record in records]
    method = "full-small-context"

    if is_project or (len(source) > max_chars and len(records) > top_k):
        query_terms = terms(task)
        scored_records = []
        for record in records:
            chunk_terms = terms(record["text"])
            overlap = len(query_terms & chunk_terms)
            coverage = overlap / max(1, len(query_terms))
            density = overlap / max(1, math.sqrt(len(chunk_terms)))
            content_score = coverage * 2 + density
            path_overlap = len(query_terms & terms(record.get("source_path", "").replace("/", " ")))
            # A path is useful structural evidence, not a replacement for
            # source content.  Its small capped contribution cannot dominate
            # a strongly relevant chunk with a less obvious filename.
            path_score = min(0.25, path_overlap * 0.10)
            scored_records.append((content_score + path_score, record))
        scored_records.sort(key=lambda item: (-float(item[0] or 0), item[1]["index"]))
        selected_limit = min(top_k, 6) if is_project else top_k
        scored_records = scored_records[:selected_limit]
        method = "lexical-overlap-path-v1" if is_project else "lexical-overlap-v1"

    selected = sorted(scored_records, key=lambda item: item[1]["index"])
    selected_records = [record for _, record in selected]
    if is_project:
        assembled = (
            f"{PROJECT_STRUCTURE_HEADER}\n{project_structure}\n\n{RETRIEVED_CONTEXT_HEADER}\n\n"
            + "\n\n".join(
                f"SOURCE: {record['source_path']}\n{record['text']}" for record in selected_records
            )
        )
    elif method == "lexical-overlap-v1":
        assembled = SNAPSHOT_SEPARATOR.join(record["text"] for record in selected_records)
    else:
        assembled = source
    snapshot = assembled[:max_chars]
    truncated = len(snapshot) < len(assembled)
    selected_ids = [record["chunk_id"] for record in selected_records]
    source_document_ids = list(dict.fromkeys(record["source_document_id"] for record in records))
    available_ids = [record["chunk_id"] for record in records]
    context_hash = _sha256(snapshot)
    snapshot_id = _snapshot_id(
        context_hash=context_hash,
        source_document_ids=source_document_ids,
        chunk_ids=selected_ids,
        settings={**settings, "method": method},
    )
    selected_views = [
        _selected_chunk_view(record, score)
        for score, record in selected
    ]
    return snapshot, {
        "snapshot_version": SNAPSHOT_VERSION,
        "retrieval_config_id": RAG_CONFIG_ID,
        "retrieval_settings_version": RAG_SETTINGS_VERSION,
        "snapshot_id": snapshot_id,
        "snapshot_hash": context_hash,
        "context_hash": context_hash,
        "source_document_ids": source_document_ids,
        "source_documents": (
            [{
                "document_id": source_document_id,
                "format": "textual",
                "source_hash": _sha256(source_document_id),
                "char_count": sum(record["char_count"] for record in records if record["source_document_id"] == source_document_id),
                "relative_path": next(record["source_path"] for record in records if record["source_document_id"] == source_document_id),
            } for source_document_id in source_document_ids]
            if is_project else [{
                "document_id": document_id,
                "format": "textual",
                "source_hash": source_hash,
                "char_count": len(source),
            }]
        ),
        "chunk_ids": selected_ids,
        "available_chunk_ids": available_ids,
        "selected_chunks": selected_views,
        "method": method,
        "chunks_total": len(records),
        "chunks_selected": len(selected_records),
        "selected_indices": [record["index"] for record in selected_records],
        "retrieval_settings": {**settings, "method": method},
        "truncation": {
            "applied": truncated,
            "reason": "max_chars" if truncated else None,
            "original_chars": len(source),
            "assembled_chars": len(assembled),
            "context_chars": len(snapshot),
            "dropped_chars": max(0, len(assembled) - len(snapshot)),
        },
        "retrieval_omissions": {
            "applied": bool(set(available_ids) - set(selected_ids)),
            "omitted_chunk_ids": [item for item in available_ids if item not in set(selected_ids)],
            "omitted_chunk_count": len([item for item in available_ids if item not in set(selected_ids)]),
            "reason": "top_k" if set(available_ids) - set(selected_ids) else None,
        },
        "created_at": created_at,
    }
