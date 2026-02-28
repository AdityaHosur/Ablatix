import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

from indexer.parser import DocumentParser
from indexer.embedder import Embedder, Reranker
from indexer.vector_store import VectorStore

app = FastAPI()

# ─────────────────────────────────────────────
# Initialize components
# ─────────────────────────────────────────────
print("Loading parser...")
parser = DocumentParser(parser_type="llama", chunk_size=500, chunk_overlap=100)

print("Loading embedder...")
embedder = Embedder(model_name="BAAI/bge-m3")

print("Loading vector store...")
vector_store = VectorStore(collection_name="ablatix_index", vector_size=1024)

print("Loading reranker...")
reranker = Reranker()

print("Loading LLM (Groq)...")
# Get free API key from https://console.groq.com/
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
GROQ_MODEL = "qwen/qwen3-32b"  # Free, fast, powerful
print("All components loaded!")


# ─────────────────────────────────────────────
# Helper: Build prompt from query + chunks
# ─────────────────────────────────────────────
def build_prompt(query: str, chunks: List[str]) -> str:
    context = "\n\n".join([f"[Chunk {i+1}]:\n{chunk}" for i, chunk in enumerate(chunks)])
    return f"""You are a helpful AI assistant. Use the context below to answer the question.
If the answer is not in the context, say "I don't have enough information to answer this question."

Context:
{context}

Question: {query}
Answer:"""


# ─────────────────────────────────────────────
# Helper: Generate answer from Groq LLM
# ─────────────────────────────────────────────
def generate_answer(query: str, chunks: List[str]) -> str:
    prompt = build_prompt(query, chunks)
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant that answers questions based on provided context."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        max_tokens=512,
        temperature=0.1
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    alpha: float = 0.5
    top_n_for_llm: int = 3


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@app.post("/upload/")
async def upload_document(
    file: UploadFile = File(...),
    parser_type: str = Form("llama")
):
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        doc_parser = DocumentParser(
            parser_type=parser_type,
            chunk_size=500,
            chunk_overlap=100
        )
        parsed_chunks = doc_parser.parse(tmp_path)
        os.remove(tmp_path)

        texts = [chunk["text"] for chunk in parsed_chunks if chunk.get("text")]
        embeddings = embedder.embed_text(texts)
        payloads = [
            {
                "text": chunk["text"],
                "metadata": chunk.get("metadata", {}),
                "type": chunk.get("type", "paragraph")
            }
            for chunk in parsed_chunks if chunk.get("text")
        ]
        vector_store.upsert(embeddings, payloads)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=400, detail=f"Indexing failed: {str(e)}")

    return {"status": "indexed", "chunks_indexed": len(texts)}


@app.post("/query/")
async def query_endpoint(
    query: str,
    top_k: int = 10,
    alpha: float = 0.5,
    top_n_for_llm: int = 3
):
    try:
        # Step 1: Embed query
        query_vector = embedder.embed_text(query)[0]

        # Step 2: Hybrid search
        results = vector_store.hybrid_search(
            query_vector,
            query,
            top_k=top_k,
            alpha=alpha
        )

        # Step 3: Rerank
        docs = [r["payload"].get("text", "") for r in results]
        scores = reranker.rerank(query, docs)

        # Step 4: Sort by rerank score
        for r, s in zip(results, scores):
            r["rerank_score"] = float(s)
        results = sorted(results, key=lambda x: x["rerank_score"], reverse=True)

        # Step 5: Select top N chunks for LLM
        top_chunks = [
            r["payload"].get("text", "")
            for r in results[:top_n_for_llm]
        ]

        # Step 6: Generate answer using Groq LLM
        answer = generate_answer(query, top_chunks)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {str(e)}")

    return {
        "query": query,
        "answer": answer,
        "sources": results[:top_n_for_llm],
        "all_results": results
    }


@app.post("/hybrid_search/")
async def hybrid_search(
    query: str,
    top_k: int = 10,
    alpha: float = 0.5
):
    try:
        query_vector = embedder.embed_text(query)[0]
        results = vector_store.hybrid_search(
            query_vector,
            query,
            top_k=top_k,
            alpha=alpha
        )
        docs = [r["payload"].get("text", "") for r in results]
        scores = reranker.rerank(query, docs)
        for r, s in zip(results, scores):
            r["rerank_score"] = float(s)
        results = sorted(results, key=lambda x: x["rerank_score"], reverse=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Hybrid search failed: {str(e)}")
    return {"results": results}


@app.post("/search/")
async def search_vectors(
    query_vector: List[float],
    top_k: int = 10
):
    try:
        results = vector_store.search(query_vector, top_k=top_k)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search failed: {str(e)}")
    return {"results": results}


@app.post("/embed/")
async def embed_texts(texts: List[str]):
    try:
        embeddings = embedder.embed_text(texts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Embedding failed: {str(e)}")
    return {"embeddings": embeddings}


@app.post("/upsert/")
async def upsert_vectors(
    embeddings: List[List[float]],
    payloads: Optional[List[Dict[str, Any]]] = None
):
    try:
        vector_store.upsert(embeddings, payloads)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upsert failed: {str(e)}")
    return {"status": "upserted", "count": len(embeddings)}