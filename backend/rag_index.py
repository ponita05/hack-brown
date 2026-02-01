# backend/rag_index.py
import os, json, glob, re
from typing import List, Dict, Any, Optional

import numpy as np
import faiss

from sentence_transformers import SentenceTransformer

# -----------------------
# Config
# -----------------------
DOCS_DIR = os.environ.get("RAG_DOCS_DIR", os.path.join(os.path.dirname(__file__), "rag_docs"))
STORE_DIR = os.environ.get("RAG_STORE_DIR", os.path.join(os.path.dirname(__file__), "rag_store"))

INDEX_PATH = os.path.join(STORE_DIR, "index.faiss")
META_PATH = os.path.join(STORE_DIR, "meta.json")

# chunk params (너무 크면 느리고, 너무 작으면 문맥 부족)
CHUNK_CHARS = int(os.environ.get("RAG_CHUNK_CHARS", "900"))
OVERLAP_CHARS = int(os.environ.get("RAG_OVERLAP_CHARS", "150"))

# embedding model (빠르고 무난)
EMBED_MODEL_NAME = os.environ.get("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# -----------------------
# Globals (lazy load)
# -----------------------
_model: Optional[SentenceTransformer] = None
_index: Optional[faiss.Index] = None
_meta: Optional[List[Dict[str, Any]]] = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model


def _normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _chunk_text(text: str, source: str) -> List[Dict[str, Any]]:
    """
    아주 단순하지만 꽤 잘 먹히는 chunking:
    - 글을 일정 길이(문자 기준)로 자르고 overlap 줌
    - metadata에 source, chunk_id 저장
    """
    text = _normalize_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    cid = 0
    n = len(text)

    while start < n:
        end = min(start + CHUNK_CHARS, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({
                "text": chunk,
                "source": source,
                "chunk_id": cid,
            })
            cid += 1
        start = max(end - OVERLAP_CHARS, end)  # overlap
        if end == n:
            break

    return chunks


def _read_markdown_files() -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(os.path.join(DOCS_DIR, "**/*.md"), recursive=True))
    all_chunks: List[Dict[str, Any]] = []

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue

        rel = os.path.relpath(p, DOCS_DIR)
        chunks = _chunk_text(text, source=rel)
        all_chunks.extend(chunks)

    return all_chunks


def _embed_texts(texts: List[str]) -> np.ndarray:
    model = _get_model()
    # normalize_embeddings=True 로 코사인 유사도에 유리 (dot = cosine)
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return np.array(vecs, dtype=np.float32)


def build_or_load_index(force_rebuild: bool = False) -> None:
    """
    - rag_docs/*.md 읽어서 chunk 만들고
    - embedding 만든 뒤
    - FAISS index 저장/로드
    """
    global _index, _meta

    os.makedirs(STORE_DIR, exist_ok=True)

    if (not force_rebuild) and os.path.exists(INDEX_PATH) and os.path.exists(META_PATH):
        _index = faiss.read_index(INDEX_PATH)
        with open(META_PATH, "r", encoding="utf-8") as f:
            _meta = json.load(f)
        return

    chunks = _read_markdown_files()
    if not chunks:
        # 빈 인덱스
        dim = 384  # all-MiniLM-L6-v2 dim
        _index = faiss.IndexFlatIP(dim)
        _meta = []
        faiss.write_index(_index, INDEX_PATH)
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(_meta, f, ensure_ascii=False, indent=2)
        return

    texts = [c["text"] for c in chunks]
    vecs = _embed_texts(texts)  # (N, D)
    dim = vecs.shape[1]

    # cosine similarity = inner product (벡터 normalize 했으니까)
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    _index = index
    _meta = chunks

    faiss.write_index(_index, INDEX_PATH)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(_meta, f, ensure_ascii=False, indent=2)


def rag_retrieve(query: str, top_k: int = 6) -> List[Dict[str, Any]]:
    """
    returns:
      [
        {"rank": 1, "score": 0.77, "text": "...", "source": "toilet_clog.md", "chunk_id": 3},
        ...
      ]
    """
    global _index, _meta
    if _index is None or _meta is None:
        build_or_load_index(force_rebuild=False)

    if not query or not query.strip():
        return []

    if _index.ntotal == 0:
        return []

    qv = _embed_texts([query])  # (1, D)
    scores, idxs = _index.search(qv, top_k)

    out: List[Dict[str, Any]] = []
    for rank, (i, s) in enumerate(zip(idxs[0].tolist(), scores[0].tolist()), start=1):
        if i < 0 or i >= len(_meta):
            continue
        m = _meta[i]
        out.append({
            "rank": rank,
            "score": float(s),
            "text": m["text"],
            "source": m.get("source", "docs"),
            "chunk_id": m.get("chunk_id", None),
        })
    return out


if __name__ == "__main__":
    # 로컬에서 인덱스만 먼저 만들고 싶을 때:
    build_or_load_index(force_rebuild=True)
    print("✅ built index:", INDEX_PATH)
    print("chunks:", 0 if _meta is None else len(_meta))
