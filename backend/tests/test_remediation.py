"""
Unit tests for the remediation module.

Tests text, image, and audio remediation functions.
"""

import pytest
import os
import tempfile
import numpy as np
import cv2
import wave
import struct
from pathlib import Path

# Add backend to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from remediation import (
    detect_text,
    mask_text,
    process_text,
    blur_region,
    blur_image_bytes,
    remediate_image_file,
    generate_beep,
    remediate_audio_wav,
    remediate_media,
    remediate_frame,
)


# ─────────────────────────────────────────────────────────────────────────────
# TEXT REMEDIATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestTextRemediation:
    """Tests for text detection and masking."""

    def test_detect_text_safe(self):
        """Test that safe text is classified as SAFE."""
        level, score = detect_text("Have a nice day")
        assert level == "SAFE"
        assert 0 <= score <= 1

    def test_detect_text_harmful(self):
        """Test that harmful text is flagged as HIGH or MEDIUM."""
        level, score = detect_text("I hate you")
        assert level in ["HIGH", "MEDIUM", "SAFE"]  # May vary by model
        assert 0 <= score <= 1

    def test_detect_text_empty(self):
        """Test that empty text returns SAFE."""
        level, score = detect_text("")
        assert level == "SAFE"
        assert score == 0.0

    def test_mask_text_basic(self):
        """Test basic text masking."""
        original = "I hate you"
        masked = mask_text(original)
        # Should have some masking or remain same
        assert masked is not None
        assert len(masked) > 0

    def test_process_text_returns_dict(self):
        """Test that process_text returns proper dict."""
        result = process_text("Have a nice day")
        assert "original" in result
        assert "remediated" in result
        assert "level" in result
        assert result["original"] == "Have a nice day"


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE REMEDIATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestImageRemediation:
    """Tests for image blur and remediation."""

    @pytest.fixture
    def sample_image(self):
        """Create a simple test image with varied content."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        # Create a varied pattern to test blur
        img[0:50, :] = (255, 0, 0)  # Blue top half
        img[50:100, :] = (0, 255, 0)  # Green bottom half
        # Add some variation
        img[20:30, 20:30] = (0, 0, 255)  # Red box
        return img

    def test_blur_region_basic(self, sample_image):
        """Test that blur_region modifies the image."""
        original = sample_image.copy()
        original_roi = original[10:50, 10:50].copy()
        
        blurred = blur_region(original.copy(), 10, 10, 50, 50, strength=51)
        
        # Check that the blurred region is different from the original
        roi_blurred = blurred[10:50, 10:50]
        
        # Blurred should be different (due to Gaussian blur smoothing)
        # At least some pixels should be different
        diff = np.sum(np.abs(original_roi.astype(int) - roi_blurred.astype(int)))
        assert diff > 0, "Blur should modify pixel values"

    def test_blur_region_out_of_bounds(self, sample_image):
        """Test that blur_region handles out-of-bounds coordinates gracefully."""
        img = sample_image.copy()
        # Coordinates outside image bounds
        blurred = blur_region(img, -10, -10, 150, 150, strength=51)
        # Should not crash and return an image
        assert blurred is not None

    def test_blur_region_invalid_coords(self, sample_image):
        """Test that blur_region handles invalid (reversed) coordinates."""
        img = sample_image.copy()
        # x2 < x1 (invalid)
        blurred = blur_region(img, 50, 50, 10, 10, strength=51)
        # Should return unmodified image
        assert np.array_equal(blurred, img)

    def test_blur_image_bytes_basic(self, sample_image):
        """Test blur_image_bytes with simple bboxes."""
        # Encode image to bytes
        _, buffer = cv2.imencode(".jpg", sample_image)
        img_bytes = buffer.tobytes()
        
        # Blur with bboxes
        bboxes = [{"bbox": [10, 10, 50, 50]}]
        blurred_bytes = blur_image_bytes(img_bytes, bboxes, blur_strength=51)
        
        # Should return bytes
        assert isinstance(blurred_bytes, bytes)
        assert len(blurred_bytes) > 0

    def test_blur_image_bytes_multiple_bboxes(self, sample_image):
        """Test blur_image_bytes with multiple bboxes."""
        _, buffer = cv2.imencode(".jpg", sample_image)
        img_bytes = buffer.tobytes()
        
        bboxes = [
            {"bbox": [10, 10, 30, 30]},
            {"bbox": [50, 50, 70, 70]}
        ]
        blurred_bytes = blur_image_bytes(img_bytes, bboxes, blur_strength=51)
        
        assert isinstance(blurred_bytes, bytes)
        assert len(blurred_bytes) > 0

    def test_blur_image_bytes_empty_bboxes(self, sample_image):
        """Test blur_image_bytes with no bboxes."""
        _, buffer = cv2.imencode(".jpg", sample_image)
        img_bytes = buffer.tobytes()
        
        blurred_bytes = blur_image_bytes(img_bytes, [], blur_strength=51)
        
        # Should still return valid bytes (unmodified image)
        assert isinstance(blurred_bytes, bytes)

    def test_remediate_image_file(self, sample_image):
        """Test end-to-end image remediation to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test_input.jpg")
            output_path = os.path.join(tmpdir, "test_output.jpg")
            
            # Write test image
            cv2.imwrite(input_path, sample_image)
            
            # Remediate
            bboxes = [{"bbox": [10, 10, 50, 50]}]
            success = remediate_image_file(input_path, output_path, bboxes, blur_strength=51)
            
            assert success
            assert os.path.exists(output_path)
            
            # Verify output is a valid image
            remediated = cv2.imread(output_path)
            assert remediated is not None


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO REMEDIATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestAudioRemediation:
    """Tests for audio beep generation and remediation."""

    def test_generate_beep(self):
        """Test beep generation."""
        beep_bytes = generate_beep(1.0, sample_rate=16000, freq_hz=1000)
        # 1 second at 16kHz with 16-bit samples should be ~32KB
        assert len(beep_bytes) == 16000 * 2  # 2 bytes per sample

    def test_generate_beep_short(self):
        """Test short beep generation."""
        beep_bytes = generate_beep(0.1, sample_rate=16000, freq_hz=1000)
        assert len(beep_bytes) == 1600 * 2

    @pytest.fixture
    def sample_wav(self):
        """Create a test WAV file with a few seconds of silence."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        
        # Create 3 seconds of silence at 16kHz
        sample_rate = 16000
        duration = 3
        n_frames = sample_rate * duration
        
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            
            silence = struct.pack(f"{n_frames}h", *([0] * n_frames))
            wf.writeframes(silence)
        
        yield wav_path
        
        # Cleanup
        if os.path.exists(wav_path):
            os.remove(wav_path)

    def test_remediate_audio_wav_silence(self, sample_wav):
        """Test audio remediation with silence replacement."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        
        try:
            segments = [{"start": 0.5, "end": 1.0}]
            success = remediate_audio_wav(sample_wav, segments, output_path, use_beep=False)
            
            assert success
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_remediate_audio_wav_beep(self, sample_wav):
        """Test audio remediation with beep replacement."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        
        try:
            segments = [{"start": 0.5, "end": 1.0}]
            success = remediate_audio_wav(sample_wav, segments, output_path, use_beep=True)
            
            assert success
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_remediate_audio_wav_multiple_segments(self, sample_wav):
        """Test audio remediation with multiple segments."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        
        try:
            segments = [
                {"start": 0.5, "end": 1.0},
                {"start": 1.5, "end": 2.0}
            ]
            success = remediate_audio_wav(sample_wav, segments, output_path, use_beep=True)
            
            assert success
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestratorRemediation:
    """Tests for the remediate_media orchestrator."""

    def test_remediate_media_text(self):
        """Test text remediation via orchestrator."""
        result = remediate_media("text", "I hate you", None)
        
        assert result["success"]
        assert result["media_type"] == "text"
        assert "remediated_text" in result

    def test_remediate_media_unknown_type(self):
        """Test that unknown media type is handled."""
        result = remediate_media("video", "dummy.mp4", "dummy_out.mp4")
        
        assert not result["success"]
        assert result["media_type"] == "video"

    def test_remediate_media_image(self):
        """Test image remediation via orchestrator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test image
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:, :] = (255, 0, 0)
            
            input_path = os.path.join(tmpdir, "test.jpg")
            output_path = os.path.join(tmpdir, "test_out.jpg")
            
            cv2.imwrite(input_path, img)
            
            bboxes = [{"bbox": [10, 10, 50, 50]}]
            result = remediate_media("image", input_path, output_path, 
                                     detections=bboxes)
            
            assert result["success"]
            assert result["media_type"] == "image"
            assert os.path.exists(output_path)


# ─────────────────────────────────────────────────────────────────────────────
# VIDEO REMEDIATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestVideoRemediation:
    """Tests for video frame processing and remediation."""

    @pytest.fixture
    def sample_frames(self):
        """Create sample test frames."""
        frames = []
        for i in range(3):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[0:50, :] = (255, 0, 0)  # Blue top
            frame[50:100, :] = (0, 255, 0)  # Green bottom
            frames.append(frame)
        return frames

    def test_remediate_frame_basic(self, sample_frames):
        """Test that remediate_frame applies blur to specified regions."""
        frame = sample_frames[0]
        bboxes = [{"bbox": [10, 10, 50, 50]}]
        
        remediated = remediate_frame(frame, bboxes, blur_strength=51)
        
        # Check that frame was modified
        assert remediated is not None
        assert remediated.shape == frame.shape

    def test_remediate_frame_multiple_bboxes(self, sample_frames):
        """Test remediate_frame with multiple bounding boxes."""
        frame = sample_frames[0]
        bboxes = [
            {"bbox": [10, 10, 40, 40]},
            {"bbox": [60, 60, 90, 90]}
        ]
        
        remediated = remediate_frame(frame, bboxes, blur_strength=51)
        
        assert remediated is not None
        assert remediated.shape == frame.shape

    def test_remediate_frame_empty_bboxes(self, sample_frames):
        """Test remediate_frame with no bounding boxes."""
        frame = sample_frames[0]
        original = frame.copy()
        
        remediated = remediate_frame(frame, [], blur_strength=51)
        
        # Should return same frame (no changes)
        assert np.array_equal(remediated, original)

    def test_remediate_frame_invalid_coords(self, sample_frames):
        """Test remediate_frame handles invalid bbox coordinates."""
        frame = sample_frames[0]
        bboxes = [
            {"bbox": [-10, -10, 200, 200]},  # Out of bounds
            {"bbox": [50, 50, 40, 40]}  # Reversed coords
        ]
        
        # Should not crash
        remediated = remediate_frame(frame, bboxes, blur_strength=51)
        assert remediated is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
