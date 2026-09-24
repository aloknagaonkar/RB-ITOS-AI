/* Standalone contract tests for the shared view's pure classification/economics.
   Run from the repository root after frontend dependencies are installed:
   node tests/test_hilega_decision_table_v1.cjs
*/
const assert=require('node:assert/strict')
const fs=require('node:fs')
const path=require('node:path')
const repo=path.resolve(__dirname,'..')
const ts=require(path.join(repo,'frontend/node_modules/typescript'))
const source=fs.readFileSync(path.join(repo,'frontend/src/hilegaDecisionTable.tsx'),'utf8')
const out=ts.transpileModule(source,{fileName:'hilegaDecisionTable.tsx',reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}})
assert.deepEqual((out.diagnostics??[]).filter(d=>d.category===ts.DiagnosticCategory.Error),[], 'TypeScript syntax')
const moduleBox={exports:{}}
const mockRequire=name=>name==='react'?{useMemo:()=>{},useState:()=>{},Fragment:Symbol('Fragment')}:name==='react/jsx-runtime'?{jsx:()=>{},jsxs:()=>{}}:name.endsWith('.css')?{}:require(name)
new Function('require','module','exports',out.outputText)(mockRequire,moduleBox,moduleBox.exports)
const {eventKind,pathText,computedPremiumPoints,decisionText,deriveDecisionRows,displayDecisionText,checkpointTransitions,shortRuleText,niftyPointsFromEntry,shortDateTime,reportedLegs,mergeLifecycleEvidence}=moduleBox.exports
const r=(over={})=>({checkpoint:'2026-09-23T09:35:00+05:30',transitions:[],strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE',events_emitted:[]},route_a:{},route_b:{},...over})
assert.equal(eventKind(r({transitions:[{event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'}]})),'ENTRY')
assert.equal(eventKind(r({transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}]})),'EXIT')
assert.equal(eventKind(r({strategy:{events_emitted:['PATH1_ARMED_RSI_CROSS_EMA3_UP']}})),'DETECTED')
assert.equal(eventKind(r({strategy:{events_emitted:['OPENING_REJECTED_0920']}})),'REJECTED')
assert.equal(eventKind(r({strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}})),'ACTIVE')
assert.equal(eventKind(r()),'NONE')
assert.equal(pathText(r({strategy:{state_before:'OPENING_CANDIDATE',state_after:'OPENING_HOLD',events_emitted:[]}})),'Opening path')
assert.equal(computedPremiumPoints({entry_open:100,exit_open:112.5,exit_timestamp:'2026-09-23T10:00:00+05:30'}),12.5)
assert.equal(computedPremiumPoints({entry_open:100,exit_open:null,exit_timestamp:null}),null)
assert.equal(computedPremiumPoints({entry_open:100,exit_open:90,exit_timestamp:'2026-09-23T10:00:00+05:30'}),-10)
assert.equal(decisionText(r({transitions:[{event_type:'ENTRY_OPENING_BULLISH_CONFIRMED'}]})),'BULLISH_ENTRY')
assert.equal(decisionText(r({strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}})),'BULLISH_CONTINUATION')
assert.equal(decisionText(r({transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}]})),'BULLISH_EXIT')
const session=deriveDecisionRows([
  r({checkpoint:'2026-09-23T09:35:00+05:30',transitions:[{event_type:'ENTRY_PATH1_ROUTE_B_STRUCTURAL'}],strategy:{state_before:'PATH1_ARMED',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_B'}}),
  r({checkpoint:'2026-09-23T09:40:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE'}}),
  r({checkpoint:'2026-09-23T09:45:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',details:{original_entry_time:'2026-09-23T09:35:00+05:30'}}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE'}}),
  r({checkpoint:'2026-09-23T09:50:00+05:30',strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE'}})
])
assert.equal(session[0].displayKind,'ENTRY')
assert.equal(session[1].displayKind,'ACTIVE')
assert.equal(session[1].origin,session[0].report.checkpoint)
assert.equal(session[1].originRoute,'ROUTE B')
assert.equal(session[2].displayKind,'EXIT')
assert.equal(session[2].origin,session[0].report.checkpoint)
assert.equal(session[3].displayKind,'NONE')
assert.equal(session[3].origin,null)
assert.equal(session[3].originRoute,null)

// Orphan raw exit/continuation records must not become valid bullish lifecycle labels.
const orphan=deriveDecisionRows([
  r({checkpoint:'2026-09-23T09:30:00+05:30'}),
  r({checkpoint:'2026-09-23T09:40:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'PATH1_IDLE',state_after:'PATH1_IDLE',selected_route:'ROUTE_A'}}),
  r({checkpoint:'2026-09-23T09:45:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE'}})
])
assert.equal(orphan[1].displayKind,'REVIEW')
assert.equal(orphan[1].lifecycleIssue,'EXIT_WITHOUT_BULLISH_ENTRY')
assert.equal(orphan[2].displayKind,'REVIEW')
assert.equal(orphan[2].lifecycleIssue,'CONTINUATION_WITHOUT_BULLISH_ENTRY')
assert.equal(displayDecisionText(orphan[1].displayKind),'REVIEW_REQUIRED')

// Once entered, ordinary completed candles remain continuation until the exit.
const carried=deriveDecisionRows([
  r({checkpoint:'2026-09-23T10:00:00+05:30',transitions:[{event_type:'ENTRY_OPENING_BULLISH_CONFIRMED'}],strategy:{state_before:'OPENING_HOLD',state_after:'BULLISH_ACTIVE',selected_route:'OPENING_PATH'}}),
  r({checkpoint:'2026-09-23T10:05:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['OPENING_REJECTED_0920']}}),
  r({checkpoint:'2026-09-23T10:10:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE'}})
])
assert.equal(carried[1].displayKind,'ACTIVE')
assert.equal(carried[1].originRoute,'OPENING PATH')
assert.equal(carried[2].displayKind,'EXIT')

// Explicit linkage can validate an exit when the loaded live window begins after entry.
const linkedExit=deriveDecisionRows([
  r({checkpoint:'2026-09-23T11:00:00+05:30',linked_signal_bar:'2026-09-23T10:30:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',selected_route:'ROUTE_B'}})
])
assert.equal(linkedExit[0].displayKind,'EXIT')
assert.equal(linkedExit[0].origin,'2026-09-23T10:30:00+05:30')

// Canonical entry reports can contain the eventual linked exit so the expanded
// audit can show the full CE lifecycle. The table classifier must use only the
// transition occurring at the row checkpoint.
const linkedFutureExit=r({
  checkpoint:'2026-09-23T09:40:00+05:30',
  transitions:[
    {event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',event_time:'2026-09-23T09:40:00+05:30',source:'ROUTE_A'},
    {event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T09:45:00+05:30',details:{original_entry_time:'2026-09-23T09:40:00+05:30'}}
  ],
  strategy:{state_before:'PATH1_IDLE',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_A',events_emitted:['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']}
})
assert.equal(checkpointTransitions(linkedFutureExit).length,1)
assert.equal(checkpointTransitions(linkedFutureExit)[0].event_type,'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21')
assert.equal(eventKind(linkedFutureExit),'ENTRY')
assert.equal(decisionText(linkedFutureExit),'BULLISH_ENTRY')
const realShape=deriveDecisionRows([
  linkedFutureExit,
  r({checkpoint:'2026-09-23T09:45:00+05:30',linked_signal_bar:'2026-09-23T09:40:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T09:45:00+05:30',details:{original_entry_time:'2026-09-23T09:40:00+05:30'}}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21']}}),
  r({checkpoint:'2026-09-23T09:55:00+05:30',transitions:[{event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',event_time:'2026-09-23T09:55:00+05:30'},{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T10:05:00+05:30',details:{original_entry_time:'2026-09-23T09:55:00+05:30'}}],strategy:{state_before:'PATH1_IDLE',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_A',events_emitted:['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']}}),
  r({checkpoint:'2026-09-23T10:00:00+05:30',strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}}),
  r({checkpoint:'2026-09-23T10:05:00+05:30',linked_signal_bar:'2026-09-23T09:55:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T10:05:00+05:30',details:{original_entry_time:'2026-09-23T09:55:00+05:30'}}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21']}})
])
assert.deepEqual(realShape.map(x=>x.displayKind),['ENTRY','EXIT','ENTRY','ACTIVE','EXIT'])
assert.equal(realShape[0].originRoute,'ROUTE A')
assert.equal(realShape[2].originRoute,'ROUTE A')
assert.equal(realShape[3].originRoute,'ROUTE A')


assert.equal(shortDateTime('2026-09-24T09:15:00+05:30'),'9/24 09:15')
assert.equal(niftyPointsFromEntry(23410.5,23390.0),20.5)
assert.equal(niftyPointsFromEntry(23380.0,23390.0),-10)
assert.equal(shortRuleText(r({checkpoint:'2026-09-23T09:40:00+05:30',transitions:[{event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',event_time:'2026-09-23T09:40:00+05:30'}],strategy:{state_before:'PATH1_IDLE',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_A',events_emitted:['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']}}),'ENTRY'),'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA')
assert.equal(shortRuleText(r({checkpoint:'2026-09-23T13:00:00+05:30',transitions:[{event_type:'ENTRY_PATH1_ROUTE_B_STRUCTURAL',event_time:'2026-09-23T13:00:00+05:30'}],strategy:{state_before:'PATH1_ARMED',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_B',events_emitted:['ENTRY_PATH1_ROUTE_B_STRUCTURAL']}}),'ENTRY'),'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑')
assert.equal(shortRuleText(r({checkpoint:'2026-09-23T13:05:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T13:05:00+05:30'}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21']}}),'EXIT'),'EXIT · RSI↓WMA21')
const pointTrail=deriveDecisionRows([
  r({checkpoint:'2026-09-23T09:40:00+05:30',bar:{close:23378},transitions:[{event_type:'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',event_time:'2026-09-23T09:40:00+05:30',price:23378}],strategy:{state_before:'PATH1_IDLE',state_after:'BULLISH_ACTIVE',selected_route:'ROUTE_A',events_emitted:['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']}}),
  r({checkpoint:'2026-09-23T09:45:00+05:30',bar:{close:23390.5},strategy:{state_before:'BULLISH_ACTIVE',state_after:'BULLISH_ACTIVE',events_emitted:[]}}),
  r({checkpoint:'2026-09-23T09:50:00+05:30',bar:{close:23370},linked_signal_bar:'2026-09-23T09:40:00+05:30',transitions:[{event_type:'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',event_time:'2026-09-23T09:50:00+05:30',details:{original_entry_time:'2026-09-23T09:40:00+05:30'}}],strategy:{state_before:'BULLISH_ACTIVE',state_after:'PATH1_IDLE',events_emitted:['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21']}})
])
assert.equal(pointTrail[0].niftyPoints,0)
assert.equal(pointTrail[1].niftyPoints,12.5)
assert.equal(pointTrail[2].niftyPoints,-8)


// CE lifecycle must be progressive by strategy row. A completed immutable trade
// attached to an entry audit must not leak its future exit/P&L into ENTRY or ACTIVE.
const ceAudit=r({
  checkpoint:'2026-09-23T10:15:00+05:30',
  option_lifecycle:{
    start:{legs:[
      {strike:23350,entry_timestamp:'2026-09-23T10:21:00+05:30',entry_open:120,exit_timestamp:null,exit_open:null}
    ]},
    updates:[
      {latest_completed_minute:'2026-09-23T10:25:00+05:30',legs:[
        {strike:23350,entry_timestamp:'2026-09-23T10:21:00+05:30',entry_open:120,latest_open:124,mfe_points:5,mae_points:-2}
      ]},
      {latest_completed_minute:'2026-09-23T10:45:00+05:30',legs:[
        {strike:23350,entry_timestamp:'2026-09-23T10:21:00+05:30',entry_open:120,latest_open:132,mfe_points:14,mae_points:-2}
      ]}
    ],
    exit:{legs:[
      {strike:23350,entry_timestamp:'2026-09-23T10:21:00+05:30',entry_open:120,exit_timestamp:'2026-09-23T11:20:00+05:30',exit_open:150,realized_points:30,mfe_points:35,mae_points:-2}
    ]}
  }
})
const ceEntry=reportedLegs(ceAudit,'2026-09-23T10:20:00+05:30','ENTRY')
assert.equal(ceEntry.length,1)
assert.equal(ceEntry[0].entry_open,120)
assert.equal(ceEntry[0].exit_open,null)
assert.equal(computedPremiumPoints(ceEntry[0]),null)

const ceActive=reportedLegs(ceAudit,'2026-09-23T10:30:00+05:30','ACTIVE')
assert.equal(ceActive.length,1)
assert.equal(ceActive[0].latest_open,124)
assert.equal(ceActive[0].exit_open,undefined)
assert.equal(computedPremiumPoints(ceActive[0]),null)

const ceExit=reportedLegs(ceAudit,'2026-09-23T11:20:00+05:30','EXIT')
assert.equal(ceExit.length,1)
assert.equal(ceExit[0].exit_open,150)
assert.equal(computedPremiumPoints(ceExit[0]),30)


// CE evidence may be recorded on a later checkpoint than the strategy entry.
// The UI must join reports belonging to the same bullish lifecycle before
// applying the no-lookahead display rules.
const entryOnly=r({
  checkpoint:'2026-09-23T10:15:00+05:30',
  option_candidate:null,
  option_lifecycle:null
})
const laterEvidence=r({
  checkpoint:'2026-09-23T10:20:00+05:30',
  option_candidate:{status:'PASS',expiry:'2026-09-29',atm:23400,contracts:[
    {strike:23350,instrument_key:'CE23350'}
  ]},
  option_lifecycle:{
    start:{legs:[
      {strike:23350,instrument_key:'CE23350',entry_timestamp:'2026-09-23T10:21:00+05:30',entry_open:120}
    ]},
    updates:[]
  }
})
const linked=mergeLifecycleEvidence(entryOnly,[laterEvidence])
assert.equal(linked.option_candidate.atm,23400)
assert.equal(linked.option_lifecycle.start.legs[0].entry_open,120)
const linkedEntryLegs=reportedLegs(linked,'2026-09-23T10:20:00+05:30','ENTRY')
assert.equal(linkedEntryLegs.length,1)
assert.equal(linkedEntryLegs[0].entry_open,120)

console.log('PASS: Hilega rule labels + date/time + Nifty delta + linked progressive CE no-lookahead + lifecycle/CE assertions')
