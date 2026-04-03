import os
import json
import base64
import argparse
import mimetypes
import importlib
from typing import List, Tuple

import requests
from dotenv import load_dotenv


OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
MODEL_NAME = "qwen3-vl:235b-cloud"


def guess_mime_type(video_path: str) -> str:
	mime, _ = mimetypes.guess_type(video_path)
	return mime or "video/mp4"


def encode_video_base64(video_path: str) -> str:
	if not os.path.isfile(video_path):
		raise FileNotFoundError(f"Video file not found: {video_path}")
	with open(video_path, "rb") as f:
		return base64.b64encode(f.read()).decode("utf-8")


def build_payload(video_path: str, question: str, use_data_url: bool = False) -> dict:
	video_b64 = encode_video_base64(video_path)

	if use_data_url:
		mime = guess_mime_type(video_path)
		video_value = f"data:{mime};base64,{video_b64}"
	else:
		video_value = video_b64

	return {
		"model": MODEL_NAME,
		"messages": [
			{
				"role": "user",
				"content": [
					{"type": "video", "video": video_value},
					{"type": "text", "text": question},
				],
			}
		],
	}


def extract_video_frames_base64(video_path: str, max_frames: int) -> Tuple[List[str], List[float]]:
	try:
		cv2 = importlib.import_module("cv2")
	except ImportError as exc:
		raise RuntimeError(
			"opencv-python is required for local-video fallback. Install it with: pip install opencv-python"
		) from exc

	if max_frames < 1:
		raise ValueError("max_frames must be at least 1")

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

	if max_frames == 1:
		indices = [0]
	else:
		indices = [int(i * (total_frames - 1) / (max_frames - 1)) for i in range(max_frames)]

	images_b64: List[str] = []
	timestamps: List[float] = []

	for idx in indices:
		cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
		ok, frame = cap.read()
		if not ok:
			continue

		ok_jpg, buf = cv2.imencode(".jpg", frame)
		if not ok_jpg:
			continue

		images_b64.append(base64.b64encode(buf.tobytes()).decode("utf-8"))
		timestamps.append(idx / fps)

	cap.release()

	if not images_b64:
		raise ValueError("Could not extract any frames from video.")

	return images_b64, timestamps


def build_frames_payload(video_path: str, question: str, max_frames: int) -> dict:
	images_b64, timestamps = extract_video_frames_base64(video_path, max_frames=max_frames)

	timestamp_text = ", ".join(
		f"frame {i + 1}: {ts:.2f}s" for i, ts in enumerate(timestamps)
	)
	prompt = (
		f"{question}\n\n"
		"The original local video could not be uploaded directly, so you are given sampled frames "
		"from that video. Use visual evidence from these frames and the provided sample timestamps.\n"
		f"Sampled timestamps: {timestamp_text}."
	)

	return {
		"model": MODEL_NAME,
		"messages": [
			{
				"role": "user",
				"content": prompt,
				"images": images_b64,
			}
		],
	}


def parse_non_stream_response(data: dict) -> str:
	msg = data.get("message", {})
	content = msg.get("content")
	if isinstance(content, str) and content.strip():
		return content.strip()

	return json.dumps(data, indent=2, ensure_ascii=True)


def run_non_stream(api_key: str, payload: dict, timeout_seconds: int = 1200) -> str:
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}

	resp = requests.post(
		OLLAMA_CHAT_URL,
		headers=headers,
		json={**payload, "stream": False},
		timeout=timeout_seconds,
	)
	resp.raise_for_status()
	data = resp.json()
	return parse_non_stream_response(data)


def run_stream(api_key: str, payload: dict, timeout_seconds: int = 1200) -> None:
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}

	with requests.post(
		OLLAMA_CHAT_URL,
		headers=headers,
		json={**payload, "stream": True},
		stream=True,
		timeout=timeout_seconds,
	) as resp:
		resp.raise_for_status()

		for raw_line in resp.iter_lines(decode_unicode=True):
			if not raw_line:
				continue

			try:
				chunk = json.loads(raw_line)
			except json.JSONDecodeError:
				print(raw_line, end="", flush=True)
				continue

			text = chunk.get("message", {}).get("content", "")
			if text:
				print(text, end="", flush=True)

			if chunk.get("done") is True:
				break

	print()


def call_ollama_with_local_video(
	video_path: str,
	question: str,
	stream: bool,
	max_frames: int,
	timeout_seconds: int,
) -> None:
	load_dotenv()
	api_key = os.getenv("OLLAMA_API_KEY")
	if not api_key:
		raise EnvironmentError("OLLAMA_API_KEY is missing. Set it in env or .env file.")

	payload = build_payload(video_path, question, use_data_url=False)

	try:
		if stream:
			run_stream(api_key, payload, timeout_seconds=timeout_seconds)
		else:
			output = run_non_stream(api_key, payload, timeout_seconds=timeout_seconds)
			print(output)
		return
	except requests.HTTPError as e:
		status = e.response.status_code if e.response is not None else "unknown"
		should_retry_data_url = status in (400, 415, 422)
		if not should_retry_data_url:
			raise

		print("Raw base64 video rejected by API, retrying with data URL format...")

		payload_data_url = build_payload(video_path, question, use_data_url=True)
		try:
			if stream:
				run_stream(api_key, payload_data_url, timeout_seconds=timeout_seconds)
			else:
				output = run_non_stream(api_key, payload_data_url, timeout_seconds=timeout_seconds)
				print(output)
			return
		except requests.HTTPError as second_error:
			second_status = (
				second_error.response.status_code if second_error.response is not None else "unknown"
			)
			should_fallback_frames = second_status in (400, 415, 422)
			if not should_fallback_frames:
				raise

			print("Video payload rejected again, falling back to sampled local frames...")
			frames_payload = build_frames_payload(video_path, question, max_frames=max_frames)
			if stream:
				run_stream(api_key, frames_payload, timeout_seconds=timeout_seconds)
			else:
				output = run_non_stream(api_key, frames_payload, timeout_seconds=timeout_seconds)
				print(output)


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Call Ollama Cloud qwen3-vl:235b-cloud using a local video file."
	)
	parser.add_argument(
		"video_path",
		help="Local path to video file (example: D:/coding/Ablatix/backend/models/sample.mp4)",
	)
	parser.add_argument(
		"--question",
		default="Describe the video in detail? If any violations or non-safe content is detected, please explicitly point them with time stamps.",
		help="Question to ask about the video.",
	)
	parser.add_argument(
		"--stream",
		action="store_true",
		help="Enable streaming response.",
	)
	parser.add_argument(
		"--max-frames",
		type=int,
		default=8,
		help="Number of sampled frames when video payload is rejected (default: 8).",
	)
	parser.add_argument(
		"--timeout",
		type=int,
		default=1200,
		help="HTTP timeout in seconds (default: 1200).",
	)

	args = parser.parse_args()

	call_ollama_with_local_video(
		video_path=args.video_path,
		question=args.question,
		stream=args.stream,
		max_frames=args.max_frames,
		timeout_seconds=args.timeout,
	)


if __name__ == "__main__":
	main()
