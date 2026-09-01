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


def normalize_source(source: str) -> str:
    """Normalize supported textual uploads without executing or interpreting them."""
    text = unicodedata.normalize("NFC", str(source or ""))
    text = text.replace("\ufeff", "", 1).replace("\x00", "")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def terms(text: str) -> set[str]:
    return {x for x in re.findall(r"[A-Za-zÀ-ỹ0-9_'-]{2,}", text.lower()) if x not in STOP}


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
    return result


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

    document_id = _document_id(source)
    source_hash = _sha256(source)
    records = _chunk_records(source, document_id, DEFAULT_CHUNK_CHARS)
    scored_records: list[tuple[float | None, dict]] = [(None, record) for record in records]
    method = "full-small-context"

    if len(source) > max_chars and len(records) > top_k:
        query_terms = terms(task)
        scored_records = []
        for record in records:
            chunk_terms = terms(record["text"])
            overlap = len(query_terms & chunk_terms)
            coverage = overlap / max(1, len(query_terms))
            density = overlap / max(1, math.sqrt(len(chunk_terms)))
            scored_records.append((coverage * 2 + density, record))
        scored_records.sort(key=lambda item: (-float(item[0] or 0), item[1]["index"]))
        scored_records = scored_records[:top_k]
        method = "lexical-overlap-v1"

    selected = sorted(scored_records, key=lambda item: item[1]["index"])
    selected_records = [record for _, record in selected]
    if method == "lexical-overlap-v1":
        assembled = SNAPSHOT_SEPARATOR.join(record["text"] for record in selected_records)
    else:
        assembled = source
    snapshot = assembled[:max_chars]
    truncated = len(snapshot) < len(assembled)
    selected_ids = [record["chunk_id"] for record in selected_records]
    source_document_ids = [document_id]
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
        "source_documents": [{
            "document_id": document_id,
            "format": "textual",
            "source_hash": source_hash,
            "char_count": len(source),
        }],
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
