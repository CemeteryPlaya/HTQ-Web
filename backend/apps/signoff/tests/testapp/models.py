"""Предметная модель-образец для тестов движка.

Движок signoff универсален: он не знает ни одной согласуемой модели. Значит
и тестировать его на конкретном домене (``contracts.budget``) неправильно —
тесты начали бы падать от изменений в чужой аппке, а покрытие «работает ли
согласование ЛЮБОЙ модели» так и не появилось бы.

Поэтому здесь заведена своя минимальная модель. Подключается она ровно тем
же способом, каким подключится contracts (примесь + регистрация из
``AppConfig.ready()``), так что заодно проверяет и сам механизм подключения.

Таблица создаётся тестовым раннером: у аппки НЕТ пакета ``migrations``, а
``migrate --run-syncdb`` (его вызывает pytest-django при создании тестовой
БД) заводит таблицы именно для таких аппок. В ``INSTALLED_APPS`` она
добавлена только в ``htqweb.settings.test``.
"""

from django.db import models

# Ровно тот импорт, который сделает предметная аппка: примесь доступна
# только через interface (apps/core/tests/test_app_isolation.py).
from apps.signoff import interface as signoff


class ProbeDoc(signoff.Approvable, models.Model):
    SIGNOFF_SUBJECT_TYPE = "testapp.probedoc"

    title = models.CharField(max_length=100, default="")
    # Собственная доменная машина состояний — чтобы проверить, что колбэки
    # предметной аппки могут вести её ОТДЕЛЬНО от approval_state, который
    # ведёт сам signoff.
    published = models.BooleanField(default=False)

    # Поля под условные ветки. Названы нейтрально намеренно: движок не знает
    # ни про страны, ни про бюджеты, и тест, проверяющий ветвление на
    # «стране», проверял бы заодно и то, чего в signoff нет.
    #
    # ``zone`` играет роль справочника (``choice``) — то же место, которое у
    # contracts занимает страна администратора; ``amount`` и ``urgent``
    # покрывают порядковые операторы и bool.
    zone = models.IntegerField(null=True, blank=True)
    amount = models.IntegerField(default=0)
    urgent = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.title
