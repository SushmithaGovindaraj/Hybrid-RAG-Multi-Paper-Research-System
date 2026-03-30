"""
Vector Store — ChromaDB + sentence-transformers embeddings.
Supports adding, deleting, and querying chunks with rich metadata filters.
"""

"""
Persistence layer abstraction for ChromaDB.
Implements upsert logic for chunked vector embeddings.
"""
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional
import os
import hashlib


# ── singleton embedding model ────────────────────────────────────────────────
_EMBED_MODEL: Optional[SentenceTransformer] = None

def get_embed_model() -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        print("[VectorStore] Loading embedding model…")
        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        print("[VectorStore] Model ready.")
    return _EMBED_MODEL


def embed(texts: List[str]) -> List[List[float]]:
    model = get_embed_model()
    return model.encode(texts, batch_size=32, show_progress_bar=False).tolist()


# ── ChromaDB client ──────────────────────────────────────────────────────────

_CLIENT: Optional[chromadb.PersistentClient] = None
_COLLECTION = None
_DB_PATH: str = ""

def _get_collection(db_path: str):
    global _CLIENT, _COLLECTION, _DB_PATH
    if _COLLECTION is None or db_path != _DB_PATH:
        _DB_PATH = db_path
        _CLIENT = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
        _COLLECTION = _CLIENT.get_or_create_collection(
            name="research_papers",
            metadata={"hnsw:space": "cosine"},
        )
    return _COLLECTION


# ── public API ───────────────────────────────────────────────────────────────

def add_chunks(chunks: List[Dict[str, Any]], db_path: str) -> int: # type: ignore
    """Embed and upsert a list of chunk dicts into ChromaDB."""
    col = _get_collection(db_path)
    texts, ids, metas = [], [], []

    for ch in chunks:
        uid = hashlib.md5(
            f"{ch['paper_id']}_{ch['page_number']}_{ch['chunk_index']}".encode()
        ).hexdigest()
        texts.append(ch["chunk_text"])
        ids.append(uid)
        metas.append({
            "paper_id":    ch["paper_id"],
            "filename":    ch["filename"],
            "page_number": ch["page_number"],
            "section":     ch["section"],
            "chunk_index": ch["chunk_index"],
        })

    embeddings = embed(texts)
    col.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
    return len(ids)


def delete_paper(paper_id: str, db_path: str):
    """Remove all chunks belonging to a paper."""
    col = _get_collection(db_path)
    col.delete(where={"paper_id": paper_id})


def query(
    question: str,
    db_path: str,
    paper_ids: Optional[List[str]] = None,
    top_k: int = 6,
) -> List[Dict[str, Any]]:
    """
    Semantic search over the vector store.
    If paper_ids is given, restrict to those papers (cross-paper comparison).
    """
    col = _get_collection(db_path)
    q_embed = embed([question])[0]

    where = None
    if paper_ids and len(paper_ids) == 1:
        where = {"paper_id": paper_ids[0]}
    elif paper_ids and len(paper_ids) > 1:
        where = {"paper_id": {"$in": paper_ids}}

    results = col.query(
        query_embeddings=[q_embed],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    docs  = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({
            "text":        doc,
            "score":       round(1 - dist, 4),   # cosine similarity
            "paper_id":    meta["paper_id"],
            "filename":    meta["filename"],
            "page_number": meta["page_number"],
            "section":     meta["section"],
        })

    return hits


def list_papers(db_path: str) -> List[Dict[str, str]]:
    """Return unique papers in the store."""
    col = _get_collection(db_path)
    total = col.count()
    if total == 0:
        return []
    # Sample up to 5000 to find unique paper_ids
    sample = col.get(limit=min(total, 5000), include=["metadatas"])
    seen, papers = set(), []
    for meta in sample["metadatas"]:
        pid = meta["paper_id"]
        if pid not in seen:
            seen.add(pid)
            papers.append({"paper_id": pid, "filename": meta["filename"]})
    return papers


def get_chunk_count(db_path: str) -> int:
    return _get_collection(db_path).count()
