/* v65 Team Design.

   There is no team picker: a design is always opened FROM a specific team, so
   the team being edited is never in doubt. Phone-first single column. The
   preview is the real TV page at the real TV aspect ratio, pinned under the
   header, edge to edge, and pinch-zoomable. Artwork is chosen by looking at
   it and added with one tap from the same strip, backed by a library that
   grows as you upload. Corner ornaments seat themselves by measuring their
   own transparent margin. */
(function(){
  const CLASSIC={
    primary:"#d8b34a",primary_bright:"#e6c760",primary_dark:"#705b20",
    secondary:"#303030",background:"#080808",panel:"#111111",text:"#f5f5f5",
    muted:"#9c9c9c",champion_text:"#ffffff"
  };
  const UNDISPUTED={
    primary:"#c58a2a",primary_bright:"#e1ad48",primary_dark:"#6f4612",
    secondary:"#8b130c",background:"#070706",panel:"#11100d",text:"#e8d6ad",
    muted:"#a3946f",champion_text:"#f7e7ae"
  };

  /* sx/sy match theme-corner-runtime-v60.js exactly: the saved crop is a
     percentage translate toward each ornament's own screen corner. */
  const CORNERS={
    corner_tl:{label:"Top Left",sx:-1,sy:-1},
    corner_tr:{label:"Top Right",sx:1,sy:-1},
    corner_bl:{label:"Bottom Left",sx:-1,sy:1},
    corner_br:{label:"Bottom Right",sx:1,sy:1}
  };
  const CORNER_SHEET="corner_sheet";
  // Not a stored asset: the picker route for "one ornament, mirrored to four".
  const CORNER_ONE="corner_one";
  const MIN_SIZE=50,MAX_SIZE=600,MAX_CROP=60;
  const MIN_ZOOM=1,MAX_ZOOM=4,MIN_PINCH_DIST=4;

  let state=null;          // /api/themes
  let library={};          // /api/asset-library -> {asset_key:[items]}
  let geometry={width:1920,height:1080,aspect:16/9,source:"default"};
  let teamId=null;
  let zoomFactor=1;
  let busy=false;

  const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const byId=id=>document.getElementById(id);
  const num=(v,d)=>{v=Number(v);return Number.isFinite(v)?v:d;};
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));

  async function jsonFetch(url,options={}){
    const r=await fetch(url,{cache:"no-store",...options});
    let d={};try{d=await r.json();}catch(e){}
    if(!r.ok||d.ok===false)throw new Error(d.error||`Request failed (${r.status})`);
    return d;
  }

  function status(text){const el=byId("tdStatus");if(el)el.textContent=text||"";}
  function setBusy(on){
    busy=!!on;
    document.querySelectorAll("#teamDesignOverlay button,#teamDesignOverlay select,#teamDesignOverlay input")
      .forEach(el=>{if(!el.dataset.tdAlwaysOn)el.disabled=busy;});
  }

  /* ------------------------------------------------------------------ CSS */

  function injectStyles(){
    if(byId("teamDesignStyles"))return;
    const s=document.createElement("style");s.id="teamDesignStyles";
    s.textContent=`
      #teamDesignOverlay .panel{width:min(900px,100%);padding:0;display:flex;flex-direction:column;max-height:none}
      .td-head{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;justify-content:space-between;
        padding:14px 16px;background:#0e0e0e;border-bottom:1px solid #333}
      .td-who{display:flex;gap:11px;align-items:center;min-width:0}
      .td-who img{width:44px;height:44px;object-fit:contain;border:1px solid #333;background:#080808;flex:0 0 auto}
      .td-who-name{font-size:19px;font-weight:900;line-height:1.15;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .td-who-sub{color:#9b9b9b;font-size:12px}
      .td-body{padding:16px;display:flex;flex-direction:column;gap:22px}
      .td-sec>h3{margin:0 0 4px;font-size:16px}
      .td-sec>.small{margin-bottom:10px}
      .td-foot{position:sticky;bottom:0;z-index:5;display:flex;gap:10px;flex-wrap:wrap;
        padding:12px 16px;background:rgba(12,12,12,.97);border-top:1px solid #333}
      .td-foot .btn{flex:1 1 auto;min-height:48px}
      #teamDesignOverlay .btn{min-height:44px}
      #teamDesignOverlay select,#teamDesignOverlay input[type=text],#teamDesignOverlay input[type=number]{min-height:44px}

      .td-confirm{margin:0;padding:13px 15px;border:1px solid #8a6d1f;background:#241d08}
      .td-confirm .btn{margin-top:10px}

      .td-colors{display:grid;grid-template-columns:1fr;gap:10px}

      /* The preview rides along under the header for the whole scroll, and
         runs the full width of the screen. */
      .td-preview-sec{position:sticky;top:var(--td-head-h,72px);z-index:4;
        background:#111;margin:0 -16px;padding:8px 0 0;border-bottom:1px solid #2a2a2a}
      .td-tvline{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
        margin:0 16px 7px;color:#9b9b9b;font-size:12px}
      .td-stage{background:#000;position:relative;overflow:hidden;
        border-top:1px solid #2a2a2a;border-bottom:1px solid #2a2a2a;
        touch-action:none;cursor:grab;user-select:none}
      .td-stage.td-grabbing{cursor:grabbing}
      .td-sizer{position:absolute;top:0;left:0;transform-origin:top left}
      .td-stage iframe,.td-stage img{position:absolute;top:0;left:0;border:0;
        transform-origin:top left;background:#000;pointer-events:none}
      .td-hint{margin:6px 16px 8px;color:#7d7d7d;font-size:11px}

      .td-asset{border:1px solid #303030;background:#0d0d0d;padding:12px;margin-bottom:10px}
      .td-asset-head{display:flex;gap:12px;align-items:center}
      .td-thumb{width:88px;height:60px;flex:0 0 auto;object-fit:contain;background:#070707;border:1px solid #242424}
      .td-thumb.empty{display:grid;place-items:center;color:#6d6d6d;font-size:10px;text-align:center}
      .td-asset-name{font-weight:900}

      /* Artwork is chosen by looking at it, not by reading its name. */
      .td-tiles{display:flex;gap:9px;overflow-x:auto;padding:4px 2px 8px;margin-top:9px;
        scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch}
      .td-tile{flex:0 0 auto;width:96px;background:transparent;border:1px solid #333;padding:0;
        cursor:pointer;scroll-snap-align:start;color:inherit;font:inherit;text-align:center}
      .td-tile:hover{border-color:#585858}
      .td-tile[aria-pressed="true"]{border-color:var(--td-accent,#d8b34a);box-shadow:0 0 0 1px var(--td-accent,#d8b34a)}
      .td-tile:focus-visible{outline:2px solid var(--td-accent,#d8b34a);outline-offset:2px}
      .td-tile-art{width:100%;height:66px;display:block;object-fit:contain;
        background-color:#0b0b0b;
        background-image:linear-gradient(45deg,#181818 25%,transparent 25%,transparent 75%,#181818 75%),
                         linear-gradient(45deg,#181818 25%,transparent 25%,transparent 75%,#181818 75%);
        background-size:14px 14px;background-position:0 0,7px 7px}
      .td-tile-frame{position:relative;width:100%;height:66px;background-color:#0b0b0b}
      .td-tile-frame img{position:absolute;width:44%;height:44%;object-fit:contain}
      .td-tile-frame .tl{top:2px;left:2px}.td-tile-frame .tr{top:2px;right:2px}
      .td-tile-frame .bl{bottom:2px;left:2px}.td-tile-frame .br{bottom:2px;right:2px}
      .td-tile-cap{display:block;padding:5px 6px;font-size:11px;line-height:1.25;color:#b6b6b6;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .td-tile-group{flex:0 0 auto;align-self:stretch;display:flex;align-items:center;
        padding:0 4px;color:#7d7d7d;font-size:10px;letter-spacing:.09em;text-transform:uppercase;
        writing-mode:vertical-rl;transform:rotate(180deg)}

      /* Adding artwork is a tile, so it sits where artwork is chosen and a
         section with no presets still has an obvious way in. */
      .td-tile-add{border-style:dashed;border-color:#4a4a4a}
      .td-tile-add .td-tile-art{display:grid;place-items:center;background-image:none;
        color:var(--td-accent,#d8b34a);font-size:30px;font-weight:400;line-height:1}
      .td-tile-wrap{position:relative;flex:0 0 auto}
      .td-tile-del{position:absolute;top:3px;right:3px;width:30px;height:30px;padding:0;
        border:1px solid #6b3333;background:rgba(10,10,10,.86);color:#ffb3b3;
        border-radius:8px;font-size:15px;line-height:1;cursor:pointer;z-index:2}
      .td-tile-del:hover{background:#2a1010}

      .td-asset-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;align-items:center}
      .td-asset-actions .btn{flex:1 1 auto}

      /* A colour is shown as a colour: a rounded square chip and a real
         button. The native input stays for the OS picker but is not seen. */
      .td-color{display:flex;gap:11px;align-items:center;border:1px solid #2e2e2e;
        background:#0d0d0d;padding:10px}
      .td-color-chip{width:44px;height:44px;flex:0 0 auto;border-radius:10px;
        border:1px solid #4a4a4a;box-shadow:inset 0 0 0 1px rgba(0,0,0,.55)}
      .td-color-text{flex:1 1 auto;min-width:0}
      .td-color-label{font-weight:700;font-size:13px}
      .td-color-value{color:#8f8f8f;font-size:11px;font-variant-numeric:tabular-nums;text-transform:uppercase}
      .td-color-btn{flex:0 0 auto}
      /* The OS colour picker still needs a real input to open from, but it is
         never seen: Chromium enforces a minimum box, so clip it as well. */
      .td-hidden-color{position:absolute;width:1px;height:1px;opacity:0;
        pointer-events:none;clip-path:inset(100%);overflow:hidden}

      .td-tune{margin-top:10px;border-top:1px dashed #333;padding-top:9px}
      .td-tune>summary{cursor:pointer;color:#9b9b9b;font-size:12px;padding:7px 0;list-style:none}
      .td-tune>summary::-webkit-details-marker{display:none}
      .td-tune>summary::before{content:"▸ ";color:#6f6f6f}
      .td-tune[open]>summary::before{content:"▾ "}
      .td-nums{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:9px}
      .td-nums label{font-size:11px;color:#9b9b9b;margin-bottom:4px}
      .td-nudge{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:8px}
      .td-tune-actions{display:flex;gap:8px;margin-top:9px}
      .td-tune-actions .btn{flex:1 1 auto}

      @media(max-width:760px){
        #teamDesignOverlay{padding:0}
        #teamDesignOverlay .panel{min-height:100vh;border:0}
        /* Keep the pinned preview to a third of the screen so the controls
           under it still have room. */
        .td-stage{max-height:38vh}
        .td-thumb{width:72px;height:50px}
      }
      /* A colour row is chip + name + button; two columns cannot hold that on
         a phone, so it stays one column until there is room for two. */
      @media(min-width:760px){
        .td-colors{grid-template-columns:repeat(2,minmax(0,1fr))}
      }
    `;
    document.head.appendChild(s);
  }

  /* ----------------------------------------------------------------- shell */

  function installUI(){
    if(byId("teamDesignOverlay"))return;
    injectStyles();
    const o=document.createElement("div");
    o.id="teamDesignOverlay";o.className="overlay";o.setAttribute("aria-hidden","true");
    o.innerHTML=`<div class="panel">
      <div class="td-head">
        <div class="td-who">
          <div id="tdWhoLogo"></div>
          <div style="min-width:0">
            <div id="tdWhoName" class="td-who-name">Team</div>
            <div class="td-who-sub">Design for this team only</div>
          </div>
        </div>
        <button id="tdClose" class="btn" type="button" data-td-always-on="1">Close</button>
      </div>
      <div class="td-body">
        <div id="tdConfirm" class="td-confirm" style="display:none">
          <strong>You are editing <span id="tdConfirmName"></span>.</strong>
          <div class="small" style="margin-top:4px">Changes here affect this team's TV design and nothing else.</div>
          <button id="tdConfirmOk" class="btn primary" type="button" data-td-always-on="1">Got it — edit this team</button>
        </div>

        <div id="tdMain" style="display:none;flex-direction:column;gap:22px">
          <section class="td-sec td-preview-sec">
            <div id="tdTvLine" class="td-tvline"></div>
            <div id="tdStage" class="td-stage"><div id="tdSizer" class="td-sizer"><iframe id="tdFrame" title="TV preview" scrolling="no"></iframe></div></div>
            <div class="td-hint">Pinch to zoom · drag to move · double-tap to fit</div>
          </section>

          <section class="td-sec">
            <h3>Theme</h3>
            <label for="tdPreset">Starting theme</label>
            <select id="tdPreset"><option value="classic">Classic</option><option value="undisputed">UNDISPUTED</option></select>
            <label class="row" style="margin-top:12px"><input id="tdEnabled" type="checkbox"><span>Use this custom theme on the TV</span></label>
          </section>

          <section class="td-sec">
            <h3>Colors</h3>
            <div id="tdColors" class="td-colors"></div>
          </section>

          <section class="td-sec">
            <h3>Theme Details</h3>
            <div class="td-color">
              <span class="td-color-chip" style="background:linear-gradient(135deg,#444,#111)"></span>
              <span class="td-color-text"><span class="td-color-label">Hero Size</span><br><span class="td-color-value">50–200%</span></span>
              <input id="tdHeroScale" type="number" min="50" max="200" step="5" value="100" inputmode="numeric" style="width:96px">
            </div>
            <div class="td-color">
              <span id="tdStripeChip" class="td-color-chip" style="background:#d8b34a"></span>
              <span class="td-color-text"><span class="td-color-label">Alternating Row Tint</span><br><span id="tdStripeValue" class="td-color-value">#d8b34a</span></span>
              <button id="tdStripeOpen" class="btn td-color-btn" type="button">Change colour</button>
              <input id="tdStripeColor" class="td-hidden-color" type="color" value="#d8b34a" tabindex="-1" aria-hidden="true">
            </div>
            <label for="tdStripeStrength">Tint strength (%)</label>
            <input id="tdStripeStrength" type="number" min="0" max="100" step="5" value="0" inputmode="numeric">
            <div class="small" style="margin-top:6px">0% keeps the current row appearance. The tint is applied to alternating rows over the theme artwork.</div>
          </section>

          <section class="td-sec">
            <h3>Team Logo</h3>
            <div class="td-asset" data-asset="team_logo">
              <div class="td-asset-head">
                <div id="tdLogoThumb" class="td-thumb empty">None</div>
                <div class="td-asset-name">Team Logo</div>
              </div>
              <div id="tdLogoTiles" class="td-tiles"></div>
              <div class="td-asset-actions">
                <button id="tdLogoReset" class="btn danger" type="button">Reset</button>
              </div>
            </div>
          </section>

          <section class="td-sec">
            <h3>Frame</h3>
            <div class="small">Add a <strong>full frame</strong> and it is cut into four corners, or <strong>one corner</strong> and it is mirrored into the other three. Either way each corner is seated against its edge — nothing else to do. To set corners individually, use their own sections below.</div>
            <div class="td-asset" data-asset="corner_sheet">
              <div class="td-asset-head">
                <div id="tdSheetThumb" class="td-thumb empty">None</div>
                <div class="td-asset-name">Corner Frame</div>
              </div>
              <div id="tdSheetTiles" class="td-tiles"></div>
              <div class="td-asset-actions">
                <button id="tdSheetReset" class="btn danger" type="button">Reset Corners</button>
              </div>
            </div>
          </section>

          <section class="td-sec">
            <h3>Artwork</h3>
            <div class="small">Tap a picture to use it. Anything you upload is saved here and offered on every team from then on.</div>
            <div id="tdAssets"></div>
          </section>
        </div>
      </div>
      <div class="td-foot">
        <button id="tdSave" class="btn primary" type="button">Save Design</button>
        <button id="tdReset" class="btn danger" type="button">Reset to Classic</button>
        <div id="tdStatus" class="small" style="flex:1 1 100%;min-height:18px;color:#d8b34a"></div>
      </div>
    </div>`;
    document.body.appendChild(o);

    byId("tdClose").addEventListener("click",close);
    byId("tdConfirmOk").addEventListener("click",()=>{
      byId("tdConfirm").style.display="none";
      byId("tdMain").style.display="flex";
      measureHead();
      installPreviewGestures();
      layoutPreview();
    });
    byId("tdPreset").addEventListener("change",presetChanged);
    byId("tdEnabled").addEventListener("change",()=>{saveTheme(true);});
    byId("tdHeroScale").addEventListener("change",()=>saveTheme(true));
    byId("tdStripeStrength").addEventListener("change",()=>saveTheme(true));
    byId("tdStripeOpen").addEventListener("click",()=>{const i=byId("tdStripeColor");if(i){i.focus();i.click();}});
    byId("tdStripeColor").addEventListener("input",()=>{
      const i=byId("tdStripeColor");
      byId("tdStripeChip").style.background=i.value;
      byId("tdStripeValue").textContent=i.value;
    });
    byId("tdStripeColor").addEventListener("change",()=>saveTheme(true));
    byId("tdSave").addEventListener("click",()=>saveTheme(false));
    byId("tdReset").addEventListener("click",resetTheme);
    byId("tdLogoReset").addEventListener("click",resetLogo);
    byId("tdSheetReset").addEventListener("click",resetCornerArtwork);
    window.addEventListener("resize",()=>{measureHead();layoutPreview();});
  }

  /* The preview sticks directly beneath the header, so it has to know how
     tall the header actually is rather than assuming. */
  function measureHead(){
    const head=document.querySelector("#teamDesignOverlay .td-head");
    if(!head)return;
    const h=Math.round(head.getBoundingClientRect().height||72);
    document.documentElement.style.setProperty("--td-head-h",`${h}px`);
  }

  function open(){const o=byId("teamDesignOverlay");o.classList.add("open");o.setAttribute("aria-hidden","false");}
  function close(){
    const o=byId("teamDesignOverlay");o.classList.remove("open");o.setAttribute("aria-hidden","true");
    byId("tdFrame").src="about:blank";
    if(typeof refreshOrg==="function")refreshOrg();
  }

  /* ------------------------------------------------------------------ data */

  const themeFor=()=>teamId&&state?.themes?.teams?.[String(teamId)]||null;
  const teamFor=()=>(state?.teams||[]).find(t=>Number(t.team_id)===Number(teamId))||null;
  const scope=()=>`team-${teamId}`;

  async function refreshState(){
    state=await jsonFetch("/api/themes");
    try{library=(await jsonFetch("/api/asset-library")).items||{};}catch(e){library={};}
  }

  async function openDesign(id){
    installUI();
    teamId=Number(id)||null;
    zoomFactor=1;panX=0;panY=0;
    if(!teamId){alert("Save this team first, then design it.");return;}

    /* Name the team before anything is fetched. The whole point of this screen
       is that you always know which team you are about to change, so the
       confirmation must never trail behind a network round trip. */
    const known=(window.teamDefs||[]).find(t=>Number(t.team_id)===teamId);
    const name=known?.name||`Team ${teamId}`;
    byId("tdWhoName").textContent=name;
    byId("tdConfirmName").textContent=name;
    byId("tdWhoLogo").innerHTML=known?.logo_url
      ?`<img src="${esc(known.logo_url)}" alt="">`
      :`<div class="td-thumb empty" style="width:44px;height:44px">—</div>`;
    byId("tdConfirm").style.display="block";
    byId("tdMain").style.display="none";
    open();
    status("Loading…");

    try{
      geometry=await jsonFetch("/api/tv/geometry");
    }catch(e){geometry={width:1920,height:1080,aspect:16/9,source:"default"};}
    try{
      await refreshState();
    }catch(e){status(e.message);return;}

    const team=teamFor();
    if(team?.name){
      byId("tdWhoName").textContent=team.name;
      byId("tdConfirmName").textContent=team.name;
      if(team.logo_url)byId("tdWhoLogo").innerHTML=`<img src="${esc(team.logo_url)}" alt="">`;
    }
    renderAll();
    status("");
  }

  function renderAll(){
    const theme=themeFor()||{};
    byId("tdPreset").value=theme.base||"classic";
    byId("tdEnabled").checked=!!theme.enabled;
    renderColors(theme.colors||CLASSIC);
    renderThemeDetails(theme);
    renderLogo();
    renderSheet();
    renderAssets();
    renderTvLine();
    loadPreview();
  }

  function renderTvLine(){
    const ratio=geometry.aspect||16/9;
    const label={kiosk:"reported by the TV",drm:"read from the HDMI port",default:"assumed"}[geometry.source]||"detected";
    byId("tdTvLine").textContent=
      `TV: ${geometry.width}×${geometry.height} (${ratio.toFixed(2)}:1) — ${label}.`;
  }

  function renderColors(colors){
    const defs=state.manifest.colors||[];
    byId("tdColors").innerHTML=defs.map(d=>{
      const value=esc(colors[d.key]||"#000000");
      return `<div class="td-color" data-color="${d.key}">
        <span class="td-color-chip" data-chip="${d.key}" style="background:${value}"></span>
        <span class="td-color-text">
          <span class="td-color-label">${esc(d.label)}</span><br>
          <span class="td-color-value" data-value="${d.key}">${value}</span>
        </span>
        <button class="btn td-color-btn" type="button" data-open-color="${d.key}">Change colour</button>
        <input class="tdColorInput td-hidden-color" data-color-key="${d.key}"
               id="tdColor_${d.key}" type="color" value="${value}" tabindex="-1" aria-hidden="true">
      </div>`;
    }).join("");

    document.querySelectorAll("[data-open-color]").forEach(b=>{
      b.addEventListener("click",()=>{
        const input=document.getElementById(`tdColor_${b.dataset.openColor}`);
        if(input){input.focus();input.click();}
      });
    });
    document.querySelectorAll(".tdColorInput").forEach(i=>{
      i.addEventListener("input",()=>{
        const key=i.dataset.colorKey;
        const chip=document.querySelector(`[data-chip="${CSS.escape(key)}"]`);
        const label=document.querySelector(`[data-value="${CSS.escape(key)}"]`);
        if(chip)chip.style.background=i.value;
        if(label)label.textContent=i.value;
      });
    });
  }

  const currentColors=()=>{
    const out={};
    document.querySelectorAll(".tdColorInput").forEach(i=>out[i.dataset.colorKey]=i.value);
    return out;
  };

  function renderThemeDetails(theme){
    const hero=clamp(num(theme?.hero_scale,100),50,200);
    const stripe=theme?.row_stripe||{};
    const color=/^#[0-9a-f]{6}$/i.test(String(stripe.color||""))
      ?String(stripe.color).toLowerCase()
      :String(theme?.colors?.primary||"#d8b34a").toLowerCase();
    const strength=clamp(num(stripe.strength,0),0,100);
    byId("tdHeroScale").value=String(Math.round(hero));
    byId("tdStripeColor").value=color;
    byId("tdStripeChip").style.background=color;
    byId("tdStripeValue").textContent=color;
    byId("tdStripeStrength").value=String(Math.round(strength));
  }

  function presetChanged(){
    const preset=byId("tdPreset").value;
    renderColors(preset==="undisputed"?UNDISPUTED:CLASSIC);
    byId("tdEnabled").checked=preset!=="classic";
  }

  function renderLogo(){
    const t=teamFor();const box=byId("tdLogoThumb");
    if(box){
      if(t?.logo_url)box.outerHTML=`<img id="tdLogoThumb" class="td-thumb" src="${esc(t.logo_url)}" alt="">`;
      else box.outerHTML=`<div id="tdLogoThumb" class="td-thumb empty">None</div>`;
    }
    // The logo is chosen the same way as any other artwork.
    const tiles=byId("tdLogoTiles");
    if(tiles){tiles.innerHTML=presetTiles("team_logo","");bindTiles(tiles);}
  }

  /* --------------------------------------------------------------- presets */

  /* Artwork is picked by looking at it. Corner sets render as a little frame
     so a set reads as a set rather than four unrelated squares. */
  function tileArt(item,assetKey){
    if(assetKey===CORNER_SHEET||item.corners){
      const c=item.corners||{};
      const one=(pos,url)=>url?`<img class="${pos}" src="${esc(url)}" alt="">`:"";
      if(item.corners){
        return `<span class="td-tile-frame">${one("tl",c.corner_tl)}${one("tr",c.corner_tr)}
          ${one("bl",c.corner_bl)}${one("br",c.corner_br)}</span>`;
      }
    }
    return `<img class="td-tile-art" src="${esc(item.url)}" alt="${esc(item.label)}" loading="lazy">`;
  }

  function presetTiles(assetKey,selectedId,opts={}){
    const items=library[assetKey]||[];
    const built=items.filter(i=>i.source!=="user");
    const mine=items.filter(i=>i.source==="user");
    const tile=i=>{
      const button=`<button class="td-tile" type="button" data-key="${esc(assetKey)}"
        data-id="${esc(i.id)}" aria-pressed="${i.id===selectedId?"true":"false"}"
        title="${esc(i.label)}">${tileArt(i,assetKey)}<span class="td-tile-cap">${esc(i.label)}</span></button>`;
      if(i.source!=="user")return button;
      return `<span class="td-tile-wrap">${button}
        <button class="td-tile-del" type="button" data-del-key="${esc(assetKey)}"
          data-del-id="${esc(i.id)}" title="Delete ${esc(i.label)}"
          aria-label="Delete ${esc(i.label)}">×</button></span>`;
    };
    // Adding is the first thing in the strip, unless the caller supplies its own.
    return (opts.noAdd?"":addTile(assetKey))+built.map(tile).join("")
      +(mine.length?`<span class="td-tile-group">Yours</span>${mine.map(tile).join("")}`:"");
  }

  function addTile(assetKey,glyph,caption,title){
    return `<button class="td-tile td-tile-add" type="button" data-add="${esc(assetKey)}"
      title="${esc(title||"Add your own artwork")}">
      <span class="td-tile-art">${esc(glyph||"+")}</span>
      <span class="td-tile-cap">${esc(caption||"Add")}</span></button>`;
  }

  function bindTiles(root){
    const scope=root||document;
    scope.querySelectorAll(".td-tile").forEach(b=>{
      if(b.dataset.bound)return;
      b.dataset.bound="1";
      if(b.dataset.add!==undefined)b.addEventListener("click",()=>pickFileFor(b.dataset.add));
      else b.addEventListener("click",()=>applyPreset(b.dataset.key,b.dataset.id));
    });
    scope.querySelectorAll(".td-tile-del").forEach(b=>{
      if(b.dataset.bound)return;
      b.dataset.bound="1";
      b.addEventListener("click",e=>{
        e.stopPropagation();
        deleteLibraryItem(b.dataset.delKey,b.dataset.delId);
      });
    });
  }

  /* One hidden file input, reused. Choosing a file uploads it — there is no
     second step and nothing that says "No file chosen". */
  function pickFileFor(assetKey){
    let input=byId("tdPicker");
    if(!input){
      input=document.createElement("input");
      input.type="file";input.id="tdPicker";
      input.accept="image/png,image/jpeg,image/webp";
      input.style.display="none";
      document.body.appendChild(input);
    }
    input.onchange=async()=>{
      const file=input.files?.[0];
      input.value="";
      if(!file)return;
      if(assetKey===CORNER_SHEET)await buildCorners(file,"sheet");
      else if(assetKey===CORNER_ONE)await buildCorners(file,"mirror");
      else if(assetKey==="team_logo")await uploadLogo(file);
      else await uploadAsset(assetKey,file,file.name);
    };
    input.click();
  }

  async function deleteLibraryItem(assetKey,id){
    if(!id.startsWith("user:"))return;
    if(!confirm("Remove this from your saved artwork? Teams already using it keep their copy."))return;
    try{
      await jsonFetch(`/api/asset-library/${encodeURIComponent(assetKey)}/${encodeURIComponent(id.slice(5))}`,
        {method:"DELETE"});
      library=(await jsonFetch("/api/asset-library")).items||library;
      renderAssets();renderSheet();renderLogo();
      status("Removed from your saved artwork.");
    }catch(e){status(e.message);}
  }

  function renderAssets(){
    const theme=themeFor()||{};
    const assets=theme.assets||{};
    const defs=(state.manifest.assets||[]).filter(d=>d.key!==CORNER_SHEET);
    byId("tdAssets").innerHTML=defs.map(d=>{
      const src=assets[d.key];
      const corner=!!CORNERS[d.key];
      const cfg=cornerCfg(d.key);
      return `<div class="td-asset" data-asset="${d.key}">
        <div class="td-asset-head">
          ${src?`<img class="td-thumb" data-thumb="${d.key}" src="${esc(src)}" alt="">`
               :`<div class="td-thumb empty" data-thumb="${d.key}">None</div>`}
          <div class="td-asset-name">${esc(d.label)}</div>
        </div>
        <div class="td-tiles" data-tiles="${d.key}">${presetTiles(d.key,"")}</div>
        <div class="td-asset-actions">
          <span class="td-color-chip tdTintChip" data-tint-chip="${d.key}"
                style="background:${esc(theme.colors?.primary_bright||"#d8b34a")};width:38px;height:38px"></span>
          <button class="btn tdRecolor" data-key="${d.key}" type="button" ${src?"":"disabled"}>Recolour</button>
          <button class="btn danger tdResetAsset" data-key="${d.key}" type="button">Reset</button>
          <input class="tdTint td-hidden-color" data-key="${d.key}" id="tdTint_${d.key}" type="color"
                 value="${esc(theme.colors?.primary_bright||"#d8b34a")}" tabindex="-1" aria-hidden="true">
        </div>
        ${corner?`<details class="td-tune">
          <summary>Fine-tune position</summary>
          <div class="small">Corners seat themselves when artwork is added. These are only for artwork that measures wrong.</div>
          <div class="td-nums">
            <div><label>Size %</label><input class="tdNum" data-key="${d.key}" data-field="size" type="number" min="${MIN_SIZE}" max="${MAX_SIZE}" step="1" value="${cfg.size}"></div>
            <div><label>Crop X %</label><input class="tdNum" data-key="${d.key}" data-field="crop_x" type="number" min="0" max="${MAX_CROP}" step="1" value="${cfg.crop_x}"></div>
            <div><label>Crop Y %</label><input class="tdNum" data-key="${d.key}" data-field="crop_y" type="number" min="0" max="${MAX_CROP}" step="1" value="${cfg.crop_y}"></div>
          </div>
          <div class="td-nudge">
            <button class="btn tdNudge" data-key="${d.key}" data-field="crop_x" data-step="-1" type="button">← X</button>
            <button class="btn tdNudge" data-key="${d.key}" data-field="crop_x" data-step="1" type="button">X →</button>
            <button class="btn tdNudge" data-key="${d.key}" data-field="crop_y" data-step="-1" type="button">↑ Y</button>
            <button class="btn tdNudge" data-key="${d.key}" data-field="crop_y" data-step="1" type="button">Y ↓</button>
          </div>
          <div class="td-tune-actions">
            <button class="btn tdSnap" data-key="${d.key}" type="button">Seat It Again</button>
            <button class="btn tdUnsnap" data-key="${d.key}" type="button">Clear Position</button>
          </div>
        </details>`:""}
      </div>`;
    }).join("");

    bindTiles(byId("tdAssets"));
    // Tapping the tint chip opens the OS picker; Recolour then applies it.
    document.querySelectorAll(".tdTintChip").forEach(chip=>{
      chip.addEventListener("click",()=>byId(`tdTint_${chip.dataset.tintChip}`)?.click());
    });
    document.querySelectorAll(".tdTint").forEach(i=>{
      i.addEventListener("input",()=>{
        const chip=document.querySelector(`[data-tint-chip="${CSS.escape(i.dataset.key)}"]`);
        if(chip)chip.style.background=i.value;
      });
    });
    document.querySelectorAll(".tdRecolor").forEach(b=>b.addEventListener("click",()=>recolorAsset(b.dataset.key)));
    document.querySelectorAll(".tdResetAsset").forEach(b=>b.addEventListener("click",()=>resetAsset(b.dataset.key)));
    document.querySelectorAll(".tdSnap").forEach(b=>b.addEventListener("click",()=>snapFlush(b.dataset.key)));
    document.querySelectorAll(".tdUnsnap").forEach(b=>b.addEventListener("click",()=>{
      const cfg={size:100,crop_x:0,crop_y:0};
      writeCornerInputs(b.dataset.key,cfg);
      saveCorner(b.dataset.key,cfg);
    }));
    // "input" paints while typing; "change" also covers steppers and blur on
    // browsers that only fire one of the two. The debounce collapses both.
    document.querySelectorAll(".tdNum").forEach(i=>{
      const push=()=>saveCorner(i.dataset.key,readCornerInputs(i.dataset.key));
      i.addEventListener("input",push);
      i.addEventListener("change",push);
    });
    document.querySelectorAll(".tdNudge").forEach(b=>b.addEventListener("click",()=>{
      const input=document.querySelector(`.tdNum[data-key="${CSS.escape(b.dataset.key)}"][data-field="${b.dataset.field}"]`);
      if(!input)return;
      input.value=clamp(num(input.value,0)+Number(b.dataset.step),0,MAX_CROP);
      saveCorner(b.dataset.key,readCornerInputs(b.dataset.key));
    }));
  }

  function renderSheet(){
    const box=byId("tdSheetTiles");
    if(box){
      // Two ways in: a whole frame to cut up, or one ornament to mirror.
      box.innerHTML=
        addTile(CORNER_SHEET,"⊞","Full frame","One image holding all four ornaments")
        +addTile(CORNER_ONE,"◺","One corner","One ornament, mirrored into all four corners")
        +presetTiles(CORNER_SHEET,"",{noAdd:true});
      bindTiles(box);
    }
    const thumb=byId("tdSheetThumb");
    const corner=(themeFor()||{}).assets?.corner_tl;
    if(thumb){
      if(corner)thumb.outerHTML=`<img id="tdSheetThumb" class="td-thumb" src="${esc(corner)}" alt="">`;
      else thumb.outerHTML=`<div id="tdSheetThumb" class="td-thumb empty">None</div>`;
    }
  }

  /* ------------------------------------------------------------- corner cfg */

  function cornerCfg(key){
    const saved=(themeFor()?.corner_settings||{})[key]||{};
    return {
      size:clamp(num(saved.size,100),MIN_SIZE,MAX_SIZE),
      crop_x:clamp(num(saved.crop_x,0),0,MAX_CROP),
      crop_y:clamp(num(saved.crop_y,0),0,MAX_CROP)
    };
  }

  function readCornerInputs(key){
    const get=f=>document.querySelector(`.tdNum[data-key="${CSS.escape(key)}"][data-field="${f}"]`);
    return {
      size:clamp(num(get("size")?.value,100),MIN_SIZE,MAX_SIZE),
      crop_x:clamp(num(get("crop_x")?.value,0),0,MAX_CROP),
      crop_y:clamp(num(get("crop_y")?.value,0),0,MAX_CROP)
    };
  }

  function writeCornerInputs(key,cfg){
    Object.entries(cfg).forEach(([field,value])=>{
      const el=document.querySelector(`.tdNum[data-key="${CSS.escape(key)}"][data-field="${field}"]`);
      if(el)el.value=Math.round(value*10)/10;
    });
  }

  /* Paint the change straight into the preview instead of reloading it. The
     frame is same-origin and the maths is the TV runtime's own, so what shows
     here is what the TV will do — but instantly, and without a blank reload. */
  function paintCorner(key,cfg){
    const info=CORNERS[key];
    const doc=byId("tdFrame")?.contentDocument;
    if(!info||!doc)return;
    const transform=`translate(${info.sx*cfg.crop_x}%,${info.sy*cfg.crop_y}%) scale(${cfg.size/100})`;
    const origin=`${info.sx<0?"left":"right"} ${info.sy<0?"top":"bottom"}`;
    const pos=`${info.sy<0?"t":"b"}${info.sx<0?"l":"r"}`;
    [".theme-corner",".bt-corner",".v55-office-corner",".v55-card-corner"].forEach(prefix=>{
      doc.querySelectorAll(`${prefix}.${pos}`).forEach(img=>{
        img.style.transformOrigin=origin;
        img.style.transform=transform;
      });
    });
  }

  const cornerSaveTimers={};
  async function writeCorner(key,cfg){
    try{
      const d=await jsonFetch(`/api/themes/${encodeURIComponent(scope())}`,{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({corner_settings:{[key]:cfg}})
      });
      if(d.theme&&state?.themes?.teams)state.themes.teams[String(teamId)]=d.theme;
      status("Saved. The TV picks it up automatically.");
    }catch(e){status(e.message);}
  }

  function saveCorner(key,cfg,immediate){
    paintCorner(key,cfg);                    // instant, on every change
    clearTimeout(cornerSaveTimers[key]);
    // Automatic seating writes straight away; only human nudging is debounced,
    // so holding an arrow costs one write instead of one per tap.
    if(immediate)return writeCorner(key,cfg);
    cornerSaveTimers[key]=setTimeout(()=>writeCorner(key,cfg),400);
  }

  function repaintAllCorners(){
    Object.keys(CORNERS).forEach(key=>paintCorner(key,cornerCfg(key)));
  }

  /* ------------------------------------------------------------ image tools */

  function loadImage(src){
    return new Promise((resolve,reject)=>{
      const img=new Image();
      img.onload=()=>resolve(img);
      img.onerror=()=>reject(new Error("Could not load that artwork."));
      // Server URLs need a cache-buster so a just-replaced asset is re-read.
      // blob:/data: URLs must be used verbatim — a query string breaks them.
      const local=/^(blob:|data:)/i.test(src);
      img.src=local?src:src+(src.includes("?")?"&":"?")+"t="+Date.now();
    });
  }

  function canvasOf(img,w,h){
    const c=document.createElement("canvas");
    c.width=w||img.naturalWidth;c.height=h||img.naturalHeight;
    return c;
  }

  const hexRgb=hex=>[parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)];
  const toBlob=canvas=>new Promise(r=>canvas.toBlob(r,"image/png",0.95));

  /* The transparent margin around the visible pixels, as a fraction of the
     image box on each side. This is what "snap flush" cancels out. */
  function alphaInsets(img){
    const c=canvasOf(img);
    const ctx=c.getContext("2d",{willReadFrequently:true});
    ctx.drawImage(img,0,0);
    const {data}=ctx.getImageData(0,0,c.width,c.height);
    let x0=c.width,y0=c.height,x1=-1,y1=-1;
    for(let y=0;y<c.height;y++){
      for(let x=0;x<c.width;x++){
        if(data[(y*c.width+x)*4+3]>8){
          if(x<x0)x0=x;
          if(x>x1)x1=x;
          if(y<y0)y0=y;
          if(y>y1)y1=y;
        }
      }
    }
    if(x1<0)return null;                       // nothing visible at all
    return {
      left:x0/c.width, top:y0/c.height,
      right:(c.width-1-x1)/c.width, bottom:(c.height-1-y1)/c.height
    };
  }

  async function snapFlush(key,quiet=false){
    const info=CORNERS[key];
    const thumb=document.querySelector(`[data-thumb="${CSS.escape(key)}"]`);
    const src=thumb?.tagName==="IMG"?thumb.getAttribute("src"):null;
    if(!info||!src){if(!quiet)status("Upload corner artwork first.");return false;}
    if(!quiet)status(`Measuring ${info.label}…`);
    try{
      const insets=alphaInsets(await loadImage(src));
      if(!insets){if(!quiet)status("That image is fully transparent — nothing to seat.");return false;}
      const x=info.sx<0?insets.left:insets.right;
      const y=info.sy<0?insets.top:insets.bottom;
      if(x<0.002&&y<0.002){
        if(!quiet)status(`${info.label} already sits flush — no margin to remove.`);
        return false;
      }
      const cfg={...readCornerInputs(key),
        crop_x:clamp(x*100,0,MAX_CROP), crop_y:clamp(y*100,0,MAX_CROP)};
      writeCornerInputs(key,cfg);
      await saveCorner(key,cfg,true);
      if(!quiet)status(`${info.label} seated against the edge.`);
      return true;
    }catch(e){if(!quiet)status(e.message);return false;}
  }

  /* ------------------------------------------------------------- asset APIs */

  async function postAsset(key,body){
    return jsonFetch(`/api/themes/${encodeURIComponent(scope())}/assets/${encodeURIComponent(key)}`,body);
  }

  async function applyPreset(key,id){
    if(!id){status("Choose a preset first.");return;}
    // The logo goes through the team endpoint, so fetch the saved file and
    // send it the way an upload would.
    if(key==="team_logo"){
      const item=(library.team_logo||[]).find(i=>i.id===id);
      if(!item){status("That logo is no longer available.");return;}
      setBusy(true);status("Applying logo…");
      try{
        const blob=await (await fetch(item.url,{cache:"no-store"})).blob();
        await uploadLogo(new File([blob],item.label||"logo.png",{type:blob.type||"image/png"}),true);
      }catch(e){status(e.message);}finally{setBusy(false);}
      return;
    }
    // A frame tile means all four corners, cut from the one image.
    if(key===CORNER_SHEET){
      const item=(library[CORNER_SHEET]||[]).find(i=>i.id===id);
      if(!item){status("That frame is no longer available.");return;}
      setBusy(true);status("Cutting corners from the frame…");
      try{
        await applySheetBlobs(await splitSheetImage(await loadImage(item.url)));
        status("Frame applied — all four corners seated.");
      }catch(e){status(e.message);}finally{setBusy(false);}
      return;
    }
    setBusy(true);status("Applying artwork…");
    try{
      await postAsset(key,{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({library_id:id})});
      await refreshState();renderAssets();reloadPreview();
      if(CORNERS[key])await snapFlush(key,true);
      status("Artwork applied.");
    }catch(e){status(e.message);}finally{setBusy(false);}
  }

  async function uploadAsset(key,blob=null,filename=null){
    const file=blob;
    if(!file){status("Choose an image first.");return false;}
    const form=new FormData();form.append("asset",file,filename||file.name||`${key}.png`);
    setBusy(true);status("Saving artwork…");
    try{
      await postAsset(key,{method:"POST",body:form});
      await refreshState();renderAssets();renderSheet();reloadPreview();
      if(CORNERS[key])await snapFlush(key,true);
      status("Artwork saved and added to your presets.");
      return true;
    }catch(e){status(e.message);return false;}finally{setBusy(false);}
  }

  async function resetAsset(key){
    setBusy(true);
    try{
      await postAsset(key,{method:"DELETE"});
      await refreshState();renderAssets();reloadPreview();
      status("Back to the preset original.");
    }catch(e){status(e.message);}finally{setBusy(false);}
  }

  async function recolorAsset(key){
    const thumb=document.querySelector(`[data-thumb="${CSS.escape(key)}"]`);
    const src=thumb?.tagName==="IMG"?thumb.getAttribute("src"):null;
    if(!src)return;
    const tint=document.querySelector(`.tdTint[data-key="${CSS.escape(key)}"]`)?.value||"#d8b34a";
    setBusy(true);status("Recoloring…");
    try{
      const img=await loadImage(src);
      const c=canvasOf(img);
      const ctx=c.getContext("2d",{willReadFrequently:true});
      ctx.drawImage(img,0,0);
      const pixels=ctx.getImageData(0,0,c.width,c.height);
      const d=pixels.data;const [tr,tg,tb]=hexRgb(tint);
      for(let i=0;i<d.length;i+=4){
        if(d[i+3]===0)continue;
        const lum=(0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2])/255;
        const lift=0.30+0.90*lum;
        d[i]=Math.min(255,tr*lift);d[i+1]=Math.min(255,tg*lift);d[i+2]=Math.min(255,tb*lift);
      }
      ctx.putImageData(pixels,0,0);
      const blob=await toBlob(c);
      if(!blob)throw new Error("Could not generate the recolored artwork.");
      setBusy(false);
      await uploadAsset(key,blob,`${key}-recolored.png`);
    }catch(e){status(e.message);setBusy(false);}
  }

  /* --------------------------------------------------------- corner sheet */

  /* One ornament becomes four. The source is taken to face top-left, which is
     how corner art is normally drawn; each corner then gets the reflection its
     position implies. A source facing some other way comes out consistently
     rotated, which is obvious in the preview and fixable per corner. */
  async function mirrorVariants(img){
    const w=img.naturalWidth,h=img.naturalHeight;
    const flips={
      corner_tl:[1,1],
      corner_tr:[-1,1],
      corner_bl:[1,-1],
      corner_br:[-1,-1]
    };
    const out={};
    for(const [key,[fx,fy]] of Object.entries(flips)){
      const c=canvasOf(null,w,h);
      const ctx=c.getContext("2d");
      ctx.translate(fx<0?w:0,fy<0?h:0);
      ctx.scale(fx,fy);
      ctx.drawImage(img,0,0,w,h);
      out[key]=await toBlob(c);
    }
    return out;
  }

  async function splitSheetImage(img){
    /* Round rather than floor so an odd width never drops its middle column. */
    const w=img.naturalWidth,h=img.naturalHeight;
    const hw=Math.round(w/2),hh=Math.round(h/2);
    const rects={
      corner_tl:[0,0,hw,hh],
      corner_tr:[hw,0,w-hw,hh],
      corner_bl:[0,hh,hw,h-hh],
      corner_br:[hw,hh,w-hw,h-hh]
    };
    const out={};
    for(const [key,[sx,sy,sw,sh]] of Object.entries(rects)){
      const c=canvasOf(null,sw,sh);
      c.getContext("2d").drawImage(img,sx,sy,sw,sh,0,0,sw,sh);
      out[key]=await toBlob(c);
    }
    return out;
  }

  const CORNER_LABEL={corner_tl:"top left",corner_tr:"top right",
                      corner_bl:"bottom left",corner_br:"bottom right"};

  async function applySheetBlobs(parts,sourceName){
    for(const [key,blob] of Object.entries(parts)){
      if(!blob)continue;
      const form=new FormData();
      // Name each piece after where it came from, so the strip reads
      // "crest.png — top right" rather than four identical entries.
      const base=String(sourceName||"corners").replace(/\.[a-z0-9]+$/i,"");
      form.append("asset",blob,`${base} — ${CORNER_LABEL[key]||key}.png`);
      await postAsset(key,{method:"POST",body:form});
    }
    await refreshState();
    renderAssets();
    for(const key of Object.keys(CORNERS))await snapFlush(key,true);
    await refreshState();
    renderAssets();
    reloadPreview();
  }

  async function resetCornerArtwork(){
    if(!confirm("Remove the corner artwork from this team?"))return;
    setBusy(true);status("Clearing corners…");
    try{
      for(const key of Object.keys(CORNERS))await postAsset(key,{method:"DELETE"});
      await refreshState();renderAssets();reloadPreview();
      status("Corners cleared.");
    }catch(e){status(e.message);}finally{setBusy(false);}
  }

  /* Both corner routes end the same way: four images, applied to the four
     corners and seated. Only how the four are produced differs. */
  async function buildCorners(file,mode){
    if(!file){status("Choose an image first.");return;}
    const cutting=mode==="sheet";
    setBusy(true);
    status(cutting?"Cutting the frame into four corners…":"Mirroring into four corners…");
    try{
      const img=await loadImage(URL.createObjectURL(file));
      const parts=cutting?await splitSheetImage(img):await mirrorVariants(img);
      await applySheetBlobs(parts,file.name);
      if(cutting){
        // Keep the sheet so it can be re-applied to another team later.
        try{
          const form=new FormData();
          form.append("asset",file,file.name||"corner-frame.png");
          form.append("label",file.name||"Corner frame");
          await jsonFetch(`/api/asset-library/${CORNER_SHEET}`,{method:"POST",body:form});
          library=(await jsonFetch("/api/asset-library")).items||library;
          renderSheet();
        }catch(e){/* the library is a convenience, never block the corners */}
      }
      status(cutting?"Frame cut into four corners and seated."
                   :"Mirrored into four corners and seated.");
    }catch(e){status(e.message);}finally{setBusy(false);}
  }

  /* --------------------------------------------------------------- theme IO */

  async function saveTheme(quiet){
    if(!teamId)return;
    if(!quiet)status("Saving…");
    try{
      const d=await jsonFetch(`/api/themes/${encodeURIComponent(scope())}`,{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          base:byId("tdPreset").value,
          enabled:byId("tdEnabled").checked,
          colors:currentColors(),
          hero_scale:clamp(num(byId("tdHeroScale")?.value,100),50,200),
          row_stripe:{
            color:byId("tdStripeColor")?.value||"#d8b34a",
            strength:clamp(num(byId("tdStripeStrength")?.value,0),0,100)
          }
        })
      });
      if(d.theme&&state?.themes?.teams)state.themes.teams[String(teamId)]=d.theme;
      status("Design saved. The TV picks it up automatically.");
      reloadPreview();
    }catch(e){status(e.message);}
  }

  async function resetTheme(){
    if(!teamId)return;
    if(!confirm("Reset this team's design to Classic? Custom artwork stops being used, but nothing is deleted."))return;
    try{
      await jsonFetch(`/api/themes/${encodeURIComponent(scope())}`,{method:"DELETE"});
      await refreshState();renderAll();
      status("Reset to Classic.");
    }catch(e){status(e.message);}
  }

  async function uploadLogo(file,fromLibrary){
    if(!file){status("Choose a logo file first.");return;}
    const form=new FormData();form.append("logo",file,file.name);
    try{
      await jsonFetch(`/api/teams/${teamId}/logo`,{method:"POST",body:form});
      // Keep it, so the same logo can be reused on another team later.
      if(!fromLibrary){
        try{
          const saved=new FormData();
          saved.append("asset",file,file.name);
          saved.append("label",file.name||"Logo");
          await jsonFetch("/api/asset-library/team_logo",{method:"POST",body:saved});
          library=(await jsonFetch("/api/asset-library")).items||library;
        }catch(e){/* the library is a convenience, never block the logo */}
      }
      await refreshState();renderLogo();reloadPreview();
      const t=teamFor();
      byId("tdWhoLogo").innerHTML=t?.logo_url?`<img src="${esc(t.logo_url)}" alt="">`:"";
      status("Team logo updated.");
    }catch(e){status(e.message);}
  }

  async function resetLogo(){
    try{
      await jsonFetch(`/api/teams/${teamId}/logo`,{method:"DELETE"});
      await refreshState();renderLogo();reloadPreview();
      status("Team logo removed.");
    }catch(e){status(e.message);}
  }

  /* --------------------------------------------------------------- preview */

  function loadPreview(){
    const frame=byId("tdFrame");
    if(!frame)return;
    frame.onload=()=>{
      // The board renders asynchronously; repaint once it has drawn so any
      // adjustment made before the reload finished is not lost visually.
      setTimeout(repaintAllCorners,900);
      setTimeout(repaintAllCorners,2200);
    };
    frame.src=`/?preview=team-${teamId}&t=${Date.now()}`;
    layoutPreview();
  }

  function reloadPreview(){
    const frame=byId("tdFrame");
    if(frame&&frame.src&&frame.src!=="about:blank")loadPreview();
  }

  function fitScale(){
    const stage=byId("tdStage");
    const width=stage?.clientWidth||360;
    return width/(geometry.width||1920);
  }

  let panX=0,panY=0;

  function layoutPreview(){
    const stage=byId("tdStage"),sizer=byId("tdSizer"),frame=byId("tdFrame");
    if(!stage||!sizer||!frame)return;
    const fit=fitScale();
    frame.style.width=`${geometry.width}px`;
    frame.style.height=`${geometry.height}px`;
    frame.style.transform="none";
    stage.style.height=`${geometry.height*fit}px`;
    clampPan();
    sizer.style.transform=`translate(${panX}px,${panY}px) scale(${fit*zoomFactor})`;
  }

  /* Keep the board inside the window: at fit it is pinned, zoomed in it can
     move but never past its own edges. */
  function clampPan(){
    const stage=byId("tdStage");
    if(!stage)return;
    if(!Number.isFinite(zoomFactor)||zoomFactor<MIN_ZOOM||zoomFactor>MAX_ZOOM)zoomFactor=MIN_ZOOM;
    if(!Number.isFinite(panX))panX=0;
    if(!Number.isFinite(panY))panY=0;
    const fit=fitScale();
    if(!Number.isFinite(fit)||fit<=0){panX=0;panY=0;return;}
    const w=geometry.width*fit*zoomFactor, h=geometry.height*fit*zoomFactor;
    const maxX=Math.max(0,Number.isFinite(w)?w-stage.clientWidth:0);
    const maxY=Math.max(0,Number.isFinite(h)?h-stage.clientHeight:0);
    panX=clamp(panX,-maxX,0);
    panY=clamp(panY,-maxY,0);
  }

  function setZoom(next,originX,originY){
    const before=Number.isFinite(zoomFactor)&&zoomFactor>=MIN_ZOOM&&zoomFactor<=MAX_ZOOM?zoomFactor:MIN_ZOOM;
    const candidate=Number(next);
    zoomFactor=Number.isFinite(candidate)?clamp(candidate,MIN_ZOOM,MAX_ZOOM):before;
    if(Number.isFinite(originX)&&Number.isFinite(originY)&&before>0){
      const ratio=zoomFactor/before;
      if(Number.isFinite(ratio)){
        panX=originX-(originX-(Number.isFinite(panX)?panX:0))*ratio;
        panY=originY-(originY-(Number.isFinite(panY)?panY:0))*ratio;
      }
    }
    if(!Number.isFinite(panX))panX=0;
    if(!Number.isFinite(panY))panY=0;
    if(zoomFactor===MIN_ZOOM){panX=0;panY=0;}
    layoutPreview();
  }

  function installPreviewGestures(){
    const stage=byId("tdStage");
    if(!stage||stage.dataset.gestures)return;
    stage.dataset.gestures="1";

    const points=new Map();
    let startDist=0,startZoom=1,startMid=null,lastTap=0,panning=false,lastX=0,lastY=0;
    const dist=([a,b])=>Math.hypot(a.x-b.x,a.y-b.y);
    const mid=([a,b])=>{
      const r=stage.getBoundingClientRect();
      return {x:(a.x+b.x)/2-r.left,y:(a.y+b.y)/2-r.top};
    };

    stage.addEventListener("pointerdown",e=>{
      try{stage.setPointerCapture(e.pointerId);}catch(_e){}
      if(!Number.isFinite(e.clientX)||!Number.isFinite(e.clientY))return;
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size===2){
        const p=[...points.values()];
        const measured=dist(p);
        startDist=Number.isFinite(measured)&&measured>=MIN_PINCH_DIST?measured:0;
        startZoom=Number.isFinite(zoomFactor)?zoomFactor:MIN_ZOOM;
        startMid=startDist?mid(p):null;
        if(startMid&&(!Number.isFinite(startMid.x)||!Number.isFinite(startMid.y))){startDist=0;startMid=null;}
        panning=false;
      }else if(points.size===1){
        const now=Date.now();
        if(now-lastTap<300){setZoom(1);lastTap=0;return;}   // double-tap = fit
        lastTap=now;
        panning=zoomFactor>1;
        lastX=e.clientX;lastY=e.clientY;
        if(panning)stage.classList.add("td-grabbing");
      }
    });

    stage.addEventListener("pointermove",e=>{
      if(!points.has(e.pointerId))return;
      if(!Number.isFinite(e.clientX)||!Number.isFinite(e.clientY))return;
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size>=2&&startDist>=MIN_PINCH_DIST&&startMid){
        const p=[...points.values()].slice(0,2);
        const measured=dist(p);
        if(Number.isFinite(measured)&&measured>=MIN_PINCH_DIST)setZoom(startZoom*(measured/startDist),startMid.x,startMid.y);
      }else if(panning){
        const dx=e.clientX-lastX,dy=e.clientY-lastY;
        if(Number.isFinite(dx)&&Number.isFinite(dy)){panX+=dx;panY+=dy;}
        lastX=e.clientX;lastY=e.clientY;
        layoutPreview();
      }
    });

    const release=e=>{
      points.delete(e.pointerId);
      if(points.size<2)startDist=0;
      if(!points.size){panning=false;stage.classList.remove("td-grabbing");}
    };
    stage.addEventListener("pointerup",release);
    stage.addEventListener("pointercancel",release);

    // Desktop: ctrl/cmd + wheel, the usual zoom convention.
    stage.addEventListener("wheel",e=>{
      if(!e.ctrlKey&&!e.metaKey)return;
      e.preventDefault();
      const r=stage.getBoundingClientRect();
      setZoom(zoomFactor*(e.deltaY<0?1.12:0.89),e.clientX-r.left,e.clientY-r.top);
    },{passive:false});

    stage.addEventListener("dblclick",()=>setZoom(1));
  }

  /* ------------------------------------------------- entry points per team */

  function decorateTeamList(){
    document.querySelectorAll("#teamBuilderList .team-actions").forEach(box=>{
      if(box.querySelector(".designTeam"))return;
      const edit=box.querySelector(".editTeam");
      const id=edit?.dataset.teamId;
      if(!id)return;
      const btn=document.createElement("button");
      btn.type="button";btn.className="btn designTeam";btn.dataset.teamId=id;
      btn.textContent="Design";
      btn.addEventListener("click",()=>openDesign(id));
      edit.insertAdjacentElement("afterend",btn);
    });
  }

  function installBuilderHook(){
    if(typeof window.renderTeamBuilderList==="function"&&!window.renderTeamBuilderList.__tdWrapped){
      const previous=window.renderTeamBuilderList;
      window.renderTeamBuilderList=function(...args){
        const out=previous.apply(this,args);
        decorateTeamList();
        return out;
      };
      window.renderTeamBuilderList.__tdWrapped=true;
    }
    // Design from inside the builder, for the team currently being edited.
    const nav=document.querySelector("#teamBuilderOverlay .builder-nav > div");
    if(nav&&!byId("builderDesign")){
      const btn=document.createElement("button");
      btn.id="builderDesign";btn.type="button";btn.className="btn";
      btn.textContent="Design";
      btn.style.marginRight="8px";
      btn.addEventListener("click",async()=>{
        if(typeof builderTeamId!=="undefined"&&builderTeamId){
          openDesign(builderTeamId);
          return;
        }
        // A new team has no id yet and a theme needs one, so save first. The
        // team name is how we find the id saveTeamBuilder does not expose.
        if(typeof saveTeamBuilder!=="function")return;
        const name=String(byId("builderTeamName")?.value||"").trim();
        if(!name){status("Name the team first.");return;}
        await saveTeamBuilder();
        const match=(window.teamDefs||[]).find(
          t=>String(t.name||"").trim().toLowerCase()===name.toLowerCase());
        if(match)openDesign(match.team_id);
      });
      nav.insertBefore(btn,nav.firstChild);
    }
  }

  function boot(){
    installUI();
    installBuilderHook();
    decorateTeamList();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();

  // The team list renders asynchronously after the first org fetch, and the
  // builder overlay markup is patched by earlier scripts. Watch, but debounce:
  // decorateTeamList mutates the DOM itself, so an unguarded observer would
  // re-enter on its own writes.
  let rescan=null;
  new MutationObserver(()=>{
    clearTimeout(rescan);
    rescan=setTimeout(()=>{installBuilderHook();decorateTeamList();},60);
  }).observe(document.documentElement,{childList:true,subtree:true});

  window.openTeamDesign=openDesign;
})();
