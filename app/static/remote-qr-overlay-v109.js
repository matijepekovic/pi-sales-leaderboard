/* v109: small QR-only phone remote overlay. No board layout changes. */
(function(){
  function mount(){
    if(document.getElementById('remoteQrV109')) return;

    const style=document.createElement('style');
    style.id='remoteQrV109Style';
    style.textContent=`
      #remoteQrV109{
        position:fixed;
        top:clamp(12px,1.15vw,22px);
        right:clamp(12px,1.15vw,22px);
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
      #remoteQrV109 img{
        display:block;
        width:clamp(48px,3.4vw,68px);
        height:auto;
      }
    `;
    document.head.appendChild(style);

    const overlay=document.createElement('div');
    overlay.id='remoteQrV109';
    overlay.setAttribute('aria-hidden','true');

    const image=document.createElement('img');
    image.alt='';
    image.draggable=false;
    image.src='/static/remote-qr-v109.svg?v=109';
    image.addEventListener('error',()=>{overlay.style.display='none';},{once:true});

    overlay.appendChild(image);
    document.body.appendChild(overlay);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
