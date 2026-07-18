"""One-shot backfill: legacy local attachments → S3.

Before this branch the messenger wrote chat attachments to the local volume
mounted at ``settings.attachment_dir`` (Docker named volume
``messenger_attachments``). Files under
``chats/<room>/<data_type>/<id>_<filename>`` need to land at the same key
inside the ``htqweb-messenger`` S3 bucket; metadata snapshots
(``chats/<room>/metadata/*.json``) are regenerated from the database.

Run inside the messenger container::

    docker compose exec messenger-service \\
        python -m scripts.migrate_attachments_to_s3 [--dry-run] [--delete-local]

Idempotent — files already present in S3 (with same size) are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.db import async_session_factory
from app.models.domain import ChatAttachment, Room
from app.services.attachment_storage import write_attachment_metadata
from app.services.s3_storage import get_storage

log = get_logger(__name__)


async def _process_attachment(
    storage,
    attachment: ChatAttachment,
    room_storage_key,
    *,
    local_root: Path,
    dry_run: bool,
    delete_local: bool,
) -> str:
    """Push a single attachment to S3. Returns one of: uploaded / skipped / missing / error."""
    if not attachment.storage_path:
        return "missing"
    local_path = (local_root / attachment.storage_path).resolve()
    if not local_path.exists():
        return "missing"

    if await storage.exists(attachment.storage_path):
        try:
            remote_size = await storage.size(attachment.storage_path)
        except Exception:  # noqa: BLE001
            remote_size = None
        if remote_size == local_path.stat().st_size:
            return "skipped"

    if dry_run:
        return "would_upload"

    data = local_path.read_bytes()
    await storage.save(attachment.storage_path, data, content_type=attachment.content_type)
    if room_storage_key is not None:
        await write_attachment_metadata(
            storage=storage, room_storage_key=room_storage_key, attachment=attachment
        )
    if delete_local:
        try:
            local_path.unlink()
        except OSError as exc:
            log.warning("local_unlink_failed", path=str(local_path), error=str(exc))
    return "uploaded"


async def run(*, dry_run: bool, delete_local: bool) -> dict:
    storage = get_storage()
    local_root = Path(settings.attachment_dir)
    if not local_root.exists():
        log.info("local_root_missing", path=str(local_root))
        return {"uploaded": 0, "skipped": 0, "missing": 0, "would_upload": 0}

    counters = {"uploaded": 0, "skipped": 0, "missing": 0, "would_upload": 0, "error": 0}

    async with async_session_factory() as session:
        rooms = {r.id: r.storage_key for r in (await session.execute(select(Room))).scalars()}
        attachments = (await session.execute(select(ChatAttachment))).scalars().all()

        for attachment in attachments:
            try:
                outcome = await _process_attachment(
                    storage,
                    attachment,
                    rooms.get(attachment.room_id) if attachment.room_id else None,
                    local_root=local_root,
                    dry_run=dry_run,
                    delete_local=delete_local,
                )
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "attachment_migration_failed",
                    attachment_id=str(attachment.id),
                    error=str(exc),
                )
                counters["error"] += 1
                continue
            counters[outcome] = counters.get(outcome, 0) + 1
            log.info(
                "attachment_migration_step",
                attachment_id=str(attachment.id),
                storage_path=attachment.storage_path,
                outcome=outcome,
            )

    log.info("attachment_migration_done", **counters)
    return counters


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan only; don't upload anything")
    parser.add_argument(
        "--delete-local",
        action="store_true",
        help="Delete the local file after a successful upload (default: keep)",
    )
    args = parser.parse_args()
    counters = asyncio.run(run(dry_run=args.dry_run, delete_local=args.delete_local))
    print(counters)
    return 0 if counters.get("error", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
