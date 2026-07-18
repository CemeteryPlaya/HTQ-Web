from sqladmin import ModelView
from app.models.domain import ChatUserReplica

class ChatUserReplicaAdmin(ModelView, model=ChatUserReplica):
    column_list = [ChatUserReplica.id, ChatUserReplica.username, ChatUserReplica.is_active]
    name = "User Replica"
