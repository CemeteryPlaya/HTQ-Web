"""Запросы БЗО компании, чьё БЗО ведётся в другой компании (решение 19.10).

У Hi-Tech Group LTD «Проекты», бюджеты, заявки, план, договоры, счета, их
файлы и согласования живут в схеме головного офиса — Hi-Tech Qazaqstan: ПМ
входят в LTD, а данные одни, без копий и расхождений
(``Company.bpp_data_company``). ``CompanyContextMiddleware`` ставит для таких
запросов контекст, ``search_path`` и ``request.company`` компании данных:
права считаются там, где лежат данные, — гейт модуля, узлы сервисов БЗО
(``bpp/services/core/permissions.py``), «Проектов» и их структуры, выгрузки и
ключи идемпотентности. Компания адреса остаётся в ``request.address_company``:
по ней ``api_view`` сверяет claim токена (токен выдан на свой поддомен) и
архив, а ``ServiceGateMiddleware`` — её рубильник.

Какой запрос — БЗО, решает только адрес, без разбора тела:

- ``/api/bpp/`` и ``/api/project/`` — сам модуль и «Проекты»;
- ``/api/files/v1/bpp.`` — документы владельцев БЗО (тип владельца в пути);
- ``GET /api/signoff/v1/processes?subject_type=bpp.…`` — вкладка «Ход
  согласования» в карточке документа БЗО (``features/bpp/core/ApprovalTab``).

Не направляется ``/api/bpp/v1/holding/`` — «Сводка группы по БЗО» читает
представления холдинга по всем компаниям и отвечает только на поддомене
холдинга, то есть в его собственном контексте. Всё прочее — кадры, задачи,
согласования самой компании — остаётся в компании запроса.
"""

from __future__ import annotations

_PREFIXES = ("/api/bpp/", "/api/project/", "/api/files/v1/bpp.")
_NOT_DELEGATED = ("/api/bpp/v1/holding/",)
_SIGNOFF_PROCESSES = ("/api/signoff/v1/processes", "/api/signoff/v1/processes/")


def is_bpp_request(request) -> bool:
    """Относится ли запрос к данным БЗО (см. докстринг модуля)."""
    path = request.path
    if path.startswith(_NOT_DELEGATED):
        return False
    if path.startswith(_PREFIXES):
        return True
    if path in _SIGNOFF_PROCESSES and request.method == "GET":
        return request.GET.get("subject_type", "").startswith("bpp.")
    return False


def is_delegated(request) -> bool:
    """Запрос уже переведён middleware в компанию данных другой компании."""
    company = getattr(request, "company", None)
    address = getattr(request, "address_company", None)
    return bool(company and address and company["slug"] != address["slug"])
