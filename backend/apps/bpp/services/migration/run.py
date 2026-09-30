"""Прогон переноса одной компании (B6.1) — шаги по порядку плана.

Вызывается командой внутри одной транзакции: любой ``MigrationStop``
откатывает всё, ``--dry-run`` откатывает и удачный прогон, оставляя отчёт.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.bpp.services.actor import Actor

from . import reference
from .documents import Documents
from .reconcile import Reconciliation
from .report import MigrationReport


@dataclass
class MigrationContext:
    snapshot: dict
    project_map: dict[int, dict]
    article_map: dict[int, dict]
    actor: Actor
    report: MigrationReport = field(default_factory=MigrationReport)
    counterparties: dict = field(default_factory=dict)
    project_by_admin: dict[int, str] = field(default_factory=dict)
    limits_by_admin: dict[int, dict] = field(default_factory=dict)
    documents: Documents | None = None


def run(ctx: MigrationContext) -> MigrationContext:
    ctx.counterparties = reference.counterparties(ctx.snapshot, ctx.report)
    ctx.project_by_admin = reference.project_ids(ctx.snapshot, ctx.project_map,
                                                 ctx.actor.user_id, ctx.report)
    ctx.limits_by_admin = reference.budgets_for(ctx.snapshot, ctx.project_by_admin,
                                                ctx.article_map, ctx.actor, ctx.report)
    ctx.documents = Documents(ctx).run()
    Reconciliation(ctx, ctx.documents).run()
    return ctx
