/* v98 remote settings accordion.
   UX ONLY: moves existing controls into clearer collapsible groups without
   changing any API calls, source logic, scheduler behavior, team logic, or TV
   rendering. Existing DOM nodes are moved intact so their event listeners and
   saved settings behavior stay exactly as shipped. */
(function(){
  const $=id=>document.getElementById(id);
  const app=()=>$("appWrap");
  const STATE_KEY="leaderboard.settings.v98.open";
  let state={};
  try{ state=JSON.parse(localStorage.getItem(STATE_KEY)||"{}"); }catch(_){ state={}; }

  function saveState(){
    try{ localStorage.setItem(STATE_KEY,JSON.stringify(state)); }catch(_){ }
  }

  function injectStyles(){
    if($("v98AccordionStyles")) return;
    const style=document.createElement("style");
    style.id="v98AccordionStyles";
    style.textContent=`
      #v98Sections{display:grid;gap:10px;margin-top:14px}
      .v98-section{background:var(--card);border:1px solid var(--line);margin:0}
      .v98-section>summary,.v98-subsection>summary{
        list-style:none;cursor:pointer;user-select:none;display:flex;align-items:center;
        justify-content:space-between;gap:12px;font-weight:900
      }
      .v98-section>summary::-webkit-details-marker,.v98-subsection>summary::-webkit-details-marker{display:none}
      .v98-section>summary{font-size:19px;padding:15px 17px}
      .v98-section>summary::after,.v98-subsection>summary::after{
        content:"+";font-size:22px;line-height:1;color:var(--muted);font-weight:400
      }
      .v98-section[open]>summary::after,.v98-subsection[open]>summary::after{content:"−"}
      .v98-section[open]>summary{border-bottom:1px solid var(--line)}
      .v98-section-body{padding:16px 17px 18px}
      .v98-inner-card{margin:0!important;padding:0!important;border:0!important;background:transparent!important}
      .v98-inner-card>h2:first-child{display:none!important}
      .v98-subsection{border:1px solid #2b2b2b;background:#101010;margin:10px 0}
      .v98-subsection>summary{padding:11px 12px;font-size:15px}
      .v98-subsection[open]>summary{border-bottom:1px solid #292929}
      .v98-subsection-body{padding:12px}
      .v98-inline-block{margin:10px 0;padding:10px;border:1px solid #2b2b2b;background:#101010}
      .v98-inline-block>h3{margin:0 0 8px}
      .v98-view-mode{margin-bottom:10px}
      .v98-view-help{margin:0 0 12px}
      .v98-save-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid #262626}
      #v98LegacyModeCard{display:none!important}
      @media(max-width:760px){
        #v98Sections{gap:8px}
        .v98-section>summary{padding:14px 13px;font-size:18px}
        .v98-section-body{padding:13px}
      }
    `;
    document.head.appendChild(style);
  }

  function keyOf(label){
    return String(label||"section").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||"section";
  }

  function buildDetails(label,key,sub=false){
    const details=document.createElement("details");
    details.className=sub?"v98-subsection":"v98-section";
    details.dataset.v98Key=key;
    details.open=!!state[key];
    const summary=document.createElement("summary");
    summary.textContent=label;
    const body=document.createElement("div");
    body.className=sub?"v98-subsection-body":"v98-section-body";
    details.append(summary,body);
    details.addEventListener("toggle",()=>{state[key]=details.open;saveState();});
    return {details,body};
  }

  function directCards(){
    const root=app();
    if(!root) return [];
    return Array.from(root.children).filter(el=>el.classList&&el.classList.contains("card"));
  }

  function directCardWith(selector){
    return directCards().find(card=>card.querySelector(selector))||null;
  }

  function headingOf(card){
    return String(card?.querySelector("h2")?.textContent||"").replace(/\s+/g," ").trim();
  }

  function putCardInBody(card,body){
    if(!card||!body) return;
    card.classList.remove("card");
    card.classList.add("v98-inner-card");
    body.appendChild(card);
  }

  function wrapSimpleCard(card,label,stack){
    if(!card||card.dataset.v98Wrapped) return null;
    const key=keyOf(label);
    const {details,body}=buildDetails(label,key,false);
    card.dataset.v98Wrapped="1";
    putCardInBody(card,body);
    stack.appendChild(details);
    return details;
  }

  function makeNestedCard(card,label,key,parentBody){
    if(!card) return null;
    const {details,body}=buildDetails(label,key,true);
    putCardInBody(card,body);
    parentBody.appendChild(details);
    return details;
  }

  function prepareView(stack){
    const displayCard=directCardWith("#displaySettingsTitle");
    const modeCard=directCardWith("#activeMode");
    if(!displayCard) return null;

    const {details,body}=buildDetails("View","view",false);

    if(modeCard){
      modeCard.id="v98LegacyModeCard";
      const active=$("activeMode");
      const field=active?.parentElement;
      if(field){
        field.classList.add("v98-view-mode");
        body.appendChild(field);
      }
      const help=$("activeModeHelp");
      if(help){ help.classList.add("v98-view-help"); body.appendChild(help); }
    }

    const filters=buildDetails("Filters","view-filters",true);
    const shownHeading=Array.from(displayCard.querySelectorAll("h3"))
      .find(h=>/data shown on tv/i.test(h.textContent||""));
    if(shownHeading) shownHeading.textContent="Fields shown on TV";
    putCardInBody(displayCard,filters.body);
    body.appendChild(filters.details);

    const numCard=directCardWith("#v75NumCard")||$("v75NumCard");
    if(numCard) makeNestedCard(numCard,"Number Size","view-number-size",body);

    const actions=document.querySelector("#appWrap > .actions");
    const save=$("save"), saved=$("saved");
    if(save||saved){
      const row=document.createElement("div");
      row.className="v98-save-row";
      if(save){ save.textContent="Save View"; row.appendChild(save); }
      if(saved) row.appendChild(saved);
      body.appendChild(row);
    }

    stack.appendChild(details);
    return {details,actions};
  }

  function prepareTv(stack,actions){
    const tvCard=directCards().find(card=>/TV Controls/i.test(headingOf(card)))||directCardWith("#refreshTV");
    if(!tvCard) return null;
    const openTv=$("openTV");
    if(openTv){
      openTv.textContent="Open TV View";
      const row=tvCard.querySelector(".row")||tvCard;
      row.appendChild(openTv);
    }
    const wrapped=wrapSimpleCard(tvCard,"TV Remote",stack);
    if(actions && !actions.querySelector("button")) actions.style.display="none";
    return wrapped;
  }

  function prepareTeam(stack){
    const card=directCards().find(card=>/Team Builder/i.test(headingOf(card)))||directCardWith("#newTeamBuilder");
    return wrapSimpleCard(card,"Team Builder",stack);
  }

  function movePullStatusIntoReport(sourceCard){
    if(!sourceCard||$("v98PullStatus")) return;
    const pullCard=directCardWith("#sourceStatusLine");
    if(!pullCard) return;
    const block=document.createElement("section");
    block.id="v98PullStatus";
    block.className="v98-inline-block";
    const h=document.createElement("h3");
    h.textContent="Status";
    block.appendChild(h);
    Array.from(pullCard.childNodes).forEach(node=>{
      if(node.nodeType===1 && node.tagName==="H2") return;
      block.appendChild(node);
    });
    const current=$("v79Current");
    const scheduleBox=current?.parentElement;
    if(scheduleBox&&scheduleBox.parentElement===sourceCard) scheduleBox.insertAdjacentElement("afterend",block);
    else sourceCard.insertBefore(block,sourceCard.children[2]||null);
    pullCard.remove();
  }

  function prepareData(stack){
    const sourceCard=$("v90SourceCard");
    if(!sourceCard) return null;
    movePullStatusIntoReport(sourceCard);

    const {details,body}=buildDetails("Data","data",false);
    makeNestedCard(sourceCard,"Tableau Report","data-tableau-report",body);

    const product=$("v75ProductCard");
    if(product) makeNestedCard(product,"Close Rate by Product — Beta","data-product",body);

    stack.appendChild(details);
    return details;
  }

  function organize(){
    const root=app();
    if(!root||$("v98Sections")) return !!$("v98Sections");
    const source=$("v90SourceCard");
    if(!source) return false; // wait until the v97 report card has mounted

    injectStyles();
    const stack=document.createElement("div");
    stack.id="v98Sections";
    const note=root.querySelector(".persist-note");
    if(note) note.insertAdjacentElement("afterend",stack); else root.prepend(stack);

    const view=prepareView(stack);
    prepareTv(stack,view?.actions||null);
    prepareTeam(stack);
    prepareData(stack);

    // Everything else remains functionally untouched, but gets the same
    // collapsible shell so the phone page stays compact.
    const leftovers=directCards().filter(card=>card.id!=="v98LegacyModeCard");
    leftovers.forEach(card=>{
      const raw=headingOf(card)||"Settings";
      let label=raw;
      if(/Software Update/i.test(raw)) label="Software";
      else if(/Settings Lock/i.test(raw)) label="Security";
      wrapSimpleCard(card,label,stack);
    });

    const actions=document.querySelector("#appWrap > .actions");
    if(actions && !actions.querySelector("button")) actions.style.display="none";
    return true;
  }

  function start(){
    let tries=0;
    (function attempt(){
      if(organize()) return;
      if(++tries<40) setTimeout(attempt,50);
    })();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",()=>setTimeout(start,0),{once:true});
  else setTimeout(start,0);
})();
