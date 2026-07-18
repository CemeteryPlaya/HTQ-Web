"""Merge two 003 heads after Rus / минус-на-минус branch merge.

Revision ID: 004_merge_heads
Revises: 003_kz_holidays_2026, 003_employee_department_scope
Create Date: 2026-05-06

Both 003 revisions branched off 002_replica_tables in parallel feature
branches and merged together, leaving Alembic with two heads. This file
exists solely to collapse them into a single linear head — it has no DDL.

Running ``alembic upgrade head`` after this file is added will, on a DB
that's already at 003_kz_holidays_2026, additionally apply
003_employee_department_scope (the head it never saw) and then mark this
merge as the new single head.
"""

from typing import Sequence, Union


revision: str = "004_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "003_kz_holidays_2026",
    "003_employee_department_scope",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
