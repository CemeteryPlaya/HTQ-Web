import logging

import bcrypt as bcrypt_lib
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

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


class User(AbstractBaseUser, PermissionsMixin):
    """Маппинг на существующую таблицу users (создана alembic'ом user-service).

    password хранится в колонке password_hash; исторические форматы:
    pbkdf2_sha256$... (родной Django) и raw bcrypt $2b$... (FastAPI-период).
    """

    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(max_length=254, unique=True)
    password = models.CharField(max_length=256, db_column="password_hash")

    first_name = models.CharField(max_length=150, blank=True, default="")
    last_name = models.CharField(max_length=150, blank=True, default="")
    patronymic = models.CharField(max_length=100, blank=True, default="")
    display_name = models.CharField(max_length=100, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    avatar_url = models.CharField(max_length=500, null=True, blank=True)
    settings = models.JSONField(default=dict)

    status = models.CharField(max_length=16, choices=UserStatus.choices,
                              default=UserStatus.PENDING)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)

    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()
    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "users"

    @property
    def is_active(self) -> bool:  # Django-контракт; колонки нет — есть status
        return self.status == UserStatus.ACTIVE

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
