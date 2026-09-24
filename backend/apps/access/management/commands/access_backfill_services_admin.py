"""Перенос администраторов сервисов: роль services-admin текущим is_staff.

Блок L. До него экраны media/conference/messenger/mail/cms/approvals пускали
по admin=True, то есть по is_staff. Гейт модуля флаги токена не читает
(как в блоке I для кадров), поэтому «перенести как есть» — выдать каждому
действующему is_staff (не суперпользователю: тот проходит гейт сам) роль
services-admin в каждой компании, где у него есть членство.

Без членства выдавать некуда — такой пользователь печатается в сводке:
токена на поддомен у него всё равно нет. Идемпотентна (get_or_create),
--dry-run ничего не пишет. RoleAssignment и CompanyMembership лежат в
public — use_company не нужен.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Role, RoleAssignment, ScopeKind

ROLE_CODE = "services-admin"


class Command(BaseCommand):
    help = ("Выдать роль services-admin действующим is_staff (кроме "
            "суперпользователей) во всех их компаниях. Идемпотентно.")

    def add_arguments(self, parser):
        parser.add_argument("--company", dest="company", default=None,
                            help="slug одной компании.")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                            help="Ничего не писать — только сводка.")

    def handle(self, *args, **options):
        from apps.companies import interface as companies
        from apps.users import interface as users

        dry_run: bool = options["dry_run"]
        only: str | None = options["company"]

        role = Role.objects.filter(code=ROLE_CODE).first()
        if role is None:
            raise CommandError(
                f"Роль {ROLE_CODE} не найдена (миграция access.0012 не применена?).")
        if only and companies.get_company(only) is None:
            raise CommandError(f"Компания {only!r} не найдена в реестре.")

        prefix = "[dry-run] " if dry_run else ""
        created = already = 0
        for user_id in users.staff_user_ids():
            slugs = companies.user_company_slugs(user_id)
            if only:
                slugs = [s for s in slugs if s == only]
            if not slugs:
                # С --company членства может не быть именно в ней, а в других —
                # есть: «нет членства» без имени компании читалось бы как «нет
                # нигде» (финальное ревью блока L, M-9).
                where = f" в {only}" if only else ""
                self.stdout.write(self.style.WARNING(
                    f"{prefix}пользователь {user_id}: нет членства{where} — роль выдавать некуда"))
                continue
            for slug in slugs:
                exists = RoleAssignment.objects.filter(
                    company_slug=slug, user_id=user_id, role=role,
                    scope_kind=ScopeKind.COMPANY, scope_id=None).exists()
                if exists:
                    already += 1
                    continue
                created += 1
                if not dry_run:
                    RoleAssignment.objects.get_or_create(
                        company_slug=slug, user_id=user_id, role=role,
                        scope_kind=ScopeKind.COMPANY, scope_id=None)
                self.stdout.write(f"{prefix}пользователь {user_id} → {slug}")
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Роль {ROLE_CODE}: выдано сейчас {created}, уже было {already}."))
