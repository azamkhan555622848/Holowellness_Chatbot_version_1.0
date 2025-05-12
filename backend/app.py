from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from rag_qwen import RAGSystem
import os
import logging
import uuid
from memory_manager import memory_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Create static directory if it doesn't exist
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

# Initialize the RAG system
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")  # Update this path as needed
logger.info(f"Initializing RAG system with documents from: {PDF_DIR}")
rag = RAGSystem(PDF_DIR)

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
            logger.warning("No data provided in request")
            return jsonify({'error': 'No data provided'}), 400
        
        # Get or create session ID
        session_id = data.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())
        
        query = data.get('query')
        if not query:
            return jsonify({'error': 'No query provided'}), 400
            
        logger.info(f"Received query for session {session_id}: {query}")
        
        # Add user message to memory
        memory_manager.add_user_message(session_id, query)
        
        # Get conversation history
        conversation_history = memory_manager.get_chat_history(session_id)
        
        # Get response using the RAG system with conversation history
        response_data = rag.generate_answer(query, conversation_history)
        
        # Extract thinking and content from the response
        thinking = response_data.get("thinking", "")
        content = response_data.get("content", "")
        
        # Log the lengths of thinking and content
        logger.info(f"Generated thinking ({len(thinking)} chars) and content ({len(content)} chars)")
        
        # Add assistant response to memory (only the content, not the thinking)
        memory_manager.add_ai_message(session_id, content)
        
        # Return ONLY the response content to the frontend
        return jsonify({
            'response': content,
            'session_id': session_id
        })
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

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