from sqladmin import ModelView
from app.models.domain import RoomParticipant

class RoomParticipantAdmin(ModelView, model=RoomParticipant):
    column_list = [RoomParticipant.room_id, RoomParticipant.user_id, RoomParticipant.role]
    name = "Room Participant"
