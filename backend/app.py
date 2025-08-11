from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import os
import logging
import uuid
from dotenv import load_dotenv
from memory_manager import memory_manager
from bson.json_util import dumps
from bson import ObjectId, errors
from sync_rag_pdfs import sync_pdfs_from_s3

# Load environment variables
load_dotenv()

# Production configuration
FLASK_ENV = os.getenv('FLASK_ENV', 'development')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# RAG/S3 configuration
RAG_SYNC_ON_START = os.getenv('RAG_SYNC_ON_START', 'true').lower() == 'true'
RAG_S3_BUCKET = os.getenv('RAG_S3_BUCKET', 'holowellness')
RAG_S3_PREFIX = os.getenv('RAG_S3_PREFIX', '')  # e.g. 'rag_pdfs/' or '' for root

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(level=getattr(logging, log_level.upper()))
logger = logging.getLogger(__name__)

# Import enhanced RAG system with BGE reranking
try:
    from enhanced_rag_qwen import EnhancedRAGSystem
    USE_ENHANCED_RAG = True
    logger = logging.getLogger(__name__)
    logger.info("Enhanced RAG system with BGE reranking is available")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Enhanced RAG system not available: {e}. Falling back to original RAG system")
    from rag_qwen import RAGSystem
    USE_ENHANCED_RAG = False

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['DEBUG'] = DEBUG

# Configure CORS based on environment
if FLASK_ENV == 'production':
    cors_origins = os.getenv('CORS_ORIGINS', '').split(',')
    CORS(app, resources={r"/api/*": {"origins": cors_origins}}, supports_credentials=True)
    logger.info(f"Production CORS configured for origins: {cors_origins}")
else:
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    logger.info("Development CORS configured for all origins")

# Create static directory if it doesn't exist
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

# Health check endpoint for AWS Load Balancer
@app.route('/health')
def health_check():
    try:
        # Basic health checks
        checks = {
            'status': 'healthy',
            'service': 'holowellness-api',
            'version': '1.0',
            'environment': FLASK_ENV,
            'openrouter_configured': bool(os.getenv('OPENROUTER_API_KEY')),
            'mongodb_configured': bool(os.getenv('MONGO_URI')),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Test MongoDB connection
        try:
            if memory_manager.mongo_client is not None:
                memory_manager.mongo_client.admin.command('ismaster')
                checks['mongodb_status'] = 'connected'
            else:
                checks['mongodb_status'] = 'error: MongoDB client not initialized'
        except Exception as e:
            checks['mongodb_status'] = f'error: {str(e)}'
            
        return jsonify(checks), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

# Initialize the RAG system (Enhanced or Original) with error handling
PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
logger.info(f"Initializing RAG system with documents from: {PDF_DIR}")

rag = None
rag_error = None

try:
    if USE_ENHANCED_RAG:
        # Use enhanced RAG with BGE reranking
        rag = EnhancedRAGSystem(pdf_dir=PDF_DIR)
        logger.info("✅ Enhanced RAG system with BGE reranking initialized successfully")
    else:
        # Fall back to original RAG system
        rag = RAGSystem(PDF_DIR)
        logger.info("⚠️ Using original RAG system (no reranking)")
except Exception as e:
    logger.error(f"❌ RAG system initialization failed: {e}", exc_info=True)
    rag_error = str(e)
    rag = None
    logger.info("🔄 Flask app will continue without RAG system")

# Optionally sync PDFs from S3 and rebuild indices at startup
try:
    if rag is not None and RAG_SYNC_ON_START:
        needs_sync = True
        if os.path.isdir(PDF_DIR):
            pdfs_present = any(name.lower().endswith('.pdf') for name in os.listdir(PDF_DIR))
            needs_sync = not pdfs_present

        if needs_sync:
            logger.info(
                f"📥 RAG_SYNC_ON_START enabled. Syncing PDFs from S3 bucket '{RAG_S3_BUCKET}' prefix '{RAG_S3_PREFIX}'..."
            )
            # sync from S3 and rebuild indices
            sync_pdfs_from_s3()
            try:
                rag._ingest_documents()
                rag._save_embeddings()
                logger.info("✅ Initial PDF sync & embedding cache built")
            except Exception as reindex_err:
                logger.error(f"Failed to build embeddings after sync: {reindex_err}")
except Exception as sync_err:
    logger.error(f"Startup sync error: {sync_err}")

DEFAULT_CHATBOT_ID = "664123456789abcdef123456"


@app.route('/', methods=['GET'])
def index():
    """Serve the static HTML file"""
    return send_from_directory('static', 'index.html')

@app.route('/api', methods=['GET'])
def api_info():
    """Root route for status check and basic instructions"""
    enhanced_info = ""
    if USE_ENHANCED_RAG and hasattr(rag, 'reranker') and rag.reranker:
        enhanced_info = " with BGE Reranking (Two-Stage Retrieval)"
    elif USE_ENHANCED_RAG:
        enhanced_info = " (Enhanced RAG - Reranker Loading)"
    
    rag_status = "Not Available"
    rag_info = {'type': 'Error', 'error': rag_error} if rag_error else {'type': 'Not Initialized'}
    
    if rag is not None:
        rag_status = "Available"
        rag_info = {
            'type': 'Enhanced RAG with BGE Reranking' if USE_ENHANCED_RAG else 'Original RAG',
            'reranker_active': bool(USE_ENHANCED_RAG and hasattr(rag, 'reranker') and rag.reranker),
            'reranker_model': rag.reranker_model_name if USE_ENHANCED_RAG and hasattr(rag, 'reranker_model_name') else None,
            'stage1_candidates': rag.first_stage_k if USE_ENHANCED_RAG and hasattr(rag, 'first_stage_k') else 'N/A',
            'final_results': rag.final_k if USE_ENHANCED_RAG and hasattr(rag, 'final_k') else 'N/A'
        }

    return jsonify({
        'status': 'ok',
        'message': f'HoloWellness Chatbot API is running with DeepSeek-R1-Distill-Qwen-14B{enhanced_info}',
        'rag_status': rag_status,
        'rag_system': rag_info,
        'endpoints': {
            '/api/chat': 'POST - Send a query to get a response from the enhanced chatbot',
            '/api/health': 'GET - Check if the API is running',
            '/api/memory': 'GET - Get memory for a session',
            '/api/memory/clear': 'POST - Clear memory for a session',
            '/api/rag/reindex': 'POST - Force reindexing of documents'
        },
        'documents_indexed': len(rag.documents) if rag and hasattr(rag, 'documents') else 0
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        # Strict JSON parsing with better error handling
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            logger.exception("Invalid JSON in request")
            return jsonify({'error': 'Invalid JSON'}), 400
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Accept both 'query' and 'message' for compatibility
        query = data.get('query') or data.get('message', '').strip()
        user_id = data.get('user_id')
        session_id = data.get('session_id')

        if not query:
            return jsonify({'error': 'Field "query" or "message" is required'}), 400

        # Generate user_id if not provided (for in-memory fallback)
        if not user_id:
            user_id = str(uuid.uuid4())
            logger.info(f"Generated user_id for session: {user_id}")

        # Validate user_id for MongoDB if available
        if memory_manager.mongodb_available:
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                return jsonify({'error': 'Invalid user_id'}), 400

        # Create or validate session - auto-recover from invalid sessions
        if not session_id or session_id.strip() == "":
            session_id = str(uuid.uuid4()) if not memory_manager.mongodb_available else str(ObjectId())
            session_doc = memory_manager._create_session_document(
                session_id, user_id, DEFAULT_CHATBOT_ID, "Default Chat Session"
            )
            logger.info(f"Created new session: {session_id}")
        else:
            # Validate existing session, create new if invalid
            session_doc = memory_manager._get_session_document(session_id)
            if not session_doc:
                logger.warning(f"Invalid session_id {session_id}, creating new session")
                session_id = str(uuid.uuid4()) if not memory_manager.mongodb_available else str(ObjectId())
                session_doc = memory_manager._create_session_document(
                    session_id, user_id, DEFAULT_CHATBOT_ID, "Default Chat Session"
                )
                logger.info(f"Created recovery session: {session_id}")

        logger.info(f"Received query for session {session_id} from user {user_id}: {query}")
        chat_session = memory_manager._get_session_document(session_id)
        chatbot_id = chat_session["chatbot"]
        memory_manager.add_user_message(session_id, query, user_id=user_id)

        # Check if RAG system is available
        if rag is None:
            error_msg = f"RAG system not available: {rag_error}" if rag_error else "RAG system not initialized"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 500

        conversation_history = memory_manager.get_chat_history(session_id)
        # Retrieve long-term memory facts related to the query
        long_term_facts = memory_manager.retrieve_long_term_memory(session_id, query)
        if long_term_facts:
            conversation_history.insert(0, {
                "role": "system",
                "content": "LONG_TERM_MEMORY:\n" + "\n".join(long_term_facts)
            })
        try:
            logger.info(f"🤖 Starting RAG generation for query: {query[:50]}...")
            logger.info(f"🔧 RAG system available: {rag is not None}")
            logger.info(f"🔑 OpenRouter API Key configured: {bool(os.getenv('OPENROUTER_API_KEY'))}")
            
            response_data = rag.generate_answer(query, conversation_history)
            content = response_data.get("content", "")
            thinking = response_data.get("thinking", "")
            retrieved_context = response_data.get("retrieved_context", "")
            
            logger.info(f"✅ RAG generation successful, content length: {len(content)}")
        except Exception as e:
            logger.error(f"❌ RAG/LLM generation error: {e}", exc_info=True)
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"🔍 Error details: {str(e)}")
            
            # FALLBACK: Try direct OpenRouter API call without RAG
            logger.info("🔄 Attempting fallback: Direct OpenRouter API call...")
            try:
                import requests
                import json
                
                api_key = os.getenv('OPENROUTER_API_KEY')
                if not api_key:
                    raise Exception("No OpenRouter API key available")
                
                # Simple conversation without RAG retrieval
                messages = [
                    {"role": "system", "content": "You are a helpful wellness assistant. Provide helpful, accurate responses about health and wellness topics."}
                ]
                
                # Add conversation history (limited to last 5 messages)
                for msg in conversation_history[-5:]:
                    messages.append(msg)
                
                # Add current user query
                messages.append({"role": "user", "content": query})
                
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                data = {
                    "model": "openai/gpt-oss-120b",
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.1
                }
                
                logger.info("🌐 Making direct OpenRouter API call...")
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    thinking = "Direct API call (RAG system unavailable)"
                    retrieved_context = "No document retrieval (fallback mode)"
                    
                    # Create response_data structure for consistency with normal flow
                    response_data = {
                        "content": content,
                        "thinking": thinking,
                        "retrieved_context": retrieved_context,
                        "reranked": False,
                        "num_sources": 0
                    }
                    
                    logger.info(f"✅ Fallback successful, content length: {len(content)}")
                else:
                    logger.error(f"❌ OpenRouter API error: {response.status_code} - {response.text}")
                    raise Exception(f"OpenRouter API error: {response.status_code}")
                    
            except Exception as fallback_error:
                logger.error(f"❌ Fallback also failed: {fallback_error}")
                # Check if it's an OpenRouter/API error
                if hasattr(e, 'status_code') or 'api' in str(e).lower():
                    error_msg = f'LLM provider error: {str(e)[:400]}'
                    logger.error(f"🌐 API Error detected: {error_msg}")
                    return jsonify({'error': error_msg}), 502
                else:
                    error_msg = f'Chat generation failed: {str(e)}'
                    logger.error(f"💥 General error: {error_msg}")
                    return jsonify({'error': error_msg}), 500

        # Enhanced response information
        reranked = response_data.get("reranked", False) if USE_ENHANCED_RAG else False
        num_sources = response_data.get("num_sources", 0)

        logger.info(f"Generated response with {len(content)} characters. Reranked: {reranked}, Sources: {num_sources}")

        # Get message_id from AI message
        message_id = memory_manager.add_ai_message(session_id, content, user_id=user_id)

        response_json = {
            'response': content,
            'message_id': message_id,
            'session_id': session_id,
            'thinking': thinking,
            'retrieved_context': retrieved_context
        }
        
        # Add enhanced RAG metadata if available
        if USE_ENHANCED_RAG:
            response_json['rag_metadata'] = {
                'reranked': reranked,
                'num_sources': num_sources,
                'system_type': 'enhanced'
            }

        return jsonify(response_json)

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



@app.route('/api/rag/reindex', methods=['POST'])
def reindex_rag():
    try:
        sync_pdfs_from_s3()
        rag._ingest_documents()

        # Get all files currently in S3/local after sync
        local_files = {f for f in os.listdir(PDF_DIR) if f.lower().endswith('.pdf')}
        
        # Update status for each RAG file in the database
        for rag_file in memory_manager.ragfiles_collection.find({}):
            if rag_file.get("file_name") in local_files:
                memory_manager.ragfiles_collection.update_one(
                    {"_id": rag_file["_id"]},
                    {"$set": {
                        "ingestion_status": "success",
                        "ingestion_message": "Ingestion completed successfully.",
                        "date_modified": datetime.utcnow()
                    }}
                )
            else:
                memory_manager.ragfiles_collection.update_one(
                    {"_id": rag_file["_id"]},
                    {"$set": {
                        "ingestion_status": "missing",
                        "ingestion_message": "File not found in local PDFs folder.",
                        "date_modified": datetime.utcnow()
                    }}
                )

        return jsonify({'status': 'ok', 'message': 'PDFs synced & RAG vectorstore rebuilt.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500



@app.route('/api/health', methods=['GET'])
def api_health_check():
    return jsonify({'status': 'ok', 'message': 'RAG system is running'})

@app.route('/api/debug/routes', methods=['GET'])
def debug_routes():
    """Debug endpoint to list all available routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': str(rule)
        })
    return jsonify({'routes': routes})

@app.route('/minimal', methods=['GET'])
def minimal():
    """Serve the minimal HTML test file"""
    return send_from_directory('static', 'minimal.html')

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve Vite build assets (JS, CSS, etc.)"""
    return send_from_directory('static/assets', filename)

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Serve other static files from the static directory"""
    try:
        return send_from_directory('static', filename)
    except FileNotFoundError:
        # If file not found, serve index.html for SPA routing
        return send_from_directory('static', 'index.html')



if __name__ == '__main__':
    logger.info("Starting Flask server on port 5000")
    app.run(host='0.0.0.0', port=5000, debug=True) 