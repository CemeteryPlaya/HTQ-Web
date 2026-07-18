"""Messenger application layer."""

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.models.domain import ChatAttachment, Message, Room, RoomParticipant
from app.schemas.messenger import MessageCreate, RoomCreate
from app.services.attachment_storage import get_storage, write_attachment_metadata
from app.api.socket import sio


class MessengerService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_room(self, data: RoomCreate, creator_id: int) -> Room:
        """Create a room and add participants.

        Enforces "one direct chat per pair": a ``direct`` room must have
        exactly two distinct participants and may not coexist with another
        direct room between the same pair. If one already exists we return
        it instead of creating a duplicate — the caller gets a stable
        reference and the chat history stays in one place. Groups have no
        such constraint: any two users can sit in arbitrary many groups
        together.
        """
        participants = set(data.participant_ids)
        participants.add(creator_id)

        if data.room_type == "direct":
            if len(participants) != 2:
                raise ValueError("Direct chats must have exactly two participants")
            existing = await self._find_direct_room(participants)
            if existing is not None:
                # Reload with the relationship eager-loaded so callers can
                # serialise it the same way as a freshly created room.
                await self.session.refresh(existing, ["participants"])
                return existing

        room = Room(
            name=data.name,
            room_type=data.room_type,
            is_e2ee=data.is_e2ee,
            avatar_url=data.avatar_url,
        )
        self.session.add(room)
        await self.session.flush()

        for uid in participants:
            rp = RoomParticipant(room_id=room.id, user_id=uid, role="admin" if uid == creator_id else "member")
            self.session.add(rp)

        await self.session.commit()
        await self.session.refresh(room, ["participants"])
        return room

    async def _find_direct_room(self, user_ids: set[int]) -> Room | None:
        """Return the existing direct room between this exact pair, if any.

        Two-step lookup: pick rooms where both users appear, then verify
        that the room has *exactly* these two participants (rules out
        accidental matches against groups that happen to include them).
        """
        if len(user_ids) != 2:
            return None
        a, b = tuple(user_ids)
        rp_a = select(RoomParticipant.room_id).where(RoomParticipant.user_id == a)
        rp_b = select(RoomParticipant.room_id).where(RoomParticipant.user_id == b)
        candidate_ids = (await self.session.execute(
            select(Room.id)
            .where(
                Room.room_type == "direct",
                Room.id.in_(rp_a),
                Room.id.in_(rp_b),
            )
        )).scalars().all()
        if not candidate_ids:
            return None

        for rid in candidate_ids:
            count = (await self.session.execute(
                select(RoomParticipant.user_id).where(RoomParticipant.room_id == rid)
            )).scalars().all()
            if set(count) == user_ids:
                room = await self.session.get(Room, rid)
                if room is not None:
                    return room
        return None

    async def send_message(self, data: MessageCreate, sender_id: int) -> Message:
        """Save message to DB and emit via Socket.IO."""
        # 1. Verify user is in room
        rp = await self.session.get(RoomParticipant, (data.room_id, sender_id))
        if not rp:
            raise ValueError("Sender is not a participant in this room")
        room = await self.session.get(Room, data.room_id)
        if not room:
            raise ValueError("Room not found")

        # 2. Save message
        msg = Message(
            room_id=data.room_id,
            sender_id=sender_id,
            content=data.content,
            is_encrypted=data.is_encrypted,
            metadata_json=data.metadata_json,
        )
        self.session.add(msg)
        await self.session.flush()

        if data.attachment_ids:
            result = await self.session.execute(
                select(ChatAttachment).where(
                    ChatAttachment.id.in_(data.attachment_ids),
                    ChatAttachment.room_id == data.room_id,
                    ChatAttachment.uploaded_by == sender_id,
                )
            )
            attachments = list(result.scalars().all())
            found_ids = {attachment.id for attachment in attachments}
            if found_ids != set(data.attachment_ids):
                raise ValueError("One or more attachments are not available for this room")
            for attachment in attachments:
                if attachment.message_id is not None:
                    raise ValueError("One or more attachments are already attached to a message")
                attachment.message_id = msg.id
            await self.session.flush()
            storage = get_storage()
            for attachment in attachments:
                await self.session.refresh(attachment)
                await write_attachment_metadata(
                    storage=storage,
                    room_storage_key=room.storage_key,
                    attachment=attachment,
                )

        await self.session.commit()

        # 4. Fetch with relations to broadcast
        result = await self.session.execute(
            select(Message)
            .where(Message.id == msg.id)
            .options(selectinload(Message.sender), selectinload(Message.attachments))
        )
        full_msg = result.scalar_one()

        # 5. Broadcast to room via Socket.IO. Frontend listens for `message_new`
        # and `message_read` (see frontend/src/features/messenger/hooks/
        # useMessengerSocket.ts). Room name is `room:<id>` to namespace from
        # other socket.io rooms.
        payload = {
            "room_id": full_msg.room_id,
            "message": {
                "id": str(full_msg.id),
                "room_id": full_msg.room_id,
                "sender_id": full_msg.sender_id,
                "content": full_msg.content,
                "is_encrypted": full_msg.is_encrypted,
                "created_at": full_msg.created_at.isoformat() if full_msg.created_at else None,
                "attachments": [
                    {
                        "id": str(attachment.id),
                        "room_id": attachment.room_id,
                        "message_id": str(attachment.message_id) if attachment.message_id else None,
                        "file_metadata_id": str(attachment.file_metadata_id) if attachment.file_metadata_id else None,
                        "filename": attachment.filename,
                        "size": attachment.size,
                        "content_type": attachment.content_type,
                        "data_type": attachment.data_type,
                        "url": attachment.url,
                        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
                    }
                    for attachment in full_msg.attachments
                ],
            },
        }
        await sio.emit("message_new", payload, room=f"room:{data.room_id}")

        # Also emit to each participant's per-user channel so the sidebar
        # (last-message preview + unread badge) updates in real-time even
        # for participants whose socket hasn't joined ``room:<id>`` yet
        # (e.g., a brand-new chat created seconds ago).
        participant_rows = await self.session.execute(
            select(RoomParticipant.user_id).where(RoomParticipant.room_id == data.room_id)
        )
        participant_ids = [int(pid) for pid in participant_rows.scalars().all()]
        for participant_id in participant_ids:
            await sio.emit("message_new", payload, room=f"user:{participant_id}")

        # Publish a notify event so task-service can persist a Notification
        # row per recipient (everyone except the sender). The subscriber on
        # the other side is in services/task/app/workers/notify_sync.py.
        # Sender display name + a short text preview keep the notification
        # readable without forcing the subscriber to load the message body.
        sender_name = ""
        sender_avatar_url: str | None = None
        if full_msg.sender is not None:
            parts = [full_msg.sender.first_name or "", full_msg.sender.last_name or ""]
            sender_name = " ".join(p for p in parts if p).strip() or full_msg.sender.username
            # Read the avatar from messenger's own replica so task-service
            # doesn't need its own replica to be in sync — see migration
            # 011_notification_actor_avatar.
            sender_avatar_url = full_msg.sender.avatar_url
        room_title = room.name or ""
        preview = self._build_message_preview(full_msg)
        from app.services.notify_publish import (
            CHANNEL_NEW_CHAT_MESSAGE,
            publish_notify_event,
        )
        await publish_notify_event(
            CHANNEL_NEW_CHAT_MESSAGE,
            {
                "room_id": full_msg.room_id,
                "room_name": room_title,
                "room_type": room.room_type,
                "sender_id": full_msg.sender_id,
                "sender_name": sender_name,
                "sender_avatar_url": sender_avatar_url,
                "preview": preview,
                "recipient_ids": [pid for pid in participant_ids if pid != sender_id],
            },
        )

        return full_msg

    @staticmethod
    def _build_message_preview(msg: Message) -> str:
        """One-line summary used in the notification verb.

        Tries to pull the rendered text out of the message body; falls back
        to attachment metadata, then to the encrypted-marker / generic
        «новое сообщение». Capped at 100 chars so the notification verb
        column (200) stays safe.
        """
        if msg.is_encrypted:
            return "🔒 новое зашифрованное сообщение"
        body = (msg.content or "").strip()
        text = ""
        if body:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    text = (parsed.get("text") or parsed.get("body") or "").strip()
                    if not text and parsed.get("file_name"):
                        text = f"📎 {parsed['file_name']}"
                else:
                    text = body
            except Exception:  # noqa: BLE001
                text = body
        if not text and msg.attachments:
            first = msg.attachments[0]
            if first.data_type == "images":
                text = f"🖼 {first.filename or 'изображение'}"
            elif first.data_type == "audio":
                text = "🎤 голосовое сообщение"
            elif first.data_type == "video":
                text = f"🎬 {first.filename or 'видео'}"
            else:
                text = f"📎 {first.filename or 'файл'}"
        if not text:
            text = "новое сообщение"
        return text[:100]

    async def mark_read(self, room_id: int, message_id: uuid.UUID, user_id: int) -> None:
        """Mark a message as read for a user."""
        rp = await self.session.get(RoomParticipant, (room_id, user_id))
        if not rp:
            raise ValueError("User not in room")

        rp.last_read_message_id = message_id
        await self.session.commit()

        # Broadcast read receipt to other participants.
        await sio.emit(
            "message_read",
            {
                "room_id": room_id,
                "message_id": str(message_id),
                "reader_user_id": user_id,
            },
            room=f"room:{room_id}",
        )

    async def publish_typing(self, room_id: int, user_id: int, is_typing: bool = True) -> None:
        """Publish typing indicator to other participants."""
        await sio.emit(
            "user_typing",
            {"room_id": room_id, "user_id": user_id, "is_typing": is_typing},
            room=f"room:{room_id}",
        )
