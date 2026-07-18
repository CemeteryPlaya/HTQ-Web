from sqladmin import ModelView
from app.models.domain import Room

class RoomAdmin(ModelView, model=Room):
    column_list = [Room.id, Room.name, Room.room_type, Room.is_e2ee]
    name = "Room"
