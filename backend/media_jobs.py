import base64
import os
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

OLLAMA_CHAT_URL = "https://ollama.com/api/chat"

_MEDIA_JOBS: Dict[str, Dict[str, Any]] = {}
_MEDIA_JOBS_LOCK = threading.Lock()


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
    fd, audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-ac",
        "1",
        "-ar",
        "16000",
        audio_path,
    ]

    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise RuntimeError("ffmpeg audio extraction failed.")

    return audio_path


def transcribe_audio_segments(audio_path: str) -> List[Dict[str, Any]]:
    try:
        import whisper  # pylint: disable=import-error
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper is required for audio transcription."
        ) from exc

    model = whisper.load_model("base")
    result = model.transcribe(audio_path)

    segments: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        segments.append(
            {
                "start": round(float(seg.get("start", 0.0)), 2),
                "end": round(float(seg.get("end", 0.0)), 2),
                "text": str(seg.get("text", "")).strip(),
            }
        )
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
