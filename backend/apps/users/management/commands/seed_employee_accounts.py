"""Учётки для засеянных сотрудников — локальные демо-данные.

Зачем отдельная команда, а не шаг внутри ``seed_hr_demo``: пароль умеет
ставить только ``apps.users.services.admin_service`` (он же проверяет
уникальность и хеширует), а импортировать его из apps.hr запрещено
(apps/core/tests/test_app_isolation.py). Поэтому команда живёт здесь, а
карточки сотрудников читает и связывает через ``apps.hr.interface`` —
единственный разрешённый путь в соседнюю аппку.

Зачем это вообще нужно. В домене задач исполнитель, владелец проекта и
руководитель объекта — это ``user_id``, а не PK строки ``Employee`` (их
имена резолвит apps.users). У засеянных сотрудников учёток не было, поэтому
любая задача оставалась без исполнителя, а отчёты по людям — пустыми.
Побочно закрывается дыра в проверках: до сих пор в базе не существовало ни
одного НЕ-администратора, и сценарии рядового сотрудника нечем было
проверить.

Пароль одинаковый и известный — это демо-данные для локальной среды; от
боевой базы команда защищена тем же ``--force-remote``, что и seed_hr_demo.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr import interface as hr_interface
from apps.users.services import admin_service

DEFAULT_PASSWORD = "demo12345"

# Локальные адреса. Совпадает со списком в apps/hr/.../seed_hr_demo.py —
# правило одно, и расходиться этим двум спискам нельзя.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "db", "::1", ""}


class Command(BaseCommand):
    help = (
        "Завести платформенные учётки для сотрудников HR и связать их "
        "с карточками (Employee.user_id). Только для локальной среды."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD,
            help=f"Пароль для всех создаваемых учёток (по умолчанию {DEFAULT_PASSWORD}).",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Завести учётки только первым N сотрудникам (0 — всем).",
        )
        parser.add_argument(
            "--force-remote", action="store_true",
            help="Осознанно разрешить неместную БД.",
        )

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Отказ работать против чего-либо, кроме локальной базы.

        Команда заводит учётные записи с известным паролем — на боевом
        хосте это дыра, а не наполнение. ``host`` передаётся только из
        тестов, чтобы правило проверялось как функция от строки и боевой
        адрес не приходилось подставлять в живые настройки.
        """
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        if host in _LOCAL_HOSTS or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда заводит "
            f"учётки с общеизвестным паролем и предназначена только для "
            f"локальной среды. Если это осознанно — --force-remote."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])
        password = options["password"]

        employees = hr_interface.list_employees_brief()
        if options["limit"]:
            employees = employees[: options["limit"]]
        if not employees:
            raise CommandError(
                "В базе нет сотрудников. Сначала: manage.py seed_hr_demo"
            )

        created = linked = skipped = already = 0
        for employee in employees:
            # У кого учётка уже есть — не трогаем вовсе. Иначе команда
            # завела бы человеку вторую и переклеила связь на неё, а первая
            # осталась бы сиротой: задачи и проекты ссылаются на СТАРЫЙ
            # user_id и потеряли бы владельца.
            if employee["user_id"]:
                already += 1
                continue

            email = (employee["email"] or "").strip().lower()
            if not email:
                skipped += 1
                continue

            # Идемпотентность: повторный запуск не должен падать на
            # уникальности почты и не должен менять уже заданный пароль.
            user = admin_service.User.objects.filter(email=email).first()
            if user is None:
                last, _, first = employee["full_name"].partition(" ")
                user = admin_service.create_user(
                    username=email.split("@")[0],
                    email=email,
                    password=password,
                    first_name=first,
                    last_name=last,
                    display_name=employee["full_name"],
                    # Рядовые сотрудники: без staff и без обязательной
                    # смены пароля — иначе демо-учётка не переживёт первый
                    # вход, а именно ради входа она и заводится.
                    is_staff=False,
                    must_change_password=False,
                )
                created += 1

            if hr_interface.link_employee_user(employee["id"], user.id):
                linked += 1

        self.stdout.write(self.style.SUCCESS(
            f"Готово: учёток создано {created}, привязано к карточкам {linked}"
            + (f", уже были {already}" if already else "")
            + (f", пропущено без почты {skipped}" if skipped else "")
        ))
        if created:
            self.stdout.write(f"  пароль у всех созданных: {password}")
