from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '28ad22354429'
down_revision = '38397d3a45ed'
branch_labels = None
depends_on = None

def upgrade():
    # Drop the foreign key first
    op.drop_constraint('player_team_id_fkey', 'player', type_='foreignkey')
    
    # Drop the team_id column from the player table
    op.drop_column('player', 'team_id')

    # Drop the team table
    op.drop_table('team')

    # Add the new league_id column to player
    op.add_column('player', sa.Column('league_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'player', 'league', ['league_id'], ['id'])

def downgrade():
    # Recreate the team table if needed during a downgrade
    op.create_table(
        'team',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Add the team_id column back to the player table
    op.add_column('player', sa.Column('team_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'player', 'team', ['team_id'], ['id'])

    # Remove the league_id column
    op.drop_constraint(None, 'player', type_='foreignkey')
    op.drop_column('player', 'league_id')
