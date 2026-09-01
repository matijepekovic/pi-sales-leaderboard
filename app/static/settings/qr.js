/* QR overlay controls for the TV. */
(function(){
  const $=id=>document.getElementById(id);
  const DEFAULT={size:68,x:100,y:0};
  const MIN_SIZE=36,MAX_SIZE=180;
  let value={...DEFAULT},dragging=false,pointerId=null;

  const clamp=(raw,min,max)=>Math.min(max,Math.max(min,Number(raw)||0));

  function styles(){
    if($("qrControlStyles"))return;
    const style=document.createElement("style");style.id="qrControlStyles";
    style.textContent=`
      #qrStage{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;border:1px solid #353d46;border-radius:6px;background:#080b0e;touch-action:none;user-select:none}
      #qrPreview{position:absolute;box-sizing:border-box;padding:3px;background:#fff;border-radius:4px;box-shadow:0 0 0 1px rgba(0,0,0,.45);cursor:grab;touch-action:none;line-height:0}
      #qrPreview.dragging{cursor:grabbing}#qrPreview img{display:block;width:100%;height:100%}
      #qrSize{padding:0;accent-color:var(--accent)}.qr-nudges{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:10px}.qr-nudges .btn{min-height:42px;padding:7px}
    `;document.head.appendChild(style);
  }

  function mount(){
    const host=$("settingsQrControls");if(!host||$("qrControlCard"))return false;styles();
    host.innerHTML=`<div class="card" id="qrControlCard">
      <h2>QR Code</h2>
      <p class="small">Drag the QR on the TV preview, then set its size.</p>
      <div id="qrStage" aria-label="QR position preview"><div id="qrPreview" role="img" aria-label="QR code position"><img src="/static/remote-qr-v109.svg" alt=""></div></div>
      <div style="margin-top:14px"><div class="row" style="justify-content:space-between"><label for="qrSize" style="margin:0">Size</label><strong id="qrSizeValue">68 px</strong></div><input id="qrSize" type="range" min="${MIN_SIZE}" max="${MAX_SIZE}" step="1" value="68"></div>
      <div class="qr-nudges"><button class="btn" type="button" data-qr-nudge="left">←</button><button class="btn" type="button" data-qr-nudge="up">↑</button><button class="btn" type="button" data-qr-nudge="down">↓</button><button class="btn" type="button" data-qr-nudge="right">→</button></div>
      <div class="row" style="margin-top:12px"><button id="qrReset" class="btn" type="button">Reset Top Right</button><button id="qrSave" class="btn primary" type="button">Save QR</button></div>
      <div id="qrStatus" class="small settings-status"></div>
    </div>`;

    $("qrSize").addEventListener("input",()=>{value.size=clamp($("qrSize").value,MIN_SIZE,MAX_SIZE);draw();});
    $("qrPreview").addEventListener("pointerdown",event=>{dragging=true;pointerId=event.pointerId;$("qrPreview").setPointerCapture(pointerId);$("qrPreview").classList.add("dragging");move(event);});
    $("qrPreview").addEventListener("pointermove",event=>{if(dragging&&event.pointerId===pointerId)move(event);});
    const stop=event=>{if(event.pointerId!==pointerId)return;dragging=false;pointerId=null;$("qrPreview").classList.remove("dragging");};
    $("qrPreview").addEventListener("pointerup",stop);$("qrPreview").addEventListener("pointercancel",stop);
    host.querySelectorAll("[data-qr-nudge]").forEach(button=>button.addEventListener("click",()=>nudge(button.dataset.qrNudge)));
    $("qrReset").addEventListener("click",()=>{value={...DEFAULT};draw();$("qrStatus").textContent="Top-right default restored. Press Save QR.";});
    $("qrSave").addEventListener("click",save);window.addEventListener("resize",draw);load();return true;
  }

  function previewSize(){const stage=$("qrStage");if(!stage)return 18;const scale=Math.max(.12,stage.clientWidth/1920);return Math.max(16,Math.min(stage.clientWidth*.25,value.size*scale));}
  function draw(){
    const stage=$("qrStage"),qr=$("qrPreview");if(!stage||!qr)return;
    value.size=clamp(value.size,MIN_SIZE,MAX_SIZE);value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);
    const size=previewSize(),travelX=Math.max(0,stage.clientWidth-size),travelY=Math.max(0,stage.clientHeight-size);
    qr.style.width=`${size}px`;qr.style.height=`${size}px`;qr.style.left=`${travelX*value.x/100}px`;qr.style.top=`${travelY*value.y/100}px`;
    $("qrSize").value=String(Math.round(value.size));$("qrSizeValue").textContent=`${Math.round(value.size)} px`;
  }

  function move(event){
    const stage=$("qrStage"),qr=$("qrPreview"),rect=stage.getBoundingClientRect(),size=qr.getBoundingClientRect().width;
    const travelX=Math.max(1,rect.width-size),travelY=Math.max(1,rect.height-size);
    value.x=clamp(event.clientX-rect.left-size/2,0,travelX)/travelX*100;
    value.y=clamp(event.clientY-rect.top-size/2,0,travelY)/travelY*100;draw();
  }

  function nudge(direction){
    if(direction==="left")value.x-=2;if(direction==="right")value.x+=2;if(direction==="up")value.y-=2;if(direction==="down")value.y+=2;
    value.x=clamp(value.x,0,100);value.y=clamp(value.y,0,100);draw();
  }

  async function load(){
    const status=$("qrStatus");
    try{
      const response=await fetch("/api/config",{cache:"no-store"});const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||"Could not load QR settings.");const settings=data.settings||{};
      value={size:clamp(settings.qr_overlay_size??DEFAULT.size,MIN_SIZE,MAX_SIZE),x:clamp(settings.qr_overlay_x??DEFAULT.x,0,100),y:clamp(settings.qr_overlay_y??DEFAULT.y,0,100)};draw();
    }catch(err){status.textContent=err.message||"Could not load QR settings.";draw();}
  }

  async function save(){
    const button=$("qrSave"),status=$("qrStatus");button.disabled=true;status.textContent="Saving…";
    try{
      const response=await fetch("/api/qr-overlay",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({size:Math.round(value.size),x:value.x,y:value.y})});
      const data=await response.json().catch(()=>({}));if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save QR settings.");
      const saved=data.qr_overlay||{};value={size:clamp(saved.size??value.size,MIN_SIZE,MAX_SIZE),x:clamp(saved.x??value.x,0,100),y:clamp(saved.y??value.y,0,100)};draw();status.textContent="Saved. The TV QR will move automatically.";
    }catch(err){status.textContent=err.message||"Could not save QR settings.";}
    finally{button.disabled=false;}
  }

  function start(){let tries=0;(function attempt(){if(mount())return;if(++tries<80)setTimeout(attempt,50);})();}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
