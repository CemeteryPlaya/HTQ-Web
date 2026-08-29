"""Доменные отказы аппки доступа.

Собраны в один модуль, чтобы вьюха переводила их в коды §4 спеки одним
``except``-каскадом, а не знала внутренности каждого сервиса.
"""


class AccessError(Exception):
    """Общий предок доменных отказов аппки."""


class RoleConflict(AccessError):
    """Код роли занят. Каталог общий, поэтому уникальность — платформенная."""


class RoleIsSystem(AccessError):
    """Служебную роль удалять нельзя."""


class RoleInUse(AccessError):
    """Роль назначена — отказ вместо тихого снятия прав у неизвестных людей."""

    def __init__(self, positions: int, users: int):
        self.positions = positions
        self.users = users
        super().__init__(f"роль назначена: должностей {positions}, пользователей {users}")


class UnknownRole(AccessError):
    """В наборе есть несуществующая роль."""


class UnknownModule(AccessError):
    """Модуля нет в реестре ``apps.core.models.KNOWN_SERVICES``."""


class ScopeInvalid(AccessError):
    """``scope_id`` не соответствует ``scope_kind``."""
