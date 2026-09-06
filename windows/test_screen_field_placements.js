/* Instance-only Field periods: controls, sync and preview invalidation. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const host={innerHTML:"",querySelector:()=>null,querySelectorAll:()=>[]},timers=[];
const context=vm.createContext({window:{StatsSettings:{esc:value=>String(value??""),on:()=>{}},StatsWidgetRenderer:{},StatsScreenAssets:{}},
  document:{getElementById:()=>host},requestAnimationFrame:()=>{},setTimeout:callback=>{timers.push(callback);return timers.length;},clearTimeout:()=>{},console});
const source=fs.readFileSync(path.join(__dirname,"../app/static/settings/screens.js"),"utf8");
vm.runInContext(source.replace(/\}\)\(\);\s*$/,'window.screenTest={S,dateControl,variantControls,sync,schedule,version:()=>previewVersion};})();'),context);
const B=context.window.screenTest;
B.S.reports=[{id:"source",fields:[{id:"name",label:"Name",type:"text",kind:"report"},{id:"net",label:"Net",type:"number",kind:"report"},{id:"rate",label:"Rate",type:"percent",kind:"report"}]}];
const widget={id:"widget",kind:"line",field_ids:["name","net","rate"],chart:{measure_field_ids:["net","rate"]}};
B.S.widgets=[widget];
const variant={id:"placement-net",field_id:"net",label:"Net last year",timeframe:{preset:"previous_year"}};
const item={id:"instance",widget_id:"widget",ranking:[],group_ids:[],field_variants:[variant],identity_field_id:"name",timeframe:null};
B.S.draft={name:"Screen",widgets:[item],timeframe:null,canvas:{width:1920,height:1080}};B.S.selected="instance";
const originalDefinition=JSON.stringify(widget);
assert.match(B.variantControls(item,widget),/Name here/);
assert.match(B.variantControls(item,widget),/Match rows using/);
assert.match(B.variantControls(item,widget),/Timeline/);
assert.doesNotMatch(B.variantControls(item,{...widget,kind:"table"}),/>Timeline</);
assert.match(B.dateControl({preset:"rolling",unit:"week",count:4,offset:4},"variant:placement-net"),/Shift back by/);
assert.doesNotMatch(B.dateControl(variant.timeframe,"variant:placement-net"),/Use Data timeframe/);
variant.interval={unit:"month",count:1};variant.aggregation="average";
assert.doesNotMatch(B.variantControls(item,widget),/Match rows using/,"Timeline summaries need no row identity prompt");
variant.aggregation="none";
assert.match(B.variantControls(item,widget),/Match rows using/,"Per-record timelines do need identity");

const input=value=>({value});
const block={dataset:{fieldVariant:"placement-net"},querySelector:selector=>({
  "[data-variant-field]":input("net"),"[data-variant-label]":input("Quarter by month"),"[data-variant-display]":input("timeline"),
  "[data-variant-interval-unit]":input("month"),"[data-variant-interval-count]":input("2"),"[data-variant-aggregation]":input("average")
}[selector]||null)};
const period={dataset:{timeframeOwner:"variant:placement-net"},querySelector:selector=>({
  "[data-timeframe-preset]":input("rolling"),"[data-timeframe-unit]":input("month"),"[data-timeframe-count]":input("6"),"[data-timeframe-offset]":input("6")
}[selector]||null)};
host.querySelectorAll=selector=>selector==="[data-field-variant]"?[block]:selector==="[data-timeframe-owner]"?[period]:[];
host.querySelector=selector=>selector==="[data-instance-identity]"?input("name"):null;
B.sync();
assert.equal(variant.label,"Quarter by month");
assert.deepEqual(JSON.parse(JSON.stringify(variant.timeframe)),{preset:"rolling",unit:"month",count:6,offset:6});
assert.deepEqual(JSON.parse(JSON.stringify(variant.interval)),{unit:"month",count:2});
assert.equal(variant.aggregation,"average");
assert.equal(B.S.draft.timeframe,null,"A Field window cannot mutate Screen defaults");
assert.equal(item.timeframe,null,"A Field window cannot mutate Widget defaults");
assert.equal(JSON.stringify(widget),originalDefinition,"Local edits cannot rewrite reusable Widget definitions");
B.S.payload={};const before=B.version();B.schedule();assert.ok(B.version()>before,"A changed draft invalidates already-running previews immediately");
console.log("Screen Field-placement controls passed");
