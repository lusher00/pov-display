// Renders the scripted POVD build-up demo from povd-sim.html to frames, then ffmpeg -> mp4.
// usage: node render_demo.js <sim.html> <outdir> [fps] [pattern]
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const [,,sim,out,fpsArg,pattern='text']=process.argv;const fps=+(fpsArg||30);
fs.mkdirSync(out,{recursive:true});

// timeline: each entry {t0,t1,cfg(t->partial config)}; rpm ramps are linear in t
const lerp=(a,b,u)=>a+(b-a)*Math.max(0,Math.min(1,u));
function cfgAt(t){
  const c={blades:2,strips_per_blade:1,rpm:60,persist_ms:60,spin_slowdown:1,columns_per_rev:720};
  if(t<5){}                                                   // 2 blades, 1 strip, 60 rpm: LEDs chasing
  else if(t<11){c.rpm=lerp(60,700,(t-5)/6)}                   // ramp up; persistence takes over
  else if(t<14){c.rpm=700;c.strips_per_blade=2}
  else if(t<17){c.rpm=700;c.strips_per_blade=3}
  else if(t<20){c.rpm=700;c.strips_per_blade=4}
  else if(t<23){c.rpm=700;c.strips_per_blade=4;c.blades=3}
  else if(t<26){c.rpm=700;c.strips_per_blade=4;c.blades=4}
  else if(t<28){c.rpm=lerp(700,500,(t-26)/2);c.strips_per_blade=4;c.blades=4}   // 4 blades let it run slower
  else if(t<34){c.rpm=lerp(500,60,(t-28)/6);c.strips_per_blade=4;c.blades=4}    // ramp down: 4 blades chasing
  else {c.rpm=60;c.strips_per_blade=4;c.blades=4}
  c.rpm=Math.round(c.rpm);
  return c;
}
const T_END=37;

(async()=>{
  const b=await chromium.launch();const p=await b.newPage({viewport:{width:1400,height:900}});
  p.on('pageerror',e=>console.log('ERR',e.message));
  await p.goto('file://'+path.resolve(sim));await p.waitForTimeout(600);
  await p.evaluate(pat=>{povd.stop();povd.pattern[pat]();document.getElementById('spin').checked=true;povd.reset()},pattern);
  let last='';const n=Math.round(T_END*fps);
  for(let i=0;i<n;i++){
    const t=i/fps;const c=cfgAt(t);const key=JSON.stringify(c);
    if(key!==last){await p.evaluate(c=>povd.set(c),c);last=key}
    const data=await p.evaluate(dt=>{povd.step(dt);return document.getElementById('disp').toDataURL('image/jpeg',0.92)},1000/fps);
    fs.writeFileSync(path.join(out,`f${String(i).padStart(5,'0')}.jpg`),Buffer.from(data.split(',')[1],'base64'));
    if(i%fps===0)process.stdout.write(`t=${t.toFixed(0)}s blades=${c.blades} strips=${c.strips_per_blade} rpm=${c.rpm}\n`);
  }
  await b.close();
})();
