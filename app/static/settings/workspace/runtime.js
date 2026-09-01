export const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

export async function request(url,options={}){
  const headers={...(options.headers||{})};
  if(options.body && !(options.body instanceof FormData) && !headers["Content-Type"])headers["Content-Type"]="application/json";
  const response=await fetch(url,{cache:"no-store",...options,headers});
  const data=await response.json().catch(()=>({}));
  if(!response.ok||data.ok===false){const error=new Error(data.error||`Request failed (${response.status})`);error.status=response.status;error.payload=data;throw error;}
  return data;
}

export const json=(method,body)=>({method,body:JSON.stringify(body||{})});

export function table(fields,rows,limit=20){
  const visible=(rows||[]).slice(0,limit);
  if(!(fields||[]).length)return '<div class="empty">No fields yet.</div>';
  return `<div class="table-wrap"><table><thead><tr>${fields.map(field=>`<th>${esc(field.label||field.key)}</th>`).join("")}</tr></thead><tbody>${visible.map(row=>`<tr>${fields.map(field=>`<td>${esc(row?.[field.key]??"")}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${fields.length}">No rows.</td></tr>`}</tbody></table></div>`;
}

export function debounce(fn,delay=250){let timer=null;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay);};}
