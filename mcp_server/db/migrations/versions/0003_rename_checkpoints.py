"""rename game table checkpoints -> field_checkpoints

Evita la collisione di nome con la tabella `checkpoints` creata dal checkpointer
LangGraph (memoria di thread dell'agente) nello stesso database.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("checkpoints", "field_checkpoints")


def downgrade() -> None:
    op.rename_table("field_checkpoints", "checkpoints")
