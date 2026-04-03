import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

from rag.indexer.page_index import PageIndexService
from rag.indexer.vrag import run_reasoning_rag
from scraper.scraper import scrape_all_platforms
from scraper.document_builder import build_per_platform_pdfs

app = FastAPI()

# ─────────────────────────────────────────────
# Initialize components
# ─────────────────────────────────────────────
print("Loading PageIndex service...")
try:
    page_index_service = PageIndexService(api_key=os.environ.get("PAGEINDEX_API_KEY"))
except ImportError as e:
    print(f"⚠️  PageIndex not available: {e}. Endpoints requiring PageIndex will return 503.")
    page_index_service = None

print("Loading LLM (Groq)...")
# Get free API key from https://console.groq.com/
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
GROQ_MODEL = "qwen/qwen3-32b"  # Free, fast, powerful
print("All components loaded!")


# ─────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    doc_id: Optional[str] = None
    top_n_for_llm: int = Field(default=3, ge=1, le=10)


class PlatformArtifactResponse(BaseModel):
    """Response for a single platform ingestion."""
    platform: str
    doc_id: Optional[str] = None
    filename: Optional[str] = None
    filepath: Optional[str] = None
    ready: bool = False
    scraped_count: int = 0
    failed_urls: List[Dict[str, str]] = []
    error: Optional[str] = None


class ScraperUploadResponse(BaseModel):
    """Response from scrape-and-upload endpoint."""
    status: str  # "completed", "partial", "failed"
    message: str
    platforms: Dict[str, PlatformArtifactResponse]


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@app.post("/upload/")
async def upload_document(
    file: UploadFile = File(...),
    parser_type: str = Form("pageindex")
):
    if parser_type.lower() != "pageindex":
        raise HTTPException(status_code=400, detail="Only parser_type='pageindex' is supported.")

    if not page_index_service:
        raise HTTPException(status_code=503, detail="PageIndex service is not configured.")

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        submit_result = page_index_service.submit_document(tmp_path, filename=file.filename)
        os.remove(tmp_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=400, detail=f"Indexing failed: {str(e)}")

    return {
        "status": "submitted",
        "doc_id": submit_result["doc_id"],
        "ready": submit_result.get("ready", False),
        "filename": file.filename,
    }


@app.post("/query/")
async def query_endpoint(request: QueryRequest):
    try:
        if not page_index_service:
            raise HTTPException(status_code=503, detail="PageIndex service is not configured.")

        doc_id = request.doc_id or page_index_service.get_latest_doc_id()
        if not doc_id:
            raise HTTPException(status_code=400, detail="No document found. Upload a document first.")

        tree = page_index_service.get_tree(doc_id, node_summary=True, wait_ready=True)
        rag_result = run_reasoning_rag(
            query=request.query,
            tree=tree,
            groq_client=groq_client,
            model=GROQ_MODEL,
            top_n=request.top_n_for_llm,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {str(e)}")

    return {
        "query": request.query,
        "doc_id": doc_id,
        "answer": rag_result["answer"],
        "sources": rag_result["sources"],
        "reasoning": rag_result["reasoning"],
    }


@app.post("/scrape-and-upload/")
async def scrape_and_upload():
    """
    Scrape all platforms from sources.json, build per-platform PDFs,
    and submit each to PageIndex. Returns per-platform doc_ids and metadata.
    """
    if not page_index_service:
        raise HTTPException(status_code=503, detail="PageIndex service is not configured.")

    try:
        print("📡 Starting scraper pipeline...")
        
        # Step 1: Scrape all platforms
        print("  Step 1: Scraping sources...")
        scraped_content = scrape_all_platforms()
        
        # Step 2: Build per-platform PDFs
        print("  Step 2: Building PDFs...")
        pdf_artifacts = build_per_platform_pdfs(scraped_content)
        
        # Step 3: Submit each PDF to PageIndex
        print("  Step 3: Submitting to PageIndex...")
        platforms_data = {}
        failed_platforms = []
        
        for platform, artifact in pdf_artifacts.items():
            if "error" in artifact:
                platforms_data[platform] = PlatformArtifactResponse(
                    platform=platform,
                    error=artifact["error"],
                )
                failed_platforms.append(platform)
                continue
            
            try:
                # Only submit if PDF was generated successfully
                if artifact.get("filepath") and os.path.exists(artifact["filepath"]):
                    submit_result = page_index_service.submit_and_track_scraper_artifact(
                        file_path=artifact["filepath"],
                        platform=platform,
                        artifact_metadata=artifact,
                    )
                    
                    platforms_data[platform] = PlatformArtifactResponse(
                        platform=platform,
                        doc_id=submit_result["doc_id"],
                        filename=artifact.get("filename"),
                        filepath=artifact.get("filepath"),
                        ready=submit_result.get("ready", False),
                        scraped_count=artifact.get("scraped_count", 0),
                        failed_urls=artifact.get("failed_urls", []),
                    )
                else:
                    platforms_data[platform] = PlatformArtifactResponse(
                        platform=platform,
                        error="PDF generation failed (file not found)",
                    )
                    failed_platforms.append(platform)
                    
            except Exception as e:
                platforms_data[platform] = PlatformArtifactResponse(
                    platform=platform,
                    error=f"PageIndex submission failed: {str(e)}",
                )
                failed_platforms.append(platform)
        
        # Determine overall status
        successful_platforms = [p for p in platforms_data if platforms_data[p].doc_id]
        
        if len(successful_platforms) == len(scraped_content):
            status = "completed"
            message = f"Successfully processed {len(successful_platforms)} platforms"
        elif len(successful_platforms) > 0:
            status = "partial"
            message = f"Processed {len(successful_platforms)} platforms; {len(failed_platforms)} failed"
        else:
            status = "failed"
            message = "All platforms failed to process"
        
        print(f"✅ Scraper pipeline complete: {status}")
        
        return ScraperUploadResponse(
            status=status,
            message=message,
            platforms=platforms_data,
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scraper pipeline failed: {str(e)}",
        )


@app.post("/hybrid_search/")
async def hybrid_search(
    query: str,
    top_k: int = 10,
    alpha: float = 0.5
):
    raise HTTPException(
        status_code=410,
        detail="/hybrid_search is deprecated. Use /query with PageIndex-backed retrieval.",
    )


@app.post("/search/")
async def search_vectors(
    query_vector: List[float],
    top_k: int = 10
):
    raise HTTPException(
        status_code=410,
        detail="/search is deprecated in vectorless mode.",
    )


@app.post("/embed/")
async def embed_texts(texts: List[str]):
    raise HTTPException(
        status_code=410,
        detail="/embed is deprecated in vectorless mode.",
    )


@app.post("/upsert/")
async def upsert_vectors(
    embeddings: List[List[float]],
    payloads: Optional[List[Dict[str, Any]]] = None
):
    raise HTTPException(
        status_code=410,
        detail="/upsert is deprecated in vectorless mode.",
    )