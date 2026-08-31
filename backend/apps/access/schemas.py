"""Схемы контракта ``/api/access/v1`` — спека стадии 2, §4.

Контракт заморожен: менять эти классы можно только вслед за правкой документа,
иначе фронт и бэкенд разъедутся молча (риск 1 спеки).

``RootModel`` для тел-списков (§4.2, §4.4) — не украшение: ``api_view(body=)``
валидирует тело через ``model_validate_json``, а голый ``list`` моделью
pydantic не является.
"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

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
    """Правка роли: название, код или оба. Пустое тело — не ошибка, а no-op."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=64,
                             pattern=r"^[-a-zA-Z0-9_]+$")


# ── Глубина роли (§4.2) ───────────────────────────────────────────────────

class PermissionItem(BaseModel):
    """Глубина на одном узле реестра функций.

    Можно прислать либо ``preset`` (шесть названных уровней), либо ``flags``
    напрямую — своя комбинация тоже допустима. Прислать оба нельзя: тогда
    непонятно, что имелось в виду, а угадывать в правах нельзя.
    """

    node: str = Field(min_length=1, max_length=128)
    flags: list[str] | None = None
    preset: str | None = None

    @model_validator(mode="after")
    def one_of_two(self):
        if self.preset is None and self.flags is None:
            raise ValueError("нужен либо preset, либо flags")
        if self.preset is not None and self.flags is not None:
            raise ValueError("preset и flags вместе не принимаются")
        return self

    @field_validator("preset")
    @classmethod
    def preset_is_known(cls, value: str | None) -> str | None:
        from apps.access import depth

        if value is not None and value not in depth.PRESETS:
            raise ValueError(f"неизвестный уровень: {value}")
        return value

    @field_validator("flags")
    @classmethod
    def flags_are_known(cls, value: list[str] | None) -> list[str] | None:
        from apps.access import depth

        if value is None:
            return value
        bad = sorted(set(value) - set(depth.FLAGS))
        if bad:
            raise ValueError(f"неизвестные признаки глубины: {bad}")
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
    # Полная картина по узлам реестра: нужна интерфейсу, чтобы скрывать
    # отдельные поля и кнопки, а не только целые разделы. Уровни модулей выше —
    # проекция этой же карты, оставленная ради маршрутов и гейта.
    depth: dict[str, list[str]] = {}
    # Страницы, закрытые роли явным запретом. Список коротких путей маршрутов —
    # фронт сверяет его с route.path. Пусто у подавляющего большинства ролей:
    # страница — вето, а не разрешение.
    hidden_pages: list[str] = []
    subordinate_companies: list[str]
