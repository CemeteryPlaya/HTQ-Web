"""Ручки справочника «Контрагенты» ``/api/bpp/v1/counterparties…`` (ТЗ §18,
L-08, задача A2.3).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня —
по узлам реестра (``services/core/permissions.can``):

- чтение — ``bpp.counterparties:view``;
- создание — ``bpp.counterparties:create`` (ФД, БУХ, СН, ПМ — ТЗ §05 п.9);
- правка карточки и банковских счетов — ``bpp.counterparties:edit`` (ФД, БУХ);
- блокировка, разблокировка, архив и метка «Проверенный» —
  ``bpp.counterparties.block:edit`` (ФД).

Записывающие ручки идемпотентны (``Idempotency-Key``), правка карточки
сверяет ``version`` (E-CON-01). Неверный UUID в адресе — 404.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from .schemas import counterparties as schemas
from .services.core import audit, permissions
from .services.counterparties import lookup, service
from .services.params import int_param

NODE = "bpp.counterparties"
BLOCK_NODE = "bpp.counterparties.block"
AUDIT_TYPE = "bpp.counterparty"


def _need(request, node: str, flag: str, action: str) -> None:
    if not permissions.can(request, node, flag):
        raise DomainError(
            "E-ACC-01",
            f"У вас нет прав: {action}. Если это ошибка, обратитесь к администратору.",
            status=403)


def _allowed_actions(request, card: dict) -> list[str]:
    """Кнопки карточки — по правам и статусу."""
    edit = permissions.can(request, NODE, "edit")
    block = permissions.can(request, BLOCK_NODE, "edit")
    status = card["status"]
    actions = []
    if edit and status != "archived":
        actions += ["edit", "add_account"]
    if block:
        if status == "active":
            actions.append("block")
        if status == "blocked":
            actions.append("unblock")
        if status != "archived":
            actions.append("archive")
        actions.append("verified")
    return actions


def _card(request, cp) -> dict:
    card = service.serialize(cp)
    card["allowed_actions"] = _allowed_actions(request, card)
    return card


def _sent(data) -> dict:
    """Присланные поля без ``null``: пустое значение в PATCH не стирает
    обязательное поле, а просто не трогает его."""
    return {key: value for key, value in data.model_dump(exclude_unset=True).items()
            if value is not None}


# Журнал карточки («История изменений») читает тот, кто видит справочник.
audit.register_history_access(
    AUDIT_TYPE, lambda request, _object_id: permissions.can(request, NODE, "view"))


# ── реестр и карточка ───────────────────────────────────────────────────

@api_view(methods=("GET",), module="bpp", level="read")
def counterparty_list(request):
    _need(request, NODE, "view", "просмотр контрагентов")
    params = request.GET
    return service.registry(
        q=params.get("q") or params.get("search") or None,
        countries=params.getlist("country"), statuses=params.getlist("status"),
        page=int_param(params, "page", 1, minimum=1),
        page_size=int_param(params, "page_size", service.DEFAULT_PAGE_SIZE),
        sort=params.get("sort") or None)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.CounterpartyCreate,
          status=201, idempotent=True)
def counterparty_create(request, data):
    _need(request, NODE, "create", "создание контрагента")
    return _card(request, service.create(data.model_dump(), actor_id=request.token.user_id))


def counterparties_collection(request):
    if request.method == "GET":
        return counterparty_list(request)
    if request.method == "POST":
        return counterparty_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def counterparty_get(request, counterparty_id):
    _need(request, NODE, "view", "просмотр контрагентов")
    return _card(request, lookup.get(uuid_or_404(counterparty_id)))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.CounterpartyUpdate,
          idempotent=True)
def counterparty_patch(request, counterparty_id, data):
    _need(request, NODE, "edit", "правка контрагента")
    sent = _sent(data)
    version = sent.pop("version", None)
    return _card(request, service.update(uuid_or_404(counterparty_id), sent,
                                         expected_version=version,
                                         actor_id=request.token.user_id))


def counterparty_detail(request, counterparty_id):
    if request.method == "GET":
        return counterparty_get(request, counterparty_id)
    if request.method == "PATCH":
        return counterparty_patch(request, counterparty_id)
    return json_error("Method Not Allowed", 405)


# ── статус и метка (ФД) ─────────────────────────────────────────────────

@api_view(methods=("POST",), module="bpp", level="write", body=schemas.BlockIn,
          idempotent=True)
def counterparty_block(request, counterparty_id, data):
    _need(request, BLOCK_NODE, "edit", "блокировка контрагента")
    return _card(request, service.block(uuid_or_404(counterparty_id), reason=data.reason,
                                        expected_version=data.version,
                                        actor_id=request.token.user_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def counterparty_unblock(request, counterparty_id, data):
    _need(request, BLOCK_NODE, "edit", "разблокировка контрагента")
    return _card(request, service.unblock(uuid_or_404(counterparty_id),
                                          expected_version=data.version,
                                          actor_id=request.token.user_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def counterparty_archive(request, counterparty_id, data):
    _need(request, BLOCK_NODE, "edit", "перевод контрагента в архив")
    return _card(request, service.archive(uuid_or_404(counterparty_id),
                                          expected_version=data.version,
                                          actor_id=request.token.user_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VerifiedIn,
          idempotent=True)
def counterparty_verified(request, counterparty_id, data):
    _need(request, BLOCK_NODE, "edit", "метка «Проверенный»")
    return _card(request, service.set_verified(uuid_or_404(counterparty_id), data.verified,
                                               expected_version=data.version,
                                               actor_id=request.token.user_id))


# ── банковские счета ────────────────────────────────────────────────────

@api_view(methods=("GET",), module="bpp", level="read")
def account_list(request, counterparty_id):
    _need(request, NODE, "view", "просмотр контрагентов")
    return service.list_accounts(uuid_or_404(counterparty_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.BankAccountCreate,
          status=201, idempotent=True)
def account_create(request, counterparty_id, data):
    _need(request, NODE, "edit", "банковские счета контрагента")
    return service.add_account(uuid_or_404(counterparty_id), data.model_dump(),
                               actor_id=request.token.user_id)


def counterparty_accounts(request, counterparty_id):
    if request.method == "GET":
        return account_list(request, counterparty_id)
    if request.method == "POST":
        return account_create(request, counterparty_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.BankAccountUpdate,
          idempotent=True)
def account_patch(request, account_id, data):
    _need(request, NODE, "edit", "банковские счета контрагента")
    return service.update_account(uuid_or_404(account_id), _sent(data),
                                  actor_id=request.token.user_id)
