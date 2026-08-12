from pathlib import Path


def replace(path, old, new, label):
    p=Path(path); s=p.read_text()
    if old in s:
        s=s.replace(old,new,1)
    elif new not in s:
        raise SystemExit(f'{label} pattern not found in {path}')
    p.write_text(s)


# ----------------------------- theme persistence -----------------------------
p=Path('app/themes.py'); s=p.read_text()
anchor='''def _effective_corner_settings(config):
    stored = _clean_corner_settings(config.get("corner_settings"))
    return {
        key: {**DEFAULT_CORNER_SETTINGS, **stored.get(key, {})}
        for key in CORNER_ASSET_KEYS
    }
'''
addition='''def _effective_corner_settings(config):
    stored = _clean_corner_settings(config.get("corner_settings"))
    return {
        key: {**DEFAULT_CORNER_SETTINGS, **stored.get(key, {})}
        for key in CORNER_ASSET_KEYS
    }


def _clean_hero_scale(value):
    return _bounded_number(value, 100, 50, 200)


def _clean_row_stripe(incoming, colors=None):
    colors = colors if isinstance(colors, dict) else {}
    default_color = str(colors.get("primary") or "#d8b34a").lower()
    color = default_color
    strength = 0.0
    if isinstance(incoming, dict):
        candidate = str(incoming.get("color") or "").strip()
        if candidate and COLOR_RE.match(candidate):
            color = candidate.lower()
        strength = _bounded_number(incoming.get("strength"), 0, 0, 100)
    return {"color": color, "strength": strength}
'''
if anchor in s:s=s.replace(anchor,addition,1)
elif '_clean_hero_scale' not in s:raise SystemExit('theme helper anchor missing')
old='''        "assets": {},
        "corner_settings": _effective_corner_settings(config),
        "has_custom_assets": False,
'''
new='''        "assets": {},
        "corner_settings": _effective_corner_settings(config),
        "hero_scale": _clean_hero_scale(config.get("hero_scale")),
        "row_stripe": _clean_row_stripe(config.get("row_stripe"), colors),
        "has_custom_assets": False,
'''
if old in s:s=s.replace(old,new,1)
elif '"hero_scale": _clean_hero_scale' not in s:raise SystemExit('effective theme block missing')
old='''        "corner_controls": {
            "size": {"min": 50, "max": 600, "step": 5, "default": 100},
            "crop_x": {"min": 0, "max": 60, "step": 1, "default": 0},
            "crop_y": {"min": 0, "max": 60, "step": 1, "default": 0},
        },
'''
new='''        "corner_controls": {
            "size": {"min": 50, "max": 600, "step": 5, "default": 100},
            "crop_x": {"min": 0, "max": 60, "step": 1, "default": 0},
            "crop_y": {"min": 0, "max": 60, "step": 1, "default": 0},
        },
        "theme_controls": {
            "hero_scale": {"min": 50, "max": 200, "step": 5, "default": 100},
            "row_stripe_strength": {"min": 0, "max": 100, "step": 5, "default": 0},
        },
'''
if old in s:s=s.replace(old,new,1)
elif '"theme_controls"' not in s:raise SystemExit('manifest block missing')
old='''        existing_corners = _clean_corner_settings(current.get("corner_settings"))
        if isinstance(incoming.get("corner_settings"), dict):
            existing_corners.update(_clean_corner_settings(incoming.get("corner_settings")))
        current["corner_settings"] = existing_corners

        version = _set_config(settings, normalized_scope, team, current)
'''
new='''        existing_corners = _clean_corner_settings(current.get("corner_settings"))
        if isinstance(incoming.get("corner_settings"), dict):
            existing_corners.update(_clean_corner_settings(incoming.get("corner_settings")))
        current["corner_settings"] = existing_corners
        current["hero_scale"] = _clean_hero_scale(
            incoming.get("hero_scale", current.get("hero_scale"))
        )
        current["row_stripe"] = _clean_row_stripe(
            incoming.get("row_stripe", current.get("row_stripe")),
            current.get("colors"),
        )

        version = _set_config(settings, normalized_scope, team, current)
'''
if old in s:s=s.replace(old,new,1)
elif 'current["hero_scale"]' not in s:raise SystemExit('save theme block missing')
old='''            "colors": dict(CLASSIC_COLORS),
            "assets": {},
            "corner_settings": {},
        }
'''
new='''            "colors": dict(CLASSIC_COLORS),
            "assets": {},
            "corner_settings": {},
            "hero_scale": 100.0,
            "row_stripe": {"color": CLASSIC_COLORS["primary"], "strength": 0.0},
        }
'''
if old in s:s=s.replace(old,new,1)
elif '"hero_scale": 100.0' not in s:raise SystemExit('reset config block missing')
p.write_text(s)

# ------------------------------- Theme Studio -------------------------------
p=Path('app/static/theme-studio.js'); s=p.read_text()
old='''          <section class="td-sec">
            <h3>Colors</h3>
            <div id="tdColors" class="td-colors"></div>
          </section>

          <section class="td-sec">
            <h3>Team Logo</h3>
'''
new='''          <section class="td-sec">
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
'''
if old in s:s=s.replace(old,new,1)
elif 'id="tdHeroScale"' not in s:raise SystemExit('Theme Studio details insertion failed')
old='''    byId("tdPreset").addEventListener("change",presetChanged);
    byId("tdEnabled").addEventListener("change",()=>{saveTheme(true);});
    byId("tdSave").addEventListener("click",()=>saveTheme(false));
'''
new='''    byId("tdPreset").addEventListener("change",presetChanged);
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
'''
if old in s:s=s.replace(old,new,1)
elif 'tdHeroScale").addEventListener' not in s:raise SystemExit('Theme Studio listeners insertion failed')
old='''    renderColors(theme.colors||CLASSIC);
    renderLogo();
'''
new='''    renderColors(theme.colors||CLASSIC);
    renderThemeDetails(theme);
    renderLogo();
'''
if old in s:s=s.replace(old,new,1)
elif 'renderThemeDetails(theme);' not in s:raise SystemExit('renderAll insertion failed')
anchor='''  const currentColors=()=>{
    const out={};
    document.querySelectorAll(".tdColorInput").forEach(i=>out[i.dataset.colorKey]=i.value);
    return out;
  };

  function presetChanged(){
'''
addition='''  const currentColors=()=>{
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
'''
if anchor in s:s=s.replace(anchor,addition,1)
elif 'function renderThemeDetails' not in s:raise SystemExit('renderThemeDetails insertion failed')
old='''        body:JSON.stringify({base:byId("tdPreset").value,enabled:byId("tdEnabled").checked,colors:currentColors()})
'''
new='''        body:JSON.stringify({
          base:byId("tdPreset").value,
          enabled:byId("tdEnabled").checked,
          colors:currentColors(),
          hero_scale:clamp(num(byId("tdHeroScale")?.value,100),50,200),
          row_stripe:{
            color:byId("tdStripeColor")?.value||"#d8b34a",
            strength:clamp(num(byId("tdStripeStrength")?.value,0),0,100)
          }
        })
'''
if old in s:s=s.replace(old,new,1)
elif 'hero_scale:clamp' not in s:raise SystemExit('saveTheme payload insertion failed')
p.write_text(s)

# -------------------------- per-team space-filling rows ----------------------
p=Path('app/static/themed-team-layout.js'); s=p.read_text()
s=s.replace('flex:1 1 0;min-height:44px;max-height:82px;', 'flex:1 1 0;min-height:0;max-height:none;', 1)
s=s.replace('flex-grow:1.18;min-height:58px;max-height:100px;', 'flex:1.18 1 0;min-height:0;max-height:none;', 1)
s=s.replace('flex-grow:1;min-height:44px;max-height:82px;', 'flex:1 1 0;min-height:0;max-height:none;', 1)
old='''    if(display.rows.length>=9) root.classList.add("very-dense");
    else if(display.rows.length>=7) root.classList.add("dense");
'''
if old in s:s=s.replace(old,'',1)
elif 'root.classList.add("very-dense")' in s:raise SystemExit('density assignment mismatch')
p.write_text(s)

# -------------------------- Whole Office dynamic sizing ---------------------
p=Path('app/static/broadcast-views-v55.js'); s=p.read_text()
s=s.replace('const comparisonModes=new Set(["team_vs_team","all_teams"]);','const comparisonModes=new Set();',1)
s=s.replace('width:min(70vw,1080px);height:100%;','width:min(78vw,1680px);height:100%;',1)
old='''    const rowCount=Math.max(display.rows.length,1);
    const brandHeight=rowCount>=14?112:rowCount>=10?132:rowCount>=7?160:220;
    const available=Math.max(300,window.innerHeight-brandHeight-30-48-34);
    const rowHeight=Math.max(25,Math.min(68,Math.floor(available/(rowCount+(rowCount?0.18:0)))));
    root.style.setProperty("--v55-office-brand-h",`${brandHeight}px`);
    root.style.setProperty("--v55-office-row-h",`${rowHeight}px`);
'''
new='''    const rowCount=Math.max(display.rows.length,1);
    const heroScale=Math.max(.5,Math.min(2,Number(theme.hero_scale||100)/100));
    // v67 Whole Office used a 19vh hero at this TV size. Keep that 100%
    // baseline, then let the theme multiplier own artwork size while rows take
    // every remaining pixel.
    const baseBrandHeight=Math.max(190,Math.min(420,window.innerHeight*.19));
    const brandHeight=baseBrandHeight*heroScale;
    const available=Math.max(120,window.innerHeight-brandHeight-30-48-20);
    const rowHeight=Math.max(12,available/(rowCount+(rowCount?0.18:0)));
    root.style.setProperty("--v55-office-brand-h",`${brandHeight.toFixed(2)}px`);
    root.style.setProperty("--v55-office-row-h",`${rowHeight.toFixed(2)}px`);
'''
if old in s:s=s.replace(old,new,1)
elif 'const heroScale=Math.max(.5' not in s:raise SystemExit('office sizing block mismatch')
p.write_text(s)

# ----------------------------- corner runtime -------------------------------
p=Path('app/static/theme-corner-runtime-v60.js'); s=p.read_text()
old='''    if(data.mode==="team_vs_team"||data.mode==="all_teams"){
      document.querySelectorAll(".v55-team-card").forEach(card=>{
        const name=String(card.dataset.team||"").trim();
        applySet(card,".v55-card-corner",themeFor(data,name,null));
      });
    }
'''
new='''    if(data.mode==="team_vs_team"||data.mode==="all_teams"){
      document.querySelectorAll(".v69-team-card").forEach(card=>{
        const name=String(card.dataset.team||"").trim();
        const teamId=Number(card.dataset.teamId||0)||null;
        applySet(card,".v69-corner",themeFor(data,name,teamId));
      });
    }
'''
if old in s:s=s.replace(old,new,1)
elif '.v69-team-card' not in s:raise SystemExit('corner comparison block mismatch')
p.write_text(s)

# ------------------------------- script stack -------------------------------
p=Path('app/templates/display.html'); s=p.read_text()
s=s.replace('themed-team-layout.js?v=49','themed-team-layout.js?v=69')
s=s.replace('comparison-team-cards-v53.js?v=53','comparison-team-cards-v53.js?v=69')
s=s.replace('broadcast-views-v55.js?v=55','broadcast-views-v55.js?v=69')
s=s.replace('<script src="/static/whole-office-scale-v56.js?v=56"></script>\n','')
s=s.replace('theme-corner-runtime-v60.js?v=64','theme-corner-runtime-v60.js?v=69')
anchor='<script src="/static/theme-corner-runtime-v60.js?v=69"></script>\n'
if 'theme-extras-v69.js' not in s:
    if anchor not in s:raise SystemExit('display extras anchor missing')
    s=s.replace(anchor,anchor+'<script src="/static/theme-extras-v69.js?v=69"></script>\n',1)
p.write_text(s)

p=Path('app/templates/settings.html'); s=p.read_text().replace('theme-studio.js?v=68','theme-studio.js?v=69'); p.write_text(s)
Path('VERSION').write_text('69\n')
