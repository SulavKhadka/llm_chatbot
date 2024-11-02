// Register Service Worker
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

// Offline Detection
let isOnline = navigator.onLine;

window.addEventListener('online', () => {
  isOnline = true;
  document.body.classList.remove('offline');
  loadChats(); // Refresh data when back online
});

window.addEventListener('offline', () => {
  isOnline = false;
  document.body.classList.add('offline');
});

// Global Variables
let activeChat = null;

// Date Formatting
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

// Load Chats
async function loadChats() {
    try {
        const response = await fetch('/chats/' + currentUserId);
        const chats = await response.json();
        const chatList = document.getElementById('chat-list');
        chatList.innerHTML = '';

        // Add New Chat Button
        const button = document.createElement('button');
        button.className = 'new-chat-button';
        button.textContent = 'New Chat';
        button.onclick = startNewChat;
        chatList.appendChild(button);

        chats.forEach(chat => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.dataset.chatId = chat.chat_id; // Add data attribute for state management
            chatItem.dataset.chat = JSON.stringify(chat); // Store chat data for popstate
            
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
            
            chatItem.onclick = () => {
                loadChat(chat);
            };
            chatList.appendChild(chatItem);
        });

        // Show chat list by default on mobile
        if (window.innerWidth <= 768 && !activeChat) {
            chatList.classList.add('show');
        }
    } catch (error) {
        console.error('Error loading chats:', error);
    }
}

// Create Message Element
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

// Toggle Chat List Visibility
function toggleChatList(show = null) {
    const chatList = document.getElementById('chat-list');
    if (show === null) {
        chatList.classList.toggle('show');
    } else if (show) {
        chatList.classList.add('show');
    } else {
        chatList.classList.remove('show');
    }
}

// Load Chat
async function loadChat(chat) {
    activeChat = chat;
    
    // Push state to history for navigation
    history.pushState(
        { chatId: chat.chat_id }, 
        `Chat ${chat.chat_id.slice(0, 8)}`, 
        `/${currentUserId}/chat/${chat.chat_id}`
    );

    // Update chat header
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = `
        <button class="menu-button" onclick="toggleChatList()">
            <svg width="24" height="24" viewBox="0 0 24 24">
                <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>
            </svg>
        </button>
        <div class="header-content">
            <h6>Chat ${chat.chat_id.slice(0, 8)}</h6>
            <div class="chat-header-meta">
                <div>Model: ${chat.model.split('/').pop()}</div>
                <div>Started: ${formatDate(chat.started_at)}</div>
                <div>Messages: ${chat.message_count}</div>
            </div>
        </div>
    `;

    // On mobile, hide chat list when viewing a chat
    if (window.innerWidth <= 768) {
        document.getElementById('chat-list').classList.remove('show');
    }

    // Load messages
    try {
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

        // Show message input if it's the latest chat
        const allChats = await fetch('/chats/' + chat.user_id).then(r => r.json());
        const messageInput = document.getElementById('message-input');
        if (allChats.length > 0 && allChats[0].chat_id === chat.chat_id) {
            messageInput.style.display = 'block';
        } else {
            messageInput.style.display = 'none';
        }

    } catch (error) {
        console.error('Error loading messages:', error);
    }
}

// Add New Chat Button
function addNewChatButton() {
    const chatList = document.getElementById('chat-list');
    const button = document.createElement('button');
    button.className = 'new-chat-button';
    button.textContent = 'New Chat';
    button.onclick = startNewChat;
    chatList.insertBefore(button, chatList.firstChild);
}

// Start New Chat
function startNewChat() {
    // Generate a new user ID if none exists
    if (!currentUserId) {
        // You might want to handle user ID generation differently
        alert('User ID is not set.');
        return;
    }
    
    // Reset the chat view
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = `
        <button class="menu-button" onclick="toggleChatList()">
            <svg width="24" height="24" viewBox="0 0 24 24">
                <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>
            </svg>
        </button>
        <div class="header-content">
            <h2>New Chat</h2>
        </div>
    `;
    
    const messagesDiv = document.getElementById('messages');
    messagesDiv.innerHTML = '';
    
    // Show message input and mark as active chat
    const messageInput = document.getElementById('message-input');
    messageInput.style.display = 'block';
    activeChat = null; // Indicate a new chat is being created
    
    // Reset active states in chat list
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    // Push state to history
    history.pushState({ newChat: true }, 'New Chat', `/${currentUserId}/new`);
}

// Format Message Content
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

// Try Parse JSON
function tryParseJSON(str) {
    try {
        const parsed = JSON.parse(str);
        return JSON.stringify(parsed, null, 2);
    } catch (e) {
        return str;
    }
}

// Toggle Message Edit
async function toggleMessageEdit(contentDiv) {
    const messageDiv = contentDiv.closest('.message');
    const messageId = messageDiv.dataset.messageId;
    
    if (contentDiv.querySelector('textarea')) {
        return; // Already in edit mode
    }
    
    // Fetch the original message content from the server
    try {
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
        textarea.style.height = (textarea.scrollHeight) + 'px';
        textarea.focus();
    } catch (error) {
        console.error('Error fetching message:', error);
    }
}

// Save Message Edit
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

// Cancel Message Edit
function cancelMessageEdit(button) {
    const contentDiv = button.closest('.message-content');
    const messageDiv = contentDiv.closest('.message');
    const messageId = messageDiv.dataset.messageId;
    
    // Reload the message to restore original content
    fetch(`/message/${messageId}`)
        .then(response => response.json())
        .then(message => {
            messageDiv.replaceWith(createMessageElement(message));
        })
        .catch(error => {
            console.error('Error fetching message:', error);
        });
}

// Handle Message Form Submission
document.addEventListener('DOMContentLoaded', function() {
    loadChats();

    const messageForm = document.getElementById('message-form');
    const messageText = document.getElementById('message-text');
    const sendButton = messageForm.querySelector('button[type="submit"]');

    messageForm.onsubmit = async function(e) {
        e.preventDefault();
        if (!messageText.value.trim() || !activeChat) return;
        
        // Disable input while processing
        messageText.disabled = true;
        sendButton.disabled = true;
        
        // Add user message to UI
        const messagesDiv = document.getElementById('messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user';
        messageDiv.innerHTML = `
            <div class="message-content">${formatMessageContent(messageText.value)}</div>
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
                    message: formatMessageContent(messageText.value),
                    user_metadata: {}
                })
            });
            if (response.status !== 200){
                throw new Error("Non-200 response");
            }
            const responseText = await response.text();
            const assistantMessageDiv = document.createElement('div');
            assistantMessageDiv.className = 'message assistant';
            assistantMessageDiv.innerHTML = `
                <div class="message-content">${formatMessageContent(responseText)}</div>
                <div class="message-meta">
                    <span class="role-badge">assistant</span>
                    <span>${formatDate(new Date())}</span>
                </div>
            `;
            messagesDiv.appendChild(assistantMessageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            
            // Clear and re-enable input
            messageText.value = '';
            messageText.style.height = 'auto';
            
        } catch (error) {
            console.error('Error sending message:', error);
            alert('Error sending message. Please try again.');
        } finally {
            messageText.disabled = false;
            sendButton.disabled = false;
        }
    };
    
    // Auto-expand textarea
    messageText.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });
    
    // Handle menu button visibility on resize
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

    // Handle browser navigation (back/forward)
    window.addEventListener('popstate', (event) => {
        if (event.state?.chatId) {
            // Return to specific chat
            const chat = document.querySelector(`.chat-item[data-chat-id="${event.state.chatId}"]`);
            if (chat) {
                loadChat(JSON.parse(chat.dataset.chat));
            }
        } else {
            // Return to chat list
            document.getElementById('chat-list').classList.add('show');
            activeChat = null;
        }
    });
});
