from alembic import op
import sqlalchemy as sa

revision = '23822e49bd32'
down_revision = '01785a473322'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add the new column as nullable
    op.add_column('matches', sa.Column('schedule_id', sa.Integer(), nullable=True))

    # 2. Backfill the schedule_id column based on home_team_id and away_team_id
    # Here, we're assuming that the combination of home_team_id and away_team_id should match team_id and opponent in the schedule.
    op.execute('''
        UPDATE matches AS m
        SET schedule_id = s.id
        FROM schedule AS s
        WHERE (m.home_team_id = s.team_id AND m.away_team_id = s.opponent)
           OR (m.home_team_id = s.opponent AND m.away_team_id = s.team_id)
    ''')

    # 3. Alter the column to make it non-nullable after populating the data
    op.alter_column('matches', 'schedule_id', existing_type=sa.Integer(), nullable=False)

    # Add the foreign key constraint if needed
    op.create_foreign_key(None, 'matches', 'schedule', ['schedule_id'], ['id'])

def downgrade():
    # Reverse the above changes
    op.drop_constraint(None, 'matches', type_='foreignkey')
    op.drop_column('matches', 'schedule_id')
