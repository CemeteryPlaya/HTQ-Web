"""Жизненный цикл компании: заведение, правка, архив, восстановление.

Единственное место оркестрации — им пользуются и management-команды
(``company_create`` / ``company_archive`` / ``company_restore``), и HTTP-вьюхи
``apps.companies.views``. Раньше оркестрация жила в самих командах; вторая
копия во вьюхах разошлась бы с первой на первой же правке порядка шагов,
а порядок здесь — не деталь (см. докстринг ``provision_company``).

Ошибки типизированы и несут ``status``/``code``: команда переводит их в
``CommandError``, вьюха — в конверт ``{"detail": ...}``. Сообщения на
русском, потому что уходят пользователю как есть.

Гейт ``LastActiveCompany`` — требование режима перехода
(docs/plans/2026-09-14-group-structure-roadmap.md, §3 п.4): архив — только
чтение (docs/plans/2026-09-25-archive-read-only-spec.md), и без действующей
компании платформе негде писать — contracts/signoff живут только в схемах
компаний. Гейт стоит здесь, а не во вьюхе, чтобы действовать и для CLI.

``bankrupt_company`` (спека docs/plans/2026-09-26-company-bankruptcy-spec.md) —
банкротство с преемником: переносит ТОЛЬКО членства (каждый участник с
действующей учёткой получает членство в преемнике и базовую роль
``employee-basic`` через ``membership_service.grant_membership``), затем
архивирует компанию. Карточки ``hr``, техника и договоры преемнику не
передаются — они остаются в архиве закрытой компании. Идемпотентно для той
же пары «банкрот → преемник»; ``restore_company`` снимает связь с
преемником, не отзывая уже выданные членства.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import ProgrammingError, transaction
from django.utils import timezone

from apps.companies.models import Company, CompanyKind, CompanyMembership, CompanyStatus
from apps.companies.services import holding_views, membership_service, migration_service, schema_service
from apps.companies.services.migration_service import _cleanup

logger = logging.getLogger(__name__)

#: Маркер «аргумент не передан» для необязательных полей правки: ``None`` у
#: ``parent_slug`` — законное значение («без родителя»), и путать его с
#: «не трогать» нельзя.
UNSET = object()

_HOLDING_STALE = (
    "{what}, но сводки холдинга собрать нельзя: состав столбцов разошёлся с "
    "другой компанией, отставшей по миграциям. Представления оставлены "
    "снесёнными: читатель получит громкую ошибку вместо цифр по "
    "полумигрированной группе. Доведите остальные компании — "
    "`manage.py migrate_companies` без фильтров. Причина: {exc}"
)


class LifecycleError(Exception):
    status = 400
    code = "lifecycle"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class CompanyExists(LifecycleError):
    status = 409
    code = "exists"


class CompanyNotFound(LifecycleError):
    status = 404
    code = "not_found"


class CompanyInvalid(LifecycleError):
    status = 422
    code = "invalid"


class ParentNotFound(LifecycleError):
    status = 422
    code = "parent_not_found"


class ParentCycle(LifecycleError):
    status = 422
    code = "parent_cycle"


class LastActiveCompany(LifecycleError):
    status = 409
    code = "last_active"


class SuccessorInvalid(LifecycleError):
    status = 422
    code = "successor_invalid"


class SuccessorConflict(LifecycleError):
    status = 409
    code = "successor_conflict"


class HoldingViewsStale(LifecycleError):
    status = 409
    code = "holding_stale"


def get_company_or_raise(slug: str) -> Company:
    company = Company.objects.select_related("parent").filter(slug=slug).first()
    if company is None:
        raise CompanyNotFound(f"Компания {slug} не найдена.")
    return company


def _resolve_parent(parent_slug: str | None) -> Company | None:
    if parent_slug is None:
        return None
    parent = Company.objects.filter(slug=parent_slug).first()
    if parent is None:
        raise ParentNotFound(f"Вышестоящая компания {parent_slug} не найдена.")
    return parent


def _assert_no_cycle(company: Company, parent: Company | None) -> None:
    """Дерево владения обязано оставаться деревом.

    ``PROTECT`` на self-FK защищает только от удаления; правка ``parent``
    может замкнуть цикл, и ``companies_below`` в apps.access тогда ходила бы
    по кругу (у неё есть своя защита, но она — последняя линия, не первая).
    """
    cursor = parent
    seen: set[int] = set()
    while cursor is not None and cursor.id not in seen:
        if cursor.id == company.id:
            raise ParentCycle(
                f"Компания {company.slug} не может подчиняться {parent.slug}: "
                "получился бы цикл в дереве владения."
            )
        seen.add(cursor.id)
        cursor = cursor.parent


def _full_clean(company: Company) -> None:
    try:
        # full_clean(), а не save(): objects.create() валидаторы (в том числе
        # SLUG_VALIDATOR и choices у kind) не вызывает вовсе.
        company.full_clean()
    except ValidationError as exc:
        raise CompanyInvalid("; ".join(
            f"{field}: {' '.join(msgs)}" for field, msgs in exc.message_dict.items()
        )) from exc


def _rebuild_or_raise(what: str) -> None:
    try:
        holding_views.rebuild_holding_views()
    except ProgrammingError as exc:
        raise HoldingViewsStale(_HOLDING_STALE.format(what=what, exc=exc)) from exc


def provision_company(*, slug: str, name: str, kind: str,
                      parent_slug: str | None = None, country: str = "",
                      subdomain: str | None = None) -> Company:
    """Строка реестра + схема + миграции + сводки холдинга.

    Порядок шагов — единственный безопасный (подробно — докстринг
    ``management/commands/company_create.py``): валидация до разрушающих
    действий; строка и ``CREATE SCHEMA`` одной транзакцией; ``drop_holding_views``
    и ``migrate_company`` вне транзакции; ``rebuild_holding_views`` в конце.
    Откат — три НЕЗАВИСИМЫХ шага через ``_cleanup``.

    ⚠️ Долгая операция (миграции четырёх аппок, ~минута): из HTTP-запроса
    под ``gunicorn --timeout 60`` не вызывать — воркер будет убит посреди
    DDL. Поэтому в блоке A заведение остаётся за CLI.
    """
    if Company.objects.filter(slug=slug).exists():
        raise CompanyExists(f"Компания {slug} уже существует.")
    parent = _resolve_parent(parent_slug)
    company = Company(slug=slug, name=name, kind=kind, parent=parent,
                      country=country, subdomain=subdomain or None)
    _full_clean(company)

    with transaction.atomic():
        company.save()
        schema_service.create_schema(slug)

    try:
        holding_views.drop_holding_views()
        migration_service.migrate_company(slug)
    except Exception:
        _cleanup("снос схемы после отката",
                 lambda: schema_service.drop_schema(slug))
        _cleanup("удаление строки реестра после отката", company.delete)
        _cleanup("пересборка сводок холдинга после отката",
                 holding_views.rebuild_holding_views)
        raise

    _rebuild_or_raise(f"Компания {slug} создана и мигрирована")
    return company


def update_company(slug: str, *, name: str | None = None, kind: str | None = None,
                   country: str | None = None, parent_slug=UNSET,
                   show_external_holders: bool | None = None,
                   subdomain=UNSET) -> Company:
    """Правка реестровых полей. Slug не правится никогда: он — имя схемы и поддомен.

    ``show_external_holders`` (задача 7 блока C) не нуждается в ``UNSET``, в
    отличие от ``parent_slug``: это простой булев переключатель, и у него нет
    третьего, «явно пустого» значения — ``None`` однозначно значит «не
    трогать».
    """
    company = get_company_or_raise(slug)
    if name is not None:
        company.name = name
    if kind is not None:
        if kind not in CompanyKind.values:
            raise CompanyInvalid(f"kind: {kind!r} не входит в {list(CompanyKind.values)}")
        company.kind = kind
    if country is not None:
        company.country = country
    if parent_slug is not UNSET:
        parent = _resolve_parent(parent_slug)
        _assert_no_cycle(company, parent)
        company.parent = parent
    if show_external_holders is not None:
        company.show_external_holders = show_external_holders
    if subdomain is not UNSET:
        # Пустая строка — «снять псевдоним», компания возвращается на слаг;
        # UNSET — «не трогать». Как у parent_slug: у поля есть третье,
        # явно пустое значение, и None его не выражает.
        company.subdomain = (subdomain or None)
    _full_clean(company)
    company.save()
    return company


def archive_company(slug: str) -> tuple[Company, bool]:
    """Перевести в архив. Идемпотентно: архивная компания — ``(company, False)``."""
    company = get_company_or_raise(slug)
    if company.status == CompanyStatus.ARCHIVED:
        return company, False
    others = Company.objects.filter(status=CompanyStatus.ACTIVE).exclude(pk=company.pk)
    if not others.exists():
        raise LastActiveCompany(
            f"{slug} — единственная действующая компания: в архиве она "
            "закрылась бы на запись, и платформе негде было бы работать — "
            "contracts и signoff живут только в схемах компаний."
        )
    company.status = CompanyStatus.ARCHIVED
    company.archived_at = timezone.now()
    company.save(update_fields=["status", "archived_at", "updated_at"])
    _rebuild_or_raise(f"Компания {slug} переведена в архив")
    return company, True


def restore_company(slug: str) -> tuple[Company, bool]:
    """Вернуть из архива. Идемпотентно: действующая компания — ``(company, False)``."""
    company = get_company_or_raise(slug)
    if company.status == CompanyStatus.ACTIVE:
        return company, False
    company.status = CompanyStatus.ACTIVE
    company.archived_at = None
    # Восстановленная компания живёт сама по себе — связь с преемником
    # теряет смысл; выданные преемнику членства не отзываются (спека §3).
    company.successor = None
    company.save(update_fields=["status", "archived_at", "successor", "updated_at"])
    _rebuild_or_raise(f"Компания {slug} возвращена из архива")
    return company, True


@dataclass(frozen=True)
class BankruptcyResult:
    company: Company
    successor: Company
    members_total: int
    members_granted: int
    members_already: int
    archived: bool
    dry_run: bool


def bankrupt_company(slug: str, successor_slug: str, *,
                     dry_run: bool = False) -> BankruptcyResult:
    """Закрыть компанию с преемником (спека docs/plans/2026-09-26-company-bankruptcy-spec.md).

    Переносится только членство (решение заказчика 26.09): каждый участник с
    ДЕЙСТВУЮЩЕЙ учёткой получает членство в преемнике через
    ``grant_membership`` — единственную точку логики членства, она же выдаёт
    новому членству ``employee-basic``. Карточки ``hr``, техника и договоры
    остаются в архиве банкрота. Флаг «по умолчанию» переезжает: иначе после
    входа человека вело бы по алфавиту.

    Идемпотентно для той же пары: повтор довыдаёт недостающие членства (сбой
    на середине не требует ручной уборки). Уже архивную компанию без
    преемника закрыть можно — архив мог случиться раньше решения о
    преемнике; с ДРУГИМ преемником — ``SuccessorConflict``.
    """
    from apps.companies.interface import active_member_ids

    company = get_company_or_raise(slug)
    successor = get_company_or_raise(successor_slug)
    if successor.pk == company.pk:
        raise SuccessorInvalid("Компания не может быть собственным преемником")
    if successor.status != CompanyStatus.ACTIVE:
        raise SuccessorInvalid("Преемник должен быть действующей компанией")
    if company.successor_id is not None and company.successor_id != successor.pk:
        raise SuccessorConflict(
            f"У компании {slug} уже есть преемник {company.successor.slug}")

    member_ids = active_member_ids(slug)
    already = set(CompanyMembership.objects
                  .filter(company=successor, user_id__in=member_ids)
                  .values_list("user_id", flat=True))
    to_grant = [uid for uid in member_ids if uid not in already]

    if dry_run:
        return BankruptcyResult(company, successor, len(member_ids), len(to_grant),
                                len(already), archived=False, dry_run=True)

    defaults = set(CompanyMembership.objects
                   .filter(company=company, user_id__in=to_grant, is_default=True)
                   .values_list("user_id", flat=True))
    with transaction.atomic():
        # Проверка преемника выше шла по строке без блокировки: два
        # суперпользователя, закрывающие одну компанию с разными преемниками,
        # прошли бы её оба и выдали членства и в Y, и в Z, а ``successor``
        # достался бы последнему — выданные доступы не отзываются. Строка
        # компании блокируется до выдачи, и проверка повторяется по ней:
        # второй вызов ждёт первый и видит уже выставленного преемника.
        # Первую проверку не убираем — она нужна ``dry_run`` и отказывает
        # сразу, не считая участников.
        company = Company.objects.select_for_update().get(pk=company.pk)
        if company.successor_id is not None and company.successor_id != successor.pk:
            raise SuccessorConflict(
                f"У компании {slug} уже есть преемник {company.successor.slug}")
        for uid in to_grant:
            membership_service.grant_membership(successor, uid,
                                                is_default=uid in defaults)
        if company.successor_id != successor.pk:
            company.successor = successor
            company.save(update_fields=["successor", "updated_at"])
    # Архив — после переноса и вне транзакции переноса: он пересобирает
    # сводки холдинга (DDL), и его сбой не должен откатывать уже выданные
    # доступы. Повтор той же пары довыдаст недостающие членства, но
    # пересборку сводок НЕ повторит: если упала именно она
    # (HoldingViewsStale), статус ARCHIVED уже сохранён, и archive_company
    # на повторе вернётся сразу — сводки после такого сбоя доводит
    # ``manage.py migrate_companies``. Гейт LastActiveCompany не сработает:
    # преемник действующий.
    company, archived = archive_company(slug)
    logger.info("company_bankrupt slug=%s successor=%s granted=%d already=%d",
                slug, successor.slug, len(to_grant), len(already))
    return BankruptcyResult(company, successor, len(member_ids), len(to_grant),
                            len(already), archived=archived, dry_run=False)
