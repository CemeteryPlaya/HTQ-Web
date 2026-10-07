"""Заявка тендерного модуля: реестр, карточка и черновик (T1.1; план этапов
0–2, §3.1, §3.4).

Права — узел ``tender.requests`` (создать / править / удалить), «все заявки,
а не только свои» — ``tender.requests.all`` (``EXPLICIT_ONLY``). Правит
черновик только автор и только в «Черновике» и «На доработке»; удаляет —
только ни разу не отправленный черновик (частей ещё не было: части — это ЗЗ в
БЗО, их заводит отправка, T1.3).

Роль инициатора (``sn``/``pm``) — роль БЗО, в которой отправка подаст ЗЗ
(BR-010): у пользователя должно быть право создавать заявки БЗО и группа
статей этой роли. ПМ подаёт только по проектам-участиям (BR-014). Группу
статей заявки проверяет отправка (T1.3, T-06); здесь — существование и
действие статей и единиц измерения.

Ошибки формы — ``DomainError`` с ``fields=[{field, message}]``, имена полей —
ключи тела запроса (``items[0].qty``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q

from apps.access import interface as access
from apps.files import interface as files
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.tender.models import (
    InitiatorRole,
    PurchaseType,
    TenderRequest,
    TenderRequestItem,
    TenderRequestStatus,
)
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.core.numbering import next_number
from apps.users import interface as users
from htqweb.errors import DomainError
from htqweb.tenancy import current_company_or_none

from .status import excludable_parts

#: Префикс номера заявки: ``ЗТ-ГГГГ-NNNNNN`` [умолч.] — свой счётчик, не ЗЗ БЗО.
PREFIX = "ЗТ"
OBJECT_TYPE = "tender.tenderrequest"
#: Владелец файлов ТЗ и чертежей в ``apps.files`` (``file_owners.py``).
FILE_OWNER = "tender.request"

NODE, NODE_ALL = "tender.requests", "tender.requests.all"
EDITABLE = (TenderRequestStatus.DRAFT, TenderRequestStatus.REWORK)
#: Роль инициатора → код группы статей БЗО (``refdata.ArticleGroup``).
ROLE_GROUP = {InitiatorRole.SN: "supply", InitiatorRole.PM: "pm"}

MAX_ITEMS = 200
TEXT_MAX = 2000
NAME_MIN, NAME_MAX = 3, 500
QTY_MAX = Decimal("1e12")      # Decimal(15,3)
MONEY_MAX = Decimal("1e16")    # Decimal(18,2)
QTY_STEP, MONEY_STEP = Decimal("0.001"), Decimal("0.01")

_TEXTS = ("delivery_address", "justification", "works_scope")
_FLAGS = ("needs_delivery", "needs_works", "allow_analogs", "allow_partial")
_ARTICLES = ("article_id", "delivery_article_id", "works_article_id")
_AMOUNTS = ("delivery_plan_amount", "works_plan_amount")


# ── кто спрашивает ──────────────────────────────────────────────────────

@dataclass
class Ctx:
    """Пользователь и компания запроса; права по узлу считаются один раз.

    Расчёт ролей гейта ``api_view(module=…)`` (``request.access_resolution``)
    переиспользуется, если совпали компания и пользователь (приём
    ``apps/bpp/services/core/permissions.py``)."""

    token: object
    company: str | None
    resolution: object = None
    _flags: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_request(cls, request) -> "Ctx":
        company = (getattr(request, "company", None) or {}).get("slug")
        cached = getattr(request, "access_resolution", None)
        resolution = None
        if cached and cached[0] == company and cached[1] == request.token.user_id:
            resolution = cached[2]
        return cls(request.token, company, resolution)

    @classmethod
    def from_token(cls, token) -> "Ctx":
        """Колбэки ``apps.files``: компания — текущего контекста."""
        return cls(token, current_company_or_none())

    @property
    def user_id(self) -> int:
        return int(self.token.user_id)

    def can(self, node: str, flag: str) -> bool:
        if node not in self._flags:
            self._flags[node] = access.flags_for(self.token, node, self.company,
                                                 resolution=self.resolution)
        return flag in self._flags[node]


# ── ошибки ──────────────────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def _not_found() -> DomainError:
    return DomainError("E-NOT-FOUND", "Заявка не найдена.", status=404)


def _bad(field_name: str, text: str, *, code: str = "E-VAL-01",
         status: int = 422) -> DomainError:
    return DomainError(code, f"{text[:1].upper()}{text[1:]}.", status=status,
                       fields=[{"field": field_name, "message": text}])


def _state_error(action: str, req: TenderRequest) -> DomainError:
    return DomainError(
        "E-STS-01",
        f"Нельзя {action} заявку {req.number} в статусе „{req.get_status_display()}“.",
        status=409)


def require(ctx: Ctx, flag: str) -> None:
    if not ctx.can(NODE, flag):
        raise _deny("Недостаточно прав на заявки тендерного модуля.")


# ── видимость ───────────────────────────────────────────────────────────

def sees_all(ctx: Ctx) -> bool:
    return ctx.can(NODE_ALL, "view")


def can_view(ctx: Ctx, req: TenderRequest) -> bool:
    return req.author_id == ctx.user_id or sees_all(ctx)


def _find(request_id, *, lock: bool = False) -> TenderRequest | None:
    try:
        key = uuid.UUID(str(request_id))
    except (ValueError, AttributeError, TypeError):
        return None
    rows = TenderRequest.objects.select_for_update() if lock else TenderRequest.objects
    return rows.filter(pk=key).first()


def get_visible(ctx: Ctx, request_id, *, lock: bool = False) -> TenderRequest:
    req = _find(request_id, lock=lock)
    if req is None or not can_view(ctx, req):
        raise _not_found()
    return req


def was_sent(req: TenderRequest) -> bool:
    """Отправлялась ли заявка: не черновик — или черновик после отзыва (части,
    то есть ЗЗ в БЗО, у неё уже были)."""
    return req.status != TenderRequestStatus.DRAFT or req.parts.exists()


def allowed_actions(ctx: Ctx, req: TenderRequest) -> list[str]:
    """Кнопки карточки — по авторству, статусу и узлу. Действия отправки,
    отзыва, отмены и исключения части выполняет T1.3."""
    if req.author_id != ctx.user_id or not ctx.can(NODE, "edit"):
        return []
    status = req.status
    actions: list[str] = []
    if status in EDITABLE:
        actions += ["save", "submit", "cancel"]
    if (status == TenderRequestStatus.DRAFT and ctx.can(NODE, "delete")
            and not was_sent(req)):
        actions.append("delete")
    if status == TenderRequestStatus.IN_APPROVAL:
        actions.append("withdraw")
    if status in (TenderRequestStatus.APPROVED, TenderRequestStatus.REJECTED):
        actions.append("cancel")
    # Условие — то же, что у самого перехода (``status.excludable_parts``):
    # кнопка не предлагается там, где сервис ответит отказом.
    if excludable_parts(req).exists():
        actions.append("exclude")
    return actions


# ── роль инициатора и проект ────────────────────────────────────────────

def initiator_roles(ctx: Ctx) -> list[str]:
    """Роли БЗО, в которых пользователь подаёт заявки: право создавать заявки
    БЗО и группа статей роли (как ``bpp.services.actor.Actor.initiator_roles``,
    но через ``access``/``refdata``)."""
    if not ctx.can("bpp.requests", "create"):
        return []
    groups = {g["code"]: g for g in refdata.article_groups() if g["is_active"]}
    return [role.value for role, code in ROLE_GROUP.items()
            if code in groups and ctx.can(groups[code]["node_key"], "view")]


def _role_for(ctx: Ctx, wanted: str | None) -> str:
    roles = initiator_roles(ctx)
    if not roles:
        raise _deny("У вас нет роли БЗО, в которой подают заявки на закупку.")
    if not wanted:
        if len(roles) == 1:
            return roles[0]
        raise DomainError(
            "E-REQ-01", "Не удалось сохранить заявку. Не заполнено поле „Роль инициатора“. "
                        "Выберите роль и повторите.",
            fields=[{"field": "initiator_role", "message": "Выберите роль"}])
    if wanted not in roles:
        raise _deny(f"Роль „{InitiatorRole(wanted).label}“ вам не назначена.")
    return wanted


def _check_project(ctx: Ctx, role: str, project_id) -> None:
    brief = projects.project_brief([str(project_id)]).get(str(project_id))
    if brief is None:
        raise DomainError("E-NOT-FOUND", "Проект не найден.", status=404,
                          fields=[{"field": "project_id", "message": "Проект не найден"}])
    if brief["status"] != "active":
        raise DomainError(
            "E-PRJ-03", f"Проект {brief['code']} не активен — заявки по нему не подаются.",
            fields=[{"field": "project_id", "message": "Проект не активен"}])
    # BR-014: ПМ — только проекты-участия; СН — все активные.
    if role == InitiatorRole.PM and not projects.is_member(str(project_id), ctx.user_id):
        raise DomainError("E-REQ-05", f"Проект {brief['code']} вам недоступен.", status=403,
                          fields=[{"field": "project_id", "message": "Проект недоступен"}])


# ── проверки полей ──────────────────────────────────────────────────────

def _articles(ids) -> dict[str, dict]:
    wanted = [str(i) for i in ids if i]
    return refdata.article_brief(wanted) if wanted else {}


def _check_article(field_name: str, article_id, briefs: dict[str, dict]) -> None:
    brief = briefs.get(str(article_id))
    if brief is None:
        raise _bad(field_name, "статья не найдена")
    if not brief["is_active"]:
        raise _bad(field_name, f"статья „{brief['name']}“ в архиве", code="E-REF-03")


def _amount(field_name: str, value, *, step: Decimal, ceiling: Decimal,
            label: str) -> Decimal:
    """Положительное число в пределах столбца БД; ``label`` — «что», для текста
    «<что>: нужно число больше нуля»."""
    if value is None or Decimal(value) <= 0:
        raise _bad(field_name, f"{label}: нужно число больше нуля")
    value = Decimal(value).quantize(step, rounding=ROUND_HALF_UP)
    if value <= 0 or value >= ceiling:
        raise _bad(field_name, f"{label}: число вне допустимого диапазона")
    return value


def _clean_header(data: dict) -> dict:
    """Поля шапки из тела (только переданные); ``None`` у поля без пустого
    значения — «не менять»."""
    out: dict = {}
    if data.get("purchase_type") is not None:
        out["purchase_type"] = PurchaseType(data["purchase_type"]).value
    if "need_date" in data:
        out["need_date"] = data["need_date"]
    for name in _TEXTS:
        if data.get(name) is not None:
            out[name] = data[name].strip()[:TEXT_MAX]
    for name in _FLAGS:
        if data.get(name) is not None:
            out[name] = bool(data[name])
    given = {name: data[name] for name in _ARTICLES if name in data}
    briefs = _articles(given.values())
    for name, value in given.items():
        if value:
            _check_article(name, value, briefs)
        out[name] = value or None
    for name in _AMOUNTS:
        if name in data:
            value = data[name]
            out[name] = None if value is None else _amount(
                name, value, step=MONEY_STEP, ceiling=MONEY_MAX, label="плановая сумма")
    return out


def _clean_items(items: list[dict], existing: set[str]) -> list[dict]:
    """Позиции формы. Строка либо полная, либо её нет: позиция без количества
    или цены не хранится (ограничения БД ``qty > 0``, ``plan_price > 0``)."""
    if len(items) > MAX_ITEMS:
        raise _bad("items", f"не больше {MAX_ITEMS} позиций", code="E-REQ-06")
    uoms = refdata.uom_brief([str(i["uom_id"]) for i in items if i.get("uom_id")])
    briefs = _articles(i.get("article_id") for i in items)
    cleaned = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        where = f"items[{index}]"
        row_id = str(item["id"]) if item.get("id") else None
        if row_id is not None and row_id not in existing:
            raise _bad(f"{where}.id", "позиция не найдена в заявке")
        if row_id is not None and row_id in seen:
            # Две строки формы на одну позицию: вторая молча затёрла бы первую.
            raise _bad(f"{where}.id", "позиция указана в форме дважды")
        if row_id is not None:
            seen.add(row_id)
        name = (item.get("name") or "").strip()
        if not NAME_MIN <= len(name) <= NAME_MAX:
            raise _bad(f"{where}.name",
                       f"наименование — от {NAME_MIN} до {NAME_MAX} символов")
        uom = uoms.get(str(item.get("uom_id") or ""))
        if uom is None or not uom["is_active"]:
            raise _bad(f"{where}.uom_id", "выберите единицу измерения из справочника")
        qty = _amount(f"{where}.qty", item.get("qty"), step=QTY_STEP, ceiling=QTY_MAX,
                      label="количество")
        price = _amount(f"{where}.plan_price", item.get("plan_price"), step=MONEY_STEP,
                        ceiling=MONEY_MAX, label="плановая цена")
        if item.get("article_id"):
            _check_article(f"{where}.article_id", item["article_id"], briefs)
        cleaned.append({
            "id": row_id, "name": name, "specs": (item.get("specs") or "")[:TEXT_MAX],
            "uom_id": str(item["uom_id"]), "qty": qty, "plan_price": price,
            "need_date": item.get("need_date"),
            "article_id": str(item["article_id"]) if item.get("article_id") else None,
        })
    return cleaned


def _write_items(req: TenderRequest, items: list[dict], actor_id: int) -> None:
    """Позиции по порядку формы. Строка с ``id`` правится на месте (её часть и
    связь с позицией ЗЗ остаются), без ``id`` — новая, не названные —
    удаляются. Номера строк — заново (уникальность отложена до коммита)."""
    keep = {item["id"] for item in items if item["id"]}
    req.items.exclude(pk__in=keep).delete()
    current = {str(row.pk): row for row in req.items.all()}
    for line_no, item in enumerate(items, start=1):
        fields = {k: v for k, v in item.items() if k != "id"}
        row = current.get(item["id"]) if item["id"] else None
        if row is None:
            TenderRequestItem.objects.create(request=req, line_no=line_no,
                                             created_by=actor_id, updated_by=actor_id,
                                             **fields)
            continue
        for name, value in fields.items():
            setattr(row, name, value)
        row.line_no, row.updated_by = line_no, actor_id
        row.save()


def _snapshot(req: TenderRequest) -> dict:
    return {
        "project_id": str(req.project_id), "initiator_role": req.initiator_role,
        "article_id": str(req.article_id or ""), "purchase_type": req.purchase_type,
        "need_date": str(req.need_date or ""),
        "needs_delivery": req.needs_delivery,
        "delivery_plan_amount": str(req.delivery_plan_amount or ""),
        "needs_works": req.needs_works, "works_plan_amount": str(req.works_plan_amount or ""),
        "items": [{"line_no": i.line_no, "name": i.name, "qty": str(i.qty),
                   "plan_price": str(i.plan_price)} for i in req.items.all()],
    }


# ── черновик ────────────────────────────────────────────────────────────

@transaction.atomic
def create_draft(ctx: Ctx, data: dict) -> TenderRequest:
    require(ctx, "create")
    role = _role_for(ctx, data.get("initiator_role"))
    if not data.get("project_id"):
        raise DomainError(
            "E-REQ-01", "Не удалось сохранить заявку. Не заполнено поле „Проект“. "
                        "Выберите проект и повторите.",
            fields=[{"field": "project_id", "message": "Выберите проект"}])
    _check_project(ctx, role, data["project_id"])
    header = _clean_header(data)
    items = _clean_items(data.get("items") or [], existing=set())
    req = TenderRequest(number=next_number(PREFIX), author_id=ctx.user_id,
                        initiator_role=role, project_id=data["project_id"],
                        created_by=ctx.user_id, updated_by=ctx.user_id, **header)
    req.save()
    _write_items(req, items, ctx.user_id)
    audit.record(req, "created", actor_id=ctx.user_id, changes=_snapshot(req))
    return req


@transaction.atomic
def update_draft(ctx: Ctx, request_id, *, expected_version: int | None,
                 data: dict) -> TenderRequest:
    require(ctx, "edit")
    req = get_visible(ctx, request_id, lock=True)
    if req.author_id != ctx.user_id:
        raise _deny(f"Править заявку {req.number} может только её автор.")
    if req.status not in EDITABLE:
        raise _state_error("править", req)
    check_version(req, expected_version)
    before = _snapshot(req)
    role = req.initiator_role
    if data.get("initiator_role") and data["initiator_role"] != req.initiator_role:
        role = _role_for(ctx, data["initiator_role"])
    project_id = data.get("project_id") or req.project_id
    if role != req.initiator_role or str(project_id) != str(req.project_id):
        _check_project(ctx, role, project_id)
    header = _clean_header(data)
    if data.get("items") is not None:
        existing = {str(pk) for pk in req.items.values_list("pk", flat=True)}
        _write_items(req, _clean_items(data["items"], existing), ctx.user_id)
    req.initiator_role, req.project_id = role, project_id
    for name, value in header.items():
        setattr(req, name, value)
    req.version += 1
    req.updated_by = ctx.user_id
    req.save()
    audit.record(req, "updated", actor_id=ctx.user_id,
                 changes={"before": before, "after": _snapshot(req)})
    return req


@transaction.atomic
def delete_draft(ctx: Ctx, request_id, *, expected_version: int | None) -> None:
    require(ctx, "delete")
    req = get_visible(ctx, request_id, lock=True)
    if req.author_id != ctx.user_id:
        raise _deny(f"Удалить заявку {req.number} может только её автор.")
    if req.status != TenderRequestStatus.DRAFT or was_sent(req):
        # Отправлявшаяся заявка — с ЗЗ в БЗО: её отменяют, а не удаляют.
        raise _state_error("удалить", req)
    check_version(req, expected_version)
    audit.record(req, "deleted", actor_id=ctx.user_id, changes=_snapshot(req))
    # Ни разу не отправленная заявка уносит файлы физически (ТЗ §21).
    files.owner_deleted(FILE_OWNER, req.pk, actor_id=ctx.user_id)
    req.delete()


# ── чтение ──────────────────────────────────────────────────────────────

def _names(user_ids) -> dict[int, str]:
    return {row["id"]: row["full_name"] for row in users.get_users_brief(set(user_ids))}


def _date(value) -> str | None:
    return value.isoformat() if value else None


def _uuid(value) -> str | None:
    return str(value) if value else None


def _money(value) -> str | None:
    return None if value is None else str(value)


def card(ctx: Ctx, req: TenderRequest) -> dict:
    project = projects.project_brief([str(req.project_id)]).get(str(req.project_id))
    return {
        "id": str(req.pk), "number": req.number, "status": req.status,
        "status_display": req.get_status_display(), "version": req.version,
        "author_id": req.author_id, "author_name": _names([req.author_id]).get(req.author_id, ""),
        "initiator_role": req.initiator_role, "project_id": str(req.project_id),
        "project": ({"id": project["id"], "code": project["code"], "name": project["name"]}
                    if project else None),
        "article_id": _uuid(req.article_id), "purchase_type": req.purchase_type,
        "need_date": _date(req.need_date), "delivery_address": req.delivery_address,
        "justification": req.justification, "needs_delivery": req.needs_delivery,
        "delivery_article_id": _uuid(req.delivery_article_id),
        "delivery_plan_amount": _money(req.delivery_plan_amount),
        "needs_works": req.needs_works, "works_scope": req.works_scope,
        "works_article_id": _uuid(req.works_article_id),
        "works_plan_amount": _money(req.works_plan_amount),
        "allow_analogs": req.allow_analogs, "allow_partial": req.allow_partial,
        "status_comment": req.status_comment, "rework_comment": req.rework_comment,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "allowed_actions": allowed_actions(ctx, req),
        "items": [{"id": str(i.pk), "line_no": i.line_no, "name": i.name, "specs": i.specs,
                   "uom_id": str(i.uom_id), "qty": str(i.qty),
                   "plan_price": str(i.plan_price), "need_date": _date(i.need_date),
                   "article_id": _uuid(i.article_id)}
                  for i in req.items.order_by("line_no")],
        "parts": [{"id": str(p.pk), "kind": p.kind, "article_id": str(p.article_id),
                   "purchase_type": p.purchase_type, "bpp_request_id": _uuid(p.bpp_request_id),
                   "bpp_number": p.bpp_number, "bpp_status": p.bpp_status,
                   "excluded_at": p.excluded_at.isoformat() if p.excluded_at else None}
                  for p in req.parts.order_by("kind", "created_at")],
    }


def registry(ctx: Ctx, *, statuses: list[str], project_id: str | None, query: str,
             page: int, page_size: int) -> dict:
    require(ctx, "view")
    rows = TenderRequest.objects.all()
    if not sees_all(ctx):
        rows = rows.filter(author_id=ctx.user_id)
    if statuses:
        rows = rows.filter(status__in=statuses)
    if project_id:
        try:
            rows = rows.filter(project_id=uuid.UUID(project_id))
        except ValueError:
            raise _bad("project_id", "неверный ключ проекта") from None
    if query:
        rows = rows.filter(Q(number__icontains=query) | Q(items__name__icontains=query))
        rows = rows.distinct()
    total = rows.count()
    start = (page - 1) * page_size
    found = list(rows.order_by("-created_at", "-number")[start:start + page_size])
    names = _names(r.author_id for r in found)
    briefs = projects.project_brief([str(r.project_id) for r in found]) if found else {}
    return {
        "results": [{
            "id": str(r.pk), "number": r.number, "status": r.status,
            "status_display": r.get_status_display(), "project_id": str(r.project_id),
            "project_code": (briefs.get(str(r.project_id)) or {}).get("code", ""),
            "project_name": (briefs.get(str(r.project_id)) or {}).get("name", ""),
            "purchase_type": r.purchase_type, "need_date": _date(r.need_date),
            "created_at": r.created_at.isoformat(), "author_id": r.author_id,
            "author_name": names.get(r.author_id, ""),
        } for r in found],
        "total": total, "page": page, "page_size": page_size,
    }


# ── регистрация ─────────────────────────────────────────────────────────

def _history_can_view(request, object_id: str) -> bool:
    ctx = Ctx.from_request(request)
    req = _find(object_id)
    return req is not None and ctx.can(NODE, "view") and can_view(ctx, req)


def register() -> None:
    """Журнал заявки читается только тем, кто видит саму заявку (T-28)."""
    audit.register_history_access(OBJECT_TYPE, _history_can_view)
