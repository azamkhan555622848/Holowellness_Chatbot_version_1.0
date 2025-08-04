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
        try:
            self.client = openai.OpenAI(
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=os.getenv("OPENROUTER_API_KEY")
            )
        except TypeError as e:
            if "proxies" in str(e):
                # Handle older OpenAI client version that doesn't support proxies
                logger.warning(f"OpenAI client initialization failed with proxies error: {e}")
                # Try without any additional parameters that might cause issues
                self.client = openai.OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=os.getenv("OPENROUTER_API_KEY", "dummy_key")
                )
            else:
                raise e
                
        self.model_name = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1")
        
        if not os.getenv("OPENROUTER_API_KEY"):
            logger.warning("OPENROUTER_API_KEY not found in environment variables")
    
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