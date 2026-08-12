const {chromium}=require('playwright');
const assert=(ok,msg)=>{if(!ok)throw new Error(msg)};
const HERO='/static/theme-packs/undisputed/hero.png';
const ROW='/static/theme-packs/undisputed/row.jpg';
const CHAMP='/static/theme-packs/undisputed/champ.jpg';
const MEDAL='/static/theme-packs/undisputed/medallion.png';
const CTL='/static/theme-packs/undisputed/ctl.png';
const CTR='/static/theme-packs/undisputed/ctr.png';
const CBL='/static/theme-packs/undisputed/cbl.png';
const CBR='/static/theme-packs/undisputed/cbr.png';
const metrics=['rank','rep_name','team','issued_leads','pitched_leads','sold_leads','gross_split','pending_split','net_split','close_rate','dpl'];
const statKeys=metrics.filter(k=>!['rank','rep_name','team'].includes(k));
const labels={rank:'Rank',rep_name:'Sales Rep',team:'Team',issued_leads:'Issued Leads',pitched_leads:'Pitched Leads',sold_leads:'Sold Leads',gross_split:'Gross Split',pending_split:'Pending Split',net_split:'Net Split',close_rate:'Close Rate',dpl:'DPL'};
const types={rank:'number',rep_name:'text',team:'text',issued_leads:'number',pitched_leads:'number',sold_leads:'number',gross_split:'currency',pending_split:'currency',net_split:'currency',close_rate:'percent',dpl:'currency'};
const colors={primary:'#c58a2a',primary_bright:'#e1ad48',primary_dark:'#6f4612',secondary:'#4a0907',background:'#070706',panel:'#11100d',text:'#e8d6ad',muted:'#a3946f',champion_text:'#fff1bd'};
function theme(id,name,{hero=100,stripe=0,corner=100,color='#c58a2a'}={}){
  const c={...colors,primary:color,primary_bright:color};
  return {scope:`team-${id}`,team_id:id,team_name:name,base:'undisputed',enabled:true,colors:c,hero_scale:hero,row_stripe:{color,strength:stripe},corner_settings:{corner_tl:{size:corner,crop_x:0,crop_y:0},corner_tr:{size:corner,crop_x:0,crop_y:0},corner_bl:{size:corner,crop_x:0,crop_y:0},corner_br:{size:corner,crop_x:0,crop_y:0}},assets:{background:'/static/theme-packs/undisputed/bg.jpg',hero:HERO,row:ROW,champion:CHAMP,medallion:MEDAL,corner_tl:CTL,corner_tr:CTR,corner_bl:CBL,corner_br:CBR,totals_mark:'/static/theme-packs/undisputed/totmark.png',logo_small:HERO}};
}
function rep(teamId,teamName,i,base){
  const issued=4+i, pitched=2+i/2, sold=Math.max(.5,1+i/4), gross=base+i*1000, pending=gross*.25, net=gross-pending;
  return {rep_key:`${teamId}-${i}`,rep_name:`${teamName} Rep ${i+1}`,team:teamName,team_id:teamId,assigned_team_id:teamId,issued_leads:issued,pitched_leads:pitched,sold_leads:sold,gross_split:gross,pending_split:pending,net_split:net,close_rate:sold/issued*100,dpl:net/issued};
}
function teamData(id,name,count,base){
  const members=Array.from({length:count},(_,i)=>rep(id,name,i,base-i*100));
  const sum=k=>members.reduce((a,r)=>a+Number(r[k]||0),0);
  return {summary:{team_id:id,team:name,logo_url:HERO,issued_leads:sum('issued_leads'),pitched_leads:sum('pitched_leads'),sold_leads:sum('sold_leads'),gross_split:sum('gross_split'),pending_split:sum('pending_split'),net_split:sum('net_split'),close_rate:sum('issued_leads')?sum('sold_leads')/sum('issued_leads')*100:0,dpl:sum('issued_leads')?sum('net_split')/sum('issued_leads'):0},members};
}
function payload(mode,{counts=[4,4,4],hero=100,stripe=0,corner=100}={}){
  const teams=[teamData(1,'Alpha',counts[0]||4,9000),teamData(2,'Bravo',counts[1]||4,19000),teamData(3,'Charlie',counts[2]||4,14000)];
  const themes=[theme(1,'Alpha',{hero,stripe,corner,color:'#c58a2a'}),theme(2,'Bravo',{hero,stripe,corner,color:'#4ee58c'}),theme(3,'Charlie',{hero,stripe,corner,color:'#8db7ff'})];
  const themeState={teams:{},by_name:{}};themes.forEach(t=>{themeState.teams[String(t.team_id)]=t;themeState.by_name[t.team_name.toLowerCase()]=t;});
  let rows=teams.flatMap(t=>t.members).sort((a,b)=>b.gross_split-a.gross_split);
  const selected=mode==='team_vs_team'?teams.slice(0,2):teams;
  const d={mode,title:'',subtitle:'',metrics,metric_labels:labels,metric_types:types,currency_symbol:'$',sort_metric:'gross_split',organization_version:1,theme_state:themeState,teams:selected,rows};
  if(mode==='per_team'){
    d.selected_team='Alpha';d.rows=teams[0].members;d.team_summary=teams[0].summary;d.teams=undefined;
  }else if(mode==='whole_office'){
    d.office_summary={team:'WHOLE OFFICE'};d.teams=undefined;
  }
  return d;
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1920,height:1080}});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  const draw=async data=>{await page.evaluate(d=>window.render(d),data);await page.waitForTimeout(180);};

  // Backend contract through the live API: 500 must store as 500.
  const api=await page.evaluate(async()=>{const s=await (await fetch('/api/themes')).json();const id=s.teams?.[0]?.team_id;if(!id)return {id:null};const put=await fetch(`/api/themes/team-${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({hero_scale:150,row_stripe:{color:'#123456',strength:35},corner_settings:{corner_tl:{size:500,crop_x:0,crop_y:0}}})});const pd=await put.json();const after=await (await fetch('/api/themes')).json();return {id,ok:put.ok,pd,theme:after.themes.teams[String(id)]};});
  assert(api.id,'CI setup did not create a theme team');assert(api.ok,'theme API rejected v69 controls');
  assert(Number(api.theme.corner_settings.corner_tl.size)===500,'API did not preserve corner size 500');
  assert(Number(api.theme.hero_scale)===150,'API did not preserve hero_scale 150');
  assert(Number(api.theme.row_stripe.strength)===35&&api.theme.row_stripe.color==='#123456','API did not preserve row stripe');

  // Team vs Team: full-width vertical stack, all metrics, winner first.
  await draw(payload('team_vs_team'));
  let cards=await page.locator('.v69-team-card').evaluateAll(es=>es.map(e=>({team:e.dataset.team,box:e.getBoundingClientRect().toJSON()})));
  assert(cards.length===2,'Team vs Team did not render 2 teams');
  assert(cards[0].team==='Bravo','Team vs Team winner is not first');
  assert(cards[1].box.y>cards[0].box.y+cards[0].box.height*.8,'Team vs Team is not vertically stacked');
  assert(Math.abs(cards[0].box.width-cards[1].box.width)<2&&cards[0].box.width>1850,'Team vs Team cards are not full width');
  let headCount=await page.locator('.v69-team-card').first().locator('.v69-head > div').count();
  let statCount=await page.locator('.v69-team-card').first().locator('.v69-row').first().locator('.v69-stat').count();
  let totalCount=await page.locator('.v69-team-card').first().locator('.v69-total').count();
  assert(headCount===statKeys.length+2,'Team vs Team header sliced enabled metrics');
  assert(statCount===statKeys.length,'Team vs Team rep row sliced enabled metrics');
  assert(totalCount===statKeys.length,'Team vs Team totals sliced enabled metrics');

  // All Teams: same full-width stack and aggregate order.
  await draw(payload('all_teams'));
  cards=await page.locator('.v69-team-card').evaluateAll(es=>es.map(e=>({team:e.dataset.team,box:e.getBoundingClientRect().toJSON()})));
  assert(cards.length===3,'All Teams did not render 3 teams');
  assert(cards.map(c=>c.team).join(',')==='Bravo,Charlie,Alpha','All Teams aggregate order is wrong: '+cards.map(c=>c.team).join(','));
  assert(cards.every(c=>c.box.width>1850),'All Teams cards are not full width');
  assert(cards[1].box.y>cards[0].box.y&&cards[2].box.y>cards[1].box.y,'All Teams cards are not vertically stacked');

  // Row stripe default is a no-op; configured stripe changes only even rows.
  await draw(payload('per_team',{stripe:0}));
  assert(!(await page.locator('#themedTeamBroadcast').evaluate(e=>e.classList.contains('v69-stripe-on'))),'Stripe default changed existing per-team appearance');
  await draw(payload('per_team',{stripe:35}));
  let stripe=await page.locator('.bt-row').evaluateAll(es=>es.slice(0,2).map(e=>getComputedStyle(e,'::before').backgroundColor));
  assert(stripe[0]!==stripe[1],'Per-team stripe did not tint alternating row');
  await draw(payload('whole_office',{stripe:35}));
  stripe=await page.locator('.v55-office-row-shade').evaluateAll(es=>es.slice(0,2).map(e=>getComputedStyle(e).backgroundColor));
  assert(stripe[0]!==stripe[1],'Whole Office stripe did not tint alternating row');
  await draw(payload('team_vs_team',{stripe:35}));
  stripe=await page.locator('.v69-team-card').first().locator('.v69-row').evaluateAll(es=>es.slice(0,2).map(e=>getComputedStyle(e,'::before').backgroundColor));
  assert(stripe[0]!==stripe[1],'Comparison stripe did not tint alternating row');

  // Hero 100 keeps the v67 baselines at 1920x1080; 150 is exactly 1.5x.
  await draw(payload('per_team',{hero:100}));
  const teamHero100=await page.locator('.bt-hero').evaluate(e=>e.getBoundingClientRect().height);
  assert(Math.abs(teamHero100-410.4)<3,`Per-team 100% hero baseline changed: ${teamHero100}`);
  await draw(payload('per_team',{hero:150}));
  const teamHero150=await page.locator('.bt-hero').evaluate(e=>e.getBoundingClientRect().height);
  assert(Math.abs(teamHero150/teamHero100-1.5)<.02,'Per-team hero 150 is not 1.5x');
  await draw(payload('whole_office',{hero:100}));
  const officeHero100=await page.locator('.v55-office-brand').evaluate(e=>e.getBoundingClientRect().height);
  assert(Math.abs(officeHero100-205.2)<3,`Whole Office 100% hero baseline changed: ${officeHero100}`);
  await draw(payload('whole_office',{hero:150}));
  const officeHero150=await page.locator('.v55-office-brand').evaluate(e=>e.getBoundingClientRect().height);
  assert(Math.abs(officeHero150/officeHero100-1.5)<.02,'Whole Office hero 150 is not 1.5x');

  // Shared corner base size across all views and same 5x scale at 500%.
  async function cornerWidth(mode,size){await draw(payload(mode,{corner:size}));const sel=mode==='per_team'?'.bt-corner.tl':mode==='whole_office'?'.v55-office-corner.tl':'.v69-corner.tl';return page.locator(sel).first().evaluate(e=>e.getBoundingClientRect().width);}
  const cTeam=await cornerWidth('per_team',100),cOffice=await cornerWidth('whole_office',100),cCompare=await cornerWidth('team_vs_team',100);
  assert(Math.max(cTeam,cOffice,cCompare)-Math.min(cTeam,cOffice,cCompare)<2,`Corner base sizes differ: ${cTeam},${cOffice},${cCompare}`);
  const cTeam5=await cornerWidth('per_team',500),cOffice5=await cornerWidth('whole_office',500),cCompare5=await cornerWidth('team_vs_team',500);
  assert(Math.abs(cTeam5/cTeam-5)<.08&&Math.abs(cOffice5/cOffice-5)<.08&&Math.abs(cCompare5/cCompare-5)<.08,'500% corner does not render 5x consistently');

  // Space-filling rows: 4 reps tall, 12 reps short, boards reach the bottom.
  await draw(payload('per_team',{counts:[4,4,4]}));
  const per4=await page.locator('.bt-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);
  let bottom=await page.locator('.bt-footer').evaluate(e=>e.getBoundingClientRect().bottom);assert(1080-bottom<22,'Per-team board does not reach bottom');
  await draw(payload('per_team',{counts:[12,4,4]}));
  const per12=await page.locator('.bt-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);assert(per4>per12*1.7,'Per-team rows do not adapt to rep count');
  bottom=await page.locator('.bt-footer').evaluate(e=>e.getBoundingClientRect().bottom);assert(1080-bottom<22,'Dense per-team board does not reach bottom');

  await draw(payload('whole_office',{counts:[4,0,0]}));
  const off4=await page.locator('.v55-office-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);
  bottom=await page.locator('.v55-office-footer').evaluate(e=>e.getBoundingClientRect().bottom);assert(1080-bottom<22,'Whole Office board does not reach bottom');
  await draw(payload('whole_office',{counts:[12,0,0]}));
  const off12=await page.locator('.v55-office-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);assert(off4>off12*1.7,'Whole Office rows do not adapt to rep count');
  bottom=await page.locator('.v55-office-footer').evaluate(e=>e.getBoundingClientRect().bottom);assert(1080-bottom<22,'Dense Whole Office board does not reach bottom');

  await draw(payload('team_vs_team',{counts:[4,4,4]}));
  const cmp4=await page.locator('.v69-team-card').first().locator('.v69-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);
  const cardBottom=await page.locator('.v69-team-card').last().evaluate(e=>e.getBoundingClientRect().bottom);assert(1080-cardBottom<22,'Comparison stack does not reach bottom');
  await draw(payload('team_vs_team',{counts:[12,12,4]}));
  const cmp12=await page.locator('.v69-team-card').first().locator('.v69-row').nth(1).evaluate(e=>e.getBoundingClientRect().height);assert(cmp4>cmp12*1.7,'Comparison rows do not adapt to rep count');

  assert(!errors.length,'page errors: '+errors.join(' | '));
  console.log('v69 real-app layout verification passed');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
