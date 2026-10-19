"""Scope summary and summary tag unique_identifier and primary key by user_id

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-19 06:40:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(
        "f_summary", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_f_summary_unique_identifier", type_="unique")
        batch_op.create_unique_constraint(
            "uq_f_summary_user_uuid", ["user_id", "unique_identifier"]
        )
        batch_op.create_primary_key("pk_f_summary", ["id", "user_id"])

    with op.batch_alter_table(
        "f_summary_tag", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_f_summary_tag_unique_identifier", type_="unique")
        batch_op.create_unique_constraint(
            "uq_f_summary_tag_user_uuid", ["user_id", "unique_identifier"]
        )
        batch_op.create_primary_key("pk_f_summary_tag", ["id", "user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table(
        "f_summary_tag", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_f_summary_tag_user_uuid", type_="unique")
        batch_op.create_unique_constraint(
            "uq_f_summary_tag_unique_identifier", ["unique_identifier"]
        )
        batch_op.create_primary_key("pk_f_summary_tag", ["id"])

    with op.batch_alter_table(
        "f_summary", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("uq_f_summary_user_uuid", type_="unique")
        batch_op.create_unique_constraint(
            "uq_f_summary_unique_identifier", ["unique_identifier"]
        )
        batch_op.create_primary_key("pk_f_summary", ["id"])
