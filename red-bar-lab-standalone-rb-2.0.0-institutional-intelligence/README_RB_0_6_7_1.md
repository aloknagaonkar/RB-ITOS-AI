# RB-0.6.7.1 UI Compatibility + Explicit Trade Outcome

This is a data-preserving UI patch on top of RB-0.6.7.

Fixes:
- Streamlit `use_container_width=True` warnings by using `width="stretch"`.
- PyArrow errors caused by mixed string / pandas.Timestamp values.
- All new live/timeline/trade rows are normalized before `st.dataframe`.

Trade model table now explicitly shows:
- State: OPEN / CLOSED
- Trade Result: WIN / LOSS / BREAKEVEN
- Successful/Failed: SUCCESS / FAILED / BREAKEVEN
- Points Gained: signed underlying points
- Exit Reason
- Exit Model
- Entry / Exit prices and timestamps
- Risk, R multiple, MFE, MAE and continuation fields

Live ACTIVE table explicitly shows:
- Entry Price
- Current Price
- Live Points Gained
- Live Result: PROFIT / LOSS / BREAKEVEN
- Open / Closed Trade Models
- Signal Lifecycle

No historical files, live cache, artifacts, or SQLite data are deleted.
