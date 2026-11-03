// Screencast of the simulator UI: a visible cursor moves to each control and changes it; the rotor
// responds live. Real time, recorded by Playwright, then converted to mp4 by ffmpeg.
// usage: node screencast.js <sim.html> <outdir> [assets_dir]
//
// Storyboard (persist_ms is the viewer's eye; spin_slowdown is "the divisor"):
//   grid, 2 blades, 1 strip, divisor 250: LEDs chasing -> divisor down to 1: POV makes the grid appear
//   rings -> divisor up a little: flicker -> text -> divisor 1: clear
//   retriever photo -> each gif: divisor up (fades) and back down (returns)
//   faded state: strips 1->2, blades 3, 4, back to 2, strips 3, 4, blades 3, 4: more blades need less rpm
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const [,,sim,out,assets='assets']=process.argv;fs.mkdirSync(out,{recursive:true});
const W=1400,H=860;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

(async()=>{
  const b=await chromium.launch();
  const ctx=await b.newContext({viewport:{width:W,height:H},recordVideo:{dir:out,size:{width:W,height:H}}});
  const p=await ctx.newPage();p.on('pageerror',e=>console.log('ERR',e.message));
  // start state is in place before the first frame: 2 blades, 1 strip, slow, human eye, grid
  await p.addInitScript(()=>{window.POVD_INIT={blades:2,blade_len_mm:550,strips_per_blade:1,rpm:500,spin_slowdown:250,persist_ms:60,spin:true}});
  await p.goto('file://'+path.resolve(sim));await p.waitForTimeout(500);
  await p.evaluate(()=>{const c=document.createElement('div');c.id='cur';
    c.style.cssText='position:fixed;left:0;top:0;width:22px;height:30px;pointer-events:none;z-index:9999;transition:transform .08s';
    c.innerHTML='<svg viewBox="0 0 22 30" width="22" height="30"><path d="M2 2 L2 24 L8 18 L12 28 L16 26 L12 17 L20 17 Z" fill="#fff" stroke="#000" stroke-width="1.5"/></svg>';
    document.body.appendChild(c);
    document.addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'});
    document.addEventListener('mousedown',()=>c.style.transform='scale(.8)');
    document.addEventListener('mouseup',()=>c.style.transform='');});
  let mx=W/2,my=H/2;
  async function moveTo(x,y,ms=450){const steps=Math.max(8,Math.round(ms/16));
    for(let i=1;i<=steps;i++){const u=i/steps,e=u<.5?2*u*u:1-Math.pow(-2*u+2,2)/2;await p.mouse.move(mx+(x-mx)*e,my+(y-my)*e);await sleep(ms/steps)}mx=x;my=y}
  async function field(id,val,hold=1200){
    const bb=await p.locator('#'+id).boundingBox();await moveTo(bb.x+bb.width*0.6,bb.y+bb.height/2);
    await p.mouse.down();await sleep(60);await p.mouse.up();await p.keyboard.press('Control+A');await sleep(100);
    await p.keyboard.type(String(val),{delay:80});await sleep(100);await p.keyboard.press('Tab');await sleep(hold)}
  async function click(id,hold=1500){const bb=await p.locator('#'+id).boundingBox();await moveTo(bb.x+bb.width/2,bb.y+bb.height/2);
    await p.mouse.down();await sleep(60);await p.mouse.up();await sleep(hold)}
  async function file(name,hold=3000){const bb=await p.locator('#img').boundingBox();await moveTo(bb.x+30,bb.y+bb.height/2);
    await p.mouse.down();await sleep(60);await p.mouse.up();await p.setInputFiles('#img',path.join(assets,name));await sleep(hold)}
  const park=async(hold=0)=>{await moveTo(360,H-120,350);await sleep(hold)};
  const divisor=async(list,hold=1500)=>{for(const d of list)await field('spin_slowdown',d,hold)};

  await park(5000);                                             // LEDs chasing, nothing recognisable yet
  // still slow: a second strip shows a different sequence (it sits at different radii), then 3, 4, back to 1
  for(const n of [2,3,4,1])await field('strips_per_blade',n,4000);
  await park(1500);
  await divisor([120,60,30,15,8,4,2,1],1500);await park(2500);  // POV takes over: grid appears
  await click('pat_photo',2500);                                 // rings
  await divisor([2,4],2500);await park(2000);                    // slow down: flicker
  await click('pat_text',1500);await divisor([2,1],1500);await park(3000);   // text, clear
  await file('retriever.jpg',4000);                              // photo
  for(const g of ['spinner1.gif','spinner2.gif','spinner3.gif']){
    await file(g,3000);await divisor([3,8],1800);await divisor([3,1],1800);await park(2000)}
  // faded state, then more strips and blades
  await divisor([2.5],2500);                                     // 2 blades: half the circle dark
  await field('strips_per_blade',2,2500);
  await field('blades',3,3000);await field('blades',4,3000);await field('blades',2,3000);
  await field('strips_per_blade',3,2000);await field('strips_per_blade',4,2000);
  await field('blades',3,3000);await field('blades',4,3000);
  await park(4000);
  await ctx.close();await b.close();
  const v=fs.readdirSync(out).find(f=>f.endsWith('.webm'));fs.renameSync(path.join(out,v),path.join(out,'screencast.webm'));
  console.log('recorded',path.join(out,'screencast.webm'));
})();
