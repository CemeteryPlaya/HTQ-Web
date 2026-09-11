"""Публичный API аппки companies для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к реестру
компаний. Прямой импорт apps.companies.models из другой аппки запрещён и
ловится apps/core/tests/test_app_isolation.py.

Отличие от остальных interface-модулей платформы: здесь НЕ вызывается
require_service("companies"). Реестр компаний — фундамент, а не отключаемый
домен: без него нельзя ни зарезолвить поддомен, ни выбрать схему, поэтому
его выключение означало бы отказ всей платформы, а не деградацию одного
сервиса. Строка ServiceStatus для него всё равно заводится (KNOWN_SERVICES),
чтобы админка и метрики видели полный список.

Кэш на 5 секунд — тот же приём и тот же TTL, что у
apps.core.services.service_status: резолв дёргается на КАЖДЫЙ запрос
(CompanyContextMiddleware), и ходить за ним в БД каждый раз незачем.
Fail-open по кэшу: недоступный Redis не должен ронять весь трафик.

Пространства имён ключей кэша обязаны быть непересекающимися. Ключ
``company:slug:{slug}`` намеренно несёт статический сегмент "slug", а не
голый ``company:{slug}`` — иначе slug компании, совпавший со статическим
ключом другой функции (например, компания с slug "active"), читал бы или
писал чужую запись кэша и подменял бы там тип значения (dict вместо list
или наоборот) без единой ошибки. ``company:member:{user_id}`` и
``company:module:{slug}:{app_label}`` от такой коллизии защищены тем, что
двоеточие в slug запрещено валидатором (SLUG_VALIDATOR в models.py), а
user_id — int, а не пользовательская строка.
"""

from __future__ import annotations

import logging

from django.core.cache import cache

from .models import Company, CompanyMembership, CompanyModule, CompanyStatus

logger = logging.getLogger(__name__)

_CACHE_TTL = 5


def _cached(key: str, producer):
    try:
        hit = cache.get(key)
    except Exception:
        logger.warning("cache.get failed for key %s; falling back to DB", key,
                       exc_info=True)
        hit = None
    if hit is None:
        hit = producer()
        try:
            cache.set(key, hit, _CACHE_TTL)
        except Exception:
            logger.warning("cache.set failed for key %s; continuing without cache",
                           key, exc_info=True)
    return hit


def _serialize(company: Company) -> dict:
    return {
        "id": company.id,
        "slug": company.slug,
        "name": company.name,
        "kind": company.kind,
        "status": company.status,
        # Готовый предикат, чтобы потребителю не требовался импорт
        # CompanyStatus: enum — деталь модели, и её протечка за границу аппки
        # ломает то же правило, что и прямой импорт apps.<other>.models.
        "is_active": company.status == CompanyStatus.ACTIVE,
        "country": company.country,
        "parent_slug": company.parent.slug if company.parent_id else None,
    }


def get_company(slug: str) -> dict | None:
    """Строка реестра по slug, или None если такой компании нет."""
    def produce():
        company = Company.objects.select_related("parent").filter(slug=slug).first()
        return _serialize(company) if company else {}

    found = _cached(f"company:slug:{slug}", produce)
    return found or None


def active_company_slugs(*, fresh: bool = False) -> list[str]:
    """Slug'и всех действующих компаний, в алфавитном порядке.

    Порядок стабильный намеренно: этот список задаёт порядок веток в
    UNION ALL-представлениях схемы holding, и его дрожание заставляло бы
    представления пересоздаваться без причины.

    ``fresh=True`` обходит кэш. Нужен пересборке представлений: она идёт
    сразу после создания или архивации компании, и пятисекундный кэш отдал
    бы ей список БЕЗ этой компании — представление собралось бы без неё
    молча, без ошибки и без следа в логе.
    """
    def produce():
        return sorted(
            Company.objects.filter(status=CompanyStatus.ACTIVE)
            .values_list("slug", flat=True)
        )

    if fresh:
        return produce()
    return _cached("company:active", produce)


def user_company_slugs(user_id: int) -> list[str]:
    """Компании, в которых пользователь имеет право работать."""
    return _cached(
        f"company:member:{user_id}",
        lambda: sorted(
            CompanyMembership.objects.filter(user_id=user_id)
            .values_list("company__slug", flat=True)
        ),
    )


def user_may_enter_company(user_id: int, slug: str) -> bool:
    """Пускать ли пользователя в компанию ``slug``.

    Единственное место, где решается «пускать ли пользователя в компанию» —
    им пользуется ``apps.users.views._company_slug_for_token``, общий шаг
    ОБЕИХ дверей выдачи токена (``obtain_token`` — вход по паролю, и
    ``refresh_token`` — обмен refresh-cookie), и любой будущий вызывающий,
    которому нужен тот же вопрос. Сегодня ответ — голое членство
    (``CompanyMembership``); когда появятся роли (должность из HR как
    носитель прав) и механизм для не-сотрудников, это тело обрастёт
    условиями, а сигнатура и место вызова останутся прежними — вызывающему
    не придётся ничего переписывать.
    """
    return slug in user_company_slugs(user_id)


def default_company_slug(user_id: int) -> str | None:
    """Компания, куда пользователя пускать сразу после входа."""
    row = (CompanyMembership.objects
           .filter(user_id=user_id)
           .order_by("-is_default", "company__slug")
           .values_list("company__slug", flat=True)
           .first())
    return row


def module_enabled(slug: str, app_label: str) -> tuple[bool, str]:
    """Включён ли модуль у компании. Отсутствие строки означает «включён»."""
    def produce():
        row = (CompanyModule.objects
               .filter(company__slug=slug, app_label=app_label)
               .values("enabled", "message")
               .first())
        if row is None:
            return (True, "")
        return (row["enabled"], row["message"] if not row["enabled"] else "")

    return _cached(f"company:module:{slug}:{app_label}", produce)
