"""Ручки «Параметры модуля» ``/api/bpp/v1/settings…`` — вкладка экрана
«Настройки» (ТЗ §05 п.10 «Администрирование»).

- ``GET settings`` — параметры реестра ``services/core/settings.EDITABLE``
  со значением (строки в таблице нет — умолчание модуля) и правилом
  проверки: ``bpp.settings:view`` (ФД, АДМ);
- ``PATCH settings/<ключ>`` ``{value}`` — смена параметра:
  ``bpp.settings:edit`` (АДМ). Неверное значение — 422 E-VAL-01, ключ вне
  реестра (в том числе служебный, например итог ночной сверки) — 404.
  Запись — через ``set_setting``, со строкой журнала; ручка идемпотентна
  (``Idempotency-Key``).

Подмодуля у параметров нет: путь ``settings`` не входит ни в один префикс
``bpp_*`` (``htqweb/middleware/service_gate.py``), и рубильник у них — только
у модуля.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view

from .schemas import settings as schemas
from .services.core import audit, permissions
from .services.core import settings as service

SETTINGS_NODE = "bpp.settings"


def _need(request, flag: str, action: str) -> None:
    if not permissions.can(request, SETTINGS_NODE, flag):
        raise DomainError(
            "E-ACC-01",
            f"У вас нет прав: {action}. Если это ошибка, обратитесь к администратору.",
            status=403)


# Журнал смены параметра (ключ — объект журнала) читает тот, кто видит параметры.
audit.register_history_access(
    "bpp.modulesetting",
    lambda request, _object_id: permissions.can(request, SETTINGS_NODE, "view"))


@api_view(methods=("GET",), module="bpp", level="read")
def settings_list(request):
    _need(request, "view", "просмотр параметров модуля")
    return service.list_params()


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.SettingUpdate,
          idempotent=True)
def setting_patch(request, key, data):
    _need(request, "edit", "правка параметров модуля")
    return service.update_param(key, data.value, actor_id=request.token.user_id)
