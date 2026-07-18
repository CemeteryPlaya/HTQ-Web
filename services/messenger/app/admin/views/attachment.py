from sqladmin import ModelView
from app.models.domain import ChatAttachment

class ChatAttachmentAdmin(ModelView, model=ChatAttachment):
    column_list = [
        ChatAttachment.id,
        ChatAttachment.room_id,
        ChatAttachment.message_id,
        ChatAttachment.filename,
        ChatAttachment.data_type,
        ChatAttachment.size,
    ]
    name = "Attachment"
