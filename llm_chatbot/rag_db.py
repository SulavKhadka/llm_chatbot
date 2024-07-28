import sqlite3
import sqlite_vec
import struct
from typing import List, Dict, Any
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def serialize(vector: List[float]) -> bytes:
    """Serializes a list of floats into a compact "raw bytes" format"""
    return struct.pack("%sf" % len(vector), *vector)

def deserialize(raw_bytes: bytes) -> List[float]:
    """Deserializes raw bytes into a list of floats"""
    return list(struct.unpack("%sf" % (len(raw_bytes) // 4), raw_bytes))

def create_database(db_path: str):
    """Creates the database and necessary tables"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        cursor = conn.cursor()

        # Create TEXT_EMBED table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS TEXT_EMBED (
                CHUNK_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                DOC_ID TEXT NOT NULL,
                TEXT_CHUNK TEXT NOT NULL,
                METADATA TEXT
            )
        """)

        # Create virtual table for text embeddings
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS TEXT_EMBED_VEC USING vec0(
                CHUNK_ID INTEGER PRIMARY KEY,
                TEXT_EMBD FLOAT[1536]
            )
        """)

        # Create IMAGE_EMBED table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS IMAGE_EMBED (
                CHUNK_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                DOC_ID TEXT,
                IMAGE_BASE64 TEXT NOT NULL,
                METADATA TEXT
            )
        """)

        # Create virtual table for image embeddings
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS IMAGE_EMBED_VEC USING vec0(
                CHUNK_ID INTEGER PRIMARY KEY,
                IMG_EMBD FLOAT[1536]
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_text_doc_id ON TEXT_EMBED(DOC_ID)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_image_doc_id ON IMAGE_EMBED(DOC_ID)")

        conn.commit()
        logger.info("Database and tables created successfully")
    except sqlite3.Error as e:
        logger.error(f"Error creating database: {e}")
    finally:
        if conn:
            conn.close()

def insert_text_embed(db_path: str, doc_id: str, text_chunks: List[str], text_embds: List[List[float]], metadata: str = None):
    """Inserts a new text embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        for i, text_chunk in enumerate(text_chunks):
            cursor.execute("""
                INSERT INTO TEXT_EMBED (DOC_ID, TEXT_CHUNK, METADATA)
                VALUES (?, ?, ?)
            """, (doc_id, text_chunk, metadata))

            chunk_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO TEXT_EMBED_VEC (CHUNK_ID, TEXT_EMBD)
                VALUES (?, ?)
            """, (chunk_id, serialize(text_embds[i])))

        conn.commit()
        logger.info(f"Text embedding inserted successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error inserting text embedding: {e}")
    finally:
        if conn:
            conn.close()

def insert_image_embed(db_path: str, doc_id: str, images_base64: List[str], img_embds: List[List[float]], metadata: str = None):
    """Inserts a new image embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        for i, img in enumerate(images_base64):
            cursor.execute("""
                INSERT INTO IMAGE_EMBED (DOC_ID, IMAGE_BASE64, METADATA)
                VALUES (?, ?, ?)
            """, (doc_id, img, metadata))

            chunk_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO IMAGE_EMBED_VEC (CHUNK_ID, IMG_EMBD)
                VALUES (?, ?)
            """, (chunk_id, serialize(img_embds[i])))

        conn.commit()
        logger.info(f"Image embedding inserted successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error inserting image embedding: {e}")
    finally:
        if conn:
            conn.close()

def update_text_embed(db_path: str, chunk_id: int, text_chunk: str = None, text_embd: List[float] = None, metadata: str = None):
    """Updates an existing text embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        if text_chunk or metadata:
            update_fields = []
            update_values = []
            if text_chunk:
                update_fields.append("TEXT_CHUNK = ?")
                update_values.append(text_chunk)
            if metadata:
                update_fields.append("METADATA = ?")
                update_values.append(metadata)

            cursor.execute(f"""
                UPDATE TEXT_EMBED
                SET {', '.join(update_fields)}
                WHERE CHUNK_ID = ?
            """, update_values + [chunk_id])

        if text_embd:
            update_fields = []
            update_values = []
            if text_embd:
                update_fields.append("TEXT_EMBD = ?")
                update_values.append(serialize(text_embd))

            cursor.execute(f"""
                UPDATE TEXT_EMBED_VEC
                SET {', '.join(update_fields)}
                WHERE CHUNK_ID = ?
            """, update_values + [chunk_id])

        conn.commit()
        logger.info(f"Text embedding updated successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error updating text embedding: {e}")
    finally:
        if conn:
            conn.close()

def update_image_embed(db_path: str, chunk_id: int, image_base64: str = None, img_embd: List[float] = None, metadata: str = None):
    """Updates an existing image embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        if image_base64 or metadata:
            update_fields = []
            update_values = []
            if image_base64:
                update_fields.append("IMAGE_BASE64 = ?")
                update_values.append(image_base64)
            if metadata:
                update_fields.append("METADATA = ?")
                update_values.append(metadata)

            cursor.execute(f"""
                UPDATE IMAGE_EMBED
                SET {', '.join(update_fields)}
                WHERE CHUNK_ID = ?
            """, update_values + [chunk_id])

        if img_embd:
            update_fields = []
            update_values = []
            if img_embd:
                update_fields.append("IMG_EMBD = ?")
                update_values.append(serialize(img_embd))

            cursor.execute(f"""
                UPDATE IMAGE_EMBED_VEC
                SET {', '.join(update_fields)}
                WHERE CHUNK_ID = ?
            """, update_values + [chunk_id])

        conn.commit()
        logger.info(f"Image embedding updated successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error updating image embedding: {e}")
    finally:
        if conn:
            conn.close()

def delete_text_embed(db_path: str, chunk_id: int):
    """Deletes a text embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM TEXT_EMBED WHERE CHUNK_ID = ?", (chunk_id,))
        cursor.execute("DELETE FROM TEXT_EMBED_VEC WHERE CHUNK_ID = ?", (chunk_id,))

        conn.commit()
        logger.info(f"Text embedding deleted successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error deleting text embedding: {e}")
    finally:
        if conn:
            conn.close()

def delete_image_embed(db_path: str, chunk_id: int):
    """Deletes an image embedding record"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM IMAGE_EMBED WHERE CHUNK_ID = ?", (chunk_id,))
        cursor.execute("DELETE FROM IMAGE_EMBED_VEC WHERE CHUNK_ID = ?", (chunk_id,))

        conn.commit()
        logger.info(f"Image embedding deleted successfully for CHUNK_ID: {chunk_id}")
    except sqlite3.Error as e:
        logger.error(f"Error deleting image embedding: {e}")
    finally:
        if conn:
            conn.close()

def retrieve_text_embed(db_path: str, chunk_id: int) -> Dict[str, Any]:
    """Retrieves a text embedding record by CHUNK_ID"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT te.CHUNK_ID, te.DOC_ID, te.TEXT_CHUNK, te.METADATA, tev.TEXT_EMBD
            FROM TEXT_EMBED te
            JOIN TEXT_EMBED_VEC tev ON te.CHUNK_ID = tev.CHUNK_ID
            WHERE te.CHUNK_ID = ?
        """, (chunk_id,))

        result = cursor.fetchone()
        if result:
            return {
                "CHUNK_ID": result[0],
                "DOC_ID": result[1],
                "TEXT_CHUNK": result[2],
                "METADATA": result[3],
                "TEXT_EMBD": deserialize(result[4])
            }
        else:
            logger.warning(f"No text embedding found for CHUNK_ID: {chunk_id}")
            return None
    except sqlite3.Error as e:
        logger.error(f"Error retrieving text embedding: {e}")
    finally:
        if conn:
            conn.close()

def retrieve_image_embed(db_path: str, chunk_id: int) -> Dict[str, Any]:
    """Retrieves an image embedding record by CHUNK_ID"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ie.CHUNK_ID, ie.DOC_ID, ie.IMAGE_BASE64, ie.METADATA, iev.IMG_EMBD
            FROM IMAGE_EMBED ie
            JOIN IMAGE_EMBED_VEC iev ON ie.CHUNK_ID = iev.CHUNK_ID
            WHERE ie.CHUNK_ID = ?
        """, (chunk_id,))

        result = cursor.fetchone()
        if result:
            return {
                "CHUNK_ID": result[0],
                "DOC_ID": result[1],
                "IMAGE_BASE64": result[2],
                "METADATA": result[3],
                "IMG_EMBD": deserialize(result[4])
            }
        else:
            logger.warning(f"No image embedding found for CHUNK_ID: {chunk_id}")
            return None
    except sqlite3.Error as e:
        logger.error(f"Error retrieving image embedding: {e}")
    finally:
        if conn:
            conn.close()

def search_text_embeds(db_path: str, query_embedding: List[float], k: int = 5) -> List[Dict[str, Any]]:
    """Performs a vector similarity search on text embeddings"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT te.CHUNK_ID, te.DOC_ID, te.TEXT_CHUNK, te.METADATA, distance
            FROM TEXT_EMBED_VEC tev
            JOIN TEXT_EMBED te ON tev.CHUNK_ID = te.CHUNK_ID
            WHERE TEXT_EMBD MATCH ?
                AND k = ?
            ORDER BY distance
        """, (serialize(query_embedding), k))

        results = cursor.fetchall()
        return [
            {
                "CHUNK_ID": r[0],
                "DOC_ID": r[1],
                "TEXT_CHUNK": r[2],
                "METADATA": r[3],
                "DISTANCE": r[4]
            }
            for r in results
        ]
    except sqlite3.Error as e:
        logger.error(f"Error searching text embeddings: {e}")
    finally:
        if conn:
            conn.close()

def search_image_embeds(db_path: str, query_embedding: List[float], k: int = 5) -> List[Dict[str, Any]]:
    """Performs a vector similarity search on image embeddings"""
    try:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ie.CHUNK_ID, ie.DOC_ID, ie.METADATA, distance
            FROM IMAGE_EMBED_VEC iev
            JOIN IMAGE_EMBED ie ON iev.CHUNK_ID = ie.CHUNK_ID
            WHERE IMG_EMBD MATCH ?
                AND k = ?
            ORDER BY distance
        """, (serialize(query_embedding), k))

        results = cursor.fetchall()
        return [
            {
                "CHUNK_ID": r[0],
                "DOC_ID": r[1],
                "METADATA": r[2],
                "DISTANCE": r[3]
            }
            for r in results
        ]
    except sqlite3.Error as e:
        logger.error(f"Error searching image embeddings: {e}")
    finally:
        if conn:
            conn.close()

def main():
    db_path = "test_embeddings.db"
    create_database(db_path)

    # Example usage
    text_embd = [0.1] * 1536  # Replace with actual embedding
    insert_text_embed(db_path, "doc1", "Sample text chunk", text_embd,'{"key": "value"}')

    img_embd = [0.3] * 1536  # Replace with actual embedding
    insert_image_embed(db_path, "doc2", "base64_encoded_image", img_embd, '{"key": "value"}')

    # Retrieve and print results
    text_result = retrieve_text_embed(db_path, 1)
    print("Text Embedding:", text_result)

    image_result = retrieve_image_embed(db_path, 1)
    print("Image Embedding:", image_result)

    # Perform similarity search
    query_embd = [0.5] * 1536  # Replace with actual query embedding
    text_search_results = search_text_embeds(db_path, query_embd, k=3)
    print("Text Search Results:", text_search_results)

    image_search_results = search_image_embeds(db_path, query_embd, k=3)
    print("Image Search Results:", image_search_results)

if __name__ == "__main__":
    main()