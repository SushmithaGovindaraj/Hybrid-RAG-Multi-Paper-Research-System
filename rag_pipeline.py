"""
RAG Pipeline — combines retrieval (vector_store) with Claude generation.
Supports:
  - Single-paper Q&A
  - Cross-paper comparison / synthesis
  - Exact citation (filename, page, section) in every answer
  - Streaming responses via AsyncAnthropic
"""

import os
from typing import List, Dict, Any, Optional, AsyncGenerator
import vector_store as vs

# ── Anthropic clients ─────────────────────────────────────────────────────────

_SYNC_CLIENT = None
_ASYNC_CLIENT = None
MODEL = "claude-3-haiku-20240307"


def _get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "your_anthropic_api_key_here":
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Please update your .env file."
        )
    return key


def get_sync_client():
    global _SYNC_CLIENT
    if _SYNC_CLIENT is None:
        import anthropic
        _SYNC_CLIENT = anthropic.Anthropic(api_key=_get_api_key())
    return _SYNC_CLIENT


def get_async_client():
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        import anthropic
        _ASYNC_CLIENT = anthropic.AsyncAnthropic(api_key=_get_api_key())
    return _ASYNC_CLIENT


# ── prompt builders ───────────────────────────────────────────────────────────

def _format_context(hits: List[Dict[str, Any]]) -> str:
    """Format retrieved chunks into a numbered context block."""
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[SOURCE {i}]\n"
            f"Paper: {h['filename']}\n"
            f"Page: {h['page_number']}  |  Section: {h['section']}\n"
            f"Relevance: {h['score']:.2f}\n\n"
            f"{h['text']}\n"
            f"{'─'*60}"
        )
    return "\n".join(parts)


QA_PROMPT = """\
You are an advanced academic research synthesis agent with deep knowledge of scientific literature.

TASK: Answer the user's question based STRICTLY on the provided source excerpts.

RULES:
1. Ground every claim in a specific source — cite as [SOURCE N] inline.
2. Always include exact page numbers and sections when referencing (e.g., "Page 4, Section: Methods").
3. If the question cannot be answered from the sources, say so explicitly.
4. Be precise, structured, and academic in tone.
5. Use bullet points or numbered lists where comparisons or multiple facts are involved.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER (cite sources inline, include page numbers):
"""

COMPARE_PROMPT = """\
You are an advanced academic research synthesis agent specializing in systematic literature review.

TASK: Perform a rigorous cross-paper comparison based on the user's request using the provided excerpts.

RULES:
1. Structure your response with clear headers: ## Overview, ## Method Comparison, ## Key Differences, ## Common Themes, ## Strengths & Weaknesses, ## Summary Table.
2. Cite every claim as [SOURCE N] with page number and section.
3. Be objective and analytical.
4. Highlight agreements and contradictions between papers.
5. End with a concise "## Verdict / Recommendation".

CONTEXT (excerpts from multiple papers):
{context}

COMPARISON REQUEST:
{question}

STRUCTURED COMPARISON:
"""

SUMMARY_PROMPT = """\
You are an academic research summarizer.

TASK: Provide a concise structured summary of this research paper based on the excerpts below.

FORMAT:
## Core Objective
## Methodology
## Key Results
## Main Contributions
## Limitations
## Conclusion

For each section cite relevant sources as [SOURCE N, Page X].

CONTEXT:
{context}

PAPER: {paper_name}

SUMMARY:
"""


def _build_prompt(question: str, hits: List[Dict[str, Any]], is_compare: bool) -> str:
    context = _format_context(hits)
    if is_compare:
        return COMPARE_PROMPT.format(context=context, question=question)
    return QA_PROMPT.format(context=context, question=question)


# ── streaming pipeline ────────────────────────────────────────────────────────

async def stream_answer_async(
    question: str,
    hits: List[Dict[str, Any]],
    is_compare: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from Claude (streaming)."""
    prompt = _build_prompt(question, hits, is_compare)
    client = get_async_client()

    async with client.messages.stream(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


# ── non-streaming pipeline ────────────────────────────────────────────────────

def _generate(prompt: str) -> str:
    """Blocking generation via Claude."""
    client = get_sync_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def answer_question(
    question: str,
    db_path: str,
    paper_ids: Optional[List[str]] = None,
    top_k: int = 6,
) -> Dict[str, Any]:
    """Full RAG pipeline (non-streaming) — used as fallback."""
    hits = vs.query(question, db_path, paper_ids=paper_ids, top_k=top_k)
    if not hits:
        return {
            "answer": "I couldn't find relevant content in the uploaded papers for this question.",
            "citations": [],
            "sources_used": 0,
        }

    is_compare = _is_comparison(question, paper_ids)
    prompt = _build_prompt(question, hits, is_compare)
    answer_text = _generate(prompt)

    return {
        "answer": answer_text,
        "citations": _build_citations(hits),
        "sources_used": len(hits),
        "papers_referenced": list({h["filename"] for h in hits}),
        "is_comparison": is_compare,
    }


def summarize_paper(
    paper_id: str,
    paper_name: str,
    db_path: str,
) -> Dict[str, Any]:
    """Generate a structured summary for a single paper."""
    hits = vs.query(
        "overview methodology results contributions conclusion",
        db_path,
        paper_ids=[paper_id],
        top_k=10,
    )
    if not hits:
        return {"answer": "No content found for this paper.", "citations": []}

    context = _format_context(hits)
    prompt = SUMMARY_PROMPT.format(context=context, paper_name=paper_name)
    answer_text = _generate(prompt)

    return {
        "answer": answer_text,
        "citations": _build_citations(hits),
        "sources_used": len(hits),
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_comparison(question: str, paper_ids: Optional[List[str]]) -> bool:
    q = question.lower()
    keywords = ["compare", "comparison", "contrast", "difference", "similar",
                "versus", "vs", "both papers", "all papers", "across", "between"]
    has_keyword = any(k in q for k in keywords)
    multi_paper = paper_ids is None or len(paper_ids) > 1
    return has_keyword and multi_paper


def _build_citations(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicated, sorted citation list."""
    seen, citations = set(), []
    for i, h in enumerate(hits, 1):
        key = f"{h['filename']}_{h['page_number']}_{h['section']}"
        if key not in seen:
            seen.add(key)
            citations.append({
                "source_num": i,
                "filename": h["filename"],
                "page": h["page_number"],
                "section": h["section"],
                "score": h["score"],
                "snippet": h["text"][:200] + "…",
            })
    return sorted(citations, key=lambda x: -x["score"])
