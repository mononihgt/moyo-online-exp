"""增加付款来源与账号合并字段

Revision ID: b7e9d4c2a6f1
Revises: f4d2c8a1b7e3
Create Date: 2026-10-21 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e9d4c2a6f1"
down_revision: Union[str, None] = "f4d2c8a1b7e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'computed'"),
        ),
    )
    op.add_column(
        "participants",
        sa.Column("merged_into_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_participants_merged_into",
        "participants",
        "participants",
        ["merged_into_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_participants_merged_into", "participants", type_="foreignkey"
    )
    op.drop_column("participants", "merged_into_id")
    op.drop_column("payments", "source")
