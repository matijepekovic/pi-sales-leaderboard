from pathlib import Path

p=Path('app/static/theme-studio.js')
s=p.read_text()
s=s.replace('const MIN_SIZE=50,MAX_SIZE=250,MAX_CROP=60;', 'const MIN_SIZE=50,MAX_SIZE=600,MAX_CROP=60;\n  const MIN_ZOOM=1,MAX_ZOOM=4,MIN_PINCH_DIST=4;')
old='''  function clampPan(){
    const stage=byId("tdStage");
    if(!stage)return;
    const fit=fitScale();
    const w=geometry.width*fit*zoomFactor, h=geometry.height*fit*zoomFactor;
    const maxX=Math.max(0,w-stage.clientWidth), maxY=Math.max(0,h-stage.clientHeight);
    panX=clamp(panX,-maxX,0);
    panY=clamp(panY,-maxY,0);
  }

  function setZoom(next,originX,originY){
    const before=zoomFactor;
    zoomFactor=clamp(next,1,6);
    if(originX!==undefined){
      // Zoom about the point under the fingers rather than the top-left.
      const ratio=zoomFactor/before;
      panX=originX-(originX-panX)*ratio;
      panY=originY-(originY-panY)*ratio;
    }
    if(zoomFactor===1){panX=0;panY=0;}
    layoutPreview();
  }
'''
new='''  function clampPan(){
    const stage=byId("tdStage");
    if(!stage)return;
    if(!Number.isFinite(zoomFactor)||zoomFactor<MIN_ZOOM||zoomFactor>MAX_ZOOM)zoomFactor=MIN_ZOOM;
    if(!Number.isFinite(panX))panX=0;
    if(!Number.isFinite(panY))panY=0;
    const fit=fitScale();
    if(!Number.isFinite(fit)||fit<=0){panX=0;panY=0;return;}
    const w=geometry.width*fit*zoomFactor, h=geometry.height*fit*zoomFactor;
    const maxX=Math.max(0,Number.isFinite(w)?w-stage.clientWidth:0);
    const maxY=Math.max(0,Number.isFinite(h)?h-stage.clientHeight:0);
    panX=clamp(panX,-maxX,0);
    panY=clamp(panY,-maxY,0);
  }

  function setZoom(next,originX,originY){
    const before=Number.isFinite(zoomFactor)&&zoomFactor>=MIN_ZOOM&&zoomFactor<=MAX_ZOOM?zoomFactor:MIN_ZOOM;
    const candidate=Number(next);
    zoomFactor=Number.isFinite(candidate)?clamp(candidate,MIN_ZOOM,MAX_ZOOM):before;
    if(Number.isFinite(originX)&&Number.isFinite(originY)&&before>0){
      const ratio=zoomFactor/before;
      if(Number.isFinite(ratio)){
        panX=originX-(originX-(Number.isFinite(panX)?panX:0))*ratio;
        panY=originY-(originY-(Number.isFinite(panY)?panY:0))*ratio;
      }
    }
    if(!Number.isFinite(panX))panX=0;
    if(!Number.isFinite(panY))panY=0;
    if(zoomFactor===MIN_ZOOM){panX=0;panY=0;}
    layoutPreview();
  }
'''
if old in s:s=s.replace(old,new)
elif new not in s:raise SystemExit('zoom block mismatch')
old='''    stage.addEventListener("pointerdown",e=>{
      stage.setPointerCapture(e.pointerId);
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size===2){
        const p=[...points.values()];
        startDist=dist(p);startZoom=zoomFactor;startMid=mid(p);
        panning=false;
      }else if(points.size===1){
'''
new='''    stage.addEventListener("pointerdown",e=>{
      try{stage.setPointerCapture(e.pointerId);}catch(_e){}
      if(!Number.isFinite(e.clientX)||!Number.isFinite(e.clientY))return;
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size===2){
        const p=[...points.values()];
        const measured=dist(p);
        startDist=Number.isFinite(measured)&&measured>=MIN_PINCH_DIST?measured:0;
        startZoom=Number.isFinite(zoomFactor)?zoomFactor:MIN_ZOOM;
        startMid=startDist?mid(p):null;
        if(startMid&&(!Number.isFinite(startMid.x)||!Number.isFinite(startMid.y))){startDist=0;startMid=null;}
        panning=false;
      }else if(points.size===1){
'''
if old in s:s=s.replace(old,new)
elif new not in s:raise SystemExit('pointerdown block mismatch')
old='''    stage.addEventListener("pointermove",e=>{
      if(!points.has(e.pointerId))return;
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size>=2&&startDist){
        const p=[...points.values()].slice(0,2);
        setZoom(startZoom*(dist(p)/startDist),startMid.x,startMid.y);
      }else if(panning){
        panX+=e.clientX-lastX;panY+=e.clientY-lastY;
        lastX=e.clientX;lastY=e.clientY;
        layoutPreview();
      }
    });
'''
new='''    stage.addEventListener("pointermove",e=>{
      if(!points.has(e.pointerId))return;
      if(!Number.isFinite(e.clientX)||!Number.isFinite(e.clientY))return;
      points.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(points.size>=2&&startDist>=MIN_PINCH_DIST&&startMid){
        const p=[...points.values()].slice(0,2);
        const measured=dist(p);
        if(Number.isFinite(measured)&&measured>=MIN_PINCH_DIST)setZoom(startZoom*(measured/startDist),startMid.x,startMid.y);
      }else if(panning){
        const dx=e.clientX-lastX,dy=e.clientY-lastY;
        if(Number.isFinite(dx)&&Number.isFinite(dy)){panX+=dx;panY+=dy;}
        lastX=e.clientX;lastY=e.clientY;
        layoutPreview();
      }
    });
'''
if old in s:s=s.replace(old,new)
elif new not in s:raise SystemExit('pointermove block mismatch')
p.write_text(s)

p=Path('app/themes.py');s=p.read_text()
s=s.replace('_bounded_number(raw.get("size"), 100, 50, 250)','_bounded_number(raw.get("size"), 100, 50, 600)')
s=s.replace('"size": {"min": 50, "max": 250, "step": 5, "default": 100}','"size": {"min": 50, "max": 600, "step": 5, "default": 100}')
p.write_text(s)
p=Path('app/templates/settings.html');p.write_text(p.read_text().replace('theme-studio.js?v=67','theme-studio.js?v=68'))
Path('VERSION').write_text('68\n')
