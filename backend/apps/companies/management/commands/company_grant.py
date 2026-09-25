"""Выдать пользователям право работать в компании (``CompanyMembership``).

Дополняет ``tenancy_bootstrap --grant-all`` (который заводит членство ОДИН
раз, при первом переводе платформы в мультикомпанейный режим) на обычный,
повторяемый случай: приняли нового сотрудника, завели вторую компанию,
кому-то нужен доступ ещё в одну — без членства ``htqweb/authn/jwt.py``
выпустит токен с ``company: null``, и запрос на поддомен компании получит
403 (см. докстринг ``tenancy_bootstrap`` и Правку 2 итогового ревью).

Идемпотентна: повторный запуск на уже выданном членстве ничего не
дублирует (``membership_service.grant_membership`` — ``get_or_create`` по
тому же ключу, что несёт ``uniq_membership``) и завершается успешно, без
ошибки — оператор может запускать её вслепую в скрипте развёртывания.

``--user``, ``--all-users`` и ``--serving`` взаимоисключающие и хотя бы один
обязателен (``add_mutually_exclusive_group(required=True)``): выдавать права
без явного указания кому — ни одному, ни всем сразу, ни по признаку — не тот
случай, где имеет смысл угадывать дефолт.

``--serving`` (задача 8 блока C) закрывает разрыв, ради которого написан этот
файл: должность вышестоящей компании, помеченная обслуживающей, несёт её
держателям права по всем дочерним (``apps.access.services.inheritance`` —
решение заказчика 1), но БЕЗ ``CompanyMembership`` для дочерней компании
токен для её поддомена всё равно не выпускается — признак сам по себе
ничего не открывает. Список держателей берётся через
``apps.access.interface.serving_holders`` — то же ядро обхода предков, что
и у витрины «внешние держатели прав» (задача 7): семантика «держит права»
здесь ОДНА, а не изобретена заново для этой команды.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.access.interface import UnknownRole, serving_holders
from apps.companies.models import Company
from apps.companies.services import membership_service


class Command(BaseCommand):
    help = ("Выдать членство в компании пользователю (--user), всем активным "
           "(--all-users) или держателям обслуживающих должностей "
           "компаний-предков (--serving).")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--user", dest="user",
                           help="id или username конкретного пользователя.")
        group.add_argument("--all-users", action="store_true", dest="all_users",
                           help="Выдать членство всем активным пользователям платформы.")
        group.add_argument("--serving", action="store_true", dest="serving",
                           help="Выдать членство держателям обслуживающих "
                                "должностей вышестоящих компаний (задача 8 "
                                "блока C).")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        company = Company.objects.filter(slug=slug).first()
        if company is None:
            raise CommandError(f"Компания {slug} не найдена.")

        if opts["all_users"]:
            user_ids = membership_service.active_user_ids()
            if not user_ids:
                self.stdout.write(self.style.WARNING(
                    "Активных пользователей не найдено — нечего выдавать."
                ))
                return
        elif opts["serving"]:
            user_ids = serving_holders(slug)
            if not user_ids:
                self.stdout.write(self.style.WARNING(
                    "Держателей обслуживающих должностей вышестоящих "
                    "компаний не найдено — нечего выдавать."
                ))
                return
        else:
            identifier = opts["user"]
            user_id = membership_service.find_user_id(identifier)
            if user_id is None:
                raise CommandError(f"Пользователь {identifier!r} не найден.")
            user_ids = [user_id]

        granted = 0
        already = 0
        for user_id in user_ids:
            try:
                created = membership_service.grant_membership(company, user_id)
            except UnknownRole as exc:
                raise CommandError(
                    f"Базовая роль не засеяна: {exc} Примените миграции access "
                    f"(manage.py migrate_shared) и повторите команду."
                ) from exc
            if created:
                granted += 1
            else:
                already += 1

        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug}: выдано новых членств {granted}, "
            f"уже было {already} (пропущено)."
        ))
