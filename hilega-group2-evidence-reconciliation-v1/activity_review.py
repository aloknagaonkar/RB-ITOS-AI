"""Anonymous structural account reconciliation, never strategy ownership or fee certification."""
from decimal import Decimal, InvalidOperation


def review(orders, trades, positions):
    issues = set()
    lookup = {}
    for row in orders:
        if not isinstance(row, dict) or not isinstance(row.get('order_id'), str) or not row['order_id']:
            issues.add('INVALID_ORDER_ID'); continue
        if row['order_id'] in lookup: issues.add('DUPLICATE_ORDER_ID')
        lookup[row['order_id']] = row
    fills, seen = {}, set()
    for row in trades:
        if not isinstance(row, dict): issues.add('INVALID_TRADE_ROW'); continue
        key = (row.get('exchange'), row.get('trade_id'))
        if not all(isinstance(x, str) and x for x in key): issues.add('INVALID_TRADE_ID')
        elif key in seen: issues.add('DUPLICATE_TRADE_ID')
        else: seen.add(key)
        oid = row.get('order_id')
        if not isinstance(oid, str) or oid not in lookup: issues.add('UNMATCHED_TRADE_ORDER')
        qty = row.get('quantity')
        if type(qty) is not int or qty <= 0: issues.add('INVALID_TRADE_QUANTITY'); continue
        try:
            price = Decimal(str(row.get('average_price')))
            if not price.is_finite() or price <= 0: raise InvalidOperation
        except (InvalidOperation, ValueError): issues.add('INVALID_TRADE_PRICE')
        if isinstance(oid, str): fills[oid] = fills.get(oid, 0) + qty
        if isinstance(oid, str) and oid in lookup:
            for field in ('instrument_token', 'transaction_type', 'product', 'exchange'):
                if not row.get(field) or row.get(field) != lookup[oid].get(field): issues.add('ORDER_TRADE_IDENTITY_MISMATCH')
    nonterminal = 0
    for oid, row in lookup.items():
        filled = row.get('filled_quantity')
        if type(filled) is not int or filled < 0: issues.add('INVALID_ORDER_FILLED_QUANTITY')
        elif filled != fills.get(oid, 0): issues.add('ORDER_FILL_QUANTITY_MISMATCH')
        if row.get('status') not in {'complete', 'cancelled', 'rejected'}: nonterminal += 1
    position_schema = all(isinstance(r, dict) and type(r.get('quantity')) is int for r in positions)
    if not position_schema: issues.add('POSITION_QUANTITY_SCHEMA_INCOMPLETE')
    nonzero = sum(r['quantity'] != 0 for r in positions) if position_schema else None
    return dict(status='STRUCTURAL_ACCOUNT_REVIEW_ONLY', order_rows=len(orders), trade_rows=len(trades),
        position_rows=len(positions), nonterminal_order_rows=nonterminal,
        nonzero_position_rows=nonzero, structural_issues=sorted(issues),
        order_fill_quantity_and_identity_consistent=not issues,
        snapshot_cross_endpoint_atomic=False, historical_cost_basis_verified=False,
        strategy_ownership_verified=False, fee_components_captured=False,
        actual_fees_reconciled=False, net_pnl_certified=False,
        local_reservation_release_permitted=False, broker_cash_addback_permitted=False,
        execution_permission=False)
