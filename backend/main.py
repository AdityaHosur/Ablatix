import os
import json
import tempfile
import uuid
import re
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
from remediation import (
    remediate_media,
    process_text,
    remediate_image_file,
    remediate_video,
    remediate_audio_wav,
    detect_text,
    mask_text,
)
import shutil

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
# Check ffmpeg availability
from media_jobs import FFMPEG_EXE
if FFMPEG_EXE:
    print(f"✓ ffmpeg found at: {FFMPEG_EXE}")
    # Add ffmpeg binary directory to PATH so that Whisper and other tools can find it by name
    ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        print(f"✓ Added ffmpeg directory to PATH: {ffmpeg_dir}")

    # Ensure a plain 'ffmpeg' executable is discoverable by subprocess calls that use the bare name.
    # Some libraries (whisper) call 'ffmpeg' directly and may not respect the imageio-ffmpeg full path.
    try:
        import sys
        venv_scripts = os.path.join(os.path.dirname(sys.executable), "Scripts")
        target_ffmpeg = os.path.join(venv_scripts, "ffmpeg.exe")
        if not shutil.which("ffmpeg") and not os.path.exists(target_ffmpeg):
            try:
                # Ensure Scripts directory exists
                os.makedirs(venv_scripts, exist_ok=True)
                # If we can't copy the binary, write a small wrapper batch file that calls the imageio-ffmpeg binary.
                if os.path.exists(FFMPEG_EXE):
                    try:
                        shutil.copy2(FFMPEG_EXE, target_ffmpeg)
                        print(f"✓ Copied ffmpeg binary to venv Scripts: {target_ffmpeg}")
                    except Exception as copy_err:
                        try:
                            # Fallback: create ffmpeg.bat wrapper
                            wrapper_path = os.path.join(venv_scripts, "ffmpeg.bat")
                            with open(wrapper_path, "w", encoding="utf-8") as f:
                                f.write(f'@echo off\n"{FFMPEG_EXE}" %*\n')
                            print(f"✓ Wrote ffmpeg wrapper to venv Scripts: {wrapper_path}")
                        except Exception as wrap_err:
                            print(f"⚠️  Could not create ffmpeg wrapper: {wrap_err}")
                else:
                    print(f"⚠️  Expected ffmpeg binary not found at: {FFMPEG_EXE}")
            except Exception as e:
                print(f"⚠️  Could not ensure venv Scripts or install ffmpeg: {e}")
    except Exception:
        pass
else:
    print("⚠️  ffmpeg not found. Audio (.mp3, .m4a, etc.) processing will fail. Install ffmpeg or imageio-ffmpeg.")

print("Loading PageIndex service...")
try:
    page_index_service = PageIndexService(api_key=os.environ.get("PAGEINDEX_API_KEY"))
except ImportError as e:
    print(f"⚠️  PageIndex not available: {e}. Endpoints requiring PageIndex will return 503.")
    page_index_service = None

print("Loading LLM (Ollama Cloud)...")
# Uses OLLAMA_API_KEY and model name configured for Ollama Cloud.
groq_client = None  # Kept for backward compatibility with run_reasoning_rag signature
GROQ_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:31b-cloud")

# ─────────────────────────────────────────────
# Remediation configuration
# ─────────────────────────────────────────────
ENABLE_REMEDIATION = os.environ.get("ENABLE_REMEDIATION", "true").lower() == "true"
BLUR_STRENGTH = int(os.environ.get("BLUR_STRENGTH", "51"))
USE_BEEP_FOR_AUDIO = os.environ.get("USE_BEEP_FOR_AUDIO", "true").lower() == "true"

print(f"Remediation settings: ENABLED={ENABLE_REMEDIATION}, BLUR_STRENGTH={BLUR_STRENGTH}, USE_BEEP={USE_BEEP_FOR_AUDIO}")
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


def _extract_bboxes_from_violations(violations: List[Dict], frame_width: int, frame_height: int) -> List[Dict]:
    """
    Convert normalized violation coordinates (0-1) to pixel coordinates.
    
    Args:
        violations: List of violation dicts with 'regions' (normalized coords)
        frame_width: Frame width in pixels
        frame_height: Frame height in pixels
    
    Returns:
        List of bbox dicts with pixel coordinates [x1, y1, x2, y2]
    """
    bboxes = []
    for violation in violations:
        regions = violation.get("regions", [])
        for region in regions:
            try:
                # Normalized coordinates: x, y, width, height (all 0-1)
                norm_x = float(region.get("x", 0))
                norm_y = float(region.get("y", 0))
                norm_width = float(region.get("width", 0.1))
                norm_height = float(region.get("height", 0.1))
                
                # Convert to pixel coordinates
                x1 = int(norm_x * frame_width)
                y1 = int(norm_y * frame_height)
                x2 = int((norm_x + norm_width) * frame_width)
                y2 = int((norm_y + norm_height) * frame_height)
                
                bboxes.append({"bbox": [x1, y1, x2, y2]})
            except (ValueError, TypeError) as e:
                print(f"⚠️  Error parsing region {region}: {e}")
                continue
    
    return bboxes


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
    remediated_image_path: Optional[str] = None
    remediated_video_path: Optional[str] = None
    remediation_stats: Dict[str, Any] = {}

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
                    "Explicitly detect and flag visual violations such as violence, nudity, weapons, cigarette smoking, tobacco products, alcohol bottles/cans, and people drinking alcohol.\n\n"
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
            
            # Do NOT perform automatic remediation here. Persist original media so remediation
            # can be triggered later via the on-demand endpoint.
            remediated_image_path = None
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
                        "Explicitly detect and flag visual violations such as violence, nudity, weapons, cigarette smoking, tobacco products, alcohol bottles/cans, and people drinking alcohol.\n\n"
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

            # Do NOT perform automatic remediation here. Persist original media so remediation
            # can be triggered later via the on-demand endpoint.
            remediated_video_path = None

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

        # Persist original uploaded media for on-demand remediation
        try:
            originals_dir = RESULTS_DIR / "originals"
            originals_dir.mkdir(parents=True, exist_ok=True)
            orig_basename = f"{job_id}_{os.path.basename(media_path)}"
            orig_dest = originals_dir / orig_basename
            shutil.copy(media_path, orig_dest)
            original_rel = str((Path("data") / "violation_results" / "originals" / orig_basename).as_posix())
        except Exception as e:
            print(f"⚠️  Failed to persist original media: {e}")
            original_rel = None

        result_payload = {
            "kind": "media",
            "created_at": _utc_now_iso(),
            "media_type": media_type,
            "description": synthesized_description,
            "frame_analyses": frame_analyses,
            "audio_transcription": transcript_segments,
            "selected_docs": [doc.model_dump() for doc in docs],
            "results": [r.model_dump() for r in violations.results],
            "remediation": {
                # Only mark remediation enabled if we actually have a remediated file
                "enabled": bool(remediated_image_path or remediated_video_path),
                "original_path": original_rel,
                "image_path": remediated_image_path,
                "video_path": remediated_video_path,
                "stats": remediation_stats or {},
            }
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
        result_payload = {
            "kind": "media",
            "created_at": _utc_now_iso(),
            "media_type": media_type,
            "description": synthesized_description,
            "frame_analyses": frame_analyses,
            "audio_transcription": transcript_segments,
            "selected_docs": [doc.model_dump() for doc in docs],
            "results": [r.model_dump() for r in violations.results],
            "remediation": {
                # Remediation will be performed on-demand by user action
                "enabled": False,
                "original_path": original_rel,
                "image_path": None,
                "video_path": None,
                "stats": {},
            }
        }

@app.get("/violations/media/remediated/{filename}")
async def get_remediated_media(filename: str):
    """
    Serve remediated media files (images, videos) from violation results.
    
    Args:
        filename: The remediated file name (e.g., 'media_20260504T083640_d996520e_remediated.mp4')
    
    Returns:
        The remediated media file with appropriate content-type header.
    """
    try:
        # Validate filename to prevent directory traversal
        if ".." in filename or filename.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        file_path = RESULTS_DIR / filename
        
        # Verify file exists and is within RESULTS_DIR
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"Remediated media not found: {filename}")
        
        if not str(file_path.resolve()).startswith(str(RESULTS_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Invalid file path")
        
        # Determine media type from extension
        suffix = file_path.suffix.lower()
        if suffix in [".mp4", ".avi", ".mov", ".webm"]:
            media_type = "video/mp4" if suffix == ".mp4" else f"video/{suffix[1:]}"
        elif suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            media_type = f"image/{suffix[1:]}" if suffix != ".jpg" else "image/jpeg"
        else:
            media_type = "application/octet-stream"
        
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"⚠️  Error serving remediated media: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving remediated media: {str(e)}")


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


@app.post("/violations/media/remediate")
async def remediate_media_endpoint(payload: Dict[str, Any]):
    """
    Trigger on-demand remediation for a previously-analyzed media job.
    Expects JSON: { "job_id": "...", "blur_strength": 51 }
    """
    job_id = payload.get("job_id")
    blur_strength = int(payload.get("blur_strength", BLUR_STRENGTH))

    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")

    job = None
    result = None
    if job_id:
        job = get_media_job(job_id)
        if not job:
            job = None
        else:
            result = job.get("result")

    # If no in-memory job/result, allow remediation via persisted storage_path
    if not result:
        storage_path = payload.get("storage_path") or payload.get("result_storage_path")
        if storage_path:
            try:
                storage_file = Path(storage_path)
                if not storage_file.exists():
                    storage_file = (BASE_DIR / storage_path).resolve()

                if not storage_file.exists():
                    raise HTTPException(status_code=404, detail="Persisted analysis result not found")

                raw = json.loads(storage_file.read_text(encoding="utf-8"))
                result = raw
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to load persisted result: {e}")

    if not result:
        raise HTTPException(status_code=404, detail="Media job not found")

    remediation = result.get("remediation") or {}
    original_rel = remediation.get("original_path")
    if not original_rel:
        raise HTTPException(status_code=400, detail="Original media not available for remediation")

    # Resolve original file path
    orig_path = (BASE_DIR / Path(original_rel)).resolve()
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="Original media file not found on server")

    media_type = result.get("media_type")
    frame_analyses = result.get("frame_analyses", [])

    # Prepare remediated output path
    try:
        rem_dir = RESULTS_DIR
        rem_dir.mkdir(parents=True, exist_ok=True)
        rem_basename = orig_path.stem + "_remediated" + orig_path.suffix
        rem_path = rem_dir / rem_basename

        update_media_job(job_id, progress=85, stage="remediation-started")

        if media_type == "image":
            # Compute bboxes from first frame analysis
            violations = frame_analyses[0].get("violations", []) if frame_analyses else []
            import cv2
            img = cv2.imread(str(orig_path))
            if img is None:
                raise HTTPException(status_code=500, detail="Failed to read original image for remediation")
            h, w = img.shape[:2]
            bboxes = _extract_bboxes_from_violations(violations, w, h)
            if not bboxes:
                raise HTTPException(status_code=400, detail="No violation regions to remediate")

            success = remediate_image_file(str(orig_path), str(rem_path), bboxes, blur_strength)
            if not success:
                raise HTTPException(status_code=500, detail="Image remediation failed")

            # Update job result
            result["remediation"]["image_path"] = str((Path("data") / "violation_results" / rem_basename).as_posix())
            result["remediation"]["enabled"] = True
            result["remediation"]["stats"] = {"regions_blurred": len(bboxes)}

        else:
            # Video remediation
            audio_segments = []
            remediation_result = remediate_video(
                input_video_path=str(orig_path),
                output_video_path=str(rem_path),
                frame_analyses=frame_analyses,
                audio_segments=audio_segments,
                blur_strength=blur_strength,
                use_beep=USE_BEEP_FOR_AUDIO,
            )

            if not remediation_result.get("success"):
                raise HTTPException(status_code=500, detail="Video remediation failed")

            result["remediation"]["video_path"] = str((Path("data") / "violation_results" / rem_basename).as_posix())
            result["remediation"]["enabled"] = True
            result["remediation"]["stats"] = remediation_result

        # Persist updated result in memory and update job
        # Persist updated result back to in-memory job if available
        if job:
            update_media_job(job_id, result=result, progress=100, stage="remediation-completed", status="completed")

        return {"success": True, "remediation": result.get("remediation")}

    except HTTPException:
        raise
    except Exception as e:
        append_media_job_error(job_id, stage="remediation", message=str(e), recoverable=False)
        raise HTTPException(status_code=500, detail=f"Remediation failed: {e}")


# ─────────────────────────────────────────────
# AUDIO REMEDIATION ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/violations/audio/jobs", response_model=MediaJobCreateResponse)
async def create_audio_violation_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    description: str = Form(""),
    platforms: str = Form("[]"),
    countries: str = Form("[]"),
    top_n_for_llm: int = Form(3),
) -> MediaJobCreateResponse:
    """Create an audio analysis job for violation detection."""
    # Validate audio format
    valid_audio_formats = {".wav", ".mp3", ".m4a", ".ogg", ".aac", ".flac"}
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in valid_audio_formats:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported audio format. Supported: {', '.join(valid_audio_formats)}"
        )

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

    suffix = os.path.splitext(file.filename or "upload.wav")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    job = create_media_job(
        {
            "media_type": "audio",
            "description": description,
            "platforms": parsed_platforms,
            "countries": parsed_countries,
            "top_n_for_llm": top_n_for_llm,
            "filename": file.filename,
        }
    )

    background_tasks.add_task(
        _process_audio_job,
        job["job_id"],
        tmp_path,
        description,
        docs,
        top_n_for_llm,
    )

    return MediaJobCreateResponse(job_id=job["job_id"], status=job["status"])


def _process_audio_job(
    job_id: str,
    audio_path: str,
    user_description: str,
    docs: List[ViolationDocDescriptor],
    top_n_for_llm: int,
) -> None:
    """Process audio file for violation detection."""
    print(f"\n[_process_audio_job] Starting job {job_id}")
    print(f"[_process_audio_job] Audio path: {audio_path}")
    print(f"[_process_audio_job] File exists: {os.path.exists(audio_path)}")
    if os.path.exists(audio_path):
        print(f"[_process_audio_job] File size: {os.path.getsize(audio_path)} bytes")
    
    update_media_job(job_id, status="processing", stage="audio-analysis", progress=10)
    
    transcript_segments: List[Dict[str, Any]] = []
    
    try:
        # Convert audio to WAV 16kHz mono if needed
        wav_path = None
        try:
            # Verify the uploaded file exists
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Uploaded audio file not found at: {audio_path}")
            
            file_ext = os.path.splitext(audio_path)[1].lower()
            print(f"[_process_audio_job] File extension: {file_ext}")
            
            if file_ext != ".wav":
                print(f"[_process_audio_job] Converting {file_ext} to WAV...")
                try:
                    wav_path = extract_audio_wav(audio_path)
                    print(f"[_process_audio_job] Conversion successful, WAV path: {wav_path}")
                except (OSError, FileNotFoundError) as fe:
                    # Handle ffmpeg issues - WinError 2, missing exe, etc.
                    print(f"[_process_audio_job] Conversion failed: {fe}")
                    raise RuntimeError(
                        f"Failed to convert {file_ext} audio to WAV. "
                        f"This usually means ffmpeg is not installed. "
                        f"Install ffmpeg or imageio-ffmpeg and try again. Details: {fe}"
                    ) from fe
            else:
                wav_path = audio_path
                print(f"[_process_audio_job] File is already WAV, using as-is")
            
            update_media_job(job_id, progress=30, stage="audio-transcription")
            
            # Transcribe audio
            print(f"[_process_audio_job] Transcribing audio...")
            transcript_segments = transcribe_audio_segments(wav_path)
            print(f"[_process_audio_job] Transcription complete, {len(transcript_segments)} segments")
            update_media_job(job_id, progress=60, stage="audio-analysis-complete")
            
        except Exception as e:
            print(f"[_process_audio_job] Error during conversion/transcription: {e}")
            import traceback
            traceback.print_exc()
            
            error_msg = str(e)
            if "ffmpeg" in error_msg.lower() or "WinError 2" in str(e):
                error_msg = f"Audio processing failed. ffmpeg may not be installed. {error_msg}"
            
            append_media_job_error(
                job_id,
                stage="audio-transcription",
                message=error_msg,
                recoverable=False,
            )
            raise
        finally:
            # Clean up temp WAV if we created one
            if wav_path and wav_path != audio_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except:
                    pass
        
        # Create description from transcript
        transcript_text = " ".join([seg.get("text", "") for seg in transcript_segments])
        synthesized_description = user_description.strip()
        if transcript_text.strip():
            if synthesized_description:
                synthesized_description += f"\n\nAudio transcript: {transcript_text[:1000]}"
            else:
                synthesized_description = f"Audio transcript: {transcript_text}"
        
        update_media_job(job_id, progress=75, stage="guideline-reasoning")
        
        # Run violation query against guidelines
        violations = _run_violation_query(
            description=synthesized_description,
            docs=docs,
            top_n_for_llm=top_n_for_llm,
        )
        
        # Persist original audio for on-demand remediation
        try:
            originals_dir = RESULTS_DIR / "audio_originals"
            originals_dir.mkdir(parents=True, exist_ok=True)
            orig_basename = f"{job_id}_{os.path.basename(audio_path)}"
            orig_dest = originals_dir / orig_basename
            shutil.copy(audio_path, orig_dest)
            original_rel = str((Path("data") / "violation_results" / "audio_originals" / orig_basename).as_posix())
        except Exception as e:
            print(f"⚠️  Failed to persist original audio: {e}")
            original_rel = None
        
        result_payload = {
            "kind": "audio",
            "created_at": _utc_now_iso(),
            "media_type": "audio",
            "description": synthesized_description,
            "audio_transcription": transcript_segments,
            "selected_docs": [doc.model_dump() for doc in docs],
            "results": [r.model_dump() for r in violations.results],
            "remediation": {
                "enabled": False,
                "original_path": original_rel,
                "audio_path": None,
                "stats": {},
            }
        }
        
        storage_path = _persist_violation_result("audio", result_payload)
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
        update_media_job(job_id, status="failed", stage="fatal", progress=0)


def _extract_violation_terms(violation_results: List[Dict[str, Any]]) -> List[str]:
    """Extract searchable violation terms from guideline results."""
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "have", "has", "not",
        "are", "was", "were", "you", "your", "they", "their", "about", "into", "over",
        "content", "policy", "guideline", "guidelines", "violation", "violations", "media",
        "audio", "text", "speech", "illegal", "harmful", "includes", "include", "using",
    }
    terms: List[str] = []

    for doc_result in violation_results or []:
        candidate_texts: List[str] = []
        if isinstance(doc_result.get("answer"), str):
            candidate_texts.append(doc_result.get("answer", ""))

        for violation in doc_result.get("violations", []) or []:
            for key in ("type", "category", "description", "snippet", "text", "reason"):
                value = violation.get(key)
                if isinstance(value, str) and value.strip():
                    candidate_texts.append(value)

        for blob in candidate_texts:
            for token in re.findall(r"[a-zA-Z']{3,}", blob.lower()):
                cleaned = token.strip("'")
                if cleaned and cleaned not in stop_words:
                    terms.append(cleaned)

    # Keep unique, stable order.
    deduped: List[str] = []
    seen = set()
    for t in terms:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _segment_words_with_timestamps(seg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return word items with timestamps; interpolate if model output has no words."""
    words = seg.get("words") or []
    if isinstance(words, list) and words:
        out: List[Dict[str, Any]] = []
        for w in words:
            start = float(w.get("start", seg.get("start", 0.0)))
            end = float(w.get("end", seg.get("end", start)))
            word = str(w.get("word", "")).strip()
            if not word:
                continue
            out.append({"start": start, "end": max(end, start), "word": word})
        if out:
            return out

    # Fallback: interpolate word timing across segment range.
    seg_text = str(seg.get("text", "")).strip()
    tokens = re.findall(r"\S+", seg_text)
    if not tokens:
        return []

    seg_start = float(seg.get("start", 0.0))
    seg_end = float(seg.get("end", seg_start))
    duration = max(seg_end - seg_start, 0.0)
    step = duration / len(tokens) if tokens else 0.0
    out: List[Dict[str, Any]] = []
    for idx, tok in enumerate(tokens):
        start = seg_start + idx * step
        end = seg_start + (idx + 1) * step if idx < len(tokens) - 1 else seg_end
        out.append({"start": start, "end": max(end, start), "word": tok})
    return out


def _merge_spans(spans: List[Dict[str, float]], max_gap_sec: float = 0.08) -> List[Dict[str, float]]:
    if not spans:
        return []

    ordered = sorted(spans, key=lambda s: (float(s["start"]), float(s["end"])))
    merged: List[Dict[str, float]] = [ordered[0].copy()]

    for span in ordered[1:]:
        current = merged[-1]
        if float(span["start"]) <= float(current["end"]) + max_gap_sec:
            current["end"] = max(float(current["end"]), float(span["end"]))
        else:
            merged.append(span.copy())

    return [{"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3)} for s in merged]


def _map_violation_spans_from_transcript(
    transcript_segments: List[Dict[str, Any]],
    violation_results: List[Dict[str, Any]],
) -> List[Dict[str, float]]:
    """
    Build precise timestamp spans for beeping.
    Priority:
    1) Match words against extracted policy-violation terms.
    2) Toxicity fallback at segment level (never whole-file fallback).
    """
    if not transcript_segments:
        return []

    violation_terms = set(_extract_violation_terms(violation_results))
    spans: List[Dict[str, float]] = []

    for seg in transcript_segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", seg_start))
        seg_text = str(seg.get("text", "")).strip()

        words = _segment_words_with_timestamps(seg)
        for w in words:
            cleaned = re.sub(r"[^a-zA-Z']", "", str(w.get("word", "")).lower()).strip("'")
            if cleaned and cleaned in violation_terms:
                spans.append({
                    "start": float(w.get("start", seg_start)),
                    "end": float(w.get("end", seg_start)),
                })

        # Toxic segment fallback when policy matching cannot localize words.
        level, _score = detect_text(seg_text)
        if level in {"MEDIUM", "HIGH"}:
            spans.append({"start": seg_start, "end": seg_end})

    return _merge_spans(spans)


@app.post("/violations/audio/remediate")
async def remediate_audio_endpoint(payload: Dict[str, Any]):
    """
    Trigger on-demand remediation for a previously-analyzed audio job.
    Beep remediation is always used for detected violating timestamps.
    """
    job_id = payload.get("job_id")
    mode = payload.get("mode", "beep")

    storage_path = payload.get("storage_path") or payload.get("result_storage_path")
    if not job_id and not storage_path:
        raise HTTPException(status_code=400, detail="job_id or storage_path is required")

    if mode != "beep":
        # Backward-compatible input handling: mode is accepted but remediation remains beep-only.
        print(f"⚠️  Audio remediation mode '{mode}' requested; using beep-only remediation")

    job = None
    result = None
    if job_id:
        job = get_media_job(job_id)
        if job:
            result = job.get("result")

    # If no in-memory job/result, allow remediation via a persisted storage_path
    if not result:
        if storage_path:
            try:
                # storage_path may be absolute or relative; try both
                storage_file = Path(storage_path)
                if not storage_file.exists():
                    # try relative to BASE_DIR
                    storage_file = (BASE_DIR / storage_path).resolve()

                if not storage_file.exists():
                    raise HTTPException(status_code=404, detail="Persisted analysis result not found")

                raw = json.loads(storage_file.read_text(encoding="utf-8"))
                result = raw
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to load persisted result: {e}")

    if not result:
        raise HTTPException(status_code=400, detail="Audio job has no result to remediate")

    remediation = result.get("remediation") or {}
    original_rel = remediation.get("original_path")
    if not original_rel:
        raise HTTPException(status_code=400, detail="Original audio not available for remediation")

    # Resolve original file path
    orig_path = (BASE_DIR / Path(original_rel)).resolve()
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="Original audio file not found on server")

    transcript_segments = result.get("audio_transcription", [])
    violation_results = result.get("results", [])

    try:
        rem_dir = RESULTS_DIR / "audio_remediated"
        rem_dir.mkdir(parents=True, exist_ok=True)
        rem_basename = orig_path.stem + "_remediated" + orig_path.suffix
        rem_path = rem_dir / rem_basename

        # Convert audio to WAV for processing
        wav_path = None
        try:
            if orig_path.suffix.lower() != ".wav":
                wav_path = extract_audio_wav(str(orig_path))
            else:
                wav_path = str(orig_path)

            if job_id and job:
                update_media_job(job_id, progress=50, stage="audio-remediation")

            # Identify precise violating timestamps (word-level when available).
            flagged_segments = _map_violation_spans_from_transcript(
                transcript_segments=transcript_segments,
                violation_results=violation_results,
            )

            if not flagged_segments:
                # No violations were detected at all, nothing to remediate
                raise HTTPException(status_code=400, detail="No violations found to remediate")

            # Apply beep remediation only.
            success = remediate_audio_wav(
                original_audio=wav_path,
                flagged_segments=flagged_segments,
                output_audio=str(rem_path),
                use_beep=True,
            )

            if not success:
                raise HTTPException(status_code=500, detail="Audio remediation failed")

            result["remediation"]["audio_path"] = str(
                (Path("data") / "violation_results" / "audio_remediated" / rem_basename).as_posix()
            )
            result["remediation"]["enabled"] = True
            total_beep_duration = sum(max(0.0, float(s.get("end", 0.0)) - float(s.get("start", 0.0))) for s in flagged_segments)
            result["remediation"]["stats"] = {
                "segments_remediated": len(flagged_segments),
                "mode": "beep",
                "mapping_method": "word_timestamps+toxicity",
                "total_beep_duration_sec": round(total_beep_duration, 3),
            }

            # Persist changes back to in-memory job if available, otherwise just return remediation info
            if job_id and job:
                update_media_job(job_id, result=result, progress=100, stage="remediation-completed", status="completed")

            return {"success": True, "remediation": result.get("remediation")}

        finally:
            # Clean up temp WAV
            if wav_path and wav_path != str(orig_path) and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except:
                    pass

    except HTTPException:
        raise
    except Exception as e:
        append_media_job_error(job_id, stage="remediation", message=str(e), recoverable=False)
        raise HTTPException(status_code=500, detail=f"Audio remediation failed: {e}")


@app.get("/violations/audio/remediated/{filename}")
async def get_remediated_audio(filename: str):
    """
    Serve remediated audio files from violation results.
    
    Args:
        filename: The remediated file name (e.g., 'audio_20260504T083640_d996520e_remediated.wav')
    
    Returns:
        The remediated audio file with appropriate content-type header.
    """
    try:
        # Validate filename to prevent directory traversal
        if ".." in filename or filename.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        file_path = RESULTS_DIR / "audio_remediated" / filename
        
        # Verify file exists and is within RESULTS_DIR
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"Remediated audio not found: {filename}")
        
        if not str(file_path.resolve()).startswith(str(RESULTS_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Invalid file path")
        
        # Determine audio type from extension
        suffix = file_path.suffix.lower()
        audio_types = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }
        media_type = audio_types.get(suffix, "audio/wav")
        
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"⚠️  Error serving remediated audio: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving remediated audio: {str(e)}")


# ─────────────────────────────────────────────
# TEXT REMEDIATION ENDPOINTS
# ─────────────────────────────────────────────

class TextAnalysisRequest(BaseModel):
    text_input: str
    platforms: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    description: str = ""
    top_n_for_llm: int = 3


class TextRemediationRequest(BaseModel):
    text_input: str
    mode: str = "mask"  # "mask" or "highlight"


class TextAnalysisResponse(BaseModel):
    success: bool = True
    violations: List[Dict[str, Any]] = Field(default_factory=list)
    original_text: str
    policy_references: List[Dict[str, Any]] = Field(default_factory=list)


class TextRemediationResponse(BaseModel):
    success: bool = True
    original_text: str
    remediated_text: str
    violations: List[Dict[str, Any]] = Field(default_factory=list)
    mode: str


def _normalize_text_redactions(text: str) -> str:
    """Normalize any redaction token into the dashboard's six-asterisk format."""
    if not text:
        return text

    text = re.sub(r"\[REDACTED\]", "******", text, flags=re.IGNORECASE)
    text = re.sub(r"\*{5,}", "******", text)
    return text


@app.post("/violations/text/analyze", response_model=TextAnalysisResponse)
async def analyze_text_endpoint(request: TextAnalysisRequest):
    """Analyze text input for policy violations."""
    if not request.text_input or not request.text_input.strip():
        raise HTTPException(status_code=400, detail="text_input cannot be empty")

    # Resolve documents
    docs = _resolve_docs_by_selection(request.platforms, request.countries)
    if not docs:
        docs = _resolve_docs_by_selection([], [])  # Use default docs if none selected
    
    if not docs:
        raise HTTPException(status_code=400, detail="No guideline documents available")

    try:
        # Run violation query
        violations = _run_violation_query(
            description=request.text_input,
            docs=docs,
            top_n_for_llm=request.top_n_for_llm,
        )
        
        return TextAnalysisResponse(
            success=True,
            violations=[v.model_dump() for v in violations.results],
            original_text=request.text_input,
            policy_references=[doc.model_dump() for doc in docs],
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text analysis failed: {e}")


@app.post("/violations/text/remediate")
async def remediate_text_endpoint(request: TextRemediationRequest):
    """Remediate text by masking violations."""
    if not request.text_input or not request.text_input.strip():
        raise HTTPException(status_code=400, detail="text_input cannot be empty")

    if request.mode not in ["mask", "highlight"]:
        raise HTTPException(status_code=400, detail="mode must be 'mask' or 'highlight'")

    try:
        # Detect toxicity level
        level, score = detect_text(request.text_input)
        
        if request.mode == "mask":
            # Use deterministic masking, then normalize the output token.
            remediated = _normalize_text_redactions(mask_text(request.text_input))
            violations = [{"type": "toxicity", "level": level, "score": score}] if level != "SAFE" else []
        else:  # highlight mode
            remediated = request.text_input  # Keep original, client will highlight
            violations = [{"type": "toxicity", "level": level, "score": score}] if level != "SAFE" else []
        
        remediation_obj = {
            "original_text": request.text_input,
            "remediated_text": remediated,
            "violations": violations,
            "mode": request.mode,
            "stats": {}
        }
        
        return {
            "success": True,
            "remediation": remediation_obj
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text remediation failed: {e}")