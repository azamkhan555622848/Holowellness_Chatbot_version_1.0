#!/usr/bin/env python3
import os
import time
import PyPDF2
import numpy as np
import requests
import json
import docx
import pytesseract
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

load_dotenv()

class RAGSystem:
    def __init__(self, pdf_dir: str):
        self.pdf_dir = pdf_dir
        self.chunk_size = 512  # tokens
        self.chunk_overlap = 50  # tokens
        self.top_k = 5  # number of chunks to retrieve
        self.together_api_key = os.getenv("TOGETHER_API_KEY")
        self.model_name = "deepseek-ai/deepseek-r1-distill-qwen-14b" # Using the specified distilled Qwen model
        self.cache_file = os.path.join(pdf_dir, "rag_cache.pkl")
        
        if not self.together_api_key:
            raise ValueError("Missing Together API key in environment variables")
        
        # Initialize components
        # Using BGE-M3 for balanced Chinese/English, requires more memory
        self.embedder = SentenceTransformer('BAAI/bge-m3')
        # Alternatively, use a smaller model if memory is an issue:
        # self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.documents = []
        self.vector_index = None
        self.bm25_index = None
        
        # Create indexes
        self._ingest_documents()

    def _generate_response(self, prompt: str) -> str:
        """Generate response using Together AI API"""
        # Using Together AI endpoint
        headers = {
            "Authorization": f"Bearer {self.together_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                 {"role": "system", "content": "You are an AI assistant that answers questions using the provided context. If you don't know the answer, say so. Cite sources using [Source: filename]."},
                 {"role": "user", "content": prompt}
            ],
            "max_tokens": 3000,
            "temperature": 0.7,
            "top_p": 0.95
        }
        try:
            response = requests.post(
                "https://api.together.xyz/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            raise Exception(f"Together AI API request failed: {str(e)}")
        except Exception as e:
             # Catch other potential errors like JSON decoding errors
            raise Exception(f"An error occurred processing the Together AI response: {str(e)}")
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk = ' '.join(words[i:i + self.chunk_size])
            chunks.append(chunk)
        return chunks
    
    def _extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file, using OCR as fallback if needed."""
        extracted_text = ""
        try:
            # First, try PyPDF2 for faster extraction from text-based PDFs
            with open(file_path, 'rb') as f:
                try:
                    pdf = PyPDF2.PdfReader(f)
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text: # Check if text was extracted
                            extracted_text += page_text + "\n"
                except Exception as pypdf_err:
                    print(f"PyPDF2 failed for {file_path}: {pypdf_err}. Attempting OCR.")
                    extracted_text = "" # Reset text if PyPDF2 fails

            # If PyPDF2 extracted very little text, assume it's image-based and try OCR
            # Adjust the threshold as needed based on typical empty page content
            MIN_TEXT_LENGTH_THRESHOLD = 100 
            if len(extracted_text.strip()) < MIN_TEXT_LENGTH_THRESHOLD:
                print(f"Minimal text extracted with PyPDF2 from {file_path}. Attempting OCR...")
                try:
                    # Use pytesseract to OCR the entire PDF
                    # Specify languages needed (e.g., English + Simplified/Traditional Chinese)
                    ocr_text = pytesseract.image_to_string(file_path, lang='eng+chi_sim+chi_tra')
                    # Simple check if OCR produced more text than PyPDF2
                    if len(ocr_text.strip()) > len(extracted_text.strip()):
                         print(f"OCR successful for {file_path}")
                         extracted_text = ocr_text
                    else:
                         print(f"OCR did not yield more text for {file_path}. Using PyPDF2 result (if any).")

                except pytesseract.TesseractNotFoundError:
                    print("*********************************************************")
                    print("ERROR: Tesseract is not installed or not in your PATH.")
                    print("Please install Tesseract OCR engine for your system.")
                    print("Example (Ubuntu/Debian): sudo apt install tesseract-ocr")
                    print("*********************************************************")
                    # Return whatever PyPDF2 found, or empty string
                    return extracted_text 
                except Exception as ocr_err:
                    print(f"OCR failed for {file_path}: {ocr_err}")
                    # Fallback to PyPDF2 text if OCR fails
            
            return extracted_text

        except Exception as e:
            print(f"Error processing PDF {file_path}: {e}")
            return "" # Return empty string on failure
    
    def _extract_text_from_docx(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            doc = docx.Document(file_path)
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n"
            return text
        except Exception as e:
            print(f"Error extracting text from DOCX {file_path}: {e}")
            return ""
    
    def _extract_text_from_image(self, file_path: str) -> str:
        """Extract text from image using OCR"""
        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            print(f"Error extracting text from image {file_path}: {e}")
            return ""
    
    def _process_file(self, file_path: str, source_info: str) -> None:
        """Process a single file and add chunks to documents"""
        try:
            # Get file extension
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.pdf':
                # Process PDF file
                text = self._extract_text_from_pdf(file_path)
            elif file_ext == '.docx':
                # Process DOCX file
                text = self._extract_text_from_docx(file_path)
            else:
                print(f"Unsupported file type: {file_ext}")
                return
                
            if not text:
                print(f"No text extracted from {file_path}")
                return
                
            # Split into chunks
            chunks = self._chunk_text(text)
            
            # Add chunks to documents list
            for chunk in chunks:
                self.documents.append({
                    'text': chunk,
                    'source': source_info,
                    'file': os.path.basename(file_path)
                })
                
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    def _should_rebuild_cache(self) -> bool:
        """Check if cache needs to be rebuilt based on file modifications"""
        if not os.path.exists(self.cache_file):
            return True
            
        cache_mtime = os.path.getmtime(self.cache_file)
        
        # Check if any document is newer than the cache
        for root, dirs, files in os.walk(self.pdf_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.getmtime(file_path) > cache_mtime:
                    print(f"File {file_path} was modified after cache was created")
                    return True
                    
        return False
    
    def _ingest_documents(self):
        """Process all documents and create search indexes with caching"""
        # Try to load from cache if it exists and is up-to-date
        if os.path.exists(self.cache_file) and not self._should_rebuild_cache():
            try:
                print("Loading documents and indexes from cache...")
                with open(self.cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    self.documents = cache_data['documents']
                    self.bm25_index = cache_data['bm25_index']
                    self.vector_index = cache_data['vector_index']
                    print(f"Loaded {len(self.documents)} chunks from cache")
                    return
            except Exception as e:
                print(f"Error loading cache: {e}. Rebuilding indexes...")
        
        print("Processing documents...")
        
        # Process main PDF files
        for filename in os.listdir(self.pdf_dir):
            file_path = os.path.join(self.pdf_dir, filename)
            
            # Skip directories for now
            if os.path.isdir(file_path):
                continue
                
            if filename.endswith(".pdf"):
                print(f"Processing main PDF: {filename}")
                self._process_file(file_path, "Main Reference")
        
        # Process case study folders
        for case_folder in os.listdir(self.pdf_dir):
            case_dir = os.path.join(self.pdf_dir, case_folder)
            
            if os.path.isdir(case_dir) and case_folder.lower().startswith("case"):
                print(f"Processing case folder: {case_folder}")
                
                # Process all files in the case folder
                for case_file in os.listdir(case_dir):
                    file_path = os.path.join(case_dir, case_file)
                    
                    if os.path.isfile(file_path):
                        self._process_file(file_path, case_folder)
        
        # Process Algorithm_docs directory
        algorithm_docs_dir = os.path.join(self.pdf_dir, "Algorithm_docs")
        if os.path.exists(algorithm_docs_dir):
            print("Processing Algorithm_docs directory...")
            for filename in os.listdir(algorithm_docs_dir):
                file_path = os.path.join(algorithm_docs_dir, filename)
                if os.path.isfile(file_path):
                    print(f"Processing algorithm document: {filename}")
                    self._process_file(file_path, "Algorithm_docs")

        # Process trigger point directory
        trigger_point_dir = os.path.join(self.pdf_dir, "trigger point")
        if os.path.exists(trigger_point_dir):
            print("Processing trigger point directory...")
            for filename in os.listdir(trigger_point_dir):
                file_path = os.path.join(trigger_point_dir, filename)
                if os.path.isfile(file_path):
                    print(f"Processing trigger point document: {filename}")
                    self._process_file(file_path, "trigger point")
        
        if not self.documents:
            print("Warning: No documents were processed. Check file paths and formats.")
            return
            
        print(f"Processed {len(self.documents)} chunks from all documents")
        
        # Create BM25 index
        tokenized_docs = [doc["text"].split() for doc in self.documents]
        self.bm25_index = BM25Okapi(tokenized_docs)
        
        # Create FAISS vector index with batch processing
        # Process in batches to avoid memory issues with large embedders like bge-m3
        batch_size = 8  # Reduced batch size further
        num_batches = (len(self.documents) + batch_size - 1) // batch_size
        print(f"Creating vector index with batch processing (size {batch_size})...")

        # Process first batch to initialize the index
        first_batch_docs = self.documents[:batch_size]
        first_embeddings = self.embedder.encode([doc['text'] for doc in first_batch_docs], normalize_embeddings=True) # Normalize for IP index
        
        # Ensure embeddings are float32
        first_embeddings = np.array(first_embeddings).astype('float32')
        
        # Get embedding dimension
        if len(first_embeddings) == 0:
            print("Warning: No documents to index.")
            self.vector_index = None
            return # Exit if no documents
            
        d = first_embeddings.shape[1]
        # Use IndexFlatIP for cosine similarity with normalized embeddings
        self.vector_index = faiss.IndexFlatIP(d) 
        self.vector_index.add(first_embeddings)

        # Process remaining batches
        for i in range(1, num_batches):
            start_idx = i * batch_size
            end_idx = min((i + 1) * batch_size, len(self.documents))
            batch_docs = self.documents[start_idx:end_idx]
            if not batch_docs: # Skip empty batches
                continue
                
            print(f"Processing batch {i+1}/{num_batches} ({len(batch_docs)} documents)")
            batch_embeddings = self.embedder.encode([doc['text'] for doc in batch_docs], normalize_embeddings=True)
            batch_embeddings = np.array(batch_embeddings).astype('float32')
            self.vector_index.add(batch_embeddings)
            # Optional: Add a small delay or clear cache if memory pressure is extreme
            # import gc
            # gc.collect()
            # torch.cuda.empty_cache() # If using PyTorch backend explicitly
            # time.sleep(0.1)
            
        print(f"FAISS index created with {self.vector_index.ntotal} vectors.")
        
        # Save to cache
        try:
            print("Saving documents and indexes to cache...")
            with open(self.cache_file, 'wb') as f:
                pickle.dump({
                    'documents': self.documents,
                    'bm25_index': self.bm25_index,
                    'vector_index': self.vector_index
                }, f)
            print("Cache saved successfully")
        except Exception as e:
            print(f"Error saving cache: {e}")

    def _format_context(self, chunks: List[Dict[str, Any]]) -> str:
        """Format the retrieved chunks into a context string for the LLM"""
        formatted_chunks = []
        for chunk in chunks:
            # Include source and file information
            formatted_chunks.append(f"Source: {chunk['file']} ({chunk['source']})\n{chunk['text']}")
        
        return "\n\n".join(formatted_chunks)

    def _hybrid_search(self, query: str) -> List[Dict[str, Any]]:
        """Perform hybrid search and return top chunks"""
        if not self.documents or self.vector_index is None or self.bm25_index is None:
            print("Warning: Documents not indexed or indexes not created. Search will return empty results.")
            return []

        try:
            # Vector search
            # Ensure query embedding is correctly shaped and typed
            query_embedding = self.embedder.encode([query], normalize_embeddings=True)[0] # Normalize for IP index
            vector_query = np.array([query_embedding]).astype('float32')
            
            # Check if vector_index exists and has vectors
            if self.vector_index is None or self.vector_index.ntotal == 0:
                 print("Warning: FAISS index is not initialized or empty.")
                 vector_ids = [[]] # Return empty list of lists to match expected format
            else:
                 _, vector_ids = self.vector_index.search(vector_query, self.top_k * 2)
            
            # BM25 search
            tokenized_query = query.split()
            bm25_scores = self.bm25_index.get_scores(tokenized_query)
            # Get indices sorted by score, descending
            bm25_ids = np.argsort(bm25_scores)[::-1][:self.top_k * 2]
            
            # Combine and deduplicate results using a set for efficiency
            # Ensure vector_ids[0] is handled correctly, could be empty
            v_ids = vector_ids[0].tolist() if len(vector_ids) > 0 and len(vector_ids[0]) > 0 else []
            b_ids = bm25_ids.tolist()
            combined_ids = set(v_ids + b_ids)

            # Score combined results for ranking (example: simple weighted sum)
            # Note: This scoring needs refinement for optimal hybrid results
            # We need the actual vector embeddings of the documents for cosine similarity
            # Storing embeddings alongside documents or re-calculating is needed
            # For now, using a simplified rank based on BM25 and presence in vector results

            scored_results = []
            for doc_id in combined_ids:
                # Check if doc_id is valid
                if 0 <= doc_id < len(self.documents):
                    bm25_score = bm25_scores[doc_id]
                    # Placeholder for vector score - requires access to document embeddings
                    # vector_score = np.dot(query_embedding, self.doc_embeddings[doc_id]) # Example if embeddings are stored
                    vector_score = 1.0 if doc_id in v_ids else 0.0 # Simple presence check
                    
                    # Combine scores (adjust weights as needed)
                    combined_score = 0.6 * bm25_score + 0.4 * vector_score
                    scored_results.append((doc_id, combined_score))
                else:
                     print(f"Warning: Invalid document ID {doc_id} encountered during hybrid search.")


            # Sort by combined score, descending
            sorted_results = sorted(scored_results, key=lambda x: x[1], reverse=True)
            
            # Get the final top_k document indices
            final_ids = [doc_id for doc_id, score in sorted_results[:self.top_k]]

            # Retrieve the actual document chunks
            return [self.documents[i] for i in final_ids]

        except Exception as e:
            print(f"Error during hybrid search:\n{e}") # Print full exception
            import traceback
            traceback.print_exc() # Print traceback for detailed debugging
            return [] # Return empty list on error

    def generate_answer(self, query: str, conversation_history: List[Dict[str, str]] = None) -> Dict[str, str]:
        """Generate an answer using RAG (English), falling back to general knowledge."""
        start_time = time.time()

        try:
            relevant_chunks = self._hybrid_search(query)
        except Exception as search_err:
            print(f"Hybrid search failed unexpectedly: {search_err}")
            relevant_chunks = [] # Treat search failure as no relevant chunks found

        # Generate internal thinking string (for logging)
        internal_thinking = ""
        context = "" # Initialize context

        if relevant_chunks:
            context = self._format_context(relevant_chunks)
            for i, chunk in enumerate(relevant_chunks): # Use limited number for thinking log
                internal_thinking += f"[Chunk {i+1} - {chunk['source']} - {chunk['file']}]\n"
                excerpt = chunk['text'][:300] + "..." if len(chunk['text']) > 300 else chunk['text']
                internal_thinking += excerpt + "\n\n"
            internal_thinking += "\nAnalysis:\n"
            internal_thinking += f"User query: '{query}'. Retrieved {len(relevant_chunks)} relevant chunks. Constructing answer using Together AI with context."
        else:
            # Even if no chunks found or search failed, proceed to LLM
            context = "No specific context found."
            internal_thinking = f"No relevant information found in the knowledge base for query: '{query}'. Attempting to answer using general knowledge."

        # --- Call the LLM --- 
        # Prepare conversation history 
        formatted_history = []
        if conversation_history:
            # Use only recent history to fit context window
            recent_history = conversation_history[-6:] # Limit history length
            for message in recent_history:
                # Ensure role and content exist
                if 'role' in message and 'content' in message:
                        formatted_history.append({"role": message['role'], "content": message['content']})

        # Updated System Prompt for allowing general knowledge but keeping constraints
        system_prompt = f"""# SYSTEM
You are HoloWellness, an AI assistant simulating a professional human doctor. Your goal is to provide **extremely concise and brief** advice.

- Use the CONTEXT below to answer the user's question if relevant information is available. Limit your response to **a few key sentences** summarizing the most critical points from the context.
- If the CONTEXT doesn't help, answer the question briefly based on your general medical knowledge.
- **Format answers using Markdown** (e.g., bullet points for clarity).
- Cite sources using [Source: filename] *only* if the information comes **directly** from the CONTEXT.
- After the brief answer, suggest **one relevant follow-up question** if appropriate.

CONTEXT:
{context}

Please answer the user's question, keeping it brief and professional, and suggest a follow-up question."""

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(formatted_history)
        messages.append({"role": "user", "content": query})

        try:
            headers = {
                "Authorization": f"Bearer {self.together_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": 1024, # Reduced max_tokens for brevity
                "temperature": 0.5, # Lower temperature for more focused response
                "top_p": 0.9
            }
            response = requests.post(
                "https://api.together.xyz/v1/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                error_text = response.text
                print(f"Error from TogetherAI API ({response.status_code}): {error_text}")
                generated_content = f"Error generating response. API returned status code {response.status_code}."
                internal_thinking += f"\nAPI Error ({response.status_code}): {error_text}"
            else:
                response_data = response.json()
                # Check for potential errors or empty choices in the response
                if 'choices' in response_data and response_data['choices'] and 'message' in response_data['choices'][0] and 'content' in response_data['choices'][0]['message']:
                        raw_content = response_data['choices'][0]['message']['content'].strip()
                        # Remove potential internal thoughts if the model adds them (e.g., <think>...</think>)
                        generated_content = re.sub(r"<think>.*?</think>\s*", "", raw_content, flags=re.DOTALL).strip()
                        internal_thinking += f"\nLLM Raw Response: {raw_content}" # Log raw response
                else:
                        print(f"Unexpected response structure from TogetherAI: {response_data}")
                        generated_content = "Error: Received an unexpected response structure from the AI service."
                        internal_thinking += f"\nAPI Response Error: Unexpected structure {response_data}"


        except requests.exceptions.RequestException as req_e:
            print(f"Network error calling TogetherAI API: {req_e}")
            generated_content = f"I encountered a network error trying to reach the AI service: {str(req_e)}"
            internal_thinking += f"\nNetwork Error calling TogetherAI: {str(req_e)}"
        except Exception as e:
            print(f"Error processing TogetherAI response: {e}")
            generated_content = f"I encountered an error while processing the AI response: {str(e)}"
            internal_thinking += f"\nError processing TogetherAI response: {str(e)}"

        # --- Return generated content --- 
        total_time = time.time() - start_time
        print(f"Answer generated in {total_time:.2f} seconds")
        print(f"Internal Thinking Process:\n{internal_thinking}")

        return {
            "thinking": internal_thinking,
            "content": generated_content
        }

if __name__ == "__main__":
    # Configuration
    PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")  # Update this path as needed
    
    # Initialize system with PDF directory; model is loaded from environment variables
    rag = RAGSystem(PDF_DIR)
    
    # Interactive loop
    while True:
        query = input("\nEnter your question (or 'quit' to exit): ").strip()
        if query.lower() in {"quit", "exit"}:
            break
        
        # Get response with thinking and content
        response = rag.generate_answer(query)
        
        # Print thinking if requested
        print("\n--- Thinking Process (Internal) ---")
        print(response["thinking"])
        print("\n--- Response (Displayed to User) ---")
        print(response["content"])

# Store conversation sessions
conversations = {}
# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Session cleanup settings
SESSION_TIMEOUT = 60 * 60  # 1 hour in seconds
MAX_SESSIONS = 100  # Maximum number of sessions to keep

def cleanup_sessions():
    """Remove old sessions to prevent memory leaks"""
    while True:
        try:
            current_time = datetime.now()
            sessions_to_remove = []

            # Iterate over a copy of keys to allow deletion during iteration
            session_ids = list(conversations.keys())

            for session_id in session_ids:
                # Check if session still exists before accessing
                if session_id not in conversations:
                    continue

                messages = conversations[session_id]
                if not messages:
                    # Potentially remove empty sessions immediately or after a shorter timeout
                    # sessions_to_remove.append(session_id)
                    continue

                try:
                    # Ensure timestamp exists and is valid ISO format
                    if 'timestamp' in messages[-1]:
                         last_message_time = datetime.fromisoformat(messages[-1]['timestamp'])
                         if (current_time - last_message_time).total_seconds() > SESSION_TIMEOUT:
                             sessions_to_remove.append(session_id)
                    else:
                         # Handle missing timestamp - maybe remove immediately or log warning
                         logger.warning(f"Session {session_id} last message missing timestamp.")
                         # sessions_to_remove.append(session_id) # Option: remove if timestamp is missing

                except (ValueError, TypeError) as time_err:
                    logger.error(f"Error parsing timestamp for session {session_id}: {time_err}. Message: {messages[-1]}")
                    # Decide how to handle invalid timestamps (e.g., remove session)
                    # sessions_to_remove.append(session_id)

            # Remove expired/problematic sessions
            for session_id in sessions_to_remove:
                 # Check if session still exists before deleting
                 if session_id in conversations:
                     logger.info(f"Removing expired/problematic session: {session_id}")
                     del conversations[session_id]

            # If we still have too many sessions, remove oldest ones
            if len(conversations) > MAX_SESSIONS:
                # Sort sessions by last message time (handle missing/invalid timestamps)
                def get_session_time(item):
                    session_id, messages = item
                    if messages and 'timestamp' in messages[-1]:
                        try:
                            return datetime.fromisoformat(messages[-1]['timestamp'])
                        except (ValueError, TypeError):
                            return datetime.min # Treat invalid timestamps as very old
                    return datetime.min # Treat empty or timestamp-less sessions as very old

                # Sort items safely
                sorted_sessions = sorted(conversations.items(), key=get_session_time)

                # Remove oldest sessions
                num_to_remove = len(conversations) - MAX_SESSIONS
                for session_id, _ in sorted_sessions[:num_to_remove]:
                     # Check if session still exists before deleting
                     if session_id in conversations:
                         logger.info(f"Removing old session due to limit: {session_id}")
                         del conversations[session_id]

        except Exception as e:
            # Log general errors in the cleanup loop
            logger.error(f"Error in session cleanup loop: {e}", exc_info=True)

        # Sleep for 10 minutes
        time_module.sleep(600)


# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_sessions, daemon=True)
cleanup_thread.start()

# Create static directory if it doesn't exist 