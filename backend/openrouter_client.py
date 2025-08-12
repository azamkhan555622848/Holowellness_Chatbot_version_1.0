"""
OpenRouter API client for HoloWellness Chatbot
Calls OpenRouter's Chat Completions API and returns an Ollama-like shape.

This version prefers a direct HTTPS call via requests so we can always
log full error bodies and set optional headers. If the requests path fails,
we attempt the official OpenAI client as a fallback.
"""
import os
from typing import Dict, List, Any
import logging
import requests
from requests import Response
try:
    import openai  # optional, fallback only
except Exception:  # pragma: no cover
    openai = None

logger = logging.getLogger(__name__)

class OpenRouterClient:
    """OpenRouter API client that mimics Ollama interface"""
    
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        # Default to the deployed DeepSeek model; override via OPENROUTER_MODEL
        self.model_name = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1-distill-qwen-14b")
        self.timeout_seconds = int(os.getenv("OPENROUTER_TIMEOUT", "30"))
        # Prepare optional fallback OpenAI client
        self.client = None
        if openai is not None and self.api_key:
            try:
                self.client = openai.OpenAI(base_url=self.base_url, api_key=self.api_key)
            except Exception as e:  # not fatal
                logger.warning(f"OpenAI client init failed, will use requests-only path: {e}")
    
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

        # Prefer direct requests path for robust error reporting
        try:
            max_tokens_env = int(os.getenv("OPENROUTER_MAX_TOKENS", "1000"))
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": options.get("temperature", 0.2),
                # Prefer option override, else env, else reasonable default
                "max_tokens": options.get("num_predict", max_tokens_env),
                "top_p": options.get("top_p", 0.9),
            }
            if "stop" in options and options["stop"]:
                payload["stop"] = options["stop"]

            headers = {
                "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                "Content-Type": "application/json",
                # Optional but helpful for OpenRouter analytics
                "HTTP-Referer": os.getenv("APP_PUBLIC_URL", "http://localhost"),
                "X-Title": os.getenv("APP_TITLE", "HoloWellness Chatbot"),
            }
            url = f"{self.base_url}/chat/completions"
            logger.info(f"Calling OpenRouter via requests with model={self.model_name}")
            r: Response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            if r.status_code != 200:
                logger.error(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")
                raise RuntimeError(f"OpenRouter HTTP {r.status_code}")

            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            return {
                "message": {"content": content},
                "model": self.model_name,
                "created_at": data.get("created"),
                "done": True,
            }
        except Exception as req_err:
            logger.error(f"Requests path failed: {type(req_err).__name__}: {req_err}")
            # Fallback to OpenAI client if available
            if self.client is not None:
                try:
                    params = {
                        "model": self.model_name,
                        "messages": messages,
                        "temperature": options.get("temperature", 0.2),
                        "max_tokens": options.get("num_predict", 600),
                        "top_p": options.get("top_p", 0.9),
                    }
                    if "stop" in options and options["stop"]:
                        params["stop"] = options["stop"]
                    response = self.client.chat.completions.create(**params)
                    content = response.choices[0].message.content
                    return {
                        "message": {"content": content.strip()},
                        "model": self.model_name,
                        "created_at": response.created,
                        "done": True,
                    }
                except Exception as e:  # final failure
                    logger.error(f"OpenAI client path failed: {type(e).__name__}: {e}")

        # Final fallback apology
        return {
            "message": {
                "content": (
                    "I apologize, but I'm having trouble processing your request right now. "
                    "Please try again in a moment."
                )
            },
            "error": "openrouter_call_failed",
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