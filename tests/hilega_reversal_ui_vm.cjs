// Run on VM from repository root; no API calls, orders or strategy execution.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const ts=require(path.resolve('frontend/node_modules/typescript'));
const source=fs.readFileSync('frontend/src/hilegaDecisionTable.tsx','utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText;
const moduleStub={exports:{}};
vm.runInNewContext(compiled,{exports:moduleStub.exports,module:moduleStub,require:()=>({}),console,Date,Intl,Set,Map,Number,JSON},{filename:'hilegaDecisionTable.cjs'});
const {deriveDecisionRows,expandRecordedReversals}=moduleStub.exports;
const at=t=>`2026-10-23T${t}:00+05:30`;
const report=(t,strategy,transitions,close)=>({checkpoint:at(t),bar:{close},strategy,transitions});
const entry=report('09:55',{owner_after:'BEARISH',state_after:'BEARISH_ACTIVE',events_emitted:['ENTRY_BEARISH_ROUTE_B_STRUCTURAL']},[{event_type:'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',event_time:at('09:55'),price:22637.95}],22637.95);
const reversal=report('13:05',{owner_before:'BEARISH',owner_after:'BULLISH',state_after:'BULLISH_ACTIVE',events_emitted:['STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21','ENTRY_PATH1_ROUTE_B_STRUCTURAL']},[
 {event_type:'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',event_time:at('13:05'),entry_time:at('09:55'),entry_price:22637.95,price:22429.35,exit_reason:'FULLY_CONFIRMED_OPPOSITE_BULLISH'},
 {event_type:'ENTRY_PATH1_ROUTE_B_STRUCTURAL',event_time:at('13:05'),entry_time:at('13:05'),entry_price:22429.35,price:22429.35}],22429.35);
const continued=report('13:10',{owner_after:'BULLISH',state_after:'BULLISH_ACTIVE'},[],22400.45);
const untouched=JSON.stringify(reversal);
const rows=deriveDecisionRows([continued,reversal,entry]);
assert.deepStrictEqual(Array.from(rows,r=>r.displayKind),['ENTRY','EXIT','ENTRY','ACTIVE']);
assert(Math.abs(rows[1].niftyPoints-208.60)<1e-7);
assert.strictEqual(rows[2].entryNifty,22429.35);
assert.strictEqual(rows[2].origin,at('13:05'));
assert(Math.abs(rows[2].niftyPoints)<1e-7);
assert(Math.abs(rows[3].niftyPoints-(-28.90))<1e-7);
assert.strictEqual(rows[3].entryNifty,22429.35);
assert.strictEqual(JSON.stringify(reversal),untouched);
assert.notStrictEqual(rows[1].report.audit_row_id,rows[2].report.audit_row_id);
const window=deriveDecisionRows([reversal,continued]);
assert.strictEqual(window[0].displayKind,'EXIT');
assert(Math.abs(window[0].niftyPoints-208.60)<1e-7);
const future={...entry,transitions:[...entry.transitions,reversal.transitions[0]]};
assert.strictEqual(expandRecordedReversals([future]).length,1);
assert.strictEqual(deriveDecisionRows([entry,{...reversal,transitions:[reversal.transitions[1]],strategy:{...reversal.strategy,events_emitted:['ENTRY_PATH1_ROUTE_B_STRUCTURAL']}}])[1].lifecycleIssue,'ENTRY_WHILE_DIRECTIONAL_ACTIVE');
console.log('PASS: recorded reversal exit-before-entry; realised208.60; bullish reset; next mark-28.90; distinct rows; future evidence ignored; unpaired entry still reviewed; input immutable');
