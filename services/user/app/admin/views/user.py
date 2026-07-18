"""sqladmin views for User model.

The unified User model carries identity + profile + status. Pending registrations
are surfaced as a second view filtered to status=pending for admin convenience.
"""

from sqladmin import ModelView

from app.models.user import User, UserStatus


class UserAdmin(ModelView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"

    column_list = [
        User.id,
        User.username,
        User.email,
        User.display_name,
        User.status,
        User.is_staff,
        User.is_superuser,
        User.date_joined,
        User.last_login,
    ]
    column_searchable_list = [User.username, User.email, User.display_name]
    column_sortable_list = [User.id, User.username, User.email, User.date_joined, User.last_login]
    column_default_sort = [(User.date_joined, True)]

    form_excluded_columns = [User.password_hash, User.created_at, User.updated_at]


class PendingRegistrationAdmin(ModelView, model=User):
    name = "Pending registration"
    name_plural = "Pending registrations"
    icon = "fa-solid fa-user-clock"
    identity = "pending_registration"

    column_list = [
        User.id,
        User.email,
        User.username,
        User.display_name,
        User.date_joined,
    ]
    column_searchable_list = [User.email, User.username]
    column_default_sort = [(User.date_joined, False)]

    can_create = False
    can_edit = True
    can_delete = True

    def list_query(self, request):  # type: ignore[override]
        return super().list_query(request).filter(User.status == UserStatus.PENDING)
