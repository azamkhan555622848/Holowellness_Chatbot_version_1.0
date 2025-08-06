"""
OpenRouter API client for HoloWellness Chatbot
Replaces local Ollama calls with cloud-based API calls
"""
import openai
import os
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class OpenRouterClient:
    """OpenRouter API client that mimics Ollama interface"""
    
    def __init__(self):
        """Initialize OpenRouter client following official documentation"""
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        
        if not api_key:
            logger.warning("OPENROUTER_API_KEY not found in environment variables")
            api_key = "dummy_key"  # Provide a dummy key to prevent initialization errors
        
        try:
            # Initialize OpenRouter client according to official documentation
            # Start with minimal parameters to avoid compatibility issues
            self.client = openai.OpenAI(
                base_url=base_url,
                api_key=api_key
            )
            logger.info("OpenRouter client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OpenRouter client: {e}")
            logger.error(f"Error details: {type(e).__name__}: {str(e)}")
            self.client = None
                
        self.model_name = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")
    
    def chat(self, model: str, messages: List[Dict], options: Dict = None) -> Dict:
        """
        Chat completion that mimics Ollama's interface
        
        Args:
            model: Model name (ignored, uses configured model)
            messages: List of messages in OpenAI format
            options: Generation options (temperature, max_tokens, etc.)
        
        Returns:
            Dict with Ollama-compatible response format
        """
        if self.client is None:
            logger.error("OpenAI client not initialized - returning error response")
            return {
                "message": {
                    "role": "assistant",
                    "content": "Sorry, the OpenRouter client is not available. Please check your configuration."
                }
            }
            
        if options is None:
            options = {}
        
        try:
            # Map Ollama options to OpenAI parameters
            openai_params = {
                "model": self.model_name,
                "messages": messages,
                "temperature": options.get("temperature", 0.4),
                "max_tokens": options.get("num_predict", 300),
                "top_p": options.get("top_p", 0.8),
            }
            
            # Handle stop tokens
            if "stop" in options and options["stop"]:
                openai_params["stop"] = options["stop"]
            
            logger.info(f"Making OpenRouter API call with model: {self.model_name}")
            
            response = self.client.chat.completions.create(**openai_params)
            
            # Convert to Ollama-compatible format
            content = response.choices[0].message.content
            
            return {
                "message": {
                    "content": content.strip()
                },
                "model": self.model_name,
                "created_at": response.created,
                "done": True
            }
            
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            # Return fallback response
            return {
                "message": {
                    "content": "I apologize, but I'm having trouble processing your request right now. Please try again in a moment."
                },
                "error": str(e)
            }

# Global instance to replace ollama
openrouter_client = OpenRouterClient()

# Ollama-compatible interface
class OllamaCompatibleAPI:
    """Provides Ollama-compatible interface using OpenRouter"""
    
    @staticmethod
    def chat(model: str, messages: List[Dict], options: Dict = None) -> Dict:
        return openrouter_client.chat(model, messages, options)

# Create ollama-compatible object for drop-in replacement
ollama = OllamaCompatibleAPI()