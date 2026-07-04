"""Re-ingest every stored file through the current chunking + embedding config,
then reset chat-memory vectors so the indexer re-embeds them with the new model.

DESTRUCTIVE to Milvus rows (file chunks are deleted+rewritten per file by
process_document itself, called via process_file; chat vectors are purged).
Postgres only gets messages.indexed_at=NULL (plus a transient files.processing_status
flip back to UPLOADED for INDEXED files, described below). Run with the TARGET
stack's DB env, e.g.:
  DATABASE__NAME=talos_frontend DATABASE__PORT=5433 EMBEDDING_PROVIDER=huggingface \
  EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 CUDA_VISIBLE_DEVICES="" \
  PYTHONPATH=src uv run python scripts/reingest_workspace_files.py [--dry-run]

Quirk handled here: `processing.tasks.process_file` claims a file by atomically
flipping its status from UPLOADED/PROCESSING_FAILED -> PROCESSING; rowcount==0
short-circuits and SKIPS the file
for any other status, including INDEXED. Files being re-ingested here are
already INDEXED (they were processed once already), so calling process_file
on them directly would silently no-op. To make re-ingestion actually run, this
script flips each target file's processing_status back to UPLOADED (committed)
immediately before calling process_file for that file. process_document's own
delete_file_chunks() purge (src/processing/documents.py) keeps this idempotent
even if a file is re-ingested more than once.
"""
import argparse
import asyncio

# Register every SQLAlchemy mapper the File relationships reach (MessageFile ->
# Message etc.) — importing the model modules directly is the reliable recipe.
import auth.model  # noqa: F401
import chat.model  # noqa: F401
import notifications.model  # noqa: F401
import workspace.model  # noqa: F401
from sqlalchemy import select, text

from database import SessionLocal
from filesystem.model import File, FileStatus
from processing.tasks import process_file  # taskiq task: async def process_file(file_id: uuid.UUID)
from rag.vector_store import WORKSPACE_COLLECTION


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        files = db.scalars(
            select(File).where(
                File.deleted_at.is_(None),
                # PROCESSING_FAILED: resume an aborted run. UPLOADED: recover a
                # file left mid-flip if the script died between the UPLOADED
                # commit and process_file's terminal status write (also simply
                # processes never-processed files, which is process_file's job).
                File.processing_status.in_(
                    [FileStatus.INDEXED, FileStatus.PROCESSING_FAILED, FileStatus.UPLOADED]
                ),
            )
        ).all()
        print(f"{len(files)} files to re-ingest")
        if args.dry_run:
            for f in files:
                print(f"  would re-ingest {f.id} {f.filename}")
            return

        for f in files:
            print(f"re-ingesting {f.id} {f.filename} ...", flush=True)
            # process_file only claims files whose status is UPLOADED or
            # PROCESSING_FAILED (see module docstring above) — flip INDEXED
            # back to UPLOADED first so the claim succeeds instead of skipping.
            f.processing_status = FileStatus.UPLOADED
            db.commit()
            asyncio.run(process_file(f.id))

        # chat memory: purge segment vectors + reset indexed_at so the cron
        # indexer re-embeds with the new embedding model
        from pymilvus import MilvusClient
        from config import global_rag_config as cfg
        client = MilvusClient(uri=f"http://{cfg.milvus_host}:{cfg.milvus_port}")
        client.delete(collection_name=WORKSPACE_COLLECTION, filter='source == "chat"')
        n = db.execute(text("UPDATE messages SET indexed_at = NULL WHERE indexed_at IS NOT NULL")).rowcount
        db.commit()
        print(f"chat vectors purged; {n} messages queued for re-indexing")


if __name__ == "__main__":
    main()
