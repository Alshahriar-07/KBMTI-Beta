"""Versioned, deterministic retrieval over the curated trading corpus.

There is no vector database and no network call. Documents are split at Markdown
headings; a query is scored by token overlap with the heading, tags and body. Ties are
broken by document id so the same query always returns the same ordered references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.intelligence.contracts import KnowledgeHit, KnowledgeSearchResponse

CORPUS_VERSION = "trading-knowledge-1.0.0"
KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"

_META = re.compile(r"^<!--\s*(.*?)\s*-->$", re.MULTILINE)
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "has",
    "have",
    "not",
    "but",
    "into",
    "over",
    "under",
    "when",
    "then",
    "than",
    "its",
    "can",
    "will",
    "may",
    "must",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "is",
    "it",
    "as",
    "be",
    "or",
}


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOP and len(token) > 1]


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    doc_id: str
    version: str
    title: str
    text: str
    tags: str


class KnowledgeBase:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or KNOWLEDGE_DIR
        self._chunks = self._load()
        self._by_id = {chunk.id: chunk for chunk in self._chunks}

    def _load(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        if not self.directory.is_dir():
            return chunks
        for path in sorted(self.directory.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            meta_match = _META.search(raw)
            meta = meta_match.group(1) if meta_match else ""
            id_match = re.search(r"\bid:\s*([\w.-]+)", meta)
            version_match = re.search(r"\bversion:\s*([\w.-]+)", meta)
            tags_match = re.search(r"\btags:\s*(.*)$", meta)
            doc_id = id_match.group(1) if id_match else path.stem
            version = version_match.group(1) if version_match else "1.0.0"
            tags = tags_match.group(1).strip() if tags_match else ""
            body = _META.sub("", raw, count=1).strip()
            sections = re.split(r"(?m)^##\s+", body)
            preamble = sections[0].strip()
            if preamble:
                chunks.append(
                    KnowledgeChunk(
                        id=f"{doc_id}#overview",
                        doc_id=doc_id,
                        version=version,
                        title=path.stem.replace("-", " ").title(),
                        text=preamble,
                        tags=tags,
                    )
                )
            for section in sections[1:]:
                lines = section.strip().splitlines()
                if not lines:
                    continue
                title = lines[0].strip()
                text = "\n".join(lines[1:]).strip()
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "section"
                chunks.append(
                    KnowledgeChunk(
                        id=f"{doc_id}#{slug}",
                        doc_id=doc_id,
                        version=version,
                        title=title,
                        text=text or title,
                        tags=tags,
                    )
                )
        return chunks

    @property
    def document_count(self) -> int:
        return len({chunk.doc_id for chunk in self._chunks})

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(self, query: str, *, limit: int = 4) -> KnowledgeSearchResponse:
        terms = _tokens(query)
        hits: list[KnowledgeHit] = []
        for chunk in self._chunks:
            haystack = f"{chunk.title} {chunk.tags} {chunk.text}".lower()
            chunk_terms = set(_tokens(haystack))
            if not terms or not chunk_terms:
                score = 0.0
            else:
                overlap = sum(1 for term in terms if term in chunk_terms)
                phrase = 1.0 if query.strip().lower() in haystack else 0.0
                score = overlap / max(1, len(set(terms))) + phrase
            if score > 0 or not terms:
                hits.append(
                    KnowledgeHit(
                        id=chunk.id,
                        version=chunk.version,
                        title=chunk.title,
                        text=chunk.text,
                        score=round(score, 4),
                        refs=[f"knowledge:{chunk.id}@{chunk.version}"],
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.id))
        limit = max(1, min(int(limit), 10))
        selected = hits[:limit]
        return KnowledgeSearchResponse(
            query=query,
            hits=selected,
            count=len(selected),
            corpus_version=CORPUS_VERSION,
        )

    def get(self, hit_id: str) -> KnowledgeChunk | None:
        return self._by_id.get(hit_id)


__all__ = ["CORPUS_VERSION", "KnowledgeBase", "KnowledgeChunk"]
