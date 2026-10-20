"""Демо-данные тендерного модуля для стенда и этапа 5 (сравнение, выбор).

    manage.py seed_tender_demo --company <slug> [--buyer ID]

Заводит то, чего на стенде нет, — заявки, тендеры, участников и поданные
предложения в состояниях, нужных этапу 5, — теми же сервисами, что и экраны
и портал. Каждый сценарий узнаётся по метке в обосновании заявки
(``[демо-тендер:<ключ>]``): есть — пропускается, поэтому повторный запуск
дозаводит только недостающее.

Сценарии:

- ``к-вскрытию`` — заявка с тремя позициями, доставкой и СМР (три ЗЗ в БЗО —
  основные позиции, доставка, СМР, — утверждены держателями задач маршрута),
  тендер со сроком в прошлом и пятью участниками: полное предложение в KZT с
  НДС 16 % (доставка в цене), частичное в USD без НДС с аналогом и
  предоплатой, полное у потенциального поставщика без НДС с постоплатой
  15 дней, отказ с причиной, молчание.
  Готов к вскрытию и сравнению (T5.1);
- ``приём-идёт`` — тендер на приёме со сроком через 5 дней, у одного участника
  черновик предложения (его не видно до вскрытия);
- ``без-предложений`` — тендер со сроком в прошлом без единого предложения:
  вскрытие переведёт его в «Не состоялся».

Нужны: демо-проект ``ДЕМО-01`` с утверждённым бюджетом
(``seed_bpp_demo --company <slug>``), роли ``tender-*``
(``tender_assign_roles``) и маршрут заявки БЗО (``bpp_configure_routes``).
Чего нет — команда говорит, что сделать, и ничего не пишет.

- Срок приёма: публикация требует срок в будущем, а предложения подаются до
  срока, поэтому у сценариев «к вскрытию» и «без предложений» срок после
  подачи сдвигается в прошлое прямо в таблице — это единственная запись
  мимо сервисов.
- Уведомления — как при ручной работе: согласующие ЗЗ получат колокольчик.
- Удаления нет: демо-документы БЗО (ЗЗ, резервы бюджета) и журнал не
  стираются; стенд пересоздаётся целиком.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.access import interface as access
from apps.bpp import interface as bpp
from apps.files import interface as files
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.tender.models import Invitation, Tender, TenderRequest
from apps.tender.services.portal import access as portal_access
from apps.tender.services.portal import offers
from apps.tender.services.portal.actor import portal_actor
from apps.tender.services.requests import crud, submit
from apps.tender.services.suppliers import contacts, prospects
from apps.tender.services.tenders import invitations, tenders
from apps.tender.services.tenders.ctx import Ctx
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

PROJECT = "ДЕМО-01"
MARK = "[демо-тендер:{}]"
MAX_DECISIONS = 12
#: Минимальный PDF — КП участника (подсистема файлов проверяет сигнатуру).
DEMO_PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF\n")
#: Демо-контрагенты БЗО (``seed_bpp_demo``) и почта их контактов для тендера.
COUNTERPARTIES = (("Демо Металл", "sales@demo-metall.kz"),
                  ("Демо Электро", "tender@demo-electro.kz"))
#: Потенциальные поставщики: имя, почта, рег. номер (пусто — без БИН).
PROSPECTS = (("ТОО «Демо Снаб»", "offers@demo-snab.kz", "990340000016"),
             ("ИП «Демо Склад»", "sklad@demo-sklad.kz", ""),
             ("ТОО «Демо Молчун»", "info@demo-silent.kz", ""))
#: Кто покупает: закупщик тендера, он же СН в БЗО (статьи «Снабжения»).
BUYER_NODES = (("tender.requests", "create"), ("tender.tenders", "create"),
               ("bpp.requests", "create"), ("bpp.articles.supply", "view"))


def _ctx(user_id: int, slug: str) -> Ctx:
    return Ctx(SimpleNamespace(user_id=int(user_id), is_superuser=False), slug)


def _portal(invitation: Invitation) -> SimpleNamespace:
    """Контекст портала без HTTP: привязка устройства не нужна сервису
    предложения (её проверяет вьюха), ссылка — строка этого приглашения."""
    inv = Invitation.objects.get(pk=invitation.pk)
    return SimpleNamespace(invitation=inv, tender=inv.tender, binding=None, ip=None,
                           user_agent="seed_tender_demo")


class Command(BaseCommand):
    help = "Демо-данные тендерного модуля: заявки, тендеры, участники, предложения (этап 5)"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug компании")
        parser.add_argument("--buyer", type=int, default=None,
                            help="id закупщика (по умолчанию — держатель ролей tender-buyer и bpp-sn)")

    # ── вход ────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        slug = options["company"]
        with use_company(slug):
            buyer = options["buyer"] or self._buyer(slug)
            project_id = self._project()
            if not signoff.has_active_route("bpp.purchase_request"):
                raise CommandError("Не настроен маршрут заявки на закупку БЗО — сначала "
                                   "manage.py bpp_configure_routes --company <slug>.")
            ctx = _ctx(buyer, slug)
            for key, scenario in (("к-вскрытию", self._to_open),
                                  ("приём-идёт", self._intake),
                                  ("без-предложений", self._no_offers)):
                if TenderRequest.objects.filter(justification__contains=MARK.format(key)).exists():
                    self.stdout.write(f"{key}: уже есть — пропущен")
                    continue
                try:
                    with transaction.atomic():
                        tender = scenario(ctx, project_id, key)
                except DomainError as exc:
                    raise CommandError(f"{key}: {exc.code}: {exc.message} — сценарий не "
                                       f"записан") from exc
                self.stdout.write(self.style.SUCCESS(
                    f"{key}: тендер {tender.number} — {tender.get_status_display()}, "
                    f"срок {timezone.localtime(tender.deadline_at):%d.%m.%Y %H:%M}"))
        self.stdout.write(self.style.SUCCESS("Готово."))

    def _buyer(self, slug: str) -> int:
        holders = None
        for node, flag in BUYER_NODES:
            ids = set(access.holders_of(node, flag, slug))
            holders = ids if holders is None else holders & ids
        if not holders:
            raise CommandError("Нет закупщика с ролями tender-buyer и bpp-sn — "
                               "manage.py tender_assign_roles и bpp_assign_roles, или --buyer ID.")
        return min(holders)

    def _project(self) -> str:
        found = projects.project_ids_by_code([PROJECT])
        if PROJECT not in found:
            raise CommandError(f"Нет демо-проекта {PROJECT} с бюджетом — сначала "
                               f"manage.py seed_bpp_demo --company <slug>.")
        return found[PROJECT]

    # ── общее ───────────────────────────────────────────────────────────

    @staticmethod
    def _articles() -> tuple[str, str]:
        supply = refdata.active_articles("supply")
        if len(supply) < 2:
            raise CommandError("Нужны две действующие статьи группы «Снабжение».")
        return supply[0]["id"], supply[1]["id"]

    @staticmethod
    def _uom(code: str) -> str:
        uom = refdata.uom_id(code)
        if uom is None:
            raise CommandError(f"Нет единицы измерения {code} в справочнике (refdata/0002)")
        return uom

    def _approve_parts(self, request: TenderRequest) -> None:
        """Решения по ЗЗ принимают держатели ждущих задач — как в seed_bpp_demo."""
        for part in request.parts.exclude(bpp_request_id=None):
            for _ in range(MAX_DECISIONS):
                process = signoff.get_process_for("bpp.purchase_request", str(part.bpp_request_id))
                tasks = ([t for st in process["stages"] for t in st["tasks"]
                          if t["state"] == "pending"]
                         if process and process.get("state") == "pending" else [])
                if not tasks:
                    break
                result = signoff.decide_many(actor_id=tasks[0]["user_id"], items=[
                    {"task_id": tasks[0]["id"], "decision": "approve", "comment": ""}])[0]
                if not result.get("ok"):
                    raise CommandError(f"ЗЗ {part.bpp_number}: {result.get('error')}")
        request.refresh_from_db()
        if request.status != "approved":
            raise CommandError(f"Заявка {request.number} не утверждена ({request.status}) — "
                               f"проверьте маршрут заявки БЗО")

    def _request(self, ctx: Ctx, project_id: str, key: str, title: str, items: list[tuple],
                 **extra) -> TenderRequest:
        goods, _other = self._articles()
        need = timezone.localdate() + timedelta(days=30)
        draft = crud.create_draft(ctx, {
            "initiator_role": "sn", "project_id": project_id, "article_id": goods,
            "purchase_type": "goods", "need_date": need,
            "delivery_address": "Астана, ул. Кенесары 40, объект «Садовый квартал»",
            "justification": f"{title} {MARK.format(key)}",
            "items": [{"name": name, "specs": specs, "uom_id": self._uom(uom), "qty": str(qty),
                       "plan_price": str(price), "need_date": need}
                      for name, specs, uom, qty, price in items],
            **extra})
        sent = submit.submit(ctx, draft.id, expected_version=None)
        self._approve_parts(sent)
        return sent

    def _counterparty_ids(self, ctx: Ctx) -> list[dict]:
        """Участники-контрагенты: ``{counterparty_id, contact_id}`` — у демо-карточек
        БЗО почты нет, приглашение идёт на контакт тендерного модуля."""
        ids = []
        for name, email in COUNTERPARTIES:
            found = [c for c in bpp.search_counterparties(name, limit=5) if name in c["name"]]
            if not found:
                raise CommandError(f"Нет контрагента «{name}» — сначала seed_bpp_demo.")
            cid = found[0]["id"]
            mine = [c for c in contacts.list_contacts(ctx, cid) if c["email"] == email]
            contact = mine[0] if mine else contacts.create(
                ctx, {"counterparty_id": cid, "email": email, "name": "Отдел продаж",
                      "is_primary": True})
            ids.append({"counterparty_id": cid, "contact_id": contact["id"]})
        return ids

    @staticmethod
    def _prospect(ctx: Ctx, name: str, email: str, reg: str):
        from apps.tender.models import SupplierProspect
        row = SupplierProspect.objects.filter(email=email).first()
        return row or prospects.create(ctx, {"name": name, "email": email, "reg_number": reg,
                                             "country_code": "KZ"})

    def _tender(self, ctx: Ctx, request: TenderRequest, *, kind: str, advance_pct=None,
                postpay_days=None) -> Tender:
        tender = tenders.create(ctx, {
            "request_id": str(request.id), "currency_code": "KZT",
            "deadline_at": timezone.now() + timedelta(days=5),
            "delivery_terms": "DAP Астана, разгрузка силами поставщика"})
        tenders.set_payment_scheme(ctx, tender.id, kind=kind, advance_pct=advance_pct,
                                   postpay_days=postpay_days)
        return tender

    def _invite(self, ctx: Ctx, tender: Tender, party: dict) -> Invitation:
        row = invitations.add(ctx, tender.id, party)
        return Invitation.objects.get(pk=row["id"])

    def _publish(self, ctx: Ctx, tender: Tender) -> None:
        tender.refresh_from_db()
        tenders.publish(ctx, tender.id, expected_version=tender.version)

    @staticmethod
    def _close(tender: Tender) -> None:
        """Срок — в прошлое (единственная запись мимо сервисов, см. докстринг)."""
        Tender.objects.filter(pk=tender.pk).update(
            deadline_at=timezone.now() - timedelta(hours=1))
        tender.refresh_from_db()

    @staticmethod
    def _offer(invitation: Invitation, data: dict, *, send: bool = True,
               with_file: bool = True) -> None:
        ctx = _portal(invitation)
        version = offers.offer_view(ctx)["version"]
        draft = offers.save_draft(ctx, {"version": version, **data})
        if with_file:
            try:
                files.attach_bytes(offers.OFFER_OWNER, draft.pk, file_type=offers.OFFER_FILE_TYPE,
                                   data=DEMO_PDF, filename="КП.pdf", mime="application/pdf",
                                   actor_id=portal_actor())
            except files.FilesError:
                pass     # антивирус стенда выключен или молчит — КП без файла
        if send:
            ctx = _portal(invitation)
            offers.submit(ctx, {"version": offers.offer_view(ctx)["version"],
                                "pd_consent": True})

    @staticmethod
    def _lines(request: TenderRequest, rows: list[tuple]) -> list[dict]:
        """``rows`` — по позициям заявки: ``(цена | None, кол-во | None, аналог)``;
        ``None`` в цене — позицию не предлагает."""
        items = list(request.items.order_by("line_no"))
        out = []
        for item, (price, qty, analog) in zip(items, rows):
            if price is None:
                out.append({"item_id": str(item.pk), "participates": False})
                continue
            out.append({"item_id": str(item.pk), "participates": True, "price": str(price),
                        "qty": str(qty if qty is not None else item.qty),
                        "delivery_date": timezone.localdate() + timedelta(days=21),
                        "is_analog": bool(analog), "analog_note": analog or ""})
        return out

    # ── сценарии ────────────────────────────────────────────────────────

    def _to_open(self, ctx: Ctx, project_id: str, key: str) -> Tender:
        _goods, other = self._articles()
        request = self._request(ctx, project_id, key, "Металлопрокат для каркаса рампы", [
            ("Швеллер 12П", "ГОСТ 8240-97, ст3пс", "t", "10", "245000"),
            ("Уголок 50×5", "ГОСТ 8509-93", "t", "4", "215000"),
            ("Лист г/к 4 мм", "ГОСТ 19903-2015, 1500×6000", "t", "2", "285000"),
        ], needs_delivery=True, delivery_article_id=other, delivery_plan_amount="350000",
            needs_works=True, works_scope="Монтаж металлокаркаса рампы",
            works_article_id=other, works_plan_amount="1200000", allow_analogs=True)
        tender = self._tender(ctx, request, kind="advance", advance_pct="30")
        metall, electro = self._counterparty_ids(ctx)
        snab = self._prospect(ctx, *PROSPECTS[0])
        sklad = self._prospect(ctx, *PROSPECTS[1])
        silent = self._prospect(ctx, *PROSPECTS[2])
        invited = [self._invite(ctx, tender, metall),
                   self._invite(ctx, tender, electro),
                   self._invite(ctx, tender, {"prospect_id": str(snab.pk)}),
                   self._invite(ctx, tender, {"prospect_id": str(sklad.pk)}),
                   self._invite(ctx, tender, {"prospect_id": str(silent.pk)})]
        self._publish(ctx, tender)
        a, b, c, d, _e = invited
        valid = timezone.localdate() + timedelta(days=45)
        # A: всё в KZT с НДС, доставка в цене, СМР суммой, аванс 30 %.
        self._offer(a, {
            "currency_code": "KZT", "with_vat": True, "vat_rate": "16", "valid_until": valid,
            "lines": self._lines(request, [("238000", None, ""), ("219000", None, ""),
                                           ("279000", None, "")]),
            "extras": {"delivery": {"included_in_price": True},
                       "works": {"amount": "1150000", "included_in_price": False,
                                 "note": "Монтаж за 12 рабочих дней"}},
            "payment_scheme": {"kind": "advance", "advance_pct": "30"}})
        # B: две позиции из трёх, USD без НДС, аналог уголка.
        self._offer(b, {
            "currency_code": "USD", "with_vat": False, "valid_until": valid,
            "lines": self._lines(request, [("452", None, ""), ("398", "3", "Уголок 50×5 ст09Г2С"),
                                           (None, None, "")]),
            "extras": {"delivery": {"amount": "640", "included_in_price": False,
                                    "note": "Доставка из Алматы, 3 дня"},
                       "works": {"amount": "2100", "included_in_price": False,
                                 "note": "Монтаж своей бригадой"}},
            "payment_scheme": {"kind": "prepay"}})
        # C: потенциальный поставщик, не плательщик НДС, постоплата 15 дней.
        self._offer(c, {
            "currency_code": "KZT", "with_vat": False, "valid_until": valid,
            "extra_terms": "Гарантия на монтаж 12 месяцев",
            "lines": self._lines(request, [("262000", None, ""), ("229000", None, ""),
                                           ("301000", None, "")]),
            "extras": {"delivery": {"amount": "280000", "included_in_price": False},
                       "works": {"amount": "1340000", "included_in_price": False,
                                 "note": "Монтаж, сварка, окраска"}},
            "payment_scheme": {"kind": "postpay", "postpay_days": 15},
            "requisites": {"name": "ТОО «Демо Снаб»", "country_code": "KZ",
                           "reg_number": PROSPECTS[0][2], "is_vat_payer": False,
                           "contact_name": "Сейткали А.", "phone": "+77010000001",
                           "email": PROSPECTS[0][1]}})
        # D: отказ с причиной; E молчит — при вскрытии станет «Срок истёк».
        decliner = _portal(d)
        offers.decline(decliner, {"reason": "Нет нужного проката на складе до конца месяца"},
                       event=lambda kind, meta: portal_access.log_event(
                           decliner.invitation, kind, user_agent="seed_tender_demo", meta=meta))
        self._close(tender)
        return tender

    def _intake(self, ctx: Ctx, project_id: str, key: str) -> Tender:
        request = self._request(ctx, project_id, key, "Кабельная продукция секции 2", [
            ("Кабель ВВГнг-LS 3×2,5", "ГОСТ 31996-2012", "m", "800", "980"),
            ("Кабель ВВГнг-LS 5×4", "ГОСТ 31996-2012", "m", "300", "2650"),
        ])
        tender = self._tender(ctx, request, kind="prepay")
        metall, electro = self._counterparty_ids(ctx)
        first = self._invite(ctx, tender, electro)
        self._invite(ctx, tender, metall)
        self._publish(ctx, tender)
        self._offer(first, {
            "currency_code": "KZT", "with_vat": True, "vat_rate": "16",
            "lines": self._lines(request, [("955", None, ""), (None, None, "")])},
            send=False, with_file=False)
        tender.refresh_from_db()
        return tender

    def _no_offers(self, ctx: Ctx, project_id: str, key: str) -> Tender:
        request = self._request(ctx, project_id, key, "Анкерные болты фундамента", [
            ("Болт фундаментный М24×800", "ГОСТ 24379.1-2012", "pcs", "64", "4200"),
        ])
        tender = self._tender(ctx, request, kind="postpay", postpay_days=10)
        _metall, electro = self._counterparty_ids(ctx)
        self._invite(ctx, tender, electro)
        self._publish(ctx, tender)
        self._close(tender)
        return tender
