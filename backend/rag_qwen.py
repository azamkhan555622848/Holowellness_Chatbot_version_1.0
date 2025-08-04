#!/usr/bin/env python3
import os
import time
import PyPDF2
import numpy as np
import requests
import json
import docx
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False
    pytesseract = None

from PIL import Image
import io
import pickle
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import faiss
from dotenv import load_dotenv
import uuid
from datetime import datetime
from datetime import timedelta
import logging
import threading
import time as time_module
import re # Import regex module
# Use OpenRouter API instead of local Ollama
try:
    from openrouter_client import ollama
    print("Using OpenRouter API for LLM calls")
except ImportError:
    import ollama
    print("Using local Ollama (fallback)")
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    convert_from_path = None
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

load_dotenv()

class RAGSystem:
    def __init__(self, pdf_directory=None, model_name="deepseek-r1:14b-qwen-distill-q4_K_M", embeddings_model="all-MiniLM-L6-v2", cache_dir="cache", init_embeddings=True, top_k=5):
        """
        Initializes the RAG system with Ollama and OCR capabilities.
        """
        self.pdf_directory = pdf_directory or os.path.join(os.path.dirname(__file__), "pdfs")
        self.model_name = model_name
        self.translator_model = "llama3f1-medical"  # Translation model
        self.embeddings_model_name = embeddings_model
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self.chunk_size = 512
        self.chunk_overlap = 50
        self.top_k = top_k

        self.vector_cache = os.path.join(self.cache_dir, "vector_index.faiss")
        self.docs_cache = os.path.join(self.cache_dir, "documents.pkl")
        self.bm25_cache = os.path.join(self.cache_dir, "bm25_index.pkl")
        
        self.embedder = None
        self.vector_store = None
        self.documents = []
        self.bm25_index = None
        
        # Initialize EasyOCR (lazy loading)
        self.ocr_reader = None
        
        if init_embeddings and self.pdf_directory:
            self._load_or_create_embeddings()

    def _init_ocr(self):
        """Initialize OCR reader only when needed"""
        if not EASYOCR_AVAILABLE:
            print("EasyOCR not available - OCR functionality disabled")
            return False
        if self.ocr_reader is None:
            print("Initializing EasyOCR...")
            self.ocr_reader = easyocr.Reader(['en'])  # Add more languages if needed: ['en', 'es', 'fr']
            print("EasyOCR initialized successfully")
        return True

    def _chunk_text(self, text: str) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk = ' '.join(words[i:i + self.chunk_size])
            chunks.append(chunk)
        return chunks

    def _extract_text_from_pdf(self, file_path: str) -> str:
        """
        Enhanced PDF text extraction with OCR fallback for image-heavy pages
        """
        text = ""
        try:
            # First, try regular text extraction with PyPDF2
            with open(file_path, 'rb') as f:
                pdf = PyPDF2.PdfReader(f)
                pages_needing_ocr = []
                
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text and len(page_text.strip()) > 50:  # If substantial text found
                        text += page_text + "\n"
                    else:
                        # Mark page for OCR if little/no text extracted
                        pages_needing_ocr.append(page_num)
                
                # If we have pages that need OCR
                if pages_needing_ocr:
                    print(f"OCR needed for {len(pages_needing_ocr)} pages in {os.path.basename(file_path)}")
                    ocr_text = self._extract_text_with_ocr(file_path, pages_needing_ocr)
                    text += ocr_text
                
        except Exception as e:
            print(f"Error reading PDF {file_path}: {e}")
            # If PyPDF2 fails completely, try OCR on the entire document
            try:
                print(f"Falling back to OCR for entire document: {os.path.basename(file_path)}")
                text = self._extract_text_with_ocr(file_path)
            except Exception as ocr_error:
                print(f"OCR also failed for {file_path}: {ocr_error}")
        
        return text

    def _extract_text_with_ocr(self, file_path: str, specific_pages: List[int] = None) -> str:
        """
        Extract text using OCR from PDF pages
        """
        try:
            if not self._init_ocr():  # Initialize OCR if not already done
                return ""  # Return empty string if OCR not available
            
            if not PDF2IMAGE_AVAILABLE:
                print("pdf2image not available - cannot convert PDF to images for OCR")
                return ""
            
            # Convert PDF pages to images
            if specific_pages:
                # Convert only specific pages
                images = convert_from_path(file_path, first_page=min(specific_pages)+1, 
                                         last_page=max(specific_pages)+1)
                # Filter to only the pages we want
                images = [images[i - min(specific_pages)] for i in specific_pages if i - min(specific_pages) < len(images)]
            else:
                # Convert all pages
                images = convert_from_path(file_path)
            
            ocr_text = ""
            for i, image in enumerate(images):
                try:
                    # Use EasyOCR to extract text
                    results = self.ocr_reader.readtext(np.array(image))
                    page_text = " ".join([result[1] for result in results])
                    if page_text.strip():
                        ocr_text += f"Page {i+1} OCR: {page_text}\n"
                except Exception as e:
                    print(f"OCR failed for page {i+1}: {e}")
                    continue
            
            return ocr_text
            
        except Exception as e:
            print(f"OCR extraction failed for {file_path}: {e}")
            return ""

    def _extract_text_from_docx(self, file_path: str) -> str:
        try:
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            print(f"Error reading DOCX {file_path}: {e}")
            return ""

    def _process_file(self, file_path: str, source_info: str):
        file_ext = os.path.splitext(file_path)[1].lower()
        text = ""
        
        print(f"Processing: {os.path.basename(file_path)}")
        
        if file_ext == '.pdf':
            text = self._extract_text_from_pdf(file_path)
        elif file_ext == '.docx':
            text = self._extract_text_from_docx(file_path)
        
        if text:
            chunks = self._chunk_text(text)
            for chunk in chunks:
                self.documents.append({'text': chunk, 'source': source_info, 'file': os.path.basename(file_path)})
            print(f"Extracted {len(chunks)} chunks from {os.path.basename(file_path)}")

    def _ingest_documents(self):
        print("Processing documents...")
        for root, _, files in os.walk(self.pdf_directory):
            for file in files:
                self._process_file(os.path.join(root, file), os.path.basename(root))

    def _format_context(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Formats the retrieved chunks into a readable context string.
        Limits context size to prevent model hanging.
        """
        if not chunks:
            return "No relevant documents found."
        
        formatted_chunks = []
        total_length = 0
        max_context_length = 20000  # Increased to match Enhanced RAG
        
        for chunk in chunks:
            # Keep chunk size at 800 characters for good balance
            chunk_text = chunk['text'][:800] + "..." if len(chunk['text']) > 800 else chunk['text']
            formatted_chunk = f"Source: {chunk['file']} ({chunk['source']})\n{chunk_text}"
            
            if total_length + len(formatted_chunk) > max_context_length:
                break
                
            formatted_chunks.append(formatted_chunk)
            total_length += len(formatted_chunk)
        
        return "\n\n".join(formatted_chunks)

    def _hybrid_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Performs a hybrid search using both BM25 and FAISS.
        """
        # Vector search (FAISS)
        query_embedding = self.embedder.encode([query])
        D, I = self.vector_store.search(np.array(query_embedding, dtype=np.float32), k=self.top_k)
        vector_results_indices = I[0]

        # Keyword search (BM25)
        tokenized_query = query.split(" ")
        bm25_scores = self.bm25_index.get_scores(tokenized_query)
        bm25_top_n_indices = np.argsort(bm25_scores)[::-1][:self.top_k]

        # Combine results
        combined_indices = list(set(vector_results_indices) | set(bm25_top_n_indices))
        
        final_ids = combined_indices[:self.top_k]
        return [self.documents[i] for i in final_ids if i < len(self.documents)]

    def _translate_to_traditional_chinese(self, english_content: str) -> str:
        """Translate English medical response to Traditional Chinese using llama3f1-medical model."""
        translation_prompt = f"""請將以下英文醫療建議翻譯成繁體中文。保持專業的醫療語調，並確保翻譯準確且易於理解：

原文：
{english_content}

繁體中文翻譯："""

        try:
            def call_translator():
                return ollama.chat(
                    model=self.translator_model,
                    messages=[{"role": "user", "content": translation_prompt}],
                    options={
                        "temperature": 0.1,  # Lower temperature for consistent translation
                        "top_p": 0.7,
                        "num_predict": 400  # Limit translation length
                    }
                )
            
            # Use ThreadPoolExecutor for timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_translator)
                response = future.result(timeout=60)  # 60 second timeout
                translated_content = response.get('message', {}).get('content', '').strip()
                print(f"Translation complete: {len(translated_content)} characters")
                return translated_content
                
        except FutureTimeoutError as e:
            print(f"Translation timeout: {e}")
            return f"翻譯逾時：{english_content[:200]}..."  # Fallback: return truncated original
        except Exception as e:
            print(f"Translation error: {e}")
            return f"翻譯錯誤：{english_content}"  # Fallback: return original with error note

    def generate_answer(self, query: str, conversation_history: List[Dict[str, str]] = None, override_context: str = None, override_thinking: str = None) -> Dict[str, str]:
        """
        Generates an answer using two-step pipeline: 
        1. deepseek-r1 for medical content generation (English)
        2. llama3f1-medical for Traditional Chinese translation
        """
        start_time = time.time()
        
        if override_context is not None:
            context = override_context
            internal_thinking = override_thinking if override_thinking else ""
            relevant_chunks = [] 
        else:
            relevant_chunks = self._hybrid_search(query)
            context = self._format_context(relevant_chunks)
            internal_thinking = f"RAG Analysis:\nQuery: '{query}'\n"
            internal_thinking += f"Found {len(relevant_chunks)} relevant chunks.\n"

        # Build conversation context if available
        conversation_context = ""
        if conversation_history and len(conversation_history) > 0:
            conversation_context = "\n\nPrevious conversation context:\n"
            # Include last 3-4 exchanges to maintain context without overwhelming the prompt
            recent_history = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history
            for msg in recent_history:
                role = "Patient" if msg.get('role') == 'user' else "Dr. HoloWellness"
                conversation_context += f"{role}: {msg.get('content', '')}\n"

        system_prompt = f"""You are Dr. HoloWellness, a sports medicine doctor speaking to your patient. 

Medical information: {context}{conversation_context}

Example:
Patient: "I have shoulder pain when lifting my arm"
Dr. HoloWellness: "It sounds like you may have rotator cuff irritation or impingement. I recommend starting with ice for 15-20 minutes several times daily and avoiding overhead activities for a few days. Have you noticed if the pain is worse at night or when reaching behind your back?"

Now respond to your patient in the same natural, caring way. Give your assessment, two recommendations, and ask one follow-up question."""

        # Build messages with conversation history for better context
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent conversation history (last 2-3 exchanges) directly to messages
        if conversation_history and len(conversation_history) > 0:
            # Get last few exchanges, ensuring we don't exceed context limits
            recent_messages = conversation_history[-4:] if len(conversation_history) > 4 else conversation_history
            for msg in recent_messages:
                if msg.get('content'):
                    messages.append({
                        "role": msg.get('role', 'user'),
                        "content": msg.get('content', '')
                    })
        
        # Add current query with empty CoT to prevent thinking tokens (official DeepSeek method)
        messages.append({"role": "user", "content": query})
        messages.append({"role": "assistant", "content": "<think>\n\n</think>\n\n"})

        print("\n--- Step 1: Generating English Response with DeepSeek ---")
        print(f"Context length: {len(context)} characters")
        print(f"Query: {query}")
        
        try:
            # Step 1: Generate English response with deepseek-r1
            print("Calling DeepSeek model...")
            
            def call_ollama():
                return ollama.chat(
                    model=self.model_name,
                    messages=messages,
                    options={
                        "temperature": 0.4,  # Slightly more creative for natural responses
                        "top_p": 0.8,        # Allow more response variety
                        "num_predict": 300,  # Shorter to prevent long thinking
                        "stop": ["<think>", "Patient:", "Dr. HoloWellness:", "\n\n\n"]
                    }
                )
            
            # Use ThreadPoolExecutor for timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_ollama)
                response = future.result(timeout=90)  # Longer timeout for complete responses
                english_content = response.get('message', {}).get('content', '').strip()
                
                # Robust thinking token removal
                import re
                
                # Remove complete thinking blocks
                english_content = re.sub(r'<think>.*?</think>', '', english_content, flags=re.DOTALL)
                
                # Remove incomplete thinking blocks (everything after <think> if no closing tag)
                if '<think>' in english_content:
                    english_content = english_content.split('<think>')[0].strip()
                
                # Remove any remaining standalone tags
                english_content = re.sub(r'</?think>', '', english_content)
                english_content = english_content.strip()
                
                print(f"English Response: {english_content}")
                internal_thinking += f"\nEnglish Response: {english_content}"
            
            # Step 2: Translate to Traditional Chinese
            print("\n--- Step 2: Translating to Traditional Chinese ---")
            translated_content = self._translate_to_traditional_chinese(english_content)
            internal_thinking += f"\nTranslated Content: {translated_content}"

        except FutureTimeoutError as e:
            error_message = f"Model timeout: {e}"
            print(error_message)
            translated_content = f"抱歉，AI模型回應時間過長，請稍後重試。"
            internal_thinking += f"\nTimeout Error: {e}"
        except Exception as e:
            error_message = f"Error communicating with Ollama: {e}"
            print(error_message)
            translated_content = f"抱歉，我在連接AI模型時遇到錯誤：{e}"
            internal_thinking += f"\nOllama Error: {e}"
        
        print("--- Two-Step Pipeline Complete ---\n")
        total_time = time.time() - start_time
        logging.info(f"Answer generated in {total_time:.2f} seconds")

        return {
            "thinking": internal_thinking,
            "content": translated_content,
            "sources": relevant_chunks
        }

    def _load_or_create_embeddings(self):
        """
        Loads embeddings and indices from cache if they exist,
        otherwise creates them from the source documents.
        """
        self.embedder = SentenceTransformer(self.embeddings_model_name)

        if os.path.exists(self.docs_cache) and os.path.exists(self.bm25_cache) and os.path.exists(self.vector_cache):
            print("Loading embeddings and indices from cache...")
            with open(self.docs_cache, 'rb') as f:
                self.documents = pickle.load(f)
            with open(self.bm25_cache, 'rb') as f:
                self.bm25_index = pickle.load(f)
            self.vector_store = faiss.read_index(self.vector_cache)
            print(f"Loaded {len(self.documents)} documents from cache.")
        else:
            print("No cache found. Creating new embeddings and indices...")
            self._ingest_documents()
            self._save_embeddings()

    def _save_embeddings(self):
        """
        Creates and saves the embeddings and indices to the cache directory.
        """
        print("Saving embeddings and indices to cache...")
        
        embeddings = self.embedder.encode([doc['text'] for doc in self.documents])
        embeddings_np = np.array(embeddings, dtype=np.float32)
        
        self.vector_store = faiss.IndexFlatL2(embeddings_np.shape[1])
        self.vector_store.add(embeddings_np)
        faiss.write_index(self.vector_store, self.vector_cache)

        tokenized_corpus = [doc['text'].split(" ") for doc in self.documents]
        self.bm25_index = BM25Okapi(tokenized_corpus)
        with open(self.bm25_cache, 'wb') as f:
            pickle.dump(self.bm25_index, f)

        with open(self.docs_cache, 'wb') as f:
            pickle.dump(self.documents, f)
            
        print(f"Saved {len(self.documents)} documents and their indices to cache.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
    
    try:
        rag = RAGSystem(PDF_DIR)
        
        while True:
            query = input("\nEnter your question (or 'quit' to exit): ").strip()
            if query.lower() in {"quit", "exit"}:
                break
            
            response = rag.generate_answer(query)
            
            print("\n--- Thinking Process ---")
            print(response["thinking"])
            print("\n--- Final Answer ---")
            print(response["content"])
            if response.get('sources'):
                print("\n--- Sources ---")
                for source in response['sources']:
                    print(f"- {source['file']}")
                    
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True) 