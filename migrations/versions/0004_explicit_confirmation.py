from alembic import op
import sqlalchemy as sa

revision = '0004_explicit_confirmation'
down_revision = '0003_legacy_decline_scope'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'registration_confirmations',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('sid', sa.String(32), sa.ForeignKey('trainings.id'), nullable=False),
        sa.Column('field', sa.String(24), nullable=False),
        sa.Column('value', sa.String(24), nullable=False),
        sa.Column('created', sa.String, nullable=False),
        sa.Column('after_message_id', sa.Integer, sa.ForeignKey('messages.id'), nullable=False),
        sa.UniqueConstraint('sid', 'field', name='uq_confirmation_field'),
    )


def downgrade():
    op.drop_table('registration_confirmations')
