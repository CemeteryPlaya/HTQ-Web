"""Дашборд D-01 «Оплаты» (ТЗ §11.5, REQ-018; план этапа 4 A, задача 5 — A4.3).

Показатели — ссылки на отфильтрованный реестр счетов L-06. Чтобы число на
карточке и строки реестра по её ссылке не расходились, показатель считается
НЕ своей выборкой, а выборкой самого реестра — ``invoices.read.visible`` с
теми же фильтрами, что уходят в ссылку (``?tab=…``, ``status``,
``recon_status``, ``bank_date_from``/``bank_date_to``, ``bank_wait_days``,
D-S4-8). Видимость счетов — тоже реестра (СН и ПМ — свои; держатели
дашборда ФД, ТД, ОД, ГД, БУХ видят все).

Показатели (D-S4-5, статусы после D-13):

* ``fd`` — «На рассмотрении ФД», вкладка ``fd``;
* ``to_pay`` — «К оплате» + «Оплачено частично», вкладка ``to_pay``;
* ``awaiting_docs`` — «Ждут закрывающих», вкладка ``awaiting_docs``;
* ``bank_unconfirmed`` — вкладка ``bank_unconfirmed`` и последняя
  неотменённая отметка БУХ по дате оплаты старше 3 рабочих дней (Пн–Пт без
  праздников, как метрика этапа 3);
* ``full`` / ``underpaid`` / ``overpaid`` — статус сверки ``full`` /
  ``partial`` / ``overpaid``; сумма недоплаты — Σ(сумма − оплачено по банку),
  переплаты — Σ(оплачено по банку − сумма), в KZT по курсу счёта;
* ``no_mark`` — «Платёж есть, отметки БУХ нет»: статус сверки ≠ «Нет данных
  банка» и статус счёта не из группы «Оплачено» (``PAID_GROUP`` — все
  статусы, где у счёта есть отметка оплаты БУХ, включая «Оплачено
  частично»). Вкладка ``bank_mismatch`` уже этого (только частичные и
  переплаты), поэтому ссылка — фильтрами ``status`` и ``recon_status``;
* ``unmatched`` — строки выписки «Не сопоставлена» загрузок «Загружена» и
  «Сверена» за период; ссылка — реестр загрузок «Оплаты факт» (``/bpp/bank``)
  с тем же периодом (``period_from``/``period_to`` — загрузки, чей период
  выписки пересекается с ним), и только тому, кто его видит (``bpp.bank``
  view — ФД, БУХ), остальным ``null``. Число со строками реестра загрузок
  не сравнивается: там загрузки, а не строки.

Период (D-S4-6) — по дате платежа в выписке и только у банковских
показателей (``full``, ``underpaid``, ``overpaid``, ``no_mark``,
``unmatched``) и графиков: он уходит в ссылку как ``bank_date_from`` /
``bank_date_to``. Очереди счетов — на текущий момент, без периода.

Фильтры проекта, статьи, контрагента и автора счёта — у всех показателей
по счетам и в их ссылках. Несопоставленная строка выписки счёта не имеет:
к ней применяется только контрагент — по БИН получателя.

**Рубильники подмодулей** (как ``digest.py``): выключен у компании
``bpp_invoices`` — показателей по счетам, авторов и графиков оплат нет вовсе
(их ссылки отвечали бы 503); выключен ``bpp_bank`` — нет показателей, которые
пишет сверка (``bank_unconfirmed``, ``full``, ``underpaid``, ``overpaid``,
``no_mark``), ``unmatched``, графиков оплат, а ``paid_fact`` у статей —
``null``; выключен ``bpp_budget`` — статей нет. Пропавший показатель не
отдаётся нулём: «не считали» и «ничего нет» не должны выглядеть одинаково.
Поэтому состояние рубильников отдаётся и явно — ``sections`` ``{invoices,
bank, budget}``: экран пишет «подмодуль выключен», а не «данных нет».

**Авторы** (фильтр «Автор счёта», ТЗ §11.5) — ``authors``: авторы счетов,
видимых пользователю по правилам реестра, без остальных фильтров дашборда
(список не прыгает при их смене), имена — ``users.interface``. Кадровый
список сотрудников для этого не годится: у ролей дашборда нет прав ``hr``.

**Всё считается агрегатами SQL**, без кэша (ТЗ: свежие цифры при каждом
открытии). Деньги — ``Decimal``: перевод в KZT — ``ROUND(сумма × курс, 2)``
по строке в запросе (Postgres округляет ``numeric`` от нуля — для
положительных сумм это ``ROUND_HALF_UP``), затем ``SUM``. «Оплачено по
банку» — только действующие сопоставления (``bank.recon.active_matches``,
D-S4-1). Сумма сопоставления — в валюте счёта (строка в другой валюте уходит
на проверку, D-S4-2), в KZT её переводит курс счёта (CALC-012).

**Нет курса у счёта в валюте** — как ``amount_kzt`` в остальном модуле
(``invoices.recalc``: курса НБРК нет — сумма в KZT пустая, ``Σ amount_kzt``
реестра её не считает): сумма такого счёта в тенге — ``NULL`` и в KZT-итоги
не входит, а не считается тенге. Штатно после отправки курс есть всегда
(иначе ``E-REF-05``). У несопоставленной строки выписки в валюте курс — НБРК
на дату платежа (``refdata.exchange_rate``), нет курса — строка в сумму не
входит (в ``count`` — входит).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, Greatest, NullIf, Round, TruncWeek
from django.utils import timezone

from apps.bpp.models import (
    BankImportStatus,
    BankStatementLine,
    Budget,
    BudgetLine,
    Counterparty,
    InvoiceStatus,
    LineMatchStatus,
    ReconStatus,
)
from apps.bpp.services.actor import Actor
from apps.bpp.services.bank import recon as bank_recon
from apps.bpp.services.budget import committed as committed_calc
from apps.bpp.services.invoices import read as registry
from apps.bpp.services.money import money
from apps.core.services import service_enabled
from apps.refdata import interface as refdata
from apps.users import interface as users

ZERO = Decimal("0.00")
KZT = "KZT"
_MONEY = DecimalField(max_digits=18, decimal_places=2)

#: Адрес реестра счетов на фронте; показатель по счетам ведёт сюда с фильтрами.
REGISTRY_URL = "/bpp/invoices"
#: Экран «Оплаты факт» — реестр загрузок выписок.
BANK_URL = "/bpp/bank"

#: «Банк не подтвердил > 3 раб. дней» (ТЗ §11.5 [У], §27 «Через 3 раб. дня»).
BANK_WAIT_WORKING_DAYS = 3
#: Топ контрагентов по оплатам (ТЗ §11.5).
TOP_COUNTERPARTIES = 10

INVOICES = "bpp_invoices"
BANK = "bpp_bank"
BUDGET = "bpp_budget"

#: Статусы, в которых у счёта есть отметка оплаты БУХ (D-S4-5).
PAID_GROUP = (InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID, InvoiceStatus.AWAITING_DOCS,
              InvoiceStatus.DOCS_PROVIDED, InvoiceStatus.CLOSED)
NO_MARK_STATUSES = tuple(value for value in InvoiceStatus.values if value not in PAID_GROUP)
#: «Платёж есть» — любой статус сверки, кроме «Нет данных банка».
HAS_BANK_DATA = tuple(value for value in ReconStatus.values if value != ReconStatus.NO_DATA)
#: Строки, которые сверка уже видела: разбор закончен, загрузка не отменена.
_LINE_IMPORT_STATUSES = (BankImportStatus.LOADED, BankImportStatus.RECONCILED)


@dataclass(frozen=True)
class Filters:
    """Фильтры дашборда (ТЗ §11.5): период по дате платежа, проект, статья,
    контрагент, автор счёта. Ключи — строки UUID, как в адресе реестра."""

    period_from: date | None = None
    period_to: date | None = None
    project_id: str | None = None
    article_id: str | None = None
    counterparty_id: str | None = None
    author_id: int | None = None

    def registry(self) -> dict:
        """Фильтры выборки реестра (``invoices.read.visible``) без вкладки."""
        return {"project_ids": [self.project_id] if self.project_id else [],
                "article_ids": [self.article_id] if self.article_id else [],
                "counterparty_id": self.counterparty_id,
                "author_id": self.author_id}

    def bank_period(self) -> dict:
        return {"bank_date_from": self.period_from.isoformat() if self.period_from else None,
                "bank_date_to": self.period_to.isoformat() if self.period_to else None}

    def query(self) -> list[tuple[str, str]]:
        """Те же фильтры параметрами адреса реестра — имена параметров ручки
        ``GET invoices``."""
        pairs = [("project_id", self.project_id), ("article_id", self.article_id),
                 ("counterparty_id", self.counterparty_id),
                 ("author_id", None if self.author_id is None else str(self.author_id))]
        return [(key, value) for key, value in pairs if value]

    def as_dict(self) -> dict:
        return {"period_from": self.period_from, "period_to": self.period_to,
                "project_id": self.project_id, "article_id": self.article_id,
                "counterparty_id": self.counterparty_id, "author_id": self.author_id}


def in_kzt(value, *, invoice: str = ""):
    """Выражение: сумма в валюте счёта → KZT по курсу счёта (CALC-012), по
    строке, ``ROUND(…, 2)``. ``invoice`` — путь до счёта (``"invoice__"`` из
    сопоставления, ``""`` из самого счёта). Счёт в валюте без курса — ``NULL``
    (как его ``amount_kzt``), ``SUM`` его пропускает."""
    return Case(
        When(**{f"{invoice}currency_code": KZT}, then=value),
        When(**{f"{invoice}rate__isnull": False},
             then=Round(value * F(f"{invoice}rate"), 2)),
        default=Value(None), output_field=_MONEY)


def _total(value) -> Decimal:
    return money(value) if value is not None else ZERO


# ── показатели ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Spec:
    key: str
    label: str
    tab: str | None = None
    statuses: tuple[str, ...] = ()
    recon: tuple[str, ...] = ()
    bank_period: bool = False
    wait_days: int | None = None
    #: ``None`` — Σ сумм в KZT; ``"under"``/``"over"`` — недоплата/переплата.
    gap: str | None = None
    #: Подмодули, без которых показателя нет (рубильник у компании).
    needs: tuple[str, ...] = (INVOICES,)


_WITH_BANK = (INVOICES, BANK)

INDICATORS: tuple[_Spec, ...] = (
    _Spec("fd", "Счета на решении ФД", tab="fd"),
    _Spec("to_pay", "К оплате", tab="to_pay"),
    _Spec("awaiting_docs", "Ждут закрывающих", tab="awaiting_docs"),
    _Spec("bank_unconfirmed", "Отмечено «Оплачено», банк не подтвердил > 3 раб. дней",
          tab="bank_unconfirmed", wait_days=BANK_WAIT_WORKING_DAYS, needs=_WITH_BANK),
    _Spec("full", "Оплачено полностью по банку", recon=(ReconStatus.FULL,), bank_period=True,
          needs=_WITH_BANK),
    _Spec("underpaid", "Оплачено частично, недоплата", recon=(ReconStatus.PARTIAL,),
          bank_period=True, gap="under", needs=_WITH_BANK),
    _Spec("overpaid", "Переплата", recon=(ReconStatus.OVERPAID,), bank_period=True,
          gap="over", needs=_WITH_BANK),
    _Spec("no_mark", "Платёж есть, отметки БУХ нет", statuses=NO_MARK_STATUSES,
          recon=HAS_BANK_DATA, bank_period=True, needs=_WITH_BANK),
)
UNMATCHED_LABEL = "Несопоставленные списания"


def _spec_filters(spec: _Spec, filters: Filters) -> dict:
    out = filters.registry()
    if spec.tab:
        out["tab"] = spec.tab
    if spec.statuses:
        out["statuses"] = list(spec.statuses)
    if spec.recon:
        out["recon_statuses"] = list(spec.recon)
    if spec.bank_period:
        out.update(filters.bank_period())
    if spec.wait_days is not None:
        out["bank_wait_days"] = spec.wait_days
    return out


def _spec_link(spec: _Spec, filters: Filters) -> str:
    pairs: list[tuple[str, str]] = []
    if spec.tab:
        pairs.append(("tab", spec.tab))
    pairs += [("status", value) for value in spec.statuses]
    pairs += [("recon_status", value) for value in spec.recon]
    pairs += filters.query()
    if spec.bank_period:
        pairs += [(key, value) for key, value in filters.bank_period().items() if value]
    if spec.wait_days is not None:
        pairs.append(("bank_wait_days", str(spec.wait_days)))
    return f"{REGISTRY_URL}?{urlencode(pairs)}" if pairs else REGISTRY_URL


def _amount_expr(spec: _Spec):
    if spec.gap is None:
        return F("amount_kzt")
    diff = (F("amount") - F("paid_bank_amount") if spec.gap == "under"
            else F("paid_bank_amount") - F("amount"))
    return in_kzt(Greatest(diff, Value(ZERO, output_field=_MONEY), output_field=_MONEY))


def _indicator(actor: Actor, spec: _Spec, filters: Filters) -> dict:
    rows = registry.visible(actor, _spec_filters(spec, filters)).order_by()
    agg = rows.aggregate(count=Count("pk"), total=Sum(_amount_expr(spec)))
    return {"key": spec.key, "label": spec.label, "count": agg["count"],
            "amount": _total(agg["total"]), "link": _spec_link(spec, filters)}


def _unmatched_lines(filters: Filters):
    rows = BankStatementLine.objects.filter(
        match_status=LineMatchStatus.UNMATCHED, cancelled_at__isnull=True,
        bank_import__status__in=_LINE_IMPORT_STATUSES)
    if filters.period_from:
        rows = rows.filter(doc_date__gte=filters.period_from)
    if filters.period_to:
        rows = rows.filter(doc_date__lte=filters.period_to)
    if filters.counterparty_id:
        reg = (Counterparty.objects.filter(pk=filters.counterparty_id)
               .values_list("reg_number", flat=True).first())
        rows = rows.filter(recipient_bin=reg) if reg else rows.none()
    return rows.order_by()


def _unmatched(actor: Actor, filters: Filters) -> dict:
    rows = _unmatched_lines(filters)
    agg = rows.aggregate(count=Count("pk"),
                         kzt=Sum("amount", filter=Q(currency=KZT)))
    amount = _total(agg["kzt"])
    # Валютные строки (у счетов организации в валюте) — по курсу НБРК на дату
    # платежа; группы (валюта, дата) — обычно ни одной.
    foreign = (rows.exclude(currency=KZT).values("currency", "doc_date")
               .annotate(total=Sum("amount")))
    for group in foreign:
        rate = refdata.exchange_rate(group["currency"], group["doc_date"])
        if rate is not None:
            amount += money(group["total"] * rate)
    link = None
    if actor.can("bpp.bank", "view"):
        # Реестр загрузок понимает только период (загрузки, чей период
        # выписки пересекается с ним) — других параметров в ссылке нет.
        pairs = [(key, value.isoformat()) for key, value in
                 (("period_from", filters.period_from), ("period_to", filters.period_to))
                 if value]
        link = f"{BANK_URL}?{urlencode(pairs)}" if pairs else BANK_URL
    return {"key": "unmatched", "label": UNMATCHED_LABEL, "count": agg["count"],
            "amount": amount, "link": link}


def indicators(actor: Actor, filters: Filters) -> list[dict]:
    """``[{key, label, count, amount, link}]`` — порядок ТЗ §11.5; показатели
    выключенных у компании подмодулей не отдаются."""
    out = [_indicator(actor, spec, filters) for spec in INDICATORS
           if all(service_enabled(name) for name in spec.needs)]
    if service_enabled(BANK):
        out.append(_unmatched(actor, filters))
    return out


def sections() -> dict:
    """``{invoices, bank, budget}`` — включены ли у компании подмодули, от
    которых зависят части дашборда: экран отличает «подмодуль выключен» от
    «данных нет». Показатели и графики уже отданы по ним же."""
    return {"invoices": service_enabled(INVOICES), "bank": service_enabled(BANK),
            "budget": service_enabled(BUDGET)}


def authors(actor: Actor) -> list[dict]:
    """``[{id, name}]`` — авторы счетов, видимых пользователю по правилам
    реестра (``invoices.read.visible`` без фильтров), для фильтра «Автор
    счёта»; по имени. Пользователя нет — ``name: null`` (фильтр по нему всё
    равно работает). Выключен ``bpp_invoices`` — пусто."""
    if not service_enabled(INVOICES):
        return []
    ids = sorted(set(registry.visible(actor).order_by()
                     .values_list("author_id", flat=True).distinct()) - {None})
    names = {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}
    out = [{"id": user_id, "name": names.get(user_id)} for user_id in ids]
    out.sort(key=lambda row: (row["name"] is None, (row["name"] or "").casefold(), row["id"]))
    return out


# ── графики ─────────────────────────────────────────────────────────────

def article_chart(project_id, *, actor: Actor, article_id: str | None = None) -> list[dict]:
    """``[{article_id, code, name, limit, committed, paid_fact}]`` — статьи
    действующей версии бюджета проекта (ТЗ §11.5 «Лимит / Задействовано /
    Оплачено факт»; последнее — ``bank.recon.paid_fact_by_article``, CALC-007;
    ``null`` при выключенном у компании ``bpp_bank``). Бюджета нет или
    ``bpp_budget`` выключен — пусто. ``actor`` обязателен: статьи — только
    групп, открытых пользователю (BR-010), как в карточке бюджета."""
    if not project_id or not service_enabled(BUDGET):
        return []
    budget = Budget.objects.filter(project_id=project_id).first()
    if budget is None or not budget.active_version_id:
        return []
    lines = BudgetLine.objects.filter(version_id=budget.active_version_id)
    if article_id:
        lines = lines.filter(article_id=article_id)
    lines = list(lines)
    briefs = refdata.article_brief([str(line.article_id) for line in lines])
    committed = committed_calc.committed_by_article(project_id)
    paid = bank_recon.paid_fact_by_article(project_id) if service_enabled(BANK) else None
    out = []
    for line in lines:
        key = str(line.article_id)
        brief = briefs.get(key)
        if not actor.sees_article(brief):
            continue
        out.append({"article_id": key, "code": brief.get("code"),
                    "name": brief.get("name") or key,
                    "limit": line.limit_amount, "committed": committed.get(key, ZERO),
                    "paid_fact": None if paid is None else paid.get(key, ZERO)})
    out.sort(key=lambda row: (row["code"] or "", row["name"]))
    return out


def _charts_enabled() -> bool:
    return service_enabled(INVOICES) and service_enabled(BANK)


def _paid_matches(actor: Actor, filters: Filters):
    """Действующие сопоставления (D-S4-1) по счетам выборки реестра за период
    по дате платежа (D-S4-6)."""
    invoices = registry.visible(actor, filters.registry()).order_by().values("pk")
    rows = bank_recon.active_matches().filter(invoice_id__in=invoices)
    if filters.period_from:
        rows = rows.filter(line__doc_date__gte=filters.period_from)
    if filters.period_to:
        rows = rows.filter(line__doc_date__lte=filters.period_to)
    return rows.order_by()


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_paid(actor: Actor, filters: Filters) -> list[dict]:
    """``[{week_start, amount}]`` — «Оплачено по банку» по неделям (Пн) даты
    платежа, в KZT (``TruncWeek`` Postgres — ISO-неделя с понедельника).
    Недели без платежей внутри периода — нулём, чтобы линия графика не
    перескакивала через них."""
    if not _charts_enabled():
        return []
    rows = (_paid_matches(actor, filters)
            .annotate(week=TruncWeek("line__doc_date"))
            .values("week").annotate(total=Sum(in_kzt(F("amount"), invoice="invoice__"))))
    by_week = {_week_start(row["week"]): _total(row["total"]) for row in rows}
    if not by_week and not (filters.period_from and filters.period_to):
        return []
    first = _week_start(filters.period_from) if filters.period_from else min(by_week)
    last = _week_start(filters.period_to) if filters.period_to else max(by_week)
    out = []
    week = first
    while week <= last:
        out.append({"week_start": week, "amount": by_week.get(week, ZERO)})
        week += timedelta(days=7)
    return out


def top_counterparties(actor: Actor, filters: Filters) -> list[dict]:
    """``[{counterparty_id, name, amount}]`` — топ-10 контрагентов по
    «Оплачено по банку» за период, в KZT; равные суммы — по имени (краткое,
    иначе полное — как ``counterparties.display_name``)."""
    if not _charts_enabled():
        return []
    name = Coalesce(NullIf(F("invoice__counterparty__short_name"), Value("")),
                    F("invoice__counterparty__name"))
    rows = (_paid_matches(actor, filters)
            .filter(invoice__counterparty__isnull=False)
            .values("invoice__counterparty_id")
            .annotate(name=name, total=Sum(in_kzt(F("amount"), invoice="invoice__")))
            .filter(total__isnull=False)
            .order_by("-total", "name")[:TOP_COUNTERPARTIES])
    return [{"counterparty_id": str(row["invoice__counterparty_id"]), "name": row["name"],
             "amount": _total(row["total"])} for row in rows]


# ── целиком ─────────────────────────────────────────────────────────────

def dashboard(actor: Actor, filters: Filters) -> dict:
    """GetPaymentDashboard (ТЗ §23, REQ-018): без кэша — ТЗ требует свежих
    цифр при каждом открытии и после каждой загрузки выписки."""
    return {
        "filters": filters.as_dict(),
        "sections": sections(),
        "authors": authors(actor),
        "indicators": indicators(actor, filters),
        "article_chart": article_chart(filters.project_id, actor=actor,
                                       article_id=filters.article_id),
        "weekly_paid": weekly_paid(actor, filters),
        "top_counterparties": top_counterparties(actor, filters),
        "as_of": timezone.now(),
    }
