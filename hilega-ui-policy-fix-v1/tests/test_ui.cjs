const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.env.HILEGA_UI_CANDIDATE||path.join(__dirname,'../files'));
let ts;try{ts=require(path.join(root,'frontend/node_modules/typescript'))}catch{}
function load(file,names,prefix=false){
  let text=fs.readFileSync(path.join(root,'frontend/src',file),'utf8');
  if(prefix)text=text.slice(0,text.indexOf('function score('));
  text=text.replace(/^import .*$/gm,'').replace(/\bexport\s+/g,'');
  const js=ts?ts.transpileModule(text,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText:
    require('node:module').stripTypeScriptTypes(text);
  return new Function(js+';return {'+names.join(',')+'}')();
}
const {overlayDirectionalAuditReports:overlay}=load('hilegaDirectionalAuditOverlay.ts',['overlayDirectionalAuditReports']);
const {deriveDecisionRows:derive,eventKind,shortRuleText}=load('hilegaDecisionTable.tsx',['deriveDecisionRows','eventKind','shortRuleText'],true);
const at=hm=>'2026-11-23T'+hm+':00+05:30';
const base={strategy_id:'HILEGA_V2_ALIGNMENT_DUAL_EXIT',strategy_version:'new',owner_before:'BEARISH',owner_after:'BEARISH',bearish_state:'BEARISH_ACTIVE',action:'BEARISH_ACTIVE',accepted_events:'',audit_status:'PROCESSED',close:25457.90};
const entry={...base,bar_timestamp:at('12:03'),decision_timestamp:at('12:03'),owner_before:'NONE',action:'BEARISH_ENTRY',accepted_events:'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',audit_status:'RECOVERED',reconstructed:true,close:25505.20,event_details:[{event_type:'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',entry_time:at('12:03'),entry_price:25505.20,price:25505.20}]};
const active={...base,bar_timestamp:at('13:39'),decision_timestamp:at('13:39')};
const projected=overlay([],[entry,active]);
assert.equal(projected.find(x=>x.checkpoint===at('13:39')).strategy.state_after,'BEARISH_ACTIVE');
assert.equal(eventKind(projected.find(x=>x.checkpoint===at('13:39'))),'ACTIVE');
const timeline=derive(projected);
assert.deepEqual(timeline.map(r=>r.displayKind),['ENTRY','ACTIVE']);
assert.ok(Math.abs(timeline[1].niftyPoints-47.30)<1e-8);
assert.equal(timeline[1].origin,at('12:03'));assert.equal(timeline[1].entryReconstructed,true);
assert.equal(shortRuleText(timeline[1].report,'ACTIVE'),'CONTINUE · BEARISH_ACTIVE');
const orphan=derive(overlay([],[active]));assert.equal(orphan[0].displayKind,'REVIEW');
assert.equal(orphan[0].niftyPoints,null);
const mixed=derive([projected.find(x=>x.checkpoint===at('12:03')),{...projected.find(x=>x.checkpoint===at('13:39')),strategy:{...projected.find(x=>x.checkpoint===at('13:39')).strategy,strategy_version:'different'}}]);
assert.equal(mixed[1].displayKind,'REVIEW');assert.equal(mixed[1].niftyPoints,null);
for(const side of ['BULLISH','BEARISH']){
 const p=overlay([],[{...active,owner_before:side,owner_after:side,bearish_state:side==='BEARISH'?'BEARISH_ACTIVE':'BEARISH_PATH1_IDLE',bullish_state:side==='BULLISH'?'BULLISH_ACTIVE':'PATH1_IDLE',action:side+'_ACTIVE'}])[0];
 assert.equal(p.strategy.state_after,side+'_ACTIVE');assert.equal(eventKind(p),'ACTIVE');
}
console.log('UI mapping/lifecycle checks PASS: both directions, reconstructed entry, points, orphan protection, version boundary.');
if(process.env.HILEGA_UI_AUDIT_FIXTURE){
 const data=JSON.parse(fs.readFileSync(process.env.HILEGA_UI_AUDIT_FIXTURE,'utf8'));
 const source=data.decisions.map(record=>{
  const p=record.payload,f=p.price_ema_frame||{};
  return {...f,bar_timestamp:p.decision_timestamp,decision_timestamp:p.decision_timestamp,
   strategy_id:p.strategy_id,strategy_version:p.strategy_version,audit_status:record.status,
   reconstructed:p.reconstructed,owner_before:p.trade_owner_before,owner_after:p.trade_owner_after,
   bullish_state:p.bullish_state,bearish_state:p.bearish_state,accepted_events:p.accepted_events,
   event_details:p.event_details};
 });
 const out=derive(overlay([],source));
 assert.equal(out.filter(x=>x.displayKind==='ENTRY').length,4);
 assert.equal(out.filter(x=>x.displayKind==='EXIT').length,3);
 const last=out[out.length-1];assert.equal(last.displayKind,'ACTIVE');
 assert.equal(last.origin,at('12:03'));assert.ok(Math.abs(last.niftyPoints-12.2)<1e-8);
 assert.equal(last.entryReconstructed,true);
 assert.equal(out.filter(x=>x.displayKind==='REVIEW').length,0);
 console.log('Uploaded 71-candle fixture PASS: 4 entries, 3 exits, reversal split, final bearish continuation +12.20 from reconstructed 12:03 entry.');
}
