from alembic import op
import sqlalchemy as sa

revision = '0001_training'
down_revision = None
branch_labels = None
depends_on = None

def ident():
    return sa.Column('id', sa.Integer, primary_key=True)

def session_key(primary=False):
    return sa.Column('sid', sa.String(32), sa.ForeignKey('trainings.id'), nullable=False, primary_key=primary)

def field(name, type_):
    return sa.Column(name, type_, nullable=False)

def upgrade():
    op.create_table('trainings', sa.Column('id', sa.String(32), primary_key=True), field('token_hash', sa.String(64)), field('created', sa.String), field('stage', sa.Integer), field('closed', sa.Boolean), sa.Column('locked_by', sa.String(32)), field('lock_until', sa.Integer))
    op.create_table('receipts', sa.Column('id', sa.String(32), primary_key=True), session_key(), field('request_id', sa.String(36)), field('fingerprint', sa.String(64)), field('attempt', sa.String(32)), field('status', sa.String(12)), sa.UniqueConstraint('sid', 'request_id'))
    op.create_table('messages', ident(), session_key(), sa.Column('receipt', sa.String(32), sa.ForeignKey('receipts.id'), nullable=False), field('role', sa.String(12)), field('speaker', sa.String(12)), field('body', sa.Text), field('created', sa.String))
    op.create_table('events', ident(), session_key(), field('kind', sa.String(32)), field('stage', sa.Integer), sa.Column('message_id', sa.Integer, sa.ForeignKey('messages.id')))
    op.create_table('traces', ident(), session_key(), sa.Column('message_id', sa.Integer, sa.ForeignKey('messages.id'), nullable=False), field('kind', sa.String(32)), field('focus', sa.String(12)), field('quote', sa.Text), field('why', sa.Text))
    op.create_table('endings', session_key(True), field('kind', sa.String(12)), sa.Column('choice', sa.String(24)), field('reason', sa.Text), field('cited', sa.JSON), field('created', sa.String))
    op.create_table('reviews', session_key(True), field('rubric', sa.String(40)), field('payload', sa.JSON))
    for table in ['receipts', 'messages', 'events', 'traces']:
        op.create_index('ix_' + table + '_sid', table, ['sid'])

def downgrade():
    for table in ['reviews', 'endings', 'traces', 'events', 'messages', 'receipts', 'trainings']:
        op.drop_table(table)
