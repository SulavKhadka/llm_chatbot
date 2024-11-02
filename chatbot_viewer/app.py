from flask import Flask, render_template, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from secret_keys import POSTGRES_DB_PASSWORD

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    "dbname": "chatbot_db",
    "user": "chatbot_user",
    "password": POSTGRES_DB_PASSWORD,
    "host": "localhost",
    "port": "5432"
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

@app.route('/<user_id>')
def index(user_id):
    return render_template('index.html', user_id=user_id)

@app.route('/api/<user_id>/<session_id>/message', methods=['POST'])
def send_message(user_id, session_id):
    data = request.json
    response = requests.post(
        f'http://localhost:8000/{user_id}/{session_id}/message?only_user_response=false',
        json=data
    )
    return response.text

@app.route('/chats/<user_id>')
def get_chats(user_id):
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
            cs.user_id,
            cs.model,
            cs.created_at as started_at,
            lm.latest_message_time,
            lm.message_count
        FROM chat_sessions cs
        JOIN latest_messages lm ON cs.chat_id = lm.chat_id
        WHERE cs.user_id = %s
        ORDER BY lm.latest_message_time DESC
    """, (user_id,))
    
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
            updated_at,
            is_purged
        FROM chat_messages
        WHERE chat_id = %s
        ORDER BY created_at, id
    """, (chat_id,))
    
    messages = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([dict(msg) for msg in messages])

@app.route('/message/<message_id>', methods=['PUT'])
def update_message(message_id):
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        UPDATE chat_messages 
        SET content = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, role, content, created_at, updated_at, is_purged
    """, (data['content'], message_id))
    
    updated_message = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify(dict(updated_message))

@app.route('/message/<message_id>', methods=['GET'])
def get_message(message_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT id, role, content, created_at, updated_at, is_purged
        FROM chat_messages
        WHERE id = %s
    """, (message_id,))
    
    message = cur.fetchone()
    cur.close()
    conn.close()
    
    return jsonify(dict(message))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
