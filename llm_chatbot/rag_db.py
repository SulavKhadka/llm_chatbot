import json
from typing import List, Dict, Any, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers.quantization import quantize_embeddings
import psycopg2
from psycopg2.extras import execute_values, Json
import torch
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
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
                
                # Create table for storing embeddings and metadata
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id SERIAL PRIMARY KEY,
                        content TEXT,
                        embedding vector(%s),
                        metadata JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        content_tsv tsvector
                    );
                """, (self.dimensions,))
                
               
                # Create GIN index on content_tsv for efficient BM25 search
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_content_tsv_idx
                    ON {self.table_name} 
                    USING GIN (content_tsv);
                """)

                # Create an index for faster similarity search
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_idx 
                    ON {self.table_name} 
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
                """)
                
                conn.commit()

    def _encode_text(self, text: str, embed_type: str="document") -> np.ndarray:
        """Encode text using the embedding model with MRL and optional BQL."""

        # Add query prompt for retrieval tasks
        if embed_type == "query":
            text = f"Represent this sentence for searching relevant passages: {text}"
            embedding = self.model.encode(text, prompt_name="query", show_progress_bar=False)
        else:
            embedding = self.model.encode(text, show_progress_bar=False)
        
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
                query_sql = f"""
                    INSERT INTO {self.table_name} (content, embedding, metadata, content_tsv)
                    VALUES (%s, %s, %s, to_tsvector(%s))
                    RETURNING id;
                """
                cur.execute(query_sql, (content, embedding.tolist(), Json(metadata) if metadata else Json({}), content))
                
                record_id = cur.fetchone()[0]
                conn.commit()
                
        return record_id

    def query_bm25(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for documents using BM25 relevance scoring on full-text matches."""
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, content, metadata, ts_rank(content_tsv, plainto_tsquery(%s)) AS rank
                    FROM {self.table_name}
                    WHERE content_tsv @@ plainto_tsquery(%s)
                    ORDER BY rank DESC
                    LIMIT %s;
                """, (query_text, query_text, top_k))
                
                results = []
                for id_, content, metadata, rank in cur.fetchall():
                    results.append({
                        "id": id_,
                        "content": content,
                        "metadata": metadata,
                        "rank": float(rank)
                    })
                
        return results

    def query(self, query_text: str, top_k: int = 5, min_p: float = 0.4) -> List[Dict[str, Any]]:
        """Find the top_k most similar items to the query text.
        
        Args:
            query_text: The text to find similar items for
            top_k: Number of results to return
            
        Returns:
            List of dicts containing id, content, metadata, and similarity score
        """
        print(f"querying {self.table_name} for query: {query_text}")
        query_embedding = self._encode_text(query_text, embed_type="query")
        
        with psycopg2.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, content, embedding, metadata 
                    FROM {self.table_name};
                """)
                tool_rows = cur.fetchall()

                top_k_tools = torch.topk(torch.tensor([]), 0)
                if len(tool_rows) > 0:
                    query_to_tools_sim = torch.cosine_similarity(
                        torch.Tensor(query_embedding),
                        torch.Tensor([json.loads(i[2]) for i in tool_rows])
                    )
                    top_k_tools = query_to_tools_sim.topk(min(top_k, query_to_tools_sim.shape[0]))
                
                results = []
                for i in range(len(top_k_tools.indices)):
                    if float(top_k_tools.values[i]) > min_p:
                        tool_idx = top_k_tools.indices[i]
                        results.append({
                            "id": tool_rows[tool_idx][0],
                            "content": tool_rows[tool_idx][1],
                            "metadata": tool_rows[tool_idx][3],
                            "similarity": float(top_k_tools.values[i])
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
                data = [(content, embedding, Json(metadata) if metadata else Json({}), content) 
                       for (content, metadata), embedding 
                       in zip(items, embeddings)]
                
                query_sql = f"""
                    INSERT INTO {self.table_name} (content, embedding, metadata, content_tsv)
                    VALUES %s
                    RETURNING id;
                """
                # Perform bulk insert
                execute_values(
                    cur,
                    query_sql,
                    data,
                    template="(%s, %s, %s, to_tsvector(%s))"
                )
                
                ids = [row[0] for row in cur.fetchall()]
                conn.commit()
        return ids