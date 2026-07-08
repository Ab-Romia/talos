"""Offloaded Slack agent turn.

The events webhook must return within Slack's 3-second window, so it only enqueues
this task. Here on the worker we run the (slow) embedded agent and post the reply.
"""
import hashlib
import os
import re
import tempfile
import uuid

from broker import broker
from config import cfg
from integrations import agent
from integrations.slack import service
from utils.logger import get_logger

logger = get_logger(__name__)

_MENTION = re.compile(r"<@[^>]+>\s*")
_HISTORY_LIMIT = 12  # prior turns fed to the agent
_HISTORY_MSG_CHARS = 2000


async def _thread_history(
    channel: str, thread_ts: str | None, msg_ts: str | None
) -> list[tuple[str, str]]:
    """Prior thread messages as (role, content) pairs, oldest first.

    The current message (matched by ts) is excluded — it's passed to the
    agent separately as the live turn.
    """
    if not thread_ts:
        return []

    history: list[tuple[str, str]] = []
    for msg in await service.fetch_thread(channel, thread_ts):
        if msg_ts is not None and msg.get("ts") == msg_ts:
            continue
        content = _MENTION.sub("", msg.get("text", "")).strip()
        if not content:
            continue
        role = "assistant" if msg.get("bot_id") else "user"
        history.append((role, content[:_HISTORY_MSG_CHARS]))
    return history[-_HISTORY_LIMIT:]


@broker.task()
async def run_agent_turn(
    slack_user: str,
    channel: str,
    text: str,
    thread_ts: str | None = None,
    msg_ts: str | None = None,
) -> None:
    """Run the embedded agent for one Slack message and reply in-thread."""
    talos_user = service.resolve_talos_user(slack_user)
    logger.info("Slack turn", slack_user=slack_user, talos_user=talos_user, channel=channel)

    history = await _thread_history(channel, thread_ts, msg_ts)

    try:
        reply = await agent.answer(text, history=history)
    except Exception:
        logger.exception("Agent turn failed")
        reply = "Sorry — something went wrong while handling that."

    # The agent may return an empty final message after a tool-only turn
    # (e.g. it posted into the Talos channel); Slack rejects empty text.
    if not reply or not reply.strip():
        reply = "Done."

    await service.post_message(channel, reply, thread_ts=thread_ts)


@broker.task()
async def ingest_slack_file(
    file_id: str,
    filename: str,
    mimetype: str,
    size: int,
    url: str,
    channel: str,
    thread_ts: str | None = None,
) -> None:
    """Download a file shared with the Slack bot, store it, and index it for RAG.

    Bytes go to MinIO, a ``File`` row is recorded against the bot's default
    workspace/channel, and the text is chunked + embedded into Milvus. Every
    terminal outcome is confirmed in-thread.
    """

    async def reply(text: str) -> None:
        await service.post_message(channel, text, thread_ts=thread_ts)

    files_cfg = cfg().files
    bot = cfg().bot

    # ── Cheap guards before touching the network ──
    if mimetype not in files_cfg.document_mime_types:
        await reply(f"Sorry, I can only ingest documents (pdf, docx, txt, md) — skipped {filename}.")
        return
    if size > files_cfg.max_size:
        await reply(
            f"Sorry, {filename} is too large to ingest "
            f"(max {files_cfg.max_size // (1024 * 1024)} MiB)."
        )
        return
    if not url:
        await reply(f"Sorry — I couldn't access {filename} on Slack.")
        return

    try:
        data = await service.download_file(url)
    except Exception:
        logger.exception("Slack file download failed", filename=filename, slack_file_id=file_id)
        await reply(f"Sorry — failed to download {filename} from Slack.")
        return

    # Re-sniff the MIME type from the actual bytes; Slack's metadata is advisory.
    import magic

    detected = magic.from_buffer(data, mime=True)
    if detected != mimetype and detected not in files_cfg.document_mime_types:
        await reply(f"Sorry, {filename} doesn't look like a document I can ingest — skipped.")
        return
    content_type = detected if detected in files_cfg.document_mime_types else mimetype

    sha = hashlib.sha256(data).hexdigest()

    from sqlalchemy import select

    from filesystem.model import File, FileStatus
    from model import SessionLocal

    workspace_id = uuid.UUID(bot.default_workspace_id)
    channel_id = uuid.UUID(bot.default_channel_id)
    file_pk: uuid.UUID | None = None

    try:
        with SessionLocal() as db:
            # ── Dedupe on content hash within the bot's workspace ──
            existing = db.execute(
                select(File).where(
                    File.sha256checksum == sha,
                    File.workspace_id == workspace_id,
                    File.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is not None:
                await reply(f"{filename} is already ingested.")
                return

            # ── Store bytes in MinIO, scoped to the bot's workspace/channel ──
            from filesystem.storage.minio import MinIOFileSystem

            fs = MinIOFileSystem(
                cfg().minio, workspace_id=workspace_id, channel_id=channel_id
            )
            path = f"slack/{filename}"
            await fs._pipe_file(path, data)
            uri = fs.unstrip_protocol(path)

            # ── Record the File row ──
            file_row = File(
                workspace_id=workspace_id,
                channel_id=channel_id,
                uploader_id=uuid.UUID(bot.bot_user_id),
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                sha256checksum=sha,
                processing_status=FileStatus.UPLOADED,
                uri=uri,
            )
            db.add(file_row)
            db.commit()
            file_pk = file_row.id

            # ── Extract text ──
            ext = os.path.splitext(filename)[1].lower()
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                from processing.documents import _extract_text

                elements = _extract_text(tmp_path, content_type)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            from langchain_core.documents import Document

            docs = [
                Document(
                    page_content=el_text,
                    metadata={
                        "workspace_id": str(workspace_id),
                        "file_id": str(file_pk),
                        "filename": filename,
                        "page_number": el_meta.get("page_number", 0),
                    },
                )
                for el_text, el_meta in elements
                if el_text and el_text.strip()
            ]

            if not docs:
                file_row.processing_status = FileStatus.PROCESSED
                db.commit()
                await reply(f"No text could be extracted from {filename}.")
                return

            # ── Chunk ──
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            from config import global_rag_config

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=global_rag_config.chunk_size,
                chunk_overlap=global_rag_config.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            chunks = splitter.split_documents(docs)
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_index"] = i

            # ── Embed into Milvus (idempotent: clear prior chunks first) ──
            from rag.vector_store import delete_file_chunks

            delete_file_chunks(str(file_pk), workspace_id=str(workspace_id))

            from rag.ingestion import ingest_file_chunks

            ingest_file_chunks(chunks, str(workspace_id), str(file_pk))

            file_row.processing_status = FileStatus.INDEXED
            db.commit()

            logger.info(
                "Slack file ingested",
                filename=filename,
                file_db_id=str(file_pk),
                num_chunks=len(chunks),
            )
            await reply(
                f"Ingested {filename} — {len(chunks)} chunks. You can now ask me about it."
            )
    except Exception:
        logger.exception("Slack file ingestion failed", filename=filename)
        if file_pk is not None:
            try:
                with SessionLocal() as db:
                    row = db.get(File, file_pk)
                    if row is not None:
                        row.processing_status = FileStatus.PROCESSING_FAILED
                        db.commit()
            except Exception:
                logger.exception("Could not mark file as failed", filename=filename)
        await reply(f"Sorry — failed to ingest {filename}.")
