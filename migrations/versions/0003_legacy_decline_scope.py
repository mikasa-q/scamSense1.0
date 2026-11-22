import re

from alembic import op
import sqlalchemy as sa

revision = '0003_legacy_decline_scope'
down_revision = '0002_partial_registration'
branch_labels = None
depends_on = None

# Only complete, unqualified statements can be settled offline; the old label covered both scopes.
_WHOLE = re.compile(r'(?:我)?(?:决定|明确|要)?(?:停止|退出|终止|取消|不参加|暂不参与|拒绝参加)(?:整个|全部|这次|本次)?(?:预)?登记')
_FIELD = r'(?:所在城市|城市|项目经历)'
_REFUSE = r'(?:我)?(?:只|暂时|暂|先)?(?:拒绝|不愿意|不想|不)(?:再)?(?:提供|提交|填写|给)'
_ITEM = re.compile(rf'(?:{_REFUSE}{_FIELD}|{_FIELD}(?:这项)?{_REFUSE})')


def upgrade():
    conn = op.get_bind()
    # 0002 already wrote an explicit, audited whole-stop reason. Do not reinterpret those decisions.
    rows = conn.execute(sa.text('''SELECT t.id, t.quote, m.body FROM traces t JOIN messages m
        ON m.id=t.message_id AND m.sid=t.sid WHERE t.kind='decline' AND m.role='chen'
        AND m.speaker='user' AND t.why != :scoped'''), {'scoped': '你明确停止了整个登记，不再主动邀请。'})
    for row in rows.mappings().all():
        body = row['body'].strip().rstrip('。.!！').strip()
        kind = 'legacy_decline'
        if row['quote'].strip() and row['quote'] in row['body']:
            if _WHOLE.fullmatch(body):
                kind = 'decline'
            elif _ITEM.fullmatch(body):
                field = 'city' if '城市' in body else 'project'
                disposition = 'deferred' if re.search('暂|先', body) else 'refusal'
                kind = f'legacy_{field}_{disposition}'
        if kind != 'decline':
            conn.execute(sa.text('UPDATE traces SET kind=:kind WHERE id=:id'), {'kind': kind, 'id': row['id']})


def downgrade():
    op.execute("UPDATE traces SET kind='decline' WHERE kind IN ('legacy_decline', 'legacy_item_decline', 'legacy_city_refusal', 'legacy_project_refusal', 'legacy_city_deferred', 'legacy_project_deferred')")
