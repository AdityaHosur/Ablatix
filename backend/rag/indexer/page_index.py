import json
import importlib
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


class PageIndexService:
    def __init__(
        self,
        api_key: Optional[str],
        cache_dir: str = ".pageindex_cache",
    ):
        if not api_key:
            raise ValueError("PAGEINDEX_API_KEY is required.")

        try:
            pageindex_module = importlib.import_module("pageindex")
            PageIndexClient = getattr(pageindex_module, "PageIndexClient")
        except Exception as exc:
            raise ImportError(
                "Missing dependency 'pageindex'. Install it in backend/requirements.txt."
            ) from exc

        self.client = PageIndexClient(api_key=api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.latest_doc_file = self.cache_dir / "latest_doc_id.txt"

    def submit_document(self, file_path: str, filename: Optional[str] = None) -> Dict[str, Any]:
        response = self.client.submit_document(file_path)
        doc_id = response.get("doc_id")
        if not doc_id:
            raise ValueError(f"Unexpected submit response: {response}")

        self.latest_doc_file.write_text(doc_id, encoding="utf-8")

        metadata = {
            "doc_id": doc_id,
            "filename": filename or os.path.basename(file_path),
            "submitted_at": int(time.time()),
        }
        self._write_json(self._meta_path(doc_id), metadata)

        ready = self.is_ready(doc_id)
        return {
            "doc_id": doc_id,
            "ready": ready,
            "metadata": metadata,
        }

    def get_latest_doc_id(self) -> Optional[str]:
        if not self.latest_doc_file.exists():
            return None
        value = self.latest_doc_file.read_text(encoding="utf-8").strip()
        return value or None

    def is_ready(self, doc_id: str) -> bool:
        return bool(self.client.is_retrieval_ready(doc_id))

    def get_tree(
        self,
        doc_id: str,
        node_summary: bool = True,
        wait_ready: bool = False,
        timeout_seconds: int = 120,
        poll_interval_seconds: int = 3,
    ) -> Dict[str, Any]:
        cached_tree = self._read_json(self._tree_path(doc_id))
        if cached_tree is not None:
            return cached_tree

        if wait_ready:
            start = time.time()
            while not self.is_ready(doc_id):
                if (time.time() - start) >= timeout_seconds:
                    raise TimeoutError(
                        f"Document {doc_id} is not ready after {timeout_seconds}s."
                    )
                time.sleep(poll_interval_seconds)
        elif not self.is_ready(doc_id):
            raise ValueError(
                f"Document {doc_id} is still processing. Retry shortly or use wait_ready=True."
            )

        response = self.client.get_tree(doc_id, node_summary=node_summary)
        tree = response.get("result") if isinstance(response, dict) else response
        if tree is None:
            raise ValueError(f"Unexpected get_tree response: {response}")

        self._write_json(self._tree_path(doc_id), tree)
        return tree

    def _tree_path(self, doc_id: str) -> Path:
        return self.cache_dir / f"tree_{doc_id}.json"

    def _meta_path(self, doc_id: str) -> Path:
        return self.cache_dir / f"meta_{doc_id}.json"

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def submit_and_track_scraper_artifact(
        self,
        file_path: str,
        platform: str,
        artifact_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Submit a scraper-generated PDF and track metadata.
        
        Args:
            file_path: Path to the PDF file
            platform: Platform name (e.g., 'youtube', 'instagram')
            artifact_metadata: Additional metadata (filename, counts, etc.)
        
        Returns:
            Dict with doc_id, platform, and tracking info
        """
        response = self.client.submit_document(file_path)
        doc_id = response.get("doc_id")
        if not doc_id:
            raise ValueError(f"Unexpected submit response: {response}")

        metadata = {
            "doc_id": doc_id,
            "platform": platform,
            "filename": artifact_metadata.get("filename"),
            "filepath": artifact_metadata.get("filepath"),
            "scraped_count": artifact_metadata.get("scraped_count"),
            "failed_urls": artifact_metadata.get("failed_urls", []),
            "total_chars": artifact_metadata.get("total_chars"),
            "submitted_at": int(time.time()),
        }
        self._write_json(
            self.cache_dir / f"scraper_meta_{platform}_{doc_id}.json",
            metadata,
        )

        ready = self.is_ready(doc_id)
        return {
            "doc_id": doc_id,
            "platform": platform,
            "ready": ready,
            "metadata": metadata,
        }

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
