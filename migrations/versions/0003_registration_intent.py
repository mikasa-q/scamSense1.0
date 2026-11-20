import re

from alembic import op
import sqlalchemy as sa

revision = '0003_registration_intent'
down_revision = '0002_registration_entries'
branch_labels = None
depends_on = None

FIELD = r'(?P<field>所在城市|城市|项目经历)'
REFUSAL = r'(?:我)?(?:只|仅)?(?:拒绝(?:继续)?(?:提供|提交|填写)?|不(?:愿意?|想|再)?(?:提供|提交|填写|给))'
FIELD_REFUSALS = [re.compile(REFUSAL + FIELD), re.compile(FIELD + REFUSAL)]


def migrate_field_refusals(conn):
    # Earlier versions used one audited decline kind for both an item and the whole invitation.
    rows = conn.execute(sa.text('''
        SELECT t.id, t.sid, t.quote, u.body, u.id AS mid, r.id AS rid FROM traces t
        JOIN messages u ON u.id=t.message_id AND u.sid=t.sid AND u.role='chen' AND u.speaker='user'
        JOIN messages r ON r.receipt=u.receipt AND r.sid=u.sid AND r.role=u.role AND r.speaker='assistant'
        WHERE t.kind='decline' ORDER BY t.id
    ''')).mappings().all()
    for row in rows:
        quote, body = row['quote'], row['body']
        if quote not in body:
            continue
        for candidate in (quote, body):
            clause = candidate.strip(' \t\n，,。.!！；;')
            match = next((m for p in FIELD_REFUSALS if (m := p.fullmatch(clause))), None)
            if match:
                field = 'project_experience' if match['field'] == '项目经历' else 'city'
                conn.execute(sa.text('''
                    INSERT INTO registration_entries (sid,message_id,reply_id,field,position,status,quote)
                    VALUES (:sid,:mid,:rid,:field,:position,'refused',:quote)
                    ON CONFLICT(message_id,field,position) DO NOTHING
                '''), dict(sid=row['sid'], mid=row['mid'], rid=row['rid'], field=field,
                           position=body.index(candidate), quote=candidate))
                conn.execute(sa.text("UPDATE traces SET kind='decline_field' WHERE id=:id"), {'id':row['id']})
                break


def upgrade():
    op.add_column('registration_entries', sa.Column('position', sa.Integer()))
    op.execute('''UPDATE registration_entries SET position=(
        SELECT instr(m.body, registration_entries.quote)-1 FROM messages m WHERE m.id=registration_entries.message_id)''')
    with op.batch_alter_table('registration_entries', naming_convention={'uq':'uq_%(table_name)s_%(column_0_name)s'}) as b:
        b.drop_constraint('uq_registration_entries_message_id', type_='unique')
        b.alter_column('position', existing_type=sa.Integer(), nullable=False)
        b.create_unique_constraint('uq_registration_field_position', ['message_id','field','position'])
    migrate_field_refusals(op.get_bind())


def downgrade():
    if op.get_bind().scalar(sa.text('''SELECT 1 FROM registration_entries
            GROUP BY message_id,field HAVING count(*) > 1 LIMIT 1''')):
        raise RuntimeError('Cannot downgrade: the previous schema would discard same-turn registration history.')
    with op.batch_alter_table('registration_entries') as b:
        b.drop_constraint('uq_registration_field_position', type_='unique')
        b.drop_column('position')
        b.create_unique_constraint('uq_registration_entries_message_id', ['message_id','field'])
    op.execute("UPDATE traces SET kind='decline' WHERE kind='decline_field'")
