// Add at the beginning of the file
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js')
      .then(registration => {
        console.log('ServiceWorker registered:', registration);
      })
      .catch(error => {
        console.log('ServiceWorker registration failed:', error);
      });
  });
}

// Add offline detection
let isOnline = navigator.onLine;

window.addEventListener('online', () => {
  isOnline = true;
  document.body.classList.remove('offline');
  loadChats(); // Refresh data when coming back online
});

window.addEventListener('offline', () => {
  isOnline = false;
  document.body.classList.add('offline');
});

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
    const response = await fetch('/chats/' + currentUserId);
    const chats = await response.json();
    console.log("scripts.js, ln 22: " + chats)
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

function formatMessageContent(content, isEditing = false) {
    if (isEditing) {
        return content;
    }
    
    // Convert newlines to <br> tags first
    content = content.replace(/\n/g, '<br>');
    
    // Handle thought tags
    content = content.replace(/<thought>([\s\S]*?)<\/thought>/g, (match, thought) => {
        return `
            <div class="message-content thought-block">
                <div class="tag-label">thought</div>
                ${thought.trim().replace(/\n/g, '<br>')}
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
    
    // Handle any remaining text with newlines
    content = content.replace(/([^>])\n/g, '$1<br>');
    
    return content;
}

async function loadChat(chat) {
    activeChat = chat;
    
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = `
        <button class="menu-button" onclick="toggleChatList()">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>
            </svg>
        </button>
        <div class="header-content">
            <h4>Chat ${chat.chat_id}</h4>
            <div class="chat-header-meta">
                <div>Model: ${chat.model.split('/').pop()}</div>
                <div>Started: ${formatDate(chat.started_at)}</div>
                <div>Messages: ${chat.message_count}</div>
            </div>
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
        const messageDiv = createMessageElement(msg);
        messagesDiv.appendChild(messageDiv);
    });
    
    // Scroll to bottom
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addNewChatButton() {
    const chatList = document.getElementById('chat-list');
    const button = document.createElement('button');
    button.className = 'new-chat-button';
    button.textContent = 'New Chat';
    button.onclick = startNewChat;
    chatList.insertBefore(button, chatList.firstChild);
}

function startNewChat() {
    // Generate a new user ID if none exists
    if (!currentUserId) {
        currentUserId = crypto.randomUUID();
    }
    
    // Reset the chat view
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = '<h2>New Chat</h2>';
    
    const messagesDiv = document.getElementById('messages');
    messagesDiv.innerHTML = '';
    
    // Show message input and mark as active chat
    const messageInput = document.getElementById('message-input');
    messageInput.style.display = 'block';
    isActiveChat = true;
    
    // Reset active states in chat list
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
}

async function loadChat(chat) {
    activeChat = chat;
    console.log(chat);
    
    // Update chat header
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = `
        <h2>Chat ${chat.chat_id}</h2>
        <div class="chat-header-meta">
            <div>User: ${chat.user_id}</div>
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
        const messageDiv = createMessageElement(msg);
        messagesDiv.appendChild(messageDiv);
    });
    
    // Show/hide message input based on whether this is the latest chat
    const messageInput = document.getElementById('message-input');
    isActiveChat = false;
    
    // Check if this is the most recent chat
    const allChats = await fetch('/chats/' + chat.user_id).then(r => r.json());
    if (allChats.length > 0 && allChats[0].chat_id === chat.chat_id) {
        messageInput.style.display = 'block';
        isActiveChat = true;
    } else {
        messageInput.style.display = 'none';
    }
    
    // Scroll to bottom
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    // Hide chat list on mobile after selection
    if (window.innerWidth <= 768) {
        document.getElementById('chat-list').classList.remove('show');
    }
}

// Initial load
loadChats();

let isActiveChat = false;

document.addEventListener('DOMContentLoaded', function() {
    addNewChatButton();
    
    const messageForm = document.getElementById('message-form');
    const messageText = document.getElementById('message-text');
    const sendButton = messageForm.querySelector('button[type="submit"]');
    
    messageForm.onsubmit = async function(e) {
        e.preventDefault();
        if (!messageText.value.trim() || !isActiveChat) return;
        
        // Disable input while processing
        messageText.disabled = true;
        sendButton.disabled = true;
        
        // Add user message to UI
        const messagesDiv = document.getElementById('messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user';
        messageDiv.innerHTML = `
            <div class="message-content">${messageText.value}</div>
            <div class="message-meta">
                <span class="role-badge">user</span>
                <span>${formatDate(new Date())}</span>
            </div>
        `;
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        
        try {
            // Send message to backend
            const response = await fetch(`/api/${currentUserId}/${activeChat.chat_id}/message`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: currentUserId,
                    client_type: "web",
                    message: messageText.value,
                    user_metadata: {}
                })
            });
            if (response.status != 200){
                throw("Not a 200 response. ewwwww");
            }
            const responseText = await response.text();
            
            // Add assistant response to UI
            const responseDiv = document.createElement('div');
            responseDiv.className = 'message assistant';
            responseDiv.innerHTML = `
                <div class="message-content">${formatMessageContent(responseText)}</div>
                <div class="message-meta">
                    <span class="role-badge">assistant</span>
                    <span>${formatDate(new Date())}</span>
                </div>
            `;
            messagesDiv.appendChild(responseDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            
            // Clear input
            messageText.value = '';
            
        } catch (error) {
            console.error('Error sending message:', error);
            alert('Error sending message. Please try again.');
        } finally {
            // Re-enable input
            messageText.disabled = false;
            sendButton.disabled = false;
            messageText.focus();
        }
    };

    // Auto-expand textarea
    messageText.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    // Handle mobile menu
    const menuButton = document.querySelector('.menu-button');
    if (window.innerWidth <= 768) {
        menuButton.style.display = 'block';
    }
    
    // Close chat list when clicking outside on mobile
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 768) {
            const chatList = document.getElementById('chat-list');
            const menuButton = document.querySelector('.menu-button');
            if (!chatList.contains(e.target) && !menuButton.contains(e.target)) {
                chatList.classList.remove('show');
            }
        }
    });
    
    // Handle window resize
    window.addEventListener('resize', () => {
        const menuButton = document.querySelector('.menu-button');
        menuButton.style.display = window.innerWidth <= 768 ? 'block' : 'none';
    });
});

function createMessageElement(msg) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${msg.role}`;
    messageDiv.dataset.messageId = msg.id;
    
    const formattedContent = formatMessageContent(msg.content);
    const isEdited = msg.updated_at !== msg.created_at;
    
    messageDiv.innerHTML = `
        <div class="message-content" onclick="toggleMessageEdit(this)">${formattedContent}</div>
        <div class="message-meta">
            <span class="role-badge">${msg.role}</span>
            <span>${formatDate(msg.created_at)}</span>
            ${isEdited ? `<span class="edited-indicator">(edited ${formatDate(msg.updated_at)})</span>` : ''}
            ${msg.is_purged ? '<span class="purged-indicator">purged</span>' : ''}
        </div>
    `;
    
    return messageDiv;
}

async function toggleMessageEdit(contentDiv) {
    const messageDiv = contentDiv.closest('.message');
    const messageId = messageDiv.dataset.messageId;
    
    if (contentDiv.querySelector('textarea')) {
        return; // Already in edit mode
    }
    
    // Fetch the original message content from the server
    const response = await fetch(`/message/${messageId}`);
    const message = await response.json();
    const originalContent = message.content;
    
    contentDiv.innerHTML = `
        <textarea class="edit-textarea">${originalContent}</textarea>
        <div class="edit-actions">
            <button onclick="saveMessageEdit('${messageId}', this)">Save</button>
            <button onclick="cancelMessageEdit(this)">Cancel</button>
        </div>
    `;
    
    const textarea = contentDiv.querySelector('textarea');
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    textarea.focus();
}

async function saveMessageEdit(messageId, button) {
    const contentDiv = button.closest('.message-content');
    const textarea = contentDiv.querySelector('textarea');
    const newContent = textarea.value;
    
    try {
        const response = await fetch(`/message/${messageId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ content: newContent })
        });
        
        const updatedMessage = await response.json();
        const messageDiv = contentDiv.closest('.message');
        messageDiv.replaceWith(createMessageElement(updatedMessage));
        
    } catch (error) {
        console.error('Error updating message:', error);
        alert('Error updating message. Please try again.');
    }
}

function cancelMessageEdit(button) {
    const contentDiv = button.closest('.message-content');
    const messageDiv = contentDiv.closest('.message');
    const messageId = messageDiv.dataset.messageId;
    
    // Reload the message to restore original content
    fetch(`/message/${messageId}`)
        .then(response => response.json())
        .then(message => {
            messageDiv.replaceWith(createMessageElement(message));
        });
}

// Add at the start of the file after service worker registration
function toggleChatList() {
    const chatList = document.getElementById('chat-list');
    chatList.classList.toggle('show');
}
