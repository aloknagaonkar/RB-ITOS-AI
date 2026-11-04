"""Historical report scope and arithmetic; never execution or reservation-release authority."""
from datetime import date
from decimal import Decimal, InvalidOperation


def need(ok, reason):
    if not ok: raise ValueError(reason)


def scope(session):
    day=date.fromisoformat(session)
    need(day.isoformat()==session, 'EXACT_ISO_SESSION_REQUIRED')
    year=day.year if day.month>=4 else day.year-1
    return dict(from_date=day.strftime('%d-%m-%Y'),to_date=day.strftime('%d-%m-%Y'),segment='FO',financial_year=f'{year%100:02d}{(year+1)%100:02d}')


def money(value):
    need(not isinstance(value,bool) and isinstance(value,(str,int,float)), 'FINITE_NONNEGATIVE_AMOUNT_REQUIRED')
    try: number=Decimal(str(value))
    except InvalidOperation: raise ValueError('FINITE_NONNEGATIVE_AMOUNT_REQUIRED') from None
    need(number.is_finite() and number>=0, 'FINITE_NONNEGATIVE_AMOUNT_REQUIRED')
    return number


def review(charges, rows, expected_count):
    need(type(expected_count) is int and expected_count>=0, 'EXACT_REPORT_COUNT_REQUIRED')
    need(isinstance(charges,dict) and charges.get('status')=='success', 'CHARGES_RESPONSE_REQUIRED')
    value=charges.get('data',{}).get('charges_breakdown')
    need(isinstance(value,dict), 'CHARGE_BREAKDOWN_REQUIRED')
    expected={'total','brokerage','taxes','charges'}
    need(set(value)==expected and isinstance(value['taxes'],dict) and isinstance(value['charges'],dict), 'CHARGE_SCHEMA_REQUIRES_REVIEW')
    need(set(value['taxes'])=={'gst','stt','stamp_duty'} and set(value['charges'])=={'transaction','clearing','ipft','others','sebi_turnover','demat_transaction'}, 'CHARGE_COMPONENT_SCHEMA_REQUIRES_REVIEW')
    fields={'brokerage':value['brokerage'],**{'taxes.'+k:v for k,v in value['taxes'].items()},**{'charges.'+k:v for k,v in value['charges'].items()}}
    missing=[k for k,v in fields.items() if v is None]
    amounts=[money(v) for v in fields.values() if v is not None]
    total=money(value['total'])
    arithmetic=not missing and sum(amounts,Decimal(0)).quantize(Decimal('.01'))==total.quantize(Decimal('.01'))
    need(isinstance(rows,list), 'REPORT_ROWS_REQUIRED')
    for row in rows:
        need(isinstance(row,dict) and row.get('trade_type') in {'FUT','OPT'}, 'FO_REPORT_ROW_REQUIRED')
        need(money(row.get('quantity'))>0, 'POSITIVE_REPORT_QUANTITY_REQUIRED')
        money(row.get('buy_amount'));money(row.get('sell_amount'))
    complete=len(rows)==expected_count
    return dict(status='AGGREGATE_POSTTRADE_REVIEW_ONLY',report_rows=len(rows),metadata_trade_count=expected_count,
        pagination_count_matches=complete,missing_or_null_components=missing,
        aggregate_component_arithmetic_matches=arithmetic,
        no_trade_report_rows=not rows,aggregate_charges_captured=True,
        broker_report_finality_verified=False,per_trade_fee_attribution_verified=False,
        strategy_ownership_verified=False,net_pnl_certified=False,
        actual_fees_reconciled=False,reservation_release_permitted=False,
        production_execution_enabled=False)
