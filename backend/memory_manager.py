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
    
    def add_user_message(self, session_id: str, message: str) -> None:
        """Add a user message to the memory"""
        memory = self.get_session(session_id)
        memory.chat_memory.add_user_message(message)
    
    def add_ai_message(self, session_id: str, message: str) -> None:
        """Add an AI message to the memory"""
        memory = self.get_session(session_id)
        memory.chat_memory.add_ai_message(message)
    
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