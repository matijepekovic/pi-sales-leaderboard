from pathlib import Path
import re


def replace(path, old, new, label):
    p=Path(path)
    s=p.read_text()
    if old in s:
        s=s.replace(old,new,1)
    elif new not in s:
        raise SystemExit(f"{label} pattern not found in {path}")
    p.write_text(s)

# ---------------- Theme Studio: remove preview zoom/pan completely ----------
p=Path('app/static/theme-studio.js')
s=p.read_text()
s=s.replace('  const MIN_ZOOM=1,MAX_ZOOM=4,MIN_PINCH_DIST=4;\n','')
s=s.replace('  let zoomFactor=1;\n','')
s=s.replace('        touch-action:none;cursor:grab;user-select:none}\n      .td-stage.td-grabbing{cursor:grabbing}\n',
            '        touch-action:auto;cursor:default;user-select:none}\n')
s=s.replace('<div class="td-hint">Pinch to zoom · drag to move · double-tap to fit</div>',
            '<div class="td-hint">Live preview at the TV aspect ratio</div>')
s=s.replace('      installPreviewGestures();\n','')
s=s.replace('    zoomFactor=1;panX=0;panY=0;\n','')
start=s.find('  function fitScale(){')
end=s.find('  /* ------------------------------------------------- entry points per team */')
if start<0 or end<0 or end<=start:
    raise SystemExit('preview gesture block not found')
fit_only='''  function fitScale(){\n    const stage=byId("tdStage");\n    const width=stage?.clientWidth||360;\n    return width/(geometry.width||1920);\n  }\n\n  /* v72: preview is fit-only. No pinch, pan, wheel zoom or double-tap zoom. */\n  function layoutPreview(){\n    const stage=byId("tdStage"),sizer=byId("tdSizer"),frame=byId("tdFrame");\n    if(!stage||!sizer||!frame)return;\n    const fit=fitScale();\n    frame.style.width=`${geometry.width}px`;\n    frame.style.height=`${geometry.height}px`;\n    frame.style.transform="none";\n    stage.style.height=`${geometry.height*fit}px`;\n    sizer.style.transform=`scale(${fit})`;\n  }\n\n'''
s=s[:start]+fit_only+s[end:]
# Fail closed if any old zoom implementation survived.
for token in ('setZoom(', 'installPreviewGestures(', 'zoomFactor', 'panX=', 'panY=', 'MIN_PINCH_DIST'):
    if token in s:
        raise SystemExit(f'zoom token survived: {token}')
p.write_text(s)

# ---------------- Display: readable table sizing + footer placement ---------
Path('app/static/table-readability-v72.js').write_text(r'''/* v72 table readability and table-bound totals.
   Presentation only. Row height remains bounded by v71; this layer makes text
   scale with the rendered row, removes old 1810/1870px width caps, reduces
   cell padding, and keeps comparison totals directly under the last row. */
(function(){
  if(typeof render!=="function") return;
  const previousRender=render;
  const STYLE_ID="tableReadabilityV72Styles";
  let scheduled=false;

  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||a));
  const median=values=>{
    const xs=values.filter(Number.isFinite).sort((a,b)=>a-b);
    if(!xs.length)return 0;
    const i=Math.floor(xs.length/2);
    return xs.length%2?xs[i]:(xs[i-1]+xs[i])/2;
  };
  const rowHeight=(root,selector,championSelector)=>{
    const normal=[...root.querySelectorAll(selector)]
      .filter(el=>!championSelector||!el.matches(championSelector))
      .map(el=>el.getBoundingClientRect().height)
      .filter(h=>h>1);
    if(normal.length)return median(normal);
    const champ=championSelector?root.querySelector(championSelector):null;
    const h=champ?.getBoundingClientRect().height||0;
    return h>1?h/1.16:0;
  };
  const setPx=(root,name,value)=>root.style.setProperty(name,`${value.toFixed(2)}px`);

  function ensureStyles(){
    if(document.getElementById(STYLE_ID))return;
    const style=document.createElement("style");
    style.id=STYLE_ID;
    style.textContent=`
      /* Use the TV width instead of the old fixed 1810/1870px ceilings. */
      #themedTeamBroadcast .bt-main{width:96.5vw!important;max-width:none!important}
      #v55OfficeBroadcast .v55-office-main{width:97vw!important;max-width:none!important}
      .v69-team-card .v69-main{width:98%!important;max-width:none!important}

      /* Give every enabled metric a real readable floor before sharing extra width. */
      #themedTeamBroadcast .bt-head,#themedTeamBroadcast .bt-row,#themedTeamBroadcast .bt-footer{
        grid-template-columns:clamp(48px,3.5vw,78px) minmax(220px,2.2fr) repeat(var(--bt-cols),minmax(86px,1fr))!important
      }
      #v55OfficeBroadcast .v55-office-head,#v55OfficeBroadcast .v55-office-row,#v55OfficeBroadcast .v55-office-footer{
        grid-template-columns:clamp(56px,3.8vw,105px) minmax(260px,2.25fr) clamp(70px,4.8vw,150px) repeat(var(--v55-office-cols),minmax(84px,1fr))!important
      }
      .v69-team-card .v69-head,.v69-team-card .v69-row,.v69-team-card .v69-footer{
        grid-template-columns:clamp(42px,3vw,68px) minmax(190px,2.1fr) repeat(var(--v69-cols),minmax(82px,1fr))!important
      }

      /* Text size follows actual bounded row height. */
      #themedTeamBroadcast .bt-name{font-size:var(--v72-team-name,16px)!important}
      #themedTeamBroadcast .champion .bt-name{font-size:calc(var(--v72-team-name,16px) * 1.08)!important}
      #themedTeamBroadcast .bt-rank{font-size:var(--v72-team-rank,24px)!important}
      #themedTeamBroadcast .bt-stat,#themedTeamBroadcast .bt-total-v{font-size:var(--v72-team-stat,12px)!important}
      #themedTeamBroadcast .bt-head{font-size:var(--v72-team-head,10px)!important}

      #v55OfficeBroadcast .v55-office-name,#v55OfficeBroadcast .champion .v55-office-name{font-size:var(--v72-office-name,15px)!important}
      #v55OfficeBroadcast .v55-office-rank{font-size:var(--v72-office-rank,22px)!important}
      #v55OfficeBroadcast .v55-office-stat,#v55OfficeBroadcast .v55-office-total-v{font-size:var(--v72-office-stat,11px)!important}
      #v55OfficeBroadcast .v55-office-head{font-size:var(--v72-office-head,9px)!important}

      .v69-team-card .v69-rep-name{font-size:var(--v72-comp-name,12px)!important}
      .v69-team-card .v69-rank{font-size:var(--v72-comp-rank,17px)!important}
      .v69-team-card .v69-stat,.v69-team-card .v69-total-v{font-size:var(--v72-comp-stat,10px)!important}
      .v69-team-card .v69-head{font-size:var(--v72-comp-head,9px)!important}

      /* Smaller cell padding gives the text the width instead of whitespace. */
      #themedTeamBroadcast .bt-rep{padding:1px 4px!important}
      #themedTeamBroadcast .bt-stat,#themedTeamBroadcast .bt-total{padding-left:1px!important;padding-right:1px!important}
      #themedTeamBroadcast .bt-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}

      #v55OfficeBroadcast .v55-office-rep{padding:1px 4px!important}
      #v55OfficeBroadcast .v55-office-stat,#v55OfficeBroadcast .v55-office-total{padding-left:1px!important;padding-right:1px!important}
      #v55OfficeBroadcast .v55-office-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}
      #v55OfficeBroadcast .v59-office-team-cell,#v55OfficeBroadcast .v58-office-team-cell{padding:0 1px!important}

      .v69-team-card .v69-rep{padding:1px 4px!important}
      .v69-team-card .v69-stat,.v69-team-card .v69-total{padding-left:1px!important;padding-right:1px!important}
      .v69-team-card .v69-head>div{padding-left:1px!important;padding-right:1px!important;line-height:1.05;white-space:normal}

      /* When moved inside the rows area, comparison totals finish the table
         immediately after the final rep rather than sitting at card bottom. */
      .v69-team-card .v69-rows>.v69-footer{
        width:100%!important;flex:0 0 auto!important;align-self:stretch!important;margin:2px 0 0!important
      }
    `;
    document.head.appendChild(style);
  }

  function applyPerTeam(root){
    const h=rowHeight(root,'.bt-row','.bt-row.champion');
    if(!h)return;
    setPx(root,'--v72-team-name',clamp(h*.36,14,28));
    setPx(root,'--v72-team-rank',clamp(h*.52,22,42));
    setPx(root,'--v72-team-stat',clamp(h*.245,11,19));
    setPx(root,'--v72-team-head',clamp(h*.20,9,15));
  }

  function applyOffice(root){
    const h=rowHeight(root,'.v55-office-row','.v55-office-row.champion');
    if(!h)return;
    setPx(root,'--v72-office-name',clamp(h*.36,14,28));
    setPx(root,'--v72-office-rank',clamp(h*.50,20,40));
    setPx(root,'--v72-office-stat',clamp(h*.24,10.5,19));
    setPx(root,'--v72-office-head',clamp(h*.20,9,15));
  }

  function applyComparison(card){
    const rows=card.querySelector('.v69-rows');
    const footer=card.querySelector('.v69-footer');
    if(rows&&footer&&footer.parentElement!==rows)rows.appendChild(footer);
    const h=rowHeight(card,'.v69-row','.v69-row.champion');
    if(!h)return;
    setPx(card,'--v72-comp-name',clamp(h*.36,12,23));
    setPx(card,'--v72-comp-rank',clamp(h*.48,16,34));
    setPx(card,'--v72-comp-stat',clamp(h*.24,10,16.5));
    setPx(card,'--v72-comp-head',clamp(h*.21,8.5,14));
  }

  function apply(){
    ensureStyles();
    const team=document.getElementById('themedTeamBroadcast');if(team)applyPerTeam(team);
    const office=document.getElementById('v55OfficeBroadcast');if(office)applyOffice(office);
    document.querySelectorAll('.v69-team-card').forEach(applyComparison);
  }
  function schedule(){
    if(scheduled)return;
    scheduled=true;
    requestAnimationFrame(()=>requestAnimationFrame(()=>{scheduled=false;apply();}));
  }

  render=function(data){const result=previousRender(data);schedule();setTimeout(schedule,90);return result;};
  window.addEventListener('resize',schedule);
  const observer=new MutationObserver(mutations=>{
    for(const m of mutations){
      if([...m.addedNodes].some(n=>n.nodeType===1)){schedule();break;}
    }
  });
  if(document.body)observer.observe(document.body,{childList:true,subtree:true});
  ensureStyles();schedule();
})();
''')

replace('app/templates/display.html',
        '<script src="/static/row-height-bounds-v71.js?v=71"></script>\n',
        '<script src="/static/row-height-bounds-v71.js?v=71"></script>\n<script src="/static/table-readability-v72.js?v=72"></script>\n',
        'display readability include')
replace('app/templates/settings.html',
        '<script src="/static/theme-studio.js?v=69"></script>',
        '<script src="/static/theme-studio.js?v=72"></script>',
        'theme studio cache bump')
Path('VERSION').write_text('72\n')
