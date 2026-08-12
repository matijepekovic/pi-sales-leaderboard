const {chromium}=require('playwright');
const assert=(ok,msg)=>{if(!ok)throw new Error(msg)};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1920,height:1080}});
  const errors=[];
  const leaderboardUrls=[];
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',req=>{
    const u=req.url();
    if(u.includes('/api/leaderboard')) leaderboardUrls.push(u);
  });
  await page.clock.install();
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>typeof window.keyboardLeaderboardUrl==='function');

  const lastQuery=()=>{
    const raw=leaderboardUrls[leaderboardUrls.length-1];
    return raw?new URL(raw).searchParams:null;
  };
  const waitRequest=async before=>{
    for(let i=0;i<50;i++){
      if(leaderboardUrls.length>before) return;
      await sleep(30);
    }
    throw new Error('leaderboard request did not fire');
  };

  // Right enters Team vs Team without touching persisted remote settings.
  let before=leaderboardUrls.length;
  await page.keyboard.press('ArrowRight');
  await waitRequest(before);
  let q=lastQuery();
  assert(q.get('mode')==='team_vs_team','Right did not enter Team vs Team');
  let pair=q.getAll('team');
  assert(pair.length===2,'Team vs Team did not include exactly two temporary teams');

  // Up changes only the pairing while remaining in Team vs Team.
  const firstPair=pair.join('|');
  before=leaderboardUrls.length;
  await page.keyboard.press('ArrowUp');
  await waitRequest(before);
  q=lastQuery();pair=q.getAll('team');
  assert(q.get('mode')==='team_vs_team','Up left Team vs Team');
  assert(pair.length===2&&pair.join('|')!==firstPair,'Up did not cycle the Team vs Team combination');

  // Right skips pairing logic and advances to All Teams.
  before=leaderboardUrls.length;
  await page.keyboard.press('ArrowRight');
  await waitRequest(before);
  q=lastQuery();
  assert(q.get('mode')==='all_teams','Right did not advance from Team vs Team to All Teams');
  assert(q.getAll('team').length===0,'Pair override leaked into All Teams');

  // Three active teams follow All Teams, then the loop returns to Whole Office.
  const expected=['per_team::Alpha','per_team::Bravo','per_team::Charlie','whole_office'];
  for(const mode of expected){
    before=leaderboardUrls.length;
    await page.keyboard.press('ArrowRight');
    await waitRequest(before);
    assert(lastQuery().get('mode')===mode,`view loop expected ${mode}, got ${lastQuery().get('mode')}`);
  }

  // Left loops backwards from Whole Office to the last team.
  before=leaderboardUrls.length;
  await page.keyboard.press('ArrowLeft');
  await waitRequest(before);
  assert(lastQuery().get('mode')==='per_team::Charlie','Left did not loop to final team view');

  // Knob/mouse-wheel changes only the active mode's sort metric.
  const beforeSort=lastQuery().get('sort_metric');
  before=leaderboardUrls.length;
  await page.evaluate(()=>window.dispatchEvent(new WheelEvent('wheel',{deltaY:120,cancelable:true})));
  await waitRequest(before);
  q=lastQuery();
  assert(q.get('mode')==='per_team::Charlie','knob changed the view');
  assert(q.get('sort_metric')&&q.get('sort_metric')!==beforeSort,'knob did not select a temporary sort metric');

  // Five minutes without control input ends the override and returns URL
  // construction to the remote-app configuration (no query override at all).
  await page.clock.fastForward('05:01');
  await page.waitForTimeout(1);
  const resetUrl=await page.evaluate(()=>window.keyboardLeaderboardUrl('/api/leaderboard'));
  assert(resetUrl==='/api/leaderboard',`inactivity did not clear override: ${resetUrl}`);

  assert(!errors.length,'page errors: '+errors.join(' | '));
  console.log('v70 keyboard browser verification passed');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
