# 🧬 Hybrid-RAG-Multi-Paper-Research-System
### *Advanced Multi-Document Synthesis & Deep Inquiry Platform*

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-white?style=for-the-badge&logo=chroma)](https://www.trychroma.com/)
[![Claude3.5](https://img.shields.io/badge/Claude--3.5--Sonnet-7C3AED?style=for-the-badge)](https://www.anthropic.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

---

## 🚀 Engineering Objective
This platform was engineered to solve the "context window fragmentation" problem in academic research. While standard RAG systems often fail to navigate cross-paper semantic relationships, this system implements a **Hybrid Retrieval** strategy—combining high-dimensional vector search with structured section-level metadata to provide syntheses that aren't just accurate, but cited at the granular level.

## 🏗️ Technical Architecture
### 1. The Ingestion Pipeline (ETL)
*   **Semantic Section Detection:** Utilizes regex-based page structural analysis to identify "Abstract", "Methodology", and "Conclusion" boundaries during PDF parsing.
*   **Structure-Aware Chunking:** Rather than arbitrary character-based splitting, the system chunks based on semantic sections to preserve context.
*   **Vector Persistence:** Optimized `ChromaDB` integration utilizing `sentence-transformers` for local embedding execution.

### 2. Retrieval & Synthesis (Hybrid RAG)
*   **Multi-Stage Retrieval:** Queries the vector database and then filters/ranks based on paper-level IDs, allowing for massive knowledge base scaling.
*   **SSE Streaming:** Implements Server-Sent Events (SSE) via FastAPI to provide a modern, low-latency "real-time thinking" experience in the frontend.
*   **Citation Engine:** Automatic citation mapping that ties every statement in the AI response to a specific PDF, page number, and section.

### 3. Frontend Architecture
*   **Design System:** Built with vanilla CSS/HTML to ensure maximum performance, utilizing a custom glassmorphism design system for a premium aesthetic.
*   **Reactive State:** Managed with a lightweight state object on the client-side for immediate UI updates during multi-file indexing.

---

## 🛠️ Key Engineering Challenges & Solutions

## 📦 Tech Stack
*   **Backend Framework:** FastAPI (Asynchronous execution)
*   **Vector DB:** ChromaDB (Persistence & Search)
*   **PDF Ingestion:** PyMuPDF (`fitz`)
*   **Model Integration:** Anthropic Claude 3.5 Sonnet / Google Gemini 1.5 Pro
*   **Embeddings:** `all-MiniLM-L6-v2` (Sentence Transformers)
*   **Frontend:** HTML5, Premium CSS (Glassmorphism), Vanilla JS

---

## 🚀 Quick Start
1.  **Environment Setup:**
    ```bash
    # Define your ANTHROPIC_API_KEY in .env
    pip install -r requirements.txt
    ```
2.  **Launch Service:**
    ```bash
    python3 main.py
    ```

---

## 🧬 Project Structure
```text
├── main.py              # FastAPI Service & SSE Routing
├── rag_pipeline.py      # LLM Orchestration & Citation Logic
├── vector_store.py      # ChromaDB Persistence Layer
├── pdf_processor.py     # ETL & Semantic Chunking
├── frontend/
│   ├── index.html       # Dashboard Structure
│   ├── app.js           # Client-side State & SSE Consumer
│   └── style.css        # Premium Design System
└── uploads/             # Managed PDF Storage
```

---

## 👨‍💻 Developer
**Sushmitha Govindaraj**
*   📧 [sushmitharaj2000@gmail.com](mailto:sushmitharaj2000@gmail.com)
---
*Developed for excellence in AI-Native Engineering.*
