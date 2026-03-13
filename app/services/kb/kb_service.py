from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.clients.openai_client import get_openai_client

logger = get_logger(__name__)

DocType = Literal["pdf", "txt", "md", "other"]


@dataclass
class KBChunk:
    text: str
    source: str      # full path string
    doc_type: DocType
    chunk_id: int


class KnowledgeBase:
    """
    Lightweight local RAG index:
    - Read docs from KB_DOCS_PATH
    - Create embeddings via OpenAI
    - Persist to KB_INDEX_DIR (embeddings.npy + chunks.jsonl)
    - Cosine similarity search at query time
    """

    def __init__(self) -> None:
        self.s = get_settings()
        self.client = get_openai_client()

        self.docs_dir = Path(self.s.kb_docs_path)
        self.index_dir = Path(self.s.kb_index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self._emb_path = self.index_dir / "embeddings.npy"
        self._meta_path = self.index_dir / "chunks.jsonl"

        self._emb: np.ndarray | None = None
        self._chunks: list[KBChunk] | None = None
        self._loaded_mtime: float | None = None  # lets the bot pick up new reindex results without restart

    async def ensure_loaded(self) -> None:
        """
        Load index from disk if needed, or reload if the index file changed.
        """
        if self._emb_path.exists() and self._meta_path.exists():
            mtime = self._emb_path.stat().st_mtime
            if self._emb is None or self._chunks is None or self._loaded_mtime != mtime:
                self._emb = np.load(self._emb_path)
                self._chunks = self._load_chunks()
                self._loaded_mtime = mtime
            return

        # No index yet
        self._emb = np.zeros((0, 1), dtype=np.float32)
        self._chunks = []
        self._loaded_mtime = None

    async def reindex(self) -> dict[str, int]:
        """
        (Re)build index from docs folder.
        """
        chunks = list(self._iter_chunks(self.docs_dir))
        if not chunks:
            np.save(self._emb_path, np.zeros((0, 1), dtype=np.float32))
            self._meta_path.write_text("", encoding="utf-8")
            self._emb = np.zeros((0, 1), dtype=np.float32)
            self._chunks = []
            self._loaded_mtime = self._emb_path.stat().st_mtime if self._emb_path.exists() else None
            return {"documents": 0, "chunks": 0}

        texts = [c.text for c in chunks]
        emb = await self._embed(texts)

        np.save(self._emb_path, emb)
        with self._meta_path.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(
                    json.dumps(
                        {
                            "text": c.text,
                            "source": c.source,
                            "doc_type": c.doc_type,
                            "chunk_id": c.chunk_id,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        self._emb = emb
        self._chunks = chunks
        self._loaded_mtime = self._emb_path.stat().st_mtime
        return {"documents": len({c.source for c in chunks}), "chunks": len(chunks)}

    async def search(self, query: str, top_k: int | None = None) -> list[tuple[KBChunk, float]]:
        await self.ensure_loaded()
        assert self._emb is not None and self._chunks is not None

        if not self._chunks:
            return []

        q = (await self._embed([query]))[0]
        q = q / (np.linalg.norm(q) + 1e-12)

        emb = self._emb
        norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
        embn = emb / norms
        scores = embn @ q

        k = int(top_k or self.s.kb_top_k)
        k = max(1, min(k, len(self._chunks)))

        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self._chunks[i], float(scores[i])) for i in idx]

    def _load_chunks(self) -> list[KBChunk]:
        chunks: list[KBChunk] = []
        if not self._meta_path.exists():
            return chunks
        with self._meta_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                chunks.append(
                    KBChunk(
                        text=obj["text"],
                        source=obj["source"],
                        doc_type=obj.get("doc_type", "other"),
                        chunk_id=int(obj.get("chunk_id", 0)),
                    )
                )
        return chunks

    async def _embed(self, texts: list[str]) -> np.ndarray:
        resp = await self.client.embeddings.create(model=self.s.kb_embed_model, input=texts)
        vecs = [np.array(d.embedding, dtype=np.float32) for d in resp.data]
        return np.vstack(vecs)

    def _iter_chunks(self, root: Path) -> Iterable[KBChunk]:
        if not root.exists():
            logger.warning("kb_docs_path_missing", path=str(root))
            return

        for p in sorted(root.rglob("*")):
            if p.is_dir():
                continue

            ext = p.suffix.lower()
            if ext == ".pdf":
                doc_type: DocType = "pdf"
            elif ext == ".txt":
                doc_type = "txt"
            elif ext in {".md", ".markdown"}:
                doc_type = "md"
            else:
                continue

            text = self._read_doc(p, doc_type)
            if not text.strip():
                continue

            for i, chunk in enumerate(self._chunk_text(text)):
                yield KBChunk(text=chunk, source=str(p), doc_type=doc_type, chunk_id=i)

    def _read_doc(self, path: Path, doc_type: DocType) -> str:
        if doc_type in {"txt", "md"}:
            return path.read_text(encoding="utf-8", errors="ignore")

        # PDF
        try:
            from pypdf import PdfReader  # pip install pypdf

            reader = PdfReader(str(path))
            pages: list[str] = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)
        except Exception as e:
            logger.warning("kb_pdf_read_failed", path=str(path), error=str(e))
            return ""

    def _chunk_text(self, text: str, size: int = 1200, overlap: int = 200) -> list[str]:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) <= size:
            return [text]

        out: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            chunk = text[start:end].strip()
            if chunk:
                out.append(chunk)
            if end == len(text):
                break
            start = max(0, end - overlap)
        return out
