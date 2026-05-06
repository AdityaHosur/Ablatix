import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

OLLAMA_CHAT_URL = "https://ollama.com/api/chat"

def _resolve_ffmpeg_executable() -> Optional[str]:
    """Resolve a working ffmpeg executable path on the current machine."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore

        candidate = get_ffmpeg_exe()
        if candidate and os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    candidate = shutil.which("ffmpeg")
    if candidate and os.path.exists(candidate):
        return candidate

    return None


FFMPEG_EXE = _resolve_ffmpeg_executable()
if FFMPEG_EXE:
    import logging
    logging.info(f"[media_jobs] ffmpeg resolved to: {FFMPEG_EXE}")

_MEDIA_JOBS: Dict[str, Dict[str, Any]] = {}
_MEDIA_JOBS_LOCK = threading.Lock()


def _extract_json(content: str) -> Dict[str, Any]:
    """Extract JSON from content with robust fallback handling."""
    if not content:
        return {}

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def create_media_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "progress": 0,
        "payload": payload,
        "stage": "queued",
        "errors": [],
        "result": None,
    }
    with _MEDIA_JOBS_LOCK:
        _MEDIA_JOBS[job_id] = job
    return job


def get_media_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _MEDIA_JOBS_LOCK:
        job = _MEDIA_JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def update_media_job(job_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with _MEDIA_JOBS_LOCK:
        job = _MEDIA_JOBS.get(job_id)
        if not job:
            return None
        job.update(changes)
        job["updated_at"] = _utc_now_iso()
        return dict(job)


def append_media_job_error(job_id: str, stage: str, message: str, recoverable: bool = True) -> None:
    with _MEDIA_JOBS_LOCK:
        job = _MEDIA_JOBS.get(job_id)
        if not job:
            return
        errors = job.get("errors", [])
        errors.append(
            {
                "stage": stage,
                "message": message,
                "recoverable": recoverable,
            }
        )
        job["errors"] = errors
        job["updated_at"] = _utc_now_iso()


def _parse_vision_analysis(response: str) -> Dict[str, Any]:
    """Parse vision model response for violations with normalized coordinates.
    
    Returns dict with 'violations' array and 'description' fallback.
    Violations include: {type, confidence, regions: [{x, y, width, height}]}
    """
    violations = []
    description = response
    
    # Try to extract JSON first
    parsed = _extract_json(response)
    if isinstance(parsed, dict) and "violations" in parsed:
        violations = parsed.get("violations", [])
        parsed_description = parsed.get("description")
        if isinstance(parsed_description, str) and parsed_description.strip():
            description = parsed_description.strip()
        # Validate and normalize coordinates to 0-1
        for v in violations:
            if "regions" in v and isinstance(v["regions"], list):
                for region in v["regions"]:
                    # Clamp to 0-1 if not already
                    region["x"] = max(0, min(1, region.get("x", 0)))
                    region["y"] = max(0, min(1, region.get("y", 0)))
                    region["width"] = max(0, min(1, region.get("width", 0)))
                    region["height"] = max(0, min(1, region.get("height", 0)))
    
    return {
        "violations": violations,
        "description": description,
    }


def frame_bytes_to_data_url(frame_bytes: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(frame_bytes).decode('utf-8')}"


def analyze_image_with_ollama(image_bytes: bytes, model: str, api_key: str, prompt: str) -> str:
    if not api_key:
        raise ValueError("OLLAMA_API_KEY is not configured.")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    response = requests.post(
        OLLAMA_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return (data.get("message", {}) or {}).get("content", "").strip()


def extract_video_sample_frames(video_path: str, max_frames: int = 6) -> List[Tuple[float, bytes]]:
    try:
        import cv2  # pylint: disable=import-error
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for video frame extraction. Install it in backend requirements."
        ) from exc

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 1.0

    if total_frames <= 0:
        cap.release()
        raise ValueError("Video has no readable frames.")

    max_frames = max(1, min(max_frames, 12))
    if max_frames == 1:
        indices = [0]
    else:
        indices = [int(i * (total_frames - 1) / (max_frames - 1)) for i in range(max_frames)]

    out: List[Tuple[float, bytes]] = []

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue

        ok_jpg, buf = cv2.imencode(".jpg", frame)
        if not ok_jpg:
            continue

        out.append((idx / fps, buf.tobytes()))

    cap.release()
    if not out:
        raise ValueError("Could not extract any frames from video.")
    return out


def extract_audio_wav(video_path: str) -> str:
    """Extract audio from video/audio file and convert to 16kHz mono WAV."""
    print(f"\n[extract_audio_wav] Input path: {video_path}")
    print(f"[extract_audio_wav] File exists: {os.path.exists(video_path)}")
    
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input audio file not found: {video_path}")

    if not FFMPEG_EXE:
        raise RuntimeError(
            "ffmpeg is required to process .mp3 and other non-WAV audio files. "
            "Install ffmpeg or imageio-ffmpeg in the backend environment."
        )

    print(f"[extract_audio_wav] Using ffmpeg: {FFMPEG_EXE}")
    print(f"[extract_audio_wav] ffmpeg exists: {os.path.exists(FFMPEG_EXE)}")
    
    fd, audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    print(f"[extract_audio_wav] Output path: {audio_path}")

    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i",
        video_path,
        "-ac",
        "1",
        "-ar",
        "16000",
        audio_path,
    ]
    
    print(f"[extract_audio_wav] Running command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        print(f"[extract_audio_wav] FileNotFoundError: {exc}")
        raise RuntimeError(
            "ffmpeg executable could not be started. Install ffmpeg or imageio-ffmpeg."
        ) from exc

    if proc.returncode != 0:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        error_output = proc.stderr if proc.stderr else "No error output"
        print(f"[extract_audio_wav] ffmpeg failed with code {proc.returncode}")
        print(f"[extract_audio_wav] stderr: {error_output}")
        raise RuntimeError(f"ffmpeg audio extraction failed: {error_output}")

    print(f"[extract_audio_wav] Extraction successful")
    return audio_path


def transcribe_audio_segments(audio_path: str) -> List[Dict[str, Any]]:
    try:
        import whisper  # pylint: disable=import-error
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper is required for audio transcription."
        ) from exc

    print(f"[transcribe_audio_segments] Loading Whisper model...")
    model = whisper.load_model("base")
    
    print(f"[transcribe_audio_segments] Transcribing audio: {audio_path}")
    print(f"[transcribe_audio_segments] File exists: {os.path.exists(audio_path)}")
    
    # Whisper's loader calls `whisper.audio.run` (imported from subprocess at module load).
    # On Windows this may still fail to find ffmpeg even when PATH is modified locally,
    # so we patch whisper.audio.run to replace bare `ffmpeg` with the absolute executable.
    if FFMPEG_EXE:
        ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
        original_path = os.environ.get("PATH", "")
        path_updated = ffmpeg_dir not in original_path
        if path_updated:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + original_path
            print(f"[transcribe_audio_segments] Updated PATH with ffmpeg dir: {ffmpeg_dir}")

        import whisper.audio as whisper_audio  # type: ignore

        original_whisper_run = whisper_audio.run

        def patched_whisper_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and cmd and str(cmd[0]).lower() == "ffmpeg":
                cmd = [FFMPEG_EXE, *cmd[1:]]
            elif isinstance(cmd, tuple) and cmd and str(cmd[0]).lower() == "ffmpeg":
                cmd = (FFMPEG_EXE, *cmd[1:])
            elif isinstance(cmd, str) and cmd.lower().startswith("ffmpeg "):
                cmd = cmd.replace("ffmpeg", f'"{FFMPEG_EXE}"', 1)
            return original_whisper_run(cmd, *args, **kwargs)

        whisper_audio.run = patched_whisper_run

        try:
            result = model.transcribe(audio_path, word_timestamps=True, verbose=False)
        finally:
            whisper_audio.run = original_whisper_run
            if path_updated:
                os.environ["PATH"] = original_path
    else:
        print(f"[transcribe_audio_segments] WARNING: FFMPEG_EXE not set, Whisper may fail")
        result = model.transcribe(audio_path, word_timestamps=True, verbose=False)

    segments: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        words: List[Dict[str, Any]] = []
        for w in seg.get("words", []) or []:
            words.append(
                {
                    "start": round(float(w.get("start", seg.get("start", 0.0))), 3),
                    "end": round(float(w.get("end", seg.get("end", 0.0))), 3),
                    "word": str(w.get("word", "")).strip(),
                    "confidence": round(float(w.get("probability", 0.0)), 4),
                }
            )

        segments.append(
            {
                "start": round(float(seg.get("start", 0.0)), 2),
                "end": round(float(seg.get("end", 0.0)), 2),
                "text": str(seg.get("text", "")).strip(),
                "words": words,
            }
        )
    
    print(f"[transcribe_audio_segments] Transcription complete, {len(segments)} segments")
    return segments


def synthesize_media_description(
    media_type: str,
    user_description: str,
    frame_analyses: List[Dict[str, Any]],
    transcript_segments: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []

    if user_description.strip():
        parts.append(f"User-provided description: {user_description.strip()}")

    if media_type == "image":
        if frame_analyses:
            parts.append(f"Image analysis: {frame_analyses[0].get('description', '')}")
    else:
        frame_lines: List[str] = []
        for frame in frame_analyses:
            frame_lines.append(
                f"- t={frame.get('timestamp', 0)}s: {frame.get('description', '')}"
            )

        if frame_lines:
            parts.append("Video frame findings:\n" + "\n".join(frame_lines))

        if transcript_segments:
            transcript_lines = [
                f"- {seg.get('start', 0)}s to {seg.get('end', 0)}s: {seg.get('text', '')}"
                for seg in transcript_segments[:12]
            ]
            parts.append("Audio transcript highlights:\n" + "\n".join(transcript_lines))

    parts.append(
        "Task: identify guideline violations, with specific references and plain-language explanations."
    )

    return "\n\n".join([p for p in parts if p.strip()])
