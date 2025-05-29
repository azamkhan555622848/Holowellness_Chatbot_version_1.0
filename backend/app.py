from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from rag_qwen import RAGSystem
import os
import logging
import uuid
from memory_manager import memory_manager
from bson.json_util import dumps
from bson import ObjectId, errors

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)


# Create static directory if it doesn't exist
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

# Initialize the RAG system
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")  # Update this path as needed
logger.info(f"Initializing RAG system with documents from: {PDF_DIR}")
rag = RAGSystem(PDF_DIR)

DEFAULT_CHATBOT_ID = "664123456789abcdef123456"

# class RAGSystem:
#     def __init__(self, pdf_dir):
#         self.documents = ["This is a mock document just for testing MongoDB insert."]

#     def generate_answer(self, query, history=None):
#         return {
#             "thinking": "Mock thinking...",
#             "content": f"Echo: {query}"
#         }
# rag = RAGSystem(PDF_DIR)


@app.route('/', methods=['GET'])
def index():
    """Serve the static HTML file"""
    return send_from_directory('static', 'index.html')

@app.route('/api', methods=['GET'])
def api_info():
    """Root route for status check and basic instructions"""
    return jsonify({
        'status': 'ok',
        'message': 'HoloWellness Chatbot API is running with DeepSeek-R1-Distill-Qwen-14B',
        'endpoints': {
            '/api/chat': 'POST - Send a query to get a response from the chatbot',
            '/api/health': 'GET - Check if the API is running',
            '/api/memory': 'GET - Get memory for a session',
            '/api/memory/clear': 'POST - Clear memory for a session'
        },
        'documents_indexed': len(rag.documents) if hasattr(rag, 'documents') else 0
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        query = data.get('query')
        user_id = data.get('user_id')
        session_id = data.get('session_id')

        if not query:
            return jsonify({'error': 'No query provided'}), 400
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400

        try:
            user_object_id = ObjectId(user_id)
        except Exception:
            return jsonify({'error': 'Invalid user_id'}), 400

        if not session_id:
            now = datetime.utcnow()
            session_oid = ObjectId()
            session_doc = {
                "_id": session_oid,
                "chatbox_title": "Default Chat Session",
                "user": user_object_id,
                "chatbot": ObjectId(DEFAULT_CHATBOT_ID),
                "messages": [],
                "created_at": now,
                "updated_at": now
            }
            memory_manager.chatbot_collection.insert_one(session_doc)
            session_id = str(session_oid)
        else:
            if not memory_manager.chatbot_collection.find_one({"_id": ObjectId(session_id)}):
                return jsonify({'error': 'Invalid session_id'}), 400

        logger.info(f"Received query for session {session_id} from user {user_id}: {query}")
        chat_session = memory_manager.chatbot_collection.find_one({"_id": ObjectId(session_id)})
        chatbot_id = chat_session["chatbot"]
        memory_manager.add_user_message(session_id, query, user_id=user_id)

        conversation_history = memory_manager.get_chat_history(session_id)
        response_data = rag.generate_answer(query, conversation_history)
        content = response_data.get("content", "")
        thinking = response_data.get("thinking", "")

        logger.info(f"Generated response with {len(content)} characters.")

        # Get message_id from AI message
        message_id = memory_manager.add_ai_message(session_id, content, user_id=user_id)

        return jsonify({
            'response': content,
            'message_id': message_id,
            'session_id': session_id
        })

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
 

@app.route('/api/store-message', methods=['POST'])
def store_message():
    """
    Allows manual insertion of a single message into a chatbot session for testing.
    """
    data = request.get_json()
    try:
        session_id = data["session_id"]
        user_id = data["user_id"]
        message_body = data["message_body"]
        is_user = data["is_user"]
        previous_message = data.get("previous_message", None)

        # Always fetch chatbot_id from the session
        chat_session = memory_manager.chatbot_collection.find_one({"_id": ObjectId(session_id)})
        chatbot_id = chat_session["chatbot"]

        memory_manager._store_message_to_mongo(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            message_body=message_body,
            is_user=is_user,
            previous_message=previous_message
        )
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/interactions', methods=['GET'])
def get_interactions():
    """
    Returns a list of chatbot interactions or a specific one if session_id is given.
    """
    try:
        session_id = request.args.get('session_id')

        if session_id:
            doc = memory_manager.chatbot_collection.find_one({"_id": ObjectId(session_id)})
            if not doc:
                return jsonify({'error': 'Interaction not found'}), 404
            return dumps(doc), 200

        # Otherwise return latest 10 sessions
        interactions = memory_manager.chatbot_collection.find().sort("updated_at", -1).limit(10)
        return dumps(list(interactions)), 200

    except Exception as e:
        logger.error(f"Error in /api/interactions: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route("/api/chat/rate", methods=["POST"])
def rate_message():
    data = request.json
    message_id = data.get("message_id")
    rating = data.get("rating")

    if not message_id or rating is None:
        return jsonify({"error": "Missing message_id or rating"}), 400

    try:
        memory_manager.rate_message(message_id=message_id, rating=int(rating))
        return jsonify({"message": "Rating saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/memory', methods=['GET'])
def get_memory():
    """Get memory for a session"""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'error': 'No session_id provided'}), 400
    
    history = memory_manager.get_chat_history(session_id)
    return jsonify({
        'session_id': session_id,
        'history': history
    })

@app.route('/api/memory/clear', methods=['POST'])
def clear_memory():
    """Clear memory for a session"""
    data = request.json
    if not data or 'session_id' not in data:
        return jsonify({'error': 'No session_id provided'}), 400
    
    session_id = data['session_id']
    memory_manager.clear_session(session_id)
    
    return jsonify({
        'status': 'ok',
        'message': f'Memory cleared for session {session_id}'
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'message': 'RAG system is running'})

@app.route('/minimal', methods=['GET'])
def minimal():
    """Serve the minimal HTML test file"""
    return send_from_directory('static', 'minimal.html')

if __name__ == '__main__':
    logger.info("Starting Flask server on port 5000")
    app.run(host='0.0.0.0', port=5000, debug=True) 