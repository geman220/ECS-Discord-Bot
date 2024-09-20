from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ad4171cf98cb'
down_revision = '0af04b9ebfef'
branch_labels = None
depends_on = None

def upgrade():
    # Set a default value for season_id before making it non-nullable
    op.add_column('league', sa.Column('season_id', sa.Integer(), nullable=True))
    op.execute('UPDATE league SET season_id = 1 WHERE season_id IS NULL')  # Replace 1 with the correct season_id if known
    op.alter_column('league', 'season_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(None, 'league', 'season', ['season_id'], ['id'])

def downgrade():
    op.drop_constraint(None, 'league', type_='foreignkey')
    op.drop_column('league', 'season_id')
