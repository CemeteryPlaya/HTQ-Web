"""Aggregated models metadata — импортирует Base каждого сервиса.

Admin-service не владеет таблицами, но регистрирует ModelView из каждого
service.app.models, чтобы sqladmin мог сгенерировать CRUD-страницы.
"""
# Подход: реэкспорт моделей через PYTHONPATH

try:
    from user.app.models import User
except ImportError:
    User = None

try:
    from hr.app.models import Employee, Department, Position
except ImportError:
    Employee = Department = Position = None

try:
    from task.app.models.domain import Task, TaskComment, TaskAttachment, Label, ProjectVersion
except ImportError:
    Task = TaskComment = TaskAttachment = Label = ProjectVersion = None

try:
    from cms.app.models import News, ContactRequest
except ImportError:
    News = ContactRequest = None

try:
    from media.app.models.domain import FileMetadata
except ImportError:
    FileMetadata = None

try:
    from messenger.app.models.domain import Room, RoomParticipant, Message, ChatUserReplica, UserKey, MessageAttachment
except ImportError:
    Room = RoomParticipant = Message = ChatUserReplica = UserKey = MessageAttachment = None

try:
    from email.app.models.domain import EmailMessage, EmailRecipientStatus, EmailAttachment, EmailOAuthToken
except ImportError:
    EmailMessage = EmailRecipientStatus = EmailAttachment = EmailOAuthToken = None

__all__ = [
    "User", "Employee", "Department", "Position",
    "Task", "TaskComment", "TaskAttachment", "Label", "ProjectVersion",
    "News", "ContactRequest", "FileMetadata",
    "Room", "RoomParticipant", "Message",
    "ChatUserReplica", "UserKey", "MessageAttachment",
    "EmailMessage", "EmailRecipientStatus", "EmailAttachment", "EmailOAuthToken",
]
