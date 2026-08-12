const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8765/settings',{waitUntil:'networkidle'});
  await page.evaluate(()=>window.openTeamDesign(1));
  await page.locator('#tdConfirmOk').click();
  const stage=page.locator('#tdStage');await stage.waitFor({state:'visible'});

  // Exact v67 failure path: synthetic/stale pointer has no browser capture slot.
  await stage.dispatchEvent('pointerdown',{pointerId:77,pointerType:'touch',clientX:140,clientY:260,buttons:1});
  await stage.dispatchEvent('pointerup',{pointerId:77,pointerType:'touch',clientX:140,clientY:260,buttons:0});

  const cdp=await page.context().newCDPSession(page),box=await stage.boundingBox();
  const x=box.x+box.width/2,y=box.y+box.height/2;
  async function finite(){
    const t=await page.locator('#tdSizer').evaluate(el=>getComputedStyle(el).transform||el.style.transform||'');
    if(/NaN|Infinity/.test(t))throw new Error('non-finite transform '+t);
    const nums=(t.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)||[]).map(Number);
    if(nums.some(n=>!Number.isFinite(n)))throw new Error('invalid transform '+t);
  }

  // Degenerate pinch: both fingers start on the same pixel, then separate.
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1},{x,y,id:2}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-30,y,id:1},{x:x+30,y,id:2}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await finite();

  // 50 real touch pinches through Chrome DevTools Protocol.
  for(let i=0;i<50;i++){
    await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:x-24,y,id:1},{x:x+24,y,id:2}]});
    await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-45,y,id:1},{x:x+45,y,id:2}]});
    await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await finite();
  }

  // Preview must still respond after the stress run.
  await stage.dispatchEvent('wheel',{deltaY:-100,ctrlKey:true,clientX:x,clientY:y});
  await finite();
  await stage.dispatchEvent('dblclick',{clientX:x,clientY:y});
  await finite();
  if(errors.length)throw new Error('page errors: '+errors.join(' | '));
  await browser.close();
  console.log('v68 touch stress passed');
})().catch(e=>{console.error(e);process.exit(1)});
