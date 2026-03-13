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
        """
        Initialize a KnowledgeBase instance and configure its filesystem and runtime state.
        
        Sets settings and OpenAI client, ensures the index directory exists, defines paths for embeddings and metadata, and initializes in-memory index state placeholders.
        """
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
        Ensure the in-memory index is loaded and up-to-date from disk.
        
        If both the embeddings file and metadata file exist, load them into the instance when the in-memory data is missing or when the on-disk embeddings file has a newer modification time; update the internal `_loaded_mtime`. If the index files do not exist, initialize `_emb` as an empty embeddings array, `_chunks` as an empty list, and clear `_loaded_mtime`.
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
        Rebuilds the on-disk and in-memory embedding index from documents in the configured docs directory.
        
        Writes computed embeddings to the embeddings file and per-chunk metadata to the metadata file, updates the in-memory embeddings and chunk list, and records the index file modification time. If no chunks are found, clears the index files and resets in-memory state.
        
        Returns:
            dict[str, int]: Mapping with keys:
                - "documents": number of unique source documents indexed.
                - "chunks": total number of chunks indexed.
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
        """
        Search the knowledge base for the chunks most similar to the provided query.
        
        Parameters:
        	query (str): The text query to search for.
        	top_k (int | None): Maximum number of results to return. If None, uses the configured default; the value is clamped to at least 1 and at most the number of indexed chunks.
        
        Returns:
        	results (list[tuple[KBChunk, float]]): A list of (KBChunk, score) tuples sorted by descending score, where `score` is the cosine similarity between the chunk embedding and the query embedding (range approximately -1 to 1). If the index has no chunks, returns an empty list.
        """
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
        """
        Load chunk metadata from the index metadata file.
        
        Reads JSON Lines from self._meta_path (if it exists), parses each non-empty line into a KBChunk, and returns the list of parsed chunks. Missing file or no valid lines results in an empty list.
        
        Returns:
            list[KBChunk]: Parsed chunks with `doc_type` defaulting to "other" and `chunk_id` defaulting to 0 when absent.
        """
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
        """
        Compute vector embeddings for each input string using the configured embedding model.
        
        Parameters:
            texts (list[str]): Input strings to embed; embeddings are returned in the same order.
        
        Returns:
            np.ndarray: 2-D array of dtype `float32` with shape (len(texts), embedding_dim) where each row is the embedding for the corresponding input string.
        """
        resp = await self.client.embeddings.create(model=self.s.kb_embed_model, input=texts)
        vecs = [np.array(d.embedding, dtype=np.float32) for d in resp.data]
        return np.vstack(vecs)

    def _iter_chunks(self, root: Path) -> Iterable[KBChunk]:
        """
        Yield KBChunk objects for each text chunk found under the given root directory for supported document types.
        
        Parameters:
            root (Path): Directory to recursively search for documents.
        
        Yields:
            KBChunk: A chunk with fields `text`, `source` (file path as string), `doc_type` ("pdf", "txt", or "md"), and `chunk_id` (0-based index for the chunk within the source).
        
        Notes:
            - If `root` does not exist, a warning is logged and nothing is yielded.
            - Files with extensions other than .pdf, .txt, .md, or .markdown are skipped.
            - Documents with empty or whitespace-only content are skipped.
        """
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
        """
        Read and extract text from a file at the given path according to its document type.
        
        Returns:
        	Extracted text content of the document. Returns an empty string if the document type is unsupported or text extraction fails (e.g., PDF parsing error).
        """
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
        """
        Split text into consecutive character chunks with a fixed maximum size and overlap.
        
        The text is normalized by collapsing consecutive spaces/tabs into a single space and reducing three or more consecutive newlines to two; leading and trailing whitespace is removed. The function then slices the text into chunks up to `size` characters, advancing by `size - overlap` characters between chunks so adjacent chunks overlap by up to `overlap` characters. Empty chunks are omitted.
        
        Parameters:
            text (str): Input text to be chunked.
            size (int): Maximum number of characters per chunk. Defaults to 1200.
            overlap (int): Number of characters that adjacent chunks should overlap. Defaults to 200.
        
        Returns:
            list[str]: A list of chunk strings, each trimmed of leading/trailing whitespace.
        """
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
