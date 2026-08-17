/* v83: searchable Tableau workbook/sheet picker.

   Presentation-only companion to source-picker-v79.js. It does not change
   discovery, pulling, parsing, mapping, previewing, saving, or the default
   source. It only filters the workbook and sheet options that the existing
   picker already loaded from Tableau.
*/
(function(){
  const SPECS=[
    {selectId:"v79Workbook", inputId:"v83WorkbookSearch", noteId:"v83WorkbookSearchCount",
     placeholder:"Search workbooks…", noun:"workbooks"},
    {selectId:"v79Sheet", inputId:"v83SheetSearch", noteId:"v83SheetSearchCount",
     placeholder:"Search sheets…", noun:"sheets"}
  ];

  const norm=value=>String(value||"").trim().toLowerCase();

  function applyFilter(spec,select,input,note){
    const query=norm(input.value);
    let matches=0;
    Array.from(select.options||[]).forEach(option=>{
      if(!option.value){
        option.hidden=false;
        option.disabled=false;
        return;
      }
      const haystack=norm(`${option.textContent||""} ${option.value||""}`);
      const hit=!query||haystack.includes(query);
      if(hit) matches+=1;
      // Never hide/disable the current choice just because the search text
      // changed. Searching is only for finding an option, not changing one.
      const keep=hit||option.selected;
      option.hidden=!keep;
      option.disabled=!keep;
    });
    note.textContent=query
      ? `${matches} matching ${spec.noun}`
      : "";
  }

  function install(spec){
    const select=document.getElementById(spec.selectId);
    if(!select||select.tagName!=="SELECT") return false;
    if(document.getElementById(spec.inputId)) return true;

    const input=document.createElement("input");
    input.id=spec.inputId;
    input.type="search";
    input.placeholder=spec.placeholder;
    input.autocomplete="off";
    input.setAttribute("aria-label",spec.placeholder.replace("…",""));
    input.style.width="100%";
    input.style.boxSizing="border-box";
    input.style.margin="0 0 5px";

    const note=document.createElement("div");
    note.id=spec.noteId;
    note.className="small";
    note.style.opacity=".65";
    note.style.minHeight="1em";
    note.style.margin="0 0 4px";

    select.parentNode.insertBefore(input,select);
    select.parentNode.insertBefore(note,select);

    const apply=()=>applyFilter(spec,select,input,note);
    input.addEventListener("input",apply);
    input.addEventListener("search",apply);
    new MutationObserver(apply).observe(select,{childList:true,subtree:true});
    apply();

    // A sheet search belongs to the workbook it was typed against. Clear it
    // when the existing picker switches workbooks and loads another sheet list.
    if(spec.selectId==="v79Workbook"){
      select.addEventListener("change",()=>{
        const sheetSearch=document.getElementById("v83SheetSearch");
        if(!sheetSearch) return;
        sheetSearch.value="";
        sheetSearch.dispatchEvent(new Event("input"));
      });
    }
    return true;
  }

  function mount(){
    SPECS.forEach(install);
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>setTimeout(mount,0));
  }else{
    setTimeout(mount,0);
  }

  // source-picker-v79 mounts on a zero-delay timer and may replace its two
  // selects with typed inputs when Tableau enumeration is unavailable. Watch
  // only long enough to install alongside real selects; typed fallback is left
  // completely alone.
  const observer=new MutationObserver(mount);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(()=>observer.disconnect(),10000);
})();
