"""Контракт ``/api/companies/v1`` — план блока A, раздел «Контракт API».

Изменение формы — только вслед за правкой плана: фронт (``src/types/companies.ts``)
собран по этой же таблице.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.companies.models import CompanyKind


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    subdomain: str | None = None
    name: str
    kind: str
    status: str
    country: str
    parent_slug: str | None
    archived_at: datetime | None
    show_external_holders: bool


class CompanyTreeNode(BaseModel):
    slug: str
    name: str
    kind: str
    status: str
    country: str
    children: list[CompanyTreeNode] = Field(default_factory=list)


class MyCompany(BaseModel):
    slug: str
    subdomain: str | None = None
    name: str
    kind: str
    is_default: bool
    is_current: bool


class CompanyPatch(BaseModel):
    """Правка реестровых полей. Slug не правится: он — имя схемы и поддомен.

    ``parent_slug=None`` в теле — «без родителя»; отсутствие ключа — «не
    трогать». Разница читается через ``model_fields_set`` во вьюхе.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = None
    country: str | None = Field(default=None, max_length=2)
    parent_slug: str | None = None
    # Задача 7 блока C: `None` — «не трогать» (правит только PATCH, которого
    # само поле не прислало); значение задаётся ТОЛЬКО платформенным
    # администратором — тем же гейтом, что и остальные поля этой схемы.
    show_external_holders: bool | None = None
    # Блок I.2: короткий адрес компании. Пустая строка или null — «снять
    # псевдоним» (компания возвращается на адрес по слагу); отсутствие ключа —
    # «не трогать» (во вьюхе — ``UNSET``, как у ``parent_slug``). Правит только
    # платформенный администратор — тот же гейт, что у остальных полей схемы.
    # Формат, зарезервированные метки и столкновения со слагами проверяет
    # ``Company.full_clean()`` в сервисе (422 ``invalid``), не схема.
    subdomain: str | None = Field(default=None, max_length=32)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in CompanyKind.values:
            raise ValueError(f"kind должен быть одним из {list(CompanyKind.values)}")
        return value


class ModuleRead(BaseModel):
    app_label: str
    enabled: bool
    message: str
    is_core: bool


class ModulePatch(BaseModel):
    enabled: bool
    message: str | None = Field(default=None, max_length=200)


class MembershipRead(BaseModel):
    user_id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    is_default: bool


class ExternalHolderModule(BaseModel):
    module: str
    level: str


class ExternalHolderRead(BaseModel):
    """Строка ``GET companies/<slug>/external-holders`` — задача 7 блока C.

    ⚠️ Ровно четыре поля НАМЕРЕННО: это раскрытие данных сотрудника холдинга
    дочерней компании, и им управляет ``Company.show_external_holders``. Ни
    email, ни телефон, ни отдел сюда не попадают — apps.access.interface их
    и не отдаёт (см. докстринг ``apps.access.services.holders.external_holders``).
    """

    full_name: str
    home_company: str
    position: str
    modules: list[ExternalHolderModule]


class MembershipCreate(BaseModel):
    user_id: int = Field(gt=0)
    is_default: bool = False
