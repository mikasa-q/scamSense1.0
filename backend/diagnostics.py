import json
import logging
from enum import Enum

import httpx


class Rule(Enum):
    generated_content = 'unapproved reply'
    sensitive_solicitation = 'sensitive solicitation'
    registration_quote_position = 'registration quote position does not match the message'
    registration_quote_ambiguous = 'ambiguous registration quote position'
    registration_choice_conflict = 'conflicting registration choices at the same position'
    registration_overlap = 'overlapping registration control and response'
    invented_new_receipt = 'chat cannot acknowledge a new receipt'
    invented_prior_receipt = 'reply invents a previous receipt'
    registration_availability = 'reply contradicts registration availability'
    registration_reopen = 'reply did not confirm that registration is open again'
    audit_unsafe = 'semantic audit rejected the reply'
    evidence_index = 'invalid evidence indexes'
    unverified_permission = 'unverified permission'
    disclosure_not_permitted = 'disclosure outside permitted facts'
    disclosure_quote_mismatch = 'disclosure quote is not in the reply'
    k05_excerpt = 'unexpected K05 excerpt'
    k04_missing = 'missing K04 assessment'
    k04_unsupported = 'unsupported K04 claim'
    k04_wrong_role = 'K04 claim does not belong to this role'
    k04_not_permitted = 'K04 fact was not permitted'
    k04_unverified = 'K04 permission was not supported by the audit'
    k05_scope = 'missing or out-of-scope K05 assessment'
    k05_parts = 'invalid or incomplete K05 part IDs'
    k05_not_permitted = 'K05 disclosure was not permitted'
    k05_conflicting_evidence = 'K05 denial and uncertainty about the same verification'
    registration_invite = 'unapproved registration'
    stale_attempt = 'stale attempt'
    chat_willingness_only = 'chat can only record willingness'
    legacy_scope_incomplete = 'legacy refusal evidence was not fully classified'
    legacy_scope_disagreement = 'legacy refusal scope not independently confirmed'
    registration_plan_mismatch = 'audited registration differs from the context used to generate the reply'


class RuleRejected(ValueError):
    def __init__(self, rule: Rule):
        super().__init__(rule.value)
        self.rule = rule


class ModelJSONError(ValueError):
    def __init__(self, error_type, status, reason):
        super().__init__(reason)
        self.error_type, self.status, self.reason = error_type, status, reason


def log_turn_failure(stage, exc):
    record = {'stage': stage, 'exception_type': type(exc).__name__}
    if isinstance(exc, ModelJSONError):
        record.update(stage=stage.removesuffix('_api') + '_json', exception_type=exc.error_type,
                      http_status=exc.status, reason_code=exc.reason)
    elif isinstance(exc, RuleRejected):
        record.update(stage='local_rule', reason_code=exc.rule.name)
    elif isinstance(exc, httpx.HTTPStatusError):
        record['http_status'] = exc.response.status_code
    # Exception messages and tracebacks may carry provider output, SQL parameters or authorization headers.
    logging.getLogger(__name__).warning('%s', json.dumps(record, separators=(',', ':')))
