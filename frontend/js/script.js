/**
 * RIO — Responsive Intelligent Operator
 * Frontend Logic — WebSocket state machine + real API
 *
 * State machine:  idle → listening → processing → speaking → idle
 * Transport:      WebSocket /ws/state  (real-time from server)
 *                 POST /chat           (text commands)
 *                 POST /voice/trigger  (mic button → server-side voice)
 */

const API_BASE  = 'http://127.0.0.1:8000';
const WS_URL    = 'ws://127.0.0.1:8000/ws/state';

// ── State config ──────────────────────────────────────────────────────────────

const STATES = {
    idle: {
        statusText:  'Operational',
        statusDot:   'online',
        statusValue: 'Ready',
        overlay:     false,
        overlayLabel:'',
        micClass:    '',
        avatarClass: '',
    },
    listening: {
        statusText:  'Listening...',
        statusDot:   'listening',
        statusValue: 'Listening',
        overlay:     true,
        overlayLabel:'Listening...',
        overlayClass:'',
        micClass:    'listening',
        avatarClass: 'listening',
    },
    processing: {
        statusText:  'Processing...',
        statusDot:   'thinking',
        statusValue: 'Processing',
        overlay:     true,
        overlayLabel:'Processing...',
        overlayClass:'processing',
        micClass:    'processing',
        avatarClass: 'processing',
    },
    speaking: {
        statusText:  'Speaking...',
        statusDot:   'speaking',
        statusValue: 'Speaking',
        overlay:     true,
        overlayLabel:'Speaking',
        overlayClass:'speaking',
        micClass:    'speaking',
        avatarClass: 'speaking',
    },
    error: {
        statusText:  'Offline',
        statusDot:   'error',
        statusValue: 'Error',
        overlay:     false,
        overlayLabel:'',
        micClass:    '',
        avatarClass: '',
    },
};

// ── DOM refs ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const chatViewport    = document.getElementById('chat-viewport');
    const userInput       = document.getElementById('user-input');
    const sendBtn         = document.getElementById('send-btn');
    const micBtn          = document.getElementById('mic-btn');
    const clearBtn        = document.getElementById('clear-chat');
    const welcomeScreen   = document.querySelector('.welcome-message');
    const statusText      = document.querySelector('.status-text');
    const statusDot       = document.querySelector('.status-indicator');
    const statusValue     = document.querySelector('.status-value');
    const voiceOverlay    = document.getElementById('voice-overlay');
    const voiceLabel      = document.getElementById('voice-overlay-label');
    const rioAvatar       = document.getElementById('rio-avatar');

    let isProcessing = false;

    // ── Apply state to UI ─────────────────────────────────────────────────────

    function applyState(stateName) {
        const s = STATES[stateName] || STATES.idle;

        // Status bar
        if (statusText)  statusText.textContent  = s.statusText;
        if (statusValue) statusValue.textContent = s.statusValue;
        if (statusDot) {
            statusDot.className = 'status-indicator ' + s.statusDot;
        }

        // Voice overlay
        if (voiceOverlay) {
            voiceOverlay.className = 'voice-overlay' + (s.overlay ? ' visible' : '') + (s.overlayClass ? ' ' + s.overlayClass : '');
        }
        if (voiceLabel && s.overlayLabel !== undefined) {
            voiceLabel.textContent = s.overlayLabel;
        }

        // Mic button
        if (micBtn) {
            micBtn.className = 'mic-btn' + (s.micClass ? ' ' + s.micClass : '');
        }

        // Avatar (only if visible)
        if (rioAvatar) {
            rioAvatar.className = 'rio-avatar glow-blue' + (s.avatarClass ? ' ' + s.avatarClass : '');
        }
    }

    // ── WebSocket — real-time state from server ───────────────────────────────

    let ws = null;
    let wsRetryTimer = null;

    function connectWS() {
        try {
            ws = new WebSocket(WS_URL);

            ws.onopen = () => {
                console.log('[WS] Connected to RIO state stream.');
                clearTimeout(wsRetryTimer);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.state) {
                        applyState(data.state);
                    }
                } catch (_) { /* ignore parse errors */ }
            };

            ws.onclose = () => {
                console.log('[WS] Disconnected — retrying in 3s...');
                wsRetryTimer = setTimeout(connectWS, 3000);
            };

            ws.onerror = () => {
                ws.close();
            };
        } catch (e) {
            wsRetryTimer = setTimeout(connectWS, 3000);
        }
    }

    connectWS();   // start immediately

    // ── Text input — POST /chat ───────────────────────────────────────────────

    const sendMessage = async () => {
        const text = userInput.value.trim();
        if (!text || isProcessing) return;

        if (welcomeScreen) welcomeScreen.style.display = 'none';

        addMessage(text, 'user');
        userInput.value = '';

        isProcessing = true;
        applyState('processing');
        const typingId = showTypingIndicator();

        try {
            const response = await callAPI(text);
            removeTypingIndicator(typingId);
            addMessage(response, 'assistant');
            applyState('idle');
        } catch (error) {
            removeTypingIndicator(typingId);
            const msg = error.message.includes('Failed to fetch')
                ? '⚠️ Cannot connect to RIO server. Start it with:\n  py -3 api/server.py'
                : '⚠️ ' + (error.message || 'Unexpected error.');
            addMessage(msg, 'assistant');
            applyState('error');
        } finally {
            isProcessing = false;
        }
    };

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // ── Mic button — POST /voice/trigger ─────────────────────────────────────

    if (micBtn) {
        micBtn.addEventListener('click', async () => {
            if (isProcessing) return;
            isProcessing = true;

            if (welcomeScreen) welcomeScreen.style.display = 'none';

            try {
                // State is pushed via WebSocket by server — we just fire the request
                const res = await fetch(`${API_BASE}/voice/trigger`, { method: 'POST' });
                const data = await res.json();

                if (data.response && data.response.trim()) {
                    addMessage('🎤 (voice command)', 'user');
                    addMessage(data.response, 'assistant');
                } else if (data.status === 'busy') {
                    addMessage('⚠️ Voice session already active.', 'assistant');
                }
            } catch (e) {
                addMessage('⚠️ Voice trigger failed. Make sure the server is running.', 'assistant');
                applyState('error');
            } finally {
                isProcessing = false;
            }
        });
    }

    // ── Clear ─────────────────────────────────────────────────────────────────

    clearBtn.addEventListener('click', () => {
        document.querySelectorAll('.message').forEach(m => m.remove());
        if (welcomeScreen) welcomeScreen.style.display = 'block';
        applyState('idle');
    });

    // ── Real API call ─────────────────────────────────────────────────────────

    const callAPI = async (message) => {
        const res = await fetch(`${API_BASE}/chat`, {
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

    // ── Message rendering ─────────────────────────────────────────────────────

    const addMessage = (text, sender) => {
        const time = new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
        const div  = document.createElement('div');
        div.className = `message ${sender}`;
        div.innerHTML = `
            <div class="message-bubble">
                <div class="message-text">${sender === 'assistant' ? '' : text.replace(/</g, '&lt;')}</div>
            </div>
            <div class="message-info">
                <span>${sender === 'assistant' ? 'RIO' : 'You'}</span>
                <span>${time}</span>
            </div>`;
        chatViewport.appendChild(div);
        chatViewport.scrollTop = chatViewport.scrollHeight;
        if (sender === 'assistant') typewriter(div.querySelector('.message-text'), text);
    };

    const typewriter = (el, text, i = 0) => {
        if (i < text.length) {
            el.textContent += text.charAt(i);
            setTimeout(() => typewriter(el, text, i + 1), 18);
            chatViewport.scrollTop = chatViewport.scrollHeight;
        }
    };

    // ── Typing indicator ──────────────────────────────────────────────────────

    const showTypingIndicator = () => {
        const id = 'typing-' + Date.now();
        const el = document.createElement('div');
        el.className = 'message assistant typing-indicator';
        el.id = id;
        el.innerHTML = `
            <div class="message-bubble typing-bubble">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
            <div class="message-info"><span>RIO is thinking...</span></div>`;
        chatViewport.appendChild(el);
        chatViewport.scrollTop = chatViewport.scrollHeight;
        return id;
    };

    const removeTypingIndicator = (id) => {
        const el = document.getElementById(id);
        if (el) el.remove();
    };
});
