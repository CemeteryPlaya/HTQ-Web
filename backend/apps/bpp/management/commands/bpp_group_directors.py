"""Директора холдинга в дочерних компаниях (A8.1, D-S7-8).

Роли ``bpp-*`` должностей ФД, ТД, ОД, ГД управляющей компании (холдинга)
действуют во всех компаниях ниже по дереву — не раздачей по людям, а
признаком ``hr.Position.serves_subsidiaries`` (``apps.access.services.
inheritance``). Но признак один токен не откроет: без ``CompanyMembership``
в дочерней компании токен на её поддомен не выдаётся. Команда делает обе
половины и печатает разрывы.

Порядок выкатки: сначала ``bpp_assign_roles --company <холдинг>`` (роли
должностям), затем эта команда. Идемпотентна; ``--dry-run`` ничего не пишет.

Решать согласования дочерней компании директора холдинга смогут после B8.1
(кросс-компанейский этап signoff) — до тех пор у дочерней должны быть свои
держатели должностей маршрута.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.access import interface as access
from apps.companies import interface as companies
from apps.hr import interface as hr
from htqweb.tenancy.db import use_company

DIRECTORS = (
    ("fd", "Финансовый директор"),
    ("td", "Технический директор"),
    ("od", "Операционный директор"),
    ("gd", "Генеральный директор"),
)


class Command(BaseCommand):
    help = ("Директорам холдинга (ФД, ТД, ОД, ГД): признак «обслуживает дочерние» "
            "и членство во всех дочерних компаниях.")

    def add_arguments(self, parser):
        parser.add_argument("--holding", required=True, help="слаг управляющей компании")
        for key, title in DIRECTORS:
            parser.add_argument(f"--{key}", type=int, default=None,
                                help=f"id должности «{title}» (иначе — по названию)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, holding, dry_run, **options):
        if companies.get_company(holding) is None:
            raise CommandError(f"Компания {holding!r} не найдена.")
        if not companies.is_holding(holding):
            raise CommandError(f"Компания {holding!r} — не холдинг.")

        positions = self._positions(holding, options)
        if not positions:
            raise CommandError("Ни одной должности директора не найдено.")
        holders = self._mark_and_resolve(holding, positions, dry_run)

        children = companies.descendant_slugs(holding)
        if not children:
            self.stdout.write("дочерних компаний нет — членства выдавать некому")
            return
        users = sorted({uid for ids in holders.values() for uid in ids})
        if not users:
            self.stdout.write("у должностей нет действующих держателей с учёткой — "
                              "членства выдавать некому")
        gaps = 0
        for child in children:
            gaps += self._memberships(child, users, dry_run)
            if not dry_run:
                gaps += self._role_gaps(child, holders)
        self.stdout.write(f"разрывов: {gaps}")

    # ── должности ──────────────────────────────────────────────────────────

    def _positions(self, holding, options) -> dict[str, int]:
        with use_company(holding):
            by_title = hr.positions_by_title([title for _, title in DIRECTORS])
        found: dict[str, int] = {}
        for key, title in DIRECTORS:
            position_id = options.get(key) or by_title.get(title)
            if position_id is None:
                self.stdout.write(f"нет должности: {title}")
                continue
            found[title] = position_id
        return found

    def _mark_and_resolve(self, holding, positions, dry_run) -> dict[str, list[int]]:
        with use_company(holding):
            changed = hr.mark_serving_subsidiaries(list(positions.values()), dry_run=dry_run)
            for title, position_id in list(positions.items()):
                if position_id not in changed:
                    self.stdout.write(f"нет активной должности: {title} (#{position_id})")
                    del positions[title]
                    continue
                if dry_run:
                    state = "будет выставлен" if changed[position_id] else "уже есть"
                else:
                    state = "выставлен" if changed[position_id] else "уже был"
                self.stdout.write(f"признак {state}: {title}")
            # Держатели — как у маршрутов согласования: и временные исполнители
            # (D-22). Членство им выдаётся постоянное — как ``company_grant
            # --serving``; снимается вручную (ранбук, шаг 6а).
            resolved = hr.resolve_position_users(list(positions.values()))
        holders = {title: resolved.get(position_id, []) for title, position_id in positions.items()}
        for title, user_ids in holders.items():
            if not user_ids:
                self.stdout.write(f"нет держателя с учётной записью: {title}")
        return holders

    # ── членства и разрывы ─────────────────────────────────────────────────

    def _memberships(self, child, users, dry_run) -> int:
        """Выдать членство; разрыв — держатели без членства (в dry-run — те, кому оно будет выдано)."""
        missing = companies.missing_member_ids(child, users)
        if dry_run:
            for user_id in missing:
                self.stdout.write(f"выдать членство в {child}: пользователь #{user_id}")
            return len(missing)
        granted = 0
        for user_id in users:
            if companies.grant_membership(child, user_id):
                granted += 1
        self.stdout.write(f"{child}: членство выдано {granted}, уже было {len(users) - granted}")
        return len(companies.missing_member_ids(child, users))

    def _role_gaps(self, child, holders) -> int:
        """Признак есть, членство есть, а ролей модуля в дочерней нет — должность
        без роли ``bpp-*`` (просмотр бюджетов есть у всех восьми, access/0014)."""
        carrying = set(access.holders_of("bpp.budgets", "view", child))
        gaps = 0
        for title, user_ids in holders.items():
            for user_id in user_ids:
                if user_id not in carrying:
                    gaps += 1
                    self.stdout.write(
                        f"разрыв: {title}, пользователь #{user_id} не несёт ролей bpp-* в {child} — "
                        f"выдайте роли должности (bpp_assign_roles)")
        return gaps
