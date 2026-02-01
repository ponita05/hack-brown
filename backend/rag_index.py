import os
from typing import List, Dict, Any

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

INDEX_DIR = os.environ.get("RAG_INDEX_DIR", "storage")
DOCS_DIR = os.environ.get("RAG_DOCS_DIR", "docs")

_embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

_index = None

def build_or_load_index():
    global _index
    if _index is not None:
        return _index

    # Load existing index if present
    if os.path.exists(INDEX_DIR) and os.path.isdir(INDEX_DIR) and len(os.listdir(INDEX_DIR)) > 0:
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_DIR)
        _index = load_index_from_storage(storage_context, embed_model=_embed_model)
        return _index

    # Build new index
    docs_path = os.path.join(os.path.dirname(__file__), DOCS_DIR)
    documents = SimpleDirectoryReader(docs_path, recursive=True).load_data()
    _index = VectorStoreIndex.from_documents(documents, embed_model=_embed_model)
    _index.storage_context.persist(persist_dir=INDEX_DIR)
    return _index

def rag_retrieve(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    index = build_or_load_index()
    retriever = index.as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(query)

    results = []
    for i, n in enumerate(nodes, start=1):
        meta = n.node.metadata or {}
        results.append({
            "rank": i,
            "score": float(n.score) if n.score is not None else None,
            "text": n.node.get_content(),
            "source": meta.get("file_name") or meta.get("filename") or meta.get("source") or "unknown"
        })
    return results
