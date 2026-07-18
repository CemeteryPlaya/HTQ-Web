from sqladmin import ModelView
from app.models.domain import Message

class MessageAdmin(ModelView, model=Message):
    column_list = [Message.id, Message.room_id, Message.sender_id, Message.is_encrypted, Message.created_at]
    name = "Message"
