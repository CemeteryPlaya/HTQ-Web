"""Экспорт реестров модуля в xlsx (ТЗ §19, мастер-план D-32; A2.2, задача 6).

Три границы по числу строк — все считает вызывающий (реестр уже знает
``count`` из своего запроса, до материализации строк):

- ``count <= 10 000`` — файл собирается сразу, в том же запросе
  (``openpyxl``, ``write_only=True``: лист пишется потоком, без листа
  целиком в памяти) и отдаётся ``HttpResponse``;
- ``10 000 < count <= 50 000`` — выборка большая для одного HTTP-запроса
  (gunicorn ``--timeout 60``): заводится строка ``ExportJob``, а файл
  собирает Celery-задача (``apps/bpp/tasks_export.py``), которая
  ПЕРЕСОБИРАЕТ строки заново по ``rebuild`` — ссылке на функцию модуля
  вида ``("apps.bpp.services.<домен>.<модуль>.export_rows", {фильтры})`` —
  а не передаёт уже прочитанные объекты через Celery (несериализуемо и
  незачем тащить через брокер то, что дешевле перечитать). Готовый файл
  кладётся в ``apps.media_files`` (scope ``generic``, приватный: байты
  только по подписанной ссылке), заказчику уходит уведомление центра со
  ссылкой на экран выгрузки, а ссылку на байты выдаёт ручка
  ``GET exports/<id>`` — только заказчику и с записью в журнал (ТЗ §25.2);
- ``count > 50 000`` — отказ ``E-EXP-01`` до всякой работы (ТЗ §19).

Почему не ``apps.files``: там документы объекта с версиями и правами
владельца, а выгрузка — разовый файл одного получателя без объекта за ним.
"""

from __future__ import annotations

import importlib
import io
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from apps.bpp.models import ExportJob, ExportStatus
from apps.bpp.services.core import audit
from apps.core.infrastructure import client_ip
from apps.core.services import require_service
from htqweb.errors import DomainError
from htqweb.tenancy.context import current_company

logger = logging.getLogger(__name__)

#: Строк — синхронно (в теле HTTP-ответа).
SYNC_LIMIT = 10_000
#: Строк — предел вообще (выше — отказ, ниже до ``SYNC_LIMIT`` — фон).
HARD_LIMIT = 50_000

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Функции пересборки — только из кода модуля: путь приходит из ручки
#: реестра, а не от клиента, но импорт по строке в задаче Celery не должен
#: уметь дотянуться до чего угодно, если однажды путь всё-таки соберут из
#: параметров запроса.
REBUILD_PREFIX = "apps.bpp."

#: Тип объекта выгрузки в журнале ``AuditLog`` (``app_label.model``).
AUDIT_OBJECT_TYPE = "bpp.exportjob"

_KINDS = ("text", "money", "decimal", "integer", "date", "datetime")
# Коды форматов в файле — всегда в синтаксисе en-US: запятая — разделитель
# разрядов, точка — дробной части. Excel и LibreOffice показывают их в
# региональных настройках читателя: в русской локали «#,##0.00» выглядит как
# «1 250 000,00» (ТЗ §4). Пробел в самом коде («# ##0.00») разрядов не
# группирует — это литерал, который встал бы один раз между тысячами и всем
# остальным («1250 000.00»).
_NUMBER_FORMAT = {
    "money": "#,##0.00",
    "decimal": "#,##0.00",
    # Счётчики (строк, дублей): целое с разрядами, без «,00».
    "integer": "#,##0",
    "date": "dd.mm.yyyy",
    "datetime": "dd.mm.yyyy hh:mm",
}
# Символы, запрещённые в имени листа Excel (иначе openpyxl падает ValueError).
_SHEET_FORBIDDEN = set('[]:*?/\\')


@dataclass(frozen=True)
class Column:
    """Колонка выгрузки: ``key`` — поле строки, ``title`` — заголовок,
    ``kind`` определяет и приведение значения, и числовой формат ячейки
    (``text|money|decimal|integer|date|datetime``)."""

    key: str
    title: str
    kind: str = "text"

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(
                f"export.Column({self.key!r}): недопустимый kind {self.kind!r}, "
                f"нужен один из {_KINDS}")

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "kind": self.kind}


def too_large(count: int) -> DomainError:
    return DomainError(
        "E-EXP-01",
        f"Не удалось выгрузить реестр: в выборке {count} строк, а в xlsx выгружается "
        f"не больше {HARD_LIMIT}. Сузьте фильтры и повторите экспорт.",
        status=422)


def _local_naive(value: datetime) -> datetime:
    """Excel не хранит часовой пояс (openpyxl отвергает aware-datetime):
    время пишется так, как его читает человек, — в поясе платформы."""
    if timezone.is_aware(value):
        value = value.astimezone(ZoneInfo(settings.PLATFORM_TIME_ZONE))
    return value.replace(tzinfo=None)


def _coerce(raw, kind: str):
    if raw is None or raw == "":
        return None
    if kind == "text":
        return str(raw)
    if kind in ("money", "decimal"):
        if isinstance(raw, Decimal):
            return raw
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            # Не число — показываем как есть, а не роняем весь экспорт.
            return str(raw)
    if kind == "integer":
        if isinstance(raw, bool):
            return str(raw)
        if isinstance(raw, int):
            return raw
        try:
            return int(Decimal(str(raw)))
        except (InvalidOperation, ValueError, OverflowError):
            return str(raw)  # не число — как есть, а не падение всего экспорта
    if kind == "date":
        if isinstance(raw, datetime):
            return _local_naive(raw).date()
        if isinstance(raw, date):
            return raw
        return date.fromisoformat(str(raw)[:10])
    # datetime
    if isinstance(raw, datetime):
        return _local_naive(raw)
    text = str(raw)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _local_naive(datetime.fromisoformat(text))


def _value_of(row, key: str):
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _sheet_title(name: str) -> str:
    title = "".join(ch for ch in (name or "") if ch not in _SHEET_FORBIDDEN).strip()
    return (title or "Экспорт")[:31]


def _filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " _-").strip()
    return f"{safe or 'export'}.xlsx"


def _cell(sheet, value, fmt: str | None) -> WriteOnlyCell:
    cell = WriteOnlyCell(sheet, value=value)
    if isinstance(value, str) and value.startswith("="):
        # openpyxl считает строку с «=» формулой — наименование контрагента
        # «=HYPERLINK(…)» выполнилось бы у читателя файла. Только текст.
        cell.data_type = "s"
    if fmt is not None and value is not None and not isinstance(value, str):
        cell.number_format = fmt
    return cell


def write_xlsx(name: str, columns: Sequence[Column], rows: Iterable, *,
               limit: int | None = None) -> bytes:
    """Собрать книгу потоком (``write_only``) — лист не держится в памяти
    целиком, поэтому пригодно и для фоновой пересборки больших выборок.

    ``limit`` — сколько строк допустимо; больше — ``E-EXP-01`` (фоновая
    пересборка могла насчитать больше, чем ручка при заказе)."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title=_sheet_title(name))
    header = []
    for column in columns:
        cell = WriteOnlyCell(sheet, value=column.title)
        cell.font = Font(bold=True)
        header.append(cell)
    sheet.append(header)
    written = 0
    for row in rows:
        written += 1
        if limit is not None and written > limit:
            raise too_large(written)
        sheet.append([_cell(sheet, _coerce(_value_of(row, column.key), column.kind),
                            _NUMBER_FORMAT.get(column.kind))
                      for column in columns])
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def _xlsx_response(name: str, columns: Sequence[Column], rows: Iterable) -> HttpResponse:
    data = write_xlsx(name, columns, rows)
    response = HttpResponse(data, content_type=XLSX_MIME)
    # filename* (RFC 6266): имя реестра — кириллица, а заголовок HTTP — latin-1.
    response["Content-Disposition"] = content_disposition_header(True, _filename(name))
    return response


# ── публичная точка входа ────────────────────────────────────────────────

def respond(request, *, name: str, columns: Sequence[Column], rows: Iterable | None,
            count: int, rebuild: tuple[str, dict] | None = None) -> HttpResponse | dict:
    """Собрать экспорт реестра по границам ТЗ §19.

    ``rows`` — уже прочитанная выборка (нужна, только если ``count`` в
    пределах ``SYNC_LIMIT``: для фона она игнорируется, туда идёт
    ``rebuild``). ``rebuild`` — ``(dotted_path, kwargs)``: путь к функции
    ``export_rows(**kwargs) -> Iterable`` модуля (``apps.bpp.…``), которая
    перечитает те же фильтры внутри фоновой задачи; ``kwargs`` — только
    JSON-значения (строки, числа, списки): их везёт брокер Celery. Права
    читателя функция пересборки применяет сама по ``kwargs`` — ручка
    реестра кладёт туда всё, что для этого нужно (например, ``user_id``
    заказчика): у задачи нет ни запроса, ни токена.

    Ответ: ``HttpResponse`` с файлом — или ``{"id", "status": "queued",
    "detail"}`` для фона (ручка реестра отдаёт его как JSON).
    """
    require_service("bpp")
    if count > HARD_LIMIT:
        raise too_large(count)
    if count <= SYNC_LIMIT:
        return _xlsx_response(name, columns, rows if rows is not None else ())

    if rebuild is None:
        raise ValueError(
            "export.respond: выборка больше SYNC_LIMIT строк требует rebuild "
            "(функция пересборки для фоновой задачи)")
    path, filters = rebuild
    if not path.startswith(REBUILD_PREFIX):
        raise ValueError(f"export.respond: функция пересборки вне модуля: {path!r}")
    try:
        json.dumps(filters)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"export.respond: фильтры пересборки должны быть JSON-значениями: {exc}") from exc

    company = current_company()
    job = ExportJob.objects.create(requested_by=request.token.user_id, name=name[:255],
                                   row_count=count)
    payload = {
        "company_slug": company, "job_id": str(job.pk),
        "columns": [column.as_dict() for column in columns],
        "rebuild_path": path, "rebuild_kwargs": filters,
    }
    # После фиксации: воркер, взявший задачу раньше коммита, не нашёл бы строку.
    transaction.on_commit(lambda: _enqueue(payload))
    return {
        "id": str(job.pk), "status": job.status,
        "detail": f"В выборке больше {SYNC_LIMIT} строк — файл готовится в фоне. "
                  f"Когда он будет готов, придёт уведомление со ссылкой.",
    }


def _enqueue(payload: dict) -> None:
    from apps.bpp.tasks_export import build_export

    try:
        build_export.delay(**payload)
    except Exception:
        # Брокер недоступен: заказ не должен висеть «готовится» вечно —
        # человек увидит причину на экране выгрузки и повторит.
        logger.exception("bpp export: не удалось поставить задачу job=%s", payload["job_id"])
        ExportJob.objects.filter(pk=payload["job_id"]).update(
            status=ExportStatus.ERROR, finished_at=timezone.now(),
            error="Очередь фоновых задач недоступна. Повторите экспорт через несколько "
                  "минут; если ошибка повторится, обратитесь к администратору.")


# ── тело фоновой задачи (зовётся из tasks_export.build_export) ──────────

def run_background(*, job_id: str, columns: list[dict], rebuild_path: str,
                   rebuild_kwargs: dict) -> None:
    """Пересобрать выборку, сохранить файл и уведомить заказчика (уже внутри
    контекста компании — ``@company_task`` в ``tasks_export.py``).

    Отказ пересборки не роняет задачу: строка получает читаемую причину, а
    заказчик — уведомление, иначе он ждал бы файл, который не придёт."""
    job = ExportJob.objects.filter(pk=job_id).first()
    if job is None or job.status != ExportStatus.QUEUED:
        # Повтор доставки уже собранного задания или строка удалена.
        logger.info("bpp export: job=%s не ждёт сборки — пропуск", job_id)
        return
    cols = [Column(**c) for c in columns]
    try:
        if not rebuild_path.startswith(REBUILD_PREFIX):
            raise ValueError(f"функция пересборки вне модуля: {rebuild_path!r}")
        module_path, func_name = rebuild_path.rsplit(".", 1)
        rebuild = getattr(importlib.import_module(module_path), func_name)
        data = write_xlsx(job.name, cols, rebuild(**rebuild_kwargs), limit=HARD_LIMIT)
        from apps.media_files import interface as media

        # scope generic приватный: байты — только по подписанной ссылке,
        # которую выдаёт ручка выгрузки заказчику (``download``). Scope
        # открытый (не в ``RESTRICTED_SCOPES``), поручительство
        # ``internal_authorized`` ему ничего не добавляет.
        stored = media.store_file(data=data, filename=_filename(job.name), mime=XLSX_MIME,
                                  scope="generic", owner_id=job.requested_by)
    except DomainError as exc:
        _fail(job, exc.message)
        return
    except Exception:
        logger.exception("bpp export: не удалось собрать job=%s (%s)", job_id, rebuild_path)
        _fail(job, "Не удалось собрать файл. Повторите экспорт; если ошибка повторится, "
                   "обратитесь к администратору.")
        return

    job.status = ExportStatus.DONE
    job.media_file_id = stored["id"]
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "media_file_id", "finished_at"])
    _notify(job, title=f"Экспорт «{job.name}» готов",
            text="Файл собран — откройте уведомление, чтобы скачать его.")


def _fail(job: ExportJob, reason: str) -> None:
    job.status = ExportStatus.ERROR
    job.error = reason
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error", "finished_at"])
    _notify(job, title=f"Экспорт «{job.name}» не собран", text=reason)


def _notify(job: ExportJob, *, title: str, text: str) -> None:
    from apps.notifications import interface as notifications

    # Ссылка — экран выгрузки во фронте (SPA-маршрут, а не адрес API:
    # колокольчик открывает её переходом внутри приложения, где JWT есть
    # только у запросов из кода). Экран зовёт ``GET /api/bpp/v1/exports/<id>``
    # и открывает выданную там подписанную ссылку на файл.
    notifications.notify(
        recipients=[job.requested_by], event="bpp.export_ready", title=title, text=text,
        url=f"/bpp/exports/{job.pk}", company_slug=current_company(),
        target_type="bpp.export", target_id=str(job.pk), deliver=True,
    )


# ── ручка выгрузки ───────────────────────────────────────────────────────

def _not_found() -> DomainError:
    return DomainError(
        "E-NOT-FOUND",
        "Выгрузка не найдена. Возможно, её заказал другой пользователь — запросите "
        "экспорт заново.", status=404)


def job_out(job: ExportJob) -> dict:
    return {"id": str(job.pk), "name": job.name, "status": job.status,
            "row_count": job.row_count, "error": job.error or None,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None}


def download(request, job_id) -> dict:
    """Состояние выгрузки и — если файл готов — временная ссылка на него.

    Только заказчику: чужая и несуществующая выгрузка неотличимы (404).
    Каждая выданная ссылка — запись ``file_downloaded`` в журнал с IP и
    user-agent (ТЗ §25.2): других путей к байтам у выгрузки нет — файл
    приватный, а загрузивший его в media — сам заказчик."""
    job = ExportJob.objects.filter(pk=job_id, requested_by=request.token.user_id).first()
    if job is None:
        raise _not_found()
    out = job_out(job)
    if job.status != ExportStatus.DONE:
        return out

    from apps.media_files import interface as media

    link = media.get_file_links([job.media_file_id]).get(str(job.media_file_id))
    if link is None:
        raise DomainError(
            "E-NOT-FOUND", "Файл выгрузки не найден в хранилище. Запросите экспорт заново.",
            status=404)
    audit.record_for(AUDIT_OBJECT_TYPE, str(job.pk), "file_downloaded",
                     actor_id=request.token.user_id,
                     changes={"media_file_id": str(job.media_file_id), "name": job.name,
                              "ip": client_ip(request) or "",
                              "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300]})
    expires = datetime.fromtimestamp(link["exp"], tz=dt_timezone.utc)
    return {**out, "url": link["url"], "expires_at": expires.isoformat()}
