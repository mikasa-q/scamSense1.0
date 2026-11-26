from alembic import op
import sqlalchemy as sa

revision = '0005_classroom_seats'
down_revision = '0004_explicit_confirmation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('classroom_seats',
                    sa.Column('sid', sa.String(32), sa.ForeignKey('trainings.id'), primary_key=True),
                    sa.Column('attempts', sa.Integer, nullable=False))


def downgrade():
    op.drop_table('classroom_seats')
