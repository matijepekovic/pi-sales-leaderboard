/* v75 Number Size control (remote side).

   Per-screen +/- for the size of the numbers on the TV. Writes
   number_font_scale[<active mode>] through the ordinary /api/config save,
   which bumps settings_version — already part of the display's render
   signature — so the board picks it up on its next poll.

   The display half of this lives in number-scale-v75.js. */
(function(){
  const MIN=60,MAX=300,STEP=10;

  const CARD=`
    <div class="card" id="v75NumCard">
      <h2>Number Size</h2>
      <div class="small">Sizes the numbers on the TV only — names, headings
        and the table layout are untouched. Saved per screen.</div>
      <div class="row" style="align-items:center;gap:12px;margin-top:12px">
        <button id="v75NumMinus" class="btn" type="button" aria-label="Smaller numbers">Font −</button>
        <div id="v75NumValue" class="strong" style="min-width:150px;text-align:center">100%</div>
        <button id="v75NumPlus" class="btn" type="button" aria-label="Bigger numbers">Font +</button>
      </div>
      <div id="v75NumScreen" class="small" style="margin-top:8px"></div>
      <div id="v75NumStatus" class="small" style="margin-top:4px"></div>
    </div>`;

  const $=id=>document.getElementById(id);

  function configReady(){
    return typeof config!=="undefined" && config && config.active_mode;
  }

  function activeMode(){
    try{ return parseActive(config.active_mode).mode||"whole_office"; }
    catch(_){ return "whole_office"; }
  }

  function currentScale(){
    const map=(config&&config.number_font_scale)||{};
    const value=Number(map[activeMode()]);
    return Number.isFinite(value)?Math.min(Math.max(value,MIN),MAX):100;
  }

  function paintScale(){
    const box=$("v75NumValue");
    if(!box||!configReady()) return;
    const value=currentScale();
    box.textContent=`${value}%`;
    $("v75NumMinus").disabled=value<=MIN;
    $("v75NumPlus").disabled=value>=MAX;
    // Name the screen being changed, so it is never ambiguous which one
    // these buttons are moving. This is the *saved* active mode -- the
    // screen actually on the TV -- not an unsaved dropdown selection.
    $("v75NumScreen").textContent=
      `Applies to: ${activeLabel(config.active_mode)}`;
  }

  /* The settings page fetches its config after load, so this can mount
     before there is anything to show. Paint as soon as it lands. */
  function paintWhenReady(){
    let tries=0;
    (function attempt(){
      if(configReady()){ paintScale(); return; }
      if(++tries>60) return;
      setTimeout(attempt,150);
    })();
  }

  async function nudge(delta){
    const next=Math.min(Math.max(currentScale()+delta,MIN),MAX);
    const mode=activeMode();
    const status=$("v75NumStatus");
    status.textContent="Saving…";
    const payload={...config,
      number_font_scale:{...(config.number_font_scale||{}),[mode]:next}};
    try{
      const {r,d}=await request("/api/config",{
        method:"PUT",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)});
      if(!r.ok){status.textContent=d.error||"Could not save.";return;}
      config=d.settings;
      paintScale();
      status.textContent="Saved. The TV updates on its next refresh.";
    }catch(e){
      if(e.message!=="locked") status.textContent="Could not reach the Pi.";
    }
  }

  function mount(){
    const app=document.getElementById("appWrap");
    if(!app||document.getElementById("v75NumCard")) return;
    app.insertAdjacentHTML("beforeend",CARD);
    $("v75NumMinus").addEventListener("click",()=>nudge(-STEP));
    $("v75NumPlus").addEventListener("click",()=>nudge(STEP));
    paintWhenReady();
  }

  // Saving from the main Settings button can move the active screen, and the
  // size is per screen, so re-read once that save has landed.
  document.addEventListener("click",event=>{
    if(event.target && event.target.id==="save") setTimeout(paintScale,900);
  });

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }
})();
