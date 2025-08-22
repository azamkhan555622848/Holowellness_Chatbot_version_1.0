"""
Professional Lambda-based RAG Indexing Service
Handles document processing in /tmp with proper error handling and monitoring
"""

import json
import os
import tempfile
import logging
import boto3
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import traceback

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class IndexingConfig:
    """Configuration for indexing job"""
    s3_bucket: str
    s3_pdfs_prefix: str
    s3_cache_prefix: str
    max_processing_time: int = 840  # 14 minutes (leave 1 min buffer)
    batch_size: int = 3  # Process 3 PDFs at a time
    max_memory_mb: int = 2800  # Leave buffer for Lambda
    
@dataclass
class IndexingResult:
    """Result of indexing operation"""
    success: bool
    documents_processed: int
    total_documents: int
    processing_time: float
    cache_size_mb: float
    error_message: Optional[str] = None
    files_created: List[str] = None

class ResourceMonitor:
    """Monitor Lambda resources during processing"""
    
    def __init__(self):
        self.start_time = time.time()
        self.memory_limit_mb = int(os.environ.get('AWS_LAMBDA_FUNCTION_MEMORY_SIZE', '3008'))
        
    def check_time_remaining(self) -> float:
        """Return seconds remaining before timeout"""
        elapsed = time.time() - self.start_time
        return 900 - elapsed  # 15 minutes - elapsed
        
    def check_memory_usage(self) -> Dict[str, float]:
        """Check memory usage (simplified for Lambda)"""
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        return {
            'used_mb': memory_info.rss / 1024 / 1024,
            'available_mb': self.memory_limit_mb - (memory_info.rss / 1024 / 1024)
        }
        
    def should_continue(self) -> bool:
        """Check if we should continue processing"""
        time_remaining = self.check_time_remaining()
        memory_info = self.check_memory_usage()
        
        return (
            time_remaining > 120 and  # At least 2 minutes left
            memory_info['available_mb'] > 500  # At least 500MB available
        )

class S3Manager:
    """Professional S3 operations with error handling"""
    
    def __init__(self, bucket: str):
        self.bucket = bucket
        self.s3_client = boto3.client('s3')
        
    def list_pdfs(self, prefix: str) -> List[str]:
        """List all PDF files in S3 prefix"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=1000
            )
            
            pdf_files = []
            for obj in response.get('Contents', []):
                if obj['Key'].lower().endswith('.pdf'):
                    pdf_files.append(obj['Key'])
                    
            logger.info(f"Found {len(pdf_files)} PDF files in s3://{self.bucket}/{prefix}")
            return pdf_files
            
        except Exception as e:
            logger.error(f"Error listing PDFs: {str(e)}")
            raise
            
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """Download file from S3 with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading s3://{self.bucket}/{s3_key} to {local_path}")
                self.s3_client.download_file(self.bucket, s3_key, local_path)
                return True
                
            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to download {s3_key} after {max_retries} attempts")
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
                
        return False
        
    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """Upload file to S3 with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Uploading {local_path} to s3://{self.bucket}/{s3_key}")
                self.s3_client.upload_file(local_path, self.bucket, s3_key)
                return True
                
            except Exception as e:
                logger.warning(f"Upload attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to upload {s3_key} after {max_retries} attempts")
                    raise
                time.sleep(2 ** attempt)
                
        return False
        
    def upload_json(self, data: Dict, s3_key: str) -> bool:
        """Upload JSON data directly to S3"""
        try:
            logger.info(f"Uploading JSON to s3://{self.bucket}/{s3_key}")
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json.dumps(data, indent=2),
                ContentType='application/json'
            )
            return True
        except Exception as e:
            logger.error(f"Failed to upload JSON {s3_key}: {str(e)}")
            raise

class RAGIndexer:
    """Professional RAG indexing with batching and optimization"""
    
    def __init__(self, temp_dir: str, config: IndexingConfig):
        self.temp_dir = temp_dir
        self.config = config
        self.monitor = ResourceMonitor()
        
        # Import heavy dependencies only when needed
        self._vector_store = None
        self._embeddings = None
        
    def _load_dependencies(self):
        """Lazy load heavy ML dependencies"""
        if self._vector_store is None:
            logger.info("Loading vector store dependencies...")
            # Import your enhanced_rag_qwen components here
            # from enhanced_rag_qwen import EnhancedRAG
            # self._vector_store = EnhancedRAG()
            
    def process_batch(self, pdf_files: List[str], s3_manager: S3Manager) -> Dict[str, Any]:
        """Process a batch of PDFs with memory optimization"""
        batch_result = {
            'processed': 0,
            'failed': [],
            'documents': []
        }
        
        for pdf_file in pdf_files:
            if not self.monitor.should_continue():
                logger.warning("Resource limits reached, stopping batch processing")
                break
                
            try:
                # Download PDF to temp location
                local_pdf = os.path.join(self.temp_dir, os.path.basename(pdf_file))
                s3_manager.download_file(pdf_file, local_pdf)
                
                # Process PDF (implement your PDF processing logic)
                documents = self._process_single_pdf(local_pdf)
                batch_result['documents'].extend(documents)
                batch_result['processed'] += 1
                
                # Clean up immediately to save space
                os.remove(local_pdf)
                logger.info(f"Processed and cleaned up {pdf_file}")
                
            except Exception as e:
                logger.error(f"Failed to process {pdf_file}: {str(e)}")
                batch_result['failed'].append({
                    'file': pdf_file,
                    'error': str(e)
                })
                
        return batch_result
        
    def _process_single_pdf(self, pdf_path: str) -> List[Dict]:
        """Process single PDF and extract documents using PyPDF2"""
        import PyPDF2
        import re
        
        documents = []
        logger.info(f"Processing PDF: {pdf_path}")
        
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # Extract text from all pages
                full_text = ""
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            full_text += f"\n--- Page {page_num + 1} ---\n{page_text}"
                    except Exception as e:
                        logger.warning(f"Failed to extract text from page {page_num + 1}: {e}")
                
                if full_text.strip():
                    # Clean and chunk the text
                    cleaned_text = self._clean_text(full_text)
                    chunks = self._chunk_text(cleaned_text, pdf_path)
                    documents.extend(chunks)
                    
                    logger.info(f"Extracted {len(chunks)} chunks from {pdf_path}")
                else:
                    logger.warning(f"No text extracted from {pdf_path}")
                    
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {str(e)}")
            
        return documents
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove page markers
        text = re.sub(r'--- Page \d+ ---', '', text)
        # Remove special characters that might cause issues
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)]', ' ', text)
        return text.strip()
    
    def _chunk_text(self, text: str, source_file: str, chunk_size: int = 1000, overlap: int = 200) -> List[Dict]:
        """Split text into overlapping chunks"""
        chunks = []
        
        # Simple sentence-aware chunking
        sentences = re.split(r'[.!?]+', text)
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # If adding this sentence would exceed chunk size, start new chunk
            if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
                chunks.append({
                    'content': current_chunk.strip(),
                    'source': source_file,
                    'chunk_id': len(chunks),
                    'char_count': len(current_chunk)
                })
                
                # Start new chunk with overlap
                words = current_chunk.split()
                if len(words) > overlap // 10:  # Rough word-based overlap
                    current_chunk = ' '.join(words[-(overlap // 10):]) + ' ' + sentence
                else:
                    current_chunk = sentence
            else:
                current_chunk += ' ' + sentence
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append({
                'content': current_chunk.strip(),
                'source': source_file,
                'chunk_id': len(chunks),
                'char_count': len(current_chunk)
            })
        
        return chunks
        
    def build_indexes(self, documents: List[Dict]) -> Dict[str, str]:
        """Build hybrid BM25 + semantic vector indexes from documents"""
        logger.info(f"Building hybrid indexes from {len(documents)} documents")
        
        if not documents:
            logger.warning("No documents to index")
            return {}
        
        try:
            # Import dependencies here to reduce cold start
            import pickle
            import gzip
            import json
            import torch
            import numpy as np
            from transformers import AutoTokenizer, AutoModel
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            
            # Extract text content for indexing
            texts = [doc['content'] for doc in documents]
            
            # Use a very lightweight sentence transformer model
            model_name = "sentence-transformers/paraphrase-MiniLM-L3-v2"  # Smallest available model
            logger.info(f"Loading lightweight model: {model_name}")
            
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
            model.eval()  # Set to evaluation mode
            
            # Build semantic vector embeddings
            logger.info("Building semantic embeddings...")
            embeddings = []
            
            for text in texts:
                # Tokenize and encode
                inputs = tokenizer(text[:512], truncation=True, padding=True, 
                                 return_tensors="pt", max_length=512)
                
                with torch.no_grad():
                    outputs = model(**inputs)
                    # Mean pooling
                    embedding = outputs.last_hidden_state.mean(dim=1).squeeze().numpy()
                    embeddings.append(embedding)
            
            embeddings = np.array(embeddings)
            dimension = embeddings.shape[1]
            
            # Build BM25-style index using rank_bm25 approach with TF-IDF
            logger.info("Building BM25 index...")
            vectorizer = TfidfVectorizer(
                max_features=10000,
                stop_words='english',
                ngram_range=(1, 2),
                max_df=0.95,
                min_df=1,
                use_idf=True,
                smooth_idf=True,
                sublinear_tf=True
            )
            bm25_matrix = vectorizer.fit_transform(texts)
            
            # Define file paths (keeping same structure for compatibility)
            index_files = {
                'vector_index': os.path.join(self.temp_dir, 'vector_index.pkl'),
                'bm25_index': os.path.join(self.temp_dir, 'bm25_index.pkl'),
                'documents': os.path.join(self.temp_dir, 'documents.pkl.gz'),
                'manifest': os.path.join(self.temp_dir, 'manifest.json')
            }
            
            # Save semantic vector index (replaces FAISS with numpy/sklearn)
            vector_data = {
                'embeddings': embeddings,
                'model_name': model_name,
                'dimension': dimension,
                'index_type': 'semantic_cosine'
            }
            with open(index_files['vector_index'], 'wb') as f:
                pickle.dump(vector_data, f)
            
            # Save BM25 index
            bm25_data = {
                'vectorizer': vectorizer,
                'tfidf_matrix': bm25_matrix,
                'feature_names': vectorizer.get_feature_names_out(),
                'index_type': 'bm25_tfidf'
            }
            with open(index_files['bm25_index'], 'wb') as f:
                pickle.dump(bm25_data, f)
            
            # Save documents (compressed)
            with gzip.open(index_files['documents'], 'wb') as f:
                pickle.dump(documents, f)
            
            # Create manifest compatible with your existing system
            manifest = {
                'documents_count': len(documents),
                'embedding_dimension': dimension,
                'model_name': model_name,
                'created_at': time.time(),
                'index_files': list(index_files.keys()),
                'search_type': 'hybrid_bm25_semantic',
                'lambda_compatible': True
            }
            
            with open(index_files['manifest'], 'w') as f:
                json.dump(manifest, f, indent=2)
            
            logger.info(f"Successfully built hybrid indexes: {len(documents)} documents, {dimension}D semantic + BM25")
            return index_files
            
        except Exception as e:
            logger.error(f"Error building indexes: {str(e)}")
            raise

def create_manifest(config: IndexingConfig, result: IndexingResult) -> Dict[str, Any]:
    """Create manifest file for cache compatibility"""
    return {
        'version': '1.0',
        'created_at': datetime.utcnow().isoformat(),
        'documents_count': result.documents_processed,
        'total_size_mb': result.cache_size_mb,
        'processing_time_seconds': result.processing_time,
        'config': {
            'batch_size': config.batch_size,
            'max_memory_mb': config.max_memory_mb
        },
        'files': result.files_created or []
    }

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Main Lambda handler with comprehensive error handling"""
    
    start_time = time.time()
    logger.info(f"Starting RAG indexing job with event: {json.dumps(event)}")
    
    try:
        # Parse configuration
        config = IndexingConfig(
            s3_bucket=os.environ['S3_BUCKET'],
            s3_pdfs_prefix=os.environ.get('S3_PDFS_PREFIX', 'rag_pdfs/'),
            s3_cache_prefix=os.environ.get('S3_CACHE_PREFIX', 'cache/current/'),
            batch_size=int(os.environ.get('BATCH_SIZE', '3')),
            max_memory_mb=int(os.environ.get('MAX_MEMORY_MB', '2800'))
        )
        
        # Initialize services
        s3_manager = S3Manager(config.s3_bucket)
        
        # Use Lambda's /tmp directory
        with tempfile.TemporaryDirectory(dir='/tmp') as temp_dir:
            logger.info(f"Using temporary directory: {temp_dir}")
            
            # Initialize indexer
            indexer = RAGIndexer(temp_dir, config)
            
            # Get list of PDFs to process
            pdf_files = s3_manager.list_pdfs(config.s3_pdfs_prefix)
            
            if not pdf_files:
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': True,
                        'message': 'No PDFs found to process'
                    })
                }
            
            # Process PDFs in batches
            all_documents = []
            total_processed = 0
            
            for i in range(0, len(pdf_files), config.batch_size):
                batch = pdf_files[i:i + config.batch_size]
                logger.info(f"Processing batch {i//config.batch_size + 1}: {len(batch)} files")
                
                batch_result = indexer.process_batch(batch, s3_manager)
                all_documents.extend(batch_result['documents'])
                total_processed += batch_result['processed']
                
                if batch_result['failed']:
                    logger.warning(f"Batch had {len(batch_result['failed'])} failures")
            
            # Build indexes
            index_files = indexer.build_indexes(all_documents)
            
            # Upload indexes to S3
            uploaded_files = []
            for index_name, file_path in index_files.items():
                if os.path.exists(file_path):
                    s3_key = f"{config.s3_cache_prefix}{os.path.basename(file_path)}"
                    s3_manager.upload_file(file_path, s3_key)
                    uploaded_files.append(s3_key)
            
            # Create and upload manifest
            processing_time = time.time() - start_time
            cache_size_mb = sum(os.path.getsize(f) for f in index_files.values() if os.path.exists(f)) / 1024 / 1024
            
            result = IndexingResult(
                success=True,
                documents_processed=total_processed,
                total_documents=len(pdf_files),
                processing_time=processing_time,
                cache_size_mb=cache_size_mb,
                files_created=uploaded_files
            )
            
            manifest = create_manifest(config, result)
            s3_manager.upload_json(manifest, f"{config.s3_cache_prefix}manifest.json")
            
            logger.info(f"Indexing completed successfully: {total_processed}/{len(pdf_files)} files processed")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'documents_processed': total_processed,
                    'total_documents': len(pdf_files),
                    'processing_time': processing_time,
                    'cache_size_mb': cache_size_mb,
                    'files_uploaded': len(uploaded_files)
                })
            }
            
    except Exception as e:
        error_message = f"Indexing failed: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': error_message,
                'processing_time': time.time() - start_time
            })
        }