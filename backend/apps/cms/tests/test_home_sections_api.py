"""Блоки главной страницы — API.

Проверяется то, что легко сломать незаметно: публичность чтения, утечка
скрытых блоков, откат перевода на русский, атомарность перестановки и
закрытость записи от не-администратора.
"""
import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.cms.models import HomeSection, HomeSectionItem

BASE = "/api/cms/v1/home"


def _token(**over):
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


@pytest.fixture
def auth():
    """Обычный залогиненный пользователь — не редактор."""
    return {"HTTP_AUTHORIZATION": f"Bearer {_token()}"}


@pytest.fixture
def admin_auth():
    return {"HTTP_AUTHORIZATION": f"Bearer {_token(user_id=9, sub='9', is_admin=True)}"}


@pytest.fixture
def section(db):
    s = HomeSection.objects.create(
        key="demo", order=10, is_visible=True,
        tag_ru="Тег", tag_en="Tag",
        title_ru="Заголовок", title_en="Title",
        description_ru="Описание", description_en="",
    )
    HomeSectionItem.objects.create(
        section=s, order=10, is_visible=True,
        title_ru="Первый", title_en="First", value="722",
    )
    HomeSectionItem.objects.create(
        section=s, order=20, is_visible=False, title_ru="Скрытый", title_en="Hidden",
    )
    return s


# ── Публичное чтение ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_public_read_needs_no_token(section):
    """Лендинг открыт анонимам — токен требовать неоткуда."""
    resp = Client().get(f"{BASE}/sections")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_public_read_returns_russian_by_default(section):
    body = Client().get(f"{BASE}/sections").json()
    demo = next(s for s in body if s["key"] == "demo")
    assert demo["title"] == "Заголовок"
    assert demo["tag"] == "Тег"


@pytest.mark.django_db
def test_public_read_returns_english_when_asked(section):
    body = Client().get(f"{BASE}/sections?lang=en").json()
    demo = next(s for s in body if s["key"] == "demo")
    assert demo["title"] == "Title"


@pytest.mark.django_db
def test_empty_translation_falls_back_to_russian(section):
    """Незаполненный перевод — не пустая вёрстка, а русский текст.

    Переводы заполняют позже русского, и до этого момента английская версия
    страницы должна оставаться читаемой.
    """
    body = Client().get(f"{BASE}/sections?lang=en").json()
    demo = next(s for s in body if s["key"] == "demo")
    assert demo["description"] == "Описание"


@pytest.mark.django_db
def test_region_suffix_is_accepted(section):
    """i18next присылает `en-US`; колонок под регионы нет, берём язык."""
    body = Client().get(f"{BASE}/sections?lang=en-US").json()
    assert next(s for s in body if s["key"] == "demo")["title"] == "Title"


@pytest.mark.django_db
def test_unknown_language_falls_back_to_russian(section):
    body = Client().get(f"{BASE}/sections?lang=zz").json()
    assert next(s for s in body if s["key"] == "demo")["title"] == "Заголовок"


@pytest.mark.django_db
def test_hidden_section_never_reaches_the_public(section):
    section.is_visible = False
    section.save()
    body = Client().get(f"{BASE}/sections").json()
    assert all(s["key"] != "demo" for s in body)


@pytest.mark.django_db
def test_hidden_item_never_reaches_the_public(section):
    demo = next(s for s in Client().get(f"{BASE}/sections").json() if s["key"] == "demo")
    titles = [i["title"] for i in demo["items"]]
    assert titles == ["Первый"]


@pytest.mark.django_db
def test_public_sections_are_ordered(section):
    HomeSection.objects.create(key="first", order=1, title_ru="Первая")
    body = Client().get(f"{BASE}/sections").json()
    keys = [s["key"] for s in body]
    assert keys.index("first") < keys.index("demo")


# ── Права на запись ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_admin_list_requires_token(section):
    assert Client().get(f"{BASE}/admin/sections").status_code == 401


@pytest.mark.django_db
def test_admin_list_forbidden_for_plain_user(auth):
    assert Client().get(f"{BASE}/admin/sections", **auth).status_code == 403


@pytest.mark.django_db
def test_update_forbidden_for_plain_user(section, auth):
    resp = Client().patch(
        f"{BASE}/admin/sections/{section.id}",
        data=json.dumps({"title_ru": "Взлом"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    section.refresh_from_db()
    assert section.title_ru == "Заголовок"


@pytest.mark.django_db
def test_admin_sees_hidden_sections_and_both_languages(section, admin_auth):
    section.is_visible = False
    section.save()
    body = Client().get(f"{BASE}/admin/sections", **admin_auth).json()
    demo = next(s for s in body if s["key"] == "demo")
    assert demo["is_visible"] is False
    assert demo["title_ru"] == "Заголовок"
    assert demo["title_en"] == "Title"
    # Скрытые элементы редактору тоже видны — иначе их нельзя было бы вернуть.
    assert len(demo["items"]) == 2


# ── Правка ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_admin_updates_only_sent_fields(section, admin_auth):
    resp = Client().patch(
        f"{BASE}/admin/sections/{section.id}",
        data=json.dumps({"title_ru": "Новый"}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    section.refresh_from_db()
    assert section.title_ru == "Новый"
    assert section.tag_ru == "Тег"          # не присылали — не тронули


@pytest.mark.django_db
def test_key_cannot_be_changed(section, admin_auth):
    """`key` связывает запись с React-компонентом: переименование оставило бы
    секцию без макета. Поля нет в схеме, лишний ключ игнорируется."""
    Client().patch(
        f"{BASE}/admin/sections/{section.id}",
        data=json.dumps({"key": "hacked", "title_ru": "Новый"}),
        content_type="application/json", **admin_auth,
    )
    section.refresh_from_db()
    assert section.key == "demo"


@pytest.mark.django_db
def test_update_missing_section_404(admin_auth):
    resp = Client().patch(
        f"{BASE}/admin/sections/999999",
        data=json.dumps({"title_ru": "x"}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


# ── Порядок ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reorder_rewrites_order(section, admin_auth):
    other = HomeSection.objects.create(key="other", order=20)
    resp = Client().post(
        f"{BASE}/admin/sections/reorder",
        data=json.dumps({"ids": [other.id, section.id]}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    section.refresh_from_db(); other.refresh_from_db()
    assert other.order < section.order


@pytest.mark.django_db
def test_reorder_ignores_unknown_ids(section, admin_auth):
    """Удалённая параллельно секция не должна ронять перестановку."""
    resp = Client().post(
        f"{BASE}/admin/sections/reorder",
        data=json.dumps({"ids": [999999, section.id]}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_item_reorder_is_scoped_to_its_section(section, admin_auth):
    """Чужой id в теле не должен перетасовать соседний блок."""
    other = HomeSection.objects.create(key="other", order=20)
    foreign = HomeSectionItem.objects.create(section=other, order=99, title_ru="Чужой")
    Client().post(
        f"{BASE}/admin/sections/{section.id}/items/reorder",
        data=json.dumps({"ids": [foreign.id]}),
        content_type="application/json", **admin_auth,
    )
    foreign.refresh_from_db()
    assert foreign.order == 99


# ── Элементы ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_item_appends_to_the_end(section, admin_auth):
    resp = Client().post(
        f"{BASE}/admin/sections/{section.id}/items",
        data=json.dumps({"title_ru": "Третий"}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["order"] > 20


@pytest.mark.django_db
def test_delete_item(section, admin_auth):
    item = section.items.first()
    resp = Client().delete(f"{BASE}/admin/items/{item.id}", **admin_auth)
    assert resp.status_code == 204
    assert not HomeSectionItem.objects.filter(pk=item.id).exists()


@pytest.mark.django_db
def test_delete_missing_item_404(admin_auth):
    assert Client().delete(f"{BASE}/admin/items/999999", **admin_auth).status_code == 404


# ── Создание и удаление блоков ──────────────────────────────────────────────

@pytest.mark.django_db
def test_create_section_derives_key_from_russian_title(admin_auth):
    """Ключ — служебный, редактор его не вводит: SlugField не принял бы
    кириллицу, поэтому сервер транслитерирует заголовок сам."""
    resp = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "Наши преимущества", "layout": "features_grid"}),
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] == "nashi-preimushchestva"
    assert body["is_system"] is False


@pytest.mark.django_db
def test_created_section_is_hidden_until_filled(admin_auth):
    """Пустая заготовка не должна появиться на сайте сама."""
    resp = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "Черновик", "layout": "cta"}),
        content_type="application/json", **admin_auth,
    )
    assert resp.json()["is_visible"] is False
    public = Client().get(f"{BASE}/sections").json()
    assert all(s["key"] != "chernovik" for s in public)


@pytest.mark.django_db
def test_duplicate_titles_get_distinct_keys(admin_auth):
    """Два блока с одним названием — обычное дело, падать на этом незачем."""
    payload = json.dumps({"title_ru": "Услуги", "layout": "features_grid"})
    first = Client().post(f"{BASE}/admin/sections", data=payload,
                          content_type="application/json", **admin_auth).json()
    second = Client().post(f"{BASE}/admin/sections", data=payload,
                           content_type="application/json", **admin_auth).json()
    assert first["key"] != second["key"]


@pytest.mark.django_db
def test_create_forbidden_for_plain_user(auth):
    resp = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "Взлом", "layout": "cta"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert not HomeSection.objects.filter(title_ru="Взлом").exists()


@pytest.mark.django_db
def test_custom_section_can_be_deleted(admin_auth):
    created = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "Временный", "layout": "cta"}),
        content_type="application/json", **admin_auth,
    ).json()
    resp = Client().delete(f"{BASE}/admin/sections/{created['id']}", **admin_auth)
    assert resp.status_code == 204
    assert not HomeSection.objects.filter(pk=created["id"]).exists()


@pytest.mark.django_db
def test_system_section_cannot_be_deleted(section, admin_auth):
    """У системной секции свой React-компонент; пересоздать её из интерфейса
    нельзя, поэтому удаление запрещено — но прятать можно."""
    section.is_system = True
    section.save()
    resp = Client().delete(f"{BASE}/admin/sections/{section.id}", **admin_auth)
    assert resp.status_code == 409
    assert HomeSection.objects.filter(pk=section.id).exists()


@pytest.mark.django_db
def test_deleting_section_removes_its_items(admin_auth):
    created = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "С элементами", "layout": "features_grid"}),
        content_type="application/json", **admin_auth,
    ).json()
    Client().post(
        f"{BASE}/admin/sections/{created['id']}/items",
        data=json.dumps({"title_ru": "Элемент"}),
        content_type="application/json", **admin_auth,
    )
    Client().delete(f"{BASE}/admin/sections/{created['id']}", **admin_auth)
    assert not HomeSectionItem.objects.filter(section_id=created["id"]).exists()


@pytest.mark.django_db
def test_layout_reaches_the_public_payload(admin_auth):
    """Лендинг выбирает шаблон по `layout` — он обязан быть в публичной выдаче."""
    created = Client().post(
        f"{BASE}/admin/sections",
        data=json.dumps({"title_ru": "Цифры года", "layout": "stats"}),
        content_type="application/json", **admin_auth,
    ).json()
    Client().patch(
        f"{BASE}/admin/sections/{created['id']}",
        data=json.dumps({"is_visible": True}),
        content_type="application/json", **admin_auth,
    )
    public = Client().get(f"{BASE}/sections").json()
    found = next(s for s in public if s["id"] == created["id"])
    assert found["layout"] == "stats"
    assert found["is_system"] is False
