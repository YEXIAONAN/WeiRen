document.addEventListener('DOMContentLoaded', () => {
  const app = document.getElementById('chat-app');
  if (!app) {
    return;
  }

  const scrollBox = document.getElementById('chat-scroll');
  const list = document.getElementById('chat-list');
  const empty = document.getElementById('chat-empty');
  const input = document.getElementById('chat-input');
  const sendButton = document.getElementById('chat-send');
  const clearButton = document.getElementById('chat-clear');
  const sessionId = app.dataset.sessionId;
  const subjectName = app.dataset.subjectName || '她';

  let sending = false;

  const updateComposerState = () => {
    const hasValue = Boolean(input.value.trim());
    sendButton.disabled = sending || !hasValue;
    clearButton.disabled = sending;
  };

  const updateEmptyState = () => {
    const hasMessages = Boolean(list.children.length);
    empty.style.display = hasMessages ? 'none' : 'flex';
  };

  const scrollToBottom = () => {
    scrollBox.scrollTop = scrollBox.scrollHeight;
  };

  const escapeHtml = (value) => {
    return value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  const renderEvidence = (items) => {
    if (!items || !items.length) {
      return '';
    }

    const blocks = items.map((item) => {
      const meta = [item.source_name, item.source_type, item.date].filter(Boolean).join(' / ');
      const extra = [];
      if (typeof item.similarity === 'number') {
        extra.push(`相似度 ${item.similarity.toFixed(1)}`);
      }
      if (Array.isArray(item.keywords) && item.keywords.length) {
        extra.push(`关键词 ${item.keywords.map(escapeHtml).join('、')}`);
      }
      return `
        <div class="chat-evidence-item">
          <div class="chat-evidence-title">${escapeHtml(meta)}</div>
          <div class="chat-evidence-snippet">${escapeHtml(item.snippet || '')}</div>
          ${extra.length ? `<div class="chat-evidence-snippet">${extra.join(' / ')}</div>` : ''}
        </div>
      `;
    }).join('');

    return `
      <button type="button" class="chat-evidence-toggle">查看依据</button>
      <div class="chat-evidence-list">${blocks}</div>
    `;
  };

  const appendMessage = (role, content, options = {}) => {
    const article = document.createElement('article');
    article.className = `chat-row ${role === 'user' ? 'chat-row-user' : 'chat-row-system'}`;

    const metaLeft = role === 'user' ? '你' : '系统';
    const metaRight = role === 'system'
      ? [options.intent || 'reply', options.confidence || 'low'].filter(Boolean).join(' / ')
      : (new Date()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

    article.innerHTML = `
      <div class="chat-bubble">
        <div class="chat-meta">
          <span>${escapeHtml(metaLeft)}</span>
          <span>${escapeHtml(metaRight)}</span>
        </div>
        <div class="chat-answer">${escapeHtml(content)}</div>
        ${role === 'system' ? renderEvidence(options.evidence || []) : ''}
      </div>
    `;

    list.appendChild(article);
    updateEmptyState();
    scrollToBottom();
  };

  const setSending = (next) => {
    sending = next;
    if (sending) {
      sendButton.textContent = '发送中';
    } else {
      sendButton.textContent = '发送';
    }
    input.disabled = sending;
    updateComposerState();
  };

  const sendQuestion = async (question) => {
    const value = typeof question === 'string' ? question.trim() : input.value.trim();
    if (!value || sending) {
      return;
    }

    appendMessage('user', value);
    input.value = '';
    updateComposerState();
    setSending(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId,
          question: value,
          subject_name: subjectName,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || '请求失败');
      }

      appendMessage('system', data.answer || '现有资料不足以确认。', {
        intent: data.intent,
        confidence: data.confidence,
        evidence: data.evidence || [],
      });
    } catch (error) {
      appendMessage('system', error instanceof Error ? error.message : '请求失败。', {
        intent: 'error',
        confidence: 'low',
        evidence: [],
      });
    } finally {
      setSending(false);
      input.focus();
    }
  };

  sendButton.addEventListener('click', () => {
    void sendQuestion();
  });

  input.addEventListener('input', updateComposerState);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion();
    }
  });

  clearButton.addEventListener('click', async () => {
    if (sending) {
      return;
    }

    setSending(true);
    try {
      const response = await fetch('/api/chat/clear', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || '清空失败');
      }
      list.innerHTML = '';
      updateEmptyState();
      input.value = '';
      updateComposerState();
      input.focus();
    } catch (error) {
      appendMessage('system', error instanceof Error ? error.message : '清空失败。', {
        intent: 'error',
        confidence: 'low',
        evidence: [],
      });
    } finally {
      setSending(false);
    }
  });

  document.querySelectorAll('[data-suggest]').forEach((button) => {
    button.addEventListener('click', () => {
      const value = button.getAttribute('data-suggest') || '';
      void sendQuestion(value);
    });
  });

  list.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (!target.classList.contains('chat-evidence-toggle')) {
      return;
    }
    const block = target.nextElementSibling;
    if (!(block instanceof HTMLElement)) {
      return;
    }
    const isOpen = block.classList.toggle('is-open');
    target.textContent = isOpen ? '收起依据' : '查看依据';
  });

  updateEmptyState();
  updateComposerState();
  scrollToBottom();
});
