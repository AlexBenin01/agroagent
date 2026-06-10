"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("cols", sa.Integer(), nullable=False),
        sa.Column("crop_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("simulation_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("focus_x", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("focus_y", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "disease_catalog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("pathogen_type", sa.Text(), nullable=False),
        sa.Column("crop_type", sa.Text(), nullable=False),
        sa.Column("symptoms_visible", ARRAY(sa.Text()), nullable=False),
        sa.Column("favorable_temp_min", sa.Float(), nullable=False),
        sa.Column("favorable_temp_max", sa.Float(), nullable=False),
        sa.Column("favorable_humidity_min", sa.Float(), nullable=False),
        sa.Column("spread_speed", sa.Text(), nullable=False),
        sa.Column("severity_score", sa.Integer(), nullable=False),
        sa.Column("treatment_duration_h", sa.Integer(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("image_folder", sa.Text(), nullable=False),
    )

    op.create_table(
        "field_cells",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("soil_moisture", sa.Float(), nullable=False),
        sa.Column("soil_temperature", sa.Float(), nullable=False),
        sa.Column("nutrient_index", sa.Float(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False),
        sa.Column("disease_risk_score", sa.Float(), nullable=False),
        sa.Column("active_disease_id", UUID(as_uuid=True), sa.ForeignKey("disease_catalog.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_photo_path", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_id", "x", "y", name="uq_field_cell_xy"),
    )
    op.create_index("ix_field_cells_field_id", "field_cells", ["field_id"])

    op.create_table(
        "weather_daily",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("sim_date", sa.Date(), nullable=False),
        sa.Column("rainfall_mm", sa.Float(), nullable=False),
        sa.Column("humidity_pct", sa.Float(), nullable=False),
        sa.Column("temp_min", sa.Float(), nullable=False),
        sa.Column("temp_max", sa.Float(), nullable=False),
        sa.Column("is_forecast", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_id", "sim_date", "is_forecast", name="uq_weather_field_date_fc"),
    )

    op.create_table(
        "checkpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("cell_x", sa.Integer(), nullable=False),
        sa.Column("cell_y", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="agent"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "agent_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("cell_x", sa.Integer(), nullable=False),
        sa.Column("cell_y", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at_sim", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_tasks_field_status", "agent_tasks", ["field_id", "status"])

    op.create_table(
        "field_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("cell_x", sa.Integer(), nullable=True),
        sa.Column("cell_y", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sim_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_field_events_field_created", "field_events", ["field_id", "created_at"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("messages", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_sessions")
    op.drop_table("field_events")
    op.drop_table("agent_tasks")
    op.drop_table("checkpoints")
    op.drop_table("weather_daily")
    op.drop_table("field_cells")
    op.drop_table("disease_catalog")
    op.drop_table("fields")
