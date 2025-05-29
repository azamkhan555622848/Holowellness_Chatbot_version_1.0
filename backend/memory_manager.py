from langchain.memory import (
    ConversationBufferMemory,
    ConversationBufferWindowMemory,
    ConversationTokenBufferMemory,
    ConversationSummaryMemory
)
from langchain.schema import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
import os
from typing import Dict, List, Any, Optional
import time
import threading
import logging
from pymongo import MongoClient
from bson import ObjectId
import uuid
from datetime import datetime
import os
import threading
from pymongo import MongoClient
from dotenv import load_dotenv
from bson import ObjectId, errors

load_dotenv()  # Load environment variables from .env


logger = logging.getLogger(__name__)

class MemoryManager:
    """Manages conversation memory using LangChain memory components"""
    
    def __init__(self, memory_type: str = "buffer_window", max_token_limit: int = 2000):
        """
        Initialize the memory manager
        
        Args:
            memory_type: Type of memory to use (buffer, buffer_window, token_buffer, summary)
            max_token_limit: Maximum number of tokens to store in memory
        """

        # Inside MemoryManager.__init__()
        mongo_uri = os.getenv("MONGO_URI" )
        self.mongo_client = MongoClient(mongo_uri)
        self.mongo_db = self.mongo_client["db_holo_wellness"]
        self.chatbot_collection = self.mongo_db["chatbotinteractions"]

        self.memory_type = memory_type
        self.max_token_limit = max_token_limit
        self.sessions = {}
        self.last_access = {}
        
        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_old_sessions, daemon=True)
        self.cleanup_thread.start()
        
        # Initialize OpenAI client for summary memory if needed
        if memory_type == "summary":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable is required for summary memory")
            self.llm = ChatOpenAI(api_key=api_key)
    
    def _create_memory(self) -> Any:
        """Create a new memory instance based on the configured type"""
        if self.memory_type == "buffer":
            return ConversationBufferMemory(return_messages=True)
        elif self.memory_type == "buffer_window":
            return ConversationBufferWindowMemory(k=5, return_messages=True)
        elif self.memory_type == "token_buffer":
            return ConversationTokenBufferMemory(llm=self.llm, max_token_limit=self.max_token_limit, return_messages=True)
        elif self.memory_type == "summary":
            return ConversationSummaryMemory(llm=self.llm, return_messages=True)
        else:
            # Default to buffer window memory
            return ConversationBufferWindowMemory(k=5, return_messages=True)
        

    
    def get_session(self, session_id: str) -> Any:
        """Get or create a memory session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = self._create_memory()
        
        # Update last access time
        self.last_access[session_id] = time.time()
        return self.sessions[session_id]
    
  


    def _store_message_to_mongo(self, session_id: str, user_id: str, chatbot_id: str,
                            message_body: str, is_user: bool, previous_message: str = None):
        """
        Appends a message to an EXISTING session document in MongoDB.
        Does NOT create a new document if session not found.
        """
        try:
            chatbot_interaction_id = ObjectId(session_id)
        except (errors.InvalidId, TypeError):
            raise ValueError(f"Invalid session_id: {session_id}")

        user_object_id = ObjectId(user_id)
        chatbot_object_id = ObjectId(chatbot_id)
        now = datetime.utcnow()

        # Prepare the message document
        message_doc = {
            "message_id": str(uuid.uuid4()),
            "chatbot": chatbot_object_id,
            "message_body": message_body,
            "direction": is_user,
            "previous_message": previous_message,
            "created_at": now,
            "updated_at": now
        }

        # Only PUSH the message, do NOT upsert!
        result = self.chatbot_collection.update_one(
            {"_id": chatbot_interaction_id},
            {
                "$push": {"messages": message_doc},
                "$set": {"updated_at": now}
            }
            # upsert is omitted (False by default)
        )
        if result.matched_count == 0:
            raise ValueError(f"No session document found for session_id {session_id}. Message not stored.")
        
    def add_user_message(self, session_id, message, user_id=None):
        memory = self.get_session(session_id)
        memory.chat_memory.add_user_message(message)
        if user_id:
            # Fetch the chatbot_id from the session doc (should already exist!)
            session = self.chatbot_collection.find_one({"_id": ObjectId(session_id)})
            if not session:
                raise ValueError(f"No session found for id {session_id}")
            chatbot_id = session["chatbot"]
            self._store_message_to_mongo(session_id, user_id, chatbot_id, message, is_user=True)

    def add_ai_message(self, session_id, message, user_id=None, previous_message=None):
        memory = self.get_session(session_id)
        memory.chat_memory.add_ai_message(message)
        message_id = None
        if user_id:
            session = self.chatbot_collection.find_one({"_id": ObjectId(session_id)})
            chatbot_id = session["chatbot"]
            # -- Build message_doc here so you can get the UUID! --
            import uuid
            now = datetime.utcnow()
            message_doc = {
                "message_id": str(uuid.uuid4()),
                "chatbot": chatbot_id,
                "message_body": message,
                "direction": False,
                "previous_message": previous_message,
                "created_at": now,
                "updated_at": now
            }
            self.chatbot_collection.update_one(
                {"_id": ObjectId(session_id)},
                {
                    "$push": {"messages": message_doc},
                    "$set": {"updated_at": now}
                }
            )
            message_id = message_doc["message_id"]
        return message_id


    def rate_message(self, message_id: str, rating: int) -> None:
        """
        Assigns a rating to a specific message in a chatbot interaction.
        Args:
            message_id: The UUID string of the message inside the messages array.
            rating: Integer rating (e.g., 1–5).
        """
        from datetime import datetime

        result = self.chatbot_collection.update_one(
            {"messages.message_id": message_id},
            {
                "$set": {
                    "messages.$.rating": rating,
                    "messages.$.rated_at": datetime.utcnow()
                }
            }
        )

        if result.matched_count == 0:
            raise ValueError(f"Message with ID {message_id} not found.")


    def get_chat_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get the chat history for a session"""
        if session_id not in self.sessions:
            return []
        
        memory = self.sessions[session_id]
        messages = memory.chat_memory.messages
        
        # Convert LangChain messages to dict format
        history = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})
        
        return history
    
    def get_memory_variables(self, session_id: str) -> Dict[str, Any]:
        """Get memory variables for a session"""
        memory = self.get_session(session_id)
        return memory.load_memory_variables({})
    
    def clear_session(self, session_id: str) -> None:
        """Clear a session from memory"""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.last_access:
            del self.last_access[session_id]
    
    def _cleanup_old_sessions(self) -> None:
        """Periodically clean up old sessions to prevent memory leaks"""
        while True:
            try:
                current_time = time.time()
                session_timeout = 3600  # 1 hour in seconds
                
                # Find expired sessions
                expired_sessions = []
                for session_id, last_access in self.last_access.items():
                    if current_time - last_access > session_timeout:
                        expired_sessions.append(session_id)
                
                # Remove expired sessions
                for session_id in expired_sessions:
                    logger.info(f"Removing expired session: {session_id}")
                    self.clear_session(session_id)
                
                # If we have too many sessions, remove the oldest ones
                max_sessions = 100
                if len(self.sessions) > max_sessions:
                    # Sort sessions by last access time
                    sorted_sessions = sorted(
                        self.last_access.items(),
                        key=lambda x: x[1]
                    )
                    
                    # Remove oldest sessions
                    for session_id, _ in sorted_sessions[:len(self.sessions) - max_sessions]:
                        logger.info(f"Removing old session due to limit: {session_id}")
                        self.clear_session(session_id)
            
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
            
            # Sleep for 10 minutes
            time.sleep(600)


# Create a global instance with default settings
memory_manager = MemoryManager(memory_type="buffer_window") 