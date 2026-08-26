"""Секции футера — контент подвала сайта, редактируемый со страницы «Главная».

ПОЧЕМУ ПЯТЬ СЕКЦИЙ, А НЕ ОДНА. Подвал — это слоган, три самостоятельные
колонки ссылок («Компания», «Услуги», «Контакты») и нижняя строка (копирайт +
правовые ссылки). У них нет общей формы: колонки — списки «заголовок+ссылка»,
контакты — «текст+иконка+ссылка» (адрес без ссылки, почта и телефон — с
``mailto:``/``tel:``), а слоган и копирайт — просто текст. Свалить всё в одну
секцию значило бы либо завести в ``value`` название колонки (тайное
соглашение, которого нет в описании поля), либо смешать разноформатные
элементы в одном списке. Пять узких секций — без обходных путей: любое поле
используется строго по своему назначению.

Как разложено:
  * ``footer-brand``    — слоган (``description``), без элементов; соцсети
    остаются в коде (см. ``frontend/src/components/Footer.tsx`` — сейчас
    список пуст, реальных аккаунтов ещё нет, а редактор иконок в CMS умеет
    показывать только набор lucide, а не логотипы соцсетей).
  * ``footer-company``  — колонка «Компания»: ``title`` — подпись колонки,
    элементы — пары заголовок+ссылка (якоря и маршруты главной).
  * ``footer-services`` — колонка «Услуги»: те же четыре ссылки, что сейчас
    вычисляются из ``data/services.ts`` (``featuredOnMain``, первые четыре);
    зафиксированы явно, чтобы редактор мог поменять их без участия
    разработчика.
  * ``footer-contact``  — колонка «Контакты»: адрес/почта/телефон, каждый
    элемент — «текст (``title``) + иконка (``icon``, имя lucide) + ссылка
    (``link``)»; у адреса ``link`` пуст (это не ссылка).
  * ``footer-legal``    — нижняя строка: ``description`` — текст про права
    («Все права защищены.»), элементы — правовые ссылки. Сейчас пуст: страниц
    /privacy и /terms ещё нет (см. ``frontend/src/data/company.ts``), поэтому
    заполнять их выдуманным содержимым не следует — фронт скрывает пустой
    список ровно как раньше.

Все пять — ``is_system=True``: они, как и девять исходных секций, обслуживают
конкретный React-компонент (``Footer.tsx``) с фиксированной вёрсткой, и
пересоздать такую секцию из интерфейса не выйдет — новый блок получил бы
generic-макет и на подвал был бы не похож. Значит их можно скрыть/подвинуть/
отредактировать, но не удалить.

Идемпотентна: секции заводятся через ``get_or_create`` по ``key``, элементы —
только для только что созданных секций (как в ``0006_seed_home_sections``).
Обратная миграция удаляет только эти пять ключей.
"""
from django.db import migrations

SECTIONS = [
    {
        "key": "footer-brand",
        "order": 100,
        "description_ru": (
            "Лидер рынка ВИЭ в Центральной Азии. Строим устойчивое будущее "
            "через инновационные солнечные решения."
        ),
        "description_en": (
            "Market leader in renewable energy sources in Central Asia. "
            "Building a sustainable future through innovative solar solutions."
        ),
        "items": [],
    },
    {
        "key": "footer-company",
        "order": 110,
        "title_ru": "Компания",
        "title_en": "Company",
        "items": [
            {"order": 10, "title_ru": "О компании", "title_en": "About Us", "link": "/#about"},
            {"order": 20, "title_ru": "Проекты", "title_en": "Projects", "link": "/projects"},
            {"order": 30, "title_ru": "Услуги", "title_en": "Services", "link": "/services"},
            {"order": 40, "title_ru": "Новости", "title_en": "News", "link": "/#news"},
        ],
    },
    {
        "key": "footer-services",
        "order": 120,
        "title_ru": "Услуги",
        "title_en": "Services",
        "items": [
            {
                "order": 10,
                "title_ru": "Услуги инженера заказчика",
                "title_en": "Owner's Engineer Service",
                "link": "/services#service-1",
            },
            {
                "order": 20,
                "title_ru": "Испытание на выдергивание (POT)",
                "title_en": "Pull Out Test (POT)",
                "link": "/services#service-2",
            },
            {
                "order": 30,
                "title_ru": "Строительные услуги",
                "title_en": "Construction Service",
                "link": "/services#service-3",
            },
            {
                "order": 40,
                "title_ru": "Ввод в эксплуатацию и подключение к сети",
                "title_en": "Commissioning and Grid Connection",
                "link": "/services#service-4",
            },
        ],
    },
    {
        "key": "footer-contact",
        "order": 130,
        "title_ru": "Контакты",
        "title_en": "Contacts",
        "items": [
            {
                "order": 10,
                "icon": "MapPin",
                "title_ru": "Казахстан, г.Тараз, мкрн.Акбулак, 9А",
                "title_en": "Kazakhstan, Taraz, Akbulak microdistrict, 9A",
                "link": "",
            },
            {
                "order": 20,
                "icon": "Mail",
                "title_ru": "info@hi-techkz.com",
                "title_en": "info@hi-techkz.com",
                "link": "mailto:info@hi-techkz.com",
            },
            {
                "order": 30,
                "icon": "Phone",
                "title_ru": "+7 (727) 123-4567",
                "title_en": "+7 (727) 123-4567",
                "link": "tel:+77271234567",
            },
        ],
    },
    {
        "key": "footer-legal",
        "order": 140,
        "description_ru": "Все права защищены.",
        "description_en": "All rights reserved.",
        "items": [],
    },
]


def seed(apps, schema_editor):
    Section = apps.get_model("cms", "HomeSection")
    Item = apps.get_model("cms", "HomeSectionItem")
    for data in SECTIONS:
        items = data.pop("items", [])
        section, created = Section.objects.get_or_create(
            key=data["key"], defaults={**data, "is_system": True},
        )
        if not created:
            continue
        for it in items:
            Item.objects.create(section=section, **it)


def unseed(apps, schema_editor):
    Section = apps.get_model("cms", "HomeSection")
    Section.objects.filter(key__in=[s["key"] for s in SECTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [("cms", "0010_conferenceinvite_locale")]

    operations = [migrations.RunPython(seed, unseed)]
