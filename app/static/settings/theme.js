/* Shared visual editor. Saves always go to the selected resource owner. */
(function(){
  const R=window.StatsSettings,$=id=>document.getElementById(id),esc=R.esc;
  const S={id:"",owner:"screen",manifest:{},theme:{},baseline:{},appearance:{},library:{},themes:[],widgets:[],preview:null,previewOptions:null,message:""};
  const clone=value=>JSON.parse(JSON.stringify(value??{}));
  const overlay=() => $("screenThemeOverlay");
  const endpoint=()=>S.owner==="group"?`/api/groups/${encodeURIComponent(S.id)}/appearance`:S.owner==="theme"?`/api/themes/${encodeURIComponent(S.id)}`:`/api/screen-themes/${encodeURIComponent(S.id)}`;
  const assetEndpoint=key=>`${S.owner==="group"?`/api/group-themes/${encodeURIComponent(S.id)}`:endpoint()}/assets/${encodeURIComponent(key)}`;

  async function loadPreview(){
    if(S.previewOptions?.widget){
      const response=await R.api("/api/widgets/preview",R.json("POST",{widget:S.previewOptions.widget,context:S.previewOptions.context||{}}));
      return {sections:[response.payload]};
    }
    if(S.previewOptions?.screen)return (await R.api("/api/screens/preview",R.json("POST",S.previewOptions.screen))).payload;
    if(S.previewOptions?.screen_id)return (await R.api(`/api/screens/${encodeURIComponent(S.previewOptions.screen_id)}/preview`)).payload;
    if(S.owner==="screen")return (await R.api(`/api/screens/${encodeURIComponent(S.id)}/preview`)).payload;
    return {sections:[]};
  }

  async function load(id,owner="screen",options=null){
    S.id=String(id||"");S.owner=owner;S.previewOptions=options;S.message="";
    const themePath=owner==="group"?`/api/group-themes/${encodeURIComponent(id)}`:owner==="theme"||owner==="preview"?`/api/themes/${encodeURIComponent(id||"starter")}`:endpoint();
    const [response,library,themes,widgets]=await Promise.all([R.api(themePath),R.api("/api/asset-library"),R.api("/api/themes"),R.api("/api/widgets")]);
    S.manifest=response.manifest||{};S.theme=response.theme||{};S.baseline=clone(S.theme);S.appearance=response.appearance||{theme_id:S.theme.theme_id||"starter",style:{},asset_bindings:{},widget_styles:{}};
    S.library=library.items||{};S.themes=themes.themes||[];S.widgets=widgets.widgets||[];S.preview=await loadPreview();
  }

  function colors(){return `<div class="grid">${(S.manifest.colors||[]).map(color=>`<div><label>${esc(color.label)}</label><input type="color" data-color="${esc(color.key)}" value="${esc(S.theme.colors?.[color.key]||"#000000")}"></div>`).join("")}</div>`;}
  function assets(){return `<div class="stack">${(S.manifest.assets||[]).map(asset=>{
    const items=S.library[asset.key]||[],url=S.theme.assets?.[asset.key];
    return `<div class="subcard"><div class="toolbar"><strong>${esc(asset.label)}</strong>${url?`<img src="${esc(url)}" alt="" style="width:90px;height:52px;object-fit:contain">`:""}</div><div class="grid"><div><label>Saved Asset</label><select data-library="${esc(asset.key)}"><option value="">Choose…</option>${items.map(item=>`<option value="${esc(item.id)}">${esc(item.label||item.id)}</option>`).join("")}</select></div><div><label>Upload</label><input type="file" accept="image/png,image/jpeg,image/webp" data-upload="${esc(asset.key)}"></div></div><div class="row"><button class="btn" data-action="apply" data-key="${esc(asset.key)}">Apply Saved</button><button class="btn" data-action="upload" data-key="${esc(asset.key)}">Upload & Apply</button><button class="btn" data-action="remove" data-key="${esc(asset.key)}">Use Theme default</button></div></div>`;
  }).join("")}</div>`;}

  function visualPreview(){
    const renderer=window.StatsWidgetRenderer,sections=S.preview?.sections||[];
    const chooser=`<label>Preview Widget</label><select data-preview-widget><option value="">Current data</option>${S.widgets.map(widget=>`<option value="${esc(widget.id)}" ${S.previewOptions?.widget?.id===widget.id?"selected":""}>${esc(widget.name)}</option>`).join("")}</select>`;
    if(!sections.length)return `<div class="card">${chooser}<p>Choose a Widget to preview its real data.</p></div>`;
    const content=sections.map(section=>{
      const specific=S.appearance.widget_styles?.[section.widget_id]||{},theme={...S.theme,colors:{...S.theme.colors,...specific.colors}};
      return `<div data-theme-preview style="height:420px;margin-top:14px;${renderer?.themeStyle(theme)||""}">${renderer?renderer.render(section,{theme,fit:{rows:10,...specific}}):'<p>Widget renderer is unavailable.</p>'}</div>`;
    }).join("");
    const refinement=S.owner==="group"&&S.previewOptions?.widget?`<div class="subcard"><strong>Appearance for ${esc(S.previewOptions.widget.name)}</strong><div class="grid"><div><label>Font size</label><input type="number" min="0" max="300" data-widget-style="font_size" value="${Number(S.appearance.widget_styles?.[S.previewOptions.widget.id]?.font_size||20)}"></div><div><label>Padding</label><input type="number" min="0" max="300" data-widget-style="padding" value="${Number(S.appearance.widget_styles?.[S.previewOptions.widget.id]?.padding??8)}"></div></div></div>`:"";
    return `<div class="card">${chooser}${refinement}${content}</div>`;
  }

  function render(){
    const root=overlay();if(!root)return;
    const previewOnly=S.owner==="preview",title=previewOnly?"Theme Preview":S.owner==="group"?"Group Theme & Assets":S.owner==="theme"?"Reusable Theme":"Screen Theme";
    const themeSelect=`<label>${S.owner==="group"?"Group Theme":"Preview Theme"}</label><select data-theme-choice>${S.themes.map(theme=>`<option value="${esc(theme.id)}" ${String(S.appearance.theme_id||S.theme.theme_id||"starter")===String(theme.id)?"selected":""}>${esc(theme.name)}</option>`).join("")}</select>`;
    root.innerHTML=`<div class="panel theme-editor-panel"><div class="toolbar"><div><h2>${title}</h2><div class="small">${previewOnly?"Real data. Preview changes are not saved.":S.owner==="group"?"Theme choices, assets and refinements are saved to this Group.":"Visual design is saved through the Theme owner."}</div></div><button class="btn" data-action="close">Close</button></div><div class="theme-editor-grid"><div><div class="subcard">${S.owner!=="screen"?themeSelect:""}${!previewOnly?`<h3>Colors</h3>${colors()}<div class="grid"><div><label>Hero scale</label><input type="number" data-visual="hero_scale" min="50" max="200" value="${Number(S.theme.hero_scale||100)}"></div><div><label>Row accent strength</label><input type="number" data-stripe-strength min="0" max="100" value="${Number(S.theme.row_stripe?.strength||0)}"></div><div><label>Row accent</label><input type="color" data-stripe-color value="${esc(S.theme.row_stripe?.color||S.theme.colors?.primary||"#d8b34a")}"></div></div><div class="row"><button class="btn primary" data-action="save">${S.owner==="group"?"Save Group Style":"Save Theme"}</button><button class="btn" data-action="save-new">Save as new Theme</button>${S.owner==="group"||S.owner==="screen"?'<button class="btn" data-action="reset">Reset style</button>':!['starter','classic'].includes(S.id)?'<button class="btn danger" data-action="delete-theme">Delete Theme</button>':""}</div>`:""}</div>${!previewOnly?`<div class="card"><h3>Assets</h3>${assets()}</div>`:""}<div class="status">${esc(S.message)}</div></div>${visualPreview()}</div></div>`;
    bind();requestAnimationFrame(()=>window.StatsWidgetRenderer?.fit(root));
  }

  function sync(){
    const root=overlay();if(!root||S.owner==="preview")return;
    root.querySelectorAll("[data-color]").forEach(input=>S.theme.colors[input.dataset.color]=input.value);
    S.theme.hero_scale=Number(root.querySelector('[data-visual="hero_scale"]')?.value||100);
    S.theme.row_stripe={strength:Number(root.querySelector("[data-stripe-strength]")?.value||0),color:root.querySelector("[data-stripe-color]")?.value||S.theme.colors.primary};
    if(S.owner==="group"){
      const style=S.appearance.style||{};
      for(const [key,value] of Object.entries(S.theme.colors||{}))if(value!==S.baseline.colors?.[key])style.colors={...style.colors,[key]:value};
      for(const key of ["hero_scale","row_stripe"])if(JSON.stringify(S.theme[key])!==JSON.stringify(S.baseline[key]))style[key]=clone(S.theme[key]);
      S.appearance.style=style;
      root.querySelectorAll("[data-widget-style]").forEach(input=>{if(!input.dataset.dirty)return;const id=S.previewOptions.widget.id;S.appearance.widget_styles[id]={...S.appearance.widget_styles[id],[input.dataset.widgetStyle]:Number(input.value)};});
    }
  }
  async function resolveDraft(){const response=await R.api("/api/themes/preview",R.json("POST",{group_id:S.owner==="group"?S.id:"",appearance:S.appearance}));S.theme=response.theme;S.baseline=clone(S.theme);}
  async function save(){sync();const body=S.owner==="group"?S.appearance:{...S.theme,name:S.theme.name||"Custom Theme",asset_bindings:S.theme.effective_asset_bindings||S.theme.asset_bindings||{}};const response=await R.api(endpoint(),R.json("PUT",body));S.theme=response.theme;S.baseline=clone(S.theme);S.message="Saved.";R.emit("theme-changed",{owner:S.owner,id:S.id});render();}
  async function saveNew(){sync();const name=prompt("Theme name");if(!name?.trim())return;const response=await R.api("/api/themes",R.json("POST",{...S.theme,id:undefined,name:name.trim(),asset_bindings:S.theme.effective_asset_bindings||{},copy_from:{owner:S.owner,id:S.id}}));if(S.owner==="group"){S.appearance.theme_id=response.definition.id;S.appearance.style={};S.appearance.asset_bindings={};await resolveDraft();S.themes=(await R.api("/api/themes")).themes;S.message="Reusable Theme created. Save Group Style to assign it.";render();}else await openTheme(response.definition.id,S.previewOptions);R.emit("theme-changed");}
  async function assetAction(action,key){sync();let request;if(action==="remove")request={method:"DELETE"};else if(action==="apply"){const id=overlay().querySelector(`[data-library="${key}"]`).value;if(!id)throw new Error("Choose a saved asset.");request=R.json("POST",{library_id:id});}else{const file=overlay().querySelector(`[data-upload="${key}"]`).files[0];if(!file)throw new Error("Choose an image.");const form=new FormData();form.append("asset",file);request={method:"POST",body:form};}const response=await R.api(assetEndpoint(key),request);if(S.owner==="group"){const persisted=(await R.api(`/api/groups/${encodeURIComponent(S.id)}/appearance`)).appearance;S.appearance.asset_bindings=persisted.asset_bindings;await resolveDraft();}else S.theme=response.theme;S.library=(await R.api("/api/asset-library")).items;S.message="Asset saved.";R.emit("theme-changed",{owner:S.owner,id:S.id});render();}
  async function reset(){if(!confirm("Reset these saved style choices?"))return;if(S.owner==="group"){S.appearance={theme_id:S.appearance.theme_id,asset_bindings:{},style:{},widget_styles:{}};await R.api(endpoint(),R.json("PUT",S.appearance));await resolveDraft();}else S.theme=(await R.api(endpoint(),{method:"DELETE"})).theme;S.baseline=clone(S.theme);R.emit("theme-changed");render();}
  function close(){const root=overlay();root?.classList.remove("open");root?.setAttribute("aria-hidden","true");if(root)root.innerHTML="";}
  async function attempt(fn){try{await fn();}catch(error){S.message=error.message;render();}}
  function bind(){
    const root=overlay();
    root.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>attempt(async()=>{const action=button.dataset.action,key=button.dataset.key;if(action==="close")close();else if(action==="save")await save();else if(action==="save-new")await saveNew();else if(action==="reset")await reset();else if(action==="delete-theme"){if(confirm("Delete this reusable Theme?")){await R.api(endpoint(),{method:"DELETE"});R.emit("theme-changed");close();}}else await assetAction(action,key);})));
    root.querySelectorAll("[data-color],[data-visual],[data-stripe-strength],[data-stripe-color]").forEach(input=>input.addEventListener("change",()=>{sync();render();}));
    root.querySelectorAll("[data-widget-style]").forEach(input=>input.addEventListener("change",()=>{input.dataset.dirty="true";sync();render();}));
    root.querySelector("[data-theme-choice]")?.addEventListener("change",event=>attempt(async()=>{sync();S.appearance.theme_id=event.target.value;if(S.owner==="theme")return openTheme(event.target.value,S.previewOptions);await resolveDraft();render();}));
    root.querySelector("[data-preview-widget]")?.addEventListener("change",event=>attempt(async()=>{sync();const widget=S.widgets.find(item=>item.id===event.target.value);S.previewOptions=widget?{widget,context:S.owner==="group"?{group_ids:[S.id]}:{}}:null;S.preview=await loadPreview();render();}));
  }
  async function show(id,owner,options){await load(id,owner,options);render();overlay().classList.add("open");overlay().setAttribute("aria-hidden","false");}
  async function open(id){const response=await R.api(`/api/screens/${encodeURIComponent(id)}/preview`),theme=response.payload?.theme||{};if(theme.group_id)return show(theme.group_id,"group",{screen_id:id});if(theme.theme_id)return show(theme.theme_id,"theme",{screen_id:id});return show(id,"screen");}
  async function openGroup(id,options=null){return show(id,"group",options);}
  async function openTheme(id,options=null){return show(id,"theme",options);}
  async function preview(options){await show(options.theme_id||"starter","preview",options);if(options.theme_group_id){const data=await R.api(`/api/group-themes/${encodeURIComponent(options.theme_group_id)}`);S.theme=data.theme;render();}}
  window.StatsThemeManager=Object.freeze({open,openGroup,openTheme,preview});
})();
