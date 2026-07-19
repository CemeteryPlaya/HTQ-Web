from django.apps import AppConfig


class UsersConfig(AppConfig):
    # AutoField (not the project-wide default BigAutoField) — consistency
    # with apps.cms (Task 1.1 pilot decision); User.id itself is already an
    # explicit AutoField, this only affects Item's auto PK.
    default_auto_field = "django.db.models.AutoField"
    name = "apps.users"
