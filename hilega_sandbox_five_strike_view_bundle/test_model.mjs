import assert from 'node:assert/strict'
import {matchSandbox,strikeRows} from './files/frontend/src/hilegaSandboxFiveStrikeModel.mjs'
const t={direction:'BEARISH',expiry:'2026-10-13',signal_bar:'2026-10-08T11:25:00+05:30',signal_boundary:'2026-10-08T11:30:00+05:30',status:'ACTIVE',legs:[{relation_to_atm:0,instrument_key:'PE',entry_open:100,latest_close:110,exit_open:null}]}
const sb={direction:'BEARISH',expiry:t.expiry,entry_signal_time:t.signal_boundary,instrument_key:'PE',quantity:65}
assert.equal(matchSandbox(t,[sb]),sb)
assert.equal(matchSandbox(t,[sb,{...sb}]),null)
assert.equal(matchSandbox(t,[{...sb,expiry:'2026-10-20'}]),null)
let rows=strikeRows(t,sb)
assert.equal(rows.length,5);assert.equal(rows.filter(r=>r.selected).length,1)
assert.equal(rows[2].estimated_rupees,650) // Long PE gains when premium rises.
assert.equal(rows[0].points,null)
rows=strikeRows({...t,status:'CLOSED'},sb)
assert.equal(rows[2].points,null) // Do not substitute latest quote for missing exact exit.
rows=strikeRows({...t,status:'CLOSED',legs:[{...t.legs[0],exit_open:80}]},sb)
assert.equal(rows[2].estimated_rupees,-1300)
assert.equal(strikeRows(t,null)[2].estimated_rupees,null)
console.log('PASS: five rows, exact signal/expiry identity, ambiguous match, missing exit, long PE P&L and quantity exclusion')
