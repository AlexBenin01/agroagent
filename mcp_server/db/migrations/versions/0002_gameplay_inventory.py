"""game modes, time speed, inventory products

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Modalità di gioco e velocità del tempo per campo
    op.add_column(
        "fields",
        sa.Column("difficulty", sa.Text(), nullable=False, server_default="normal"),
    )
    op.add_column(
        "fields",
        sa.Column("time_speed", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "product_catalog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("targets", ARRAY(sa.Text()), nullable=False),
        sa.Column("delivery_min_h", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("delivery_max_h", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("efficacy", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "field_inventory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("product_catalog.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("field_id", "product_id", name="uq_inventory_field_product"),
    )
    op.create_index("ix_field_inventory_field_id", "field_inventory", ["field_id"])

    op.create_table(
        "product_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("product_catalog.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="in_transit"),
        sa.Column("ordered_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrives_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_orders_field_status", "product_orders", ["field_id", "status"])


def downgrade() -> None:
    op.drop_table("product_orders")
    op.drop_table("field_inventory")
    op.drop_table("product_catalog")
    op.drop_column("fields", "time_speed")
    op.drop_column("fields", "difficulty")
