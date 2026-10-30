"""Project manual fill evidence without fabricating fill prices for cancellations."""
def apply_manual_exit_pnl(leg,entry,exit_row):
 if not exit_row or not exit_row.get('manual_exit_confirmed'):return leg
 buy=exit_row.get('confirmed_buy') or {}
 filled=buy.get('filled');pnl=exit_row.get('confirmed_pnl_rupees')
 leg['exit_time']=exit_row.get('event_timestamp') or exit_row.get('timestamp')
 leg['requested_quantity']=entry['quantity'];leg['exit_reason']='MANUAL_EXIT'
 leg['pnl_basis']='CONFIRMED_FILLS';leg['manual_exit_confirmed']=True
 if filled is None or not buy.get('terminal') or pnl is None:
  leg.update(points=None,pnl_rupees=None,status='MANUAL_EXIT_EVIDENCE_INCOMPLETE');return leg
 filled=int(filled)
 leg['quantity']=filled;leg['pnl_rupees']=float(pnl)
 if filled==0:
  leg.update(entry_price=None,exit_price=None,current_price=None,points=None,status='CANCELLED_UNFILLED',exit_order_id=None)
 else:
  en=buy.get('average_price');ex=exit_row.get('confirmed_exit_price')
  if en is None or ex is None or float(en)<=0 or float(ex)<=0:
   leg.update(entry_price=en,exit_price=ex,current_price=ex,points=None,pnl_rupees=None,status='MANUAL_EXIT_EVIDENCE_INCOMPLETE')
  else:
   leg.update(entry_price=float(en),exit_price=float(ex),current_price=float(ex),points=float(ex)-float(en),status='SELL_FILLED')
 return leg
