from flask import Flask, render_template_string, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
from secret_keys import POSTGRES_DB_PASSWORD

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    "dbname": "chatbot_db",
    "user": "chatbot_user",
    "password": POSTGRES_DB_PASSWORD,  # Replace with actual password
    "host": "localhost",
    "port": "5432"
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

# HTML template as a string
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Chat Viewer</title>
    <style>
        :root {
            --primary-color: #2563eb;
            --bg-color: #f8fafc;
            --border-color: #e2e8f0;
            --text-color: #334155;
            --meta-color: #64748b;
            --hover-color: #eff6ff;
            --code-bg: #1e293b;
            --code-text: #e2e8f0;
            --thought-bg: #f8f7ff;
            --thought-border: #818cf8;
            --tool-call-bg: #fffbeb;
            --tool-call-border: #d97706;
            --tool-response-bg: #f0f9ff;
            --json-bg: #1e293b;
        }
        
        /* Layout Styles */
        body {
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            height: 100vh;
            color: var(--text-color);
            background: var(--bg-color);
        }
        
        #chat-list {
            width: 20%;
            border-right: 1px solid var(--border-color);
            overflow-y: auto;
            background: white;
        }
        
        #chat-view {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            background: white;
            width: 80%;
        }
        
        /* Chat List Styles */
        .chat-item {
            padding: 12px;
            border-bottom: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .chat-item:hover {
            background: var(--hover-color);
        }
        
        .chat-item.active {
            background: var(--hover-color);
            border-left: 3px solid var(--primary-color);
        }
        
        .chat-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
        }
        
        .chat-id {
            font-weight: 600;
            color: var(--primary-color);
        }
        
        .chat-meta {
            font-size: 0.85em;
            color: var(--meta-color);
        }
        
        /* Message Styles */
        #messages {
            flex-grow: 1;
            overflow-y: auto;
            padding: 20px;
        }
        
        .message {
            margin-bottom: 20px;
            max-width: 85%;
        }
        
        .message.user {
            margin-left: auto;
        }
        
        .message-content {
            padding: 12px 16px;
            border-radius: 12px;
            background: var(--bg-color);
            word-break: break-word;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
        }
        
        .message.user .message-content {
            background: var(--primary-color);
            color: white;
        }
        
        .message.assistant .message-content {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
        }
        
        /* Nested Content Styles */
        .thought-block {
            margin: 8px 0 !important;
            padding: 8px 12px !important;
            background: var(--thought-bg) !important;
            border-left: 2px solid var(--thought-border) !important;
            font-size: 0.95em;
            color: var(--text-color);
            border-radius: 4px !important;
            box-shadow: none !important;
        }
        
        .tool-response, .function-call {
            margin: 8px 0 !important;
            padding: 0 !important;
            border-radius: 4px !important;
            overflow: hidden !important;
        }
        
        .tool-response {
            background: var(--tool-response-bg) !important;
            border-left: 2px solid var(--primary-color) !important;
        }
        
        .function-call {
            background: var(--tool-call-bg) !important;
            border-left: 2px solid var(--tool-call-border) !important;
        }
        
        .json-content {
            background: var(--json-bg);
            color: var(--code-text);
            padding: 12px;
            margin: 0;
            font-family: 'Menlo', 'Monaco', monospace;
            font-size: 0.9em;
            white-space: pre;
            overflow-x: auto;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .tag-label {
            padding: 4px 12px;
            font-size: 0.75em;
            color: var(--meta-color);
            background: rgba(255, 255, 255, 0.8);
            border-bottom: 1px solid rgba(0, 0, 0, 0.1);
        }
        
        /* Code Blocks */
        pre {
            background: var(--code-bg);
            color: var(--code-text);
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 8px 0;
        }
        
        code {
            font-family: 'Menlo', 'Monaco', monospace;
            font-size: 0.9em;
        }
        
        /* Header Styles */
        .chat-header {
            padding: 16px 20px;
            background: white;
            border-bottom: 1px solid var(--border-color);
        }
        
        .chat-header h2 {
            margin: 0 0 8px 0;
            color: var(--primary-color);
        }
        
        .chat-header-meta {
            display: flex;
            gap: 16px;
            color: var(--meta-color);
            font-size: 0.9em;
        }
        
        /* Utility Classes */
        .message-count {
            background: var(--primary-color);
            color: white;
            padding: 2px 6px;
            border-radius: 12px;
            font-size: 0.8em;
        }
        
        .purged-indicator {
            background: #fee2e2;
            color: #991b1b;
            padding: 2px 6px;
            border-radius: 12px;
            font-size: 0.85em;
        }
        
        .role-badge {
            text-transform: capitalize;
            padding: 2px 6px;
            border-radius: 12px;
            font-size: 0.85em;
            background: var(--bg-color);
            border: 1px solid var(--border-color);
        }
        
        .message-meta {
            font-size: 0.8em;
            color: var(--meta-color);
            margin-top: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .empty-state {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--meta-color);
            font-size: 1.1em;
        }
        
        /* Responsive Design */
        @media (max-width: 768px) {
            #chat-list {
                width: 30%;
            }
            #chat-view {
                width: 70%;
            }
            .message {
                max-width: 95%;
            }
            .chat-header-meta {
                flex-direction: column;
                gap: 4px;
            }
        }
    </style>
</head>
<body>
    <div id="chat-list"></div>
    <div id="chat-view">
        <div id="chat-header"></div>
        <div id="messages">
            <div class="empty-state">
                Select a chat to view messages
            </div>
        </div>
    </div>

    <script>
        let activeChat = null;
        
        function formatDate(dateString) {
            const date = new Date(dateString);
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });
        }
        
        async function loadChats() {
            const response = await fetch('/chats');
            const chats = await response.json();
            
            const chatList = document.getElementById('chat-list');
            chatList.innerHTML = '';
            
            chats.forEach(chat => {
                const chatItem = document.createElement('div');
                chatItem.className = 'chat-item';
                chatItem.innerHTML = `
                    <div class="chat-item-header">
                        <span class="chat-id">${chat.chat_id.slice(0, 8)}</span>
                        <span class="message-count">${chat.message_count}</span>
                    </div>
                    <div class="chat-meta">
                        <div>${chat.model.split('/').pop()}</div>
                        <div>Last active: ${formatDate(chat.latest_message_time)}</div>
                    </div>
                `;
                
                chatItem.onclick = () => loadChat(chat);
                chatList.appendChild(chatItem);
            });
        }
        
        function tryParseJSON(str) {
            try {
                const parsed = JSON.parse(str);
                return JSON.stringify(parsed, null, 2);
            } catch (e) {
                return str;
            }
        }
        
        function formatMessageContent(content) {
            // Handle thought tags
            content = content.replace(/<thought>([\s\S]*?)<\/thought>/g, (match, thought) => {
                return `
                    <div class="message-content thought-block">
                        <div class="tag-label">thought</div>
                        ${thought.trim()}
                    </div>`;
            });
            
            // Handle code blocks
            content = content.replace(/```([\s\S]*?)```/g, (match, code) => {
                return `<pre><code>${code}</code></pre>`;
            });
            
            // Handle tool calls
            content = content.replace(/<tool_call>([\s\S]*?)<\/tool_call>/g, (match, toolCall) => {
                const formattedJson = tryParseJSON(toolCall.trim());
                return `
                    <div class="message-content function-call">
                        <div class="tag-label">tool call</div>
                        <div class="json-content">${formattedJson}</div>
                    </div>`;
            });
            
            // Handle tool call responses
            content = content.replace(/<tool_call_response>([\s\S]*?)<\/tool_call_response>/g, (match, response) => {
                const formattedJson = tryParseJSON(response.trim());
                return `
                    <div class="message-content tool-response">
                        <div class="tag-label">tool response</div>
                        <div class="json-content">${formattedJson}</div>
                    </div>`;
            });
            
            return content;
        }
        
        async function loadChat(chat) {
            activeChat = chat;
            
            // Update chat header
            const chatHeader = document.getElementById('chat-header');
            chatHeader.innerHTML = `
                <h2>Chat ${chat.chat_id}</h2>
                <div class="chat-header-meta">
                    <div>Model: ${chat.model.split('/').pop()}</div>
                    <div>Started: ${formatDate(chat.started_at)}</div>
                    <div>Messages: ${chat.message_count}</div>
                </div>
            `;
            
            // Highlight active chat in list
            document.querySelectorAll('.chat-item').forEach(item => {
                item.classList.remove('active');
                if(item.textContent.includes(chat.chat_id.slice(0, 8))) {
                    item.classList.add('active');
                }
            });
            
            // Load messages
            const response = await fetch(`/chat/${chat.chat_id}/messages`);
            const messages = await response.json();
            
            const messagesDiv = document.getElementById('messages');
            messagesDiv.innerHTML = '';
            
            messages.forEach(msg => {
                if(msg.role === 'system') return;  // Skip system messages
                
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${msg.role}`;
                
                const formattedContent = formatMessageContent(msg.content);
                
                messageDiv.innerHTML = `
                    <div class="message-content">${formattedContent}</div>
                    <div class="message-meta">
                        <span class="role-badge">${msg.role}</span>
                        <span>${formatDate(msg.created_at)}</span>
                        ${msg.is_purged ? '<span class="purged-indicator">purged</span>' : ''}
                    </div>
                `;
                
                messagesDiv.appendChild(messageDiv);
            });
            
            // Scroll to bottom
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
        
        // Initial load
        loadChats();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/chats')
def get_chats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        WITH latest_messages AS (
            SELECT 
                chat_id,
                MAX(created_at) as latest_message_time,
                COUNT(*) as message_count
            FROM chat_messages
            GROUP BY chat_id
        )
        SELECT 
            cs.chat_id,
            cs.model,
            cs.created_at as started_at,
            lm.latest_message_time,
            lm.message_count
        FROM chat_sessions cs
        JOIN latest_messages lm ON cs.chat_id = lm.chat_id
        ORDER BY lm.latest_message_time DESC
    """)
    
    chats = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([dict(chat) for chat in chats])

@app.route('/chat/<chat_id>/messages')
def get_chat_messages(chat_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            id,
            role,
            content,
            created_at,
            is_purged
        FROM chat_messages
        WHERE chat_id = %s
        ORDER BY created_at, id
    """, (chat_id,))
    
    messages = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([dict(msg) for msg in messages])

if __name__ == '__main__':
    app.run(debug=True)