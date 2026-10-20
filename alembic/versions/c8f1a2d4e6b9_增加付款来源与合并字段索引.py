"""增加付款来源与合并字段索引

Revision ID: c8f1a2d4e6b9
Revises: b7e9d4c2a6f1
Create Date: 2026-10-21 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c8f1a2d4e6b9"
down_revision: Union[str, None] = "b7e9d4c2a6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_payments_source", "payments", ["source"])
    op.create_index(
        "ix_participants_merged_into_id",
        "participants",
        ["merged_into_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_participants_merged_into_id", table_name="participants")
    op.drop_index("ix_payments_source", table_name="payments")
