/* Windows Software version display.
   Kept separate from updater controls so version identity remains a small,
   reusable Software component when the settings frontend is restructured. */
(function(){
  const platform=String(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent||"");
  if(!/windows|win32|win64/i.test(platform))return;

  function softwareCard(){
    const anchor=document.getElementById("v107SoftwareManual")
      ||document.getElementById("softwareVersion")
      ||document.getElementById("checkGithub");
    return anchor?.closest(".card,.v98-inner-card")||null;
  }

  function install(){
    const card=softwareCard();
    if(!card)return false;
    if(document.getElementById("softwareVersionCurrent"))return true;

    const row=document.createElement("div");
    row.id="softwareVersionCurrent";
    row.style.cssText="margin:0 0 12px;font-weight:900";
    row.textContent="Software version: checking…";
    const heading=card.querySelector("h2");
    if(heading)heading.insertAdjacentElement("afterend",row);
    else card.prepend(row);

    fetch("/api/system/version",{cache:"no-store"})
      .then(r=>r.json().then(d=>({r,d})))
      .then(({r,d})=>{
        if(!r.ok||!d?.ok)throw new Error(d?.error||"version unavailable");
        row.textContent=`Software version: ${String(d.version||"unknown")}`;
      })
      .catch(()=>{row.textContent="Software version: unavailable";});
    return true;
  }

  let tries=0;(function attempt(){
    if(install())return;
    if(++tries<120)setTimeout(attempt,50);
  })();
})();
