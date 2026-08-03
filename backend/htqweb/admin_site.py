"""Брендинг и порядок разделов в /django-admin/.

Стоковый индекс админки сортирует разделы по алфавиту их ``verbose_name``, из-за
чего 11 доменов платформы шли вперемешку: служебные «Пользователи» и рубильник
сервисов оказывались посреди предметных «Кадров» и «Работ». Здесь задан
осмысленный порядок — сначала люди и работы, потом документооборот, дальше
контент и коммуникации, служебное в конце.

Подключается не заменой ``admin.site`` (это сломало бы все ``@admin.register``,
которые пишут в дефолтный сайт), а штатной точкой Django — ``AdminConfig.
default_site`` в ``htqweb/apps.py``: Django сам создаёт ЭТОТ класс как
``admin.site``, поэтому регистрация во всех 98 ModelAdmin работает без правок.

Порядок моделей ВНУТРИ раздела не трогаем — он остаётся алфавитным, как у
Django по умолчанию.
"""
from django.contrib.admin import AdminSite

# app_label -> вес. Меньше = выше в индексе и в боковом сайдбаре.
# Аппка, которой здесь нет (включая django.contrib.*), уезжает в конец и
# сортируется по алфавиту между такими же — список не обязан быть полным.
_APP_ORDER: dict[str, int] = {
    "hr": 10,           # Кадры
    "tasks": 20,        # Работы
    "approvals": 30,    # Заявки и формы
    "signoff": 40,      # Согласование
    "contracts": 50,    # Договоры и бюджеты
    "cms": 60,          # Сайт и контент
    "media_files": 70,  # Файлы
    "mail": 80,         # Почта
    "messenger": 90,    # Мессенджер
    "users": 100,       # Пользователи
    "core": 110,        # Служебное (рубильник сервисов)
}

_UNLISTED = 10_000  # всё, чего нет в _APP_ORDER — после перечисленного

# Русские подписи для СТОРОННИХ аппок. Своим моделям имена ставятся штатно —
# Meta.verbose_name в apps/*/models.py; здесь так нельзя: модели чужие, а
# заводить ради подписи proxy-модель с миграцией — избыточно. Поэтому правим
# только то, что показывает индекс: ключ — app_label, значение — имя раздела и
# карта object_name -> имя модели (во множественном числе, как в сайдбаре).
# django_celery_beat и auth свои переводы поставляют сами — их здесь нет.
_THIRD_PARTY_NAMES: dict[str, tuple[str, dict[str, str]]] = {
    "django_celery_results": ("Результаты Celery", {
        "TaskResult": "Результаты задач",
        "GroupResult": "Результаты групп задач",
    }),
}


class HTQAdminSite(AdminSite):
    site_header = "HTQWeb — администрирование"
    site_title = "HTQWeb"
    index_title = "Разделы платформы"

    def get_app_list(self, request, app_label=None):
        """Тот же список, что у Django, но в порядке _APP_ORDER.

        Базовый метод уже отфильтровал разделы по правам (в том числе через
        ``ServiceGatedAdminMixin.has_module_permission`` — выключенный сервис
        сюда не доходит), поэтому здесь только пересортировка.
        """
        app_list = super().get_app_list(request, app_label)
        for app in app_list:
            names = _THIRD_PARTY_NAMES.get(app["app_label"])
            if not names:
                continue
            app["name"], model_names = names
            for model in app["models"]:
                model["name"] = model_names.get(model["object_name"], model["name"])
        return sorted(
            app_list,
            # str() — имена моделей приходят ленивыми объектами перевода
            # (gettext_lazy), а они между собой не сравниваются.
            key=lambda app: (_APP_ORDER.get(app["app_label"], _UNLISTED), str(app["name"])),
        )
