"""Блоки главной страницы — чтение и правка.

Публичное чтение отдаёт УЖЕ локализованные строки: лендинг не должен знать про
существование второго языка, иначе выбор перевода размазался бы по девяти
React-компонентам. Редакторское чтение, наоборот, отдаёт оба языка сразу —
форме нужны обе вкладки, и второй запрос за переводом был бы лишним.
"""
from __future__ import annotations

from django.db import transaction

from apps.cms.models import HomeSection, HomeSectionItem

# Язык по умолчанию. Русский — не «первый попавшийся»: именно он обязателен к
# заполнению, и именно на него откатывается пустой перевод (см. `_pick`).
DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "en")


def normalize_lang(raw: str | None) -> str:
    """``?lang=en-US`` → ``en``; неизвестное → русский.

    Берём только первые две буквы: i18next присылает и `en`, и `en-US`, а
    заводить колонку под каждый регион никто не собирается.
    """
    code = (raw or "").strip().lower()[:2]
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def _pick(obj, field: str, lang: str) -> str:
    """Значение поля на нужном языке с откатом на русский.

    Откат — не перестраховка, а рабочий сценарий: перевод заполняют позже
    русского текста, и до этого момента английская версия страницы должна
    показывать русскую строку, а не пустое место в вёрстке.
    """
    value = (getattr(obj, f"{field}_{lang}", "") or "").strip()
    if value:
        return value
    return (getattr(obj, f"{field}_{DEFAULT_LANG}", "") or "").strip()


def public_sections(lang: str) -> list[dict]:
    """Видимые секции с видимыми элементами, локализованные под ``lang``."""
    lang = normalize_lang(lang)
    sections = (
        HomeSection.objects.filter(is_visible=True)
        .prefetch_related("items")
        .order_by("order", "id")
    )
    out: list[dict] = []
    for s in sections:
        out.append({
            "id": s.id,
            "key": s.key,
            "layout": s.layout,
            "is_system": s.is_system,
            "tag": _pick(s, "tag", lang),
            "title": _pick(s, "title", lang),
            "description": _pick(s, "description", lang),
            # Фильтруем в Python, а не вторым запросом: элементы уже подтянуты
            # prefetch_related, и .filter() на связи выбросил бы кэш и сделал
            # по запросу на секцию.
            "items": [
                {
                    "id": i.id,
                    "title": _pick(i, "title", lang),
                    "description": _pick(i, "description", lang),
                    "value": i.value,
                    "icon": i.icon,
                    "image": i.image,
                    "link": i.link,
                }
                for i in s.items.all() if i.is_visible
            ],
        })
    return out


def admin_sections() -> list[dict]:
    """Все секции (включая скрытые) с обоими языками — для формы управления."""
    sections = HomeSection.objects.prefetch_related("items").order_by("order", "id")
    return [_serialize_section_admin(s) for s in sections]


def _serialize_item_admin(i: HomeSectionItem) -> dict:
    return {
        "id": i.id,
        "title_ru": i.title_ru, "title_en": i.title_en,
        "description_ru": i.description_ru, "description_en": i.description_en,
        "value": i.value, "icon": i.icon, "image": i.image, "link": i.link,
        "is_visible": i.is_visible, "order": i.order,
    }


def _serialize_section_admin(s: HomeSection) -> dict:
    return {
        "id": s.id, "key": s.key, "layout": s.layout, "is_system": s.is_system,
        "tag_ru": s.tag_ru, "tag_en": s.tag_en,
        "title_ru": s.title_ru, "title_en": s.title_en,
        "description_ru": s.description_ru, "description_en": s.description_en,
        "is_visible": s.is_visible, "order": s.order,
        "items": [_serialize_item_admin(i) for i in s.items.all()],
    }


class SectionNotFound(Exception):
    pass


class ItemNotFound(Exception):
    pass


def get_section(section_id: int) -> HomeSection:
    section = HomeSection.objects.filter(pk=section_id).first()
    if section is None:
        raise SectionNotFound()
    return section


def update_section(section_id: int, patch: dict, *, user_id: int | None) -> dict:
    section = get_section(section_id)
    for field, value in patch.items():
        setattr(section, field, value)
    section.updated_by = user_id
    section.save()
    section.refresh_from_db()
    return _serialize_section_admin(section)


def create_item(section_id: int, data: dict) -> dict:
    section = get_section(section_id)
    # Ставим в конец с запасом по шагу — так же, как сеет миграция, чтобы
    # ручная вставка не ломала разреженную нумерацию.
    last = section.items.order_by("-order").values_list("order", flat=True).first()
    item = HomeSectionItem.objects.create(
        section=section, order=(last or 0) + 10, **data,
    )
    return _serialize_item_admin(item)


def update_item(item_id: int, patch: dict) -> dict:
    item = HomeSectionItem.objects.filter(pk=item_id).first()
    if item is None:
        raise ItemNotFound()
    for field, value in patch.items():
        setattr(item, field, value)
    item.save()
    return _serialize_item_admin(item)


def delete_item(item_id: int) -> None:
    deleted, _ = HomeSectionItem.objects.filter(pk=item_id).delete()
    if not deleted:
        raise ItemNotFound()


@transaction.atomic
def reorder_sections(ids: list[int]) -> None:
    """Присланный порядок id → колонка ``order`` (10, 20, 30…).

    В одной транзакции: перетаскивание меняет позиции сразу нескольким
    соседям, и оборванная на середине запись оставила бы страницу с
    перемешанными блоками. Незнакомые id молча игнорируются — они означают,
    что кто-то удалил секцию, пока её тащили, и это не повод ронять запрос.
    """
    known = set(HomeSection.objects.filter(pk__in=ids).values_list("pk", flat=True))
    for position, section_id in enumerate((i for i in ids if i in known), start=1):
        HomeSection.objects.filter(pk=section_id).update(order=position * 10)


@transaction.atomic
def reorder_items(section_id: int, ids: list[int]) -> None:
    """То же для элементов внутри секции.

    Ограничиваем выборку этой секцией: иначе чужой id в теле запроса
    перетасовал бы соседний блок.
    """
    known = set(
        HomeSectionItem.objects.filter(pk__in=ids, section_id=section_id)
        .values_list("pk", flat=True)
    )
    for position, item_id in enumerate((i for i in ids if i in known), start=1):
        HomeSectionItem.objects.filter(pk=item_id).update(order=position * 10)


class SystemSectionProtected(Exception):
    """Попытка удалить одну из девяти исходных секций."""


def _derive_key(title: str) -> str:
    """Служебный ключ из заголовка: транслит, только a-z0-9 и дефис.

    Заголовок русский, а ``key`` — SlugField, поэтому без транслитерации почти
    любое название схлопнулось бы в пустую строку. Уникальность разводим
    суффиксом, а не ошибкой: два блока «Наши услуги» — нормальная ситуация,
    и падать на ней незачем.
    """
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    slug = "".join(table.get(ch, ch) for ch in (title or "").strip().lower())
    slug = "".join(ch if (ch.isascii() and (ch.isalnum())) else "-" for ch in slug)
    slug = "-".join(part for part in slug.split("-") if part)[:48] or "block"

    candidate, suffix = slug, 2
    while HomeSection.objects.filter(key=candidate).exists():
        candidate = f"{slug}-{suffix}"
        suffix += 1
    return candidate


def create_section(data: dict, *, user_id: int | None) -> dict:
    """Новый блок — всегда в конец и всегда пользовательский (не системный)."""
    last = HomeSection.objects.order_by("-order").values_list("order", flat=True).first()
    section = HomeSection.objects.create(
        key=_derive_key(data.get("title_ru") or data.get("title_en")),
        order=(last or 0) + 10,
        is_system=False,
        # Скрыт по умолчанию: только что созданный блок пуст, и показывать
        # посетителям заготовку без содержимого нельзя. Редактор наполнит его
        # и включит показ сам.
        is_visible=False,
        updated_by=user_id,
        **data,
    )
    return _serialize_section_admin(section)


def delete_section(section_id: int) -> None:
    section = get_section(section_id)
    if section.is_system:
        raise SystemSectionProtected()
    section.delete()
