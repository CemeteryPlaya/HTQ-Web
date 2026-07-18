from sqladmin import ModelView
from app.models.domain import UserKey

class UserKeyAdmin(ModelView, model=UserKey):
    column_list = [UserKey.user_id, UserKey.device_id]
    name = "User Key"
