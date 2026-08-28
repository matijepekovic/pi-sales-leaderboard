/* v127 Windows Theme Builder color/apply reliability.

   Chromium's native color dialog is awkward in kiosk/fullscreen mode and can
   temporarily blank the visual editor. Keep the existing theme inputs and API
   as the source of truth, but edit them through an in-app H/S/L + hex picker.
   The picker paints the real iframe immediately, persists without reloading it,
   and makes any actual design edit activate the team's theme on the TV. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  const META={
    primary:{label:"Frame & Borders",help:"Outer frame, dividers and border accents."},
    primary_bright:{label:"Main Accent",help:"Team name, ranks, totals and highlighted numbers."},
    primary_dark:{label:"Shadow / Depth",help:"Dark depth behind the frame and champion row."},
    secondary:{label:"Background Glow",help:"Secondary glow used in the theme atmosphere."},
    background:{label:"Canvas Background",help:"Main color behind the theme artwork."},
    panel:{label:"Rows & Panels",help:"Leaderboard rows, column header and totals panel."},
    text:{label:"Main Text",help:"Normal stat text and team-lead text."},
    muted:{label:"Labels / Muted Text",help:"Column labels and secondary information."},
    champion_text:{label:"Champion Highlight",help:"Champion name and highlighted champion value."}
  };
  const BT_VAR={
    primary:"--bt-primary",primary_bright:"--bt-bright",primary_dark:"--bt-dark",
    secondary:"--bt-secondary",background:"--bt-bg",panel:"--bt-panel",
    text:"--bt-text",muted:"--bt-muted",champion_text:"--bt-champ"
  };
  const LEGACY_VAR={
    primary:"--theme-primary",primary_bright:"--theme-primary-bright",primary_dark:"--theme-primary-dark",
    secondary:"--theme-secondary",background:"--theme-bg",panel:"--theme-panel",
    text:"--theme-text",muted:"--theme-muted",champion_text:"--theme-champion-text"
  };

  let picker=null;
  let mode=null;
  let decorateTimer=0;
  let enableTimer=0;
  let activePromise=null;

  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||0));
  const validHex=value=>/^#[0-9a-f]{6}$/i.test(String(value||""));
  const status=text=>{const el=document.getElementById("tdStatus");if(el)el.textContent=text||"";};
  const overlay=()=>document.getElementById("teamDesignOverlay");

  function teamId(){
    const frame=document.getElementById("tdFrame");
    try{
      const url=new URL(frame?.getAttribute("src")||"",location.href);
      const match=/^team-(\d+)$/.exec(String(url.searchParams.get("preview")||""));
      if(match)return Number(match[1]);
    }catch(_){ }
    const name=String(document.getElementById("tdWhoName")?.textContent||"").trim().toLowerCase();
    const team=(window.teamDefs||[]).find(t=>String(t.name||"").trim().toLowerCase()===name);
    return Number(team?.team_id||0)||null;
  }

  async function putTheme(payload){
    const id=teamId();
    if(!id)throw new Error("Could not determine which team is being edited.");
    const response=await fetch(`/api/themes/team-${id}`,{
      method:"PUT",cache:"no-store",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload||{})
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.ok===false)throw new Error(data.error||"Could not save the theme.");
    return data;
  }

  function markActive(){
    const enabled=document.getElementById("tdEnabled");
    if(enabled)enabled.checked=true;
  }
  async function ensureActive(){
    markActive();
    if(activePromise)return activePromise;
    activePromise=putTheme({enabled:true}).catch(error=>{status(error.message);}).finally(()=>{activePromise=null;});
    return activePromise;
  }
  function ensureActiveSoon(){
    markActive();clearTimeout(enableTimer);
    enableTimer=setTimeout(()=>ensureActive(),260);
  }

  function hexToHsl(hex){
    const r=parseInt(hex.slice(1,3),16)/255,g=parseInt(hex.slice(3,5),16)/255,b=parseInt(hex.slice(5,7),16)/255;
    const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;
    let h=0;
    if(d){
      if(max===r)h=((g-b)/d)%6;
      else if(max===g)h=(b-r)/d+2;
      else h=(r-g)/d+4;
      h=Math.round(h*60);if(h<0)h+=360;
    }
    const l=(max+min)/2;
    const s=d===0?0:d/(1-Math.abs(2*l-1));
    return [h,Math.round(s*100),Math.round(l*100)];
  }
  function hslToHex(h,s,l){
    h=((Number(h)%360)+360)%360;s=clamp(s,0,100)/100;l=clamp(l,0,100)/100;
    const c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs((h/60)%2-1)),m=l-c/2;
    let r=0,g=0,b=0;
    if(h<60){r=c;g=x;}else if(h<120){r=x;g=c;}else if(h<180){g=c;b=x;}
    else if(h<240){g=x;b=c;}else if(h<300){r=x;b=c;}else{r=c;b=x;}
    const one=v=>Math.round((v+m)*255).toString(16).padStart(2,"0");
    return `#${one(r)}${one(g)}${one(b)}`;
  }

  function frameDoc(){
    try{return document.getElementById("tdFrame")?.contentDocument||null;}catch(_){return null;}
  }
  function paintThemeColor(key,value){
    const doc=frameDoc();if(!doc)return;
    const root=doc.getElementById("themedTeamBroadcast");
    if(root&&BT_VAR[key])root.style.setProperty(BT_VAR[key],value);
    if(root&&key==="background"){
      const bg=root.querySelector(".bt-bg");if(bg)bg.style.backgroundColor=value;
    }
    if(LEGACY_VAR[key])doc.documentElement.style.setProperty(LEGACY_VAR[key],value);
  }
  function paintStripe(value){
    const doc=frameDoc();if(!doc)return;
    [doc.getElementById("themedTeamBroadcast"),doc.getElementById("v55OfficeBroadcast"),...doc.querySelectorAll(".v69-team-card")]
      .filter(Boolean).forEach(root=>root.style.setProperty("--v69-stripe-color",value));
  }

  function updateOriginalInput(value){
    if(!mode||!validHex(value))return;
    value=value.toLowerCase();
    mode.input.value=value;
    if(mode.kind==="theme"){
      const chip=document.querySelector(`[data-chip="${CSS.escape(mode.key)}"]`);
      const label=document.querySelector(`[data-value="${CSS.escape(mode.key)}"]`);
      if(chip)chip.style.background=value;if(label)label.textContent=value;
      paintThemeColor(mode.key,value);
    }else if(mode.kind==="stripe"){
      const chip=document.getElementById("tdStripeChip"),label=document.getElementById("tdStripeValue");
      if(chip)chip.style.background=value;if(label)label.textContent=value;
      paintStripe(value);
    }else if(mode.kind==="tint"){
      const chip=document.querySelector(`[data-tint-chip="${CSS.escape(mode.key)}"]`);
      if(chip)chip.style.background=value;
    }
  }

  function ensureStyles(){
    if(document.getElementById("windowsThemeColorV127Styles"))return;
    const style=document.createElement("style");style.id="windowsThemeColorV127Styles";
    style.textContent=`
      #teamDesignOverlay .td-color-help-v127{margin-top:3px;color:#8e9ba3;font-size:10px;line-height:1.25}
      #teamDesignOverlay #tdColorPickerV127{position:absolute;inset:0;z-index:2400;display:none;place-items:center;
        padding:16px;background:rgba(5,7,9,.80)}
      #teamDesignOverlay #tdColorPickerV127.open{display:grid}
      #tdColorPickerV127 .tcp-card{width:min(390px,100%);padding:18px;border:1px solid #4c6573;border-radius:11px;
        background:#11181d;box-shadow:0 22px 60px rgba(0,0,0,.58)}
      #tdColorPickerV127 h3{margin:0 0 4px;color:#fff;font-size:19px}
      #tdColorPickerV127 .tcp-help{color:#9eabb2;font-size:11px;line-height:1.35;margin-bottom:13px}
      #tdColorPickerV127 .tcp-top{display:grid;grid-template-columns:64px minmax(0,1fr);gap:12px;align-items:center;margin-bottom:13px}
      #tdColorPickerV127 .tcp-swatch{width:64px;height:64px;border-radius:10px;border:1px solid #73828a;box-shadow:inset 0 0 0 1px rgba(0,0,0,.5)}
      #tdColorPickerV127 .tcp-hex{width:100%;min-height:42px;padding:8px 10px;border:1px solid #43515a;border-radius:7px;
        background:#080d10;color:#fff;font:700 14px Consolas,monospace;text-transform:uppercase}
      #tdColorPickerV127 .tcp-line{display:grid;grid-template-columns:72px minmax(0,1fr) 42px;gap:8px;align-items:center;margin:10px 0}
      #tdColorPickerV127 .tcp-line label{font-size:12px;color:#d2dce1}
      #tdColorPickerV127 .tcp-line output{text-align:right;color:#aebbc2;font-size:11px;font-variant-numeric:tabular-nums}
      #tdColorPickerV127 input[type=range]{width:100%;accent-color:#56bdea}
      #tdColorPickerV127 .tcp-actions{display:flex;gap:9px;margin-top:16px}
      #tdColorPickerV127 .tcp-actions .btn{flex:1 1 0}
      #teamDesignOverlay .td-color-native-disabled-v127{display:none!important}
    `;
    document.head.appendChild(style);
  }

  function ensurePicker(){
    if(picker)return picker;
    const panel=document.querySelector("#teamDesignOverlay .td-desktop-panel")||document.querySelector("#teamDesignOverlay .panel");
    if(!panel)return null;
    picker=document.createElement("div");picker.id="tdColorPickerV127";
    picker.innerHTML=`<div class="tcp-card" role="dialog" aria-modal="true" aria-label="Theme color picker">
      <h3 id="tcpTitle">Color</h3><div id="tcpHelp" class="tcp-help"></div>
      <div class="tcp-top"><div id="tcpSwatch" class="tcp-swatch"></div><input id="tcpHex" class="tcp-hex" type="text" maxlength="7" spellcheck="false" aria-label="Hex color"></div>
      <div class="tcp-line"><label for="tcpHue">Hue</label><input id="tcpHue" type="range" min="0" max="359" step="1"><output id="tcpHueOut"></output></div>
      <div class="tcp-line"><label for="tcpSat">Saturation</label><input id="tcpSat" type="range" min="0" max="100" step="1"><output id="tcpSatOut"></output></div>
      <div class="tcp-line"><label for="tcpLight">Lightness</label><input id="tcpLight" type="range" min="0" max="100" step="1"><output id="tcpLightOut"></output></div>
      <div class="tcp-actions"><button class="btn" type="button" data-tcp-cancel="1">Cancel</button><button class="btn primary" type="button" data-tcp-apply="1">Apply</button></div>
    </div>`;
    panel.appendChild(picker);
    const hue=picker.querySelector("#tcpHue"),sat=picker.querySelector("#tcpSat"),light=picker.querySelector("#tcpLight"),hex=picker.querySelector("#tcpHex");
    const fromSliders=()=>setPickerColor(hslToHex(hue.value,sat.value,light.value),false);
    [hue,sat,light].forEach(input=>input.addEventListener("input",fromSliders));
    hex.addEventListener("input",()=>{const v=String(hex.value||"").trim();if(validHex(v))setPickerColor(v,true);});
    picker.querySelector('[data-tcp-cancel="1"]').addEventListener("click",cancelPicker);
    picker.querySelector('[data-tcp-apply="1"]').addEventListener("click",applyPicker);
    picker.addEventListener("pointerdown",e=>{if(e.target===picker)cancelPicker();});
    return picker;
  }

  function setPickerColor(value,fromHex){
    if(!picker||!validHex(value))return;
    value=value.toLowerCase();
    const [h,s,l]=hexToHsl(value);
    if(!fromHex){picker.querySelector("#tcpHex").value=value.toUpperCase();}
    else{
      picker.querySelector("#tcpHue").value=String(h);picker.querySelector("#tcpSat").value=String(s);picker.querySelector("#tcpLight").value=String(l);
    }
    if(!fromHex){
      picker.querySelector("#tcpHue").value=String(h);picker.querySelector("#tcpSat").value=String(s);picker.querySelector("#tcpLight").value=String(l);
    }
    picker.querySelector("#tcpSwatch").style.background=value;
    picker.querySelector("#tcpHueOut").textContent=`${h}°`;
    picker.querySelector("#tcpSatOut").textContent=`${s}%`;
    picker.querySelector("#tcpLightOut").textContent=`${l}%`;
    updateOriginalInput(value);
  }

  function openPicker(nextMode){
    const box=ensurePicker();if(!box||!nextMode?.input)return false;
    const value=validHex(nextMode.input.value)?String(nextMode.input.value).toLowerCase():"#d8b34a";
    mode={...nextMode,original:value};
    box.querySelector("#tcpTitle").textContent=nextMode.label||"Color";
    box.querySelector("#tcpHelp").textContent=nextMode.help||"Adjust the color and watch the TV preview update live.";
    box.classList.add("open");
    setPickerColor(value,true);
    setTimeout(()=>box.querySelector("#tcpHex")?.focus(),0);
    return true;
  }
  function closePicker(){if(picker)picker.classList.remove("open");mode=null;}
  function cancelPicker(){
    if(mode)updateOriginalInput(mode.original);
    closePicker();
  }

  function palette(){
    const colors={};
    document.querySelectorAll("#teamDesignOverlay .tdColorInput").forEach(input=>{
      if(input.dataset.colorKey&&validHex(input.value))colors[input.dataset.colorKey]=String(input.value).toLowerCase();
    });
    return colors;
  }
  async function applyPicker(){
    if(!mode)return;
    const current=String(mode.input.value||"").toLowerCase();
    if(!validHex(current)){status("Enter a six-digit hex color such as #D8B34A.");return;}
    const applying={...mode};
    const applyButton=picker?.querySelector('[data-tcp-apply="1"]');if(applyButton)applyButton.disabled=true;
    try{
      if(applying.kind==="theme"){
        markActive();
        await putTheme({base:document.getElementById("tdPreset")?.value||"starter",enabled:true,colors:palette()});
        status(`${applying.label} saved and applied.`);
      }else if(applying.kind==="stripe"){
        markActive();
        const strength=clamp(document.getElementById("tdStripeStrength")?.value,0,100);
        await putTheme({enabled:true,row_stripe:{color:current,strength}});
        status("Alternating row tint saved and applied.");
      }else if(applying.kind==="tint"){
        await ensureActive();
        const recolor=document.querySelector(`.tdRecolor[data-key="${CSS.escape(applying.key)}"]`);
        if(!recolor||recolor.disabled)throw new Error("Choose artwork first, then recolor it.");
        closePicker();
        recolor.click();
        return;
      }
      closePicker();
    }catch(error){status(error.message||"Could not save that color.");}
    finally{if(applyButton)applyButton.disabled=false;}
  }

  function openThemeColor(key){
    const input=document.getElementById(`tdColor_${key}`),meta=META[key]||{label:key,help:"Theme color."};
    if(!input){status("That color control is unavailable.");return false;}
    return openPicker({kind:"theme",key,input,label:meta.label,help:meta.help});
  }
  function openStripe(){
    const input=document.getElementById("tdStripeColor");if(!input)return false;
    return openPicker({kind:"stripe",key:"row_stripe",input,label:"Alternating Row Tint",help:"Color laid over every other leaderboard row. Tint Strength controls how much of it shows."});
  }
  function openTint(key){
    const input=document.querySelector(`.tdTint[data-key="${CSS.escape(key)}"]`);
    const recolor=document.querySelector(`.tdRecolor[data-key="${CSS.escape(key)}"]`);
    if(!input||!recolor||recolor.disabled){status("Choose artwork first, then recolor it.");return false;}
    const asset=document.querySelector(`[data-asset="${CSS.escape(key)}"] .td-asset-name`)?.textContent||key.replaceAll("_"," ");
    return openPicker({kind:"tint",key,input,label:`Recolor ${asset}`,help:"This recolors the artwork itself. Position, size, rotation and opacity are left unchanged."});
  }

  function decorateColors(){
    ensureStyles();
    const colors=document.getElementById("tdColors");
    if(colors){
      const section=colors.closest(".td-sec");
      if(section&&!section.querySelector(".td-colors-intro-v127")){
        const intro=document.createElement("div");intro.className="small td-colors-intro-v127";
        intro.textContent="Every color below is used by the TV design. The name tells you exactly what it controls.";
        section.querySelector("h3")?.insertAdjacentElement("afterend",intro);
      }
      colors.querySelectorAll(".td-color[data-color]").forEach(row=>{
        const key=String(row.dataset.color||""),meta=META[key];if(!meta)return;
        const label=row.querySelector(".td-color-label");if(label&&label.textContent!==meta.label)label.textContent=meta.label;
        const text=row.querySelector(".td-color-text");
        let help=row.querySelector(".td-color-help-v127");
        if(text&&!help){help=document.createElement("div");help.className="td-color-help-v127";text.appendChild(help);}
        if(help&&help.textContent!==meta.help)help.textContent=meta.help;
      });
    }
    const save=document.getElementById("tdSave");if(save&&save.textContent!=="Save & Apply Design")save.textContent="Save & Apply Design";
    const enabled=document.getElementById("tdEnabled");
    const label=enabled?.closest("label")?.querySelector("span");if(label&&label.textContent!=="Theme is active on the TV")label.textContent="Theme is active on the TV";
    ensurePicker();wrapHost();
  }
  function scheduleDecorate(){
    if(decorateTimer)return;
    decorateTimer=requestAnimationFrame(()=>{decorateTimer=0;decorateColors();});
  }

  function interceptClick(event){
    if(!overlay()?.contains(event.target))return;
    const themeButton=event.target.closest?.("[data-open-color]");
    if(themeButton){
      event.preventDefault();event.stopImmediatePropagation();openThemeColor(String(themeButton.dataset.openColor||""));return;
    }
    if(event.target.closest?.("#tdStripeOpen")){
      event.preventDefault();event.stopImmediatePropagation();openStripe();return;
    }
    const tintChip=event.target.closest?.(".tdTintChip");
    if(tintChip){
      event.preventDefault();event.stopImmediatePropagation();openTint(String(tintChip.dataset.tintChip||""));return;
    }
    if(event.target.closest?.("#tdSave"))markActive();
    if(event.target.closest?.(".td-tile:not(.td-tile-add),.tdRecolor,.tdResetAsset,.tdSnap,.tdUnsnap,#tdLogoReset,#tdSheetReset"))ensureActiveSoon();
  }
  function interceptValueEdit(event){
    if(!overlay()?.contains(event.target)||event.target.id==="tdEnabled")return;
    if(event.target.matches?.("#tdHeroScale,#tdStripeStrength,.tdNum"))ensureActiveSoon();
  }

  function wrapHost(){
    const host=window.StatsThemeEditorHost;if(!host?.action||host.action.__v127Wrapped)return false;
    const previous=host.action;
    const wrapped=function(action,key,team){
      if(action==="color")return key==="background"?openThemeColor("background"):openTint(String(key||""));
      if(action==="upload"||action==="remove")ensureActiveSoon();
      return previous(action,key,team);
    };
    wrapped.__v127Wrapped=true;host.action=wrapped;return true;
  }

  function boot(){
    ensureStyles();decorateColors();
    document.addEventListener("click",interceptClick,true);
    document.addEventListener("change",interceptValueEdit,true);
    document.addEventListener("input",interceptValueEdit,true);
    document.addEventListener("keydown",event=>{if(event.key==="Escape"&&picker?.classList.contains("open"))cancelPicker();});
    const colors=document.getElementById("tdColors");
    if(colors)new MutationObserver(scheduleDecorate).observe(colors,{childList:true,subtree:true});
    let tries=0;(function retryHost(){if(wrapHost())return;if(++tries<120)setTimeout(retryHost,50);})();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
