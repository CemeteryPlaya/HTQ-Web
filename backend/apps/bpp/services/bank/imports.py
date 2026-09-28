"""Загрузка выписки банк-клиента (ТЗ §11.2, §11.3 п.1–3, §15.5, BR-075,
L-07; план этапа 3 A, задача 3 — A4.1, перенесена из этапа 4).

Два шага:

1. ``start_import`` — в запросе. Счёт организации действующий, файл не
   больше 20 МБ, расширение — формата шаблона счёта (E-IMP-01), быстрая
   проверка содержимого разборщиком (``precheck``: заголовок 1С — E-IMP-01,
   колонки шаблона — E-IMP-02, не больше 10 000 строк — E-IMP-03), период
   (из файла, если он его несёт, иначе из формы; «по» ≥ «с», не позже
   сегодня). Файл ложится в ``apps.files`` (владелец ``bpp.bank_import``,
   тип ``bank_statement``), строка ``BankImport`` — в статусе «Обрабатывается»,
   разбор ставится в очередь после фиксации транзакции.
2. ``run_import`` — в воркере (``tasks_bank.run_bank_import``). Полный разбор,
   только списания своего счёта, запись строк пачками по ``BATCH`` с
   ``ON CONFLICT DO NOTHING`` по ключу дубля, прогресс — в ``rows_done``.
   Итог — «Загружена»; отказ — «Ошибка загрузки» с причиной, а строки,
   успевшие записаться, отменяются (иначе они держали бы ключи дублей).

**Дубль** (BR-075) — «счёт организации + дата + № документа + сумма + БИН
получателя»: ``dedup_hash`` — SHA-256 от id счёта (не IBAN: IBAN счёта
организации можно поправить, пока по нему нет загрузок, а ключ строки не
должен от этого меняться — ``settings.update_account`` правку IBAN счёта
с загрузками отвергает). Уникальность — частичный индекс БД среди
неотменённых строк, поэтому и две одновременные загрузки одного файла не
дают второй строки: вставка проигравшей ждёт фиксации победившей и
пропускает её строки как дубли. Строки вставляются в порядке ключа — у всех
загрузок один порядок блокировок, взаимной блокировки нет.

Сверка (A4.2, этап 4) добавит статус «Сверена» и сопоставление строк; до
неё загрузка останавливается на «Загружена», строки — «Не сопоставлена»
(решение D-S3-2).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.bpp.models.bank import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    LineMatchStatus,
    OrgBankAccount,
    StatementFormat,
)
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.core.numbering import next_number
from apps.users import interface as users
from htqweb.errors import DomainError
from htqweb.tenancy import current_company

from . import templates
from .file_owner import FILE_TYPE
from .parsers import onec, tabular

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_TYPE",
    "BATCH",
    "DEFAULT_PAGE_SIZE",
    "MAX_MB",
    "card",
    "dedup_hash",
    "export_count",
    "export_rows",
    "get_import",
    "lines",
    "reap_stale",
    "registry",
    "run_import",
    "start_import",
]

AUDIT_TYPE = "bpp.bankimport"
NUMBER_PREFIX = "ВП"
NUMBER_WIDTH = 4
#: Файл выписки — не больше (ТЗ §11.2; тип ``bank_statement`` в справочнике
#: файлов — те же 20 МБ, nginx пускает на ``/api/bpp/v1/bank/`` до 21 МБ).
MAX_MB = 20
#: Строк выписки за одну вставку.
BATCH = 500
PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50
LINES_PAGE_SIZES = (25, 50, 100, 200)
#: Разбор, не закончившийся за столько минут, считается потерянным (воркер
#: убит пределом времени задачи ``CELERY_TASK_TIME_LIMIT`` = 5 мин, памятью
#: или перезапуском; рубильник ``bpp_bank`` выключили, пока задача ждала).
#: Втрое больше предела времени — живой разбор к этому сроку уже закончен.
STALE_MINUTES = 15
STALE_REASON = ("Загрузка прервана — повторите загрузку. Если ошибка повторится, "
                "обратитесь к администратору.")

#: Запись «Истории изменений» об итоге разбора.
_FINISHED = "loaded"
_FAILED = "failed"


# ── общие куски ─────────────────────────────────────────────────────────

def _invalid(field: str, message: str) -> DomainError:
    return DomainError("E-VAL-01", message, fields=[{"field": field, "message": message}])


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise _invalid(field, "Дата — в формате ГГГГ-ММ-ДД.") from None


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def dedup_hash(account_id, *, doc_date: date, doc_number: str, amount, recipient_bin: str
               ) -> str:
    """Ключ дубля строки выписки (BR-075): SHA-256 от «счёт организации +
    дата + № документа + сумма + БИН получателя». Номер — без крайних
    пробелов и регистра, сумма — с двумя знаками."""
    parts = (str(account_id), doc_date.isoformat(), " ".join(doc_number.split()).upper(),
             f"{amount:.2f}", "".join((recipient_bin or "").split()))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ── загрузка: запрос ───────────────────────────────────────────────────

def _active_account(account_id) -> OrgBankAccount:
    key = _as_uuid(account_id)
    account = (OrgBankAccount.objects.select_related("template").filter(pk=key).first()
               if key else None)
    if account is None or not account.is_active:
        raise _invalid("account_id", "Выберите действующий банковский счёт организации: "
                                     "этот не найден или переведён в архив.")
    if not account.template.is_active:
        raise _invalid("account_id", f"Шаблон выписки счёта {account.iban} в архиве. "
                                     f"Попросите администратора выбрать для счёта "
                                     f"действующий шаблон.")
    return account


def _size_error(name: str) -> DomainError:
    # Текст — как у файловой подсистемы (ТЗ §13.2): одна фраза на формат и размер.
    message = f"Файл {name} не загружен: допустимы TXT, XLSX, CSV до {MAX_MB} МБ"
    return DomainError("E-FIL-02", message, fields=[{"field": "file", "message": message}],
                       status=413)


def _precheck(content: bytes, name: str, account: OrgBankAccount) -> dict:
    template = account.template
    templates.check_extension(name, template)
    if template.format == StatementFormat.ONEC:
        return onec.precheck(content, account=account, encoding=template.encoding)
    return tabular.precheck(content, name=name, template=template)


def _period(period_from, period_to, found: dict) -> tuple[date, date, list[str]]:
    """Период выписки: из файла, если он его несёт (заголовок 1С), иначе из
    формы (ТЗ §11.2); «по» ≥ «с», не позже сегодня. Третье — предупреждение,
    если период из файла заменил другой, введённый в форме."""
    typed_from, typed_to = _date(period_from, "period_from"), _date(period_to, "period_to")
    start = found.get("period_from") or typed_from
    end = found.get("period_to") or typed_to
    notes = []
    if start and end and ((typed_from and typed_from != start)
                          or (typed_to and typed_to != end)):
        notes.append(f"Период взят из файла выписки: {_day(start)}–{_day(end)}. "
                     f"Период, указанный в форме, не учтён.")
    missing = [field for field, value in (("period_from", start), ("period_to", end))
               if value is None]
    if missing:
        message = "Укажите период выписки: в файле его нет."
        raise DomainError("E-VAL-01", message,
                          fields=[{"field": field, "message": message} for field in missing])
    if end < start:
        raise _invalid("period_to", "Дата «по» периода выписки не может быть раньше даты «с».")
    if end > timezone.localdate():
        raise _invalid("period_to", "Период выписки не может заканчиваться позже сегодняшнего "
                                    "дня.")
    return start, end, notes


def _overlaps(account: OrgBankAccount, start: date, end: date, exclude=None) -> list[str]:
    """Предупреждения ТЗ §11.2: период пересекается с прошлой загрузкой этого
    счёта — повторные операции отсекутся как дубли (BR-075)."""
    rows = (BankImport.objects
            .filter(account=account, period_from__lte=end, period_to__gte=start,
                    status__in=(BankImportStatus.PROCESSING, BankImportStatus.LOADED))
            .order_by("period_from", "created_at")
            .only("number", "period_from", "period_to"))  # без байтов ``source``
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    return [f"Период пересекается с загрузкой {row.number} "
            f"({_day(row.period_from)}–{_day(row.period_to)}) этого счёта: операции, "
            f"которые уже загружены, будут пропущены как дубли."
            for row in rows[:5]]


def start_import(*, account_id, upload, period_from=None, period_to=None, comment: str = "",
                 actor_id: int, request=None) -> tuple[BankImport, list[str]]:
    """Принять выписку и поставить разбор в очередь. Ответ — загрузка
    («Обрабатывается») и предупреждения: период из файла заменил период
    формы, период пересекается с прошлыми загрузками счёта."""
    account = _active_account(account_id)
    if upload is None:
        raise _invalid("file", "Выберите файл выписки.")
    name = (getattr(upload, "name", "") or "").strip() or "vypiska"
    if (getattr(upload, "size", 0) or 0) > MAX_MB * 1024 * 1024:
        raise _size_error(name)
    if hasattr(upload, "seek"):
        upload.seek(0)
    content = upload.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise _size_error(name)
    found = _precheck(content, name, account)
    start, end, notes = _period(period_from, period_to, found)
    comment = str(comment or "").strip()

    with transaction.atomic():
        imp = BankImport.objects.create(
            number=next_number(NUMBER_PREFIX, width=NUMBER_WIDTH), account=account,
            format=account.template.format, period_from=start, period_to=end,
            filename=name[-255:], comment=comment, author_id=actor_id,
            created_by=actor_id, updated_by=actor_id, source=content)
        core_files.attach(imp, FILE_TYPE, data=content, filename=name,
                          mime=getattr(upload, "content_type", "") or "",
                          actor_id=actor_id, request=request)
        audit.record(imp, "created", actor_id=actor_id, changes={
            "number": imp.number, "account": account.iban, "format": imp.format,
            "period_from": start.isoformat(), "period_to": end.isoformat(),
            "filename": imp.filename, "documents": found.get("documents")})
        company = current_company()
        import_id = str(imp.pk)
        # После фиксации: воркер, взявший задачу раньше коммита, не нашёл бы строку.
        transaction.on_commit(lambda: _enqueue(import_id, company))
    return imp, [*notes, *_overlaps(account, start, end, exclude=imp.pk)]


def _enqueue(import_id: str, company: str) -> None:
    from apps.bpp.tasks_bank import run_bank_import

    try:
        run_bank_import.delay(company_slug=company, import_id=import_id)
    except Exception:
        # Брокер недоступен: загрузка не должна висеть «Обрабатывается»
        # вечно — ФД увидит причину в реестре и загрузит файл снова.
        logger.exception("bpp bank import: не удалось поставить разбор import=%s", import_id)
        _fail(import_id, "Очередь фоновых задач недоступна. Повторите загрузку через "
                         "несколько минут; если ошибка повторится, обратитесь к "
                         "администратору.")


# ── загрузка: разбор в воркере ─────────────────────────────────────────

def _parse(imp: BankImport):
    account = imp.account
    content = bytes(imp.source or b"")
    template = account.template
    if imp.format == StatementFormat.ONEC:
        return onec.parse(content, account=account, encoding=template.encoding)
    if template.format != imp.format:
        # Счёт перевели на шаблон другого формата, пока файл ждал очереди.
        raise DomainError("E-IMP-01", f"Шаблон счёта {account.iban} сменился на формат, "
                                      f"которому файл не соответствует. Загрузите выписку "
                                      f"ещё раз.")
    return tabular.parse(content, name=imp.filename, template=template, account=account)


def _insert(imp: BankImport, parsed_lines: list[dict]) -> None:
    """Запись списаний пачками по ``BATCH``: каждая пачка — своя транзакция
    (прогресс виден опросу экрана), ``ON CONFLICT DO NOTHING`` отсекает
    дубли (BR-075) — и уже загруженные прежде, и повторы внутри файла, и
    строки параллельной загрузки того же файла."""
    rows = [BankStatementLine(
        bank_import=imp, account_id=imp.account_id, created_by=imp.author_id,
        updated_by=imp.author_id, match_status=LineMatchStatus.UNMATCHED,
        dedup_hash=dedup_hash(imp.account_id, doc_date=item["doc_date"],
                              doc_number=item["doc_number"], amount=item["amount"],
                              recipient_bin=item["recipient_bin"]),
        **item) for item in parsed_lines]
    rows.sort(key=lambda row: row.dedup_hash)  # один порядок блокировок у всех загрузок
    done = duplicates = 0
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        with transaction.atomic():
            mine = BankStatementLine.objects.filter(bank_import=imp)
            before = mine.count()
            BankStatementLine.objects.bulk_create(chunk, ignore_conflicts=True)
            inserted = mine.count() - before
            done += len(chunk)
            duplicates += len(chunk) - inserted
            BankImport.objects.filter(pk=imp.pk).update(
                rows_done=done, duplicates=duplicates, updated_at=timezone.now())


def _fail(import_id, reason: str) -> None:
    """«Ошибка загрузки» с причиной; строки, успевшие записаться, отменяются
    (иначе они держали бы ключи дублей, и повтор той же выписки их пропустил
    бы), копия байтов ``source`` стирается. Повторный вызов ничего не
    меняет: трогается только загрузка в «Обрабатывается».

    Редкая гонка: загрузки A и B одного файла идут одновременно, A успела
    зафиксировать пачки, B пропустила эти операции как дубли, а потом A
    упала. Строки A отменяются, у B этих операций нет — до повторной
    загрузки их в базе не будет. Поэтому причина отказа предлагает загрузить
    выписку снова: повтор найдёт ключи свободными и загрузит эти операции."""
    now = timezone.now()
    with transaction.atomic():
        BankStatementLine.objects.filter(bank_import_id=import_id,
                                         cancelled_at__isnull=True).update(cancelled_at=now)
        updated = BankImport.objects.filter(pk=import_id,
                                            status=BankImportStatus.PROCESSING).update(
            status=BankImportStatus.FAILED, failure=reason, finished_at=now, source=b"",
            updated_at=now)
        if updated:
            audit.record_for(AUDIT_TYPE, str(import_id), _FAILED, actor_id=None,
                             changes={"failure": reason})


def run_import(import_id) -> None:
    """Разобрать и записать загрузку ``import_id`` (тело задачи
    ``tasks_bank.run_bank_import``, уже в контексте компании).

    Повторная доставка задачи безопасна: разбор «берётся» проставлением
    ``started_at`` одной командой БД, и второй вызов, не взявший его, ничего
    не делает."""
    key = _as_uuid(import_id)
    if key is None:
        return
    claimed = BankImport.objects.filter(
        pk=key, status=BankImportStatus.PROCESSING, started_at__isnull=True,
    ).update(started_at=timezone.now())
    if not claimed:
        logger.info("bpp bank import: import=%s не ждёт разбора — пропуск", import_id)
        return
    imp = BankImport.objects.select_related("account__template").get(pk=key)
    try:
        parsed = _parse(imp)
        BankImport.objects.filter(pk=key).update(
            rows_total=parsed.rows_total, debits=len(parsed.lines), errors=parsed.errors,
            updated_at=timezone.now())
        _insert(imp, parsed.lines)
    except DomainError as exc:
        _fail(key, exc.message)
        return
    except Exception:
        logger.exception("bpp bank import: разбор import=%s упал", import_id)
        _fail(key, "Выписку не удалось разобрать из-за внутренней ошибки. Повторите "
                   "загрузку; если ошибка повторится, обратитесь к администратору.")
        return
    now = timezone.now()
    BankImport.objects.filter(pk=key).update(status=BankImportStatus.LOADED, finished_at=now,
                                             source=b"", updated_at=now)
    imp.refresh_from_db(fields=["rows_total", "debits", "duplicates", "errors"])
    audit.record_for(AUDIT_TYPE, str(key), _FINISHED, actor_id=None, changes={
        "rows_total": imp.rows_total, "debits": imp.debits, "duplicates": imp.duplicates,
        "loaded": imp.debits - imp.duplicates, "errors": len(imp.errors or [])})


def reap_stale(*, now=None) -> dict:
    """Потерянные разборы — в «Ошибка загрузки» (тело периодики
    ``tasks_bank.reap_stale_imports``, уже в контексте компании).

    Разбор, убитый пределом времени задачи, нехваткой памяти или
    перезапуском воркера, до ``_fail`` не доходит; задача, взятая при
    выключенном ``bpp_bank``, не начинается вовсе. Такая загрузка висела бы
    «Обрабатывается» вечно, с байтами ``source`` в строке и с ключами
    дублей у строк, успевших записаться. Потерянной считается загрузка в
    «Обрабатывается», чей разбор начат (``started_at``) — а не начатый
    создан (``created_at``) — больше ``STALE_MINUTES`` минут назад."""
    cutoff = (now or timezone.now()) - timedelta(minutes=STALE_MINUTES)
    stale = list(BankImport.objects
                 .filter(status=BankImportStatus.PROCESSING)
                 .filter(Q(started_at__lt=cutoff)
                         | Q(started_at__isnull=True, created_at__lt=cutoff))
                 .values_list("pk", flat=True))
    for import_id in stale:
        logger.warning("bpp bank import: разбор import=%s потерян — «Ошибка загрузки»",
                       import_id)
        _fail(import_id, STALE_REASON)
    return {"failed": len(stale)}


# ── чтение: карточка, реестр L-07, строки ──────────────────────────────

def _names(ids) -> dict[int, str]:
    ids = sorted({i for i in ids if i})
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


def _with_counts(rows):
    live = Q(lines__cancelled_at__isnull=True)
    return rows.annotate(
        n_lines=Count("lines", filter=live),
        n_unmatched=Count("lines", filter=live & Q(lines__match_status=LineMatchStatus.UNMATCHED)))


def _brief(imp: BankImport, names: dict[int, str]) -> dict:
    account = imp.account
    lines_total = getattr(imp, "n_lines", None)
    unmatched = getattr(imp, "n_unmatched", None)
    if lines_total is None:
        live = imp.lines.filter(cancelled_at__isnull=True)
        lines_total = live.count()
        unmatched = live.filter(match_status=LineMatchStatus.UNMATCHED).count()
    return {
        "id": str(imp.pk), "number": imp.number,
        "account": {"id": str(account.pk), "iban": account.iban,
                    "bank_name": account.bank_name, "currency": account.currency},
        "bank_name": account.bank_name, "format": imp.format,
        "period_from": imp.period_from, "period_to": imp.period_to,
        "status": imp.status, "status_label": imp.get_status_display(),
        "filename": imp.filename, "comment": imp.comment,
        "rows_total": imp.rows_total, "debits": imp.debits, "rows_done": imp.rows_done,
        "duplicates": imp.duplicates, "errors_count": len(imp.errors or []),
        "lines": lines_total, "matched": lines_total - unmatched, "unmatched": unmatched,
        "author_id": imp.author_id, "author_name": names.get(imp.author_id),
        "created_at": imp.created_at, "finished_at": imp.finished_at,
    }


def get_import(import_id) -> BankImport:
    key = _as_uuid(import_id)
    imp = (BankImport.objects.select_related("account").defer("source").filter(pk=key).first()
           if key else None)
    if imp is None:
        raise DomainError("E-NOT-FOUND", "Загрузка выписки не найдена.", status=404)
    return imp


def card(imp: BankImport) -> dict:
    """Карточка загрузки — её опрашивает экран, пока идёт разбор:
    состояние, итог (строк в файле, списаний, дублей, ошибок), ошибки строк
    «Строка N: …», причина отказа и файл выписки."""
    data = _brief(imp, _names([imp.author_id]))
    progress = 100 if imp.status != BankImportStatus.PROCESSING else (
        int(imp.rows_done * 100 / imp.debits) if imp.debits else 0)
    stored = core_files.list_files(imp)
    data.update({"errors": list(imp.errors or []), "failure": imp.failure,
                 "progress": progress, "file": stored[0] if stored else None})
    return data


def _filtered(*, account_ids=(), period_from=None, period_to=None, statuses=()):
    rows = BankImport.objects.select_related("account").defer("source")
    keys = [key for key in (_as_uuid(value) for value in account_ids) if key]
    if account_ids and not keys:
        return rows.none()
    if keys:
        rows = rows.filter(account_id__in=keys)
    start, end = _date(period_from, "period_from"), _date(period_to, "period_to")
    if start:  # период загрузки пересекается с выбранным
        rows = rows.filter(period_to__gte=start)
    if end:
        rows = rows.filter(period_from__lte=end)
    statuses = [status for status in statuses if status]
    if statuses:
        unknown = [status for status in statuses if status not in BankImportStatus.values]
        if unknown:
            raise _invalid("status", f"Неизвестный статус загрузки: {', '.join(unknown)}.")
        rows = rows.filter(status__in=statuses)
    return rows.order_by("-created_at", "-pk")


def registry(*, account_ids=(), period_from=None, period_to=None, statuses=(), page: int = 1,
             page_size: int | None = None) -> dict:
    """Реестр L-07: номер, банк, период, дата загрузки, кто, строк,
    сопоставлено, не сопоставлено, статус; фильтры «банк» (счёт), «период»
    (пересечение), «статус»; пагинация 25/50/100 (по умолчанию 50)."""
    rows = _filtered(account_ids=account_ids, period_from=period_from, period_to=period_to,
                     statuses=statuses)
    page_size = page_size if page_size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    page = max(1, page or 1)
    total = rows.count()
    chunk = list(_with_counts(rows)[(page - 1) * page_size: page * page_size])
    names = _names([imp.author_id for imp in chunk])
    return {"items": [_brief(imp, names) for imp in chunk], "total": total, "page": page,
            "page_size": page_size}


def export_count(*, account_ids=(), period_from=None, period_to=None, statuses=()) -> int:
    return _filtered(account_ids=account_ids, period_from=period_from, period_to=period_to,
                     statuses=statuses).count()


def export_rows(*, account_ids=(), period_from=None, period_to=None, statuses=()):
    """Строки выгрузки реестра L-07 — та же выборка, что у страницы, без
    пагинации (и функция пересборки фоновой выгрузки ``export.respond``).
    Видимость одна на всех держателей ``bpp.bank`` view."""
    rows = list(_with_counts(_filtered(account_ids=account_ids, period_from=period_from,
                                       period_to=period_to, statuses=statuses)))
    names = _names([imp.author_id for imp in rows])
    for imp in rows:
        item = _brief(imp, names)
        item["account_iban"] = imp.account.iban
        item["period"] = f"{_day(imp.period_from)}–{_day(imp.period_to)}"
        yield item


def serialize_line(row: BankStatementLine) -> dict:
    return {
        "id": str(row.pk), "row_no": row.row_no, "doc_date": row.doc_date,
        "doc_number": row.doc_number, "amount": row.amount, "currency": row.currency,
        "recipient_name": row.recipient_name, "recipient_bin": row.recipient_bin,
        "recipient_iban": row.recipient_iban, "purpose": row.purpose,
        "match_status": row.match_status, "match_status_label": row.get_match_status_display(),
        "cancelled_at": row.cancelled_at,
    }


def lines(imp: BankImport, *, match_status: str | None = None, include_cancelled: bool = False,
          page: int = 1, page_size: int | None = None) -> dict:
    """Строки загрузки — по порядку в файле, страницами. По умолчанию только
    действующие (как счётчики карточки); отменённые — ``include_cancelled``."""
    rows = imp.lines.all().order_by("row_no", "pk")
    if not include_cancelled:
        rows = rows.filter(cancelled_at__isnull=True)
    if match_status:
        if match_status not in LineMatchStatus.values:
            raise _invalid("match_status", f"Неизвестный статус строки: {match_status}.")
        rows = rows.filter(match_status=match_status)
    page_size = page_size if page_size in LINES_PAGE_SIZES else DEFAULT_PAGE_SIZE
    page = max(1, page or 1)
    total = rows.count()
    return {"items": [serialize_line(row)
                      for row in rows[(page - 1) * page_size: page * page_size]],
            "total": total, "page": page, "page_size": page_size}
