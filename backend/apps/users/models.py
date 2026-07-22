import logging

import bcrypt as bcrypt_lib
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Now

logger = logging.getLogger(__name__)


class UserStatus(models.TextChoices):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra):
        user = self.model(username=username,
                          email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("status", UserStatus.ACTIVE)
        return self.create_user(username, email, password, **extra)


class User(AbstractBaseUser):
    """Идиоматичная Django-модель пользователя, с нуля в схеме ``public``.

    Решение Р1 (заказчик): платформа использует собственные is_staff/
    is_superuser + RBAC из htqweb.authn, Django-группы/права не нужны — от
    ``PermissionsMixin`` отказались осознанно (см. has_perm/has_module_perms
    ниже — минимальная замена для нужд django.contrib.admin).

    password хранится в колонке password_hash; исторические форматы:
    pbkdf2_sha256$... (родной Django) и raw bcrypt $2b$... (FastAPI-период).
    """

    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(max_length=254, unique=True)
    password = models.CharField(max_length=256, db_column="password_hash")

    first_name = models.CharField(max_length=150, blank=True, default="", db_default="")
    last_name = models.CharField(max_length=150, blank=True, default="", db_default="")
    patronymic = models.CharField(max_length=100, blank=True, default="", db_default="")
    display_name = models.CharField(max_length=100, blank=True, default="", db_default="")
    bio = models.TextField(blank=True, default="", db_default="")
    phone = models.CharField(max_length=30, blank=True, default="", db_default="")
    avatar_url = models.CharField(max_length=500, null=True, blank=True)
    settings = models.JSONField(default=dict)

    status = models.CharField(max_length=16, choices=UserStatus.choices,
                              default=UserStatus.PENDING, db_default=UserStatus.PENDING,
                              db_index=True)
    is_staff = models.BooleanField(default=False, db_default=False)
    is_superuser = models.BooleanField(default=False, db_default=False)
    must_change_password = models.BooleanField(default=False, db_default=False)

    date_joined = models.DateTimeField(auto_now_add=True, db_default=Now())
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    objects = UserManager()
    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    @property
    def is_active(self) -> bool:  # Django-контракт; колонки нет — есть status
        return self.status == UserStatus.ACTIVE

    # Р1: без PermissionsMixin — django.contrib.admin всё равно опрашивает
    # has_perm/has_module_perms. Минимальная реализация: только суперюзер
    # проходит; staff без superuser прав в админке пока не получает вообще
    # (task 2.6 — гейт для админки — строится поверх этого).
    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_active and self.is_superuser

    def check_password(self, raw_password: str) -> bool:
        if self.password.startswith("$2"):  # raw bcrypt из FastAPI-периода
            try:
                ok = bcrypt_lib.checkpw(raw_password.encode(),
                                        self.password.encode())
            except ValueError:
                logger.warning("bcrypt.checkpw rejected stored hash for user_id=%s "
                               "(malformed hash, not a wrong password)", self.id)
                return False
            if ok:  # прозрачный апгрейд до PBKDF2, как делал auth_service.py
                self.set_password(raw_password)
                self.save(update_fields=["password"])
            return ok
        return super().check_password(raw_password)


class AuditLog(models.Model):
    """Аудит-журнал привилегированных действий identity-домена — та же форма,
    что у ``apps.cms.models.AuditLog`` / ``apps.media_files.models.AuditLog``
    (каждая аппка владеет своей конкретной моделью, а не общей — см. их
    докстрайны). ``users`` — самая аудируемая поверхность платформы (админ
    создаёт/правит/удаляет пользователей, сбрасывает пароли, модерирует
    регистрации), и до этой задачи (R3 плана устранения находок фаз 2-3) она
    не писала ничего, кроме structlog-строк, в отличие от cms/media — эта
    таблица и ``services.audit.record_action`` (см. этот модуль) закрывают
    разрыв. Никогда не пишет пароль/хэш в ``changes`` — см. вызывающих в
    ``views.py``.
    """

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_default=Now())


