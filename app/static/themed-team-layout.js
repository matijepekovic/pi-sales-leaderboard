/* v45 purpose-built individual-team broadcast renderer.
   Full team themes are not skins on the Classic HTML table. This renderer uses
   the theme assets as structural layout pieces, matching the STATS mockup:
   hero -> column header -> champion strip -> row strips -> totals footer -> frame.
   Other TV modes remain owned by the existing renderer/theme runtime. */
(function(){
  if(typeof render !== "function") return;

  const previousRender = render;
  const ROOT_ID = "themedTeamBroadcast";
  const STYLE_ID = "themedTeamBroadcastStyles";
  const SUM_FIELDS = ["issued_leads","pitched_leads","sold_leads","gross_split","pending_split","net_split"];
  const TEXT_METRICS = new Set(["rank","rep_name","team","home_branch","title","hire_date"]);

  const h = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[c]));
  const n = value => {
    const x = Number(value || 0);
    return Number.isFinite(x) ? x : 0;
  };

  function assigned(row){
    return Number(row?.assigned_team_id || 0) > 0;
  }

  function aggregate(rows, base={}){
    const out = {...(base || {}), rep_count: rows.length};
    SUM_FIELDS.forEach(key => out[key] = rows.reduce((sum,row)=>sum+n(row?.[key]),0));
    out.pitched_rate = out.issued_leads ? out.pitched_leads / out.issued_leads * 100 : 0;
    out.close_rate = out.issued_leads ? out.sold_leads / out.issued_leads * 100 : 0;
    out.dpl = out.issued_leads ? out.net_split / out.issued_leads : 0;
    out.sales_retention = out.gross_split ? out.net_split / out.gross_split * 100 : 0;
    out.avg_gross_sale = out.sold_leads ? out.gross_split / out.sold_leads : 0;
    out.avg_net_sale = out.sold_leads ? out.net_split / out.sold_leads : 0;
    return out;
  }

  function teamTheme(data){
    const summary = data.team_summary || {};
    const state = data.theme_state || {};
    const byId = summary.team_id != null && state.teams
      ? state.teams[String(summary.team_id)]
      : null;
    if(byId) return byId;
    const key = String(summary.team || data.selected_team || "").trim().toLowerCase();
    return state.by_name?.[key] || null;
  }

  function usableTheme(data){
    const theme = teamTheme(data);
    return data.mode === "per_team" && theme && theme.enabled && theme.colors;
  }

  function clearLegacyThemeDecor(){
    document.querySelectorAll(".theme-frame,.theme-corner,.theme-hero,.theme-medallion,.theme-total-mark")
      .forEach(el=>el.remove());
  }

  function removeBroadcast(){
    document.getElementById(ROOT_ID)?.remove();
    document.body.classList.remove("broadcast-team-active");
    const header = document.querySelector("body > header");
    const content = document.getElementById("content");
    const status = document.getElementById("status");
    if(header) header.style.display = "";
    if(content) content.style.display = "";
    if(status) status.style.display = "";
  }

  function ensureStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      body.broadcast-team-active{padding:0!important;overflow:hidden!important;background:#070706!important}
      body.broadcast-team-active > header,
      body.broadcast-team-active > #content,
      body.broadcast-team-active > #status{display:none!important}

      #${ROOT_ID}{
        --bt-primary:#c58a2a;--bt-bright:#e1ad48;--bt-dark:#6f4612;
        --bt-secondary:#8b130c;--bt-bg:#070706;--bt-panel:#11100d;
        --bt-text:#e8d6ad;--bt-muted:#a3946f;--bt-champ-text:#f7e7ae;
        position:fixed;inset:0;z-index:120;overflow:hidden;
        display:flex;flex-direction:column;
        color:var(--bt-text);background-color:var(--bt-bg);
        font-family:"Arial Narrow","Roboto Condensed",Impact,Arial,sans-serif;
      }
      #${ROOT_ID} *{box-sizing:border-box}
      #${ROOT_ID} .bt-backdrop{position:absolute;inset:0;z-index:0;background-position:center;background-size:cover;background-repeat:no-repeat}
      #${ROOT_ID} .bt-glow{position:absolute;inset:0;z-index:1;pointer-events:none;background:
        radial-gradient(60% 46% at 50% 4%,color-mix(in srgb,var(--bt-bright) 8%,transparent),transparent 62%),
        radial-gradient(58% 50% at 100% 100%,color-mix(in srgb,var(--bt-secondary) 24%,transparent),transparent 62%),
        radial-gradient(58% 50% at 0% 100%,color-mix(in srgb,var(--bt-secondary) 20%,transparent),transparent 62%),
        linear-gradient(rgba(7,7,6,.86),rgba(7,7,6,.91));
      }
      #${ROOT_ID} .bt-frame{position:absolute;inset:10px;z-index:30;pointer-events:none;border:2px solid var(--bt-primary);box-shadow:inset 0 0 0 1px #000,inset 0 0 0 5px color-mix(in srgb,var(--bt-primary) 35%,transparent),inset 0 0 70px rgba(0,0,0,.74)}
      #${ROOT_ID} .bt-corner{position:absolute;z-index:31;width:clamp(60px,7vw,120px);height:auto;object-fit:contain;pointer-events:none;filter:drop-shadow(0 2px 5px #000)}
      #${ROOT_ID} .bt-corner.tl{top:6px;left:6px}#${ROOT_ID} .bt-corner.tr{top:6px;right:6px}#${ROOT_ID} .bt-corner.bl{bottom:6px;left:6px}#${ROOT_ID} .bt-corner.br{bottom:6px;right:6px}

      #${ROOT_ID} .bt-header{position:relative;z-index:4;flex:0 0 auto;min-height:0;text-align:center;padding:clamp(7px,1.1vh,14px) clamp(30px,3vw,52px) 2px}
      #${ROOT_ID} .bt-hero{display:block;margin:0 auto;width:min(72vw,1160px);height:clamp(185px,38vh,420px);object-fit:contain;filter:drop-shadow(0 5px 14px rgba(0,0,0,.88))}
      #${ROOT_ID}.bt-dense .bt-hero{height:clamp(130px,28vh,285px);width:min(64vw,920px)}
      #${ROOT_ID}.bt-very-dense .bt-hero{height:clamp(100px,22vh,230px);width:min(58vw,800px)}
      #${ROOT_ID} .bt-team-wordmark{height:clamp(130px,29vh,310px);max-width:min(62vw,920px);margin:0 auto;display:flex;align-items:center;justify-content:center;font-family:Impact,"Arial Narrow",sans-serif;font-size:clamp(54px,8vw,138px);line-height:.9;letter-spacing:.035em;text-transform:uppercase;color:var(--bt-bright);text-shadow:0 3px 0 #000,0 0 16px color-mix(in srgb,var(--bt-bright) 30%,transparent);overflow:hidden}
      #${ROOT_ID}.bt-dense .bt-team-wordmark{height:clamp(100px,22vh,225px);font-size:clamp(46px,6.5vw,108px)}
      #${ROOT_ID} .bt-side{position:absolute;top:clamp(16px,2.2vh,30px);right:clamp(24px,3vw,52px);z-index:8;text-align:right;text-transform:uppercase;line-height:1.45;letter-spacing:.20em;font-weight:800;text-shadow:0 2px 4px #000}
      #${ROOT_ID} .bt-side .l1{font-size:clamp(9px,.9vw,15px);color:var(--bt-muted)}
      #${ROOT_ID} .bt-side .l2{font-size:clamp(10px,1.05vw,17px);color:var(--bt-bright);max-width:280px}

      #${ROOT_ID} .bt-main{position:relative;z-index:4;flex:1 1 auto;min-height:0;width:min(94.5%,1810px);margin:0 auto;display:flex;flex-direction:column}
      #${ROOT_ID} .bt-colhead,#${ROOT_ID} .bt-row{display:grid;grid-template-columns:clamp(58px,4.2vw,82px) minmax(220px,2.45fr) repeat(var(--bt-cols),minmax(0,1fr));align-items:center}
      #${ROOT_ID} .bt-colhead{flex:0 0 auto;color:var(--bt-bright);text-transform:uppercase;letter-spacing:.12em;text-align:center;font-size:clamp(8px,.72vw,12px);font-weight:800;padding:7px 0;border-top:1px solid color-mix(in srgb,var(--bt-primary) 48%,transparent);border-bottom:1px solid color-mix(in srgb,var(--bt-primary) 48%,transparent);background:rgba(6,6,5,.92);text-shadow:0 1px 3px #000}
      #${ROOT_ID} .bt-colhead .rep{text-align:left;padding-left:10px;color:var(--bt-muted)}
      #${ROOT_ID} .bt-board{flex:1 1 auto;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:1px}
      #${ROOT_ID} .bt-row{position:relative;flex:1 1 0;min-height:44px;max-height:82px;background-position:center;background-size:100% 100%;background-repeat:no-repeat;border-bottom:1px solid color-mix(in srgb,var(--bt-primary) 13%,transparent);overflow:hidden}
      #${ROOT_ID}.bt-dense .bt-row{min-height:38px;max-height:67px}
      #${ROOT_ID}.bt-very-dense .bt-row{min-height:31px;max-height:55px}
      #${ROOT_ID} .bt-row::before{content:"";position:absolute;inset:0;background:rgba(4,4,3,.56);z-index:0;pointer-events:none}
      #${ROOT_ID} .bt-row > *{position:relative;z-index:1}
      #${ROOT_ID} .bt-rank{font-family:Impact,"Arial Narrow",sans-serif;text-align:center;color:var(--bt-bright);font-size:clamp(23px,2.65vw,46px);font-weight:900;text-shadow:0 2px 4px #000;min-width:0}
      #${ROOT_ID}.bt-dense .bt-rank{font-size:clamp(20px,2.15vw,36px)}
      #${ROOT_ID} .bt-rep{padding:4px 10px;min-width:0;overflow:hidden}
      #${ROOT_ID} .bt-name{font-family:Impact,"Arial Narrow",sans-serif;color:var(--bt-bright);font-size:clamp(14px,1.32vw,23px);letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 3px #000}
      #${ROOT_ID}.bt-dense .bt-name{font-size:clamp(12px,1.12vw,19px)}
      #${ROOT_ID} .bt-repmeta{margin-top:2px;color:var(--bt-muted);font-size:clamp(7px,.62vw,11px);letter-spacing:.13em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #${ROOT_ID}.bt-very-dense .bt-repmeta{display:none}
      #${ROOT_ID} .bt-stat{align-self:stretch;display:flex;align-items:center;justify-content:center;text-align:center;border-left:1px solid color-mix(in srgb,var(--bt-primary) 24%,transparent);font-variant-numeric:tabular-nums;font-weight:800;font-size:clamp(10px,.88vw,16px);text-shadow:0 2px 3px #000;white-space:nowrap;overflow:hidden;padding:0 3px}
      #${ROOT_ID}.bt-dense .bt-stat{font-size:clamp(9px,.76vw,13px)}
      #${ROOT_ID} .bt-stat.currency{color:var(--bt-bright)}
      #${ROOT_ID} .bt-stat.primary{color:var(--bt-champ-text);font-weight:900;position:relative}
      #${ROOT_ID} .bt-champion{flex-grow:1.18;min-height:58px;max-height:100px;margin:4px 0;border:2px solid var(--bt-bright);border-radius:7px;box-shadow:0 0 34px color-mix(in srgb,var(--bt-bright) 34%,transparent),inset 0 0 0 1px color-mix(in srgb,var(--bt-champ-text) 28%,transparent),0 4px 26px rgba(0,0,0,.82)}
      #${ROOT_ID} .bt-champion::before{background:rgba(30,4,3,.12)}
      #${ROOT_ID} .bt-champion::after{content:"";position:absolute;top:0;bottom:0;width:28%;z-index:2;background:linear-gradient(105deg,transparent,color-mix(in srgb,var(--bt-champ-text) 15%,transparent),transparent);animation:btShimmer 8s linear infinite;pointer-events:none}
      @keyframes btShimmer{from{left:-35%}to{left:135%}}
      @media(prefers-reduced-motion:reduce){#${ROOT_ID} .bt-champion::after{animation:none}}
      #${ROOT_ID} .bt-champion .bt-name{color:var(--bt-champ-text);font-size:clamp(15px,1.45vw,25px)}
      #${ROOT_ID} .bt-medallion{display:block;width:clamp(48px,5.2vw,88px);height:clamp(48px,7.2vh,88px);object-fit:contain;margin:auto;filter:drop-shadow(0 3px 10px rgba(0,0,0,.9))}
      #${ROOT_ID}.bt-dense .bt-medallion{width:clamp(38px,4.2vw,64px);height:clamp(38px,5.6vh,64px)}
      #${ROOT_ID} .bt-champion .bt-stat.primary::after{content:"";position:absolute;left:16%;right:16%;bottom:18%;height:2px;background:linear-gradient(90deg,transparent,var(--bt-bright),transparent);box-shadow:0 0 8px color-mix(in srgb,var(--bt-bright) 85%,transparent)}

      #${ROOT_ID} .bt-footer{position:relative;z-index:4;flex:0 0 auto;width:min(94.5%,1810px);margin:clamp(4px,.65vh,9px) auto clamp(9px,1.4vh,18px);display:grid;grid-template-columns:repeat(var(--bt-total-cols),minmax(0,1fr));align-items:center;border-top:2px solid var(--bt-primary);background:rgba(0,0,0,.62);padding:clamp(6px,.9vh,11px) 0;min-height:54px}
      #${ROOT_ID} .bt-total{min-width:0;text-align:center;border-left:1px solid color-mix(in srgb,var(--bt-primary) 28%,transparent);padding:0 4px}
      #${ROOT_ID} .bt-total:first-of-type{border-left:none}
      #${ROOT_ID} .bt-total-v{color:var(--bt-bright);font-size:clamp(12px,1.35vw,23px);font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:clip;font-variant-numeric:tabular-nums;text-shadow:0 2px 3px #000}
      #${ROOT_ID} .bt-total-l{color:var(--bt-muted);font-size:clamp(6px,.58vw,10px);letter-spacing:.15em;text-transform:uppercase;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #${ROOT_ID} .bt-total-mark{position:absolute;left:-2px;bottom:calc(100% - 5px);height:clamp(28px,4.4vh,52px);max-width:120px;object-fit:contain;filter:drop-shadow(0 2px 5px #000)}

      @media(max-width:1100px){
        #${ROOT_ID} .bt-hero{width:min(68vw,780px)}
        #${ROOT_ID} .bt-colhead,#${ROOT_ID} .bt-row{grid-template-columns:52px minmax(180px,2.3fr) repeat(var(--bt-cols),minmax(0,1fr))}
        #${ROOT_ID} .bt-side{right:26px}
      }
    `;
    document.head.appendChild(style);
  }

  function setThemeVars(root, colors={}){
    const vars = {
      primary:"--bt-primary",primary_bright:"--bt-bright",primary_dark:"--bt-dark",
      secondary:"--bt-secondary",background:"--bt-bg",panel:"--bt-panel",
      text:"--bt-text",muted:"--bt-muted",champion_text:"--bt-champ-text"
    };
    Object.entries(vars).forEach(([key,css])=>{
      if(colors[key]) root.style.setProperty(css,colors[key]);
    });
  }

  function cssUrl(url){
    return `url("${String(url || "").replace(/["\\\n\r]/g,"")}")`;
  }

  function dateLabel(data){
    const raw = String(data.subtitle || "").trim();
    if(raw) return raw;
    return "";
  }

  function metricKeys(data){
    const selected = Array.isArray(data.metrics) ? data.metrics : [];
    return selected.filter(key=>!TEXT_METRICS.has(key) && (typeof isNumber !== "function" || isNumber(data.metric_types?.[key])));
  }

  function valueHTML(row,key,data){
    const type = data.metric_types?.[key];
    const value = typeof fmt === "function"
      ? fmt(row?.[key], type, data.currency_symbol)
      : h(row?.[key]);
    return value;
  }

  function rowHTML(row,index,data,theme,metrics,champion){
    const assets = theme.assets || {};
    const rowBg = champion ? (assets.champion || assets.row) : assets.row;
    const classes = ["bt-row",champion?"bt-champion":""].filter(Boolean).join(" ");
    const meta = [row.home_branch,row.title].filter(Boolean).join(" · ");
    const rank = champion && assets.medallion
      ? `<img class="bt-medallion" src="${h(assets.medallion)}" alt="Champion">`
      : String(index+1);
    return `<div class="${classes}" style="${rowBg?`background-image:${cssUrl(rowBg)};`:""}">
      <div class="bt-rank">${rank}</div>
      <div class="bt-rep"><div class="bt-name">${h(row.rep_name)}</div>${meta?`<div class="bt-repmeta">${h(meta)}</div>`:""}</div>
      ${metrics.map(key=>`<div class="bt-stat ${data.metric_types?.[key]==="currency"?"currency":""} ${key===data.sort_metric?"primary":""}">${valueHTML(row,key,data)}</div>`).join("")}
    </div>`;
  }

  function buildBroadcast(data,theme){
    ensureStyles();
    removeBroadcast();
    clearLegacyThemeDecor();

    const rows = (Array.isArray(data.rows)?data.rows:[]).filter(assigned);
    const summary = aggregate(rows,data.team_summary || {});
    const metrics = metricKeys(data);
    const assets = theme.assets || {};
    const colors = theme.colors || {};
    const teamName = summary.team || data.selected_team || data.title || "TEAM";
    const teamLogo = summary.logo_url || null;
    const customHero = assets.hero && String(assets.hero).includes("/api/theme-assets/");
    const isUndisputed = String(teamName).trim().toLowerCase() === "undisputed";
    const hero = customHero ? assets.hero : (isUndisputed && assets.hero ? assets.hero : teamLogo);
    const denseClass = rows.length >= 9 ? "bt-very-dense" : (rows.length >= 7 ? "bt-dense" : "");

    const root = document.createElement("section");
    root.id = ROOT_ID;
    if(denseClass) root.classList.add(denseClass);
    root.style.setProperty("--bt-cols",Math.max(metrics.length,1));
    root.style.setProperty("--bt-total-cols",Math.max(metrics.length,1));
    setThemeVars(root,colors);

    root.innerHTML = `
      <div class="bt-backdrop"></div><div class="bt-glow"></div><div class="bt-frame"></div>
      ${[["corner_tl","tl"],["corner_tr","tr"],["corner_bl","bl"],["corner_br","br"]].map(([key,pos])=>assets[key]?`<img class="bt-corner ${pos}" src="${h(assets[key])}" alt="">`:"").join("")}
      <header class="bt-header">
        ${hero?`<img class="bt-hero" src="${h(hero)}" alt="${h(teamName)}">`:`<div class="bt-team-wordmark">${h(teamName)}</div>`}
        <div class="bt-side"><div class="l1">Leaderboard</div><div class="l2">${h(dateLabel(data))}</div></div>
      </header>
      <main class="bt-main">
        <div class="bt-colhead">
          <div></div><div class="rep">Rep</div>
          ${metrics.map(key=>`<div>${h(data.metric_labels?.[key] || key)}</div>`).join("")}
        </div>
        <div class="bt-board">
          ${rows.length ? rows.map((row,index)=>rowHTML(row,index,data,theme,metrics,index===0)).join("") : `<div style="display:grid;place-items:center;flex:1;color:var(--bt-muted);font-size:24px">No assigned reps</div>`}
        </div>
      </main>
      ${metrics.length?`<footer class="bt-footer">
        ${assets.totals_mark?`<img class="bt-total-mark" src="${h(assets.totals_mark)}" alt="">`:""}
        ${metrics.map(key=>`<div class="bt-total"><div class="bt-total-v">${valueHTML(summary,key,data)}</div><div class="bt-total-l">${h(data.metric_labels?.[key] || key)}</div></div>`).join("")}
      </footer>`:""}
    `;

    const backdrop = root.querySelector(".bt-backdrop");
    if(backdrop){
      backdrop.style.backgroundColor = colors.background || "#070706";
      if(assets.background) backdrop.style.backgroundImage = cssUrl(assets.background);
    }

    document.body.classList.add("broadcast-team-active");
    document.body.appendChild(root);
  }

  render = function(data){
    const result = previousRender(data);
    const theme = usableTheme(data);
    if(theme){
      buildBroadcast(data,theme);
    }else{
      removeBroadcast();
    }
    return result;
  };
})();
