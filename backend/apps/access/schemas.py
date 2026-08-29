"""Схемы контракта ``/api/access/v1`` — спека стадии 2, §4.

Контракт заморожен: менять эти классы можно только вслед за правкой документа,
иначе фронт и бэкенд разъедутся молча (риск 1 спеки).

``RootModel`` для тел-списков (§4.2, §4.4) — не украшение: ``api_view(body=)``
валидирует тело через ``model_validate_json``, а голый ``list`` моделью
pydantic не является.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from apps.access.models import Level, ScopeKind


# ── Роль (§4.1) ───────────────────────────────────────────────────────────

class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    is_system: bool


class RoleIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[-a-zA-Z0-9_]+$")
    title: str = Field(min_length=1, max_length=255)


class RolePatchIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)


# ── Права роли (§4.2) ─────────────────────────────────────────────────────

class PermissionItem(BaseModel):
    module: str = Field(min_length=1, max_length=32)
    level: Level

    @field_validator("module")
    @classmethod
    def module_is_known(cls, value: str) -> str:
        """Реестр модулей один — ``KNOWN_SERVICES``; своего справочника нет.

        Импорт внутри валидатора, а не на уровне модуля: схемы читаются при
        сборке URL-конфигурации, когда реестр аппок ещё может быть неполон.
        """
        from apps.core.models import KNOWN_SERVICES

        if value not in KNOWN_SERVICES:
            raise ValueError(f"неизвестный модуль: {value}")
        return value


PermissionsIn = RootModel[list[PermissionItem]]


# ── Роли должности (§4.3) ─────────────────────────────────────────────────

class PositionRoleRead(BaseModel):
    role_id: int
    code: str
    title: str


class PositionRolesIn(BaseModel):
    role_ids: list[int]


# ── Личные назначения (§4.4) ──────────────────────────────────────────────

class AssignmentItem(BaseModel):
    role_id: int
    scope_kind: ScopeKind
    scope_id: int | None = None


AssignmentsIn = RootModel[list[AssignmentItem]]


# ── Права текущего пользователя (§4.5) ────────────────────────────────────

class MeScope(BaseModel):
    kind: ScopeKind
    id: int | None


class MeEntry(BaseModel):
    level: Level
    scope: MeScope


class MeRead(BaseModel):
    company: str | None
    permissions: dict[str, MeEntry]
    subordinate_companies: list[str]
