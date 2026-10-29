"""Offline review of proposed BUY-option loss budgets; no execution authority.

All inputs are caller assertions. This module authenticates no evidence, writes
no ledger/latch, and does not connect to the application or a broker.
"""
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

MODEL = 'HILEGA_DAILY_LOSS_REVIEW_V1'
POLICY = 'NO_PROFIT_OFFSET_PREVIEW_V1'
IST = ZoneInfo('Asia/Kolkata')

class ReviewBlocked(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise ReviewBlocked(reason)

def integer(value, name, *, positive=False):
    require(type(value) is int, name + '_INTEGER_PAISE_OR_COUNT_REQUIRED')
    require(value > 0 if positive else value >= 0, name + '_OUT_OF_RANGE')
    return value

def signed_integer(value, name):
    require(type(value) is int, name + '_INTEGER_PAISE_REQUIRED')
    return value

def aware(value, name):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError):
        raise ReviewBlocked(name + '_TIMESTAMP_INVALID') from None
    require(result.tzinfo is not None and result.utcoffset() is not None, name + '_TIMEZONE_REQUIRED')
    return result

def review(config, evidence, candidate, *, as_of, expected_account_scope):
    """Evaluate caller-supplied values without authorizing or persisting anything.

    Integer monetary values are paise. Supplied P&L must already be net of fees.
    Proposed conservative policy: realized and open losses are added; profits
    never offset either loss bucket. Candidate max cost means the approved
    premium-plus-fees maximum loss of a BUY CE/PE, not a stop-loss estimate.
    """
    require(all(isinstance(x, Mapping) for x in (config, evidence, candidate)), 'MAPPING_INPUTS_REQUIRED')
    require(isinstance(expected_account_scope, str) and bool(expected_account_scope.strip()), 'EXPECTED_ACCOUNT_SCOPE_REQUIRED')
    now = aware(as_of, 'AS_OF')
    session = now.astimezone(IST).date().isoformat()
    reasons = []
    def block(reason):
        if reason not in reasons: reasons.append(reason)

    if config.get('loss_accounting_policy') != POLICY:
        block('LOSS_ACCOUNTING_POLICY_UNSUPPORTED')
    if config.get('policy_approved') is not True:
        block('DAILY_LOSS_POLICY_UNAPPROVED')
    for name, value in (('CONFIG', config), ('EVIDENCE', evidence), ('CANDIDATE', candidate)):
        if value.get('account_scope') != expected_account_scope:
            block(name + '_ACCOUNT_SCOPE_MISMATCH')
        if value.get('session_date') != session:
            block(name + '_SESSION_MISMATCH')

    limit = config.get('daily_loss_limit_paise')
    if limit is None: block('DAILY_LOSS_LIMIT_MISSING')
    else: integer(limit, 'DAILY_LOSS_LIMIT', positive=True)
    max_cost = config.get('max_entry_cost_paise')
    if max_cost is None: block('MAX_ENTRY_COST_MISSING')
    else: integer(max_cost, 'MAX_ENTRY_COST', positive=True)
    max_age = config.get('max_pnl_age_seconds')
    if max_age is None: block('PNL_AGE_LIMIT_MISSING')
    else:
        integer(max_age, 'PNL_AGE_LIMIT', positive=True)
        require(max_age <= 30, 'PNL_AGE_LIMIT_EXCEEDS_REVIEW_SCOPE')

    if evidence.get('pnl_attribution_verified') is not True:
        block('PNL_ATTRIBUTION_UNVERIFIED')
    if evidence.get('fees_complete') is not True:
        block('FEES_INCOMPLETE_OR_UNKNOWN')
    if evidence.get('positions_reconciled') is not True:
        block('POSITIONS_UNRECONCILED')
    if evidence.get('requests_reconciled') is not True:
        block('REQUESTS_UNRECONCILED')
    latch = evidence.get('daily_stop_latched')
    if latch is True: block('DAILY_STOP_ALREADY_LATCHED')
    elif latch is not False: block('DAILY_STOP_LATCH_STATE_UNKNOWN')
    for field, reason in (('open_position_count', 'POSITION_ALREADY_OPEN'),
                          ('pending_request_count', 'REQUEST_PENDING')):
        count = evidence.get(field)
        if count is None: block(field.upper() + '_UNKNOWN')
        elif integer(count, field.upper()) != 0: block(reason)
    unresolved = evidence.get('unresolved_outcome')
    if unresolved is True: block('UNRESOLVED_EXECUTION_OUTCOME')
    elif unresolved is not False: block('EXECUTION_OUTCOME_STATE_UNKNOWN')

    observed_at = evidence.get('observed_at')
    age = None
    if observed_at is None:
        block('PNL_TIMESTAMP_MISSING')
    else:
        at = aware(observed_at, 'PNL_OBSERVED_AT')
        age = (now - at).total_seconds()
        if at.astimezone(IST).date().isoformat() != session:
            block('PNL_OBSERVATION_SESSION_MISMATCH')
        if age < 0: block('PNL_OBSERVATION_FUTURE')
        elif max_age is not None and age > max_age: block('PNL_OBSERVATION_STALE')

    realized = evidence.get('realized_net_pnl_paise')
    opened = evidence.get('open_net_pnl_paise')
    if realized is None: block('REALIZED_PNL_UNAVAILABLE')
    else: signed_integer(realized, 'REALIZED_PNL')
    if opened is None: block('OPEN_PNL_UNAVAILABLE')
    else: signed_integer(opened, 'OPEN_PNL')
    # Arithmetic may be reported for review even when attribution is unverified;
    # its availability never overrides an evidence/policy rejection.
    losses = None if realized is None or opened is None else max(0, -realized) + max(0, -opened)
    remaining = None if limit is None or losses is None else max(0, limit - losses)
    breach = None if limit is None or losses is None else losses >= limit
    if breach is True: block('DAILY_LOSS_LIMIT_REACHED')

    if candidate.get('transaction_type') != 'BUY' or candidate.get('instrument_type') not in ('CE', 'PE'):
        block('CANDIDATE_OUTSIDE_BUY_OPTION_SCOPE')
    if candidate.get('pricing_policy_approved') is not True:
        block('CANDIDATE_PRICING_UNAPPROVED')
    if candidate.get('cost_includes_fees') is not True:
        block('CANDIDATE_FEES_UNCONFIRMED')
    cost = candidate.get('max_loss_cost_paise')
    if cost is None: block('CANDIDATE_MAX_LOSS_COST_MISSING')
    else:
        integer(cost, 'CANDIDATE_MAX_LOSS_COST', positive=True)
        if max_cost is not None and cost > max_cost: block('MAX_ENTRY_COST_EXCEEDED')
        if remaining is not None and cost > remaining: block('REMAINING_LOSS_BUDGET_EXCEEDED')

    return dict(
        model=MODEL, scope='CALLER_SUPPLIED_OFFLINE_INPUTS_ONLY',
        status='BLOCKED' if reasons else 'REVIEWED_ONLY', reasons=sorted(reasons),
        calculation_policy=POLICY, session_date=session, assessed_at=now.isoformat(),
        daily_loss_limit_paise=limit, conservative_loss_used_paise=losses,
        remaining_loss_budget_paise=remaining, candidate_max_loss_cost_paise=cost,
        pnl_age_seconds=age, daily_stop_latch_required=breach,
        evidence_authenticated_by_this_module=False,
        durable_daily_stop_latch_persisted=False,
        broker_cash_reserved=False, application_ledger_updated=False,
        entry_permission=False, executable_request_created=False,
        production_execution_enabled=False, orders_sent=False,
        reservation_release_permission=False, production_ready=False,
    )
