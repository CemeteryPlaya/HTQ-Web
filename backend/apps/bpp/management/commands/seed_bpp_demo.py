"""Демо-данные модуля БЗО для пилота и e2e (мастер-план, задача B4.2).

    manage.py seed_bpp_demo --company <slug> [--sn ID --pm ID --fd ID --buh ID]
    manage.py seed_bpp_demo --company <slug> --purge

Заводит два проекта ``ДЕМО-01`` / ``ДЕМО-02`` и проводит по ним документы
теми же сервисами, что и экраны, от имени настоящих держателей ролей:
утверждённые бюджеты, заявки во всех статусах (черновик, на согласовании,
на доработке, отклонена, утверждена), договор — действующий и черновик,
счета — черновик, у ФД, к оплате и частично оплачен (по договору), оплачен
с запросом закрывающих, и подотчёт. Решения по маршрутам принимает держатель
ждущей задачи — поэтому нужны настроенные маршруты
(``bpp_configure_routes``) и роли у людей (``bpp_assign_roles`` или личные
назначения); чего нет — команда говорит, что сделать, и ничего не пишет.

- **Идемпотентна**: проект ``ДЕМО-01`` уже есть — повторный запуск ничего не
  делает (пересоздать — ``--purge`` и запуск заново).
- **``--purge`` удаляет только своё**: документы демо-проектов, их процессы
  согласования, сами проекты и демо-контрагентов (если на них не ссылаются
  чужие документы). Журнал изменений неизменяем (триггер ``bpp/0001``) —
  его строки о демо-документах остаются, как и израсходованные номера.
- К договору и счетам прикладывается файл-заглушка ``DEMO_PDF`` — без файла
  их не отправить (ТЗ §21); ``--purge`` убирает файлы вместе с документами.
- Уведомления — как при ручной работе: согласующие получат колокольчик и
  письма о демо-документах. На пилоте запускать до подключения людей.
- Статьи бюджета — действующие статьи групп «Снабжение» и «Проектное
  управление» из справочника (его ведёт управляющая компания): сид их не
  заводит.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.access import interface as access
from apps.bpp.models import (
    AccountableFundsRequest,
    Agreement,
    AgreementStatus,
    Budget,
    Counterparty,
    Invoice,
    PurchaseRequest,
)
from apps.bpp.services.accountable import accountable as accountable_service
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.budget import budgets
from apps.bpp.services.core import files as core_files
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.requests import requests as request_service
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

PROJECTS = (("ДЕМО-01", "Демо: ЖК «Садовый квартал»"), ("ДЕМО-02", "Демо: склад «Восток»"))
#: Демо-контрагенты: тело БИН (11 цифр, контрольный разряд считается), имя,
#: «Проверенный» — ручная метка ФД или нет.
COUNTERPARTIES = (("99000000001", "ТОО «Демо Металл»", "Демо Металл", True),
                  ("99000000002", "ТОО «Демо Электро»", "Демо Электро", None))
#: Кто нужен и по каким узлам его узнать (роль — сочетание прав, как у
#: ``Actor.initiator_roles``; держатель ищется среди участников компании).
PEOPLE = {
    "sn": ("СН (снабжение)", (("bpp.requests", "create"), ("bpp.articles.supply", "view"))),
    "pm": ("ПМ (руководитель проекта)", (("bpp.requests", "create"), ("bpp.articles.pm", "view"))),
    "fd": ("ФД", (("bpp.budgets.approve", "edit"), ("bpp.invoices.decision", "edit"))),
    "buh": ("бухгалтер", (("bpp.invoices.payment", "edit"),)),
}
ROUTES = (("bpp.purchase_request", "заявки на закупку"), ("bpp.agreement", "договора"),
          ("bpp.invoice", "счёта на оплату"))
#: Сколько решений подряд ждать закрытия маршрута — страховка от петли.
MAX_DECISIONS = 12
#: Файл-заглушка для договора и счетов: минимальный PDF (подсистема файлов
#: проверяет сигнатуру содержимого, а не только расширение).
DEMO_PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF\n")


def bin_with_checksum(body11: str) -> str:
    """БИН: 11 цифр + контрольный разряд (двухпроходный алгоритм РК)."""
    digits = [int(c) for c in body11]
    for weights in (range(1, 12), [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]):
        rest = sum(d * w for d, w in zip(digits, weights)) % 11
        if rest != 10:
            return body11 + str(rest)
    raise CommandError(f"Для {body11} контрольный разряд не вычисляется — возьмите другой")


class Command(BaseCommand):
    help = "Демо-данные модуля БЗО: проекты, бюджеты, заявки, договоры, счета, оплаты (B4.2)"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--purge", action="store_true",
                            help="удалить демо-данные этой команды и выйти")
        for key, (title, _) in PEOPLE.items():
            parser.add_argument(f"--{key}", type=int, default=None,
                                help=f"id пользователя-{title} (по умолчанию — держатель роли)")

    # ── вход ────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        slug = options["company"]
        with use_company(slug):
            if options["purge"]:
                with transaction.atomic():
                    self._purge()
                return
            if projects.project_ids_by_code([PROJECTS[0][0]]):
                self.stdout.write(f"Демо-данные уже есть (проект {PROJECTS[0][0]}). "
                                  f"Пересоздать — --purge и запуск заново.")
                return
            people = self._people(slug, options)
            self._check_routes()
            self.stdout.write(self.style.WARNING(
                "Уведомления — как при ручной работе: согласующие получат колокольчик и письма."))
            try:
                with transaction.atomic():
                    self._seed(slug, people)
            except DomainError as exc:
                raise CommandError(f"{exc.code}: {exc.message} — ничего не записано") from exc
        self.stdout.write(self.style.SUCCESS("Готово."))

    def _people(self, slug: str, options) -> dict[str, int]:
        found, missing = {}, []
        for key, (title, nodes) in PEOPLE.items():
            if options.get(key):
                found[key] = options[key]
                continue
            holders = None
            for node, flag in nodes:
                ids = set(access.holders_of(node, flag, slug))
                holders = ids if holders is None else holders & ids
            if holders:
                found[key] = min(holders)
            else:
                missing.append(f"{title} (--{key})")
        if missing:
            raise CommandError(
                "Нет держателя роли в компании: " + ", ".join(missing) + ". Выдайте роли "
                "(manage.py bpp_assign_roles или личным назначением) или укажите id явно.")
        return found

    def _check_routes(self) -> None:
        missing = [title for subject, title in ROUTES if not signoff.has_active_route(subject)]
        if missing:
            raise CommandError(
                "Не настроены маршруты согласования: " + ", ".join(missing) + ". Сначала "
                "manage.py bpp_configure_routes --company <slug>.")

    # ── решения по маршруту ─────────────────────────────────────────────

    @staticmethod
    def _pending(subject_type: str, subject_id) -> list[dict]:
        process = signoff.get_process_for(subject_type, str(subject_id))
        if not process or process.get("state") != "pending":
            return []
        return [t for st in process["stages"] for t in st["tasks"] if t["state"] == "pending"]

    def _decide(self, subject_type: str, subject_id, decision: str, comment: str = "") -> None:
        tasks = self._pending(subject_type, subject_id)
        if not tasks:
            raise CommandError(f"{subject_type} {subject_id}: нет ждущей задачи для «{decision}»")
        task = tasks[0]
        result = signoff.decide_many(actor_id=task["user_id"], items=[
            {"task_id": task["id"], "decision": decision, "comment": comment}])[0]
        if not result.get("ok"):
            raise CommandError(f"{subject_type} {subject_id}: {result.get('error')}")

    def _approve_all(self, subject_type: str, subject_id) -> None:
        for _ in range(MAX_DECISIONS):
            if not self._pending(subject_type, subject_id):
                return
            self._decide(subject_type, subject_id, "approve")
        raise CommandError(f"{subject_type} {subject_id}: маршрут не закрылся за "
                           f"{MAX_DECISIONS} решений")

    # ── данные ──────────────────────────────────────────────────────────

    def _articles(self) -> tuple[list[dict], list[dict]]:
        supply, pm = refdata.active_articles("supply"), refdata.active_articles("pm")
        if len(supply) < 2 or not pm:
            raise CommandError(
                "Нужны действующие статьи бюджета: две в группе «Снабжение» и одна в "
                "«Проектное управление» (раздел «Справочники» → «Статьи»).")
        return supply[:2], pm[:1]

    def _uoms(self) -> dict[str, str]:
        units = {code: refdata.uom_id(code) for code in ("pcs", "t", "m")}
        absent = [code for code, uid in units.items() if uid is None]
        if absent:
            raise CommandError(f"Нет единиц измерения {', '.join(absent)} в справочнике "
                               f"(сид refdata/0002)")
        return units

    def _counterparties(self) -> list[Counterparty]:
        rows = []
        for body, name, short, verified in COUNTERPARTIES:
            row, _ = Counterparty.objects.get_or_create(
                country_code="KZ", reg_number=bin_with_checksum(body),
                defaults={"name": name, "short_name": short, "kind": "legal",
                          "is_vat_payer": True, "verified_override": verified})
            rows.append(row)
        return rows

    def _request(self, actor: Actor, project_id: str, article_id: str, role: str,
                 justification: str, items: list[tuple]) -> PurchaseRequest:
        need = timezone.localdate() + timedelta(days=14)
        return request_service.create_draft(actor, {
            "initiator_role": role, "project_id": project_id, "article_id": article_id,
            "purchase_type": "goods", "need_date": need, "justification": justification,
            "items": [{"name": name, "uom_id": uom, "qty": Decimal(str(qty)),
                       "price": Decimal(str(price)), "need_date": need}
                      for name, uom, qty, price in items]})

    def _submitted(self, actor: Actor, *args) -> PurchaseRequest:
        req = self._request(actor, *args)
        return request_service.submit(actor, req.id, expected_version=None)

    def _seed(self, slug: str, people: dict[str, int]) -> None:
        sn, pm, fd, buh = (Actor.for_user(people[k], company=slug)
                           for k in ("sn", "pm", "fd", "buh"))
        supply, pm_articles = self._articles()
        units = self._uoms()
        today = timezone.localdate()
        out = self.stdout.write

        # Проекты и бюджеты.
        ids = []
        for code, name in PROJECTS:
            ids.append(projects.create_project(
                code=code, name=name, country_code="KZ", actor_id=people["fd"],
                manager_user_id=people["pm"], member_ids=[people["sn"]]))
            out(f"проект {code}")
        limits = [(supply[0]["id"], "60000000"), (supply[1]["id"], "20000000"),
                  (pm_articles[0]["id"], "15000000")]
        for project_id in ids:
            budget = budgets.create(fd, project_id=project_id, lines=[
                {"article_id": art, "limit_amount": Decimal(limit)} for art, limit in limits])
            budgets.approve(fd, budget.id, expected_version=None)
        out("бюджеты утверждены: " + ", ".join(f"{a['code']}" for a, _ in
                                                zip(supply + pm_articles, limits)))

        p1, p2 = ids
        metal, electro, design = supply[0]["id"], supply[1]["id"], pm_articles[0]["id"]
        t, m, pcs = units["t"], units["m"], units["pcs"]

        # Заявки во всех статусах.
        draft = self._request(sn, p1, metal, "sn", "Арматура для фундамента секции 2",
                              [("Арматура А500С Ø12", t, 5, 320000)])
        review = self._submitted(sn, p1, metal, "sn", "Закладные детали перекрытий",
                                 [("Пластина 200×200×10", pcs, 120, 3500)])
        rework = self._submitted(sn, p1, metal, "sn", "Сетка кладочная",
                                 [("Сетка 50×50×4", pcs, 300, 1800)])
        self._decide("bpp.purchase_request", rework.pk, "rework",
                     "Уточните размер ячейки и сроки поставки")
        rejected = self._submitted(sn, p1, metal, "sn", "Профнастил для ограждения",
                                   [("Профнастил С21", pcs, 80, 5600)])
        self._decide("bpp.purchase_request", rejected.pk, "reject",
                     "Позиции уже закуплены по другой заявке")
        for_agreement = self._submitted(sn, p1, metal, "sn", "Металлокаркас рампы", [
            ("Швеллер 12П", t, 10, 240000), ("Уголок 50×5", t, 4, 210000),
            ("Лист г/к 4 мм", t, 2, 280000)])
        self._approve_all("bpp.purchase_request", for_agreement.pk)
        for_invoices = self._submitted(sn, p1, electro, "sn", "Электромонтаж секции 1", [
            ("Кабель ВВГнг 3×2,5", m, 500, 950), ("Автомат 16А", pcs, 40, 4200),
            ("Щит ЩРН-24", pcs, 3, 38000)])
        self._approve_all("bpp.purchase_request", for_invoices.pk)
        pm_request = self._submitted(pm, p2, design, "pm", "Рабочая документация склада",
                                     [("Раздел КЖ", pcs, 1, 1800000)])
        self._approve_all("bpp.purchase_request", pm_request.pk)
        for req in (draft, review, rework, rejected, for_agreement, for_invoices, pm_request):
            req.refresh_from_db()
            out(f"заявка {req.number} — {req.get_status_display()}")

        metal_cp, electro_cp = self._counterparties()
        agreement_items = list(for_agreement.items.order_by("line_no"))
        invoice_items = list(for_invoices.items.order_by("line_no"))

        # Договор: действующий по двум позициям, черновик — по третьей.
        agr = agreement_service.create_from_plan(sn, [str(i.id) for i in agreement_items[:2]],
                                                 role="sn")
        agr, _ = agreement_service.update_draft(sn, agr.id, expected_version=None, data={
            "counterparty_id": str(metal_cp.pk), "ext_number": "Д-2026/17",
            "ext_date": today, "name": "Поставка металлопроката для рампы"})
        self._attach(agr, "agreement", "dogovor-D-2026-17.pdf")
        agreement_service.submit(sn, agr.id, expected_version=None)
        self._approve_all("bpp.agreement", agr.pk)
        agr.refresh_from_db()
        if agr.status != AgreementStatus.ACTIVE:
            raise CommandError(f"Договор {agr.number} не вступил в силу: {agr.status}")
        agr_draft = agreement_service.create_from_plan(sn, [str(agreement_items[2].id)],
                                                       role="sn")
        out(f"договоры {agr.number} — действует, {agr_draft.number} — черновик")

        # Счёт по договору: ФД — «Оплатить», БУХ — оплата половины.
        by_agr = invoice_service.create_from_agreement(sn, agr.id)
        by_agr, _ = invoice_service.update_draft(sn, by_agr.id, expected_version=None, data={
            "ext_number": "145", "ext_date": today})
        self._attach(by_agr, "invoice", "schet-145.pdf")
        invoice_service.submit(sn, by_agr.id, expected_version=None)
        self._fd_decide(slug, by_agr, "pay")
        by_agr.refresh_from_db()
        payments.mark_paid(buh, by_agr.id, pay_date=today, amount=by_agr.amount / 2,
                           pp_number="1001")

        # Счета без договора: черновик, у ФД, оплачен с запросом закрывающих.
        inv_draft = self._invoice(sn, invoice_items[0], electro_cp, "Э-71", submit=False)
        inv_review = self._invoice(sn, invoice_items[1], electro_cp, "Э-72")
        inv_paid = self._invoice(sn, invoice_items[2], electro_cp, "Э-73")
        self._fd_decide(slug, inv_paid, "pay")
        inv_paid.refresh_from_db()
        payments.mark_paid(buh, inv_paid.id, pay_date=today, amount=inv_paid.amount,
                           pp_number="1002")
        payments.request_docs(buh, inv_paid.id,
                              docs={"avr": False, "waybill": True, "vat_invoice": True},
                              comment="Накладная и счёт-фактура на щиты")
        for inv in (by_agr, inv_draft, inv_review, inv_paid):
            inv.refresh_from_db()
            out(f"счёт {inv.number} — {inv.get_status_display()}")

        # Подотчёт: с маршрутом — до выдачи, иначе черновик.
        acc = accountable_service.create(sn, project_id=p1, article_id=electro, amount=150000,
                                         goal="Мелкие закупки на объекте: крепёж, расходники")
        subject = AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE
        if signoff.has_active_route(subject):
            accountable_service.submit(sn, acc.id, expected_version=None)
            self._approve_all(subject, acc.pk)
            accountable_service.mark_paid(buh, acc.id, expected_version=None)
        acc.refresh_from_db()
        out(f"подотчёт {acc.number} — {acc.get_status_display()}")

    def _invoice(self, sn: Actor, item, counterparty: Counterparty, ext_number: str, *,
                 submit: bool = True) -> Invoice:
        inv = invoice_service.create_from_plan(sn, [str(item.id)], role="sn")
        inv, _ = invoice_service.update_draft(sn, inv.id, expected_version=None, data={
            "counterparty_id": str(counterparty.pk), "ext_number": ext_number,
            "ext_date": timezone.localdate()})
        self._attach(inv, "invoice", f"schet-{ext_number}.pdf")
        if submit:
            inv = invoice_service.submit(sn, inv.id, expected_version=None,
                                         counterparty_confirmed=True)
        return inv

    @staticmethod
    def _attach(doc, file_type: str, filename: str) -> None:
        """Файл документа (договор и счёт обязательны для отправки, ТЗ §21) —
        загрузкой из кода от имени автора."""
        core_files.attach(doc, file_type, data=DEMO_PDF, filename=filename,
                          mime="application/pdf", actor_id=doc.author_id)

    def _fd_decide(self, slug: str, inv: Invoice, decision: str) -> None:
        """Решение ФД — доменной ручкой от имени держателя ждущей задачи:
        она ставит плановую дату и пишет журнал."""
        tasks = self._pending(Invoice.SIGNOFF_SUBJECT_TYPE, inv.pk)
        if not tasks:
            raise CommandError(f"Счёт {inv.number}: нет задачи ФД")
        decisions.decide(Actor.for_user(tasks[0]["user_id"], company=slug), inv.id,
                         decision=decision)

    # ── очистка ─────────────────────────────────────────────────────────

    def _purge(self) -> None:
        project_ids = list(projects.project_ids_by_code([code for code, _ in PROJECTS]).values())
        if not project_ids:
            self.stdout.write("Демо-проектов нет — удалять нечего.")
        invoices = Invoice.objects.filter(project_id__in=project_ids)
        agreements = Agreement.objects.filter(project_id__in=project_ids)
        requests = PurchaseRequest.objects.filter(project_id__in=project_ids)
        accountable = AccountableFundsRequest.objects.filter(project_id__in=project_ids)
        subjects = (
            (Invoice.SIGNOFF_SUBJECT_TYPE, invoices),
            (Agreement.SIGNOFF_SUBJECT_TYPE, agreements),
            (PurchaseRequest.SIGNOFF_SUBJECT_TYPE, requests),
            (AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE, accountable),
        )
        processes = sum(signoff.purge_processes(subject, [str(pk) for pk in
                                                          rows.values_list("pk", flat=True)])
                        for subject, rows in subjects)
        report_ids = [str(pk) for pk in accountable.values_list("reports__pk", flat=True) if pk]
        processes += signoff.purge_processes("bpp.advance_report", report_ids)
        counts = {
            "счета": invoices.count(), "договоры": agreements.count(),
            "заявки": requests.count(), "подотчёт": accountable.count(),
        }
        for doc in [*invoices, *agreements]:
            core_files.owner_deleted(doc, actor_id=None)
        invoices.delete()
        # Допсоглашения держат основной договор (PROTECT) — сначала они.
        agreements.filter(parent_agreement__isnull=False).delete()
        agreements.delete()
        for req in requests:
            core_files.owner_deleted(req, actor_id=None)
        requests.delete()
        for acc in accountable:
            for report in acc.reports.all():
                core_files.owner_deleted(report, actor_id=None)
                report.delete()
        accountable.delete()
        budgets_count = Budget.objects.filter(project_id__in=project_ids).count()
        Budget.objects.filter(project_id__in=project_ids).delete()
        for project_id in project_ids:
            projects.delete_project(project_id)
        kept = []
        for body, name, *_ in COUNTERPARTIES:
            row = Counterparty.objects.filter(country_code="KZ",
                                              reg_number=bin_with_checksum(body)).first()
            if row is None:
                continue
            if row.agreements.exists() or row.invoices.exists():
                kept.append(name)
                continue
            row.bank_accounts.all().delete()
            row.delete()
        self.stdout.write(
            "Удалено: " + ", ".join(f"{k} — {v}" for k, v in counts.items())
            + f", бюджеты — {budgets_count}, проекты — {len(project_ids)}, "
              f"процессы согласования — {processes}.")
        if kept:
            self.stdout.write("Оставлены контрагенты с чужими документами: " + ", ".join(kept))
