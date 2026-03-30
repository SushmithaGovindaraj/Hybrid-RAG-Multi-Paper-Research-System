"""
FastAPI Backend — Research Paper Assistant
Endpoints:
  POST /upload              — upload & index a PDF
  GET  /papers              — list all indexed papers
  DELETE /papers/{paper_id} — remove a paper
  POST /ask                 — Q&A / comparison (non-streaming)
  POST /ask/stream          — Q&A / comparison (SSE streaming)
  POST /summarize/{paper_id}— structured paper summary
  GET  /health              — health check
"""

import os
import uuid
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

"""
Main entry point for the FastAPI research service.
Handles SSE streams and vector database management.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

logger = logging.getLogger("papermind")

import pdf_processor as pp
import vector_store as vs
import rag_pipeline as rp

# ── lifespan: pre-warm embedding model so first upload is instant ─────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    import sys
    print("[startup] Pre-loading embedding model…", flush=True)
    try:
        # Load synchronously — safe at startup, only blocks during boot
        vs.get_embed_model()
        print("[startup] Embedding model ready.", flush=True)
    except Exception as e:
        import traceback
        print(f"[startup] ERROR loading model: {traceback.format_exc()}", flush=True)
    yield  # server runs here

# ── config ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
CHROMA_DIR  = str(BASE_DIR / os.getenv("CHROMA_DB_DIR", "chroma_db"))
CHUNK_SIZE  = int(os.getenv("CHUNK_SIZE", 800))
CHUNK_OV    = int(os.getenv("CHUNK_OVERLAP", 150))
TOP_K       = int(os.getenv("TOP_K_RESULTS", 6))
MAX_MB      = int(os.getenv("MAX_FILE_SIZE_MB", 50))
PAPERS_META = BASE_DIR / "papers_meta.json"

UPLOAD_DIR.mkdir(exist_ok=True)

# ── paper metadata store (persisted as JSON) ──────────────────────────────────
def load_meta() -> dict:
    if PAPERS_META.exists():
        return json.loads(PAPERS_META.read_text())
    return {}

def save_meta(meta: dict):
    PAPERS_META.write_text(json.dumps(meta, indent=2))

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Research Paper Assistant API",
    description="Hybrid RAG for academic papers with exact citations",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── models ────────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    paper_ids: Optional[List[str]] = None   # None = all papers
    top_k: int = 6


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    chunk_count = vs.get_chunk_count(CHROMA_DIR)
    papers = load_meta()
    return {
        "status": "ok",
        "papers_indexed": len(papers),
        "total_chunks": chunk_count,
    }


@app.get("/papers")
async def list_papers():
    meta = load_meta()
    return {"papers": list(meta.values())}


@app.post("/upload")
async def upload_paper(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")

    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_MB} MB limit.")

    paper_id = str(uuid.uuid4())
    safe_name = file.filename.replace(" ", "_")
    pdf_path  = UPLOAD_DIR / f"{paper_id}_{safe_name}"

    pdf_path.write_bytes(content)

    try:
        # Run CPU-bound work in a thread so the event loop stays responsive
        def process_pdf():
            pdf_meta = pp.get_paper_metadata(str(pdf_path))
            pages    = pp.extract_pages(str(pdf_path), paper_id, safe_name)
            chunks   = pp.chunk_pages(pages, chunk_size=CHUNK_SIZE, overlap=CHUNK_OV)
            return pdf_meta, chunks

        pdf_meta, chunks = await asyncio.to_thread(process_pdf)

        if not chunks:
            pdf_path.unlink()
            raise HTTPException(422, "Could not extract text from this PDF.")

        num_chunks = await asyncio.to_thread(vs.add_chunks, chunks, CHROMA_DIR)

        meta = load_meta()
        meta[paper_id] = {
            "paper_id":   paper_id,
            "filename":   safe_name,
            "title":      pdf_meta["title"],
            "author":     pdf_meta["author"],
            "page_count": pdf_meta["page_count"],
            "num_chunks": num_chunks,
            "file_path":  str(pdf_path),
        }
        save_meta(meta)

        return {
            "paper_id":   paper_id,
            "filename":   safe_name,
            "title":      pdf_meta["title"],
            "page_count": pdf_meta["page_count"],
            "num_chunks": num_chunks,
            "message":    f"Indexed {num_chunks} chunks from {pdf_meta['page_count']} pages.",
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[upload] FAILED for {safe_name}: {traceback.format_exc()}")
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Processing failed: {str(e)}")


@app.delete("/papers/{paper_id}")
async def delete_paper(paper_id: str):
    meta = load_meta()
    if paper_id not in meta:
        raise HTTPException(404, "Paper not found.")

    info = meta.pop(paper_id)
    save_meta(meta)

    vs.delete_paper(paper_id, CHROMA_DIR)

    pdf_path = Path(info.get("file_path", ""))
    pdf_path.unlink(missing_ok=True)

    return {"message": f"Removed '{info['filename']}' from the index."}


@app.post("/ask")
async def ask(req: AskRequest):
    """Non-streaming Q&A (fallback)."""
    if not req.question.strip():
        raise HTTPException(400, "Question cannot be empty.")

    meta = load_meta()
    if not meta:
        raise HTTPException(400, "No papers uploaded yet. Please upload PDFs first.")

    if req.paper_ids:
        invalid = [p for p in req.paper_ids if p not in meta]
        if invalid:
            raise HTTPException(400, f"Unknown paper IDs: {invalid}")

    result = rp.answer_question(
        question=req.question,
        db_path=CHROMA_DIR,
        paper_ids=req.paper_ids,
        top_k=req.top_k or TOP_K,
    )
    return result


@app.post("/ask/stream")
async def ask_stream(req: AskRequest):
    """Streaming Q&A via Server-Sent Events."""
    if not req.question.strip():
        raise HTTPException(400, "Question cannot be empty.")

    meta = load_meta()
    if not meta:
        raise HTTPException(400, "No papers uploaded yet. Please upload PDFs first.")

    if req.paper_ids:
        invalid = [p for p in req.paper_ids if p not in meta]
        if invalid:
            raise HTTPException(400, f"Unknown paper IDs: {invalid}")

    async def event_stream():
        try:
            # Retrieve chunks (embedding is CPU-bound — run in thread)
            hits = await asyncio.to_thread(
                vs.query, req.question, CHROMA_DIR, req.paper_ids, req.top_k or TOP_K
            )

            if not hits:
                yield _sse({"type": "error", "message": "No relevant content found in the uploaded papers."})
                return

            # Send metadata (citations) before the text starts
            is_compare = rp._is_comparison(req.question, req.paper_ids)
            citations  = rp._build_citations(hits)
            unique_papers = list({h["filename"] for h in hits})

            yield _sse({
                "type": "meta",
                "citations": citations,
                "sources_used": len(hits),
                "papers_referenced": unique_papers,
                "is_comparison": is_compare,
            })

            # Stream LLM response token by token
            async for chunk in rp.stream_answer_async(req.question, hits, is_compare):
                                    # Stream chunk to frontend
                    yield _sse({"type": "chunk", "text": chunk})

            yield _sse({"type": "done"})

        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/summarize/{paper_id}")
async def summarize(paper_id: str):
    meta = load_meta()
    if paper_id not in meta:
        raise HTTPException(404, "Paper not found.")

    info = meta[paper_id]
    result = rp.summarize_paper(
        paper_id=paper_id,
        paper_name=info["title"],
        db_path=CHROMA_DIR,
    )
    return result


# ── helpers ───────────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
# environment verification
