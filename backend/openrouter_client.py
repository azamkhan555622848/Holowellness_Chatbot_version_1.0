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
        self.client = None
        api_key = os.getenv("OPENROUTER_API_KEY", "dummy_key")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        
        # Try multiple initialization approaches
        initialization_attempts = [
            # Attempt 1: Basic initialization with just required params
            lambda: openai.OpenAI(api_key=api_key, base_url=base_url),
            # Attempt 2: Minimal initialization with only API key
            lambda: openai.OpenAI(api_key=api_key),
            # Attempt 3: Use default initialization and set attributes after
            lambda: self._init_with_defaults(api_key, base_url)
        ]
        
        for i, init_func in enumerate(initialization_attempts):
            try:
                self.client = init_func()
                if self.client is not None:
                    logger.info(f"OpenAI client initialized successfully (attempt {i+1})")
                    break
            except Exception as e:
                logger.warning(f"OpenAI client initialization attempt {i+1} failed: {e}")
                if i == len(initialization_attempts) - 1:
                    logger.error("All OpenAI client initialization attempts failed - OpenRouter functionality will be disabled")
                    # Set client to None to prevent further errors
                    self.client = None
                
        self.model_name = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1")
        
        if not os.getenv("OPENROUTER_API_KEY"):
            logger.warning("OPENROUTER_API_KEY not found in environment variables")
    
    def _init_with_defaults(self, api_key: str, base_url: str):
        """Fallback initialization method"""
        try:
            # Set the environment variable temporarily for default initialization
            import os
            original_key = os.environ.get('OPENAI_API_KEY')
            os.environ['OPENAI_API_KEY'] = api_key
            
            client = openai.OpenAI()
            # Try to set base_url manually if possible
            if hasattr(client, 'base_url'):
                client.base_url = base_url
            
            # Restore original environment variable
            if original_key is not None:
                os.environ['OPENAI_API_KEY'] = original_key
            else:
                os.environ.pop('OPENAI_API_KEY', None)
                
            return client
        except Exception as e:
            # If that fails, try creating a minimal mock client
            logger.warning(f"Default initialization failed: {e}. Creating mock client.")
            return None
    
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