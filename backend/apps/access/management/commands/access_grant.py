"""Выдать пользователю роль в компании из консоли.

Путь начальной раздачи прав, которому не нужен ни один экран. Он существует
затем, что интерфейс выдачи ролей сам закрыт гейтом: пока в базе нет ни одного
назначения, у всех, кроме суперпользователя, карта прав пуста — и страница,
через которую роли выдаются, закрыта вместе со всем остальным. Разорвать этот
круг можно либо суперпользователем, либо отсюда.

Идемпотентна: повторный запуск на уже выданной роли ничего не дублирует
(уникальность несут частичные индексы ``RoleAssignment``) и завершается
успешно — команду можно звать вслепую из скрипта развёртывания.

``--company`` обязателен и не имеет умолчания: назначение действует ровно в
одной компании, и угадывать, в какой именно, здесь нечего — подстановка
«первой попавшейся» раздала бы права не туда молча.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Role, RoleAssignment, ScopeKind


class Command(BaseCommand):
    help = "Выдать пользователю роль в компании (RoleAssignment)."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, dest="user",
                            help="id или username пользователя.")
        parser.add_argument("--role", required=True, dest="role_code",
                            help="code роли из каталога, например platform-admin.")
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании, в которой действует назначение.")
        parser.add_argument("--scope", default=ScopeKind.COMPANY,
                            choices=[ScopeKind.COMPANY, ScopeKind.DEPARTMENT, ScopeKind.SITE],
                            dest="scope_kind",
                            help="Область действия. По умолчанию вся компания.")
        parser.add_argument("--scope-id", type=int, default=None, dest="scope_id",
                            help="Идентификатор отдела или объекта; обязателен, кроме области company.")

    def handle(self, *args, **opts):
        user = self._resolve_user(opts["user"])
        role = Role.objects.filter(code=opts["role_code"]).first()
        if role is None:
            known = ", ".join(Role.objects.values_list("code", flat=True)) or "каталог пуст"
            raise CommandError(f"Роль {opts['role_code']} не найдена. Есть: {known}")

        self._check_company(opts["company_slug"])
        scope_kind, scope_id = opts["scope_kind"], opts["scope_id"]
        if scope_kind == ScopeKind.COMPANY and scope_id is not None:
            raise CommandError("Область «компания» не имеет идентификатора: уберите --scope-id.")
        if scope_kind != ScopeKind.COMPANY and scope_id is None:
            raise CommandError(f"Область «{scope_kind}» требует --scope-id.")

        _row, created = RoleAssignment.objects.get_or_create(
            company_slug=opts["company_slug"], user_id=user.id, role=role,
            scope_kind=scope_kind, scope_id=scope_id,
        )
        verb = "выдана" if created else "уже была выдана"
        self.stdout.write(self.style.SUCCESS(
            f"Роль {role.code} {verb}: пользователь {user.username} (id={user.id}), "
            f"компания {opts['company_slug']}, область {scope_kind}"
            + (f" #{scope_id}" if scope_id is not None else "")
        ))

        if not user.is_active:
            self.stdout.write(self.style.WARNING(
                "Учётная запись неактивна — права появятся только после её включения."))

    def _resolve_user(self, raw: str):
        User = get_user_model()
        user = (User.objects.filter(pk=int(raw)).first() if raw.isdigit()
                else User.objects.filter(username=raw).first())
        if user is None:
            raise CommandError(f"Пользователь {raw} не найден.")
        return user

    def _check_company(self, slug: str) -> None:
        """Компания сверяется через интерфейс соседа, а не запросом к его моделям.

        Отсутствие компании — предупреждение, а не отказ: назначение хранится
        слагом и переживёт заведение компании позже, а вот тихо промолчать об
        опечатке в слаге нельзя — права просто не сработают.
        """
        from apps.companies import interface as companies

        if companies.get_company(slug) is None:
            self.stdout.write(self.style.WARNING(
                f"В реестре нет компании {slug} — проверьте slug, иначе назначение не сработает."))
