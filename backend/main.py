import os
import json
import tempfile
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

from rag.indexer.page_index import PageIndexService
from rag.indexer.vrag import run_reasoning_rag
from scraper.scraper import scrape_all_platforms
from scraper.document_builder import build_per_platform_pdfs
from media_jobs import (
    create_media_job,
    get_media_job,
    update_media_job,
    append_media_job_error,
    analyze_image_with_ollama,
    extract_video_sample_frames,
    extract_audio_wav,
    transcribe_audio_segments,
    synthesize_media_description,
    _parse_vision_analysis,
    frame_bytes_to_data_url,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your frontend's origin
    allow_credentials=True,
    allow_methods=["*"],  # Or specify specific methods like ["GET", "POST"]
    allow_headers=["*"],  # Or specify specific headers
)

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "data" / "violation_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# Initialize components
# ─────────────────────────────────────────────
print("Loading PageIndex service...")
try:
    page_index_service = PageIndexService(api_key=os.environ.get("PAGEINDEX_API_KEY"))
except ImportError as e:
    print(f"⚠️  PageIndex not available: {e}. Endpoints requiring PageIndex will return 503.")
    page_index_service = None

print("Loading LLM (Ollama Cloud)...")
# Uses OLLAMA_API_KEY and model name configured for Ollama Cloud.
groq_client = None  # Kept for backward compatibility with run_reasoning_rag signature
GROQ_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:397b-cloud")
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


class CountryDocResponse(BaseModel):
    filename: str
    doc_id: str
    ready: bool = False


class CountryIngestionResult(BaseModel):
    items: List[CountryDocResponse]
    errors: List[Dict[str, Any]]


class MediaPlatformIngestionResult(BaseModel):
    platform: str
    status: str
    filename: Optional[str] = None
    filepath: Optional[str] = None
    doc_id: Optional[str] = None
    ready: bool = False
    scraped_count: int = 0
    failed_urls: List[Dict[str, Any]] = []
    error: Optional[str] = None


class MediaIngestionResult(BaseModel):
    platforms: Dict[str, MediaPlatformIngestionResult]
    errors: List[Dict[str, Any]]


class CreateTreeResponse(BaseModel):
    status: str  # "completed", "partial", "failed"
    country: CountryIngestionResult
    media: MediaIngestionResult


class MediaDocResponse(BaseModel):
    platform: Optional[str]
    filename: str
    doc_id: str


class DocIdsResponse(BaseModel):
    country: List[CountryDocResponse]
    media: List[MediaDocResponse]


class ViolationDocDescriptor(BaseModel):
    doc_id: str
    label: Optional[str] = None


class ViolationDocResult(BaseModel):
    doc_id: str
    label: Optional[str] = None
    answer: str
    sources: List[Dict[str, Any]]
    reasoning: str
    violations: List[Dict[str, Any]] = Field(default_factory=list)


class ViolationQueryRequest(BaseModel):
    description: str
    docs: List[ViolationDocDescriptor]
    top_n_for_llm: int = Field(default=3, ge=1, le=10)


class ViolationQueryResponse(BaseModel):
    description: str
    results: List[ViolationDocResult]
    storage_path: Optional[str] = None


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _persist_violation_result(prefix: str, payload: Dict[str, Any]) -> str:
    filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    path = RESULTS_DIR / filename
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


class MediaJobCreateResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str


class MediaJobStatusResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str
    stage: str
    progress: int = Field(default=0, ge=0, le=100)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None


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
        "storage_path": rag_result.storage_path,
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


# ─────────────────────────────────────────────
# Helper functions for create_tree pipeline
# ─────────────────────────────────────────────

def _resolve_docs_by_selection(platforms: List[str], countries: List[str]) -> List[ViolationDocDescriptor]:
    """Resolve selected platforms/countries to violation doc descriptors."""
    docs: List[ViolationDocDescriptor] = []

    country_dir = BASE_DIR / "data" / "guidelines" / "country"
    media_dir = BASE_DIR / "data" / "guidelines" / "media"

    country_items: List[CountryDocResponse] = []
    media_items: List[MediaDocResponse] = []

    if country_dir.exists():
        for sidecar in sorted(country_dir.glob("*.doc_id.txt")):
            doc_id = sidecar.read_text(encoding="utf-8").strip()
            if not doc_id:
                continue
            base_name = sidecar.name[: -len(".doc_id.txt")]
            country_items.append(
                CountryDocResponse(filename=f"{base_name}.pdf", doc_id=doc_id, ready=False)
            )

    if media_dir.exists():
        for sidecar in sorted(media_dir.glob("*.doc_id.txt")):
            doc_id = sidecar.read_text(encoding="utf-8").strip()
            if not doc_id:
                continue
            base_name = sidecar.name[: -len(".doc_id.txt")]
            filename = f"{base_name}.pdf"
            platform = filename.split("_guidelines_", 1)[0] if "_guidelines_" in filename else None
            media_items.append(MediaDocResponse(platform=platform, filename=filename, doc_id=doc_id))

    media_by_platform: Dict[str, List[MediaDocResponse]] = {}
    for item in media_items:
        if not item.platform:
            continue
        key = item.platform.lower()
        media_by_platform.setdefault(key, []).append(item)

    for platform in platforms:
        items = media_by_platform.get(platform.lower(), [])
        if not items:
            continue
        chosen = items[0]
        if platform.lower() == "youtube":
            label = "YouTube Guidelines"
        elif platform.lower() == "instagram":
            label = "Instagram Guidelines"
        elif platform.lower() == "twitter":
            label = "Twitter / X Guidelines"
        else:
            label = f"{platform} Guidelines"
        docs.append(ViolationDocDescriptor(doc_id=chosen.doc_id, label=label))

    country_by_key: Dict[str, List[CountryDocResponse]] = {}
    for item in country_items:
        key = item.filename.replace(".pdf", "").strip().lower()
        country_by_key.setdefault(key, []).append(item)

    for country in countries:
        key = country.strip().lower().replace(" ", "_")
        items = country_by_key.get(key, [])
        if not items:
            continue
        chosen = items[0]
        docs.append(
            ViolationDocDescriptor(
                doc_id=chosen.doc_id,
                label=f"{country} Country Guidelines",
            )
        )

    return docs


def _run_violation_query(
    description: str,
    docs: List[ViolationDocDescriptor],
    top_n_for_llm: int,
) -> ViolationQueryResponse:
    if not page_index_service:
        raise HTTPException(status_code=503, detail="PageIndex service is not configured.")

    if not docs:
        raise HTTPException(status_code=400, detail="At least one document must be provided.")

    results: List[ViolationDocResult] = []

    for doc in docs:
        try:
            print(f"🔎 Running violation query for doc_id={doc.doc_id} label={doc.label!r}")

            tree = page_index_service.get_tree(
                doc.doc_id,
                node_summary=True,
                wait_ready=True,
            )

            violation_query = f""" You are a compliance and policy expert. You are given a single policy or guideline document and a description of a media item.

            Your task: determine whether this media content violates this specific document, and explain your reasoning in clear, plain language that a non-lawyer can understand.

            Media description:
            {description}

            Instructions:
            - Work ONLY with the provided document context; do not assume external rules.
            - Use simple, direct language. Avoid legal jargon and quote-heavy answers.
            - Identify all clearly relevant rules, sections, clauses, or articles in this document that the media may violate.
            - For each potential violation, list:
                - The exact reference, using the PageIndex tree node title, rule number, clause, or article if available.
                - A short, human-friendly explanation of how the media conflicts with that reference.
                - A concise action-oriented remediation such as trim, blur, crop, remove, or mute when appropriate.
            - If the document does not clearly cover this situation, say clearly that you cannot identify any specific violations in this document.

            Present your answer as a concise, numbered list of violations (or a clear statement that no violations can be determined).
            """

            rag_result = run_reasoning_rag(
                query=violation_query,
                tree=tree,
                groq_client=groq_client,
                model=GROQ_MODEL,
                top_n=top_n_for_llm,
                structured=True,
            )

            violations = rag_result.get("answer_structured", [])

            results.append(
                ViolationDocResult(
                    doc_id=doc.doc_id,
                    label=doc.label,
                    answer=rag_result["answer"],
                    sources=rag_result.get("sources", []),
                    reasoning=rag_result.get("reasoning", ""),
                    violations=violations,
                )
            )

        except Exception as e:
            error_msg = f"Error while querying doc_id {doc.doc_id}: {e}"
            print(f"  ❌ {error_msg}")
            results.append(
                ViolationDocResult(
                    doc_id=doc.doc_id,
                    label=doc.label,
                    answer=error_msg,
                    sources=[],
                    reasoning="",
                    violations=[],
                )
            )

    response = ViolationQueryResponse(description=description, results=results)
    storage_path = _persist_violation_result(
        "text",
        {
            "kind": "text",
            "created_at": _utc_now_iso(),
            "description": description,
            "docs": [doc.model_dump() for doc in docs],
            "top_n_for_llm": top_n_for_llm,
            "results": [result.model_dump() for result in results],
        },
    )
    response.storage_path = storage_path
    return response

def _save_doc_id_sidecar(pdf_path: Path, doc_id: str) -> None:
    """Save doc_id to a sidecar text file next to the PDF.

    Example: eur.pdf -> eur.doc_id.txt
    """
    sidecar_path = pdf_path.with_suffix("")
    sidecar_path = sidecar_path.with_suffix(".doc_id.txt")
    sidecar_path.write_text(doc_id, encoding="utf-8")


def _ingest_country_guidelines() -> CountryIngestionResult:
    country_dir = BASE_DIR / "data" / "guidelines" / "country"
    items: List[CountryDocResponse] = []
    errors: List[Dict[str, Any]] = []

    if not country_dir.exists():
        errors.append({"error": f"Country guidelines directory not found: {country_dir}"})
        return CountryIngestionResult(items=items, errors=errors)

    print(f"🌍 Ingesting country guidelines from {country_dir}...")

    for pdf_path in sorted(country_dir.glob("*.pdf")):
        try:
            print(f"  ➜ Submitting country PDF: {pdf_path.name}")
            submit_result = page_index_service.submit_document(str(pdf_path), filename=pdf_path.name)
            doc_id = submit_result["doc_id"]
            ready = bool(submit_result.get("ready", False))

            _save_doc_id_sidecar(pdf_path, doc_id)

            items.append(
                CountryDocResponse(
                    filename=pdf_path.name,
                    doc_id=doc_id,
                    ready=ready,
                )
            )
        except Exception as e:
            print(f"  ❌ Failed to ingest {pdf_path.name}: {e}")
            errors.append({"filename": pdf_path.name, "error": str(e)})

    return CountryIngestionResult(items=items, errors=errors)


def _ingest_media_guidelines() -> MediaIngestionResult:
    platforms_result: Dict[str, MediaPlatformIngestionResult] = {}
    errors: List[Dict[str, Any]] = []

    print("📡 Running scraper pipeline for media guidelines...")

    scraped_content = scrape_all_platforms()
    pdf_artifacts = build_per_platform_pdfs(scraped_content)

    for platform, artifact in pdf_artifacts.items():
        platform_status = MediaPlatformIngestionResult(
            platform=platform,
            status="pending",
        )

        # Handle PDF generation errors
        if "error" in artifact:
            msg = artifact.get("error", "Unknown PDF generation error")
            print(f"  ❌ PDF generation failed for {platform}: {msg}")
            platform_status.status = "pdf_error"
            platform_status.error = msg
            errors.append({"platform": platform, "error": msg})
            platforms_result[platform] = platform_status
            continue

        filepath = artifact.get("filepath")
        filename = artifact.get("filename")

        platform_status.filename = filename
        platform_status.filepath = filepath
        platform_status.scraped_count = artifact.get("scraped_count", 0)
        # failed_urls from scraper is List[Tuple[str,str]]; convert to list of dicts for response
        failed_urls_raw = artifact.get("failed_urls", [])
        platform_status.failed_urls = [
            {"url": url, "error": err} for url, err in failed_urls_raw
        ]

        if not filepath or not os.path.exists(filepath):
            msg = "PDF file not found after generation"
            print(f"  ❌ {msg} for {platform}: {filepath}")
            platform_status.status = "file_missing"
            platform_status.error = msg
            errors.append({"platform": platform, "error": msg})
            platforms_result[platform] = platform_status
            continue

        try:
            print(f"  ➜ Submitting media PDF for platform {platform}: {filename}")
            submit_result = page_index_service.submit_and_track_scraper_artifact(
                file_path=filepath,
                platform=platform,
                artifact_metadata=artifact,
            )
            doc_id = submit_result["doc_id"]
            ready = bool(submit_result.get("ready", False))

            _save_doc_id_sidecar(Path(filepath), doc_id)

            platform_status.status = "ok"
            platform_status.doc_id = doc_id
            platform_status.ready = ready
        except Exception as e:
            print(f"  ❌ Failed to submit media PDF for {platform}: {e}")
            platform_status.status = "submit_error"
            platform_status.error = str(e)
            errors.append({"platform": platform, "error": str(e)})

        platforms_result[platform] = platform_status

    return MediaIngestionResult(platforms=platforms_result, errors=errors)


@app.post("/create_tree/", response_model=CreateTreeResponse)
async def create_tree() -> CreateTreeResponse:
    """Ingest country PDFs and media PDFs into PageIndex.

    - Submits all PDFs in data/guidelines/country one by one.
    - Runs the scraper for links in scraper/sources.json, builds per-platform PDFs
      in data/guidelines/media, and submits them one by one.
    - For each PDF, saves a sidecar text file `<name>.doc_id.txt` containing
      the PageIndex doc_id.
    """
    if not page_index_service:
        raise HTTPException(status_code=503, detail="PageIndex service is not configured.")

    try:
        print("🚀 Starting create_tree pipeline...")
        country_result = _ingest_country_guidelines()
        media_result = _ingest_media_guidelines()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"create_tree pipeline failed: {e}")

    # Determine overall status
    any_country = bool(country_result.items)
    any_media_ok = any(
        p.status == "ok" for p in media_result.platforms.values()
    )
    any_success = any_country or any_media_ok
    any_errors = bool(country_result.errors or media_result.errors)

    if any_success and not any_errors:
        status = "completed"
    elif any_success:
        status = "partial"
    else:
        status = "failed"

    print(f"✅ create_tree pipeline complete with status: {status}")

    return CreateTreeResponse(status=status, country=country_result, media=media_result)


@app.get("/doc_ids/", response_model=DocIdsResponse)
async def list_doc_ids() -> DocIdsResponse:
    """List available PageIndex doc_ids for country and media guidelines.

    This reads sidecar files generated by the create_tree pipeline:
    - Country: data/guidelines/country/*.doc_id.txt
    - Media:   data/guidelines/media/*.doc_id.txt
    """
    country_dir = BASE_DIR / "data" / "guidelines" / "country"
    media_dir = BASE_DIR / "data" / "guidelines" / "media"

    country_items: List[CountryDocResponse] = []
    media_items: List[MediaDocResponse] = []

    # Country docs: read from .doc_id.txt sidecars so we don't depend
    # on PDFs being present on disk.
    if country_dir.exists():
        for sidecar in sorted(country_dir.glob("*.doc_id.txt")):
            doc_id = sidecar.read_text(encoding="utf-8").strip()
            if not doc_id:
                continue

            # Example: india.doc_id.txt -> india.pdf
            base_name = sidecar.name[: -len(".doc_id.txt")]
            filename = f"{base_name}.pdf"

            country_items.append(
                CountryDocResponse(filename=filename, doc_id=doc_id, ready=False)
            )

    # Media docs: likewise, infer from .doc_id.txt filenames such as
    # youtube_guidelines_*.doc_id.txt.
    if media_dir.exists():
        for sidecar in sorted(media_dir.glob("*.doc_id.txt")):
            doc_id = sidecar.read_text(encoding="utf-8").strip()
            if not doc_id:
                continue

            base_name = sidecar.name[: -len(".doc_id.txt")]
            filename = f"{base_name}.pdf"

            # Derive platform from filename if possible, e.g. youtube_guidelines_*.pdf
            name = filename
            platform: Optional[str]
            if "_guidelines_" in name:
                platform = name.split("_guidelines_", 1)[0]
            else:
                platform = None

            media_items.append(
                MediaDocResponse(platform=platform, filename=filename, doc_id=doc_id)
            )

    return DocIdsResponse(country=country_items, media=media_items)


@app.post("/violations/query", response_model=ViolationQueryResponse)
async def violations_query(request: ViolationQueryRequest) -> ViolationQueryResponse:
    """Run a violation-focused query against one or more documents.

    For each selected doc_id, we:
    - Fetch the PageIndex tree (with wait_ready=True)
    - Build a violation-specific query based on the media description
    - Run reasoning RAG independently
    - Return answers grouped per document
    """
    return _run_violation_query(
        description=request.description,
        docs=request.docs,
        top_n_for_llm=request.top_n_for_llm,
    )


def _process_media_job(
    job_id: str,
    media_path: str,
    media_type: str,
    user_description: str,
    docs: List[ViolationDocDescriptor],
    run_audio: bool,
    top_n_for_llm: int,
) -> None:
    update_media_job(job_id, status="processing", stage="media-analysis", progress=10)

    frame_analyses: List[Dict[str, Any]] = []
    transcript_segments: List[Dict[str, Any]] = []

    try:
        ollama_api_key = os.environ.get("OLLAMA_API_KEY", "")

        if media_type == "image":
            with open(media_path, "rb") as f:
                image_bytes = f.read()

            desc = analyze_image_with_ollama(
                image_bytes=image_bytes,
                model=GROQ_MODEL,
                api_key=ollama_api_key,
                prompt=(
                    "Analyze this image for policy and safety compliance violations.\n\n"
                    "Return ONLY valid JSON:\n"
                    "{\n"
                    '  "violations": [\n'
                    "    {\n"
                    '      "type": "violation category",\n'
                    '      "confidence": 0.95,\n'
                    '      "regions": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}]\n'
                    "    }\n"
                    "  ],\n"
                    '  "description": "summary"\n'
                    "}\n\n"
                    "Coordinates are normalized 0-1 (top-left=0,0, bottom-right=1,1).\n"
                    "Include regions for each violation found.\n"
                    "If no violations, return empty violations array."
                ),
            )
            analyzed = _parse_vision_analysis(desc)
            frame_analyses.append({"timestamp": 0.0, "violations": analyzed.get("violations", []), "description": analyzed.get("description", "")})
            update_media_job(job_id, progress=45, stage="image-analysis")
        else:
            frames = extract_video_sample_frames(media_path, max_frames=6)
            update_media_job(job_id, progress=25, stage="frame-extraction")

            for ts, frame_bytes in frames:
                desc = analyze_image_with_ollama(
                    image_bytes=frame_bytes,
                    model=GROQ_MODEL,
                    api_key=ollama_api_key,
                    prompt=(
                        "Analyze this video frame for policy and safety compliance violations.\n\n"
                        "Return ONLY valid JSON:\n"
                        "{\n"
                        '  "violations": [\n'
                        "    {\n"
                        '      "type": "violation category",\n'
                        '      "confidence": 0.95,\n'
                        '      "regions": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}]\n'
                        "    }\n"
                        "  ],\n"
                        '  "description": "summary"\n'
                        "}\n\n"
                        "Coordinates are normalized 0-1 (top-left=0,0, bottom-right=1,1).\n"
                        "Include regions for each violation found.\n"
                        "If no violations, return empty violations array."
                    ),
                )
                analyzed = _parse_vision_analysis(desc)
                frame_analyses.append({
                    "timestamp": round(ts, 2),
                    "frame_preview": frame_bytes_to_data_url(frame_bytes),
                    "violations": analyzed.get("violations", []),
                    "description": analyzed.get("description", ""),
                })

            update_media_job(job_id, progress=55, stage="frame-captioning")

            if run_audio:
                audio_path = None
                try:
                    audio_path = extract_audio_wav(media_path)
                    transcript_segments = transcribe_audio_segments(audio_path)
                    update_media_job(job_id, progress=70, stage="audio-transcription")
                except Exception as e:
                    append_media_job_error(
                        job_id,
                        stage="audio-transcription",
                        message=str(e),
                        recoverable=True,
                    )
                finally:
                    if audio_path and os.path.exists(audio_path):
                        os.remove(audio_path)

        synthesized_description = synthesize_media_description(
            media_type=media_type,
            user_description=user_description,
            frame_analyses=frame_analyses,
            transcript_segments=transcript_segments,
        )

        update_media_job(job_id, progress=82, stage="guideline-reasoning")

        violations = _run_violation_query(
            description=synthesized_description,
            docs=docs,
            top_n_for_llm=top_n_for_llm,
        )

        result_payload = {
            "kind": "media",
            "created_at": _utc_now_iso(),
            "media_type": media_type,
            "description": synthesized_description,
            "frame_analyses": frame_analyses,
            "audio_transcription": transcript_segments,
            "selected_docs": [doc.model_dump() for doc in docs],
            "results": [r.model_dump() for r in violations.results],
        }
        storage_path = _persist_violation_result("media", result_payload)
        result_payload["storage_path"] = storage_path

        update_media_job(
            job_id,
            status="completed",
            stage="completed",
            progress=100,
            result=result_payload,
        )

    except Exception as e:
        append_media_job_error(job_id, stage="fatal", message=str(e), recoverable=False)
        failure_payload = {
            "kind": "media",
            "created_at": _utc_now_iso(),
            "job_id": job_id,
            "media_type": media_type,
            "description": user_description,
            "selected_docs": [doc.model_dump() for doc in docs],
            "frame_analyses": frame_analyses,
            "audio_transcription": transcript_segments,
            "error": str(e),
        }
        failure_storage_path = _persist_violation_result("media_failed", failure_payload)
        failure_payload["storage_path"] = failure_storage_path
        update_media_job(job_id, status="failed", stage="failed", progress=100, result=failure_payload)
    finally:
        if os.path.exists(media_path):
            os.remove(media_path)


@app.post("/violations/media/jobs", response_model=MediaJobCreateResponse)
async def create_media_violation_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    media_type: str = Form(...),
    description: str = Form(""),
    platforms: str = Form("[]"),
    countries: str = Form("[]"),
    include_audio: bool = Form(True),
    top_n_for_llm: int = Form(3),
) -> MediaJobCreateResponse:
    if media_type not in {"image", "video"}:
        raise HTTPException(status_code=400, detail="media_type must be 'image' or 'video'.")

    try:
        parsed_platforms = json.loads(platforms) if platforms else []
        parsed_countries = json.loads(countries) if countries else []
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON for platforms/countries: {e}")

    if not isinstance(parsed_platforms, list) or not isinstance(parsed_countries, list):
        raise HTTPException(status_code=400, detail="platforms and countries must be JSON arrays.")

    docs = _resolve_docs_by_selection(parsed_platforms, parsed_countries)
    if not docs:
        raise HTTPException(
            status_code=400,
            detail="No matching guideline documents found for selected platforms/regions.",
        )

    suffix = os.path.splitext(file.filename or "upload.bin")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    job = create_media_job(
        {
            "media_type": media_type,
            "description": description,
            "platforms": parsed_platforms,
            "countries": parsed_countries,
            "include_audio": include_audio,
            "top_n_for_llm": top_n_for_llm,
            "filename": file.filename,
        }
    )

    background_tasks.add_task(
        _process_media_job,
        job["job_id"],
        tmp_path,
        media_type,
        description,
        docs,
        include_audio,
        top_n_for_llm,
    )

    return MediaJobCreateResponse(job_id=job["job_id"], status=job["status"])


@app.get("/violations/media/jobs/{job_id}", response_model=MediaJobStatusResponse)
async def get_media_violation_job(job_id: str) -> MediaJobStatusResponse:
    job = get_media_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return MediaJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        stage=job.get("stage", "unknown"),
        progress=job.get("progress", 0),
        errors=job.get("errors", []),
        result=job.get("result"),
    )