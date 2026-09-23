"""Кадровые права вызывающего — по узлам реестра ``apps.access``.

С задачи 9 блока I «Единая модель прав» это ЕДИНСТВЕННАЯ модель прав
кадрового домена. До неё вьюхи звали ``apps.hr.access.resolve_hr_access`` —
уровень угадывался по названию должности (или брался из
``Position.permissions``), а гейт ``api_view(module="hr", level=…)`` стоял
поверх «И-И». Теперь гейт решает про ВХОД в ручку (уровень модуля), а этот
модуль — про конкретное ДЕЙСТВИЕ внутри неё (узел реестра функций).

Почему не только гейт. Уровень модуля считается по всему поддереву
``hr.*``: роль ``hr-senior`` несёт DELETE на оргструктуре, штатке и
календаре и потому агрегируется в ``admin`` — ровно как ``hr-lead``, — хотя
удалять сотрудников ей не положено. ``level="admin"`` на ``DELETE
/employees/{id}`` не отличил бы одну от другой; отличает проверка узла
``hr.employees`` на признак ``delete``.

Почему через СТАРЫЕ ключи. Вьюхи по-прежнему говорят ``EMPLOYEES_DELETE``,
``CALENDAR_MANAGE``, ``STAFFING_VIEW`` (``apps.hr.permissions``) — и это
не пережиток, а единственная таблица соответствия ключа узлу и признакам:
``apps.hr.legacy_roles.KEY_TO_NODE``. Ею же засеяны четыре системные роли
(``access/migrations/0005``), поэтому проверка «у вызывающего есть ВСЕ
признаки ключа на его узле» отвечает так же, как старая модель отвечала
держателю того же уровня, — без второго соответствия, которое разошлось
бы с первым. Каждое расхождение таблицы (например, ``EMPLOYEES_TRANSFER``
→ ``EDIT``, а не отдельный признак) — решение задачи 1, здесь оно только
воспроизводится.

Область («свой отдел» против «вся компания») — не признак узла, а
``scope`` выдачи роли (``PositionRole.scope_kind``/``RoleAssignment``);
берётся из ``access.permissions_for(...)["hr"]["scope"]`` — того же
ответа, которым живёт ``/api/access/v1/me`` и фронт.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.access import interface as access
from apps.hr.legacy_roles import KEY_TO_NODE
from htqweb.tenancy.context import current_company_or_none

COMPANY_SCOPE = "company"
DEPARTMENT_SCOPE = "department"


@dataclass
class NodeAccess:
    """Права одного вызывающего в одной компании — на время запроса.

    Роли считаются один раз (``access.resolution``) при первом обращении и
    переиспользуются всеми проверками ниже: карточка сотрудника за один
    PATCH спрашивает до пяти узлов (правка, перевод, идентичность, две
    секции Т-2) плюс область отдела — с пересчётом ролей на каждый это
    было бы полтора десятка запросов и столько же переключений схемы.
    """

    token: object
    company: str | None
    #: Запрос, если объект собран из него (``resolve(request)``): гейт
    #: ``api_view(module=, level=)`` уже посчитал роли и оставил их в
    #: ``request.access_resolution`` тройкой (компания, user_id, расчёт) —
    #: второй расчёт не нужен (блок I.2, R8).
    request: object | None = field(default=None, repr=False)
    _resolution: object = field(default=None, repr=False)
    _resolved: bool = field(default=False, repr=False)
    _scope: tuple[str, int | None] | None = field(default=None, repr=False)

    def _res(self):
        if not self._resolved:
            # Пара (компания, расчёт), которую оставил гейт. «Считали» — сам
            # факт наличия пары, а не значение расчёта: суперпользователю
            # ``access.resolution`` отдаёт ``None``, и это готовый ответ, не
            # повод считать заново. Ручки без гейта модуля (реестр
            # самообслуживания — ``/employees/me/card``) пары не получают и
            # считают сами, как раньше.
            cached = getattr(self.request, "access_resolution", None)
            # Расчёт годится только для той компании И того пользователя,
            # для которых сделан: иначе роли одной компании ответили бы за
            # другую, а роли вызывающего — за чужой токен, собранный на том
            # же запросе (блок I.2, B3).
            if (cached is not None and cached[0] == self.company
                    and cached[1] == getattr(self.token, "user_id", None)):
                self._resolution = cached[2]
            else:
                self._resolution = access.resolution(self.token, self.company)
            self._resolved = True
        return self._resolution

    def flags_for(self, node: str) -> frozenset[str]:
        return access.flags_for(self.token, node, self.company, resolution=self._res())

    def has(self, key: str) -> bool:
        """Есть ли у вызывающего старый ключ — то есть ВСЕ признаки его узла.

        ``KeyError`` на ключе вне ``KEY_TO_NODE`` — намеренно: ключ без узла
        (``DEFERRED_KEYS``, чужая аппка) проверять здесь нечем, и тихий
        ``False`` спрятал бы ошибку программиста за отказом в доступе.
        """
        node, flags = KEY_TO_NODE[key]
        return frozenset(flags) <= self.flags_for(node)

    @property
    def scope(self) -> tuple[str, int | None]:
        """``("company", None)`` | ``("department", id)`` | ``("none", None)``.

        Третье — модуля ``hr`` в карте нет вовсе (ни одной роли с узлом
        ``hr.*``): за гейтом такого вызывающего не бывает, но ручки без гейта
        (``/employees/me/card``) обязаны получить честное «ничего», а не
        исключение.
        """
        if self._scope is None:
            entry = access.permissions_for(
                self.token, self.company, resolution=self._res()).get("hr")
            if entry is None:
                self._scope = ("none", None)
            else:
                self._scope = (entry["scope"]["kind"], entry["scope"]["id"])
        return self._scope

    @property
    def can_read_all(self) -> bool:
        """Область — вся компания (старый ``hr.employees.view.all``)."""
        return self.scope[0] == COMPANY_SCOPE

    @property
    def department_id(self) -> int | None:
        """Отдел области, если она сужена до отдела; иначе ``None``."""
        kind, scope_id = self.scope
        return scope_id if kind == DEPARTMENT_SCOPE else None

    def can_see_department(self, department_id: int | None) -> bool:
        """Видит ли вызывающий сотрудников этого отдела.

        Порт ``HRAccess.can_see_department``: вся компания — любой отдел;
        область отдела — только свой; иное (``site``, нет модуля) — ничей.
        """
        if self.can_read_all:
            return True
        own = self.department_id
        return own is not None and department_id == own


def resolve(request) -> NodeAccess:
    """Права вызывающего текущего запроса: токен + компания поддомена.

    Компания — та же, по которой гейт ``api_view`` считал уровень модуля
    (``htqweb.tenancy.context.current_company_or_none``), поэтому ручка и её
    внутренние проверки никогда не смотрят на разные компании. Запрос
    передаётся целиком, чтобы переиспользовать уже посчитанные гейтом роли
    (``NodeAccess._res``).
    """
    return NodeAccess(request.token, current_company_or_none(), request=request)
