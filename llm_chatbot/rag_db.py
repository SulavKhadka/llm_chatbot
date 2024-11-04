from typing import List, Dict, Any, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers.quantization import quantize_embeddings
import psycopg2
from psycopg2.extras import execute_values, Json
import json
import os

class VectorSearch:
    def __init__(
        self,
        db_config: dict[str, str],
        dimensions: int = 512,
        model_name: str = "mixedbread-ai/mxbai-embed-large-v1",
        use_binary: bool = True,
        table_name: str = "embeddings" 
    ):
        """Initialize the vector search system.
        
        Args:
            dimensions: Number of dimensions to use (MRL)
            model_name: Name of the embedding model to use
            connection_string: PostgreSQL connection string
            use_binary: Whether to use binary quantization
        """
        # Initialize the embedding model with MRL
        self.model = SentenceTransformer(model_name, truncate_dim=dimensions)
        self.use_binary = use_binary
        self.dimensions = dimensions

        # Setup database connection
        self.table_name = table_name
        self.conn_string = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['dbname']}"
        
        # Initialize database
        self._init_db()

    def _init_db(self):
        """Initialize the database schema with pgvector extension."""
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                # Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                
                # Create table for storing embeddings and metadata
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id SERIAL PRIMARY KEY,
                        content TEXT,
                        embedding vector(%s),
                        metadata JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """, (self.dimensions,))
                
                # Create an index for faster similarity search
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_idx 
                    ON {self.table_name} 
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
                """)
                
                conn.commit()

    def _encode_text(self, text: str) -> np.ndarray:
        """Encode text using the embedding model with MRL and optional BQL."""
        # Add query prompt for retrieval tasks
        query_text = f"Represent this sentence for searching relevant passages: {text}"
        
        # Generate embedding
        embedding = self.model.encode(query_text, prompt_name="query")
        
        # Apply binary quantization if enabled
        if self.use_binary:
            embedding = quantize_embeddings([embedding], precision="ubinary")[0]
            
        return embedding

    def insert(self, content: str, metadata: Dict[str, Any] = None) -> int:
        """Insert content and its embedding into the database.
        
        Args:
            content: The text content to embed
            metadata: Optional metadata to store with the embedding
            
        Returns:
            id: The ID of the inserted record
        """
        embedding = self._encode_text(content)
        
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO embeddings (content, embedding, metadata)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                """, (content, embedding.tolist(), Json(metadata) if metadata else Json({})))
                
                record_id = cur.fetchone()[0]
                conn.commit()
                
        return record_id

    def query(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find the top_k most similar items to the query text.
        
        Args:
            query_text: The text to find similar items for
            top_k: Number of results to return
            
        Returns:
            List of dicts containing id, content, metadata, and similarity score
        """
        query_embedding = self._encode_text(query_text)
        
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, content, metadata, 
                           1 - (embedding <=> %s::vector) as similarity
                    FROM embeddings
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                """, (query_embedding.tolist(), query_embedding.tolist(), top_k))
                
                results = []
                for id_, content, metadata, similarity in cur.fetchall():
                    results.append({
                        "id": id_,
                        "content": content,
                        "metadata": metadata,
                        "similarity": float(similarity)
                    })
                
        return results

    def bulk_insert(self, items: List[Tuple[str, Dict[str, Any]]]) -> List[int]:
        """Insert multiple items efficiently.
        
        Args:
            items: List of (content, metadata) tuples
            
        Returns:
            List of inserted record IDs
        """
        # Generate all embeddings in parallel
        contents = [item[0] for item in items]
        embeddings = [self._encode_text(content).tolist() for content in contents]
        
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                # Prepare data for bulk insert
                data = [(content, embedding, Json(metadata) if metadata else Json({})) 
                       for (content, metadata), embedding 
                       in zip(items, embeddings)]
                
                # Perform bulk insert
                execute_values(
                    cur,
                    """
                    INSERT INTO embeddings (content, embedding, metadata)
                    VALUES %s
                    RETURNING id;
                    """,
                    data,
                    template="(%s, %s, %s)"
                )
                
                ids = [row[0] for row in cur.fetchall()]
                conn.commit()
                
        return ids