from alembic import op
import sqlalchemy as sa

revision = '0002_registration_entries'
down_revision = '0001_training'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'registration_entries',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('sid', sa.String(32), sa.ForeignKey('trainings.id'), nullable=False),
        sa.Column('message_id', sa.Integer, sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('reply_id', sa.Integer, sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('field', sa.String(24), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('quote', sa.Text, nullable=False),
        sa.UniqueConstraint('message_id', 'field'),
    )
    op.create_index('ix_registration_entries_sid', 'registration_entries', ['sid'])


def downgrade():
    op.drop_table('registration_entries')
