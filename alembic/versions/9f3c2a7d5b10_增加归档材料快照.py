"""增加归档材料快照

Revision ID: 9f3c2a7d5b10
Revises: 40dedb1d81c7
Create Date: 2026-10-18 05:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "9f3c2a7d5b10"
down_revision: Union[str, None] = "40dedb1d81c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("archive_snapshot_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("rooms", "archive_snapshot_json")
