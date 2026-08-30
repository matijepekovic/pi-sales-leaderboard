/* v110 remote: dedicated QR Code section with drag-to-position + size control. */
(function(){
  const DEFAULT={size:68,x:100,y:0};
  const MIN_SIZE=36,MAX_SIZE=180;
  let value={...DEFAULT};
  let stage=null,qr=null,sizeInput=null,sizeValue=null,status=null;
  let dragging=false,pointerId=null;

  const $=id=>document.getElementById(id);
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||0));

  function styles(){
    if($('v110QrStyles')) return;
    const style=document.createElement('style');
    style.id='v110QrStyles';
    style.textContent=`
      #v110QrStage{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;
        border:1px solid #353535;background:#080808;
        background-image:linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px),
                         linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px);
        background-size:10% 10%;touch-action:none;user-select:none}
      #v110QrPreview{position:absolute;box-sizing:border-box;padding:3px;background:#fff;
        border-radius:4px;box-shadow:0 0 0 1px rgba(0,0,0,.4);cursor:grab;touch-action:none;line-height:0}
      #v110QrPreview.dragging{cursor:grabbing}
      #v110QrPreview img{display:block;width:100%;height:100%}
      #v110QrSize{padding:0;accent-color:var(--accent)}
      .v110-qr-nudges{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:10px}
      .v110-qr-nudges .btn{min-height:44px;padding:8px}
      .v110-qr-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
      .v110-qr-actions .btn{flex:1 1 150px;min-height:46px}
    `;
    document.head.appendChild(style);
  }

  function makeSection(){
    const stack=$('v98Sections');
    if(!stack||$('v110QrSection')) return !!$('v110QrSection');
    styles();

    const section=document.createElement('details');
    section.id='v110QrSection';
    section.className='v98-section';
    section.innerHTML=`
      <summary>QR Code</summary>
      <div class="v98-section-body">
        <div class="small" style="margin-bottom:10px">Drag the QR anywhere on the TV preview, then set its size.</div>
        <div id="v110QrStage" aria-label="QR position preview">
          <div id="v110QrPreview" role="img" aria-label="QR code position"><img src="/static/remote-qr-v109.svg?v=109" alt=""></div>
        </div>
        <div style="margin-top:14px">
          <div class="row" style="justify-content:space-between"><label for="v110QrSize" style="margin:0">Size</label><strong id="v110QrSizeValue">68 px</strong></div>
          <input id="v110QrSize" type="range" min="${MIN_SIZE}" max="${MAX_SIZE}" step="1" value="68">
        </div>
        <div class="v110-qr-nudges">
          <button class="btn" type="button" data-qr-nudge="left">←</button>
          <button class="btn" type="button" data-qr-nudge="up">↑</button>
          <button class="btn" type="button" data-qr-nudge="down">↓</button>
          <button class="btn" type="button" data-qr-nudge="right">→</button>
        </div>
        <div class="v110-qr-actions">
          <button id="v110QrReset" class="btn" type="button">Reset Top Right</button>
          <button id="v110QrSave" class="btn primary" type="button">Save QR</button>
        </div>
        <div id="v110QrStatus" class="small" style="margin-top:10px"></div>
      </div>`;

    const tvSection=Array.from(stack.querySelectorAll(':scope > .v98-section')).find(el=>
      String(el.querySelector(':scope > summary')?.textContent||'').trim()==='TV Remote'
    );
    if(tvSection) tvSection.insertAdjacentElement('afterend',section);
    else stack.appendChild(section);

    stage=$('v110QrStage');
    qr=$('v110QrPreview');
    sizeInput=$('v110QrSize');
    sizeValue=$('v110QrSizeValue');
    status=$('v110QrStatus');

    sizeInput.addEventListener('input',()=>{
      value.size=clamp(sizeInput.value,MIN_SIZE,MAX_SIZE);
      draw();
    });

    qr.addEventListener('pointerdown',e=>{
      dragging=true;pointerId=e.pointerId;qr.setPointerCapture(pointerId);
      qr.classList.add('dragging');
      moveFromPointer(e);
    });
    qr.addEventListener('pointermove',e=>{if(dragging&&e.pointerId===pointerId) moveFromPointer(e);});
    const stop=e=>{
      if(e.pointerId!==pointerId) return;
      dragging=false;pointerId=null;qr.classList.remove('dragging');
    };
    qr.addEventListener('pointerup',stop);
    qr.addEventListener('pointercancel',stop);

    section.querySelectorAll('[data-qr-nudge]').forEach(button=>button.addEventListener('click',()=>{
      const dir=button.dataset.qrNudge;
      if(dir==='left') value.x-=2;
      if(dir==='right') value.x+=2;
      if(dir==='up') value.y-=2;
      if(dir==='down') value.y+=2;
      value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);draw();
    }));

    $('v110QrReset').addEventListener('click',()=>{value={...DEFAULT};draw();status.textContent='Top-right default restored. Press Save QR.';});
    $('v110QrSave').addEventListener('click',save);
    window.addEventListener('resize',draw);
    load();
    return true;
  }

  function previewSize(){
    if(!stage) return 18;
    const scale=Math.max(.12,stage.clientWidth/1920);
    return Math.max(16,Math.min(stage.clientWidth*.25,value.size*scale));
  }

  function draw(){
    if(!stage||!qr) return;
    value.size=clamp(value.size,MIN_SIZE,MAX_SIZE);
    value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);
    const size=previewSize();
    const travelX=Math.max(0,stage.clientWidth-size);
    const travelY=Math.max(0,stage.clientHeight-size);
    qr.style.width=`${size}px`;
    qr.style.height=`${size}px`;
    qr.style.left=`${travelX*value.x/100}px`;
    qr.style.top=`${travelY*value.y/100}px`;
    if(sizeInput) sizeInput.value=String(Math.round(value.size));
    if(sizeValue) sizeValue.textContent=`${Math.round(value.size)} px`;
  }

  function moveFromPointer(e){
    const rect=stage.getBoundingClientRect();
    const size=qr.getBoundingClientRect().width;
    const travelX=Math.max(1,rect.width-size);
    const travelY=Math.max(1,rect.height-size);
    const left=clamp(e.clientX-rect.left-size/2,0,travelX);
    const top=clamp(e.clientY-rect.top-size/2,0,travelY);
    value.x=left/travelX*100;
    value.y=top/travelY*100;
    draw();
  }

  async function load(){
    try{
      const response=await fetch('/api/config',{cache:'no-store'});
      if(!response.ok) throw new Error('Could not load QR settings.');
      const data=await response.json();
      const settings=data.settings||{};
      value={
        size:clamp(settings.qr_overlay_size??DEFAULT.size,MIN_SIZE,MAX_SIZE),
        x:clamp(settings.qr_overlay_x??DEFAULT.x,0,100),
        y:clamp(settings.qr_overlay_y??DEFAULT.y,0,100)
      };
      draw();
    }catch(e){
      if(status) status.textContent=e.message||'Could not load QR settings.';
      draw();
    }
  }

  async function save(){
    const button=$('v110QrSave');
    button.disabled=true;status.textContent='Saving…';
    try{
      const response=await fetch('/api/qr-overlay',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({size:Math.round(value.size),x:value.x,y:value.y})
      });
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ok===false) throw new Error(data.error||'Could not save QR settings.');
      const saved=data.qr_overlay||{};
      value={
        size:clamp(saved.size??value.size,MIN_SIZE,MAX_SIZE),
        x:clamp(saved.x??value.x,0,100),
        y:clamp(saved.y??value.y,0,100)
      };
      draw();status.textContent='Saved. The TV QR will move automatically.';
    }catch(e){status.textContent=e.message||'Could not save QR settings.';}
    finally{button.disabled=false;}
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(makeSection()) return;
      if(++tries<100) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
