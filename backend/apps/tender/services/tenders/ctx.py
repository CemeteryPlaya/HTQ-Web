"""Кто спрашивает: пользователь и компания запроса, права по узлу реестра.

Общая основа сервисов тендеров и справочников участников. Расчёт ролей гейта
``api_view(module=…)`` (``request.access_resolution``) переиспользуется, если
совпали компания и пользователь (приём ``apps/bpp/services/core/permissions.py``).
Своя копия, а не ``services/requests/crud.Ctx``: у подразделов разные
исполнители, и правка одного не должна ломать другой.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.access import interface as access
from htqweb.errors import DomainError
from htqweb.tenancy import current_company_or_none


@dataclass
class Ctx:
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
        return cls(token, current_company_or_none())

    @property
    def user_id(self) -> int:
        return int(self.token.user_id)

    def can(self, node: str, flag: str) -> bool:
        if node not in self._flags:
            self._flags[node] = access.flags_for(self.token, node, self.company,
                                                 resolution=self.resolution)
        return flag in self._flags[node]

    def require(self, node: str, flag: str, text: str) -> None:
        if not self.can(node, flag):
            raise deny(text)


def deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def bad(field_name: str, text: str, *, code: str = "E-VAL-01",
        status: int = 422) -> DomainError:
    """Отказ по полю формы: ``fields=[{field, message}]`` с именем поля тела."""
    return DomainError(code, f"{text[:1].upper()}{text[1:]}.", status=status,
                       fields=[{"field": field_name, "message": text}])
