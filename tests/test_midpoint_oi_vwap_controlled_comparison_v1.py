from datetime import datetime
from market_lab.midpoint_oi_vwap_controlled_comparison_v1 import confluence_direction,floor_completed_5m

def test_floor_does_not_look_forward(): assert floor_completed_5m(datetime(2026,9,15,9,28))==datetime(2026,9,15,9,25)
def test_exact_checkpoint_unchanged(): assert floor_completed_5m(datetime(2026,9,15,9,30))==datetime(2026,9,15,9,30)
def test_bullish_confluence(): assert confluence_direction({"ce_state":"LONG_BUILDUP","pe_state":"SHORT_BUILDUP","futures_close":101,"futures_vwap":100})=="BULLISH"
def test_bearish_confluence(): assert confluence_direction({"ce_state":"SHORT_BUILDUP","pe_state":"LONG_BUILDUP","futures_close":99,"futures_vwap":100})=="BEARISH"
def test_misaligned_is_neutral(): assert confluence_direction({"ce_state":"LONG_BUILDUP","pe_state":"SHORT_BUILDUP","futures_close":99,"futures_vwap":100})=="NEUTRAL"
