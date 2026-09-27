"""Кто выполняет действие — для сервисов бюджета, заявок и плана (B2.x).

Права модуля тоньше уровня модуля проверяются по узлам реестра
(``services/core/permissions.py``, A1.4), а тот работает от запроса: расчёт
ролей кладёт в запрос гейт ``api_view``. ``Actor`` держит запрос и отвечает
на вопросы сервисов словами предметной области, не размазывая по ним
названия узлов.

Принадлежность («свой документ», «участник проекта») решает сам документ —
здесь только роли.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from apps.bpp.models import InitiatorRole
from apps.bpp.services.core import permissions
from apps.project import interface as projects
from apps.refdata import interface as refdata

#: Группа статей роли инициатора (BR-010): коды групп ``refdata.ArticleGroup``.
ROLE_GROUP = {InitiatorRole.SN: "supply", InitiatorRole.PM: "pm"}


@dataclass
class Actor:
    request: object
    _flags: dict = field(default_factory=dict, repr=False)

    @property
    def user_id(self) -> int:
        return self.request.token.user_id

    def can(self, node: str, flag: str) -> bool:
        if node not in self._flags:
            self._flags[node] = permissions.flags(self.request, node)
        return flag in self._flags[node]

    # ── статьи ──────────────────────────────────────────────────────────

    @cached_property
    def group_codes(self) -> list[str]:
        """Группы статей, открытые пользователю (BR-010)."""
        return permissions.article_groups_for(self.request)

    @cached_property
    def _groups_by_id(self) -> dict[str, dict]:
        return {group["id"]: group for group in refdata.article_groups()}

    def sees_article(self, brief: dict | None) -> bool:
        """Статья из группы, открытой пользователю (``refdata.article_brief``)."""
        if brief is None:
            return False
        group = self._groups_by_id.get(brief["group_id"])
        return bool(group) and group["code"] in self.group_codes

    def initiator_roles(self) -> list[str]:
        """Роли, в которых пользователь может подать заявку: право создавать
        заявки и группа статей этой роли (ТЗ §7.1)."""
        if not self.can("bpp.requests", "create"):
            return []
        return [role for role, code in ROLE_GROUP.items() if code in self.group_codes]

    # ── проекты ─────────────────────────────────────────────────────────

    @cached_property
    def sees_all_projects(self) -> bool:
        """ПМ видит только проекты-участия (BR-014); узел ``project.all``
        отличает его от остальных (миграция ``access/0015``)."""
        return self.can("project.all", "view")

    @cached_property
    def member_project_ids(self) -> set[str]:
        return set(projects.member_project_ids(self.user_id))

    def sees_project(self, project_id) -> bool:
        return self.sees_all_projects or str(project_id) in self.member_project_ids
