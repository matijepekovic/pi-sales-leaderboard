/* v110: QR-only TV overlay with persistent size + free position controls. */
(function(){
  const DEFAULT={size:68,x:100,y:0};
  const LIMITS={min:36,max:180,margin:12};
  let state={...DEFAULT};
  let overlay=null;

  const clamp=(value,min,max)=>Math.min(max,Math.max(min,Number(value)||0));

  function mount(){
    if(document.getElementById('remoteQrV110')) return;

    const style=document.createElement('style');
    style.id='remoteQrV110Style';
    style.textContent=`
      #remoteQrV110{
        position:fixed;
        z-index:2147483000;
        box-sizing:border-box;
        padding:4px;
        border-radius:5px;
        background:rgba(255,255,255,.96);
        box-shadow:0 0 0 1px rgba(0,0,0,.20);
        line-height:0;
        pointer-events:none;
        user-select:none;
      }
      #remoteQrV110 img{display:block;height:auto}
    `;
    document.head.appendChild(style);

    overlay=document.createElement('div');
    overlay.id='remoteQrV110';
    overlay.setAttribute('aria-hidden','true');

    const image=document.createElement('img');
    image.alt='';
    image.draggable=false;
    image.src='/static/remote-qr-v109.svg?v=109';
    image.addEventListener('error',()=>{overlay.style.display='none';},{once:true});
    overlay.appendChild(image);
    document.body.appendChild(overlay);

    apply();
    refresh();
    setInterval(refresh,2000);
    window.addEventListener('resize',apply);
  }

  function apply(){
    if(!overlay) return;
    const image=overlay.querySelector('img');
    const size=Math.round(clamp(state.size,LIMITS.min,LIMITS.max));
    const x=clamp(state.x,0,100);
    const y=clamp(state.y,0,100);
    const pad=8;
    const total=size+pad;
    const margin=Math.min(LIMITS.margin,Math.max(4,Math.floor(Math.min(innerWidth,innerHeight)*.01)));
    const travelX=Math.max(0,innerWidth-total-margin*2);
    const travelY=Math.max(0,innerHeight-total-margin*2);
    overlay.style.left=`${Math.round(margin+travelX*x/100)}px`;
    overlay.style.top=`${Math.round(margin+travelY*y/100)}px`;
    image.style.width=`${size}px`;
  }

  async function refresh(){
    try{
      const response=await fetch('/api/config',{cache:'no-store'});
      if(!response.ok) return;
      const data=await response.json();
      const settings=data.settings||{};
      const next={
        size:clamp(settings.qr_overlay_size??DEFAULT.size,LIMITS.min,LIMITS.max),
        x:clamp(settings.qr_overlay_x??DEFAULT.x,0,100),
        y:clamp(settings.qr_overlay_y??DEFAULT.y,0,100)
      };
      if(next.size!==state.size||next.x!==state.x||next.y!==state.y){
        state=next;
        apply();
      }
    }catch(_){ }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
