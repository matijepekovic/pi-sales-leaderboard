from pathlib import Path

p = Path('VERSION')
if p.read_text() != '100\n':
    raise SystemExit('VERSION is not v100')
p.write_text('101\n')

p = Path('app/server.py')
s = p.read_text()
old = '"rows": apply_team_overlay([dict(row) for row in rows[:8]]),'
new = '"rows": apply_team_overlay([dict(row) for row in rows]),'
if old not in s:
    raise SystemExit('preview API row cap anchor changed')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('app/static/data-source-v90.js')
s = p.read_text()
start = s.index('  function paintPreviewRows(rows){')
end = s.index('\n  async function runPreview(on_tv){', start)
replacement = '''  function paintPreviewRows(rows){
    const wrap=$("v79PreviewRows");
    // Keep the report table inside the phone viewport. The table itself stays
    // at its natural width; the user pans across it instead of Safari shrinking
    // the whole settings page to make every metric fit at once.
    wrap.style.minWidth="0";
    wrap.style.width="100%";
    wrap.style.maxWidth="100%";
    wrap.style.overflow="hidden";
    if(!rows||!rows.length){wrap.innerHTML="";return;}
    const stats=statList().filter(([key])=>rows.some(r=>
      Object.prototype.hasOwnProperty.call(r,key)
      && r[key]!==null && r[key]!==undefined && r[key]!==""));
    const head=["Rep","Team",...stats.map(([,label])=>label)];
    const num=v=>typeof v==="number"
      ? v.toLocaleString(undefined,{maximumFractionDigits:2}) : String(v??"");
    const body=rows.map(rep=>
      `<tr>${[esc(rep.rep_name||""),esc(rep.team||"")]
        .concat(stats.map(([key])=>esc(num(rep[key]))))
        .map(c=>`<td style="padding:6px 12px 6px 0;white-space:nowrap">${c}</td>`).join("")}</tr>`).join("");
    wrap.innerHTML=`<div class="v101-number-preview" style="box-sizing:border-box;width:100%;max-width:100%;max-height:55vh;overflow:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y">
      <table class="small" style="border-collapse:collapse;width:max-content;min-width:max-content;white-space:nowrap">
      <tr>${head.map(h=>`<th style="position:sticky;top:0;z-index:2;background:#111;text-align:left;padding:6px 12px 6px 0;white-space:nowrap">${esc(h)}</th>`).join("")}</tr>
      ${body}</table></div>`;
  }
'''
s = s[:start] + replacement + s[end:]
p.write_text(s)

p = Path('app/templates/settings.html')
s = p.read_text()
old = '<script src="/static/data-source-v90.js?v=100"></script>'
new = '<script src="/static/data-source-v90.js?v=101"></script>'
if old not in s:
    raise SystemExit('data source cache-buster anchor changed')
p.write_text(s.replace(old, new, 1))
