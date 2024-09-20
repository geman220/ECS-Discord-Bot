"""Add opponent_id to Schedule

Revision ID: 28273eda56f9
Revises: 22087fcb9b47
Create Date: 2024-08-22 22:31:55.482121

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '28273eda56f9'
down_revision = '22087fcb9b47'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schedule', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opponent_id', sa.Integer(), nullable=True))

def downgrade():
    with op.batch_alter_table('schedule', schema=None) as batch_op:
        batch_op.drop_column('opponent_id')