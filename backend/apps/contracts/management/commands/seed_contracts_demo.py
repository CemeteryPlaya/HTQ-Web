# -*- coding: utf-8 -*-
"""Наполнение домена договоров: страны, проекты, статьи, бюджет, контрагенты.

ТОЛЬКО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ — как ``seed_hr_demo`` и ``seed_tasks_demo``, и той
же защитой ``_assert_local``. Боевой реестр наполняют не отсюда.

Всё через ``update_or_create`` по естественному ключу, поэтому второй запуск
ничего не дублирует, а правит на месте.

**Порядок обязателен, и он не косметика.** Страна идёт первой (на неё
ссылаются и администратор, и контрагент — оба ``PROTECT``), затем программы
(на них ссылается строка бюджета), затем администратор, бюджет и его строки.
Контрагенты зависят только от страны, поэтому идут после справочников, а
договоры — последними: они ссылаются и на строку бюджета, и на контрагента.

Бюджет заводится ОДИН на связку (администратор, год, валюта) — на это стоит
``UniqueConstraint``, поэтому ключ ``update_or_create`` именно такой.

Суммы подобраны так, чтобы в интерфейсе было на что смотреть: часть строк
остаётся с большим остатком, а по статье 3019 заведён доходный договор из
настоящей карточки HTQ 04/2026 — он показывает, что «Поступление» расходный
остаток НЕ трогает.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tasks import interface as tasks

from apps.contracts.models import (
    Administrator,
    Agreement,
    AgreementStatus,
    Budget,
    BudgetLine,
    BudgetStatus,
    Counterparty,
    Country,
    Program,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "db", "::1", ""}

COUNTRIES = [("Казахстан", "KZ"), ("Россия", "RU"), ("Узбекистан", "UZ")]

# (код статьи, название программы, статья расходов)
PROGRAMS = [
    ("3019", "Ограждение/дороги/выравнивание", "Ограждение/дороги/выравнивание"),
    ("3020", "Земляные работы", "Земляные работы и планировка"),
    ("3021", "Электромонтаж", "Кабельные линии и подстанции"),
    ("3022", "Монтаж металлоконструкций", "Металлоконструкции и опоры"),
    ("3105", "Проектирование", "Рабочая документация и авторский надзор"),
    ("4010", "Транспорт и логистика", "Доставка оборудования на объект"),
    ("4021", "Аренда техники", "Аренда спецтехники и механизмов"),
    ("5001", "Общехозяйственные расходы", "Хозяйственные нужды объекта"),
]

# (проект, страна)
ADMINISTRATORS = [
    ("QAZAQSTAN-Aralsk", "Казахстан"),
    ("QAZAQSTAN-Shymkent", "Казахстан"),
    ("SARYARQA-Karaganda", "Казахстан"),
]

# проект -> [(код статьи, сумма строки, примечание)]
BUDGET_LINES = {
    "QAZAQSTAN-Aralsk": [
        ("3019", "1200000000.00", "Ограждение периметра, внутриплощадочные дороги"),
        ("3020", "480000000.00", "Выемка грунта, обратная засыпка, планировка"),
        ("3021", "950000000.00", "ВЛ-10 кВ, КТП, внутренние сети"),
        ("3022", "610000000.00", "Опоры и несущие конструкции"),
        ("3105", "85000000.00", "РД по всем разделам"),
        ("4010", "140000000.00", "Доставка модулей и трансформаторов"),
        ("4021", "260000000.00", "Экскаваторы, краны, автовышки"),
        ("5001", "35000000.00", "Бытовой городок, расходники"),
    ],
    "QAZAQSTAN-Shymkent": [
        ("3019", "540000000.00", "Ограждение и КПП"),
        ("3020", "310000000.00", "Земляные работы первой очереди"),
        ("3021", "720000000.00", "Электромонтаж первой очереди"),
        ("3105", "60000000.00", "Проектные работы"),
        ("4021", "180000000.00", "Аренда техники"),
    ],
    "SARYARQA-Karaganda": [
        ("3020", "260000000.00", "Планировка площадки"),
        ("3022", "430000000.00", "Металлоконструкции складского комплекса"),
        ("4010", "95000000.00", "Логистика"),
        ("5001", "22000000.00", "Хознужды"),
    ],
}

# (БИН/ИИН, наименование, НДС, контакт, телефон, почта, страна, статус, адрес)
#
# Двое, а не витрина из девяти: реестр здесь — фон для договоров, и длинный
# список только мешал бы читать бюджет. Один с НДС, второй без — этого хватает,
# чтобы в карточке договора было видно обе ветки флага НДС.
COUNTERPARTIES = [
    ("80340019927", "ТОО «Снабкомплект Монтаж»", True, "Куаныш Садиев",
     "+7 (701) 555-01-27", "info@snabkomplekt.kz", "Казахстан", "active",
     "г. Аральск, ул. Промышленная, 14"),
    ("061240009900", "ТОО «СпецТехАренда»", False, "Нурлан Есимов",
     "+7 (708) 401-56-33", "arenda@spectech.kz", "Казахстан", "active",
     "г. Аральск, ул. Автобазовская, 7"),
]

# Контрагенты, которых команда заводила раньше и больше не заводит. Нужны
# только сносу: без них ``--purge`` на уже наполненной базе оставил бы семь
# сирот, и «оставили двоих» превратилось бы в «завели двоих поверх девяти».
_RETIRED_BIN_IINS = (
    "140240013561", "051140004521", "990340000123", "120640007788",
    "7714301234", "301567890123", "030240001111",
)


def _agreement_specs() -> list[dict]:
    """Договоры, которые команда заводит поверх бюджета.

    Первый — настоящая карточка HTQ 04/2026: направление «Поступление»,
    ставка НДС 0,1 %, срок исполнения словом «уточнить», даты нет. Остальные
    расходные и в разных статусах, чтобы в строках бюджета было видно и
    занятое, и остаток: черновик лимит не занимает, подписанный — занимает.
    """
    return [
        {
            "number": "HTQ 04/2026", "project": "QAZAQSTAN-Aralsk",
            "code": "3019", "bin_iin": "80340019927",
            "name": "Монтаж ограждения, дороги, выравнивание, земляные работы",
            "subject": "Монтаж ограждения, дороги, выравнивание, земляные работы",
            "direction": "income", "kind": "works_services",
            "contract_type": "standard", "sed_number": "DOC-00026-20260623",
            "manager_name": "Куаныш Садиев",
            "has_vat": True, "vat_rate": "0.10",
            "amount_without_vat": "99999999999.00",
            "vat_amount": "100000000.00", "amount": "100099999999.00",
            "has_advance": False, "advance_percentage": None,
            "advance_amount_planned": None,
            "retention_rate": "5.00", "retention_amount": "5004999999.95",
            "signed_date": dt.date(2026, 5, 28),
            "start_date": dt.date(2026, 5, 28), "end_date": None,
            "term_comment": "уточнить", "status": AgreementStatus.SIGNED,
        },
        {
            "number": "HTQ 05/2026", "project": "QAZAQSTAN-Aralsk",
            "code": "3021", "bin_iin": "80340019927",
            "name": "Электромонтажные работы ВЛ-10 кВ",
            "subject": "Монтаж ВЛ-10 кВ, установка КТП, прокладка внутренних сетей",
            "direction": "expense", "kind": "works_services",
            "contract_type": "standard", "sed_number": "DOC-00031-20260701",
            "manager_name": "Куаныш Садиев",
            "has_vat": True, "vat_rate": "12.00",
            "amount_without_vat": "375000000.00",
            "vat_amount": "45000000.00", "amount": "420000000.00",
            "has_advance": True, "advance_percentage": "30.00",
            "advance_amount_planned": "126000000.00",
            "retention_rate": "5.00", "retention_amount": "21000000.00",
            "signed_date": dt.date(2026, 7, 1),
            "start_date": dt.date(2026, 7, 15),
            "end_date": dt.date(2026, 12, 20),
            "term_comment": "", "status": AgreementStatus.SIGNED,
        },
        {
            "number": "HTQ 06/2026", "project": "QAZAQSTAN-Aralsk",
            "code": "4021", "bin_iin": "061240009900",
            "name": "Аренда спецтехники",
            "subject": "Экскаваторы, автокраны и автовышки с экипажем",
            "direction": "expense", "kind": "lease",
            "contract_type": "framework", "sed_number": "DOC-00033-20260705",
            "manager_name": "Нурлан Есимов",
            "has_vat": False, "vat_rate": "0.00",
            "amount_without_vat": "88000000.00",
            "vat_amount": None, "amount": "88000000.00",
            "has_advance": False, "advance_percentage": None,
            "advance_amount_planned": None,
            "retention_rate": "0.00", "retention_amount": None,
            "signed_date": dt.date(2026, 7, 5),
            "start_date": dt.date(2026, 7, 10),
            "end_date": dt.date(2026, 11, 30),
            "term_comment": "", "status": AgreementStatus.SIGNED,
        },
        {
            "number": "HTQ 07/2026", "project": "QAZAQSTAN-Shymkent",
            "code": "3105", "bin_iin": "80340019927",
            "name": "Разработка рабочей документации",
            "subject": "РД по разделам ЭМ, КЖ, АР с авторским надзором",
            "direction": "expense", "kind": "services",
            "contract_type": "non_standard", "sed_number": "DOC-00040-20260812",
            "manager_name": "Куаныш Садиев",
            "has_vat": True, "vat_rate": "12.00",
            "amount_without_vat": "37500000.00",
            "vat_amount": "4500000.00", "amount": "42000000.00",
            "has_advance": True, "advance_percentage": "20.00",
            "advance_amount_planned": "8400000.00",
            "retention_rate": "0.00", "retention_amount": None,
            "signed_date": dt.date(2026, 8, 12),
            "start_date": dt.date(2026, 8, 20),
            "end_date": dt.date(2026, 10, 31),
            "term_comment": "", "status": AgreementStatus.ON_REVIEW,
        },
        {
            "number": "HTQ 08/2026", "project": "SARYARQA-Karaganda",
            "code": "3022", "bin_iin": "061240009900",
            "name": "Поставка и монтаж металлоконструкций",
            "subject": "Изготовление, поставка и монтаж несущих металлоконструкций",
            "direction": "expense", "kind": "goods",
            "contract_type": "standard", "sed_number": "DOC-00044-20260901",
            "manager_name": "Нурлан Есимов",
            "has_vat": True, "vat_rate": "12.00",
            "amount_without_vat": "160714285.71",
            "vat_amount": "19285714.29", "amount": "180000000.00",
            "has_advance": False, "advance_percentage": None,
            "advance_amount_planned": None,
            "retention_rate": "10.00", "retention_amount": "18000000.00",
            "signed_date": dt.date(2026, 9, 1),
            "start_date": dt.date(2026, 9, 10),
            "end_date": dt.date(2027, 3, 31),
            "term_comment": "", "status": AgreementStatus.DRAFT,
        },
    ]

_MONEY_FIELDS = ("amount", "amount_without_vat", "vat_amount",
                 "advance_amount_planned", "retention_amount",
                 "vat_rate", "retention_rate", "advance_percentage")


class Command(BaseCommand):
    help = ("Наполнить домен договоров демо-данными: справочники, бюджеты по "
            "проектам, реестр контрагентов и договоры. Только локальная БД.")

    def add_arguments(self, parser) -> None:
        parser.add_argument("--purge", action="store_true",
                            help="Снести засеянное перед наполнением.")
        parser.add_argument("--purge-only", action="store_true",
                            help="Только снести засеянное, не наполнять.")
        parser.add_argument("--force-remote", action="store_true",
                            help="Осознанно разрешить неместную БД.")

    # ── защита ──────────────────────────────────────────────────────────

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Отказ работать против чего-либо, кроме локальной базы.

        ``host`` передаётся только из тестов: иначе проверить правило можно
        было бы лишь подставив боевой адрес в живые настройки.
        """
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        if host in _LOCAL_HOSTS or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда наполняет "
            f"домен договоров демо-данными и предназначена только для "
            f"локальной среды. Если это осознанно — --force-remote."
        )

    # ── снос ────────────────────────────────────────────────────────────

    def _purge(self) -> None:
        """Снести ровно засеянное — по естественным ключам, а не всю таблицу.

        Порядок обратный наполнению: договоры ссылаются на строку бюджета и
        контрагента, строки — на бюджет и программу. Снести родителя раньше
        ребёнка не даст ``PROTECT``.
        """
        projects = [name for name, _ in ADMINISTRATORS]
        agreements = Agreement.objects.filter(
            number__in=[s["number"] for s in _agreement_specs()]).delete()[0]
        lines = BudgetLine.objects.filter(
            budget__administrator__project_name__in=projects).delete()[0]
        budgets = Budget.objects.filter(
            administrator__project_name__in=projects).delete()[0]
        parties = Counterparty.objects.filter(
            bin_iin__in=[c[0] for c in COUNTERPARTIES] + list(_RETIRED_BIN_IINS)
        ).delete()[0]
        admins = Administrator.objects.filter(
            project_name__in=projects).delete()[0]
        programs = Program.objects.filter(
            code__in=[p[0] for p in PROGRAMS]).delete()[0]
        self.stdout.write(
            f"  снесено: договоров {agreements}, строк {lines}, "
            f"бюджетов {budgets}, контрагентов {parties}, "
            f"проектов {admins}, программ {programs}")

    # ── наполнение ──────────────────────────────────────────────────────

    def _seed_countries(self) -> dict[str, Country]:
        out = {}
        for name, iso in COUNTRIES:
            out[name] = Country.objects.update_or_create(
                name=name, defaults={"iso_code": iso})[0]
        self.stdout.write(f"  стран: {len(out)}")
        return out

    def _seed_programs(self) -> dict[str, Program]:
        """Ключ — (name, expense_item): именно на них стоит UniqueConstraint.

        Код же необязателен и может меняться, поэтому он в defaults, а не в
        ключе — иначе смена кода заводила бы вторую программу вместо правки.
        """
        out = {}
        for code, name, expense_item in PROGRAMS:
            out[code] = Program.objects.update_or_create(
                name=name, expense_item=expense_item,
                defaults={"code": code, "is_active": True})[0]
        self.stdout.write(f"  программ/статей: {len(out)}")
        return out

    def _seed_administrators(self, countries) -> dict[str, Administrator]:
        """Администраторы бюджета + связь с проектами модуля задач.

        Связь ищется ПО ИМЕНИ (``find_project_by_name``) и только у тех, у
        кого проект на доске задач уже есть: заводить его отсюда нельзя —
        это чужой домен, а межаппочный доступ идёт исключительно через
        ``interface`` (``apps/core/tests/test_app_isolation.py``). Нет
        проекта — запись просто остаётся несвязанной, как и у половины
        боевых данных.
        """
        out, linked = {}, 0
        for project_name, country_name in ADMINISTRATORS:
            brief = tasks.find_project_by_name(project_name)
            defaults = {"country": countries[country_name], "is_active": True}
            if brief is not None:
                defaults["project_id"] = brief["id"]
                linked += 1
            out[project_name] = Administrator.objects.update_or_create(
                project_name=project_name, defaults=defaults,
            )[0]
        note = f", связано с задачами: {linked}" if linked else                " (проектов с такими именами в модуле задач нет — связь пуста)"
        self.stdout.write(f"  проектов: {len(out)}{note}")
        return out

    def _seed_budgets(self, admins, programs) -> dict[str, Budget]:
        out, total_lines = {}, 0
        for project_name, administrator in admins.items():
            budget, _ = Budget.objects.update_or_create(
                administrator=administrator, period_year=2026, currency="KZT",
                defaults={"status": BudgetStatus.ACTIVE,
                          "note": f"Бюджет 2026 по проекту {project_name}"},
            )
            out[project_name] = budget
            for code, amount, note in BUDGET_LINES[project_name]:
                BudgetLine.objects.update_or_create(
                    budget=budget, program=programs[code],
                    defaults={"amount": Decimal(amount), "note": note},
                )
                total_lines += 1
        self.stdout.write(f"  бюджетов: {len(out)}, строк в них: {total_lines}")
        return out

    def _seed_counterparties(self, countries) -> dict[str, Counterparty]:
        out = {}
        for (bin_iin, name, vat, contact, phone, email,
             country_name, status, address) in COUNTERPARTIES:
            out[bin_iin] = Counterparty.objects.update_or_create(
                bin_iin=bin_iin,
                defaults={"name": name, "vat": vat, "contact_name": contact,
                          "phone": phone, "email": email, "address": address,
                          "country": countries[country_name], "status": status},
            )[0]
        by_status: dict[str, int] = {}
        for row in out.values():
            by_status[row.status] = by_status.get(row.status, 0) + 1
        self.stdout.write("  контрагентов: {} ({})".format(
            len(out), ", ".join(f"{k} {v}" for k, v in sorted(by_status.items()))))
        return out

    def _seed_agreements(self, budgets, programs, parties) -> int:
        """Договоры пишутся моделью напрямую, в обход ``agreement_service``.

        Сервис проверял бы лимит строки, а суммы здесь подобраны под витрину,
        а не под правило: смысл наполнения — чтобы в интерфейсе было видно и
        занятое, и остаток, и «Поступление», которое лимит не трогает.
        """
        for spec in _agreement_specs():
            line = BudgetLine.objects.get(budget=budgets[spec["project"]],
                                          program=programs[spec["code"]])
            fields = {k: v for k, v in spec.items()
                      if k not in ("project", "code", "bin_iin", "number")}
            for money in _MONEY_FIELDS:
                if fields.get(money) is not None:
                    fields[money] = Decimal(fields[money])
            Agreement.objects.update_or_create(
                number=spec["number"],
                defaults={"budget_line": line,
                          "counterparty": parties[spec["bin_iin"]],
                          "currency": "KZT", "created_by": 1, **fields},
            )
        count = len(_agreement_specs())
        self.stdout.write(f"  договоров: {count}")
        return count

    # ── точка входа ─────────────────────────────────────────────────────

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        self._assert_local(options["force_remote"])

        if options["purge"] or options["purge_only"]:
            self._purge()
            if options["purge_only"]:
                self.stdout.write(self.style.SUCCESS("Готово: только снос."))
                return

        countries = self._seed_countries()
        programs = self._seed_programs()
        admins = self._seed_administrators(countries)
        budgets = self._seed_budgets(admins, programs)
        parties = self._seed_counterparties(countries)
        self._seed_agreements(budgets, programs, parties)

        self.stdout.write(self.style.SUCCESS(
            "Готово. Смотреть: /contracts/budgets и /contracts/counterparties"))
