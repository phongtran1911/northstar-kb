from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from openai import APIError, OpenAI

from src.models import Article

CHUNKING_STRATEGY = {
    "type": "static",
    "static": {
        "max_chunk_size_tokens": 800,
        "chunk_overlap_tokens": 400,
    },
}


class VectorStore:
    """Upload Markdown articles to an OpenAI vector store."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("VECTOR_STORE_PATH", "data/vectors"))
        self.articles_dir = Path(os.getenv("DATA_DIR", "data/articles"))
        self.manifest_path = self.path / "manifest.json"

    def upsert(self, articles: list[Article]) -> int:
        del articles  # Files on disk are the source uploaded to OpenAI.
        client = OpenAI(api_key=_api_key())
        manifest = self._load_manifest()
        store_id = self._ensure_store(client, manifest)
        print(f"vector_store_id={store_id}")

        added = 0
        updated = 0
        skipped = 0
        embedded_ids: list[str] = []

        for path in sorted(self.articles_dir.glob("*.md")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            current = manifest["files"].get(path.name)
            if current and current.get("sha256") == digest:
                skipped += 1
                continue

            if current and current.get("file_id"):
                _delete_remote(client, store_id, current["file_id"])
                updated += 1
            else:
                added += 1

            file_id = _upload_file(client, path)
            embedded_ids.append(file_id)
            manifest["files"][path.name] = {"sha256": digest, "file_id": file_id}

        if embedded_ids:
            _attach(client, store_id, embedded_ids)
            self._save_manifest(manifest)

        chunk_count = _count_chunks(client, store_id, embedded_ids)
        print(f"added={added} updated={updated} skipped={skipped}")
        print(f"embedded files={added + updated} chunks={chunk_count}")
        return added + updated

    def _ensure_store(self, client: OpenAI, manifest: dict) -> str:
        store_id = os.getenv("VECTOR_STORE_ID") or manifest.get("vector_store_id")
        if store_id:
            manifest["vector_store_id"] = store_id
            self._save_manifest(manifest)
            return store_id

        store = client.vector_stores.create(name="northstar-kb")
        manifest["vector_store_id"] = store.id
        self._save_manifest(manifest)
        return store.id

    def _load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {"vector_store_id": "", "files": {}}
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        data.setdefault("files", {})
        return data

    def _save_manifest(self, manifest: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _api_key() -> str:
    key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Set API_KEY in the environment or .env")
    return key


def _upload_file(client: OpenAI, path: Path) -> str:
    with path.open("rb") as handle:
        uploaded = client.files.create(file=(path.name, handle), purpose="assistants")
    return uploaded.id


def _attach(client: OpenAI, store_id: str, file_ids: list[str]) -> None:
    batch = client.vector_stores.file_batches.create_and_poll(
        store_id,
        file_ids=file_ids,
        chunking_strategy=CHUNKING_STRATEGY,
    )
    if batch.status == "completed" and batch.file_counts.failed == 0:
        return

    errors: list[str] = []
    failed = client.vector_stores.file_batches.list_files(
        batch.id,
        vector_store_id=store_id,
        filter="failed",
    )
    for item in failed.data:
        errors.append(f"{item.id}: {item.last_error}")
    detail = "; ".join(errors) or batch.status
    raise RuntimeError(f"Vector store indexing failed: {detail}")


def _count_chunks(client: OpenAI, store_id: str, file_ids: list[str]) -> int:
    total = 0
    for file_id in file_ids:
        page = client.vector_stores.files.content(file_id, vector_store_id=store_id)
        for chunk_page in page.iter_pages():
            total += len(chunk_page.data)
    return total


def _delete_remote(client: OpenAI, store_id: str, file_id: str) -> None:
    try:
        client.vector_stores.files.delete(file_id, vector_store_id=store_id)
    except APIError:
        pass
    try:
        client.files.delete(file_id)
    except APIError:
        pass
