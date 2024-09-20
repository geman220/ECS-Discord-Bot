"""Make opponent_id non-nullable

Revision ID: 59847cf7c24a
Revises: 28273eda56f9
Create Date: 2024-08-22 22:35:39.212821

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '59847cf7c24a'
down_revision = '28273eda56f9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schedule', schema=None) as batch_op:
        batch_op.alter_column('opponent', existing_type=sa.Integer(), nullable=False)

def downgrade():
    with op.batch_alter_table('schedule', schema=None) as batch_op:
        batch_op.alter_column('opponent', existing_type=sa.Integer(), nullable=True)
