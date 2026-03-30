/**
 * PaperMind Frontend Logic
 * Handles: streaming API interaction, UI state, citation rendering, file uploads
 */

// ── STATE ────────────────────────────────────────────────────────────────────
const state = {
    papers: [],
    selectedPaperIds: [],
    mode: 'ask', // 'ask', 'compare', 'summarize'
    isGenerating: false,
    messages: [],
    currentCitations: [],
};

// ── DOM ELEMENTS ─────────────────────────────────────────────────────────────
const els = {
    uploadZone: document.getElementById('uploadZone'),
    fileInput: document.getElementById('fileInput'),
    papersList: document.getElementById('papersList'),
    paperCount: document.getElementById('paperCount'),
    uploadProgress: document.getElementById('uploadProgress'),
    progressFill: document.getElementById('progressFill'),
    progressLabel: document.getElementById('progressLabel'),

    modeBtns: document.querySelectorAll('.mode-btn'),
    topbarTitle: document.getElementById('topbarTitle'),

    welcomeScreen: document.getElementById('welcomeScreen'),
    chatArea: document.getElementById('chatArea'),
    messagesContainer: document.getElementById('messagesContainer'),

    questionInput: document.getElementById('questionInput'),
    sendBtn: document.getElementById('sendBtn'),
    clearChatBtn: document.getElementById('clearChatBtn'),

    paperFilter: document.getElementById('paperFilter'),
    filterTags: document.getElementById('filterTags'),
    selectedPapersHint: document.getElementById('selectedPapersHint'),

    citationsPanel: document.getElementById('citationsPanel'),
    citationsList: document.getElementById('citationsList'),
    closeCitations: document.getElementById('closeCitations'),

    statPapers: document.getElementById('statPapers'),
    statChunks: document.getElementById('statChunks'),

    sidebar: document.getElementById('sidebar'),
    sidebarToggle: document.getElementById('sidebarToggle'),
};

// ── INITIALIZATION ────────────────────────────────────────────────────────────
function init() {
    fetchPapers();
    attachEventListeners();
    updateModeUI('ask');
}

function attachEventListeners() {
    // Upload
    els.uploadZone.addEventListener('click', () => els.fileInput.click());
    els.fileInput.addEventListener('change', handleFileSelect);

    els.uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        els.uploadZone.classList.add('dragover');
    });
    els.uploadZone.addEventListener('dragleave', () => {
        els.uploadZone.classList.remove('dragover');
    });
    els.uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        els.uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
    });

    // Chat
    els.sendBtn.addEventListener('click', handleSend);
    els.questionInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
    });
    els.questionInput.addEventListener('input', () => {
        els.questionInput.style.height = 'auto';
        els.questionInput.style.height = els.questionInput.scrollHeight + 'px';
    });

    els.clearChatBtn.addEventListener('click', () => {
        state.messages = [];
        els.messagesContainer.innerHTML = '';
        els.welcomeScreen.classList.remove('hidden');
        els.chatArea.classList.add('hidden');
    });

    // Mode
    els.modeBtns.forEach(btn => {
        btn.addEventListener('click', () => updateModeUI(btn.dataset.mode));
    });

    // Sidebar / panels
    els.sidebarToggle.addEventListener('click', () => els.sidebar.classList.toggle('collapsed'));
    els.closeCitations.addEventListener('click', () => els.citationsPanel.classList.add('hidden'));

    // Quick prompts
    document.querySelectorAll('.qp-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            els.questionInput.value = btn.dataset.prompt;
            els.questionInput.dispatchEvent(new Event('input'));
            handleSend();
        });
    });
}

// ── API CALLS ──────────────────────────────────────────────────────────────────
    /**
     * Syncs with backend for paper metadata.
     */
    async function fetchPapers() {
    try {
        const res = await fetch('/papers');
        if (!res.ok) throw new Error('Failed to fetch');
        const data = await res.json();
        state.papers = data.papers;
        renderPapers();
        updateStats();
    } catch {
        showToast('Failed to connect to server', 'error');
    }
}

    /**
     * Manages parallel file uploads and indexing status.
     */
    async function uploadFiles(files) {
    els.uploadProgress.classList.remove('hidden');
    const total = files.length;
    let done = 0;

    for (const file of Array.from(files)) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showToast(`Skipping ${file.name}: only PDFs allowed`, 'warning');
            done++;
            continue;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            els.progressLabel.textContent = `Uploading ${file.name}…`;
            const res = await fetch('/upload', { method: 'POST', body: formData });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
                throw new Error(err.detail || 'Upload failed');
            }
            done++;
            els.progressFill.style.width = `${(done / total) * 100}%`;
            showToast(`Indexed ${file.name}`, 'info');
        } catch (err) {
            showToast(`Failed: ${err.message}`, 'error');
            done++;
        }
    }

    els.progressLabel.textContent = 'Optimizing indexes...';
    await fetchPapers();
    setTimeout(() => {
        els.uploadProgress.classList.add('hidden');
        els.progressFill.style.width = '0%';
        els.progressLabel.textContent = 'Ready for analysis';
    }, 1200);
}

    /**
     * Orchestrates user query processing and message history.
     */
    async function handleSend() {
    const query = els.questionInput.value.trim();
    if (!query || state.isGenerating) return;

    if (state.papers.length === 0) {
        showToast('Please upload a paper first.', 'warning');
        return;
    }

    els.welcomeScreen.classList.add('hidden');
    els.chatArea.classList.remove('hidden');
    els.questionInput.value = '';
    els.questionInput.style.height = 'auto';

    addMessage('user', query);
    const aiMsgId = addMessage('ai', '', true);
    scrollToBottom();

    state.isGenerating = true;
    els.sendBtn.disabled = true;

    try {
        if (state.mode === 'summarize') {
            const pid = state.selectedPaperIds[0] || state.papers[0].paper_id;
            const res = await fetch(`/summarize/${pid}`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Summarize failed' }));
                throw new Error(err.detail);
            }
            const data = await res.json();
            finalizeAIMessage(aiMsgId, data);
        } else {
            const payload = {
                question: query,
                paper_ids: state.selectedPaperIds.length > 0 ? state.selectedPaperIds : null,
                top_k: 8,
            };
            await streamResponse(payload, aiMsgId);
        }
    } catch (err) {
        finalizeAIMessage(aiMsgId, { answer: `**Error:** ${err.message}` });
    } finally {
        state.isGenerating = false;
        els.sendBtn.disabled = false;
        scrollToBottom();
    }
}

async function streamResponse(payload, aiMsgId) {
    const res = await fetch('/ask/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || 'Streaming failed');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    let metaData = null;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop(); // Keep the incomplete trailing chunk

        for (const part of parts) {
            if (!part.startsWith('data: ')) continue;
            let event;
            try { event = JSON.parse(part.slice(6)); } catch { continue; }

            if (event.type === 'meta') {
                metaData = event;
            } else if (event.type === 'chunk') {
                fullText += event.text;
                streamToAIMessage(aiMsgId, fullText);
                scrollToBottom();
            } else if (event.type === 'error') {
                throw new Error(event.message);
            } else if (event.type === 'done') {
                break;
            }
        }
    }

    // Finalize with citations
    finalizeAIMessage(aiMsgId, {
        answer: fullText,
        citations: metaData?.citations || [],
        sources_used: metaData?.sources_used || 0,
        papers_referenced: metaData?.papers_referenced || [],
    });
}

async function deletePaper(paperId, e) {
    e.stopPropagation();
    if (!confirm('Remove this paper from the index?')) return;

    try {
        const res = await fetch(`/papers/${paperId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');
        state.selectedPaperIds = state.selectedPaperIds.filter(id => id !== paperId);
        await fetchPapers();
        showToast('Paper removed.', 'info');
    } catch {
        showToast('Delete failed', 'error');
    }
}

// ── UI RENDERING ──────────────────────────────────────────────────────────────

function renderPapers() {
    els.papersList.innerHTML = '';
    els.paperCount.textContent = state.papers.length;

    if (state.papers.length === 0) {
        els.papersList.innerHTML = `<div class="empty-papers">📭 No papers yet</div>`;
        return;
    }

    state.papers.forEach((p, index) => {
        const div = document.createElement('div');
        div.className = `paper-item ${state.selectedPaperIds.includes(p.paper_id) ? 'selected' : ''}`;
        div.style.animationDelay = `${index * 0.05}s`;
        div.innerHTML = `
            <div class="paper-item-icon">📄</div>
            <div class="paper-item-info">
                <div class="paper-title" title="${escapeAttr(p.title)}">${escapeHtml(p.title)}</div>
                <div class="paper-meta">
                    <span>${p.page_count} pgs</span>
                    <span>${p.num_chunks || 0} fragments</span>
                </div>
            </div>
            <button class="delete-paper" title="Remove paper">✕</button>
        `;
        div.addEventListener('click', () => togglePaperSelection(p.paper_id));
        div.querySelector('.delete-paper').addEventListener('click', (e) => deletePaper(p.paper_id, e));
        els.papersList.appendChild(div);
    });

    renderFilterTags();
}

function renderFilterTags() {
    els.filterTags.innerHTML = '';
    state.papers.forEach(p => {
        const tag = document.createElement('div');
        tag.className = `filter-tag ${state.selectedPaperIds.includes(p.paper_id) ? 'active' : ''}`;
        const name = p.filename.length > 20 ? p.filename.substring(0, 17) + '…' : p.filename;
        tag.textContent = name;
        tag.addEventListener('click', () => togglePaperSelection(p.paper_id));
        els.filterTags.appendChild(tag);
    });
    updateHint();
}

function togglePaperSelection(id) {
    if (state.selectedPaperIds.includes(id)) {
        state.selectedPaperIds = state.selectedPaperIds.filter(i => i !== id);
    } else {
        state.selectedPaperIds.push(id);
    }
    renderPapers();
}

function updateModeUI(mode) {
    state.mode = mode;
    els.modeBtns.forEach(b => b.classList.toggle('active', b.dataset.mode === mode));

    if (mode === 'ask') {
        els.topbarTitle.textContent = 'Ask anything about your papers';
        els.paperFilter.classList.add('hidden');
        els.questionInput.placeholder = "Ask a question… e.g. 'What is the main contribution?'";
    } else if (mode === 'compare') {
        els.topbarTitle.textContent = 'Cross-paper comparison';
        els.paperFilter.classList.remove('hidden');
        els.questionInput.placeholder = "Compare papers… e.g. 'Compare the accuracy results across papers'";
    } else if (mode === 'summarize') {
        els.topbarTitle.textContent = 'Paper Summarization';
        els.paperFilter.classList.remove('hidden');
        els.questionInput.placeholder = "Select a paper then press Enter to summarize";
    }
    updateHint();
}

function updateHint() {
    els.selectedPapersHint.textContent = state.selectedPaperIds.length === 0
        ? 'All papers selected'
        : `${state.selectedPaperIds.length} paper(s) selected`;
}

function addMessage(role, text, isLoading = false) {
    const id = 'msg-' + Date.now();
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.id = id;
    div.innerHTML = `
        <div class="message-header">
            <span class="message-${role}">${role === 'user' ? '👤 YOU' : '🧠 AI'}</span>
        </div>
        <div class="message-content">
            ${isLoading ? '<div class="loading-dots">Thinking</div>' : formatMarkdown(text)}
        </div>
    `;
    els.messagesContainer.appendChild(div);
    state.messages.push({ id, role, text });
    return id;
}

function streamToAIMessage(id, text) {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector('.message-content').innerHTML =
        formatMarkdown(text) + '<span class="streaming-cursor"></span>';
}

function finalizeAIMessage(id, data) {
    const el = document.getElementById(id);
    if (!el) return;
    const contentEl = el.querySelector('.message-content');
    contentEl.innerHTML = formatMarkdown(data.answer || '');

    if (data.citations && data.citations.length > 0) {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'message-meta';
        metaDiv.innerHTML = `
            <span style="font-size:0.75rem;color:var(--text-muted)">
                Found in ${data.sources_used} excerpt${data.sources_used !== 1 ? 's' : ''}
            </span>
            <button class="view-citations-btn">View ${data.citations.length} Citations 📍</button>
        `;
        metaDiv.querySelector('button').addEventListener('click', () => showCitations(data.citations));
        contentEl.appendChild(metaDiv);
    }
}

function showCitations(citations) {
    state.currentCitations = citations;
    els.citationsList.innerHTML = '';
    els.citationsPanel.classList.remove('hidden');

    citations.forEach(c => {
        const card = document.createElement('div');
        card.className = 'citation-card';
        card.innerHTML = `
            <div class="citation-source-tag">[SOURCE ${c.source_num}]</div>
            <div class="citation-meta">${escapeHtml(c.filename)} · Page ${c.page} · ${escapeHtml(c.section)}</div>
            <div class="citation-text">"${escapeHtml(c.snippet)}"</div>
            <div style="font-size:0.7rem;color:var(--accent);margin-top:8px">
                Similarity: ${Math.round(c.score * 100)}%
            </div>
        `;
        els.citationsList.appendChild(card);
    });
}

// ── MARKDOWN RENDERER ─────────────────────────────────────────────────────────

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escapeAttr(text) {
    return String(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function processInline(text) {
    // Escape HTML, then apply inline formatting
    return escapeHtml(text)
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[SOURCE (\d+)\]/g,
            '<span class="cite-tag" onclick="window.highlightCitation($1)">[SOURCE $1]</span>');
}

function formatMarkdown(text) {
    if (!text) return '';

    const lines = text.split('\n');
    let html = '';
    let inList = false;
    let inCodeBlock = false;
    let codeLines = [];

    const flushList = () => {
        if (inList) { html += '</ul>'; inList = false; }
    };

    for (const line of lines) {
        // Fenced code block
        if (line.startsWith('```')) {
            if (!inCodeBlock) {
                flushList();
                inCodeBlock = true;
                codeLines = [];
            } else {
                inCodeBlock = false;
                html += `<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
                codeLines = [];
            }
            continue;
        }
        if (inCodeBlock) { codeLines.push(line); continue; }

        // Headers
        if (line.startsWith('### ')) {
            flushList();
            html += `<h3>${processInline(line.slice(4))}</h3>`;
        } else if (line.startsWith('## ')) {
            flushList();
            html += `<h2>${processInline(line.slice(3))}</h2>`;
        } else if (line.startsWith('# ')) {
            flushList();
            html += `<h1>${processInline(line.slice(2))}</h1>`;
        }
        // Unordered list item
        else if (/^[\*\-\+] /.test(line)) {
            if (!inList) { html += '<ul>'; inList = true; }
            html += `<li>${processInline(line.slice(2))}</li>`;
        }
        // Numbered list item
        else if (/^\d+\. /.test(line)) {
            if (!inList) { html += '<ol>'; inList = true; }
            html += `<li>${processInline(line.replace(/^\d+\. /, ''))}</li>`;
        }
        // Blank line
        else if (line.trim() === '') {
            flushList();
        }
        // Paragraph
        else {
            flushList();
            html += `<p>${processInline(line)}</p>`;
        }
    }

    flushList();
    if (inCodeBlock) html += `<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`;

    return html;
}

window.highlightCitation = function (num) {
    els.citationsPanel.classList.remove('hidden');
    els.citationsList.querySelectorAll('.citation-card').forEach(card => {
        if (card.querySelector('.citation-source-tag').textContent === `[SOURCE ${num}]`) {
            card.scrollIntoView({ behavior: 'smooth' });
            card.style.borderColor = 'var(--accent)';
            card.style.background = 'rgba(79, 70, 229, 0.1)';
            setTimeout(() => {
                card.style.borderColor = 'var(--panel-border)';
                card.style.background = 'rgba(255, 255, 255, 0.03)';
            }, 2000);
        }
    });
};

// ── UTILS ─────────────────────────────────────────────────────────────────────

function handleFileSelect(e) {
    if (e.target.files.length) uploadFiles(e.target.files);
}

function scrollToBottom() {
    els.chatArea.scrollTop = els.chatArea.scrollHeight;
}

function updateStats() {
    // Use data already fetched from /papers — no extra request needed
    els.statPapers.textContent = state.papers.length;
    els.statChunks.textContent = state.papers.reduce((acc, p) => acc + (p.num_chunks || 0), 0);
}

function showToast(msg, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    const icon = type === 'error' ? '❌' : type === 'warning' ? '⚠️' : '✅';
    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(msg)}</span>`;
    document.getElementById('toastContainer').appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

init();
