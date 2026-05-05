"""
Remediation module for text, image, and video content.

Provides functions to detect and remediate harmful content:
- Text: mask toxic/harmful words
- Image: blur harmful regions detected by YOLO or LLM
- Video: frame-by-frame blur with audio muting/beeping
- Audio: mute or beep harmful speech segments
"""

import cv2
import numpy as np
import os
import json
import tempfile
import subprocess
import wave
import struct
import math
from pathlib import Path
from typing import Tuple, List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def get_ffmpeg_executable() -> str:
    """Return a path to an ffmpeg executable.

    Prefers the `imageio_ffmpeg` bundled binary when available, otherwise
    falls back to the system `ffmpeg` command name.
    """
    try:
        from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore

        path = get_ffmpeg_exe()
        if path:
            return path
    except Exception:
        # imageio-ffmpeg not installed or failed — fall back
        pass

    return "ffmpeg"

# ─────────────────────────────────────────────────────────────────────────────
# TEXT REMEDIATION
# ─────────────────────────────────────────────────────────────────────────────

try:
    from transformers import pipeline
    TOXICITY_CLASSIFIER = None  # Lazy load
except ImportError:
    logger.warning("transformers not installed; text classification will be disabled")
    TOXICITY_CLASSIFIER = None

try:
    from better_profanity import profanity
    PROFANITY_READY = False  # Lazy load
except ImportError:
    logger.warning("better_profanity not installed; keyword-based profanity filtering disabled")
    PROFANITY_READY = False


def _load_toxicity_classifier():
    """Lazy load the toxic-bert text classifier."""
    global TOXICITY_CLASSIFIER
    if TOXICITY_CLASSIFIER is None:
        try:
            TOXICITY_CLASSIFIER = pipeline("text-classification", model="unitary/toxic-bert")
            logger.info("✅ Toxicity classifier loaded")
        except Exception as e:
            logger.error(f"Failed to load toxicity classifier: {e}")
            TOXICITY_CLASSIFIER = False
    return TOXICITY_CLASSIFIER


def _load_profanity_filter():
    """Lazy load better-profanity filter."""
    global PROFANITY_READY
    if not PROFANITY_READY:
        try:
            profanity.load_censor_words()
            PROFANITY_READY = True
            logger.info("✅ Profanity filter loaded")
        except Exception as e:
            logger.error(f"Failed to load profanity filter: {e}")
            PROFANITY_READY = False
    return PROFANITY_READY


def detect_text(text: str) -> Tuple[str, float]:
    """
    Detect toxicity level in text using toxic-bert classifier.

    Args:
        text: Text to analyze

    Returns:
        (level, score) where level is "SAFE", "MEDIUM", or "HIGH"
    """
    if not text or text.strip() == "":
        return "SAFE", 0.0

    classifier = _load_toxicity_classifier()
    if classifier is False:
        logger.warning("Toxicity classifier unavailable; returning SAFE")
        return "SAFE", 0.0

    try:
        result = classifier(text)[0]
        score = result["score"]

        if score > 0.7:
            return "HIGH", score
        elif score > 0.4:
            return "MEDIUM", score
        else:
            return "SAFE", score
    except Exception as e:
        logger.error(f"Error detecting text toxicity: {e}")
        return "SAFE", 0.0


def mask_text(text: str) -> str:
    """
    Mask toxic words in text by replacing with asterisks.

    Args:
        text: Text to remediate

    Returns:
        Text with toxic words masked
    """
    if not text or text.strip() == "":
        return text

    # Load profanity filter if needed
    _load_profanity_filter()

    words = text.split()
    masked_words = []

    for word in words:
        # First check better-profanity keyword list
        if PROFANITY_READY:
            try:
                if profanity.contains_profanity(word):
                    masked_words.append("*" * len(word))
                    continue
            except Exception as e:
                logger.warning(f"Error checking profanity for '{word}': {e}")

        # Then check ML classifier
        classifier = _load_toxicity_classifier()
        if classifier and classifier is not False:
            try:
                result = classifier(word)[0]
                if result["score"] > 0.4:
                    masked_words.append("*" * len(word))
                    continue
            except Exception as e:
                logger.warning(f"Error classifying word '{word}': {e}")

        # Keep original word if not flagged
        masked_words.append(word)

    return " ".join(masked_words)


def process_text(text: str) -> Dict:
    """
    Process text: detect toxicity and remediate if needed.

    Args:
        text: Text to process

    Returns:
        {
            "original": original_text,
            "remediated": remediated_text,
            "level": toxicity_level
        }
    """
    level, score = detect_text(text)

    if level == "SAFE":
        return {
            "original": text,
            "remediated": text,
            "level": level,
            "score": score
        }

    safe_text = mask_text(text)

    return {
        "original": text,
        "remediated": safe_text,
        "level": level,
        "score": score
    }


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE REMEDIATION
# ─────────────────────────────────────────────────────────────────────────────


def blur_region(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int,
                strength: int = 51) -> np.ndarray:
    """
    Apply Gaussian blur to a rectangular region of an image/frame.

    Args:
        frame: Input image (numpy array, BGR format from OpenCV)
        x1, y1, x2, y2: Bounding box coordinates (top-left, bottom-right)
        strength: Blur kernel size (must be odd; default 51)

    Returns:
        Frame with blurred region
    """
    h, w = frame.shape[:2]
    
    # Clamp coordinates to frame bounds
    x1 = max(0, int(x1))
    y1 = max(0, int(y1))
    x2 = min(w, int(x2))
    y2 = min(h, int(y2))

    # Skip if region is invalid
    if x2 <= x1 or y2 <= y1:
        return frame

    # Ensure kernel size is odd
    k = strength if strength % 2 == 1 else strength + 1

    # Extract region of interest and blur it
    roi = frame[y1:y2, x1:x2]
    if roi.size > 0:
        frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)

    return frame


def blur_image_bytes(image_bytes: bytes, bboxes: List[Dict], blur_strength: int = 51) -> bytes:
    """
    Blur harmful regions in an image given as bytes.

    Args:
        image_bytes: Image data (JPEG/PNG/etc.)
        bboxes: List of bounding boxes, each with keys:
            - "x1", "y1", "x2", "y2": Pixel coordinates
            - OR "bbox": [x1, y1, x2, y2]
        blur_strength: Gaussian blur kernel size (default 51)

    Returns:
        Blurred image as bytes (same format as input if possible)
    """
    # Decode image
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            logger.error("Failed to decode image bytes")
            return image_bytes
    except Exception as e:
        logger.error(f"Error decoding image bytes: {e}")
        return image_bytes

    # Apply blur to each bounding box
    for bbox_info in bboxes:
        try:
            # Extract coordinates (support both formats)
            if "bbox" in bbox_info:
                x1, y1, x2, y2 = bbox_info["bbox"]
            else:
                x1 = bbox_info.get("x1", bbox_info.get("x", 0))
                y1 = bbox_info.get("y1", bbox_info.get("y", 0))
                x2 = bbox_info.get("x2", x1 + 10)
                y2 = bbox_info.get("y2", y1 + 10)

            img = blur_region(img, x1, y1, x2, y2, blur_strength)
        except Exception as e:
            logger.warning(f"Error blurring bbox {bbox_info}: {e}")
            continue

    # Encode back to bytes
    try:
        _, buffer = cv2.imencode(".jpg", img)
        return buffer.tobytes()
    except Exception as e:
        logger.error(f"Error encoding blurred image: {e}")
        return image_bytes


def remediate_image_file(input_path: str, output_path: str, bboxes: List[Dict],
                         blur_strength: int = 51) -> bool:
    """
    Load image, blur harmful regions, and save remediated image.

    Args:
        input_path: Path to input image
        output_path: Path to save remediated image
        bboxes: List of bounding boxes to blur
        blur_strength: Blur kernel size

    Returns:
        True if successful, False otherwise
    """
    try:
        # Read image
        img = cv2.imread(input_path)
        if img is None:
            logger.error(f"Failed to read image: {input_path}")
            return False

        h, w = img.shape[:2]

        # Apply blur to each bounding box
        for bbox_info in bboxes:
            try:
                # Extract coordinates
                if "bbox" in bbox_info:
                    x1, y1, x2, y2 = bbox_info["bbox"]
                else:
                    x1 = bbox_info.get("x1", bbox_info.get("x", 0))
                    y1 = bbox_info.get("y1", bbox_info.get("y", 0))
                    x2 = bbox_info.get("x2", x1 + 10)
                    y2 = bbox_info.get("y2", y1 + 10)

                img = blur_region(img, x1, y1, x2, y2, blur_strength)
            except Exception as e:
                logger.warning(f"Error blurring bbox {bbox_info}: {e}")
                continue

        # Save remediated image
        success = cv2.imwrite(output_path, img)
        if not success:
            logger.error(f"Failed to write remediated image: {output_path}")
            return False

        logger.info(f"✅ Remediated image saved: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error remediating image: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO REMEDIATION
# ─────────────────────────────────────────────────────────────────────────────


def generate_beep(duration_sec: float, sample_rate: int = 16000,
                  freq_hz: int = 1000, amplitude: float = 0.3) -> bytes:
    """
    Generate a beep tone as raw PCM bytes.

    Args:
        duration_sec: Duration of beep in seconds
        sample_rate: Sample rate in Hz (default 16000)
        freq_hz: Beep frequency in Hz (default 1000)
        amplitude: Amplitude (0.0-1.0, default 0.3)

    Returns:
        Raw PCM bytes (16-bit signed)
    """
    num_samples = int(sample_rate * duration_sec)
    samples = [
        int(amplitude * 32767 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(num_samples)
    ]
    return struct.pack(f"{num_samples}h", *samples)


def remediate_audio_wav(original_audio: str, flagged_segments: List[Dict],
                        output_audio: str, use_beep: bool = True) -> bool:
    """
    Mute or beep harmful segments in a WAV audio file.

    Args:
        original_audio: Path to input WAV file
        flagged_segments: List of harmful segments with 'start' and 'end' times (in seconds)
        output_audio: Path to save remediated audio
        use_beep: If True, replace with beep tone; if False, replace with silence

    Returns:
        True if successful, False otherwise
    """
    try:
        # Open and read WAV file
        with wave.open(original_audio, "rb") as wf:
            params = wf.getparams()
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw_data = bytearray(wf.readframes(n_frames))

        bytes_per_sample = sampwidth * n_channels

        # Process each flagged segment
        for seg in flagged_segments:
            start_frame = int(seg["start"] * sample_rate)
            end_frame = int(seg["end"] * sample_rate)
            start_byte = start_frame * bytes_per_sample
            end_byte = min(end_frame * bytes_per_sample, len(raw_data))
            duration = seg["end"] - seg["start"]

            if use_beep:
                # Generate beep and insert
                beep_pcm = generate_beep(duration, sample_rate)
                beep_len = min(len(beep_pcm), end_byte - start_byte)
                raw_data[start_byte : start_byte + beep_len] = beep_pcm[:beep_len]
            else:
                # Insert silence (zeros)
                raw_data[start_byte:end_byte] = bytes(end_byte - start_byte)

        # Write remediated audio
        with wave.open(output_audio, "wb") as wf:
            wf.setparams(params)
            wf.writeframes(bytes(raw_data))

        logger.info(f"✅ Remediated audio saved: {output_audio} ({len(flagged_segments)} segments processed)")
        return True

    except Exception as e:
        logger.error(f"Error remediating audio: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────


def remediate_media(media_type: str, input_path: str, output_path: str,
                    detections: Optional[Dict] = None, **kwargs) -> Dict:
    """
    Orchestrator function: routes to appropriate remediation based on media type.

    Args:
        media_type: "text", "image", or "video"
        input_path: Path to input file (or text string if media_type=="text")
        output_path: Path to save remediated file
        detections: Detection results (bounding boxes, segments, etc.)
        **kwargs: Additional arguments (e.g., audio_segments, blur_strength)

    Returns:
        {
            "success": bool,
            "media_type": str,
            "input": str,
            "output": str,
            "details": dict
        }
    """
    result = {
        "success": False,
        "media_type": media_type,
        "input": input_path,
        "output": output_path,
        "details": {}
    }

    try:
        if media_type == "text":
            processed = process_text(input_path)
            result["success"] = True
            result["details"] = processed
            result["remediated_text"] = processed["remediated"]

        elif media_type == "image":
            bboxes = detections or []
            blur_strength = kwargs.get("blur_strength", 51)
            success = remediate_image_file(input_path, output_path, bboxes, blur_strength)
            result["success"] = success
            result["details"] = {
                "num_bboxes": len(bboxes),
                "blur_strength": blur_strength
            }

        elif media_type == "audio":
            audio_segments = detections or []
            use_beep = kwargs.get("use_beep", True)
            success = remediate_audio_wav(input_path, audio_segments, output_path, use_beep)
            result["success"] = success
            result["details"] = {
                "num_segments": len(audio_segments),
                "use_beep": use_beep
            }

        else:
            logger.error(f"Unknown media type: {media_type}")
            result["details"]["error"] = f"Unknown media type: {media_type}"

    except Exception as e:
        logger.error(f"Error in remediate_media: {e}")
        result["details"]["error"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# VIDEO REMEDIATION
# ─────────────────────────────────────────────────────────────────────────────


def extract_video_frames(video_path: str, output_dir: str, skip_frames: int = 1) -> Tuple[List[str], float, int, int]:
    """
    Extract frames from video to image files.

    Args:
        video_path: Path to input video
        output_dir: Directory to save extracted frames
        skip_frames: Extract every Nth frame (1=all, 2=every 2nd, etc.)

    Returns:
        (frame_paths, fps, width, height)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        logger.info(f"📹 Extracting frames: {width}x{height} @ {fps:.1f} fps | {total_frames} total frames")

        frame_paths = []
        frame_idx = 0
        extracted_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Extract every Nth frame
            if frame_idx % skip_frames == 0:
                frame_path = os.path.join(output_dir, f"frame_{extracted_idx:06d}.jpg")
                cv2.imwrite(frame_path, frame)
                frame_paths.append(frame_path)
                extracted_idx += 1

            frame_idx += 1

        cap.release()
        logger.info(f"✅ Extracted {len(frame_paths)} frames")
        return frame_paths, fps, width, height

    except Exception as e:
        logger.error(f"Error extracting video frames: {e}")
        raise


def remediate_frame(frame: np.ndarray, bboxes: List[Dict], blur_strength: int = 51) -> np.ndarray:
    """
    Apply blur to all bounding boxes in a single frame.

    Args:
        frame: Input frame (numpy array)
        bboxes: List of bounding boxes with pixel coordinates
        blur_strength: Gaussian blur kernel size

    Returns:
        Remediated frame
    """
    remediated = frame.copy()
    for bbox_info in bboxes:
        try:
            if "bbox" in bbox_info:
                x1, y1, x2, y2 = bbox_info["bbox"]
            else:
                x1 = bbox_info.get("x1", 0)
                y1 = bbox_info.get("y1", 0)
                x2 = bbox_info.get("x2", x1 + 10)
                y2 = bbox_info.get("y2", y1 + 10)

            remediated = blur_region(remediated, x1, y1, x2, y2, blur_strength)
        except Exception as e:
            logger.warning(f"Error blurring bbox in frame: {e}")
            continue

    return remediated


def process_video_frames(video_path: str, frame_analyses: List[Dict],
                         output_video_path: str, blur_strength: int = 51) -> Dict:
    """
    Extract frames from video, apply blur to detected violations, re-encode video.

    Args:
        video_path: Path to input video
        frame_analyses: List of frame violation analysis with timestamps and bboxes
        output_video_path: Path to save remediated video
        blur_strength: Gaussian blur kernel size

    Returns:
        {
            "success": bool,
            "total_frames": int,
            "remediated_frames": int,
            "fps": float,
            "width": int,
            "height": int,
            "output_path": str
        }
    """
    result = {
        "success": False,
        "total_frames": 0,
        "remediated_frames": 0,
        "fps": 0,
        "width": 0,
        "height": 0,
        "output_path": output_video_path
    }

    temp_frame_dir = None

    try:
        # Collect ALL unique violations from all analyzed frames
        # (video analysis only samples 6 frames, but we apply to all frames)
        all_violations = []
        for analysis in frame_analyses:
            violations = analysis.get("violations", [])
            # Collect unique violations across all frames
            for violation in violations:
                # Check if this violation is already in all_violations
                if not any(v.get("type") == violation.get("type") for v in all_violations):
                    all_violations.append(violation)

        logger.info(f"🔍 Found {len(all_violations)} unique violations to apply across all frames")

        # Open input video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        result["fps"] = fps
        result["width"] = width
        result["height"] = height
        result["total_frames"] = total_frames

        # Prepare output video writer
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
        if not out.isOpened():
            raise RuntimeError(f"Failed to open video writer: {output_video_path}")

        logger.info(f"📹 Processing video: {width}x{height} @ {fps:.1f} fps | {total_frames} frames")

        frame_idx = 0
        remediated_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Apply violations to ALL frames (if violations were detected in any sample frame)
            remediated_frame = frame
            if all_violations:
                # Convert normalized coordinates to pixels
                bboxes = _extract_bboxes_from_violations(all_violations, width, height)
                if bboxes:
                    remediated_frame = remediate_frame(frame, bboxes, blur_strength)
                    remediated_count += 1

            out.write(remediated_frame)
            frame_idx += 1

        cap.release()
        out.release()

        result["success"] = True
        # If violations were found, all frames got remediated
        result["remediated_frames"] = total_frames if all_violations else 0

        logger.info(f"✅ Video remediation complete: {result['remediated_frames']}/{total_frames} frames processed with blur")
        return result

    except Exception as e:
        logger.error(f"Error processing video frames: {e}")
        result["details"] = {"error": str(e)}
        return result

    finally:
        if temp_frame_dir and os.path.exists(temp_frame_dir):
            import shutil
            shutil.rmtree(temp_frame_dir, ignore_errors=True)


def merge_video_with_audio(video_path: str, audio_path: Optional[str],
                           output_path: str, use_shortest: bool = True) -> bool:
    """
    Merge remediated video with remediated (or original) audio using ffmpeg.

    Args:
        video_path: Path to remediated video (no audio)
        audio_path: Path to remediated audio WAV, or None for no audio
        output_path: Path to save final merged video
        use_shortest: If True, use -shortest flag (stops at end of shorter stream)

    Returns:
        True if successful, False otherwise
    """
    try:
        ffmpeg_exe = get_ffmpeg_executable()

        if audio_path and os.path.exists(audio_path):
            # Check if ffmpeg is available
            try:
                result = subprocess.run([ffmpeg_exe, "-version"], capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error("ffmpeg not found; cannot merge video with audio")
                    # Fallback: copy video-only path to output so remediation can continue without audio
                    try:
                        import shutil
                        shutil.copy2(video_path, output_path)
                        logger.warning("ffmpeg missing — produced output contains video only (no audio). Install ffmpeg to enable audio merging.")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to copy video-only file to output: {e}")
                        return False
            except FileNotFoundError:
                logger.error("ffmpeg binary not found on PATH (FileNotFoundError)")
                try:
                    import shutil
                    shutil.copy2(video_path, output_path)
                    logger.warning("ffmpeg not installed — output contains video only (no audio). Install ffmpeg to enable audio merging.")
                    return True
                except Exception as e:
                    logger.error(f"Failed to copy video-only file to output: {e}")
                    return False

            logger.info(f"🔗 Merging video + audio: {output_path}")

            # Build ffmpeg command
            cmd = [
                ffmpeg_exe, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k"
            ]

            if use_shortest:
                cmd.append("-shortest")

            cmd.append(output_path)

            # Run ffmpeg
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            except FileNotFoundError as e:
                logger.error(f"ffmpeg not found when attempting merge: {e}")
                try:
                    import shutil
                    shutil.copy2(video_path, output_path)
                    logger.warning("ffmpeg not installed — output contains video only (no audio). Install ffmpeg to enable audio merging.")
                    return True
                except Exception as e2:
                    logger.error(f"Failed to copy video-only file to output: {e2}")
                    return False

            if result.returncode != 0:
                logger.error(f"ffmpeg merge failed: {result.stderr}")
                return False

            logger.info(f"✅ Video merged with audio: {output_path}")
            return True

        else:
            # No audio provided; just re-encode video with quality settings
            logger.info(f"📹 Re-encoding video (no audio merge): {output_path}")

            cmd = [
                ffmpeg_exe, "-y",
                "-i", video_path,
                "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                output_path
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            except FileNotFoundError:
                logger.error("ffmpeg binary not found when attempting re-encode; copying video instead")
                try:
                    import shutil
                    shutil.copy2(video_path, output_path)
                    logger.warning("ffmpeg not installed — copied video-only file to output. Install ffmpeg to enable re-encoding.")
                    return True
                except Exception as e:
                    logger.error(f"Failed to copy video-only file to output: {e}")
                    return False

            if result.returncode != 0:
                logger.error(f"ffmpeg re-encode failed: {result.stderr}")
                return False

            logger.info(f"✅ Video re-encoded: {output_path}")
            return True

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg command timed out (>1 hour)")
        return False
    except Exception as e:
        logger.error(f"Error merging video with audio: {e}")
        return False


def remediate_video(input_video_path: str, output_video_path: str,
                    frame_analyses: List[Dict], audio_segments: Optional[List[Dict]] = None,
                    blur_strength: int = 51, use_beep: bool = True) -> Dict:
    """
    Full end-to-end video remediation:
    1. Extract frames from video
    2. Apply blur to violation regions
    3. Re-encode video
    4. If audio provided, remediate audio segments
    5. Merge remediated video + audio

    Args:
        input_video_path: Path to input video
        output_video_path: Path to save final remediated video
        frame_analyses: List of frame analysis with violations and timestamps
        audio_segments: List of harmful audio segments (optional)
        blur_strength: Gaussian blur kernel size
        use_beep: Use beep or silence for audio remediation

    Returns:
        {
            "success": bool,
            "video_path": str,
            "audio_path": Optional[str],
            "merged_path": str,
            "frame_stats": dict,
            "audio_stats": dict,
            "details": dict
        }
    """
    result = {
        "success": False,
        "video_path": None,
        "audio_path": None,
        "merged_path": output_video_path,
        "frame_stats": {},
        "audio_stats": {},
        "details": {}
    }

    temp_video_path = None
    temp_audio_path = None

    try:
        # Step 1: Remediate video frames
        logger.info("🎬 STEP 1: Processing video frames...")
        temp_video_path = output_video_path.replace(".mp4", "_video_only.mp4")
        
        frame_result = process_video_frames(input_video_path, frame_analyses,
                                           temp_video_path, blur_strength)

        if not frame_result["success"]:
            raise RuntimeError("Failed to process video frames")

        result["frame_stats"] = frame_result
        result["video_path"] = temp_video_path

        # Step 2: Remediate audio (if provided)
        final_audio_path = None
        if audio_segments:
            logger.info("🎤 STEP 2: Processing audio segments...")

            # Extract audio from original video
            temp_audio_extracted = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
            try:
                ffmpeg_exe = get_ffmpeg_executable()
                extract_cmd = [
                    ffmpeg_exe, "-y", "-i", input_video_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    temp_audio_extracted
                ]
                extract_result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=300)

                if extract_result.returncode == 0 and os.path.exists(temp_audio_extracted):
                    # Remediate audio
                    temp_audio_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
                    audio_success = remediate_audio_wav(temp_audio_extracted, audio_segments,
                                                        temp_audio_path, use_beep)

                    if audio_success:
                        final_audio_path = temp_audio_path
                        result["audio_stats"] = {
                            "num_segments": len(audio_segments),
                            "use_beep": use_beep
                        }
                        logger.info(f"✅ Audio remediated: {len(audio_segments)} segments")
                    else:
                        logger.warning("Audio remediation failed; skipping audio merge")

            except Exception as e:
                logger.warning(f"Audio extraction/remediation failed: {e}")
            finally:
                if os.path.exists(temp_audio_extracted):
                    os.remove(temp_audio_extracted)

        # Step 3: Merge video + audio
        logger.info("🔗 STEP 3: Merging video and audio...")
        merge_success = merge_video_with_audio(temp_video_path, final_audio_path,
                                               output_video_path, use_shortest=True)

        if not merge_success:
            raise RuntimeError("Failed to merge video with audio")

        result["success"] = True
        result["details"] = {
            "video_remediated": True,
            "audio_remediated": final_audio_path is not None,
            "total_frames": frame_result["total_frames"],
            "remediated_frames": frame_result["remediated_frames"]
        }

        logger.info(f"✅ Full video remediation complete: {output_video_path}")
        return result

    except Exception as e:
        logger.error(f"Error in video remediation: {e}")
        result["details"]["error"] = str(e)
        return result

    finally:
        # Cleanup temporary files
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
                logger.debug(f"Cleaned up temp video: {temp_video_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp video: {e}")

        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
                logger.debug(f"Cleaned up temp audio: {temp_audio_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp audio: {e}")


def _extract_bboxes_from_violations(violations: List[Dict], frame_width: int, 
                                    frame_height: int) -> List[Dict]:
    """
    Convert normalized violation coordinates (0-1) to pixel coordinates.
    
    Helper function for video frame processing.
    """
    bboxes = []
    for violation in violations:
        regions = violation.get("regions", [])
        for region in regions:
            try:
                norm_x = float(region.get("x", 0))
                norm_y = float(region.get("y", 0))
                norm_width = float(region.get("width", 0.1))
                norm_height = float(region.get("height", 0.1))
                
                x1 = int(norm_x * frame_width)
                y1 = int(norm_y * frame_height)
                x2 = int((norm_x + norm_width) * frame_width)
                y2 = int((norm_y + norm_height) * frame_height)
                
                bboxes.append({"bbox": [x1, y1, x2, y2]})
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing region {region}: {e}")
                continue
    
    return bboxes

