const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=path.resolve(process.argv[2]||'.');
const src=fs.readFileSync(path.join(root,'frontend/src/hilegaDecisionTable.tsx'),'utf8');
let code=src.slice(src.indexOf('const reportDirection='),src.indexOf('export function eventKind'));
code=code.replace("(r:HilegaAudit):'BULLISH'|'BEARISH'",'(r)').replaceAll('(c:any)','(c)').replaceAll('(d:string)','(d)').replaceAll(" as 'BULLISH'|'BEARISH'",'');
const resolve=vm.runInNewContext(code+'\nreportDirection',{list:x=>Array.isArray(x)?x:[]});
let count=0;
const fixtures=JSON.parse(fs.readFileSync(path.join(__dirname,'vm-fixtures.json'),'utf8'));
for(const fixture of fixtures){assert.equal(resolve(fixture),'BEARISH');count++;}
for(const [row,expected] of [
 [{strategy:{owner_after:'NONE',direction:'BULLISH',bullish_armed:false,bearish_armed:true}},'BEARISH'],
 [{strategy:{owner_after:'NONE',bullish_armed:true,bearish_armed:false}},'BULLISH'],
 [{strategy:{owner_after:'BULLISH',bullish_armed:false,bearish_armed:true}},'BULLISH'],
 [{strategy:{owner_after:'BEARISH',bullish_armed:true,bearish_armed:false}},'BEARISH'],
 [{strategy:{owner_after:'NONE'},conditions:{wma_gap_checks:[{direction:'BEARISH'}]}},'BEARISH'],
 [{strategy:{owner_after:'NONE',owner_before:'BEARISH',directional_action:'BEARISH_EXIT'}},'BEARISH']
]){assert.equal(resolve(row),expected);count++;}
console.log(count+' UI direction checks passed, including all9 VM decision rows');
