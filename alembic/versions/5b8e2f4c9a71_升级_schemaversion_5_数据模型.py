"""升级 schemaVersion 5 数据模型

Revision ID: 5b8e2f4c9a71
Revises: 9f3c2a7d5b10
Create Date: 2026-10-19 09:00:00.000000

破坏性迁移：删除全部 Room 相关数据、旧指导语与旧条件材料。
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "5b8e2f4c9a71"
down_revision: Union[str, None] = "9f3c2a7d5b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROOM_DATA_TABLES = (
    "turn_submissions",
    "turns",
    "game_trials",
    "questionnaire_drafts",
    "questionnaire_responses",
    "payments",
    "bookings",
    "room_participants",
    "room_config_revisions",
    "room_events",
    "room_timers",
    "rooms",
)


def _drop_foreign_keys(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    names = bind.execute(
        sa.text(
            "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name "
            "AND COLUMN_NAME = :column_name AND REFERENCED_TABLE_NAME IS NOT NULL"
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalars().all()
    for name in names:
        op.drop_constraint(name, table_name, type_="foreignkey")


def upgrade() -> None:
    for table_name in ROOM_DATA_TABLES:
        op.execute(sa.text(f"DELETE FROM {table_name}"))
    op.execute(sa.text("DELETE FROM instruction_versions"))
    _drop_foreign_keys("rooms", "condition_version_id")
    op.drop_column("rooms", "condition_version_id")
    op.drop_column("rooms", "base_pay_cents")
    op.drop_column("rooms", "performance_rate_cents")
    op.drop_column("rooms", "showup_pay_cents")
    op.drop_table("condition_versions")

    op.create_table(
        "troop_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("built_in", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "troop_profile_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("troop_profile_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rows_json", sa.JSON(), nullable=False),
        sa.Column("practice_trials", sa.Integer(), nullable=False),
        sa.Column("formal_trials", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["troop_profile_id"], ["troop_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "troop_profile_id", "version", name="uq_troop_profile_versions_profile_version"
        ),
    )
    op.create_index(
        "ix_troop_profile_versions_status", "troop_profile_versions", ["status"], unique=False
    )
    op.create_table(
        "map_group_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("cols", sa.Integer(), nullable=False),
        sa.Column("spawn_a_index", sa.Integer(), nullable=False),
        sa.Column("spawn_b_index", sa.Integer(), nullable=False),
        sa.Column("troop_profile_version_id", sa.String(length=36), nullable=False),
        sa.Column("practice_trials", sa.Integer(), nullable=False),
        sa.Column("formal_trials", sa.Integer(), nullable=False),
        sa.Column("practice_turn_cap", sa.Integer(), nullable=False),
        sa.Column("practice_turn_seconds", sa.Integer(), nullable=False),
        sa.Column("formal_turn_cap", sa.Integer(), nullable=False),
        sa.Column("formal_turn_seconds", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("randomize_formal", sa.Boolean(), nullable=False),
        sa.Column("base_pay_cents", sa.Integer(), nullable=False),
        sa.Column("performance_rate_cents", sa.Integer(), nullable=False),
        sa.Column("performance_cap_cents", sa.Integer(), nullable=False),
        sa.Column("showup_pay_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["troop_profile_version_id"], ["troop_profile_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_map_group_versions_name_version"),
    )
    op.create_index("ix_map_group_versions_status", "map_group_versions", ["status"], unique=False)
    op.create_table(
        "maps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("map_group_version_id", sa.String(length=36), nullable=False),
        sa.Column("slot", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("size_token", sa.String(length=20), nullable=False),
        sa.Column("factor_level", sa.String(length=200), nullable=False),
        sa.Column("player_suffix", sa.String(length=10), nullable=False),
        sa.Column("cells_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["map_group_version_id"], ["map_group_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("map_group_version_id", "slot", name="uq_maps_group_slot"),
        sa.UniqueConstraint("map_group_version_id", "name", name="uq_maps_group_name"),
    )
    op.create_table(
        "participant_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("room_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("real_name_encrypted", sa.Text(), nullable=False),
        sa.Column("alipay_phone_encrypted", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("document_number_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id", "participant_id", name="uq_participant_identities_room_participant"
        ),
    )

    op.add_column("rooms", sa.Column("map_group_version_id", sa.String(length=36), nullable=False))
    op.create_foreign_key(
        "fk_rooms_map_group_versions",
        "rooms",
        "map_group_versions",
        ["map_group_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_rooms_map_group_version_id", "rooms", ["map_group_version_id"], unique=False
    )
    op.alter_column(
        "rooms",
        "wait_window_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("600"),
    )
    op.alter_column(
        "rooms",
        "reconnect_window_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("600"),
    )

    op.alter_column(
        "instruction_versions",
        "name",
        existing_type=sa.String(length=120),
        type_=sa.String(length=300),
        existing_nullable=False,
    )
    op.add_column(
        "instruction_versions", sa.Column("map_group_prefix", sa.String(length=200), nullable=False)
    )
    op.create_index(
        "ix_instruction_versions_map_group_prefix",
        "instruction_versions",
        ["map_group_prefix"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_instruction_versions_map_group_prefix", table_name="instruction_versions")
    op.drop_column("instruction_versions", "map_group_prefix")
    op.alter_column(
        "instruction_versions",
        "name",
        existing_type=sa.String(length=300),
        type_=sa.String(length=120),
        existing_nullable=False,
    )

    op.alter_column(
        "rooms",
        "reconnect_window_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "rooms",
        "wait_window_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=None,
    )
    op.drop_constraint("fk_rooms_map_group_versions", "rooms", type_="foreignkey")
    op.drop_index("ix_rooms_map_group_version_id", table_name="rooms")
    op.drop_column("rooms", "map_group_version_id")

    op.drop_table("participant_identities")
    op.drop_table("maps")
    op.drop_table("map_group_versions")
    op.drop_table("troop_profile_versions")
    op.drop_table("troop_profiles")

    op.create_table(
        "condition_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("cols", sa.Integer(), nullable=False),
        sa.Column("cells_json", sa.JSON(), nullable=False),
        sa.Column("visuals_json", sa.JSON(), nullable=False),
        sa.Column("base_a_index", sa.Integer(), nullable=False),
        sa.Column("base_b_index", sa.Integer(), nullable=False),
        sa.Column("trial_params_json", sa.JSON(), nullable=False),
        sa.Column("practice_trials", sa.Integer(), nullable=False),
        sa.Column("formal_trials", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("turn_seconds", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("randomize_formal", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_condition_versions_name_version"),
    )
    op.create_index("ix_condition_versions_status", "condition_versions", ["status"], unique=False)

    op.add_column("rooms", sa.Column("condition_version_id", sa.String(length=36), nullable=False))
    op.add_column(
        "rooms",
        sa.Column("base_pay_cents", sa.Integer(), nullable=False, server_default=sa.text("4500")),
    )
    op.add_column(
        "rooms",
        sa.Column(
            "performance_rate_cents", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.add_column(
        "rooms",
        sa.Column("showup_pay_cents", sa.Integer(), nullable=False, server_default=sa.text("1000")),
    )
    op.create_foreign_key(
        "fk_rooms_condition_versions",
        "rooms",
        "condition_versions",
        ["condition_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
