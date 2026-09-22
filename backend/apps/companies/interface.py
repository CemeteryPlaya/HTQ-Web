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

from .models import Company, CompanyKind, CompanyMembership, CompanyModule, CompanyStatus

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
        "subdomain": company.subdomain,
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


def is_holding(slug: str) -> bool:
    """Компания этого слага — холдинг (владеет долями остальных).

    Предикат, а не выдача ``kind`` наружу: ``CompanyKind`` — деталь модели, и
    её протечка за границу аппки ломает то же правило, что прямой импорт
    чужих моделей. Ровно та же причина, по которой рядом отдаётся готовый
    ``is_active``, а не сырой ``status``.

    Неизвестный слаг — False, а не исключение: спрашивающий уже получил
    компанию из контекста запроса, и «такой компании нет» значит для него
    ровно «не холдинг».
    """
    company = get_company(slug)
    return bool(company and company["kind"] == CompanyKind.HOLDING)


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


def active_member_ids(slug: str) -> list[int]:
    """Id участников компании, чья УЧЁТКА действует, по возрастанию.

    Обратная сторона ``user_company_slugs``: там «в каких компаниях этот
    человек», здесь «какие люди в этой компании». Понадобилась переносу
    базовой роли (``manage.py access_backfill_basic``, блок I задача 4,
    раунд правок 1): ``apps.access`` обязана спросить состав компании у
    соседа, а не собирать его запросом к ``CompanyMembership``
    (``apps/core/tests/test_app_isolation.py``).

    Два условия, а не одно: строка ``CompanyMembership`` И действующая
    учётка. Членство переживает увольнение — строку никто не снимает
    автоматически, — и выдавать права по нему одному значило бы раздать их
    отключённым и неподтверждённым учёткам. Статус считает
    ``membership_service.list_memberships`` через ``apps.users.interface``:
    знания об enum статусов пользователя в этой аппке нет и не должно быть.

    БЕЗ кэша, в отличие от соседей выше: список запрашивают команды переноса
    и администрирования, а не горячий путь запроса, зато устаревший на пять
    секунд состав компании означал бы «кому-то не выдали права, и никто не
    заметил».
    """
    from apps.companies.services import membership_service

    company = Company.objects.filter(slug=slug).first()
    if company is None:
        return []
    return sorted(row["user_id"] for row in membership_service.list_memberships(company)
                  if row["is_active"])


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


def schema_exists(slug: str) -> bool:
    """Есть ли у компании ФИЗИЧЕСКАЯ схема.

    Строка реестра и схема — разные факты (осиротевшая строка после
    неудачного отката ``company_create``, см. CLAUDE.md). ``SET search_path``
    молча принимает несуществующую схему, и запросы уходят в ``public`` —
    поэтому команда, входящая в схему по slug, обязана спросить это до входа.
    """
    from apps.companies.services import schema_service
    return schema_service.schema_exists(slug)


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
