/**
 * RIO — Responsive Intelligent Operator
 * Frontend Logic (Vanilla JS)
 * Connects to FastAPI backend at http://127.0.0.1:8000
 */

const API_URL = 'http://127.0.0.1:8000/chat';

document.addEventListener('DOMContentLoaded', () => {
    const chatViewport  = document.getElementById('chat-viewport');
    const userInput     = document.getElementById('user-input');
    const sendBtn       = document.getElementById('send-btn');
    const clearBtn      = document.getElementById('clear-chat');
    const welcomeScreen = document.querySelector('.welcome-message');
    const statusText    = document.querySelector('.status-text');
    const statusDot     = document.querySelector('.status-indicator');
    const statusValue   = document.querySelector('.status-value');

    let isProcessing = false;

    // ── Status helpers ────────────────────────────────────────────────────────

    const setStatus = (state) => {
        const states = {
            online:     { text: 'Operational',  dot: 'online',     card: 'Running'    },
            thinking:   { text: 'Thinking...',  dot: 'thinking',   card: 'Processing' },
            error:      { text: 'Offline',       dot: 'error',      card: 'Error'      },
        };
        const s = states[state] || states.online;
        if (statusText)  statusText.textContent  = s.text;
        if (statusValue) statusValue.textContent = s.card;
        if (statusDot) {
            statusDot.className = 'status-indicator ' + s.dot;
        }
    };

    // ── Input Handling ────────────────────────────────────────────────────────

    const sendMessage = async () => {
        const text = userInput.value.trim();
        if (!text || isProcessing) return;

        if (welcomeScreen) welcomeScreen.style.display = 'none';

        addMessage(text, 'user');
        userInput.value = '';

        isProcessing = true;
        setStatus('thinking');
        const typingId = showTypingIndicator();

        try {
            const response = await callAPI(text);
            removeTypingIndicator(typingId);
            addMessage(response, 'assistant');
            setStatus('online');
        } catch (error) {
            removeTypingIndicator(typingId);
            const msg = error.message.includes('Failed to fetch')
                ? '⚠️ Cannot connect to RIO server. Make sure it\'s running:\n  py -3 api/server.py'
                : '⚠️ ' + (error.message || 'Unexpected error.');
            addMessage(msg, 'assistant');
            setStatus('error');
        } finally {
            isProcessing = false;
        }
    };

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    clearBtn.addEventListener('click', () => {
        document.querySelectorAll('.message').forEach(m => m.remove());
        if (welcomeScreen) welcomeScreen.style.display = 'block';
        setStatus('online');
    });

    // ── Real API Call ─────────────────────────────────────────────────────────

    const callAPI = async (message) => {
        const res = await fetch(API_URL, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ message }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Server error ${res.status}`);
        }

        const data = await res.json();
        return data.response || '(no response)';
    };

    // ── Message Rendering ─────────────────────────────────────────────────────

    const addMessage = (text, sender) => {
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}`;

        // Preserve newlines as line breaks
        const safeText = sender === 'assistant' ? '' : text.replace(/</g, '&lt;');

        messageDiv.innerHTML = `
            <div class="message-bubble">
                <div class="message-text">${safeText}</div>
            </div>
            <div class="message-info">
                <span>${sender === 'assistant' ? 'RIO' : 'You'}</span>
                <span>${time}</span>
            </div>
        `;

        chatViewport.appendChild(messageDiv);
        chatViewport.scrollTop = chatViewport.scrollHeight;

        if (sender === 'assistant') {
            typewriter(messageDiv.querySelector('.message-text'), text);
        }
    };

    const typewriter = (element, text, index = 0) => {
        if (index < text.length) {
            element.textContent += text.charAt(index);
            setTimeout(() => typewriter(element, text, index + 1), 18);
            chatViewport.scrollTop = chatViewport.scrollHeight;
        }
    };

    // ── Typing Indicator ──────────────────────────────────────────────────────

    const showTypingIndicator = () => {
        const id = 'typing-' + Date.now();
        const indicator = document.createElement('div');
        indicator.className = 'message assistant typing-indicator';
        indicator.id = id;
        indicator.innerHTML = `
            <div class="message-bubble typing-bubble">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
            <div class="message-info"><span>RIO is thinking...</span></div>
        `;
        chatViewport.appendChild(indicator);
        chatViewport.scrollTop = chatViewport.scrollHeight;
        return id;
    };

    const removeTypingIndicator = (id) => {
        const el = document.getElementById(id);
        if (el) el.remove();
    };
});
