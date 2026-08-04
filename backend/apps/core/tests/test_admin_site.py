"""Брендинг и порядок разделов в /django-admin/ (htqweb/admin_site.py).

Стоковый ``AdminSite`` сортирует разделы по алфавиту их ``verbose_name``,
поэтому служебные «Пользователи»/«Служебное» вставали посреди предметных
разделов. ``HTQAdminSite.get_app_list`` пересортировывает их по ``_APP_ORDER``.

Подключение — через ``AdminConfig.default_site`` (htqweb/apps.py в
INSTALLED_APPS вместо "django.contrib.admin"). Первый тест сторожит именно
эту связку: если конфиг вернут на стоковый, ``@admin.register`` продолжит
работать молча, а брендинг и порядок тихо исчезнут.
"""

import pytest
from django.contrib import admin
from django.test import Client

from apps.users.models import User, UserStatus
from htqweb.admin_site import HTQAdminSite


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="site-admin", email="site-admin@htq.test",
                            password="x", status=UserStatus.ACTIVE,
                            is_staff=True, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


def _app_labels(user) -> list[str]:
    c = Client()
    c.force_login(user)
    # get_app_list — тот же метод, которым AdminSite.index() строит и индекс,
    # и боковой сайдбар, поэтому проверяем именно его.
    resp = c.get("/django-admin/")
    assert resp.status_code == 200
    return [app["app_label"] for app in resp.context["app_list"]]


@pytest.mark.django_db
def test_default_site_is_the_branded_one():
    # admin.site — ленивый прокси DefaultAdminSite, поэтому type() вернёт
    # обёртку. LazyObject проксирует __class__ на обёрнутый объект, так что
    # сверять надо именно его: type(admin.site) здесь дал бы ложный зелёный.
    assert admin.site.__class__ is HTQAdminSite
    assert admin.site.site_header == "HTQWeb — администрирование"
    assert admin.site.site_title == "HTQWeb"
    assert admin.site.index_title == "Разделы платформы"


@pytest.mark.django_db
def test_domain_sections_come_before_service_sections(superuser):
    labels = _app_labels(superuser)
    for domain in ("hr", "tasks", "approvals"):
        assert labels.index(domain) < labels.index("users"), domain
        assert labels.index(domain) < labels.index("core"), domain


@pytest.mark.django_db
def test_section_order_follows_app_order_map(superuser):
    labels = _app_labels(superuser)
    expected = [label for label in (
        "hr", "tasks", "approvals", "signoff", "contracts",
        "cms", "media_files", "mail", "messenger", "users", "core",
    ) if label in labels]
    assert [label for label in labels if label in expected] == expected


@pytest.mark.django_db
def test_unlisted_apps_go_last(superuser):
    """django_celery_beat и прочие сторонние аппки в _APP_ORDER не описаны —
    они обязаны уехать в хвост, а не разбить предметные разделы."""
    labels = _app_labels(superuser)
    known = {"hr", "tasks", "approvals", "signoff", "contracts", "cms",
             "media_files", "mail", "messenger", "users", "core"}
    unlisted = [i for i, label in enumerate(labels) if label not in known]
    if unlisted:
        assert min(unlisted) > max(i for i, label in enumerate(labels) if label in known)


@pytest.mark.django_db
def test_branded_stylesheet_is_linked_on_admin_pages(superuser):
    """Фирменная тема подключается через свой templates/admin/base_site.html.

    Тихий режим отказа, ради которого этот тест и написан: если из TEMPLATES
    уберут DIRS или переименуют шаблон, Django молча возьмёт стоковый
    base_site.html — админка продолжит работать, просто без темы.
    """
    c = Client()
    c.force_login(superuser)
    body = c.get("/django-admin/").content.decode()
    assert "admin/htqweb.css" in body
    # Наш шаблон должен ДОПОЛНЯТЬ, а не вытеснять штатные стили: {{ block.super }}
    # в extrastyle + порядок в admin/base.html — иначе переменные перекрывать нечего.
    assert "admin/css/base.css" in body
    assert "admin/css/dark_mode.css" in body


@pytest.mark.django_db
def test_login_page_is_branded_too(db):
    """Страница входа рендерится анонимному пользователю — свой base_site.html
    должен работать и там (у неё отдельный шаблон, наследующий тот же базовый)."""
    body = Client().get("/django-admin/login/").content.decode()
    assert "admin/htqweb.css" in body
    assert "HTQWeb" in body


@pytest.mark.django_db
def test_sections_are_named_in_russian(superuser):
    """verbose_name у AppConfig — иначе в индексе видно «Hr», «Media files»."""
    c = Client()
    c.force_login(superuser)
    names = {app["app_label"]: app["name"] for app in c.get("/django-admin/").context["app_list"]}
    assert names["hr"] == "Кадры"
    assert names["tasks"] == "Работы"
    assert names["media_files"] == "Файлы"
    assert names["core"] == "Служебное"


@pytest.mark.django_db
def test_model_names_in_sidebar_are_russian(superuser):
    """Meta.verbose_name_plural у моделей — иначе в сайдбаре «Level thresholds».

    Проверяем не выборочно, а сплошняком: ни одно имя модели в НАШИХ разделах
    не должно состоять из латиницы. Именно так дефект и выглядел — часть
    списка переведена, часть нет.
    """
    c = Client()
    c.force_login(superuser)
    ours = {"hr", "tasks", "approvals", "signoff", "contracts", "cms",
            "media_files", "mail", "messenger", "users", "core"}
    latin = [
        f'{app["app_label"]}.{model["object_name"]}: {model["name"]}'
        for app in c.get("/django-admin/").context["app_list"] if app["app_label"] in ours
        for model in app["models"]
        if not any("а" <= ch.lower() <= "я" or ch == "ё" for ch in str(model["name"]))
    ]
    assert latin == [], latin


@pytest.mark.django_db
def test_third_party_sections_are_relabelled(superuser):
    """Чужим моделям Meta не поставить, поэтому подписи задаются в AdminSite."""
    c = Client()
    c.force_login(superuser)
    celery = next(
        (app for app in c.get("/django-admin/").context["app_list"]
         if app["app_label"] == "django_celery_results"), None,
    )
    assert celery is not None, "django_celery_results пропал из админки"
    assert celery["name"] == "Результаты Celery"
    assert {str(m["name"]) for m in celery["models"]} == {
        "Результаты задач", "Результаты групп задач",
    }
