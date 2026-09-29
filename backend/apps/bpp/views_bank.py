"""Ручки «Счета организации и шаблоны выписок» ``/api/bpp/v1/bank/…`` (ТЗ
§11.1, §18, задача A3.1) — подмодуль ``bpp_bank``.

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня —
по узлам реестра (``services/core/permissions.can``, матрица ролей):

- чтение — ``bpp.bank:view`` (ФД, БУХ) или ``bpp.settings:view`` (ФД, АДМ):
  справочник нужен и тому, кто грузит выписку, и тому, кто его ведёт;
- создание и правка (в том числе архив) — ``bpp.settings:edit`` (АДМ,
  ТЗ §11.1 «Настройка шаблонов разбора выписки — АДМ»);
- предпросмотр образца по шаблону ничего не сохраняет — ему хватает чтения.

Записывающие ручки идемпотентны (``Idempotency-Key``), правка сверяет
``version`` (E-CON-01). Неверный UUID в адресе — 404.

**Загрузки выписок** (``bank/imports…``, ТЗ §11.1–11.2, L-07, задача 3 —
A4.1): загрузка — ``bpp.bank:edit`` (ФД), реестр, карточка и строки —
``bpp.bank:view`` (ФД, БУХ). Разбор идёт в фоне
(``services/bank/imports.py``), экран опрашивает карточку загрузки.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from .schemas import bank as schemas
from .services.bank import imports
from .services.bank import settings as service
from .services.bank import templates
from .services.core import audit, export, permissions
from .services.params import int_param

BANK_NODE = "bpp.bank"
SETTINGS_NODE = "bpp.settings"

#: Образец выписки для предпросмотра — не больше, чем сама выписка (тип
#: файла ``bank_statement``, ТЗ §11.2: «до 20 МБ»).
SAMPLE_MAX_MB = 20


def _deny(action: str) -> DomainError:
    return DomainError(
        "E-ACC-01",
        f"У вас нет прав: {action}. Если это ошибка, обратитесь к администратору.",
        status=403)


def _can_read(request) -> bool:
    return (permissions.can(request, BANK_NODE, "view")
            or permissions.can(request, SETTINGS_NODE, "view"))


def _need_read(request) -> None:
    if not _can_read(request):
        raise _deny("просмотр счетов организации и шаблонов выписок")


def _need_edit(request) -> None:
    if not permissions.can(request, SETTINGS_NODE, "edit"):
        raise _deny("настройка счетов организации и шаблонов выписок")


def _sent(data) -> tuple[dict, int | None]:
    """Присланные поля без ``null`` и версия отдельно: пустое значение в
    PATCH поле не стирает, а не трогает."""
    sent = {key: value for key, value in data.model_dump(exclude_unset=True).items()
            if value is not None}
    return sent, sent.pop("version", None)


def _active_only(request) -> bool:
    return request.GET.get("active") in ("1", "true", "yes")


# Журнал счёта и шаблона читает тот, кто видит справочник.
audit.register_history_access("bpp.orgbankaccount",
                              lambda request, _object_id: _can_read(request))
audit.register_history_access("bpp.statementtemplate",
                              lambda request, _object_id: _can_read(request))
# Журнал загрузки выписки — тому, кто видит загрузки (ФД, БУХ).
audit.register_history_access(
    imports.AUDIT_TYPE, lambda request, _object_id: permissions.can(request, BANK_NODE, "view"))


# ── счета организации ───────────────────────────────────────────────────

@api_view(methods=("GET",), module="bpp", level="read")
def account_list(request):
    _need_read(request)
    return service.list_accounts(active=_active_only(request))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.AccountCreate,
          status=201, idempotent=True)
def account_create(request, data):
    _need_edit(request)
    account = service.create_account(data.model_dump(), actor_id=request.token.user_id)
    return service.serialize_account(account)


def accounts_collection(request):
    if request.method == "GET":
        return account_list(request)
    if request.method == "POST":
        return account_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def account_get(request, account_id):
    _need_read(request)
    return service.serialize_account(service.get_account(uuid_or_404(account_id)))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.AccountUpdate,
          idempotent=True)
def account_patch(request, account_id, data):
    _need_edit(request)
    sent, version = _sent(data)
    account = service.update_account(uuid_or_404(account_id), sent, expected_version=version,
                                     actor_id=request.token.user_id)
    return service.serialize_account(account)


def account_detail(request, account_id):
    if request.method == "GET":
        return account_get(request, account_id)
    if request.method == "PATCH":
        return account_patch(request, account_id)
    return json_error("Method Not Allowed", 405)


# ── шаблоны выписок ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="bpp", level="read")
def template_list(request):
    _need_read(request)
    return service.list_templates(active=_active_only(request))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.TemplateCreate,
          status=201, idempotent=True)
def template_create(request, data):
    _need_edit(request)
    tpl = service.create_template(data.model_dump(exclude_none=True),
                                  actor_id=request.token.user_id)
    return service.serialize_template(tpl)


def templates_collection(request):
    if request.method == "GET":
        return template_list(request)
    if request.method == "POST":
        return template_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def template_get(request, template_id):
    _need_read(request)
    return service.serialize_template(service.get_template(uuid_or_404(template_id)))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.TemplateUpdate,
          idempotent=True)
def template_patch(request, template_id, data):
    _need_edit(request)
    sent, version = _sent(data)
    tpl = service.update_template(uuid_or_404(template_id), sent, expected_version=version,
                                  actor_id=request.token.user_id)
    return service.serialize_template(tpl)


def template_detail(request, template_id):
    if request.method == "GET":
        return template_get(request, template_id)
    if request.method == "PATCH":
        return template_patch(request, template_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="read")
def template_preview(request, template_id):
    """Предпросмотр образца выписки по шаблону: multipart ``file``, ничего
    не сохраняет. Ответ — ``templates.preview``: строка заголовка, найденные
    колонки, первые 20 строк (суммы — строкой ``Decimal``), ошибки строк."""
    _need_read(request)
    tpl = service.get_template(uuid_or_404(template_id))
    upload = request.FILES.get("file")
    if upload is None:
        message = "Приложите файл образца выписки."
        raise DomainError("E-VAL-01", message, fields=[{"field": "file", "message": message}])
    if upload.size > SAMPLE_MAX_MB * 1024 * 1024:
        message = f"Образец выписки — не больше {SAMPLE_MAX_MB} МБ."
        raise DomainError("E-VAL-01", message, fields=[{"field": "file", "message": message}])
    return templates.preview(upload, tpl)


# ── загрузки выписок (A4.1) ─────────────────────────────────────────────

#: Путь пересборки фоновой выгрузки реестра — строка: её везёт брокер Celery.
IMPORTS_EXPORT_REBUILD_PATH = "apps.bpp.services.bank.imports.export_rows"

IMPORTS_EXPORT_COLUMNS = (
    export.Column("number", "Номер"),
    export.Column("bank_name", "Банк"),
    export.Column("account_iban", "Счёт"),
    export.Column("period", "Период"),
    export.Column("created_at", "Дата загрузки", kind="datetime"),
    export.Column("author_name", "Кто загрузил"),
    export.Column("rows_total", "Строк в файле", kind="integer"),
    export.Column("debits", "Списаний", kind="integer"),
    export.Column("duplicates", "Пропущено дублей", kind="integer"),
    export.Column("errors_count", "Ошибок", kind="integer"),
    export.Column("matched", "Сопоставлено", kind="integer"),
    export.Column("unmatched", "Не сопоставлено", kind="integer"),
    export.Column("status_label", "Статус"),
)


def _need_bank(request, flag: str, action: str) -> None:
    if not permissions.can(request, BANK_NODE, flag):
        raise _deny(action)


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


@api_view(methods=("GET",), module="bpp", level="read")
def import_list(request):
    """Реестр L-07 (``{items, total, page, page_size}``) или, с
    ``?format=xlsx``, его выгрузка — та же фильтрованная выборка."""
    _need_bank(request, "view", "просмотр загрузок выписок")
    params = request.GET
    filters = {"account_ids": _list_param(request, "account_id"),
               "period_from": params.get("period_from") or None,
               "period_to": params.get("period_to") or None,
               "statuses": _list_param(request, "status")}
    if params.get("format") == "xlsx":
        return export.respond(
            request, name="Загрузки выписок", columns=IMPORTS_EXPORT_COLUMNS,
            rows=imports.export_rows(**filters), count=imports.export_count(**filters),
            rebuild=(IMPORTS_EXPORT_REBUILD_PATH, filters))
    return imports.registry(**filters, page=int_param(params, "page", 1, minimum=1),
                            page_size=int_param(params, "page_size", imports.DEFAULT_PAGE_SIZE))


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def import_create(request):
    """Загрузка выписки — multipart: ``account_id``, ``file``, ``period_from``,
    ``period_to`` (ГГГГ-ММ-ДД; у выписки 1С период берётся из файла),
    ``comment``. Ответ — карточка загрузки («Обрабатывается») и
    ``warnings``: период из файла 1С заменил другой, введённый в форме;
    период пересекается с прошлыми загрузками счёта."""
    _need_bank(request, "edit", "загрузка выписки")
    form = request.POST
    imp, warnings = imports.start_import(
        account_id=form.get("account_id"), upload=request.FILES.get("file"),
        period_from=form.get("period_from"), period_to=form.get("period_to"),
        comment=form.get("comment", ""), actor_id=request.token.user_id, request=request)
    return {**imports.card(imports.get_import(imp.pk)), "warnings": warnings}


def imports_collection(request):
    if request.method == "GET":
        return import_list(request)
    if request.method == "POST":
        return import_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def import_get(request, import_id):
    """Карточка загрузки: состояние, итог, ошибки строк — экран опрашивает
    её, пока идёт разбор."""
    _need_bank(request, "view", "просмотр загрузок выписок")
    return imports.card(imports.get_import(uuid_or_404(import_id)))


@api_view(methods=("GET",), module="bpp", level="read")
def import_lines(request, import_id):
    """Строки загрузки по порядку в файле — ``{items, total, page, page_size}``;
    отменённые — только с ``?include_cancelled=1``."""
    _need_bank(request, "view", "просмотр загрузок выписок")
    imp = imports.get_import(uuid_or_404(import_id))
    params = request.GET
    return imports.lines(imp, match_status=params.get("match_status") or None,
                         include_cancelled=params.get("include_cancelled") in ("1", "true"),
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", imports.DEFAULT_PAGE_SIZE))
