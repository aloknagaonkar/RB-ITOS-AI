const fs=require('fs'),vm=require('vm'),assert=require('assert');
const file=process.argv[2];const html=fs.readFileSync(file,'utf8');const js=html.split('<script>')[1].split('</script>')[0];
new vm.Script(js); // Parse the full delivered script.
const elements={side:{value:''},route:{value:''}};
const context=vm.createContext({document:{getElementById:id=>elements[id]},console});
vm.runInContext(js.split("$('dates').onclick")[0],context);
assert.equal(vm.runInContext("esc('<img>')",context),'&lt;img&gt;');
assert(vm.runInContext("filters({side:'CE',route_name:'Normal Route'})",context));
elements.side.value='PE';assert(!vm.runInContext("filters({side:'CE',route_name:'Normal Route'})",context));
assert(vm.runInContext("filters({side:'PE',route_name:'Normal Route'})",context));
elements.route.value='WMA_bypass';assert(!vm.runInContext("filters({side:'PE',route_name:'Normal Route'})",context));
assert.equal(vm.runInContext("required('rsi9_threshold','PE')",context),'< 45');
assert.equal(vm.runInContext("required('close_vs_ema30_high','CE')",context),'close > EMA30 High');
assert(html.includes('owner_before'));assert(html.includes('exit_evaluation'));assert(html.includes('route_blockers'));
assert(html.includes('BLOCKED:'));assert(html.includes('STALE:'));assert(html.includes('Download full HTML audit'));
console.log('PASS: complete script parses; filters, escaping, thresholds and audit fields');
