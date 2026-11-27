// DigitalCrate — studio features layered on Browser.html (loaded after the main script; shares its globals).
// Project mode · sound & reference search · daily crate · galaxy · sketchpad · chop pads · MIDI · vocal tuning
// · Ableton racks · YouTube scout · Ableton Link.
(function(){
if(typeof S==='undefined'||typeof F==='undefined')return;
const KEYS24=(()=>{const B=['B','F#','Db','Ab','Eb','Bb','F','C','G','D','A','E'],A=['Abm','Ebm','Bbm','Fm','Cm','Gm','Dm','Am','Em','Bm','F#m','Dbm'];
 const o=[];for(let k=0;k<12;k++){o.push([`${k+1}A`,A[k]]);o.push([`${k+1}B`,B[k]])}return o})();
const keyFromCam=c=>(KEYS24.find(([k])=>k===c)||[])[1]||'';
const camOfKey=n=>(KEYS24.find(([,k])=>k===n)||[])[0]||'';
const catColor=c=>getComputedStyle(document.documentElement).getPropertyValue('--'+AB[c]).trim()||'#888';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function api(path,body){const r=await fetch(path,body?{method:'POST',body:JSON.stringify(body)}:undefined);const j=await r.json();if(j&&j.error)throw new Error(j.error);return j}

// ================= project mode =================
const PROJ=Object.assign({on:false,key:'',bpm:0,link:false,linkTransport:false},(()=>{try{return JSON.parse(localStorage.getItem('atlasProj')||'{}')}catch(e){return{}}})());
window.PROJ=PROJ;
const conformURL=(path,key,bpm)=>`api/conform?path=${encodeURIComponent(path)}&key=${encodeURIComponent(key||'')}&bpm=${bpm||''}`;
const purl=path=>PROJ.on&&SERVED&&(PROJ.key||PROJ.bpm)?conformURL(path,PROJ.key,PROJ.bpm):url(path);
const projTag=()=>PROJ.on&&(PROJ.key||PROJ.bpm)?` → ${[PROJ.key,PROJ.bpm?PROJ.bpm+' bpm':''].filter(Boolean).join(' · ')}`:'';
function setProj(patch,settle=300){const before=PROJ.key+'|'+PROJ.bpm;Object.assign(PROJ,patch);try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}
 drawProj();if(PROJ.key+'|'+PROJ.bpm!==before){skReloadSoon(settle);if(st.sel!=null&&$('pjinfo'))projInfo(st.sel)}}
const top=document.querySelector('.top');
top.insertAdjacentHTML('afterend',`<div class="projbar" id="projbar"><b>Project</b>
 key <select id="pjkey"><option value="">—</option>${KEYS24.map(([c,n])=>`<option value="${n}">${c} · ${n}</option>`).join('')}</select>
 tempo <input id="pjbpm" type="number" step="0.1" min="40" max="220" placeholder="bpm" style="width:72px">
 <label title="every preview, variation and 'play together' is pitched/stretched into the project key & tempo"><input type="checkbox" id="pjon"> play everything in the project key/tempo</label>
 <button id="pjlink" class="tbtn" title="follow Ableton Live's tempo via Link (turn on Link in Live's top bar)">🔗 Live</button>${hq('project')}
 <label class="sub" title="start/stop the sketchpad with Live's transport (Live: Link → Start Stop Sync)"><input type="checkbox" id="pjlt"> start/stop with Live</label>
 <span class="lk" id="pjlk"></span><span style="flex:1"></span><button id="skbtn" class="tbtn">🎛 sketchpad (0)</button></div>
 <div id="sbanner" class="prov sbanner" hidden></div>`);
function drawProj(){$('pjkey').value=PROJ.key||'';$('pjbpm').value=PROJ.bpm||'';$('pjon').checked=!!PROJ.on;$('pjlink').classList.toggle('on',!!PROJ.link);$('pjlt').checked=!!PROJ.linkTransport;
 $('skbtn').textContent=`🎛 sketchpad (${SK.lanes.length})`;$('skbtn').classList.toggle('on',SK.open)}
$('pjkey').onchange=e=>setProj({key:e.target.value});
$('pjbpm').onchange=e=>setProj({bpm:Math.max(0,+e.target.value||0)});
$('pjon').onchange=e=>{setProj({on:e.target.checked});if(e.target.checked&&!PROJ.key&&!PROJ.bpm)toast('set a key and/or tempo for the project');stopAll()};
$('pjlink').onclick=()=>{setProj({link:!PROJ.link});if(PROJ.link)linkPoll();else $('pjlk').textContent=''};
$('pjlt').onchange=e=>setProj({linkTransport:e.target.checked});
// playback that respects the project (overrides the main script's players)
function cancelPreview(a){a.removeAttribute('src');a.load()}
toggle=function(i,btn,{loop=true,exclusive=true}={}){
 if(players.has(i)){const a=players.get(i);a.pause();endListen(i,a);players.delete(i);
  if(a instanceof HTMLAudioElement&&a.readyState<4)cancelPreview(a);mark();return}
 if(exclusive)stopAll();
 const a=new Audio(purl(S[i][F.path]));a.loop=loop&&S[i][F.kind]!=='oneshot';a.onended=()=>{endListen(i,a);players.delete(i);mark()};
 a.play().catch(()=>{});players.set(i,a);beginListen(i,S[i][F.path]);setNP(S[i][F.path],S[i][F.id],lbl(i)+projTag(),i);mark()};
playTogether=function(ids){stopAll();const as=ids.map(i=>{const a=new Audio(purl(S[i][F.path]));a.loop=S[i][F.kind]!=='oneshot';a.volume=.8;players.set(i,a);return a});
 setNP(S[ids[ids.length-1]][F.path],S[ids[ids.length-1]][F.id],'together: '+ids.map(i=>S[i][F.artist]).join(' + ')+projTag(),ids[ids.length-1]);
 Promise.all(as.map(a=>new Promise(r=>{a.oncanplaythrough=r;a.load()}))).then(()=>{
  if(as.every((a,k)=>players.get(ids[k])===a)){as.forEach(a=>a.play().catch(()=>{}));mark()}})};
playVar=function(k){const rows=[...document.querySelectorAll('#vars .vrow')];if(!rows.length)return;k=Math.max(0,Math.min(rows.length-1,k));vcur=k;
 const b=rows[k].querySelector('[data-vp]');stopAll();const a=new Audio(purl(b.dataset.vp));a.loop=true;a.play().catch(()=>{});players.set('v'+k,a);beginListen('v'+k,b.dataset.vp);
 if(st.sel!=null)setNP(b.dataset.vp,S[st.sel][F.id],`${S[st.sel][F.artist]} — ${S[st.sel][F.title]} · variation ${String(k).padStart(2,'0')}${projTag()}`,st.sel);
 rows.forEach((r,j)=>{r.style.background=j===k?'#1f2630':'';r.querySelector('.play').classList.toggle('playing',j===k)});rows[k].scrollIntoView({block:'nearest'})};
async function projInfo(i){const el=$('pjinfo');if(!el)return;if(!PROJ.key&&!PROJ.bpm){el.textContent='';return}
 try{const r=await api(`api/conform/info?path=${encodeURIComponent(S[i][F.path])}&key=${encodeURIComponent(PROJ.key)}&bpm=${PROJ.bpm||''}`);
  const parts=[];if(r.semis)parts.push(`${r.semis>0?'+':''}${r.semis} st`);if(Math.abs(r.time-1)>1e-3)parts.push(`stretch ×${(+r.time).toFixed(3)}`);
  el.textContent=`in your project (${[PROJ.key,PROJ.bpm&&PROJ.bpm+' bpm'].filter(Boolean).join(' · ')}): ${parts.length?parts.join(', '):'fits as is'}${r.key?' → '+r.key:''}`}catch(e){el.textContent=''}}

// ================= Link =================
const LINK={ok:false,peers:0,tempo:0,ref:null,wasPlaying:false};
let linkT=null;
async function linkPoll(){clearTimeout(linkT);if(!PROJ.link||!SERVED)return;
 try{const t0=performance.now(),r=await api('api/link'),t1=performance.now();
  if(!r.ok){$('pjlk').textContent='Link: '+r.error}else{
   Object.assign(LINK,{ok:true,peers:r.peers,tempo:r.tempo,ref:{perf:(t0+t1)/2,beat:r.beat}});
   $('pjlk').className='lk'+(r.peers?' on':'');$('pjlk').textContent=r.peers?`Live: ${r.tempo.toFixed(1)} bpm · ${r.playing?'playing':'stopped'}`:'Link on — enable Link in Live';
   if(r.peers&&Math.abs(r.tempo-(PROJ.bpm||0))>0.05)setProj({bpm:+r.tempo.toFixed(2)},1000);
   if(PROJ.linkTransport&&r.peers){if(r.playing&&!LINK.wasPlaying&&SK.lanes.length&&!SK.playing)skPlay();if(!r.playing&&LINK.wasPlaying&&(SK.playing||reloadPlay))skStop()}
   LINK.wasPlaying=!!r.playing}}catch(e){$('pjlk').textContent='Link unavailable'}
 linkT=setTimeout(linkPoll,300)}
function linkNextBar(){// AudioContext time of Live's next bar line
 if(!(PROJ.link&&LINK.ok&&LINK.peers&&LINK.ref))return AC.currentTime+0.06;
 const beatNow=LINK.ref.beat+(performance.now()-LINK.ref.perf)/1000*LINK.tempo/60,next=Math.ceil(beatNow/4+1e-4)*4;
 let t=AC.currentTime+(next-beatNow)*60/LINK.tempo-(AC.outputLatency||AC.baseLatency||0);if(t<AC.currentTime+0.03)t+=240/LINK.tempo;return t}

// ================= sound search & reference search =================
let SOUND=null;
document.getElementById('search').insertAdjacentHTML('afterend',`<button id="sndbtn" class="tbtn" title="search by what it sounds like (CLAP): e.g. “lonely female voice, distant” · add -word to push away">≈ by sound</button><button id="refbtn" class="tbtn" title="find samples that feel like a reference track (never sampled)">🎧 feels like…</button><button id="mybtn" class="tbtn" title="drop in a bounce of your own track: samples that would fit into it (key, tempo, sound)">🎚 fits my track</button>${hq('sound')}`);
let soundMode=false;
$('sndbtn').onclick=()=>{soundMode=!soundMode;$('sndbtn').classList.toggle('on',soundMode);$('search').placeholder=soundMode?'describe a sound, press Enter — e.g. “lonely female voice, distant, rainy night”':'search artist, title, mood, instrument, id…';
 if(!soundMode&&SOUND&&!SOUND.ref){SOUND=null;render()}if(soundMode&&$('search').value.trim())soundSearch($('search').value.trim());$('search').focus()};
$('search').addEventListener('keydown',e=>{if(e.key==='Enter'&&soundMode&&$('search').value.trim()){e.preventDefault();soundSearch($('search').value.trim())}});
async function soundSearch(q){if(!SERVED){toast('sound search needs the local server');return}toast(`listening for “${q}”…`);
 try{const r=await api('api/search?q='+encodeURIComponent(q));SOUND={label:`sounds like “${q}”`,score:new Map(r.results.map((x,k)=>[x.path,r.results.length-k])),at:null};
  setTab('S');st.shown=200;render()}catch(e){toast('search failed: '+e.message)}}
$('refbtn').onclick=()=>{if(!SERVED){toast('needs the local server');return}
 modal(`<h2 style="margin:0">Find samples that feel like a track</h2><div class="sub">A YouTube/SoundCloud URL, an audio file path, or “artist – title” from your library (e.g. <i>Burial – Archangel</i>). The reference is only listened to — never sampled, never added. Results come from your own library, minus cuts of the reference itself.</div>
 <input id="refIn" style="width:100%" placeholder="Burial – Archangel   ·   https://…   ·   /path/to/track.mp3"><div class="edrow"><button id="refGo" class="pill">find</button><button data-close>close</button></div><div id="refMsg" class="sub"></div>`);
 $('refIn').focus();$('refIn').onkeydown=e=>{if(e.key==='Enter')$('refGo').click()};
 $('refGo').onclick=async()=>{const t=$('refIn').value.trim();if(!t)return;$('refMsg').textContent='listening to the reference… (10–60 s; a URL has to download first)';$('refGo').disabled=true;
  try{const r=await api('api/refsearch',{target:t});SOUND={ref:true,label:`feels like ${r.reference}`,score:new Map(r.results.map((x,k)=>[x.path,r.results.length-k])),at:new Map(r.results.map(x=>[x.path,x.at]))};
   $('modal').hidden=true;setTab('S');st.shown=200;render()}catch(e){$('refMsg').textContent='error: '+e.message}finally{$('refGo')&&($('refGo').disabled=false)}}};
const _filtered=filtered;
filtered=function(){const blank=soundMode||(SOUND&&SOUND.ref);if(!blank&&(!SOUND||st.tab!=='S'&&st.tab!=='G'))return _filtered();const el=$('search'),v=el.value;if(blank)el.value='';let out;try{out=_filtered()}finally{el.value=v}
 if(!SOUND||st.tab!=='S'&&st.tab!=='G')return out;return out.filter(i=>SOUND.score.has(S[i][F.path])).sort((a,b)=>SOUND.score.get(S[b][F.path])-SOUND.score.get(S[a][F.path]))};
function drawSBanner(){const b=$('sbanner');if(!SOUND||!(st.tab==='S'||st.tab==='G')){b.hidden=true;return}b.hidden=false;
 b.innerHTML=`≈ <b>${esc(SOUND.label)}</b> — ${SOUND.mine?'best fit first':'closest first'}; your other filters still apply &nbsp;${SOUND.mine?`<button id="myproj" title="conform the sketchpad and exports to your track">use ${esc(SOUND.mine.key)} · ${SOUND.mine.bpm} bpm as the project</button> `:''}<button id="sclear">✕ clear</button>`;$('sclear').onclick=()=>{SOUND=null;if(soundMode)$('sndbtn').click();render()}}

// ================= tabs: crate · galaxy · scout =================
$('tabS').insertAdjacentHTML('afterend',`<button id="tabC" title="today's crate: 20 picks for you + wildcards">🎲 Crate</button>`);
document.querySelector('.tabs').insertAdjacentHTML('beforeend',`<button id="tabG" title="every sample on a map by sound">🌌 Galaxy</button><button id="tabY" title="scout YouTube for raw singing">🔭 Scout</button>`);
const MYTABS={C:'tabC',G:'tabG',Y:'tabY'};
function setTab(k){st.tab=k;document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));const id=tabs[k]||MYTABS[k];if($(id))$(id).classList.add('on');render()}
Object.entries(MYTABS).forEach(([k,id])=>$(id).onclick=()=>setTab(k));
Object.values(tabs).forEach(id=>$(id).addEventListener('click',()=>Object.values(MYTABS).forEach(m=>$(m).classList.remove('on'))));
const _render=render;
render=function(){document.body.classList.toggle('wide',st.tab==='Y');drawSBanner();if('CGY'.includes(st.tab)&&typeof drawCats==='function')drawCats();if(st.tab==='C'){paintWheel();drawBanner();return renderCrate()}if(st.tab==='G'){paintWheel();drawBanner();return renderGalaxy()}
 if(st.tab==='Y'){paintWheel();drawBanner();return renderScout()}
 if(st.tab==='F'&&FAVVIEW==='sets'&&SERVED){paintWheel();drawBanner();return renderSets()}
 if(st.tab==='F'&&FAVVIEW==='cols'&&SERVED){paintWheel();drawBanner();return renderCollections()}
 _render();if(st.tab==='K')renderKitExtras();if(st.tab==='F'&&SERVED)$('list').insertAdjacentHTML('afterbegin',favViewBar());if(st.tab==='S'&&SOUND&&SOUND.at)annotateAt()};
function annotateAt(){document.querySelectorAll('#list .row[data-i]').forEach(r=>{const p=S[+r.dataset.i][F.path],a=SOUND.at.get(p);const m=r.querySelector('.meta');
 if(a&&m&&!m.dataset.at){m.dataset.at=1;m.insertAdjacentHTML('beforeend',` · <span style="color:var(--acc)">${SOUND.why?esc(a):'like the reference @ '+a}</span>`)}})}
// ---------- 🎚 fits my track: samples that would fit into your own song (mytrack.py). The file is only analysed.
$('mybtn').onclick=()=>{if(!SERVED){toast('needs the local server');return}
 modal(`<h2 style="margin:0">Samples that fit my track</h2><div class="sub">Drop a bounce of something you're making (WAV, AIFF, MP3…), or paste its path. Its key and tempo are detected and the library is ranked by what would fit into it: key (how far a sample has to move), tempo for loops, and sound. The file is only listened to: analysed here and deleted, never added or sent anywhere.</div>
 <div id="mydrop" class="mydrop">drop the audio file here<br><span class="sub">or</span> <input id="myfile" type="file" accept="audio/*"></div>
 <input id="myIn" style="width:100%" placeholder="/path/to/my bounce.wav"><div class="edrow"><button id="myGo" class="pill">find</button><button data-close>close</button></div><div id="myMsg" class="sub"></div>`);
 const go=async body=>{$('myMsg').textContent='listening… (10–40 s: key, tempo, and its sound against every sample)';$('myGo').disabled=true;
  try{const r=await api('api/mytrack',body);
   SOUND={mine:r,why:true,label:`fits ${r.name} · ${r.key} (${r.camelot}) · ${r.bpm} bpm${r.tempo_sure?'':' (tempo unsure)'}`,score:new Map(r.results.map((x,k)=>[x.path,r.results.length-k])),at:new Map(r.results.map(x=>[x.path,x.why]))};
   $('modal').hidden=true;setTab('S');st.shown=200;render()}catch(e){$('myMsg').textContent='error: '+e.message}finally{$('myGo')&&($('myGo').disabled=false)}};
 const send=f=>{const rd=new FileReader();rd.onload=()=>go({name:f.name,b64:rd.result});$('myMsg').textContent='reading '+f.name+'…';rd.readAsDataURL(f)};
 const dz=$('mydrop');dz.ondragover=e=>{e.preventDefault();dz.classList.add('on')};dz.ondragleave=()=>dz.classList.remove('on');
 dz.ondrop=e=>{e.preventDefault();dz.classList.remove('on');const f=e.dataTransfer.files[0];if(f)send(f)};
 $('myfile').onchange=e=>{const f=e.target.files[0];if(f)send(f)};
 $('myIn').onkeydown=e=>{if(e.key==='Enter')$('myGo').click()};$('myGo').onclick=()=>{const t=$('myIn').value.trim();if(t)go({file:t})}};
// the banner offers the track's key and tempo as the project's (so the sketchpad and exports conform to it)
document.addEventListener('click',e=>{if(!e.target.closest('#myproj')||!SOUND||!SOUND.mine)return;const r=SOUND.mine;
 PROJ.key=r.key;if(!(PROJ.link&&LINK.peers))PROJ.bpm=r.bpm;try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(err){}drawProj();toast(`project set to ${r.key} · ${PROJ.bpm} bpm`)},true);
// rows get a ＋ (add to sketchpad)
const _rowHTML=rowHTML;
rowHTML=function(i){return _rowHTML(i).replace('<span class="id"',`<button class="xp" data-sk="${i}" title="add to the sketchpad">＋</button><span class="id"`)};

// ---------- daily crate
function rng(seed){let a=0;for(const c of seed)a=(a*31+c.charCodeAt(0))|0;return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
function lsj(k,d){try{return JSON.parse(localStorage.getItem(k)||'null')??d}catch(e){return d}}
// which sample types the crate draws from: [] = all (the default); remembered per browser
const crateMix=()=>lsj('atlasCrateMix',[]);
function buildCrate(force){const day=new Date().toLocaleDateString('en-CA');const saved=lsj('atlasCrate',null),mix=crateMix();
 if(!force&&saved&&saved.day===day&&saved.paths&&saved.paths.length&&String(saved.mix||[])===String(mix))return saved;
 const n=(saved&&saved.day===day?saved.n||0:0)+(force?1:0),R=rng(day+':'+n),seen=new Set(lsj('atlasCrateSeen',[]));
 const rated=new Set([...FAV.keys(),...TASTE.disliked]);
 const pool=S.map((s,i)=>i).filter(i=>{const s=S[i];return !rated.has(s[F.path])&&!seen.has(s[F.path])&&!st.excl.has(s[F.genre])&&s[F.q]>=0.45&&!s[F.path].startsWith('_Reference')&&!s[F.parent]&&(!mix.length||mix.includes(s[F.cat]))});
 const sc=i=>TASTE.score[S[i][F.path]]??(S[i][F.q]-1),ds=i=>TASTE.discover[S[i][F.path]]??R();
 const pick=(list,k,out,byT,byA)=>{for(const i of list){if(out.length>=k)break;const t=S[i][F.tid],a=S[i][F.artist];if(byT.has(t)||(byA.get(a)||0)>=2)continue;byT.add(t);byA.set(a,(byA.get(a)||0)+1);out.push(i)}return out};
 const byT=new Set(),byA=new Map();
 const you=pick(pool.slice().sort((a,b)=>sc(b)-sc(a)+(R()-.5)*0.15),14,[],byT,byA);
 const disc=pool.slice().sort((a,b)=>ds(b)-ds(a)).slice(30,900);for(let k=disc.length-1;k>0;k--){const j=Math.floor(R()*(k+1));[disc[k],disc[j]]=[disc[j],disc[k]]}
 const wild=pick(disc,6,[],byT,byA);
 const c={day,n,mix,paths:you.map(i=>S[i][F.path]),wild:wild.map(i=>S[i][F.path])};try{localStorage.setItem('atlasCrate',JSON.stringify(c));
  localStorage.setItem('atlasCrateSeen',JSON.stringify([...seen,...c.paths,...c.wild].slice(-3000)))}catch(e){}return c}
function renderCrate(){const c=buildCrate(false),all=[...c.paths,...c.wild],ids=p=>p.map(x=>byPath.get(x)).filter(x=>x!=null);
 const done=all.filter(p=>FAV.has(p)||TASTE.disliked.has(p)).length;
 $('count').textContent=`today's crate · ${done}/${all.length} rated`+(TASTE.n?` · taste model: ${TASTE.n} ratings`:'');
 const mix=crateMix(),cats=Object.keys(D.subtypes).filter(c=>S.some(s=>s[F.cat]===c));
 $('list').innerHTML=`<div class="crateprog"><i style="width:${all.length?done/all.length*100:0}%"></i></div>
 <div class="chips" style="margin:0 16px 12px;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="sub">In this crate:</span>
 <button data-crmix="" class="${mix.length?'':'on'}" title="every type (the default)">All</button>${cats.map(c=>`<button data-crmix="${esc(c)}" class="${mix.includes(c)?'on':''}" title="${esc(c)}"><span class="badge" style="background:${col(c)}">${AB[c]}</span>${esc(c.replace('Atmospheres','Atmos'))}</button>`).join('')}
 <span class="sub">pick one or more</span></div>
 <div class="kit"><h3><span>For you — what the taste model rates highest that you haven't heard${hq('crate')}</span><button id="crnew" title="a fresh crate">↻ new crate</button></h3>${ids(c.paths).map(rowHTML).join('')||(mix.length?'<div class="empty">No unheard samples of these types left. Add another type.</div>':'<div class="empty">rate a few samples first</div>')}</div>
 <div class="kit"><h3><span>Wildcards — outside your usual, picked to teach the model fastest</span></h3>${ids(c.wild).map(rowHTML).join('')}</div>
 <div class="hint" style="margin:0 16px 16px">★ and ✕ train the taste model; a new crate appears each day. Already-crated samples don't come back.</div>`;
 $('crnew').onclick=()=>{buildCrate(true);renderCrate()};
 $('list').querySelectorAll('[data-crmix]').forEach(b=>b.onclick=()=>{const v=b.dataset.crmix;let m=crateMix();
  m=v===''?[]:m.includes(v)?m.filter(x=>x!==v):[...m,v];try{localStorage.setItem('atlasCrateMix',JSON.stringify(m))}catch(e){}buildCrate(true);renderCrate()});mark()}

// ---------- 🧩 sets: favourites that fit together (sets.py), on the Favorites tab
let FAVVIEW=lsj('atlasFavView','list'),SETS=null;
const favViewBar=()=>`<div class="chips" style="margin:0 16px 10px;display:flex;gap:6px;align-items:center"><span class="sub">View:</span><button data-favview="list" class="${FAVVIEW==='list'?'on':''}">★ list</button><button data-favview="sets" class="${FAVVIEW==='sets'?'on':''}" title="your favourites grouped into sets that fit together, and what would complete each">🧩 sets that fit together</button><button data-favview="cols" class="${FAVVIEW==='cols'?'on':''}" title="collections: samples saved for a project you have in mind">📁 collections</button></div>`;
document.addEventListener('click',e=>{const b=e.target.closest('[data-favview]');if(!b)return;FAVVIEW=b.dataset.favview;try{localStorage.setItem('atlasFavView',JSON.stringify(FAVVIEW))}catch(err){}render()});
async function renderSets(){const L=$('list');$('count').textContent='your favourites, grouped into sets that fit together';
 const key=[...FAV.keys()].sort().join('|');
 if(!SETS||SETS.key!==key){L.innerHTML=favViewBar()+'<div class="sub" style="margin:12px 16px">grouping your favourites…</div>';
  try{SETS=await api('api/sets');SETS.key=key}catch(e){L.innerHTML=favViewBar()+`<div class="empty">couldn't group them: ${esc(e.message)}</div>`;return}}
 if(st.tab!=='F'||FAVVIEW!=='sets')return;
 const ids=ps=>ps.map(p=>byPath.get(p)).filter(i=>i!=null&&!GONE.has(i));
 L.innerHTML=favViewBar()+`<div class="hint" style="margin:0 16px 12px">Every pair in a set fits: key (and the notes actually played), tempo for loops, role and sound, scored like "goes well with". ${SETS.loose?`${SETS.loose} favourites don't fit a set strongly yet; starring more fills them in.`:''}</div>`
  +(SETS.sets.length?SETS.sets.map((s,k)=>{const m=ids(s.members),c=s.complete.filter(x=>byPath.has(x.path)&&!GONE.has(byPath.get(x.path)));
   return `<div class="kit"><h3><span>Set ${k+1} · ${esc(s.name)} <span class="sub">${m.length} samples · every pair fits ≥ ${Math.round(s.weakest*100)}%</span></span><button data-setplay="${k}">▶ play together</button> <button data-setsk="${k}" title="open the set in the sketchpad">🎛 sketch</button> <button data-setexp="${k}">⇩ export</button></h3>
   ${m.map(rowHTML).join('')}
   ${c.length?`<div class="sub" style="margin:10px 0 4px">Would complete it, from the rest of your library (fits every sample above):</div>${c.map(x=>{const i=byPath.get(x.path);return rowHTML(i).replace('<div class="meta">',`<div class="meta">${x.new_role?'<span style="color:var(--acc)">adds a new role</span> · ':''}fit ${Math.round(x.fit*100)}% · `)}).join('')}`:''}</div>`}).join('')
   :'<div class="empty">No sets yet: star a few more samples that sound good together.</div>');mark()}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-setplay],[data-setsk],[data-setexp]');if(!b||!SETS)return;e.stopPropagation();
 const k=+(b.dataset.setplay??b.dataset.setsk??b.dataset.setexp),s=SETS.sets[k],m=s.members.map(p=>byPath.get(p)).filter(i=>i!=null&&!GONE.has(i));
 if(b.dataset.setplay!=null){playTogether(m);return}
 if(b.dataset.setsk!=null){if(SK.lanes.length)setTimeout(()=>toast('the sketch was replaced · ⌘Z brings it back'),400);skStop();SK.lanes=[];SK.drums=null;SK.name=`Set ${k+1} · ${s.name}`;for(const i of m)await skAdd(i);skPlay();return}
 b.textContent='exporting…';try{const r=await api('api/export',{scope:'paths',paths:m.map(i=>S[i][F.path]),name:`Set ${k+1} ${s.name}`.replace(/[^\w #·-]/g,'')});b.textContent=`exported ${r.count} ✓`}catch(err){b.textContent='error'}},true);

// ---------- 📁 collections: samples saved with a project in mind (collections_.py)
let COLS=[],COLLAST=lsj('atlasColLast','');
const colsOf=p=>COLS.filter(c=>c.set.has(p)).map(c=>c.name);
async function colLoad(){if(!SERVED)return;try{COLS=(await api('api/collections')).map(c=>({...c,set:new Set(c.paths)}))}catch(e){COLS=[]}
 document.querySelectorAll('[data-col]').forEach(b=>b.classList.toggle('on',colsOf(b.dataset.colp).length>0))}
const colBtn=(i,big)=>SERVED?`<button class="${big?'':'xp '}${colsOf(S[i][F.path]).length?'on':''}" data-col="${i}" data-colp="${esc(S[i][F.path])}" title="add to a collection (a project you have in mind)">📁${big?' collection':''}</button>`:'';
async function colToggle(name,i,on){const p=S[i][F.path];
 await api(`api/collections/${on?'add':'remove'}`,{name,path:p,id:S[i][F.id]});COLLAST=name;try{localStorage.setItem('atlasColLast',JSON.stringify(name))}catch(e){}
 await colLoad();
 if(!window.ACT_QUIET)actPush(`${on?'added':'removed'} ${nameOf(p)} ${on?'to':'from'} “${name}”`,()=>colToggle(name,i,!on),!on);else return;
 if(on)toast(`added to “${name}”`)}
function colPop(b){const i=+b.dataset.col,p=S[i][F.path];let pop=$('colpop');if(!pop){pop=document.createElement('div');pop.id='colpop';pop.className='colpop';document.body.appendChild(pop)}
 const names=COLS.map(c=>c.name).sort((a,c)=>(c===COLLAST)-(a===COLLAST)),mine=new Set(colsOf(p));
 pop.innerHTML=`<div class="sub" style="margin-bottom:6px">Collections for this sample</div>${names.map(n=>`<label class="colrow"><input type="checkbox" data-colname="${esc(n)}" ${mine.has(n)?'checked':''}> ${esc(n)} <span class="sub">${COLS.find(c=>c.name===n).n}</span></label>`).join('')||'<div class="sub">none yet</div>'}
 <div style="display:flex;gap:6px;margin-top:8px"><input id="colnew" placeholder="new collection, e.g. Night drive EP" style="flex:1;min-width:0"><button id="colmk">＋</button></div>`;
 const r=b.getBoundingClientRect();pop.style.left=Math.max(8,Math.min(innerWidth-280,r.left-120))+'px';pop.style.top=(r.bottom+6+scrollY)+'px';pop.hidden=false;pop.dataset.i=i;
 pop.onchange=async e=>{const n=e.target.dataset.colname;if(n!=null)await colToggle(n,i,e.target.checked)};
 const mk=async()=>{const n=$('colnew').value.trim();if(!n)return;await colToggle(n,i,true);colPop(b)};$('colmk').onclick=mk;$('colnew').onkeydown=e=>{if(e.key==='Enter')mk()};setTimeout(()=>$('colnew').focus(),0)}
document.addEventListener('click',e=>{const b=e.target.closest('[data-col]');const pop=$('colpop');
 if(b){e.stopPropagation();e.preventDefault();if(pop&&!pop.hidden&&+pop.dataset.i===+b.dataset.col){pop.hidden=true;return}colPop(b);return}
 if(pop&&!pop.hidden&&!e.target.closest('#colpop'))pop.hidden=true},true);
// rows and the sample panel get 📁
const _rowHTMLc=rowHTML;rowHTML=function(i){return _rowHTMLc(i).replace('<span class="id"',colBtn(i)+'<span class="id"')};
const _selectC=select;select=function(i,from){_selectC(i,from);
 if(SERVED&&S[i][F.cat]==='Percussion'&&S[i][F.kind]==='loop'){const xb=document.querySelector('#detail [data-xp]');if(xb&&!$('sliceit'))xb.insertAdjacentHTML('afterend',`<button id="sliceit" title="slice this loop at its hits into pads of the sketchpad's drum lane, each on its step, so you can re-sequence it">🥁 slice into pads</button>`)}
 if(SERVED&&TASTE.loaded){const xb=document.querySelector('#detail [data-xp]');if(xb&&!$('whybtn')){xb.parentNode.insertAdjacentHTML('afterend',`<div id="whybox" class="prov" hidden></div>`);
  xb.insertAdjacentHTML('afterend',`<button id="whybtn" title="why the taste model ranks this where it does">💡 why this?</button>`);if(WHY_OPEN)whyShow(i)}}
 const SC=D.sections||{};if(SC[i]){const m=document.querySelector('#detail .meta');if(m&&!m.querySelector('.secb'))m.insertAdjacentHTML('afterbegin',`<span class="badge secb" title="where in the song it comes from (All-In-One)">from the ${esc({inst:'instrumental break'}[SC[i]]||SC[i])}</span> `)}
 if(LOOPS[i]&&S[i][F.kind]!=='loop'){const xb=document.querySelector('#detail [data-xp]'),lp=LOOPS[i];if(xb&&!$('holdit'))xb.insertAdjacentHTML('afterend',`<button id="holdit" data-i="${i}" title="play it and hold it on its seamless loop (${lp[0].toFixed(1)}–${lp[1].toFixed(1)} s) until you stop it: how it sustains in a sampler">∞ hold</button>`)}
 const CH=D.chords||{};if(CH[i]){const m=document.querySelector('#detail .meta');if(m&&!m.querySelector('.chb'))m.insertAdjacentHTML('afterbegin',`<span class="badge chb" title="its own chords (madmom's chord recognizer)">${CH[i].map(esc).join(' → ')}</span> `)}
 if(SERVED&&['Pads & Atmospheres','Strings & Orchestral','Chords & Keys','Vocal Atmospheres'].includes(S[i][F.cat])&&S[i][F.kind]!=='oneshot'){const xb=document.querySelector('#detail [data-xp]');
  if(xb&&!$('playit'))xb.insertAdjacentHTML('afterend',`<button id="playit" data-i="${i}" title="for Live: a Simpler instrument tuned to its chord (each key plays it from that note, holding on its loop), and its chords as a MIDI clip to start from">🎹 playable</button>`)}
 if(SERVED){const xb=document.querySelector('#detail [data-xp]');if(xb&&!$('reveal'))xb.insertAdjacentHTML('afterend',`<button id="reveal" title="show the file in Finder, selected: drag it from there into Live (or anywhere)">↗ Finder</button>`)}
 if(SERVED&&S[i][F.cat]==='Percussion'&&S[i][F.kind]!=='loop'){const xb=document.querySelector('#detail [data-xp]');if(xb&&!$('kitaround'))xb.insertAdjacentHTML('afterend',`<button id="kitaround" title="start (or add to) the sketchpad's drum lane with this hit, then find the rest of a kit that sounds like it">🥁 build a kit around this</button>`)}const xb=document.querySelector('#detail [data-xp]');if(xb&&SERVED&&!$('detail').querySelector('[data-col]'))xb.insertAdjacentHTML('afterend',colBtn(i,true))};
// the Favorites tab's 📁 view
let COLSEL=lsj('atlasColSel','');
async function renderCollections(){const L=$('list');await colLoad();if(st.tab!=='F'||FAVVIEW!=='cols')return;
 if(!COLS.some(c=>c.name===COLSEL))COLSEL=(COLS[0]||{}).name||'';const c=COLS.find(x=>x.name===COLSEL);
 $('count').textContent=`${COLS.length} collection${COLS.length===1?'':'s'}`+(SERVED?' · also in SampleLibrary/Collections':'');
 const ids=c?c.paths.map(p=>byPath.get(p)).filter(i=>i!=null&&!GONE.has(i)):[];
 L.innerHTML=favViewBar()+(COLS.length?`<div class="chips" style="margin:0 16px 12px;display:flex;gap:6px;flex-wrap:wrap">${COLS.map(x=>`<button data-colsel="${esc(x.name)}" class="${x.name===COLSEL?'on':''}">📁 ${esc(x.name)} <span class="sub">${x.n}</span></button>`).join('')}</div>`:'')
  +(c?`<div class="kit"><h3><span>📁 ${esc(c.name)} <span class="sub">${ids.length} samples</span></span><button data-colplay>▶ play together</button> <button data-colsk title="open it in the sketchpad (drum hits go to the drum lane)">🎛 sketch</button> <button data-colexp>⇩ export</button> <button data-colsets title="its samples grouped into sets that fit together">🧩 sets</button> <button data-colren>rename</button> <button data-coldel title="removes the collection, not the samples">delete</button></h3>
   <div id="colsets"></div>${ids.map(rowHTML).join('')||'<div class="empty">Empty: add samples with 📁</div>'}</div>`
  :`<div class="empty">No collections yet. Click 📁 on any sample (or press C while one plays) to save it to a collection for a project you have in mind.</div>`);mark()}
document.addEventListener('click',async e=>{const t=e.target.closest('[data-colsel],[data-colplay],[data-colsk],[data-colexp],[data-colsets],[data-colren],[data-coldel]');if(!t)return;e.stopPropagation();
 if(t.dataset.colsel!=null){COLSEL=t.dataset.colsel;try{localStorage.setItem('atlasColSel',JSON.stringify(COLSEL))}catch(err){}renderCollections();return}
 const c=COLS.find(x=>x.name===COLSEL);if(!c)return;const ids=c.paths.map(p=>byPath.get(p)).filter(i=>i!=null&&!GONE.has(i));
 if(t.dataset.colplay!=null){playTogether(ids);return}
 if(t.dataset.colsk!=null){if(SK.lanes.length)setTimeout(()=>toast('the sketch was replaced · ⌘Z brings it back'),400);skStop();SK.lanes=[];SK.name=c.name;for(const i of ids)await skAdd(i);skPlay();return}
 if(t.dataset.colexp!=null){t.textContent='exporting…';try{const r=await api('api/export',{scope:'paths',paths:ids.map(i=>S[i][F.path]),name:c.name});t.textContent=`exported ${r.count} ✓`}catch(err){t.textContent='error'}return}
 if(t.dataset.colsets!=null){const box=$('colsets');box.innerHTML='<div class="sub">grouping…</div>';const r=await api('api/sets?collection='+encodeURIComponent(c.name));
  box.innerHTML=r.sets.length?r.sets.map((s,k)=>`<div class="sub" style="margin:6px 0 2px">🧩 set ${k+1} · ${esc(s.name)} · every pair fits ≥ ${Math.round(s.weakest*100)}% · ${s.members.length} samples</div>`).join('')+'<div class="sub" style="margin-bottom:8px">(the full sets view with play and sketch buttons is in 🧩 sets for favourites)</div>':`<div class="sub">${r.note||'no sets that fit tightly yet: add a few more samples'}</div>`;return}
 if(t.dataset.colren!=null){const n=window.prompt?prompt('New name',c.name):null;if(!n||n===c.name)return;try{await api('api/collections/rename',{name:c.name,new:n});COLSEL=n;renderCollections()}catch(err){toast(err.message)}return}
 if(t.dataset.coldel!=null){if(t.dataset.armed!=='1'){t.dataset.armed='1';t.textContent='delete? (samples stay)';setTimeout(()=>{t.dataset.armed='';t.textContent='delete'},3000);return}
  await api('api/collections/delete',{name:c.name});COLSEL='';renderCollections()}},true);
colLoad();

// ---------- new samples appear while you work (live.py): no `digitalcrate build`, no reload
let LIVE_SINCE=BORN.reduce((a,b)=>Math.max(a,b||0),0);
async function liveCheck(force){if(!SERVED||(document.hidden&&!force))return 0;let r;try{r=await api('api/live/new?since='+LIVE_SINCE)}catch(e){return 0}
 const add=r.samples.map((row,k)=>({row,parts:r.partners[k]||[],b:r.born[k]})).filter(x=>!BYID.has(x.row[F.id]));if(!add.length)return 0;
 add.forEach(x=>{const e=x.row[F.env];if(typeof e==='string'){const b=atob(e),v=new Array(b.length);for(let k=0;k<b.length;k++)v[k]=b.charCodeAt(k);x.row[F.env]=v}});  // waveforms come packed, like in the page file
 Object.assign(D.tracks,r.tracks);
 add.forEach(x=>{const j=S.push(x.row)-1;x.j=j;BYID.set(x.row[F.id],j);byPath.set(x.row[F.path],j);if(!BYTRACK.has(x.row[F.tid]))BYTRACK.set(x.row[F.tid],[]);BYTRACK.get(x.row[F.tid]).push(j);BORN[j]=x.b});
 add.forEach(x=>{P[x.j]=x.parts.map(([id,sc,h,v])=>[BYID.get(id),sc,h,v]).filter(q=>q[0]!=null)});  // second pass: partners may be other new ones
 LIVE_SINCE=Math.max(LIVE_SINCE,...add.map(x=>x.b));
 toast(`${add.length} new sample${add.length>1?'s':''} from your mining run · in the list now`);
 if(typeof loadTaste==='function')loadTaste();
 if(['S','C','R','F'].includes(st.tab)){const m=document.querySelector('main'),y=m?m.scrollTop:0;render();if(m)m.scrollTop=y}
 return add.length}
window.liveCheck=liveCheck;setInterval(liveCheck,60000);setTimeout(liveCheck,8000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)liveCheck()});

// ---------- drag samples out (into Live, Finder, anywhere that takes files) and ↗ show in Finder
let LIBROOT=null;if(SERVED)api('api/libroot').then(r=>LIBROOT=r.root).catch(()=>{});
document.addEventListener('dragstart',e=>{const row=e.target.closest&&e.target.closest('.row[data-i]');if(!row||!SERVED)return;const s=S[+row.dataset.i],p=s[F.path],name=p.split('/').pop();
 const dt=e.dataTransfer;dt.effectAllowed='copy';
 dt.setData('DownloadURL',`audio/wav:${name}:${location.origin}/${p.split('/').map(encodeURIComponent).join('/')}`);  // a file promise: Finder, the desktop, most apps
 if(LIBROOT){const abs=LIBROOT+'/'+p;dt.setData('text/uri-list','file://'+abs.split('/').map(encodeURIComponent).join('/'));dt.setData('text/plain',abs)}  // the real file, for apps that take a path
 toast('drop it in Live, Finder or anywhere that takes audio files · if Live won’t take it, ↗ Finder in the sample panel')});
// rows are draggable (but not their buttons, sliders or text you select)
new MutationObserver(()=>document.querySelectorAll('#list .row[data-i]:not([draggable])').forEach(r=>r.setAttribute('draggable','true'))).observe($('list'),{subtree:true,childList:true});
document.addEventListener('click',async e=>{const b=e.target.closest('#reveal');if(!b)return;e.stopPropagation();const i=st.sel;if(i==null)return;
 try{await api('api/reveal',{path:S[i][F.path]});toast('shown in Finder: drag it from there into Live')}catch(err){toast("couldn't show it: "+err.message)}},true);

// ---------- recent actions, with undo (★, ✕, moving a sample to another category, collections, deletes)
// ⌘Z undoes the sketch when the sketchpad is open, otherwise the last action here
const ACTS=[];window.ACT_QUIET=false;
function actPush(label,undo,toastIt){ACTS.push({label,undo,t:Date.now(),done:false});if(ACTS.length>50)ACTS.shift();
 const b=$('actbtn');if(b){b.hidden=false;b.textContent='🕘 '+ACTS.filter(a=>!a.done).length}
 if(toastIt){const t=$('toast');t.innerHTML=`${esc(label)} <button id="actundo">undo</button>`;t.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>t.hidden=true,6000);
  const a=ACTS[ACTS.length-1];$('actundo').onclick=()=>actUndo(a)}}
window.actPush=actPush;
async function actUndo(a){if(!a||a.done)return;a.done=true;window.ACT_QUIET=true;try{await a.undo()}finally{window.ACT_QUIET=false}
 const b=$('actbtn');if(b)b.textContent='🕘 '+ACTS.filter(x=>!x.done).length;toast('undone: '+a.label);const p=$('actpop');if(p&&!p.hidden)actPop()}
const nameOf=p=>{const i=byPath.get(p);return i==null?p.split('/').pop():`${S[i][F.artist]} — ${S[i][F.sub]}`};
function actPop(){let p=$('actpop');if(!p){p=document.createElement('div');p.id='actpop';p.className='colpop';document.body.appendChild(p)}
 const r=$('actbtn').getBoundingClientRect();p.style.left=(r.left)+'px';p.style.top=(r.bottom+6+scrollY)+'px';p.style.width='330px';p.hidden=false;
 const list=ACTS.slice().reverse();
 p.innerHTML=`<div class="sub" style="margin-bottom:6px">Recent actions (newest first)</div>${list.map((a,k)=>`<div class="colrow" style="justify-content:space-between"><span style="${a.done?'opacity:.45;text-decoration:line-through':''}">${esc(a.label)} <span class="sub">${Math.max(1,Math.round((Date.now()-a.t)/60000))} min</span></span>${a.done?'':`<button data-actu="${ACTS.length-1-k}">undo</button>`}</div>`).join('')||'<div class="sub">nothing yet</div>'}`;
 p.onclick=e=>{const b=e.target.closest('[data-actu]');if(b){e.stopPropagation();actUndo(ACTS[+b.dataset.actu])}}}
document.addEventListener('click',e=>{if(e.target.closest('#actbtn')){e.stopPropagation();const p=$('actpop');if(p&&!p.hidden){p.hidden=true;return}actPop();return}
 const p=$('actpop');if(p&&!p.hidden&&!e.target.closest('#actpop'))p.hidden=true},true);
// ★ and ✕ (the page's own functions, wrapped so every way of starring is recorded)
const _toggleFavA=toggleFav;toggleFav=async function(path,id,label){const was=FAV.has(path);const r=await _toggleFavA(path,id,label);
 if(!window.ACT_QUIET)actPush(`${was?'unstarred':'starred'} ${nameOf(path)}`,()=>toggleFav(path,id,label));return r};
const _toggleDisA=toggleDislike;toggleDislike=function(path,id){const was=TASTE.disliked.has(path);const r=_toggleDisA(path,id);
 if(!window.ACT_QUIET)actPush(`${was?'un-✕':'✕'} ${nameOf(path)}`,()=>toggleDislike(path,id),!was);return r};

// ---------- the keyboard: ↑/↓ (J/K) move through the list with a preview, Enter edit, F ★, X ✕, C 📁, A sketch, / search, ? help
let KPREVIEW=lsj('atlasKPreview',true),kPreviewT=null;
const typing=e=>['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable;
const padsOpen=()=>$('pads')&&!$('pads').hidden;  // the pads use the letter keys
const keyTarget=()=>st.sel!=null?st.sel:(NP&&!NP.edit&&NP.i!=null&&players.size?NP.i:null);
function kMove(d){clearTimeout(kPreviewT);const rows=[...document.querySelectorAll('#list .row[data-i]')];if(!rows.length)return;
 let k=rows.findIndex(r=>+r.dataset.i===st.sel);k=k<0?(d>0?0:rows.length-1):Math.max(0,Math.min(rows.length-1,k+d));
 const i=+rows[k].dataset.i;select(i,'list');rows[k].scrollIntoView({block:'nearest'});if(!KPREVIEW)return;
 if(PROJ.on&&SERVED&&(PROJ.key||PROJ.bpm))kPreviewT=setTimeout(()=>{if(st.sel===i)toggle(i,null,{loop:false})},120);
 else toggle(i,null,{loop:false})}
function kHelp(){let p=$('khelp');if(p){p.hidden=!p.hidden;return}p=document.createElement('div');p.id='khelp';p.className='colpop';p.style.cssText+=';left:50%;top:80px;transform:translateX(-50%);width:420px;position:fixed';
 const rows=[['↓ ↑ or J K','next / previous sample (with a preview)'],['P','preview while moving: '+(KPREVIEW?'on':'off')],['Enter','edit the selected sample'],['Space','stop · on Mashup: play / stop'],['F','★ favourite'],['X','✕ not for me'],['C','📁 add to your last collection'],['A','＋ add to the sketchpad'],['/','search'],['Esc','unselect · close'],['Backspace','back to the previous sample'],['← →','variations (when shown)'],['T','next take (when a sample has takes)'],['⌘Z  ⌘⇧Z','undo / redo (the sketch when the sketchpad is open)'],['⌘S','save the sketch'],['?','this list']];
 p.innerHTML=`<div style="display:flex;justify-content:space-between;margin-bottom:6px"><b>Keyboard</b><button id="khclose">✕</button></div><div style="display:grid;grid-template-columns:110px 1fr;gap:4px 10px">${rows.map(([k,v])=>`<code>${k}</code><span>${v}</span>`).join('')}</div>`;
 document.body.appendChild(p);$('khclose').onclick=()=>p.hidden=true}
document.addEventListener('keydown',e=>{if(e.metaKey||e.ctrlKey||e.altKey||typing(e))return;
 if(padsOpen()&&/^[a-z0-9]$/i.test(e.key))return;
 const k=e.key;
 if(k==='ArrowDown'||k==='j'){e.preventDefault();kMove(1);return}
 if(k==='ArrowUp'||k==='k'){e.preventDefault();kMove(-1);return}
 if(k==='?'){e.preventDefault();kHelp();return}
 if(k==='/'){e.preventDefault();$('search').focus();return}
 if(k==='p'||k==='P'){KPREVIEW=!KPREVIEW;clearTimeout(kPreviewT);try{localStorage.setItem('atlasKPreview',JSON.stringify(KPREVIEW))}catch(err){}toast('preview while moving: '+(KPREVIEW?'on':'off'));return}
 const i=keyTarget();if(i==null)return;const s=S[i];
 if(k==='Enter'&&st.sel!=null){e.preventDefault();const b=$('edopen');if(b)b.click();return}
 if(k==='f'||k==='F'){toggleFav(s[F.path],s[F.id],`${s[F.artist]} — ${s[F.title]} · ${s[F.sub]}`);setTimeout(()=>{drawNP();mark()},60);return}
 if(k==='x'||k==='X'){toggleDislike(s[F.path],s[F.id]);return}
 if(k==='a'||k==='A'){skAdd(i);return}
 if(k==='c'||k==='C'){if(!SERVED)return;if(!COLLAST||!COLS.some(c=>c.name===COLLAST)){toast('use 📁 once to pick a collection; then C adds to it');return}
  colToggle(COLLAST,i,!colsOf(s[F.path]).includes(COLLAST))}});

// ---------- slice a drum loop into pads: one pad per hit, on the step where it falls in the original (so it plays the
// loop back, now re-sequenceable and at the sketch's tempo without stretching)
async function sliceLoop(i){const s=S[i];let r;try{r=await api('api/slices?path='+encodeURIComponent(s[F.path])+'&n=16')}catch(e){toast("couldn't slice it: "+e.message);return}
 const bpm=s[F.bpm]||PROJ.bpm||120,st=60/bpm/4,bars=Math.max(1,Math.min(2,s[F.bars]||Math.round(s[F.dur]/(st*16))||1));
 if(!PROJ.bpm){PROJ.bpm=bpm;try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj()}
 const old=drumLane();if(old&&old.pads.length){SK.lanes.splice(SK.lanes.indexOf(old),1);setTimeout(()=>toast('the drum lane was replaced · ⌘Z brings it back'),500)}
 const l=drumLane(true);if(!l){toast('the sketchpad holds 8 lanes');return}l.bars=bars;
 r.slices.forEach(([t0,t1],k)=>{const idx=Math.round(t0/st);if(idx>=16*bars||l.pads.length>=16)return;const steps=new Array(DSTEPS).fill(0);steps[idx]=1;
  l.pads.push({i,path:s[F.path],label:`slice ${k+1}`,start:t0,end:t1,auto:false,db:0,mute:false,steps})});
 SK.open=true;drawSK();drawProj();await drumLoad(l);drawSK();toast(`${l.pads.length} slices, each on its step · move, retune or drop them`)}
document.addEventListener('click',e=>{if(!e.target.closest('#sliceit'))return;e.stopPropagation();if(st.sel!=null)sliceLoop(st.sel)},true);

// ---------- 💡 why this? (taste.why): how the taste model got to this sample's rank, in its own numbers
let WHY_OPEN=false;
const whyName=p=>{const j=byPath.get(p);return j==null?esc(p.split('/').pop()):`<a href="#" data-go2="${j}">${esc(S[j][F.sub])} · ${esc(S[j][F.artist])} — ${esc(S[j][F.title])}</a>`};
async function whyShow(i){const box=$('whybox');if(!box)return;box.hidden=false;box.innerHTML='<span class="sub">asking the taste model…</span>';let r;
 try{r=await api('api/why?path='+encodeURIComponent(S[i][F.path]))}catch(e){box.textContent="couldn't: "+e.message;return}if(st.sel!==i||!$('whybox'))return;
 if(r.error){box.textContent=r.error;return}
 const pa=r.parts,pn=v=>`${v>=0?'+':''}${v.toFixed(1)}`;
 const up=(r.reasons||[]).filter(x=>x.pull>0),down=(r.reasons||[]).filter(x=>x.pull<0);
 const songTxt=r.song.liked||r.song.passed?`its song: you liked ${r.song.liked} and passed over ${r.song.passed} of its other samples`:"you haven't rated anything else from its song";
 box.innerHTML=`<b>${r.top<50?`In your top ${r.top<1?r.top.toFixed(1):Math.round(r.top)}%`:`In your bottom ${Math.round(100-r.top)}%`}</b> of ${S.length.toLocaleString()} samples, from ${r.n_labels.toLocaleString()} ratings and listens (${r.n_pos} liked).
  ${pa?`<div class="whybars">${[['the model',pa.model,'what it has learned from everything you rated: sound, type, quality, style'],['close to a like',pa.close,'how close it is to the single liked sample it most resembles'],['its song',pa.song,'how you rated the other samples cut from the same song']].map(([n,v,t])=>`<div title="${t}"><span>${n}</span><i style="--w:${Math.min(100,Math.abs(v)*16)}%" class="${v<0?'neg':''}"></i><span>${pn(v)}</span></div>`).join('')}</div>`:''}
  ${up.length?`<div>pulled up by <b>${up.map(x=>esc(x.what)).join(', ')}</b>${down.length?`; down by <b>${down.map(x=>esc(x.what)).join(', ')}</b>`:''}</div>`:''}
  ${(r.like=(r.like||[]).filter(x=>!GONE.has(byPath.get(x.path))).slice(0,3)).length?`<div>sounds closest to what you liked: ${r.like.map(x=>`${whyName(x.path)} <span class="sub">(${Math.round(x.sim*100)}%)</span>`).join(' · ')}</div>`:''}
  <div class="sub">${songTxt}</div>`}
document.addEventListener('click',e=>{if(!e.target.closest('#whybtn'))return;e.stopPropagation();const b=$('whybox');
 if(b&&!b.hidden){b.hidden=true;WHY_OPEN=false;return}WHY_OPEN=true;if(st.sel!=null)whyShow(st.sel)},true);

// ---------- galaxy
let GAL=null,GV={x:0,y:0,z:1},GH=null,GTASTE=false,GHOVER=true;
async function renderGalaxy(){const L=$('list');$('count').textContent='sample galaxy';
 L.innerHTML=`<div class="galaxy" id="gal"><canvas id="galc"></canvas><div class="gl" id="gll">loading the map…</div><div class="gtip" id="gtip" hidden></div></div>`;
 if(!GAL){try{const g=await api('api/galaxy');GAL=g.xy}catch(e){$('gll').textContent='map unavailable: '+e.message;return}}
 if(st.tab!=='G')return;galSetup();galDraw()}
function galPts(){const keep=new Set(filtered()),out=[];S.forEach((s,i)=>{let p=GAL[s[F.path]];if(!p&&s[F.root]&&BYID.has(s[F.root]))p=GAL[S[BYID.get(s[F.root])][F.path]];if(p)out.push([i,p[0],p[1],keep.has(i)])});return out}
let GP=[];
function galXY(c,x,y){const W=c.clientWidth,H=c.clientHeight,m=24,s=Math.min(W,H)-2*m;return[(x-.5-GV.x)*GV.z*s+W/2,(y-.5-GV.y)*GV.z*s+H/2]}
function galSetup(){const c=$('galc'),tip=$('gtip');GP=galPts();
 $('gll').innerHTML=`${hq('galaxy')} ${GP.filter(p=>p[3]).length.toLocaleString()} samples by sound — nearby = similar · wheel zoom · drag pan · click opens<br>
 <label style="pointer-events:auto"><input type="checkbox" id="ghov" ${GHOVER?'checked':''}> hover to play</label> <label style="pointer-events:auto"><input type="checkbox" id="gtaste" ${GTASTE?'checked':''}> show taste</label>
 <span style="pointer-events:auto">${CATS.map(cn=>`<span class="badge" style="background:${col(cn)}">${AB[cn]}</span>`).join('')}</span> <span>★ = favourite (ringed)</span>`;
 $('gll').style.pointerEvents='auto';$('ghov').onchange=e=>GHOVER=e.target.checked;$('gtaste').onchange=e=>{GTASTE=e.target.checked;galDraw()};
 let drag=null,hoverT=null,last=null;
 const near=e=>{const r=c.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;let best=null,bd=81;
  for(const p of GP){if(!p[3])continue;const[x,y]=galXY(c,p[1],p[2]);const d=(x-mx)**2+(y-my)**2;if(d<bd){bd=d;best=p}}return best};
 c.onwheel=e=>{e.preventDefault();const r=c.getBoundingClientRect(),W=c.clientWidth,H=c.clientHeight,s=Math.min(W,H)-48,f=e.deltaY>0?0.85:1.18;
  const mx=(e.clientX-r.left-W/2)/(GV.z*s)+GV.x,my=(e.clientY-r.top-H/2)/(GV.z*s)+GV.y;GV.z=Math.max(0.8,Math.min(60,GV.z*f));
  GV.x=mx-(e.clientX-r.left-W/2)/(GV.z*s);GV.y=my-(e.clientY-r.top-H/2)/(GV.z*s);galDraw()};
 c.onmousedown=e=>{drag={x:e.clientX,y:e.clientY,gx:GV.x,gy:GV.y,moved:false}};
 c.onmouseup=()=>{setTimeout(()=>{drag=null},0)};
 c.onmousemove=e=>{if(drag&&e.buttons){const s=Math.min(c.clientWidth,c.clientHeight)-48,dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
   GV.x=drag.gx-dx/(GV.z*s);GV.y=drag.gy-dy/(GV.z*s);galDraw();return}
  const p=near(e);GH=p;galDraw();if(!p){tip.hidden=true;clearTimeout(hoverT);last=null;return}const i=p[0],[x,y]=galXY(c,p[1],p[2]);
  tip.hidden=false;tip.style.left=Math.min(x+12,c.clientWidth-260)+'px';tip.style.top=(y+10)+'px';
  tip.innerHTML=`<span class="badge" style="background:${col(S[i][F.cat])}">${AB[S[i][F.cat]]}</span>${esc(S[i][F.sub])} · ${S[i][F.cam]||'—'} · ${esc(S[i][F.artist])} — ${esc(S[i][F.title])}`;
  if(GHOVER&&last!==i){clearTimeout(hoverT);last=i;hoverT=setTimeout(()=>{if(GH&&GH[0]===i&&!players.has(i))toggle(i)},160)}};
 c.onmouseleave=()=>{tip.hidden=true;GH=null;galDraw()};
 c.onclick=e=>{if(drag&&drag.moved)return;const p=near(e);if(p)select(p[0],'list')};
 }
window.addEventListener('resize',()=>{if(st.tab==='G')galDraw()});
let GCOL=null,galTaste={src:null,min:0,max:1};
function galDraw(){rafOnce('gal',galPaint)}
function galPaint(){
 PERF.gal++;
 const c=$('galc');if(!c)return;
 const dpr=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight,w=Math.floor(W*dpr),h=Math.floor(H*dpr),g=c.getContext('2d');
 if(c.width!==w||c.height!==h){c.width=w;c.height=h}else g.setTransform(1,0,0,1,0,0);
 g.scale(dpr,dpr);
 g.fillStyle='#0b0d10';g.fillRect(0,0,W,H);
 if(!GCOL){GCOL={};for(const cat of CATS)GCOL[cat]=catColor(cat)}
 const src=TASTE.score;
 if(galTaste.src!==src){
  let min=0,max=1;
  for(const value of Object.values(src||{})){min=Math.min(min,value);max=Math.max(max,value)}
  galTaste={src,min,max}
 }
 const {min:tmin,max:tmax}=galTaste;
 for(const p of GP){if(p[3])continue;const[x,y]=galXY(c,p[1],p[2]);if(x<-5||y<-5||x>W+5||y>H+5)continue;g.fillStyle='rgba(255,255,255,.05)';g.fillRect(x-1,y-1,2,2)}
 const r0=Math.min(5,1.6+GV.z*0.25);
 for(const p of GP){if(!p[3])continue;const i=p[0],path=S[i][F.path];const[x,y]=galXY(c,p[1],p[2]);if(x<-5||y<-5||x>W+5||y>H+5)continue;
  const dis=TASTE.disliked.has(path);g.globalAlpha=dis?0.15:0.85;
  if(GTASTE){const v=src[path];const t=v==null?0:(v-tmin)/(tmax-tmin+1e-9);g.fillStyle=`hsl(${30+t*0},${40+t*60}%,${18+t*55}%)`}else g.fillStyle=GCOL[S[i][F.cat]];
  g.beginPath();g.arc(x,y,r0,0,7);g.fill();
  if(FAV.has(path)){g.globalAlpha=1;g.strokeStyle='#fff';g.lineWidth=1.5;g.beginPath();g.arc(x,y,r0+2.5,0,7);g.stroke()}
  if(players.has(i)||st.sel===i){g.globalAlpha=1;g.strokeStyle='#e0a458';g.lineWidth=2;g.beginPath();g.arc(x,y,r0+5,0,7);g.stroke()}}
 g.globalAlpha=1;if(GH){const[x,y]=galXY(c,GH[1],GH[2]);g.strokeStyle='#fff';g.lineWidth=1;g.beginPath();g.arc(x,y,r0+4,0,7);g.stroke()}}
setInterval(()=>{if(st.tab==='G'&&players.size)galDraw()},500);

// ---------- YouTube scout
let ytT=null,ytRes=[],ytD={},ytInbox=null,ytSig='',ytCur='',ytQ='',ytSty='',ytOpen=new Set(),ytMode=(()=>{try{return localStorage.getItem('ytMode')||'voice'}catch(e){return 'voice'}})();
const YTM={voice:{label:'🎤 voice',ph:'e.g. acapella cover · singing in my car · choir rehearsal',bars:['voice','band/talk']},
 pads:{label:'🌫 pads & textures',ph:'e.g. ps1 ambient soundtrack · organ drone · 70s synth soundtrack',bars:['ambient','drums/talk/voice']},
 guided:{label:'🧭 your styles',ph:'e.g. rare neo soul · modal jazz 1960s',bars:['your styles','talk/noise']}};
const ytTime=s=>Math.floor(s/60)+':'+String(Math.round(s%60)).padStart(2,'0');
const ytAgo=t=>{if(!t)return'';const d=(Date.now()-new Date(t.replace(' ','T')+'Z'))/864e5;return d<1?'today':d<2?'yesterday':Math.floor(d)+' days ago'};
async function ytLoad(){try{ytD=await api('api/ytscout')}catch(e){ytD={results:[]}}ytRes=ytD.results||[];if(!ytInbox)ytInbox=new Set();
 ytRes.forEach(r=>{if(r.auto&&!r.seen&&!ytGone(r)&&r.status!=='ingested')ytInbox.add(r.id)});const sig=ytRes.map(r=>r.id+r.status).join();const ch=sig!==ytSig;ytSig=sig;return ch}
async function renderScout(){$('count').textContent='YouTube scout';const L=$('list');
 if(!SERVED){L.innerHTML='<div class="empty">The scout needs the local server.</div>';return}
 await ytLoad();if(st.tab!=='Y')return;const d=ytD,M=YTM[ytMode],pre=(d.presets&&d.presets[ytMode])||[],lr=d.learned||{};
 L.innerHTML=`<div class="ytwrap"><div class="ythead">
 <div class="chips" style="align-items:center"><span class="sub">search for</span>${Object.entries(YTM).map(([k,m])=>`<button data-ytmode="${k}" class="${k===ytMode?'on':''}">${m.label}</button>`).join('')} ${hq('scout')}<span style="flex:1"></span>
  <label class="sub" title="once a day while the app is open, it runs a few searches by itself: more like your latest add, your best search again, and one you haven't tried"><input type="checkbox" id="ytauto" ${d.auto&&d.auto.enabled?'checked':''}> daily finds</label>
  <span class="sub" title="✕ and add source teach the ranking: closer to what you added, further from what you dismissed">${lr.added||lr.dismissed?`learned from ${lr.added||0} add${lr.added===1?'':'s'} · ${lr.dismissed||0} ✕`:'✕ and add source teach the ranking'}</span></div>
 <div class="edrow"><input id="ytq" placeholder="${M.ph}" style="flex:1;min-width:200px" value="${esc(ytQ.startsWith('more like: ')?'':ytQ)}">${ytMode==='guided'?ytStyleSel(d):''}<select id="ytn" title="how many new videos to listen to"><option>10</option><option selected>15</option><option>25</option></select><button id="ytgo" class="pill">scout</button></div>
 ${ytMode==='guided'?ytGuided(d):`<div class="chips">${pre.map(p=>`<button data-ytp="${esc(p)}">${esc(p)}</button>`).join('')}</div>`}<div id="ytjobs"></div>
 <div class="edrow sub"><label><input type="checkbox" id="ytsk"> show dismissed & filtered</label><span id="ytcount"></span></div></div><div id="ytlist"></div></div>`;
 $('ytgo').onclick=()=>ytStart($('ytq').value.trim());$('ytq').onkeydown=e=>{if(e.key==='Enter')$('ytgo').click()};$('ytsk').onchange=ytDraw;if($('ytsty'))$('ytsty').onchange=e=>{ytSty=e.target.value};
 $('ytauto').onchange=e=>api('api/ytscout/auto',{enabled:e.target.checked}).then(()=>toast(e.target.checked?'daily finds on':'daily finds off')).catch(err=>toast('error: '+err.message));
 ytDraw();ytPoll();if(ytMode==='guided')ytRelated()}
async function ytRelated(){const el=$('ytrel');if(!el)return;let r=ytRelated.cache;if(!r){try{r=await api('api/related-artists')}catch(e){r={artists:[]}}ytRelated.cache=r}
 const el2=$('ytrel');if(!el2)return;const A=(r.artists||[]).slice(0,18);
 el2.innerHTML=A.length?`<div class="chips">${A.map(a=>`<button data-ytp="${esc(a.name)}" data-yts="" title="listeners of ${esc(a.because.join(', '))} play them too${a.comment?' · '+esc(a.comment):''}">${esc(a.name)} <span style="opacity:.6">← ${esc(a.because[0])}</span></button>`).join('')}</div>`:'none found';}
function ytStyleSel(d){const P=(d.profile&&d.profile.styles)||[];if(!P.length)return'';
 return `<select id="ytsty" title="what to listen for"><option value="">listen for all your styles</option>${P.map(p=>`<option value="${esc(p.full)}" ${p.full===ytSty?'selected':''}>${esc(p.name)} (${Math.round(p.share*100)}%${p.era?' · '+p.era:''})</option>`).join('')}</select>`}
function ytGuided(d){const P=(d.profile&&d.profile.styles)||[],G=d.guided||[];
 if(!P.length)return `<div class="sub">${d.profile&&d.profile.ready===false?'Your songs\' styles haven\'t been analysed yet: run <b>Tag styles</b> on the ⚙ Processing page (about an hour for the whole collection).':'Like (★) some samples first: your styles come from the songs behind the samples you like.'}</div>`;
 return `<div class="chips">${G.map(g=>`<button data-ytp="${esc(g.query)}" data-yts="${esc(g.style)}" title="listens for ${esc(g.style.split('---')[1])}">${esc(g.query)}</button>`).join('')}</div>
 <details class="sub"><summary>artists related to yours · your styles</summary><div style="display:grid;gap:8px;margin-top:6px">
 <div>Artists you don't have that listeners pair with yours (ListenBrainz); click one to scout it:<div id="ytrel" style="margin-top:4px">looking up… (about 20 s the first time)</div></div>
 <div style="line-height:1.9">Your styles, by how much more often they turn up in songs you like than in your whole collection (✕ if one isn't really yours): ${P.slice(0,12).map(p=>`<span style="white-space:nowrap;margin-right:10px"><b>${esc(p.name)}</b> ${p.lift}×<button data-hidesty="${esc(p.full)}" title="not one of my styles: leave it out of the searches" style="border:0;background:none;color:var(--mute);cursor:pointer;padding:0 0 0 5px">✕</button></span>`).join('')}</div></div></details>`}
document.addEventListener('click',async e=>{const h=e.target.closest('[data-hidesty]');if(!h)return;h.disabled=true;
 try{await api('api/styles/hide',{style:h.dataset.hidesty,hide:true});toast(h.dataset.hidesty.split('---')[1]+' left out of your styles');renderScout()}catch(err){toast('error: '+err.message)}});
const ytGone=r=>r.status==='skipped'||r.status==='filtered';
function ytRow(r){const bl=(YTM[r.mode||'voice']||YTM.voice).bars,M=r.moments||[],pk=r.picks||0;
 return `<div class="yt${ytGone(r)?' dim':''}"><div class="ymoms">${M.map((m,k)=>`<button class="play" data-ytsnip="${esc(m[1]||'')}" data-ytt="${esc(r.title||'')}" data-ytid="${esc(r.id)}" title="${['best','second','third'][k]} moment">▶ ${ytTime(m[0])}</button>`).join('')}</div>
  <div style="min-width:0"><div class="name">${r.status==='ingested'?'<span class="badge" style="background:var(--acc)">added</span> ':''}${r.status==='filtered'?'<span class="badge">filtered</span> ':''}<a href="${esc(r.url)}&t=${Math.floor(M[0]?M[0][0]:0)}s" target="_blank" rel="noopener" style="color:inherit" title="open on YouTube at the best moment">${esc(r.title||r.id)}</a></div>
  <div class="meta">${r.style?`🧭 ${esc(r.style.split('---')[1])} · `:''}${esc(r.channel||'')}${r.views!=null?' · '+Number(r.views).toLocaleString()+' views':''}${r.duration?' · '+ytTime(r.duration):''}${r.mine?` · <span style="color:var(--acc)" title="you have music by them">you have ${esc(r.mine)}</span>`:''}</div>
  <div class="bars"><span>${bl[0]}</span><i style="width:${Math.max(2,r.vocal*120)}px"></i><span>${bl[1]}</span><i style="width:${Math.max(2,r.neg*120)}px;background:#d96c6c"></i><span>your taste</span><i style="width:${Math.max(2,(r.taste||0)*120)}px;background:var(--acc)"></i>${pk?`<span title="like what you added (+) or what you dismissed (−)">your picks ${pk>0?'+':'−'}</span><i style="width:${Math.max(2,Math.min(60,Math.abs(pk)*60))}px;background:${pk>0?'#7fc98f':'#d96c6c'}"></i>`:''}</div></div>
  <div class="yact"><span class="score" title="rank among your ${YTM[r.mode||'voice'].label} finds (100 = best), including what your adds and ✕ taught it">${r.pct}</span><button data-ytmore="${esc(r.id)}" data-ytt="${esc(r.title||'')}" title="more like this: its channel's other uploads, and a search built from its title">🔭 more</button>${r.status==='ingested'?'':`<button data-ytadd="${esc(r.url)}" data-ytid="${esc(r.id)}" data-ytdur="${r.duration||0}" class="pill" title="download it and mine it into the library">add source →</button>`}<button data-ytskip="${esc(r.id)}" title="not for me (teaches the ranking)">✕</button></div></div>`}
function ytDraw(){const el=$('ytlist');if(!el)return;const sk=$('ytsk')&&$('ytsk').checked,vis=r=>sk||!ytGone(r);
 const inbox=ytRes.filter(r=>ytInbox&&ytInbox.has(r.id)&&!ytGone(r));
 const G=new Map();ytRes.filter(vis).filter(r=>!(ytInbox&&ytInbox.has(r.id))).forEach(r=>{const q=r.query||'?';if(!G.has(q))G.set(q,{q,mode:r.mode||'voice',style:r.style||'',rows:[],t:''});const g=G.get(q);g.rows.push(r);if((r.created_at||'')>g.t)g.t=r.created_at||''});
 const groups=[...G.values()].sort((a,b)=>(b.q===ytQ)-(a.q===ytQ)||b.t.localeCompare(a.t));
 const hid=ytRes.filter(ytGone).length;
 if($('ytcount'))$('ytcount').textContent=`${ytRes.length-hid} finds from ${G.size} searches${hid&&!sk?` · ${hid} dismissed or filtered (playlists, mixes, music videos)`:''}`;
 let h='';
 if(inbox.length)h+=`<div class="ygrp inbox"><div class="yghead"><b>📥 ${inbox.length} new find${inbox.length===1?'':'s'}</b><span class="sub">found by itself (daily finds)</span><span style="flex:1"></span><button data-ytseen>mark all seen</button></div>${inbox.slice(0,12).map(ytRow).join('')}</div>`;
 h+=groups.map(g=>{const open=ytOpen.has(g.q)||g.q===ytQ,shown=open?g.rows:g.rows.slice(0,4),more=g.q.startsWith('more like: ');
  return `<div class="ygrp"><div class="yghead"><b>${more?'🔭 ':''}${esc(g.q)}</b><span class="sub">${YTM[g.mode].label} · ${g.rows.length} find${g.rows.length===1?'':'s'} · ${ytAgo(g.t)}</span><span style="flex:1"></span>${more?'':`<button data-ytagain="${esc(g.q)}" data-ytm="${g.mode}" data-yts="${esc(g.style)}" title="search again: listens to the next videos down YouTube's results">dig deeper</button>`}</div>
  ${shown.map(ytRow).join('')}${g.rows.length>shown.length?`<button class="ymore" data-ytopen="${esc(g.q)}">show all ${g.rows.length}</button>`:''}</div>`}).join('');
 el.innerHTML=h||`<div class="empty">${ytPoll.wasRunning?'Listening…':'No finds yet: pick a search above, or type your own.'}</div>`;
 if(ytCur&&players.has('yt'))el.querySelectorAll('[data-ytsnip]').forEach(b=>{if(b.dataset.ytsnip===ytCur)b.classList.add('playing')})}
async function ytStart(q,mode,style){if(!q)return;if(mode&&mode!==ytMode){ytMode=mode;try{localStorage.setItem('ytMode',ytMode)}catch(e){}}
 ytQ=q;ytOpen.add(q);
 try{await api('api/ytscout',{query:q,n:+(($('ytn')||{}).value||15),mode:ytMode,style:ytMode==='guided'?(style!=null?style:($('ytsty')?$('ytsty').value:ytSty)):''});toast('scouting “'+q+'”…');ytDraw();ytPoll()}catch(e){toast('error: '+e.message)}}
async function ytPoll(){clearTimeout(ytT);if(st.tab!=='Y')return;let js=[];try{js=await api('api/jobs?kind=ytscout')}catch(e){}
 const el=$('ytjobs');if(!el)return;const run=js.filter(j=>j.running);
 el.innerHTML=js.slice(-1).map(j=>{const sms=j.tail.map(t=>t.startsWith('SUMMARY ')?JSON.parse(t.slice(8)):null).filter(Boolean),sm=sms.pop();
  const txt=sm&&!j.running?`${sm.listened} listened to · ${sm.already} already scouted${sm.filtered?` · ${sm.filtered} skipped (playlists, mixes, music videos)`:''}${sm.too_short?` · ${sm.too_short} too short`:''}${sm.failed?` · ${sm.failed} failed to download`:''}`:j.tail.slice(-2).map(esc).join('\n');
  return `<div class="prov"><b>${esc(j.target)}</b> — ${j.running?'listening…':'done'}<div class="meta" style="white-space:pre-wrap">${txt}</div></div>`}).join('');
 if(run.length||ytPoll.wasRunning){if(await ytLoad())ytDraw()}
 ytPoll.wasRunning=run.length>0;if(run.length)ytT=setTimeout(ytPoll,2500)}
const ytSeen=ids=>{if(!ids.length)return;api('api/ytscout/seen',{ids}).catch(()=>{});ytRes.forEach(r=>{if(ids.includes(r.id))r.seen=1})};
document.addEventListener('click',async e=>{const ym=e.target.closest('[data-ytmode]');if(ym){ytMode=ym.dataset.ytmode;try{localStorage.setItem('ytMode',ytMode)}catch(err){}renderScout();return}
 const p=e.target.closest('[data-ytp]');if(p){$('ytq').value=p.dataset.ytp;if(p.dataset.yts!=null&&$('ytsty')){ytSty=p.dataset.yts;$('ytsty').value=ytSty}ytStart(p.dataset.ytp);return}
 const ag=e.target.closest('[data-ytagain]');if(ag){ytStart(ag.dataset.ytagain,ag.dataset.ytm,ag.dataset.yts);return}
 const op=e.target.closest('[data-ytopen]');if(op){ytOpen.add(op.dataset.ytopen);ytDraw();return}
 if(e.target.closest('[data-ytseen]')){ytSeen(ytRes.filter(r=>r.auto&&!r.seen).map(r=>r.id).concat([...(ytInbox||[])]));ytInbox=new Set();ytDraw();return}
 const mo=e.target.closest('[data-ytmore]');if(mo){mo.disabled=true;const t=mo.dataset.ytt||mo.dataset.ytmore;
  try{await api('api/ytscout/more',{id:mo.dataset.ytmore,title:t});ytQ='more like: '+t.slice(0,60);ytOpen.add(ytQ);ytSeen([mo.dataset.ytmore]);toast('listening for more like “'+t.slice(0,50)+'”…');ytDraw();ytPoll()}catch(err){toast('error: '+err.message)}return}
 const sn=e.target.closest('[data-ytsnip]');if(sn){if(!sn.dataset.ytsnip)return;if(players.has('yt')&&sn.classList.contains('playing')){stopAll();return}stopAll();
  const a=new Audio(url(sn.dataset.ytsnip));a.play().catch(()=>{if(players.get('yt')===a){players.delete('yt');sn.classList.remove('playing');toast('that preview is missing')}});players.set('yt',a);ytCur=sn.dataset.ytsnip;a.onended=()=>{players.delete('yt');ytCur='';document.querySelectorAll('[data-ytsnip].playing').forEach(b=>b.classList.remove('playing'));drawNP()};document.querySelectorAll('[data-ytsnip]').forEach(b=>b.classList.remove('playing'));sn.classList.add('playing');
  if(sn.dataset.ytid)ytSeen([sn.dataset.ytid]);setNP(sn.dataset.ytsnip,null,'scout preview · '+sn.dataset.ytt,null);return}
 const ad=e.target.closest('[data-ytadd]');if(ad){const du=+ad.dataset.ytdur||0;if(du>1800&&!confirm(`This video is ${ytTime(du)} long: adding it downloads and mines all of it. Add it anyway?`))return;ad.disabled=true;ad.textContent='adding…';try{await api('api/ingest',{target:ad.dataset.ytadd,drums:false});await api('api/ytscout/mark',{id:ad.dataset.ytid,status:'ingested'});
  ytRes.forEach(r=>{if(r.id===ad.dataset.ytid){r.status='ingested';r.seen=1}});ytDraw();toast('added: downloading & mining in the background (progress under ＋ add source). 🔭 more finds others like it.')}catch(err){toast('error: '+err.message)}return}
 const skp=e.target.closest('[data-ytskip]');if(skp){await api('api/ytscout/mark',{id:skp.dataset.ytskip,status:'skipped'}).catch(()=>{});ytRes.forEach(r=>{if(r.id===skp.dataset.ytskip){r.status='skipped';r.seen=1}});ytDraw()}});

// ================= sketchpad =================
const SK={lanes:[],playing:false,open:false,voices:[],timer:null,raf:0,master:null,nextBar:0,start:0,arr:'',sec:4};window.SK=SK;
const PERF={anim:0,peaks:0,skWave:0,gal:0,ir:0};
const RAFQ=new Map();
function rafOnce(key,fn){
 const pending=RAFQ.has(key);
 RAFQ.set(key,fn);
 if(!pending)requestAnimationFrame(()=>{const paint=RAFQ.get(key);RAFQ.delete(key);paint()})
}
const PEAKS=new WeakMap();  // at most eight waveform geometries per AudioBuffer
const WAVE_CANVASES=new WeakMap();
function reuseWaveCanvas(canvas,owner,attribute){
 if(!canvas)return null;
 const previous=WAVE_CANVASES.get(owner);
 if(!previous){WAVE_CANVASES.set(owner,canvas);return canvas}
 if(previous!==canvas){
  previous.setAttribute(attribute,canvas.getAttribute(attribute));
  canvas.replaceWith(previous)
 }
 return previous
}
function wavePeaks(buf,W,from,to,stride){
 W=Math.max(1,Math.floor(W));
 let cache=PEAKS.get(buf);
 if(!cache){cache=new Map();PEAKS.set(buf,cache)}
 const key=`${W}|${from}|${to}|${stride}`,cached=cache.get(key);
 if(cached)return cached;
 PERF.peaks++;
 const peaks=new Float32Array(W),data=buf.getChannelData(0),per=Math.max(1,Math.floor((to-from)/W));
 for(let x=0;x<W;x++){
  let peak=0;
  const end=Math.min(to,data.length,from+(x+1)*per);
  for(let k=from+x*per;k<end;k+=stride)peak=Math.max(peak,Math.abs(data[k]));
  peaks[x]=peak
 }
 if(cache.size>=8)cache.delete(cache.keys().next().value);
 cache.set(key,peaks);
 return peaks
}
function lruMap(max){
 const entries=new Map();
 return {
  has(key){return entries.has(key)},
  get(key){
   if(!entries.has(key))return;
   const value=entries.get(key);
   entries.delete(key);
   entries.set(key,value);
   return value
  },
  set(key,value){
   entries.delete(key);
   entries.set(key,value);
   if(entries.size>max)entries.delete(entries.keys().next().value)
  },
  delete(key){return entries.delete(key)},
  get size(){return entries.size}
 }
}
// ---------- arrangement: sections like "AABA", each SK.sec bars; every lane plays in the sections ticked on it (all by
// default). Empty = the sketch loops as one section. Playback, bounce, stems and the Live set all go through skBar.
const secAt=bar=>SK.arr?SK.arr[Math.floor(bar/SK.sec)%SK.arr.length]:'';
const laneOn=(l,bar)=>!SK.arr||!l.secs||l.secs.includes(secAt(bar));
const secLetters=()=>[...new Set(SK.arr.split(''))].sort();
const songBars=()=>SK.arr?SK.arr.length*SK.sec:0;
function secChips(l,k){if(!SK.arr)return'';return`<span class="secs" title="the sections this lane plays in">${secLetters().map(c=>`<button class="tbtn sec${!l.secs||l.secs.includes(c)?' on':''}" data-sksec="${k}:${c}">${c}</button>`).join('')}</span>`}
const np=$('np'),dock=document.createElement('div');dock.className='dock';np.parentNode.insertBefore(dock,np);
dock.insertAdjacentHTML('beforeend','<div class="sk" id="sk" hidden></div>');dock.appendChild(np);
$('skbtn').onclick=()=>{SK.open=!SK.open;drawSK();drawProj()};
const barLen=()=>240/(PROJ.bpm||120);
// a non-loop lane repeats every N bars: the shortest of 1/2/4/8/16 that fits the whole clip (so it never piles up on itself)
// repeat on the clip's own length in whole bars, so it comes back as it ends (powers of two left every lane
// silent together for bars at a time); a slightly longer clip's tail crossfades into the next pass
const skEvery=dur=>Math.max(1,Math.min(16,Math.round(dur/barLen())));
async function skAdd(i){if(!SERVED){toast('the sketchpad needs the local server');return}
 if(S[i][F.cat]==='Percussion'&&S[i][F.kind]!=='loop')return drumAdd(i);  // drum hits become pads in the drum lane
 if(SK.lanes.length>=8){toast('the sketchpad holds 8 lanes');return}
 if(SK.lanes.some(l=>l.path===S[i][F.path])){toast('already in the sketch');return}
 const patch={};if(!PROJ.key&&S[i][F.cam])patch.key=keyFromCam(S[i][F.cam]);if(!PROJ.bpm)patch.bpm=S[i][F.bpm]||120;if(Object.keys(patch).length){Object.assign(PROJ,patch);try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj()}
 const loop=S[i][F.kind]==='loop';
 const lane={i,path:S[i][F.path],db:0,mute:false,solo:false,every:loop?0:skEvery(S[i][F.dur]),offset:0,buf:null,state:'loading'};
 SK.lanes.push(lane);SK.open=true;drawSK();drawProj();await skLoad(lane);drawSK();toast(`added to the sketch (${SK.lanes.length})`)}
function skLoad(lane){return lane.loadPromise=skLoadBuffer(lane)}
async function skLoadBuffer(lane){
 if(lane.type==='drums'){await drumLoad(lane);return}
 if(lane.ctl)lane.ctl.abort();
 const ctl=lane.ctl=new AbortController();
 lane.state='loading';
 try{
  const path=conformURL(lane.path,lane.nat?'':PROJ.key,PROJ.bpm)+(lane.src?`&src=${lane.src}`:'');
  const response=await fetch(path,{signal:ctl.signal});
  if(lane.ctl!==ctl)return;
  const ab=await response.arrayBuffer();
  if(lane.ctl!==ctl)return;
  const buf=await AC.decodeAudioData(ab);
  if(lane.ctl!==ctl)return;
  let pulse=lane.pulse;
  if(S[lane.i]&&S[lane.i][F.kind]!=='loop'&&!pulse){
   pulse=await api('api/pulse?path='+encodeURIComponent(lane.path)).catch(()=>null);
   if(lane.ctl!==ctl)return
  }
  lane.buf=buf;lane.norm=skNorm(buf);lane.pulse=pulse;lane.att=null;lane.state='ok'
 }catch(e){
  if(lane.ctl!==ctl)return;
  lane.state='error'
 }finally{
  if(lane.ctl===ctl)lane.ctl=null
 }
 if(lane.db==null)lane.db=lane.vol!=null?Math.max(-24,Math.min(6,Math.round(20*Math.log10(Math.max(lane.vol,0.01)/0.8)*2)/2)):0
}
// relative volume: every lane is levelled to the same loudness when it loads, so 0 dB on every fader = equally loud;
// the fader then moves it relative to the others
function skNorm(b){let s=0,n=0;const g=Math.pow(10,-50/20);for(let c=0;c<b.numberOfChannels;c++){const d=b.getChannelData(c);for(let k=0;k<d.length;k+=8){const v=d[k];if(Math.abs(v)>g){s+=v*v;n++}}}
 const rms=n?Math.sqrt(s/n):0.05;return Math.min(6,0.07/Math.max(rms,1e-4))}
const laneGain=l=>(l.norm||1)*Math.pow(10,(l.db||0)/20);
const dbTxt=db=>`${db>0?'+':''}${(+db).toFixed(1)} dB`;
// where the sound really starts inside a (trimmed) clip: phrases often open with a breath or silence, so the
// attack, not the file's first sample, is what gets placed on the beat
function skAttack(l){const [r0,R]=skRegion(l),key=`${r0}|${R}`;if(l.att&&l.att.key===key)return l.att.v;
 // the first attack tick in the selection (the same ticks drawn on the waveform), else the first loud sample
 const first=skStrong(l,r0,r0+R)[0];if(first!=null){const v=Math.max(0,first-r0-0.01);l.att={key,v};return v}const sr=l.buf.sampleRate,a=Math.floor(r0*sr),b=Math.min(l.buf.length,a+Math.floor(Math.min(R,4)*sr));
 let pk=0;const chs=[...Array(l.buf.numberOfChannels).keys()].map(c=>l.buf.getChannelData(c));for(const d of chs)for(let k=a;k<b;k+=2)pk=Math.max(pk,Math.abs(d[k]));
 let at=a;outer:for(let k=a;k<b;k+=2)for(const d of chs)if(Math.abs(d[k])>0.2*pk){at=k;break outer}
 const v=Math.min(1,Math.max(0,(at-a)/sr-0.01));l.att={key,v};return v}
let reloadSeq=0,reloadT=null,reloadLanes=null,reloadPlay=false;
// Playback pauses at the first change and resumes after the latest load finishes.
function skReloadSoon(ms){
 if(!SK.lanes.length)return;
 const lanes=SK.lanes,was=SK.playing||(reloadLanes===lanes&&reloadPlay);
 if(SK.playing)skStop();
 reloadPlay=was;
 reloadLanes=lanes;
 reloadSeq++;
 for(const lane of lanes){
  if(lane.ctl){lane.ctl.abort();lane.ctl=null}
  lane.state='loading'
 }
 drawSK();
 clearTimeout(reloadT);
 reloadT=setTimeout(()=>{
  reloadT=null;
  if(lanes!==SK.lanes||!lanes.length){reloadLanes=null;reloadPlay=false;return}
  skReload(reloadPlay)
 },ms)
}
async function skReload(play){
 const seq=reloadSeq,lanes=SK.lanes,was=play||SK.playing;
 if(SK.playing)skStop();
 reloadPlay=was;
 lanes.forEach(skLoad);
 let pending;
 do{
  pending=lanes.map(l=>l.loadPromise);
  await Promise.all(pending);
  if(seq!==reloadSeq)return
 }while(lanes===SK.lanes&&lanes.some((l,k)=>l.loadPromise!==pending[k]));
 const resume=reloadPlay;
 reloadLanes=null;reloadPlay=false;
 if(lanes!==SK.lanes)return;
 drawSK();
 if(resume)skPlay()
}
// a soloed drum pad solos its lane too: you hear just that pad
const laneSolo=l=>l.solo||(l.type==='drums'&&l.pads.some(p=>p.solo));
function skGains(){const solo=SK.lanes.some(laneSolo);SK.lanes.forEach(l=>{if(l.g)l.g.gain.setTargetAtTime(l.mute||(solo&&!laneSolo(l))?0:laneGain(l),AC.currentTime,0.02)})}
if(Object.keys(D.sections||{}).length&&$('secsel'))$('secsel').hidden=false;  // the section filter, once sections exist
// ---------- sustain loops (loopfind.py): where a pad, drone or held chord loops seamlessly. D.loops[i] = [start, end, crossfade]
const LOOPS=D.loops||{},HOLDBUF=lruMap(24);
function bakeLoop(buf,a,b,xf){const sr=buf.sampleRate,A=Math.round(a*sr),B=Math.round(b*sr),N=Math.round(xf*sr),out=AC.createBuffer(buf.numberOfChannels,buf.length,sr);
 for(let c=0;c<buf.numberOfChannels;c++){const d=buf.getChannelData(c).slice();if(N>0&&A-N>=0)for(let k=0;k<N;k++){const g=Math.sin(k/N*Math.PI/2)**2;d[B-N+k]=d[B-N+k]*(1-g)+d[A-N+k]*g}out.copyToChannel(d,c)}return out}
// a lane's clip is conformed (re-pitched / stretched), so its loop points scale with its length
function laneHold(l){const lp=LOOPS[l.i];if(!l.hold||!lp||!l.buf)return null;if(l.hbuf&&l.hbuf.src===l.buf)return l.hbuf;const r=l.buf.duration/(S[l.i][F.dur]||l.buf.duration);
 const a=lp[0]*r,b=Math.min(l.buf.duration,lp[1]*r);if(b-a<0.05)return null;l.hbuf={src:l.buf,buf:bakeLoop(l.buf,a,b,lp[2]*r),a,b};return l.hbuf}
async function holdPlay(i,btn){if(players.has('hold')){stopAll();return}stopAll();const lp=LOOPS[i],p=S[i][F.path];btn.classList.add('on');
 if(!HOLDBUF.has(p))HOLDBUF.set(p,fetch(url(p)).then(r=>r.arrayBuffer()).then(b=>AC.decodeAudioData(b)).then(b=>bakeLoop(b,lp[0],lp[1],lp[2])));
 let buf;try{buf=await HOLDBUF.get(p)}catch(e){btn.classList.remove('on');toast('could not load it');return}AC.resume();
 const s=AC.createBufferSource(),g=AC.createGain();s.buffer=buf;s.loop=true;s.loopStart=lp[0];s.loopEnd=lp[1];s.connect(g);g.connect(AC.destination);s.start();
 players.set('hold',{pause(){const t=AC.currentTime;g.gain.setTargetAtTime(0,t,0.12);s.stop(t+0.8);btn.classList.remove('on')},duration:NaN});
 setNP(p,i,'∞ holding on its loop · '+(S[i][F.title]||''),null)}
document.addEventListener('click',e=>{const b=e.target.closest('#holdit');if(!b)return;e.stopPropagation();holdPlay(+b.dataset.i,b)});
// a lane can be trimmed to part of its clip: trim = [from, to] as fractions of the (conformed) clip
const skRegion=l=>{const d=l.buf.duration,[a,b]=l.trim||[0,1];return [a*d,Math.max(0.01,(b-a)*d)]};
function skVoice(ctx,dest,l,t,dur,arr,xf=0){const s=ctx.createBufferSource();s.buffer=l.buf;const h=laneHold(l);if(h){s.buffer=h.buf;s.loop=true;s.loopStart=h.a;s.loopEnd=h.b}const g=ctx.createGain();s.connect(g);g.connect(dest);
 let off=skRegion(l)[0];const lead=l.every===0||!skPulse(l)?0:skAttack(l);t+=l.nudge||0;
 if(lead>0){if(t-lead>=ctx.currentTime+0.005)t-=lead;else{off+=lead;dur=Math.max(0.01,dur-lead)}}
 const fi=Math.min(Math.max(0.004,(l.fin||0)/1000),dur/2),fo=Math.min(Math.max(0.004,xf,(l.fout||0)/1000),dur/2);
 g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(1,t+fi);g.gain.setValueAtTime(1,Math.max(t+fi,t+dur-fo));g.gain.linearRampToValueAtTime(0,t+dur);s.start(t,off,dur);
 if(ctx===AC){(l.on||(l.on=[])).push({t0:t,off,dur});if(l.on.length>8)l.on.shift()}  /* remembered for the playhead */if(arr){arr.push(s);s.onended=()=>{const k=arr.indexOf(s);if(k>=0)arr.splice(k,1)}}}
function skBar(ctx,dest,l,bar,t,L,arr){if(!laneOn(l,bar))return;if(l.type==='drums'){drumBar(ctx,dest,l,bar,t,L,arr);return}if(!l.buf)return;const R=skRegion(l)[1];if(l.every===0){const n=Math.max(1,Math.round(R/L));if(bar%n)return;skVoice(ctx,dest,l,t,Math.min(R,n*L),arr)}
 else{if(bar%l.every)return;const cut=R>l.every*L||!!laneHold(l);skVoice(ctx,dest,l,t+l.offset*L/4,cut?l.every*L+0.15:R,arr,cut?0.15:0)}}  // a longer clip fades out under the next pass
// ---------- the drum lane: drum one-shots as pads in a step sequencer (16 steps a bar, 1 or 2 bars, velocity, swing)
// It's one lane, so mute / solo / its fader and every export (bounce, stems, Live set) treat it like any other.
const DSTEPS=32;  // steps stored per pad (2 bars); a 1-bar pattern uses the first 16
// the same kinds as drumkit.py (single hits; layered ones go by their first drum)
function drumKind(i){const t=(S[i][F.sub]||'').toLowerCase();
 return /^kick/.test(t)?'kick':/^snare/.test(t)?'snare':/rim|clap/.test(t)?'clap':/hat/.test(t)?'hat':/ride|crash|cymbal/.test(t)?'cymbal':/shaker|tamb/.test(t)?'shaker':/tom/.test(t)?'tom':'perc'}
function drumStarter(kind){const s=new Array(DSTEPS).fill(0),on=(ks,v=1)=>ks.forEach(k=>{s[k]=v;s[k+16]=v});
 if(kind==='kick'){on([0,10]);on([8],0.75)}else if(kind==='snare')on([4,12]);else if(kind==='clap')on([4,12],0.8);else if(kind==='cymbal')s[0]=0.8;else if(kind==='hat'){for(let k=0;k<DSTEPS;k+=2)s[k]=k%4?0.5:0.8}
 else if(kind==='shaker'){for(let k=0;k<DSTEPS;k++)s[k]=k%2?0.3:0.5}else if(kind==='tom')on([14],0.7);else on([6],0.6);return s}
function drumLane(make){let l=SK.lanes.find(x=>x.type==='drums');if(l||!make)return l;if(SK.lanes.length>=8)return null;
 l={type:'drums',pads:[],bars:1,swing:0,db:-4,mute:false,solo:false,state:'ok',buf:null};SK.lanes.push(l);return l}
const PADBUF=lruMap(128);  // path -> decoding promise: the slices of one loop share it
async function drumPadLoad(p){if(p.buf)return;try{if(!PADBUF.has(p.path))PADBUF.set(p.path,fetch(url(p.path)).then(r=>r.arrayBuffer()).then(b=>AC.decodeAudioData(b)));
 p.buf=await PADBUF.get(p.path);p.norm=skNorm(p.buf);
 if(p.start==null){p.start=padAttack(p.buf);p.auto=p.start>0.003}}catch(e){p.err=true}
 await drumTakesLoad(p)}
// alternate takes (round robin): other hits of the same drum from the same song, each starting on its own hit
async function drumTakesLoad(p){const T=p.takes||[];if(!T.length){p.tk=[];return}if(p.tk&&p.tk.length===T.length&&p.tk.every((x,k)=>x.path===T[k]))return;
 p.tk=(await Promise.all(T.map(async path=>{try{if(!PADBUF.has(path))PADBUF.set(path,fetch(url(path)).then(r=>r.arrayBuffer()).then(b=>AC.decodeAudioData(b)));
  const buf=await PADBUF.get(path);return {path,buf,norm:skNorm(buf),start:padAttack(buf)}}catch(e){return null}}))).filter(Boolean)}
// which recording plays this hit: the n-th hit of the pad in the song cycles main, take 2, take 3… (the same every
// pass, so playback, bounce and the exported MIDI agree)
// ⇧-click pins a step to one take; "shuffled" is a seeded shuffle bag, so it
// still plays the same every time and the export matches (drumexport.take_idx is the same function)
function takeHash(x){x=Math.imul(x^(x>>>16),0x45d9f3b)>>>0;x=Math.imul(x^(x>>>16),0x45d9f3b)>>>0;return (x^(x>>>16))>>>0}
function takePerm(b,n,s){const P=[...Array(n).keys()];for(let k=n-1;k>0;k--){const j=takeHash(b*131+k+s)%(k+1);[P[k],P[j]]=[P[j],P[k]]}return P}
function takeIdx(p,h,j,nT){const pin=p.pins&&p.pins[j];if(pin)return Math.min(pin-1,nT-1);if(p.order!=='shuffle'||nT<2)return h%nT;
 const s=(p.seed||1)*7919;if(nT===2)return takeHash(h+s)%2;  // a shuffle bag: each take once in a random order, then a new order
 const b=Math.floor(h/nT),P=takePerm(b,nT,s);if(b>0&&P[0]===takePerm(b-1,nT,s)[nT-1])[P[0],P[1]]=[P[1],P[0]];return P[h%nT]}
function drumTake(l,p,idx,bar){const T=p.tk||[];if(!T.length||bar==null)return null;const n=16*l.bars,act=[];for(let k=0;k<n;k++)if(p.steps[k])act.push(k);
 const h=Math.floor(bar/l.bars)*act.length+Math.max(0,act.indexOf(idx)),w=takeIdx(p,h,idx,T.length+1);return w?T[w-1]:null}  // pads start on the hit, not on silence before it
async function drumLoad(l){l.state='loading';await Promise.all(l.pads.map(drumPadLoad));
 l.buf=l.pads.map(p=>p.buf).filter(Boolean).sort((a,b)=>b.duration-a.duration)[0]||AC.createBuffer(1,1,44100);l.state='ok'}  // buf: so "is it loaded" checks pass
async function drumAdd(i,{quiet=false,starter=true}={}){const l=drumLane(true);if(!l){toast('the sketchpad holds 8 lanes');return}
 if(l.pads.some(p=>p.path===S[i][F.path])){if(!quiet)toast('already in the drum lane');return}if(l.pads.length>=16){toast('the drum lane holds 16 pads');return}
 if(!PROJ.bpm){PROJ.bpm=S[i][F.bpm]||120;try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj()}
 const kind=drumKind(i),first=!l.pads.some(p=>drumKind(p.i)===kind);  // a starter pattern for the first pad of each kind
 const pad={i,path:S[i][F.path],db:0,mute:false,steps:starter&&first?drumStarter(kind):new Array(DSTEPS).fill(0)};
 l.pads.push(pad);SK.open=true;drawSK();drawProj();await drumLoad(l);drawSK();if(!quiet)toast(`pad ${l.pads.length} in the drum lane (${kind})`)}
// 🥁 build a kit around this: the hit goes into the drum lane, then the finder looks for the rest of a kit that sounds
// like it (the hits it's missing, recorded alike)
document.addEventListener('click',async e=>{if(!e.target.closest('#kitaround'))return;e.stopPropagation();if(st.sel==null)return;
 await drumAdd(st.sel,{quiet:true});const l=drumLane();if(!l)return;if(!(l.find&&!l.find.error))drumFind(l);
 setTimeout(()=>$('sk').scrollIntoView({block:'nearest',behavior:'smooth'}),100)},true);
// offline (bounce, stems): a whole bar at once. Live playback uses drumTick, step by step, so edits are heard at once.
function drumBar(ctx,dest,l,bar,t,L,arr){const base=(bar%l.bars)*16,st=L/16,solo=l.pads.some(p=>p.solo);
 if(ctx===AC){(l.sched||(l.sched=[])).push({t,bar});if(l.sched.length>8)l.sched.shift()}
 for(let s=0;s<16;s++)l.pads.forEach(p=>{if(!p.buf||p.mute||(solo&&!p.solo))return;drumStep(ctx,dest,l,p,base+s,t+s*st+(s%2?l.swing*st:0),arr,bar)})}
// one step of one pad: velocity, humanize (timing ±12 ms, velocity ±15% at 100%), a flam (a soft grace hit 20 ms
// before), and choke groups (a hit cuts off whatever else in its group is still ringing: closed hat chokes open hat)
function drumStep(ctx,dest,l,p,idx,t,arr,bar){let v=p.steps[idx];if(!v)return null;const h=l.human||0,tk=drumTake(l,p,idx,bar);
 if(h){t+=(Math.random()*2-1)*0.012*h;v=Math.max(0.05,Math.min(1,v*(1+(Math.random()*2-1)*0.15*h)))}
 if(p.flams&&p.flams[idx])drumHit(ctx,dest,p,t-0.02,v*0.45,arr,tk);
 const src=drumHit(ctx,dest,p,t,v,arr,tk);
 if(src&&p.choke){const m=(l._choke||(l._choke=new WeakMap())),g=m.get(ctx)||{};m.set(ctx,g);const prev=g[p.choke];
  if(prev&&prev!==src&&prev._t<=t){try{prev._g.gain.cancelScheduledValues(t);prev._g.gain.setTargetAtTime(0,Math.max(t,ctx.currentTime),0.004);prev.stop(t+0.06)}catch(e){}}
  g[p.choke]=src}
 return src}
function drumTick(l){const L=barLen(),st=L/16,solo=l.pads.some(p=>p.solo);if(l.nextAbs==null)l.nextAbs=Math.max(0,Math.ceil((AC.currentTime-SK.start)/st));
 l.live=l.live||new Map();
 const look=document.hidden?1.5:0.25;  // background tabs tick about once a second: look further ahead there
 while(SK.start+l.nextAbs*st<AC.currentTime+look){const abs=l.nextAbs++,bar=Math.floor(abs/16),s=abs%16,base=(bar%l.bars)*16;
  if(s===0){(l.sched||(l.sched=[])).push({t:SK.start+bar*L,bar});if(l.sched.length>8)l.sched.shift()}
  const t=SK.start+abs*st+(s%2?l.swing*st:0);
  if(!laneOn(l,bar))continue;
  l.pads.forEach((p,r)=>{if(!p.steps[base+s]||!p.buf||p.mute||(solo&&!p.solo))return;const src=drumStep(AC,l.g,l,p,base+s,t,SK.voices,bar);if(src)l.live.set(r+':'+(base+s),{src,t})})}
 if(l.live.size>256)[...l.live.keys()].slice(0,128).forEach(k=>l.live.delete(k))}
// a step switched on inside the window drumTick has already scheduled still plays in this pass
function drumLateStep(l,r,j){if(!SK.playing||!l.g||l.nextAbs==null)return;const p=l.pads[r],st=barLen()/16,solo=l.pads.some(x=>x.solo);
 if(!p.buf||p.mute||(solo&&!p.solo))return;
 const guard=AC.currentTime+0.01,swing=(l.swing||0)*st;
 const first=Math.max(0,Math.ceil((guard-SK.start-Math.max(0,swing))/st));
 for(let abs=first;abs<l.nextAbs;abs++){const bar=Math.floor(abs/16),s=abs%16;
  if((bar%l.bars)*16+s!==j||!laneOn(l,bar))continue;
  const t=SK.start+abs*st+(s%2?swing:0);if(t<guard)continue;
  const src=drumStep(AC,l.g,l,p,j,t,SK.voices,bar);if(src)l.live.set(r+':'+j,{src,t})}}
function drumCancelStep(l,r,j){
 const key=r+':'+j,q=l.live&&l.live.get(key);
 if(q&&q.t>AC.currentTime){try{q.src.stop()}catch(e){}l.live.delete(key)}
}
function drumHit(ctx,dest,p,t,v,arr,tk){if(!p.buf)return null;
  const tt=Math.max(t,ctx.currentTime),src=ctx.createBufferSource(),g=ctx.createGain(),B=tk?tk.buf:p.buf;src.buffer=B;
  // a take keeps the pad's edits: same length from its own hit, same tune, decay and level
  const rate=padRate(p),a=tk?tk.start:(p.start||0),span=tk?(p.end?p.end-(p.start||0):B.duration-a):((p.end||B.duration)-a),
   len=Math.max(0.005,Math.min(span,B.duration-a)/rate),amp=v*((tk?tk.norm:p.norm)||1)*Math.pow(10,(p.db||0)/20);
  src.playbackRate.value=rate;src.connect(g);g.connect(dest);g.gain.setValueAtTime(amp,tt);
  if(p.decay){g.gain.setTargetAtTime(0,tt+0.005,p.decay/4.6);src.start(tt,a,Math.min(len,p.decay*1.5))}  // -40 dB at `decay`
  else{g.gain.setValueAtTime(amp,tt+Math.max(0,len-0.004));g.gain.linearRampToValueAtTime(0,tt+len);src.start(tt,a,len)}
  src._g=g;src._t=tt;  // for choke groups
  if(arr){arr.push(src);src.onended=()=>{const k=arr.indexOf(src);if(k>=0)arr.splice(k,1)}}return src}
function drumLaneHTML(l,k){const n=16*l.bars;
 return `<div class="lane dlane${l.mute?' muted':''}" data-ln="${k}">
 <label class="onoff" title="turn the drum lane on or off"><input type="checkbox" data-skon="${k}" ${l.mute?'':'checked'}><span></span></label>
 <div class="lname"><div class="name">${secChips(l,k)}<span class="badge" style="background:${col('Percussion')}">${AB.Percussion}</span>Drums · ${l.pads.length} pad${l.pads.length===1?'':'s'}</div><div class="meta" title="click: on → soft → off · scroll over a step: its velocity · ⌥-click: a flam">click · scroll = velocity · ⌥ = flam</div></div>
 <div class="ctl"><select data-dbars="${k}" title="pattern length"><option value="1">1 bar</option><option value="2" ${l.bars===2?'selected':''}>2 bars</option></select>
  <label title="delays every other 16th: 0 = straight">swing <input type="range" min="0" max="0.6" step="0.05" value="${l.swing}" data-dswing="${k}" style="width:70px"></label>
  <label title="loosens timing (up to ±12 ms) and velocity (up to ±15%), so it isn't machine-tight">humanize <input type="range" min="0" max="1" step="0.05" value="${l.human||0}" data-dhuman="${k}" style="width:60px"></label>
  <button class="tbtn" data-dmidi="${k}" title="a Drum Rack of these pads (trimmed and edited as here, choke groups included) and a MIDI clip of the pattern, for Live">⇩ MIDI + rack</button>
  <button class="tbtn" data-dstart="${k}" title="a starter pattern from the pad types (kick, snare, hats…)">✨ starter</button><button class="tbtn" data-dclear="${k}">clear</button>
  <button class="tbtn${l.find?' on':''}" data-dfind="${k}" title="hits for the kinds this kit is missing, that sound like they were recorded with the pads you have">🔎 complete the kit</button></div>
 <div class="fader" title="drum lane volume · double-click for 0 dB"><input type="range" min="-24" max="6" step="0.5" value="${l.db||0}" data-skv="${k}"><output>${dbTxt(l.db||0)}</output></div>
 <button class="tbtn${l.solo?' on':''}" data-sks="${k}" title="solo">S</button><button class="tbtn" data-skx="${k}" title="remove the drum lane">✕</button>
 <div class="dgrid" data-dgrid="${k}" style="--n:${n}">${l.pads.map((p,r)=>{const s=S[p.i]||[];return `<div class="drow${p.mute?' muted':''}">
  <button class="tbtn" data-dpad="${k}:${r}" title="hear it">▶</button><button class="dlab dedit${p.open?' on':''}" data-dedit="${k}:${r}" title="${esc(s[F.artist]||'')} — ${esc(s[F.title]||'')} · click to ${p.open?'close':'open'} this pad's editor (start, end, tune, decay)"><span class="dtri">${p.open?'▾':'▸'}</span>${esc(p.label||s[F.sub]||'hit')}${p.tune||p.decay||p.end||(p.start>0.003&&!p.auto)?' ✎':''}</button>
  <div class="dsteps">${p.steps.slice(0,n).map((v,j)=>`<button class="dstep${v?' on':''}${j%4===0?' beat':''}${p.flams&&p.flams[j]?' flam':''}${p.pins&&p.pins[j]&&(p.takes||[]).length?' pin':''}" data-dstep="${k}:${r}:${j}" ${p.pins&&p.pins[j]?`data-pin="${p.pins[j]}"`:''} ${v?`style="--v:${Math.round(v*100)}%"`:''} title="${v?`velocity ${Math.round(v*100)}%${p.flams&&p.flams[j]?' · flam':''}`:'off'}"></button>`).join('')}</div>
  <button class="tbtn${(p.takes||[]).length?' on':''}" data-dtakes="${k}:${r}" title="${(p.takes||[]).length?`alternating ${p.takes.length+1} takes of this hit (round robin) · ⇧-click a step to pin it to one take · click to show or hide its takes row (hear each, pick the main one, shuffle, off)`:'alternate takes (round robin): cycle through other hits of this drum from the same song, so repeated hits sound played, not copied'}">🔁${(p.takes||[]).length?' '+(p.takes.length+1):''}</button>
  <select class="dchoke" data-dchoke="${k}:${r}" title="choke group: pads in the same group cut each other off, like a real hi-hat (a closed hat silences a ringing open hat). Put both hats in group 1; pads with no choke ring over each other"><option value="0">no choke</option>${[1,2,3].map(g=>`<option value="${g}" ${p.choke===g?'selected':''}>choke grp ${g}</option>`).join('')}</select>
  <span class="dvol" title="this pad's volume against the other pads (every pad starts equally loud at 0 dB) · double-click for 0 dB"><input type="range" min="-24" max="6" step="0.5" value="${p.db||0}" data-dpv="${k}:${r}"><output>${dbTxt(p.db||0)}</output></span>
  <span class="dsm"><button class="tbtn${p.solo?' on':''}" data-dsolo="${k}:${r}" title="solo: hear only this pad (and any other soloed pads)">S</button><button class="tbtn${p.mute?' on':''}" data-dmute="${k}:${r}" title="mute this pad">M</button></span><button class="tbtn" data-dpx="${k}:${r}" title="remove this pad">✕</button></div>${p.tkopen!==false?takesHTML(k,p,r):''}${p.open?padEditHTML(l,k,p,r):''}`}).join('')||'<div class="sub">add drum one-shots with ＋, or send a song\'s drum rack here</div>'}${drumFindHTML(l,k)}</div></div>`}
function drumFindHTML(l,k){const f=l.find;if(!f)return'';if(f.loading&&!f.missing)return '<div class="sub dfind">listening for hits that match this kit…</div>';if(f.error)return `<div class="sub dfind">${esc(f.error)}</div>`;
 const rows=f.missing.filter(m=>f.all||!m.have);
 const pick=(m,p)=>{const i=byPath.get(p.path);if(i==null)return'';const s=S[i];const steer=f.steer[m.kind]===p.path;
  return `<span class="dfpick${steer?' steer':''}"><button class="tbtn" data-dfplay="${esc(p.path)}" title="hear it">▶</button><span class="sub" title="${esc(s[F.artist])} — ${esc(s[F.title])} · ${esc(p.sub)}">${esc(s[F.artist]).slice(0,18)}${p.same_song?' · same song':''}</span>
   <button class="tbtn" data-dfsteer="${k}|${m.kind}|${esc(p.path)}" title="more like this: re-rank ${esc(m.label.toLowerCase())} toward this one's sound (click again to undo)">≈</button><button class="tbtn" data-dfno="${k}|${m.kind}|${esc(p.path)}" title="not this one: the next slides in">✕</button><button class="tbtn" data-dfadd="${i}" title="add it as a pad (with a starter part)">＋</button></span>`};
 return `<div class="dfind"><div class="sub" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span>${rows.length?'Picked to sound like the same recording (room, tape, brightness):':'Every kind is covered.'}</span>
  <label><input type="checkbox" data-dfall="${k}" ${f.all?'checked':''}> also kinds you have (alternatives)</label>${f.loading?'<span>…</span>':''}</div>
  ${rows.map(m=>{const vis=m.picks.filter(p=>!f.hidden.has(p.path)&&!GONE.has(byPath.get(p.path))),o=Math.min(f.off[m.kind]||0,Math.max(0,vis.length-3)),page=vis.slice(o,o+3);
  return `<div class="dfrow"><span class="dlab">${esc(m.label)}${m.have?' <span class="sub">(have)</span>':''}${m.steered?' <span class="sub">· steered</span>':''}</span><div class="dfpicks">${page.map(p=>pick(m,p)).join('')||'<span class="sub">no more</span>'}
   <span class="dfnav">${o>0?`<button class="tbtn" data-dfmore="${k}|${m.kind}|-3" title="back">‹</button>`:''}<span class="sub">${vis.length?`${o+1}–${Math.min(o+3,vis.length)} of ${vis.length}`:''}</span>${o+3<vis.length?`<button class="tbtn" data-dfmore="${k}|${m.kind}|3" title="three more">↻ more</button>`:''}</span></div></div>`}).join('')}</div>`}
async function drumFind(l,keep){const prev=l.find||{};l.find={...prev,loading:true,missing:keep?prev.missing:null,off:keep?prev.off||{}:{},hidden:prev.hidden||new Set(),steer:prev.steer||{},all:!!prev.all};drawSK();
 try{const r=await api('api/drumkit',{paths:l.pads.map(p=>p.path),steer:l.find.steer,everything:true});
  if(r.error)l.find={error:r.error};else{const off={...l.find.off};r.missing.forEach(m=>{if(m.steered)off[m.kind]=0});Object.assign(l.find,{missing:r.missing,loading:false,off})}}catch(e){l.find={error:"couldn't search: "+e.message}}drawSK()}
// the playing step lights up
function drumHeads(){const now=AC.currentTime;SK.lanes.forEach((l,k)=>{if(l.type!=='drums')return;const g=document.querySelector(`[data-dgrid="${k}"]`);if(!g)return;
 const L=barLen(),v=(l.sched||[]).filter(x=>now>=x.t&&now<x.t+L).pop(),cur=SK.playing&&v?(v.bar%l.bars)*16+Math.floor((now-v.t)/(L/16)):-1;
 if(g._cur===cur)return;g._cur=cur;g.querySelectorAll('.dstep.now').forEach(b=>b.classList.remove('now'));if(cur>=0)g.querySelectorAll(`[data-dstep$=":${cur}"]`).forEach(b=>b.classList.add('now'))})}
$('sk').addEventListener('click',async e=>{const t=e.target.closest('[data-dstep],[data-dpad],[data-dpx],[data-dmute],[data-dsolo],[data-dstart],[data-dclear],[data-dfind],[data-dfplay],[data-dfadd],[data-dfmore],[data-dfno],[data-dfsteer]');if(!t)return;e.stopPropagation();
 if(t.dataset.dfmore!=null){const [k,kind,d]=t.dataset.dfmore.split('|'),f=SK.lanes[+k].find;f.off[kind]=Math.max(0,(f.off[kind]||0)+(+d));drawSK();return}
 if(t.dataset.dfno!=null){const [k,,p]=t.dataset.dfno.split('|');SK.lanes[+k].find.hidden.add(p);drawSK();return}
 if(t.dataset.dfsteer!=null){const [k,kind,p]=t.dataset.dfsteer.split('|'),l=SK.lanes[+k];if(l.find.steer[kind]===p)delete l.find.steer[kind];else l.find.steer[kind]=p;drumFind(l,true);return}
 if(t.dataset.dfind!=null){const l=SK.lanes[+t.dataset.dfind];if(l.find&&!l.find.loading){l.find=null;drawSK();return}drumFind(l);return}
 if(t.dataset.dfplay!=null){stopAll();const a=new Audio(url(t.dataset.dfplay));a.play().catch(()=>{});players.set('df',a);a.onended=()=>players.delete('df');return}
 if(t.dataset.dfadd!=null){const l=drumLane();await drumAdd(+t.dataset.dfadd);if(l&&l.find)drumFind(l,true);return}
 if(t.dataset.dstep){const [k,r,j]=t.dataset.dstep.split(':').map(Number),l=SK.lanes[k],p=l.pads[r],v=p.steps[j];
  if(e.shiftKey&&(p.takes||[]).length){p.pins=p.pins||new Array(DSTEPS).fill(0);p.pins[j]=((p.pins[j]||0)+1)%(p.takes.length+2);if(!v){p.steps[j]=1;drumLateStep(l,r,j)}drawSK();return}
  if(e.altKey){p.flams=p.flams||new Array(DSTEPS).fill(0);p.flams[j]=p.flams[j]?0:1;if(!v){p.steps[j]=1;drumLateStep(l,r,j)}drawSK();return}
  p.steps[j]=!v?1:v>0.7?0.55:0;if(!v)drumLateStep(l,r,j);else if(!p.steps[j])drumCancelStep(l,r,j);
  t.classList.toggle('on',!!p.steps[j]);t.style.setProperty('--v',Math.round(p.steps[j]*100)+'%');
  return}
 if(t.dataset.dpad){const [k,r]=t.dataset.dpad.split(':').map(Number),p=SK.lanes[k].pads[r];if(!p.buf)return;AC.resume();
  const one={...SK.lanes[k],pads:[{...p,steps:[1],mute:false,solo:false}],bars:1,swing:0};drumBar(AC,AC.destination,one,0,AC.currentTime+0.01,barLen(),null);return}
 if(t.dataset.dmute){const [k,r]=t.dataset.dmute.split(':').map(Number),p=SK.lanes[k].pads[r];p.mute=!p.mute;drawSK();return}
 if(t.dataset.dsolo){const [k,r]=t.dataset.dsolo.split(':').map(Number),p=SK.lanes[k].pads[r];p.solo=!p.solo;skGains();drawSK();return}
 if(t.dataset.dpx){const [k,r]=t.dataset.dpx.split(':').map(Number),l=SK.lanes[k];l.pads.splice(r,1);if(!l.pads.length)SK.lanes.splice(k,1);if(!SK.lanes.length)skStop();drawSK();drawProj();return}
 const l=SK.lanes[+(t.dataset.dstart??t.dataset.dclear)];
 if(t.dataset.dclear!=null){l.pads.forEach(p=>p.steps.fill(0));drawSK();return}
 const seen=new Set();l.pads.forEach(p=>{const kd=drumKind(p.i);p.steps=seen.has(kd)?new Array(DSTEPS).fill(0):drumStarter(kd);seen.add(kd)});drawSK()},true);
$('sk').addEventListener('change',e=>{const t=e.target;if(t.dataset.dbars!=null){const l=SK.lanes[+t.dataset.dbars];l.bars=+t.value;
  if(l.bars===2)l.pads.forEach(p=>{if(!p.steps.slice(16).some(Boolean))for(let j=0;j<16;j++)p.steps[16+j]=p.steps[j]});drawSK()}},true);  // 1 → 2 bars: the second bar starts as a copy
document.addEventListener('click',async e=>{if(!e.target.closest('#racksk'))return;e.stopPropagation();
 const per={},order=['kick','snare','hat','shaker','tom','perc'],ids=[];  // a playable kit: up to 2 of each kind, 12 pads at most
 RACK.ids.forEach(i=>{const k=drumKind(i);(per[k]||(per[k]=[])).push(i)});order.forEach(k=>(per[k]||[]).slice(0,2).forEach(i=>ids.length<12&&ids.push(i)));const l=drumLane(true);if(!l){toast('the sketchpad holds 8 lanes');return}
 for(const i of ids)await drumAdd(i,{quiet:true});toast(`${ids.length} pads in the drum lane · press ▶ in the sketchpad`)},true);
$('sk').addEventListener('change',e=>{const t=e.target;if(t.dataset.dfall!=null){const l=SK.lanes[+t.dataset.dfall];l.find.all=t.checked;drawSK()}},true);
$('sk').addEventListener('change',e=>{const t=e.target;
 if(t.id==='skarr'){SK.arr=t.value.toUpperCase().replace(/[^A-H]/g,'').slice(0,16);
  SK.lanes.forEach(l=>{if(l.secs){l.secs=l.secs.split('').filter(c=>SK.arr.includes(c)).join('');if(!l.secs)l.secs=null}});drawSK()}
 else if(t.id==='sksec'){SK.sec=+t.value;drawSK()}},true);
$('sk').addEventListener('keydown',e=>{if(e.target.id==='skarr'&&e.key==='Enter')e.target.blur()},true);
$('sk').addEventListener('click',e=>{const b=e.target.closest('[data-sksec]');if(!b)return;e.stopPropagation();const [k,c]=b.dataset.sksec.split(':'),l=SK.lanes[+k];
 const cur=l.secs==null?secLetters().join(''):l.secs,next=cur.includes(c)?cur.replace(c,''):cur+c;
 l.secs=next.length===secLetters().length?null:[...next].sort().join('');drawSK()},true);
$('sk').addEventListener('wheel',e=>{const t=e.target.closest&&e.target.closest('[data-dstep]');if(!t)return;e.preventDefault();
 const [k,r,j]=t.dataset.dstep.split(':').map(Number),l=SK.lanes[k],p=l.pads[r],before=p.steps[j]||0;
 const v=Math.round(Math.max(0,Math.min(1,before+(e.deltaY<0?0.1:-0.1)))*10)/10;
 p.steps[j]=v;if(!before&&v>0)drumLateStep(l,r,j);else if(before&&!v)drumCancelStep(l,r,j);
 t.classList.toggle('on',!!v);t.style.setProperty('--v',Math.round(v*100)+'%');t.title=v?`velocity ${Math.round(v*100)}%`:'off'},{passive:false});
document.addEventListener('click',async e=>{const b=e.target.closest('#playit');if(!b)return;const i=+b.dataset.i;b.disabled=true;b.textContent='🎹 making it…';
 try{const r=await api('api/pad/playable',{path:S[i][F.path]});toast(`Playable pads/${r.adv||r.wav} · drop the .adv on a MIDI track: ${r.chords.join(' → ')||'its note'} plays on ${['C','D♭','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][r.root%12]}${r.midi?'; the chords clip is next to it':''}`)}
 catch(err){toast('failed: '+err.message)}b.disabled=false;b.textContent='🎹 playable'});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-dtakes]');if(!b)return;e.stopPropagation();const [k,r]=b.dataset.dtakes.split(':').map(Number),p=SK.lanes[k]&&SK.lanes[k].pads[r];if(!p)return;
 if((p.takes||[]).length){p.tkopen=p.tkopen===false;drawSK();return}
 b.disabled=true;let T=[];try{T=(await api('api/drums/takes?path='+encodeURIComponent(p.path))).takes.map(t=>t.path).filter(x=>byPath.has(x)&&!GONE.has(byPath.get(x)))}catch(err){}
 if(!T.length){b.disabled=false;toast('no other takes of this hit in its song');return}p.takes=T;p.tkopen=true;await drumTakesLoad(p);drawSK();toast(`${T.length+1} takes: hits now cycle through them`)},true);
$('sk').addEventListener('change',e=>{const t=e.target;if(t.dataset.dchoke!=null){const [k,r]=t.dataset.dchoke.split(':').map(Number);SK.lanes[k].pads[r].choke=+t.value||0}},true);
$('sk').addEventListener('input',e=>{const t=e.target;if(t.dataset.dhuman!=null)SK.lanes[+t.dataset.dhuman].human=+t.value},true);
$('sk').addEventListener('click',async e=>{const b=e.target.closest('[data-dmidi]');if(!b)return;e.stopPropagation();const l=SK.lanes[+b.dataset.dmidi];
 const name=(($('skname').value||'').trim()||SK.name||'Drums '+new Date().toISOString().slice(0,10))+' drums';b.textContent='exporting…';
 try{const r=await api('api/drums/export',{name,bpm:PROJ.bpm||120,bars:l.bars,swing:l.swing,
   pads:l.pads.map(p=>({path:p.path,label:p.label||(S[p.i]||[])[F.sub]||'',steps:p.steps.slice(0,16*l.bars),flams:(p.flams||[]).slice(0,16*l.bars),choke:p.choke||0,mute:!!p.mute,start:p.start||0,end:p.end||null,tune:p.tune||0,decay:p.decay||0,takes:(p.takes||[]).slice(),pins:(p.pins||[]).slice(0,16*l.bars),order:p.order||'cycle',seed:p.seed||1}))});
  b.textContent='⇩ MIDI + rack';toast(`rack + MIDI clip → ${r.dest.split('/').slice(-2).join('/')} · drop the rack on a track, then the clip`)}catch(err){b.textContent='⇩ MIDI + rack';toast('export failed: '+err.message)}},true);
$('sk').addEventListener('input',e=>{const t=e.target;if(t.dataset.dswing!=null)SK.lanes[+t.dataset.dswing].swing=+t.value},true);
// ---------- editing pads inside the drum lane: start on the hit, end, tune, decay (all live, no rendering)
// where the hit really starts: the first sample above a quarter of the peak, backed up to where it rises from quiet
function padAttack(buf){const sr=buf.sampleRate,d=buf.getChannelData(0),n=Math.min(d.length,sr*3);let pk=0;for(let k=0;k<n;k++)pk=Math.max(pk,Math.abs(d[k]));
 let a=0;while(a<n&&Math.abs(d[a])<0.25*pk)a++;let b=a;const floor=0.03*pk,lim=Math.max(0,a-Math.floor(0.02*sr));while(b>lim&&Math.abs(d[b])>floor)b--;
 return Math.max(0,b/sr-0.001)}
const padRate=p=>Math.pow(2,(p.tune||0)/12);
function padWaves(){SK.lanes.forEach((l,k)=>{if(l.type!=='drums')return;l.pads.forEach((p,r)=>{
 if(!p.open||!p.buf)return;
 const c=reuseWaveCanvas(document.querySelector(`[data-dpc="${k}:${r}"]`),p,'data-dpc');
 if(c)padWave(c,p)
})})}
function padWave(c,p){const dpr=devicePixelRatio||1,W=Math.floor(c.clientWidth*dpr),H=Math.floor(56*dpr),buf=p.buf;
 if(!W||!H||!buf)return;
 const g=c.getContext('2d'),sr=buf.sampleRate;
 if(c.width!==W||c.height!==H){c.width=W;c.height=H}else g.clearRect(0,0,W,H);
 const view=Math.min(buf.duration,Math.max(0.5,(p.end||buf.duration)+0.1)),X=t=>t/view*W,s0=p.start||0,e0=p.end||buf.duration;
 const peaks=wavePeaks(buf,W,0,Math.min(buf.length,Math.floor(view*sr)),2);
 for(let x=0;x<peaks.length;x++){const m=peaks[x],t=x/W*view;g.fillStyle=t>=s0&&t<=e0?'#e0a458':'#3a4048';g.fillRect(x,H/2-m*H/2,1,Math.max(1,m*H))}
 g.fillStyle='#fff';g.fillRect(X(s0)-dpr,0,2*dpr,H);g.fillStyle='#7fb0c9';g.fillRect(X(e0)-dpr,0,2*dpr,H);c._view=view}
function padEditHTML(l,k,p,r){const ms=Math.round((p.start||0)*1000),dec=p.decay||0;
 return `<div class="dped"><canvas data-dpc="${k}:${r}" title="drag the white line to where the hit starts, the blue one to where it ends"></canvas>
 <div class="ctl"><span class="sub">start ${ms} ms${p.auto?' (moved to the hit)':''}</span><button class="tbtn" data-dpstart="${k}:${r}:hit" title="put the start on the hit again">to the hit</button><button class="tbtn" data-dpstart="${k}:${r}:0" title="play from the file's beginning">from 0</button>
  <button class="tbtn" data-dpend="${k}:${r}" title="let it ring to the end of the file">full length</button>
  <label>tune <input type="range" min="-12" max="12" step="1" value="${p.tune||0}" data-dptune="${k}:${r}"><output>${p.tune>0?'+':''}${p.tune||0} st</output></label>
  <label title="shortens the tail with a natural fade">decay <input type="range" min="0" max="100" step="1" value="${decayVal(dec)}" data-dpdec="${k}:${r}"><output>${dec?dec.toFixed(2)+' s':'natural'}</output></label>
  <button class="tbtn" data-dpad="${k}:${r}">▶</button><button class="tbtn" data-dpfull="${k}:${r}" title="open it in the full editor (punch, drive, low cut…); save as new and the pad switches to your edit">↗ full editor</button></div></div>`}
function takesHTML(k,p,r){const T=p.takes||[];if(!T.length)return'';
 return `<div class="dtk"><span class="sub">takes</span>${[p.path,...T].map((x,w)=>`<span class="dtkb"><button class="tbtn" data-dtkplay="${k}:${r}:${w}" title="hear take ${w+1}">▶ ${w+1}${w?'':' main'}</button>${w?`<button class="tbtn" data-dtkmain="${k}:${r}:${w}" title="make take ${w+1} the main hit (the others stay as takes)">★</button>`:''}</span>`).join('')}
  <select data-dtkord="${k}:${r}" title="in turn: main, 2, 3, main… · shuffled: every take once in a random order, then a new order (never the same twice running), the same every play"><option value="cycle">in turn</option><option value="shuffle" ${p.order==='shuffle'?'selected':''}>shuffled</option></select>
  ${p.order==='shuffle'?`<button class="tbtn" data-dtkseed="${k}:${r}" title="a different shuffle">🎲</button>`:''}
  <button class="tbtn" data-dtkoff="${k}:${r}" title="back to one take">off</button>
  <span class="sub">⇧-click a step to pin it to a take (click again for the next one)</span>${(p.pins||[]).some(Boolean)?`<button class="tbtn" data-dtkunpin="${k}:${r}">unpin all</button>`:''}</div>`}
$('sk').addEventListener('click',async e=>{const t=e.target.closest('[data-dtkplay],[data-dtkmain],[data-dtkseed],[data-dtkunpin],[data-dtkoff]');if(!t)return;e.preventDefault();e.stopPropagation();
 const [k,r,w]=(t.dataset.dtkplay||t.dataset.dtkmain||t.dataset.dtkseed||t.dataset.dtkunpin||t.dataset.dtkoff).split(':').map(Number),l=SK.lanes[k],p=l.pads[r];
 if(t.dataset.dtkplay!=null){if(!p.buf)return;AC.resume();const one={...l,pads:[{...p,steps:[1],pins:[w+1],order:'cycle',mute:false,solo:false}],bars:1,swing:0};drumBar(AC,AC.destination,one,0,AC.currentTime+0.01,barLen(),null);return}
 if(t.dataset.dtkseed!=null){p.seed=1+Math.floor(Math.random()*99999);drawSK();return}
 if(t.dataset.dtkunpin!=null){p.pins=null;drawSK();return}
 if(t.dataset.dtkoff!=null){p.takes=[];p.tk=[];p.pins=null;p.order=null;drawSK();return}
 // make take w the main hit: swap it with the main one (pins follow their recording), keep the pad's length
 const span=p.end?p.end-(p.start||0):null,nw=p.takes[w-1];p.takes[w-1]=p.path;p.path=nw;p.i=byPath.get(nw);p.buf=null;p.start=null;p.end=null;p.tk=null;
 if(p.label)p.label=null;if(p.pins)p.pins=p.pins.map(x=>x===1?w+1:x===w+1?1:x);
 await drumPadLoad(p);if(span&&p.buf)p.end=Math.min(p.buf.duration,p.start+span);drawSK();toast(`take ${w+1} is now the main hit`)},true);
$('sk').addEventListener('change',e=>{const t=e.target;if(t.dataset.dtkord==null)return;const [k,r]=t.dataset.dtkord.split(':').map(Number),p=SK.lanes[k].pads[r];
 p.order=t.value;if(p.order==='shuffle'&&!p.seed)p.seed=1+Math.floor(Math.random()*99999);drawSK()},true);
// drag the start / end lines
document.addEventListener('mousedown',e=>{const c=e.target.closest&&e.target.closest('[data-dpc]');if(!c)return;e.preventDefault();
 const [k,r]=c.dataset.dpc.split(':').map(Number),p=SK.lanes[k].pads[r],t0=()=>((e.offsetX)/c.clientWidth)*c._view;
 const at=ev=>Math.max(0,Math.min(p.buf.duration,(ev.clientX-c.getBoundingClientRect().left)/c.clientWidth*c._view));
 const which=Math.abs(t0()-(p.start||0))<=Math.abs(t0()-(p.end||p.buf.duration))?'start':'end';
 const move=ev=>{const t=at(ev);if(which==='start'){p.start=Math.min(t,(p.end||p.buf.duration)-0.01);p.auto=false}else p.end=Math.max(t,(p.start||0)+0.01);
  rafOnce('paddrag',()=>{if(c.isConnected)padWave(c,p)})};
 move(e);const up=()=>{removeEventListener('mousemove',move);removeEventListener('mouseup',up);drawSK()};addEventListener('mousemove',move);addEventListener('mouseup',up)});
$('sk').addEventListener('click',async e=>{const t=e.target.closest('[data-dedit],[data-dpstart],[data-dpend],[data-dpfull]');if(!t)return;e.stopPropagation();
 const [k,r,how]=(t.dataset.dedit||t.dataset.dpstart||t.dataset.dpend||t.dataset.dpfull).split(':'),p=SK.lanes[+k].pads[+r];
 if(t.dataset.dedit!=null){p.open=!p.open;drawSK();return}
 if(t.dataset.dpstart!=null){if(how==='hit'){p.start=padAttack(p.buf);p.auto=true}else{p.start=0;p.auto=false}drawSK();return}
 if(t.dataset.dpend!=null){p.end=null;drawSK();return}
 // the full editor: when you save as new, this pad switches to your edit
 select(p.i,'list');await openEditor(p.i);if(ED){ED.fromPad={lane:SK.lanes[+k],pad:p}};toast('edit it, then save as new: the pad switches to your edit')},true);
$('sk').addEventListener('input',e=>{const t=e.target;if(t.dataset.dpv==null)return;const [k,r]=t.dataset.dpv.split(':').map(Number),p=SK.lanes[k].pads[r];
 p.db=+t.value;t.parentNode.querySelector('output').textContent=dbTxt(p.db)},true);  // heard within a step (drumTick reads it as it schedules)
$('sk').addEventListener('dblclick',e=>{const t=e.target;if(!t.dataset||t.dataset.dpv==null)return;e.stopPropagation();const [k,r]=t.dataset.dpv.split(':').map(Number);SK.lanes[k].pads[r].db=0;drawSK()},true);
$('sk').addEventListener('input',e=>{const t=e.target;if(t.dataset.dptune==null&&t.dataset.dpdec==null)return;const [k,r]=(t.dataset.dptune||t.dataset.dpdec).split(':').map(Number),p=SK.lanes[k].pads[r],o=t.parentNode.querySelector('output');
 if(t.dataset.dptune!=null){p.tune=+t.value;o.textContent=(p.tune>0?'+':'')+p.tune+' st'}else{p.decay=+decayS(+t.value).toFixed(3);o.textContent=p.decay?p.decay.toFixed(2)+' s':'natural'}},true);
const _drawSKpad=drawSK;drawSK=function(){_drawSKpad();padWaves()};
const _edSavePad=edSave;edSave=async function(...a){const fp=ED&&ED.fromPad,n0=S.length;const r=await _edSavePad.apply(this,a);
 if(fp&&S.length>n0){const j=S.length-1,p=fp.pad;Object.assign(p,{i:j,path:S[j][F.path],buf:null,start:null,end:null,tune:0,decay:0});await drumLoad(fp.lane);drawSK();toast('the pad now plays your edit')}return r};
// ---------- tempo in the sketchpad: drums-only sketches change tempo live; sample lanes need re-stretching (a reload)
function skTempo(b){b=Math.max(40,Math.min(220,Math.round(b*10)/10));if(!b||b===PROJ.bpm)return;
 if(!SK.playing||SK.lanes.some(l=>l.type!=='drums')){if(SK.playing&&SK.lanes.some(l=>l.type!=='drums'))toast(`re-stretching the lanes to ${b} bpm…`);setProj({bpm:b});drawSK();return}
 const now=AC.currentTime,pos=(now-SK.start)/barLen();PROJ.bpm=b;try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj();
 SK.start=now-pos*barLen();SK.lanes.forEach(l=>{l.nextAbs=null;l.sched=[]});  // same place in the bar, new speed
 const inp=$('skbpm');if(inp&&document.activeElement!==inp)inp.value=Math.round(b)}
let TAPS=[];
$('sk').addEventListener('click',e=>{const t=e.target.closest('[data-skbpm],#sktap');if(!t)return;e.stopPropagation();
 if(t.id==='sktap'){const now=performance.now();TAPS=TAPS.filter(x=>now-x<2500);TAPS.push(now);
  if(TAPS.length>=3){const iv=TAPS.slice(1).map((x,k)=>x-TAPS[k]);skTempo(60000/(iv.reduce((a,c)=>a+c,0)/iv.length));const inp=$('skbpm');if(inp)inp.value=Math.round(PROJ.bpm)}
  t.textContent=TAPS.length<3?`tap ${TAPS.length}/3…`:'tap';clearTimeout(t._r);t._r=setTimeout(()=>{t.textContent='tap'},2600);return}
 skTempo((PROJ.bpm||120)+(+t.dataset.skbpm)*(e.shiftKey?5:1))},true);
$('sk').addEventListener('change',e=>{if(e.target.id==='skbpm')skTempo(+e.target.value)},true);
$('sk').addEventListener('keydown',e=>{if(e.target.id==='skbpm'&&e.key==='Enter')e.target.blur()},true);
// ---------- sketch state: one definition, used by save, bounce provenance, undo/redo, "unsaved" and the draft
function skLanesState(){return SK.lanes.map(l=>l.type==='drums'?{type:'drums',secs:l.secs||null,bars:l.bars,swing:l.swing,db:l.db||0,mute:!!l.mute,solo:!!l.solo,
  human:l.human||0,pads:l.pads.map(p=>({path:p.path,label:p.label||null,db:p.db||0,mute:!!p.mute,solo:!!p.solo,steps:p.steps.slice(),flams:(p.flams||[]).slice(),choke:p.choke||0,start:p.start,end:p.end||null,tune:p.tune||0,decay:p.decay||0,auto:!!p.auto,takes:(p.takes||[]).slice(),pins:(p.pins||[]).slice(),order:p.order||'cycle',seed:p.seed||1}))}
 :({path:l.path,secs:l.secs||null,db:l.db||0,vol:+(0.8*Math.pow(10,(l.db||0)/20)).toFixed(3),mute:!!l.mute,solo:!!l.solo,every:l.every,offset:l.offset,trim:l.trim||null,fin:l.fin||0,fout:l.fout||0,nudge:l.nudge||0,src:l.src||null,nat:!!l.nat,hold:!!l.hold}))}
const skSnap=()=>JSON.stringify({key:PROJ.key||null,bpm:PROJ.bpm||null,name:SK.name||'',arr:SK.arr||'',sec:SK.sec||4,lanes:skLanesState()});
const EMPTY_SNAP=()=>JSON.stringify({key:PROJ.key||null,bpm:PROJ.bpm||null,name:'',arr:'',sec:4,lanes:[]});
SK.saved=null;
const skDirty=()=>SK.lanes.length>0&&skSnap()!==SK.saved;
// put a remembered state back, reusing audio already loaded (only what changed is fetched again)
async function skRestore(st){const was=SK.playing||(reloadLanes===SK.lanes&&reloadPlay);if(was)skStop();
 const keyChanged=(st.key||null)!==(PROJ.key||null)||(st.bpm||null)!==(PROJ.bpm||null);
 if(keyChanged){Object.assign(PROJ,{key:st.key,bpm:st.bpm});try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj()}
 const old=new Map();SK.lanes.forEach(l=>{if(l.type==='drums')l.pads.forEach(p=>{if(p.buf)old.set('d|'+p.path,p)});else if(l.buf&&l.state==='ok')old.set(`${l.path}|${l.nat?1:0}|${l.src||''}`,l)});
 SK.name=st.name||'';SK.arr=st.arr||'';SK.sec=st.sec||4;
 SK.lanes=st.lanes.map(l=>{if(l.type==='drums'){return {...l,state:'loading',buf:null,pads:l.pads.map(p=>{const o=old.get('d|'+p.path);return {...p,steps:p.steps.slice(),i:byPath.get(p.path),buf:o?o.buf:null,norm:o?o.norm:null}}).filter(p=>p.i!=null)}}
  const o=keyChanged?null:old.get(`${l.path}|${l.nat?1:0}|${l.src||''}`);return {...l,i:byPath.get(l.path),buf:o?o.buf:null,norm:o?o.norm:null,pulse:o?o.pulse:null,ons:o?o.ons:null,state:o?'ok':'loading'}})
  .filter(l=>l.type==='drums'?l.pads.length:l.i!=null);
 drawSK();drawProj();await Promise.all(SK.lanes.filter(l=>l.type==='drums'||l.state!=='ok').map(skLoad));drawSK();if(was&&SK.lanes.length)skPlay()}
// undo / redo: a change is recorded once the sketch has been still for a moment, so a fader drag is one step
const UNDO={past:[],future:[],cur:null,seen:null,still:0,hold:false};
// the draft: a refresh or crash keeps your sketch (written whenever the sketch settles, undo and redo included)
const skDraft=()=>{try{localStorage.setItem('atlasSketchDraft',JSON.stringify({snap:UNDO.cur,saved:SK.saved}))}catch(e){}};
function undoTick(){if(document.hidden||UNDO.hold)return;const s=skSnap();
 if(UNDO.cur===null){UNDO.cur=s;UNDO.seen=s;return}
 if(s!==UNDO.seen){UNDO.seen=s;UNDO.still=0}else if(s!==UNDO.cur&&++UNDO.still>=1){UNDO.past.push(UNDO.cur);if(UNDO.past.length>100)UNDO.past.shift();UNDO.future=[];UNDO.cur=s;skDraft()}
 skMarkSave(s)}
async function skUndo(dir){const from=dir<0?UNDO.past:UNDO.future,to=dir<0?UNDO.future:UNDO.past;undoTick();
 if(UNDO.seen!==UNDO.cur){to.push(UNDO.cur);UNDO.cur=UNDO.seen}  // an unrecorded change in flight counts as a step
 if(!from.length){toast(dir<0?'nothing to undo':'nothing to redo');return}
 to.push(UNDO.cur);const s=from.pop();UNDO.cur=UNDO.seen=s;UNDO.hold=true;try{await skRestore(JSON.parse(s))}finally{UNDO.cur=UNDO.seen=skSnap();UNDO.hold=false}
 skDraft();SK.open=true;drawSK();toast(dir<0?`undone · ${UNDO.past.length} more to undo`:`redone`)}
function skMarkSave(s=skSnap()){const b=$('sksave');if(!b)return;const d=SK.lanes.length>0&&s!==SK.saved;b.classList.toggle('dirty',d);b.textContent=d?'save •':'save';b.title=d?'unsaved changes: save to keep this version (⌘S)':'saved (⌘S)';
 const u=$('skundo'),r=$('skredo');if(u)u.disabled=!UNDO.past.length&&UNDO.seen===UNDO.cur;if(r)r.disabled=!UNDO.future.length}
setInterval(undoTick,300);
$('sk').addEventListener('click',e=>{const t=e.target.closest('#skundo,#skredo');if(!t)return;e.stopPropagation();skUndo(t.id==='skundo'?-1:1)},true);
document.addEventListener('keydown',e=>{if(!(e.metaKey||e.ctrlKey))return;const k=e.key.toLowerCase();
 if(k==='s'&&SK.lanes.length){e.preventDefault();if(e.target.id==='skname')SK.name=e.target.value;SK.open=true;drawSK();$('sksave')&&$('sksave').click();return}  // ⌘S saves, even from the name field
 if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;  // ⌘Z in a text field undoes the typing
 if(k==='z'&&SK.open&&(SK.lanes.length||UNDO.past.length||UNDO.future.length)){e.preventDefault();skUndo(e.shiftKey?1:-1);return}
 if(k==='z'&&!e.shiftKey){const a=[...ACTS].reverse().find(x=>!x.done);if(a){e.preventDefault();actUndo(a)};return}
 if(k==='y'&&UNDO.future.length){e.preventDefault();skUndo(1);return}
 });
// your sketch from last time (a refresh, a crash): it comes back, not playing, marked unsaved if it was
setTimeout(async()=>{let d=null;try{d=JSON.parse(localStorage.getItem('atlasSketchDraft')||'null')}catch(e){}
 if(!d||!d.snap||SK.lanes.length)return;const st=JSON.parse(d.snap);if(!st.lanes||!st.lanes.length)return;
 UNDO.hold=true;try{await skRestore(st);SK.saved=d.saved||null}finally{UNDO.cur=UNDO.seen=skSnap();UNDO.hold=false}
 drawSK();toast(`your sketch from last time is back (${SK.lanes.length} lane${SK.lanes.length>1?'s':''}) · 🎛 sketchpad`)},1500);
function skPlay(){if(SK.playing||!SK.lanes.length)return;AC.resume();
 if(reloadLanes===SK.lanes){reloadPlay=true;return}
 stopAll();padsStopLoop();  // a sketch takes over from whatever was playing (clips over a running sketch still work)
SK.master=AC.createGain();SK.master.gain.value=0.9;SK.master.connect(AC.destination);
 SK.lanes.forEach(l=>{l.g=AC.createGain();l.g.connect(SK.master);if(l.type==='drums'){l.nextAbs=null;l.live=new Map();l.sched=[]}});skGains();SK.start=linkNextBar();SK.nextBar=0;SK.playing=true;SK.voices=[];skTick();cancelAnimationFrame(SK.raf);SK.raf=requestAnimationFrame(skAnim);drawSK()}
function skTick(){if(!SK.playing)return;const L=barLen(),ahead=1.2+Math.max(0,...SK.lanes.map(l=>l.buf&&l.every&&l.type!=='drums'?Math.min(8,skAttack(l)):0));
 SK.lanes.forEach(l=>{if(!l.g&&SK.master){l.g=AC.createGain();l.g.connect(SK.master);skGains()}});  // a lane added while playing joins in
 while(SK.start+SK.nextBar*L<AC.currentTime+ahead){const t=SK.start+SK.nextBar*L;SK.lanes.forEach(l=>{if(l.g&&l.type!=='drums')skBar(AC,l.g,l,SK.nextBar,t,L,SK.voices)});SK.nextBar++}
 SK.lanes.forEach(l=>{if(l.g&&l.type==='drums')drumTick(l)});  // drums: step by step, 250 ms ahead, so edits are heard at once
 SK.timer=setTimeout(skTick,25)}
function skStop(){reloadPlay=false;SK.playing=false;clearTimeout(SK.timer);const now=AC.currentTime;if(SK.master){SK.master.gain.setTargetAtTime(0,now,0.015);const m=SK.master;setTimeout(()=>{try{m.disconnect()}catch(e){}},150)}
 SK.voices.forEach(s=>{try{s.stop(now+0.08)}catch(e){}});SK.voices=[];SK.lanes.forEach(l=>l.on=[]);drawSK()}
function skAnim(){PERF.anim++;skHeads();drumHeads();if(!SK.playing){SK.raf=0;return}const el=$('skpos');if(el){const L=barLen(),t=AC.currentTime-SK.start;const b=Math.floor(t/L);el.textContent=t<0?'waiting for the bar…':`${SK.arr?`section ${secAt(b)} · `:''}bar ${(SK.arr?b%songBars():b)+1} · beat ${Math.floor(t%L/(L/4))+1}`}SK.raf=requestAnimationFrame(skAnim)}
function skWave(c,buf,trim){if(!c||!buf)return;PERF.skWave++;
 const dpr=devicePixelRatio||1,W=Math.floor(c.clientWidth*dpr),H=Math.floor(30*dpr);
 if(!W||!H)return;
 const g=c.getContext('2d');
 if(c.width!==W||c.height!==H){c.width=W;c.height=H}else g.clearRect(0,0,W,H);
 const [ta,tb]=trim||[0,1],xa=ta*W,xb=tb*W;
 const peaks=wavePeaks(buf,W,0,buf.length,4);
 for(let x=0;x<peaks.length;x++){const m=peaks[x];g.fillStyle=x>=xa&&x<=xb?'#8cc0da':'#3a4048';g.fillRect(x,H/2-m*H/2,1,Math.max(1,m*H))}
 const ln=SK.lanes[+c.dataset.skw];
 // the project's beats as this lane plays them: the attack (or a loop's start) sits on a beat, shifted by any nudge
 if(ln){const L=barLen(),bt=L/4,[r0]=skRegion(ln),pad=ln.every!==0&&!skPulse(ln),o=r0+(ln.every===0||pad?0:skAttack(ln))-(ln.nudge||0),X=p=>p/buf.duration*W;
  for(let k=Math.ceil(-o/bt);o+k*bt<=buf.duration;k++){const x=X(o+k*bt);if(x<0)continue;const bar=((k%4)+4)%4===0;g.fillStyle=bar?'rgba(224,164,88,.7)':'rgba(224,164,88,.22)';g.fillRect(x,0,(bar?1.5:1)*dpr,H)}
  const strong=new Set(skStrong(ln,0,buf.duration));g.fillStyle='rgba(255,255,255,.6)';skOnsets(ln).forEach(p=>{const h=strong.has(p)?9:4;g.fillRect(X(p)-0.5*dpr,H-h*dpr,(strong.has(p)?1.5:1)*dpr,h*dpr)});
  if(!pad){const xo=X(o<0?o+Math.ceil(-o/bt)*bt:o);g.fillStyle='#e0a458';g.beginPath();g.moveTo(xo-4*dpr,0);g.lineTo(xo+4*dpr,0);g.lineTo(xo,6*dpr);g.fill()}}  // ▼ = the point on the beat
 if(trim){g.fillStyle='rgba(224,164,88,.12)';g.fillRect(xa,0,xb-xa,H);g.fillStyle='#e0a458';[xa,xb].forEach(x=>{g.fillRect(x-dpr,0,2*dpr,H);g.fillRect(x-3*dpr,H/2-6*dpr,6*dpr,12*dpr)})}
 const l=SK.lanes[+c.dataset.skw];if(l&&(l.fin||l.fout)){const px=ms=>ms/1000/buf.duration*W;g.strokeStyle='#ffffff';g.lineWidth=1.2*dpr;g.beginPath();
  if(l.fin){g.moveTo(xa,H-2*dpr);g.lineTo(Math.min(xb,xa+px(l.fin)),2*dpr)}if(l.fout){g.moveTo(Math.max(xa,xb-px(l.fout)),2*dpr);g.lineTo(xb,H-2*dpr)}g.stroke()}
 const copy=c._base||(c._base=document.createElement('canvas')),base=copy.getContext('2d');
 if(copy.width!==W||copy.height!==H){copy.width=W;copy.height=H}else base.clearRect(0,0,W,H);
 base.drawImage(c,0,0)}
// playhead: a white line on each lane's waveform at the point that's sounding, like the editor's
// attacks inside a clip (spectral-flux-ish on a coarse energy envelope), cached per buffer
function skOnsets(l){if(l.ons&&l.ons.buf===l.buf)return l.ons.v;const b=l.buf,sr=b.sampleRate,hop=256,n=Math.floor(b.length/hop),e=new Float32Array(n);
 const chs=[...Array(b.numberOfChannels).keys()].map(c=>b.getChannelData(c));
 for(let i=0;i<n;i++){let s=0;for(const d of chs)for(let k=i*hop;k<(i+1)*hop;k++)s+=d[k]*d[k];e[i]=10*Math.log10(1e-12+s/(hop*chs.length))}
 // rise in level (dB) over ~20 ms against the level just before; ignore anything far below the clip's peak,
 // where small noise wobbles look like big jumps on a log scale
 let pk=-200;for(let i=0;i<n;i++)pk=Math.max(pk,e[i]);const floor=pk-30,w=Math.max(1,Math.round(0.02*sr/hop)),gap=Math.round(0.09*sr/hop);
 const f=new Float32Array(n);for(let i=w;i<n;i++){let pre=-200;for(let k=i-w;k<i;k++)pre=Math.max(pre,e[k]);f[i]=e[i]>floor?Math.max(0,e[i]-pre):0}
 const v=[],lv=[];let last=-1e9;const lvAt=i=>{let m=-200;for(let k=i;k<Math.min(n,i+Math.round(0.08*sr/hop));k++)m=Math.max(m,e[k]);return m};
 for(let i=w;i<n-1;i++)if(f[i]>=4&&f[i]>=f[i-1]&&f[i]>=f[i+1]){if(i-last>gap){v.push(i*hop/sr);lv.push(lvAt(i));last=i}
  else if(f[i]>f[Math.round(v[v.length-1]*sr/hop)]){v[v.length-1]=i*hop/sr;lv[lv.length-1]=lvAt(i);last=i}}
 // a long clip cut from inside a song starts with a short fade-in, which reads as an "attack" at 0: drop it
 if(b.duration>4&&v.length&&v[0]<0.06){v.shift();lv.shift()}
 l.ons={buf:b,v,lv};return v}
// the attacks that matter: within 10 dB of the loudest attack in the range
function skStrong(l,a,b){skOnsets(l);const {v,lv}=l.ons;let mx=-200;v.forEach((p,k)=>{if(p>=a&&p<=b)mx=Math.max(mx,lv[k])});return v.filter((p,k)=>p>=a&&p<=b&&lv[k]>=mx-10)}
// re-align: try putting each attack near the start of the selection on the beat (and small shifts around it),
// keep the placement where the most of the clip's attacks fall on the project's 8th-note grid
function skAlign(l){if(l.every!==0&&!skPulse(l)){l.nudge=0;return 'no steady pulse in this selection: it plays from its start, like a pad'}
 const [r0,R]=skRegion(l),e8=barLen()/8,o0=r0+(l.every===0?0:skAttack(l));
 const ons=skOnsets(l).filter(p=>p>=r0&&p<=r0+R);if(ons.length<4){l.nudge=0;return 'too few attacks to find a pulse: first attack put on the beat'}
 const hit=c=>ons.reduce((s,p)=>{const ph=(((p-c)/e8)%1+1)%1,d=Math.min(ph,1-ph)*e8;return s+Math.exp(-((d/0.025)**2))},0);
 const cands=ons.filter(p=>p<=r0+Math.min(R,barLen()*2));let best=o0,bs=hit(o0);
 for(const c of cands)for(let dl=-0.04;dl<=0.0401;dl+=0.01){const s=hit(c+dl);if(s>bs+1e-9){bs=s;best=c+dl}}
 // what random placement would score, to tell a real pulse from noise
 let rnd=0;for(let k=0;k<16;k++)rnd+=hit(o0+k*e8/16);rnd/=16;
 const on=ons.filter(p=>{const ph=(((p-best)/e8)%1+1)%1;return Math.min(ph,1-ph)*e8<0.035}).length;
 if(bs<rnd*1.5){l.nudge=0;return `no clear pulse in this selection (${on} of ${ons.length} attacks near the grid, about what chance gives): first attack put on the beat`}
 // any whole number of 8ths fits the grid equally well: apply only the smallest shift, so the clip stays where it was
 let dlt=best-o0;dlt-=Math.round(dlt/e8)*e8;
 l.nudge=-dlt;return `aligned: ${on} of ${ons.length} attacks on the grid${Math.abs(l.nudge)>0.001?` (moved ${Math.round(l.nudge*1000)} ms)`:''}`}
// does this lane have a steady pulse? Measured on the server with Essentia's beat tracker (confidence >= 2.5 and
// steady beats). No pulse = a pad or texture: it plays from the start of its selection, nothing to line up.
function skPulse(l){return l.pulse&&l.pulse.ok?l.pulse:null}
function skHeads(){const now=AC.currentTime,dpr=devicePixelRatio||1;SK.lanes.forEach((l,k)=>{const c=document.querySelector(`[data-skw="${k}"]`);if(!c||!c._base||!l.buf)return;
 const g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);g.drawImage(c._base,0,0);
 const v=(l.on||[]).filter(v=>now>=v.t0&&now<v.t0+v.dur).pop();if(!v||!SK.playing)return;
 const x=(v.off+(now-v.t0))/l.buf.duration*c.width;g.fillStyle='#fff';g.fillRect(x-dpr,0,2*dpr,c.height);g.fillStyle='rgba(255,255,255,.15)';g.fillRect(x-6*dpr,0,5*dpr,c.height)})}
function drawSK(){const el=$('sk');if(typeof drawNP==='function')drawNP();
 if(!SK.open){el.classList.toggle('skmini',SK.playing);el.hidden=!SK.playing;  // hidden but playing: a small bar to stop it or bring it back
  if(SK.playing)el.innerHTML=`<div class="skminibar">🎛 <b>sketch playing</b><span class="sub">samples you play are heard over it</span><span id="skpos" class="sub"></span><span style="flex:1"></span><button id="skplay" class="pill">■ stop</button><button id="skshow">▴ show</button></div>`;
  return}
 el.classList.remove('skmini');el.hidden=false;
 el.innerHTML=`<h3><button id="skhide" title="hide the sketchpad (it keeps playing; the 🎛 sketchpad button brings it back)">▾ hide</button> 🎛 Sketchpad${hq('sketch')} <span class="skbpm" title="the sketch's tempo (the project tempo): − / + (shift: ±5), type it, or tap the beat"><button class="tbtn" data-skbpm="-1">−</button><input id="skbpm" type="number" min="40" max="220" step="1" value="${Math.round(PROJ.bpm||120)}"><button class="tbtn" data-skbpm="1">+</button> bpm <button class="tbtn" id="sktap">tap</button></span> <span class="sub">${esc(PROJ.key||'no key')} — every lane conformed to the project${PROJ.link&&LINK.peers?' · starts on Live\'s next bar':''}</span>
 <button id="skplay" class="${SK.playing?'pill':''}">${SK.playing?'■ stop':'▶ play'}</button><span id="skpos" class="sub"></span><span style="flex:1"></span>
 <span class="skarr" title="arrangement: sections in order (e.g. AABA), each the length chosen; tick the letters on each lane for the sections it plays in. Empty = loop everything"><input id="skarr" placeholder="arrange: AABA" maxlength="16" value="${esc(SK.arr||'')}" style="width:96px"> × <select id="sksec">${[1,2,4,8].map(n=>`<option value="${n}" ${SK.sec===n?'selected':''}>${n} bar${n>1?'s':''}</option>`).join('')}</select></span>
 <button class="tbtn" id="skundo" title="undo (⌘Z)">↶</button><button class="tbtn" id="skredo" title="redo (⌘⇧Z)">↷</button>
 <input id="skname" placeholder="sketch name" style="width:130px" value="${esc(SK.name||'')}"><button id="sksave" class="${skDirty()?'dirty':''}" title="${skDirty()?'unsaved changes: save to keep this version (⌘S)':'saved (⌘S)'}">${skDirty()?'save •':'save'}</button><select id="skbars" title="bounce / stems / Live set length">${songBars()?`<option value="${songBars()}" selected>song · ${songBars()} bars</option>`:''}<option value="4">4 bars</option><option value="8" ${songBars()?'':'selected'}>8 bars</option><option value="16">16 bars</option></select><button id="skbounce" title="render the mix as a new sample (favourited, with provenance)">⤓ bounce</button>
 <button id="skstems" title="each lane as its own WAV, all the same length from bar 1, in the sketch's key and tempo: drop them into Live and they line up">⇩ stems</button><button id="skals" title="a Live set: one audio track per lane, a clip wherever it plays, at the sketch's tempo (muted lanes come in as muted tracks). Opens in Live.">⇩ Live set</button><button id="skexp" title="export conformed copies + a Drum Rack to Ableton">⇩ Ableton</button><button id="skclear">clear</button></h3>
 ${SK.lanes.map((l,k)=>{if(l.type==='drums')return drumLaneHTML(l,k);const s=S[l.i]||[];const loop=s[F.kind]==='loop';const pu=l.state==='ok'&&!loop?skPulse(l):null;
  const tbars=l.trim&&l.buf&&barLen()?(l.trim[1]-l.trim[0])*l.buf.duration/barLen():0,tb=Math.round(tbars);
  const tags=[l.trim?`✂ ${tb>=1&&Math.abs(tbars-tb)<0.004?`${tb} bar${tb>1?'s':''}`:Math.round((l.trim[1]-l.trim[0])*100)+'%'}`:'',l.nat?'orig key':'',loop?'loop':`every ${l.every} · +${l.offset}`,l.hold&&LOOPS[l.i]?'∞ held':'',
   loop||l.state!=='ok'?'':l.src?`tempo-matched to ${PROJ.bpm}`:pu?`pulse ≈ ${pu.bpm} bpm`:'no pulse'].filter(Boolean).join(' · ');
  const fit=!loop&&l.state==='ok'&&pu&&!l.src;
  return`<div class="lane${l.mute?' muted':''}" data-ln="${k}">
  <label class="onoff" title="turn this lane on or off"><input type="checkbox" data-skon="${k}" ${l.mute?'':'checked'}><span></span></label>
  <div class="lname" title="${esc(s[F.artist]||'')} — ${esc(s[F.title]||'')} · ${esc(s[F.sub]||'')} ${s[F.cam]||''}"><div class="name">${secChips(l,k)}<span class="badge" style="background:${col(s[F.cat])}">${AB[s[F.cat]]}</span>${esc(s[F.artist]||'')}</div><div class="meta">${esc(s[F.title]||'')} · ${tags}</div></div>
  <div class="lwave"><div class="lbtns">${fit?`<button class="tbtn realign fitb" data-skfit="${k}" title="the clip has a steady pulse of about ${pu.bpm} bpm: stretch it onto ${PROJ.bpm} bpm so every attack stays on the grid">⟷ match tempo</button>`:''}${l.src?`<button class="tbtn realign fitb" data-skunfit="${k}" title="back to the clip's own tempo">⟷ undo match</button>`:''}${l.trim||l.nudge?`<button class="tbtn realign" data-skalign="${k}" title="put the first strong attack of the selection on the beat (clears any nudge)">↺ re-align</button>`:''}</div>${l.state==='ok'?`<canvas data-skw="${k}"></canvas>`:`<span class="sub">${l.state==='loading'?'conforming…':'failed to load'}</span>`}</div>
  <div class="fader" title="volume relative to the other lanes (all start equally loud at 0 dB) · double-click for 0 dB"><input type="range" min="-24" max="6" step="0.5" value="${l.db||0}" data-skv="${k}"><output>${dbTxt(l.db||0)}</output></div>
  <button class="tbtn${l.solo?' on':''}" data-sks="${k}" title="solo">S</button><button class="tbtn${l.more?' on':''}" data-skmore="${k}" title="timing, key, fades, open, remove">⋯</button>
  ${l.more?`<div class="lmore">${loop?'<span class="sub">loop: locked to the bar</span>':`<label class="sub">repeat <select data-ske="${k}">${Array.from({length:16},(_,j)=>j+1).map(n=>`<option value="${n}" ${l.every===n?'selected':''}>every ${n} bar${n>1?'s':''}</option>`).join('')}</select></label>
   <label class="sub">start <select data-sko="${k}">${Array.from({length:32},(_,b)=>b/2).map(b=>`<option value="${b}" ${l.offset===b?'selected':''}>+${b} beat${b===1?'':'s'}</option>`).join('')}</select></label>`}
   ${!loop&&LOOPS[l.i]?`<button class="tbtn${l.hold?' on':''}" data-skhold="${k}" title="hold: sustain the clip on its seamless loop for the whole repeat length, so a short pad becomes a bed">∞ hold</button>`:''}
   ${s[F.cat]!=='Percussion'&&s[F.cam]?`<button class="tbtn${l.nat?' on':''}" data-sknat="${k}" title="keep this lane's own key instead of moving it to the project key">orig key (${s[F.cam]})</button>`:''}
   <span class="sub" title="slide this lane in time (or ⌥-drag its waveform)">nudge <button class="tbtn" data-sknudge="${k}" data-d="-1">◀</button><output>${Math.round((l.nudge||0)*1000)} ms</output><button class="tbtn" data-sknudge="${k}" data-d="1">▶</button></span>
   <label class="sub" title="fade in at every repeat">fade in <input type="range" min="0" max="2000" step="10" value="${l.fin||0}" data-skfi="${k}" style="width:80px"> <output>${l.fin||0} ms</output></label>
   <label class="sub" title="fade out at the end of every repeat">fade out <input type="range" min="0" max="2000" step="10" value="${l.fout||0}" data-skfo="${k}" style="width:80px"> <output>${l.fout||0} ms</output></label>
   ${l.trim?'<span class="sub">trimmed: double-click the waveform for the whole clip</span>':'<span class="sub">drag on the waveform to use part of the clip</span>'}
   <span style="flex:1"></span><button data-go="${l.i}" title="open in the sample panel">open →</button><button data-skx="${k}" title="remove from the sketch">remove ✕</button></div>`:''}</div>`}).join('')||'<div class="sub">Empty — press ＋ on any sample (list, detail panel, “goes well with”) to add it.</div>'}
 <div class="hint">Amber lines = the project's bars and beats as each lane plays; white ticks = the clip's own attacks. Drag a waveform to use part of it · ⌥-drag to slide it in time (⌥⇧ for fine) · ↺ re-align puts the first attack back on the beat.</div>`;
 skWaves()}
function skWaves(){const el=$('sk');SK.lanes.forEach((l,k)=>{
 const c=reuseWaveCanvas(el.querySelector(`[data-skw="${k}"]`),l,'data-skw');
 skWave(c,l.buf,l.trim)
})}
window.addEventListener('resize',()=>{
 if(SK.open)rafOnce('skresize',()=>{if(SK.open){skWaves();padWaves()}})
});
// trim a lane: drag on its waveform to pick a part, grab an edge to move just that edge, double-click for the whole clip
(function(){let drag=null;const sk=$('sk'),frac=(c,e)=>Math.max(0,Math.min(1,(e.clientX-c.getBoundingClientRect().left)/c.clientWidth));
 sk.addEventListener('mousedown',e=>{const c=e.target.closest('[data-skw]');if(!c)return;e.preventDefault();const l=SK.lanes[+c.dataset.skw];if(!l||!l.buf)return;
  if(e.altKey){drag={c,l,nudgeFrom:e.clientX,n0:l.nudge||0};return}  // ⌥-drag slides the lane in time (+shift: 10x finer)
  const f=frac(c,e),[a,b]=l.trim||[0,1],px=7/c.clientWidth;
  const nearA=Math.abs(f-a)<=px,nearB=Math.abs(f-b)<=px;
  if(nearA||nearB)drag={c,l,anchor:nearA&&(!nearB||Math.abs(f-a)<Math.abs(f-b))?b:a};  // move one edge, keep the other
  else{drag={c,l,anchor:f};l.trim=[f,f]}});
 window.addEventListener('mousemove',e=>{
  if(drag){const {c,l,nudgeFrom,n0,anchor}=drag,duration=l.buf.duration;
   if(nudgeFrom!=null)l.nudge=Math.max(-2,Math.min(2,n0+(e.clientX-nudgeFrom)/c.clientWidth*duration*(e.shiftKey?0.1:1)));
   else{let f=frac(c,e);
    // the length sticks at whole bars (1, 2, 3…) of the project when the edge comes within 8 px of one; ⌥ moves freely
    const bar=barLen();if(bar&&!e.altKey){const len=Math.abs(f-anchor)*duration,n=Math.round(len/bar),tol=Math.min(0.2*bar,8/c.clientWidth*duration);
     if(n>=1&&Math.abs(len-n*bar)<=tol){const ff=anchor+Math.sign(f-anchor)*n*bar/duration;if(ff>=-1e-6&&ff<=1+1e-6)f=Math.max(0,Math.min(1,ff))}}
    l.trim=[Math.min(anchor,f),Math.max(anchor,f)]}
   rafOnce('skdrag',()=>{if(c.isConnected)skWave(c,l.buf,l.trim)});return}
  const c=e.target.closest&&e.target.closest('[data-skw]');if(c){const l=SK.lanes[+c.dataset.skw];const f=frac(c,e),[a,b]=(l&&l.trim)||[0,1],px=7/c.clientWidth;c.style.cursor=l&&l.trim&&(Math.abs(f-a)<=px||Math.abs(f-b)<=px)?'ew-resize':'crosshair'}});
 window.addEventListener('mouseup',()=>{if(!drag)return;if(drag.nudgeFrom!=null){drag=null;drawSK();return}const l=drag.l;if(l.trim&&l.trim[1]-l.trim[0]<0.01)l.trim=null;if(l.trim&&l.trim[0]<0.002&&l.trim[1]>0.998)l.trim=null;drag=null;drawSK()});
 sk.addEventListener('dblclick',e=>{const c=e.target.closest('[data-skw]');if(!c)return;SK.lanes[+c.dataset.skw].trim=null;drawSK()})})();
$('sk').addEventListener('click',async e=>{const t=e.target;
 if(t.id==='skplay'){SK.playing?skStop():skPlay();return}if(t.id==='skhide'){SK.open=false;drawSK();drawProj();return}
 if(t.id==='skshow'){SK.open=true;drawSK();drawProj();return}
 if(t.id==='skclear'){skStop();SK.lanes=[];SK.name='';drawSK();drawProj();toast('cleared · ⌘Z brings it back');return}
 if(t.dataset.skm!=null){const l=SK.lanes[+t.dataset.skm];l.mute=!l.mute;skGains();drawSK();return}
 if(t.dataset.sks!=null){const l=SK.lanes[+t.dataset.sks];l.solo=!l.solo;skGains();drawSK();return}
 if(t.dataset.skfit!=null){const l=SK.lanes[+t.dataset.skfit],pu=skPulse(l);if(!pu)return;l.src=pu.bpm;l.nudge=0;toast('stretching…');drawSK();await skLoad(l);const r=skAlign(l);drawSK();toast(`tempo-matched (${pu.bpm} → ${PROJ.bpm} bpm) · ${r}`);return}
 if(t.dataset.skunfit!=null){const l=SK.lanes[+t.dataset.skunfit];l.src=null;l.nudge=0;drawSK();await skLoad(l);drawSK();return}
 if(t.dataset.skalign!=null){const l=SK.lanes[+t.dataset.skalign];if(!l.buf)return;const r=skAlign(l);drawSK();toast(r);return}
 if(t.dataset.sknudge!=null){const l=SK.lanes[+t.dataset.sknudge],step=e.shiftKey?barLen()/16:0.01;l.nudge=Math.max(-2,Math.min(2,(l.nudge||0)+(+t.dataset.d)*step));drawSK();return}
 if(t.dataset.skmore!=null){const l=SK.lanes[+t.dataset.skmore];l.more=!l.more;drawSK();return}
 if(t.dataset.skhold!=null){const l=SK.lanes[+t.dataset.skhold];l.hold=!l.hold;if(l.hold&&l.every<2)l.every=4;drawSK();if(SK.playing){skStop();skPlay()}return}
 if(t.dataset.sknat!=null){const l=SK.lanes[+t.dataset.sknat];l.nat=!l.nat;drawSK();await skLoad(l);drawSK();return}
 if(t.dataset.skx!=null){SK.lanes.splice(+t.dataset.skx,1);if(!SK.lanes.length)skStop();drawSK();drawProj();return}
 if(t.dataset.go!=null){select(+t.dataset.go,'list');return}
 if(t.id==='sksave'){const name=($('skname').value||'').trim()||`Sketch ${new Date().toLocaleString()}`;SK.name=name;
  await api('api/sketch/save',{name,state:{key:PROJ.key,bpm:PROJ.bpm,arr:SK.arr||'',sec:SK.sec||4,lanes:skLanesState()}}).then(()=>{SK.saved=skSnap();skDraft();skMarkSave();toast(`“${name}” saved · find it in the Kits tab`)}).catch(err=>toast('error: '+err.message));return}
 if(t.id==='skexp'){const name=($('skname').value||'').trim()||'Sketch '+new Date().toISOString().slice(0,10);toast('exporting conformed copies + Drum Rack…');
  api('api/export',{scope:'paths',paths:SK.lanes.flatMap(l=>l.type==='drums'?l.pads.map(p=>p.path):[l.path]),name,
   pad_edits:Object.fromEntries(SK.lanes.filter(l=>l.type==='drums').flatMap(l=>l.pads.map(p=>[p.path,{start:p.start||0,end:p.end||null,tune:p.tune||0,decay:p.decay||0}]))),key:PROJ.key,bpm:PROJ.bpm,rack:true,reveal:true}).then(r=>toast(`exported ${r.count} files + rack → ${name}`)).catch(err=>toast('error: '+err.message));return}
 if(t.id==='skbounce'){skBounce(+$('skbars').value);return}
 if(t.id==='skstems'){skStems(+$('skbars').value);return}if(t.id==='skals'){skStems(+$('skbars').value,true);return}});
// aligned stems: render every audible lane alone over the same N bars, so each file starts on bar 1 and they all line up
async function skStems(bars,als){if(!SK.lanes.length||SK.lanes.some(l=>!l.buf)){toast('wait for every lane to load');return}
 const L=barLen(),sr=44100,solo=SK.lanes.some(laneSolo),name=($('skname').value||'').trim()||SK.name||'Sketch '+new Date().toISOString().slice(0,10);
 const off=l=>l.mute||(solo&&!laneSolo(l));
 // stems: only what you hear; a Live set: every lane, the silent ones as muted tracks you can bring back
 const lanes=als?SK.lanes:SK.lanes.filter(l=>!off(l));if(!lanes.length){toast('every lane is muted');return}toast(`rendering ${lanes.length} ${als?'tracks':'stems'}…`);
 try{const stems=[];
  for(const l of lanes){const ctx=new OfflineAudioContext(2,Math.ceil(bars*L*sr),sr),g=ctx.createGain();g.gain.value=laneGain(l);g.connect(ctx.destination);
   for(let b=0;b<bars;b++)skBar(ctx,g,l,b,b*L,L,null);const s=l.type==='drums'?null:S[l.i];
   stems.push({label:s?`${AB[s[F.cat]]} ${s[F.artist]} - ${s[F.title]}`:`DRUMS ${l.pads.length} pads`,wav:await wavB64(await ctx.startRendering()),mute:off(l),category:s?s[F.cat]:'Percussion',drums:!s||s[F.cat]==='Percussion'})}
  const r=await api('api/stems',{name,key:PROJ.key,bpm:PROJ.bpm,stems,als:!!als,bars});
  toast(als?`Live set “${r.als.split('/').pop()}” written · opening it in Live`:`${r.files.length} stems → ${r.dest.split('/').slice(-2).join('/')} · set Live to ${PROJ.bpm} bpm, ⌘-drag them in to get one track each`)}catch(e){toast((als?'Live set':'stems')+' failed: '+e.message)}}
$('sk').addEventListener('input',e=>{const t=e.target;
 if(t.dataset.skfi!=null||t.dataset.skfo!=null){const l=SK.lanes[+(t.dataset.skfi??t.dataset.skfo)];l[t.dataset.skfi!=null?'fin':'fout']=+t.value;
  const o=t.parentNode.querySelector('output');if(o)o.textContent=t.value+' ms';const k=SK.lanes.indexOf(l);skWave(document.querySelector(`[data-skw="${k}"]`),l.buf,l.trim);return}if(t.dataset.skv!=null){const l=SK.lanes[+t.dataset.skv];l.db=+t.value;skGains();const o=t.parentNode.querySelector('output');if(o)o.textContent=dbTxt(l.db)}});
$('sk').addEventListener('dblclick',e=>{const t=e.target;if(t.dataset&&t.dataset.skv!=null){const l=SK.lanes[+t.dataset.skv];l.db=0;skGains();drawSK()}});
$('sk').addEventListener('change',e=>{const t=e.target;if(t.dataset.skon!=null){const l=SK.lanes[+t.dataset.skon];l.mute=!t.checked;skGains();drawSK();return}if(t.dataset.ske!=null){SK.lanes[+t.dataset.ske].every=+t.value;drawSK();return}if(t.dataset.sko!=null){SK.lanes[+t.dataset.sko].offset=+t.value;drawSK();return}if(t.id==='skname')SK.name=t.value});
$('sk').addEventListener('input',e=>{if(e.target.id==='skname')SK.name=e.target.value},true);
async function skBounce(bars){if(!SK.lanes.length||SK.lanes.some(l=>!l.buf)){toast('wait for every lane to load');return}
 const L=barLen(),sr=44100,len=bars*L,tail=SK.lanes.some(l=>l.every)?Math.min(4,Math.max(...SK.lanes.map(l=>l.buf.duration))):0;
 const ctx=new OfflineAudioContext(2,Math.ceil((len)*sr),sr),solo=SK.lanes.some(laneSolo);
 SK.lanes.forEach(l=>{if(l.mute||(solo&&!laneSolo(l)))return;const g=ctx.createGain();g.gain.value=laneGain(l);g.connect(ctx.destination);for(let b=0;b<bars;b++)skBar(ctx,g,l,b,b*L,L,null)});
 toast('bouncing…');const buf=await ctx.startRendering();const first=SK.lanes.find(l=>l.path)||{path:(SK.lanes[0].pads[0]||{}).path};
 try{const r=await api('api/bounce',{parent:first.path,wav:await wavB64(buf),kind:'loop',bpm:PROJ.bpm,bars,key:PROJ.key,prefix:'Sketch',name:($('skname').value||'').trim(),
   tag:`sketch ${SK.lanes.length} layers`,ops:{key:PROJ.key,bpm:PROJ.bpm,lanes:skLanesState()}});
  const j=addRow(first.i,r.row);toast('bounced → new sample (★ favourited)');select(j,'go')}catch(e){toast('bounce failed: '+e.message)}}
function addRow(i,n){const row=S[i].slice();Object.assign(row,{[F.id]:n.id,[F.path]:n.path,[F.cat]:n.category,[F.sub]:n.subtype,[F.kind]:n.kind,[F.cam]:n.cam,[F.key]:n.key,[F.bpm]:n.bpm,[F.dur]:n.dur,
 [F.env]:n.env,[F.note]:n.note,[F.bars]:n.bars,[F.start]:n.start,[F.parent]:n.parent,[F.root]:n.root,[F.ops]:n.ops});
 const j=S.push(row)-1;P.push(n.partners?n.partners.map(([id,sc,h,v])=>[BYID.get(id),sc,h,v]).filter(x=>x[0]!=null):P[i]);BYID.set(n.id,j);byPath.set(n.path,j);(BYTRACK.get(row[F.tid])||[]).push(j);
 FAV.set(n.path,{path:n.path,sample_id:n.id,label:n.ops,added_at:new Date().toISOString()});return j}
function wavBytes(buf){const n=buf.length,ch=2,sr=buf.sampleRate,b=new ArrayBuffer(44+n*ch*2),v=new DataView(b),w=(o,s)=>{for(let k=0;k<s.length;k++)v.setUint8(o+k,s.charCodeAt(k))};
 w(0,'RIFF');v.setUint32(4,36+n*ch*2,true);w(8,'WAVE');w(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,ch,true);v.setUint32(24,sr,true);v.setUint32(28,sr*ch*2,true);v.setUint16(32,ch*2,true);v.setUint16(34,16,true);w(36,'data');v.setUint32(40,n*ch*2,true);
 const left=buf.getChannelData(0),right=buf.numberOfChannels>1?buf.getChannelData(1):left;
 const pcm=new Int16Array(b,44,n*ch);
 for(let k=0;k<n;k++){
  pcm[k*ch]=Math.max(-1,Math.min(1,left[k]))*32767;
  pcm[k*ch+1]=Math.max(-1,Math.min(1,right[k]))*32767
 }
 return new Uint8Array(b)
}
async function wavB64(buf){
 const blob=new Blob([wavBytes(buf)]);
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(reader.result.slice(reader.result.indexOf(',')+1));
  reader.onerror=()=>reject(reader.error);
  reader.readAsDataURL(blob)
 })
}
// sketches + kit racks in the Kits tab
async function renderKitExtras(){const L=$('list');
 L.querySelectorAll('[data-kitexp]').forEach(b=>{const k=D.kits.findIndex(x=>x.name===b.dataset.kitexp);b.insertAdjacentHTML('afterend',` <button data-kitrack="${k}" title="export + Ableton Drum Rack">⇩ rack</button> <button data-kitsk="${k}" title="load into the sketchpad">🎛 sketch</button>`)});
 if(!SERVED)return;let sk=[];try{sk=await api('api/sketches')}catch(e){}if(st.tab!=='K'||!sk.length)return;
 L.insertAdjacentHTML('afterbegin',`<div class="kit"><h3><span>Your sketches${hq('kits')}</span></h3>${sk.map(x=>{const s=JSON.parse(x.state);return`<div class="prow"><button class="play" data-skopen="${esc(x.name)}">▶</button><div style="min-width:0"><div class="name"><a href="#" data-skload="${esc(x.name)}" title="open in the sketchpad without playing">${esc(x.name)}</a></div><div class="meta">${esc(s.key||'')} · ${s.bpm||'—'} bpm · ${s.lanes.length} lanes · ${esc(x.updated_at?new Date(x.updated_at.replace(' ','T')+'Z').toLocaleString():'')}</div></div><button data-skdel="${esc(x.name)}">✕</button></div>`}).join('')}</div>`);
 L.querySelectorAll('[data-skopen]').forEach(b=>b.onclick=()=>{const x=sk.find(z=>z.name===b.dataset.skopen);skOpen(x.name,JSON.parse(x.state))});
 L.querySelectorAll('[data-skload]').forEach(b=>b.onclick=e=>{e.preventDefault();const x=sk.find(z=>z.name===b.dataset.skload);skOpen(x.name,JSON.parse(x.state),false)});
 L.querySelectorAll('[data-skdel]').forEach(b=>b.onclick=async()=>{await api('api/sketch/delete',{name:b.dataset.skdel});render()})}
async function skOpen(name,s,play=true){skStop();Object.assign(PROJ,{key:s.key,bpm:s.bpm});try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(e){}drawProj();
 UNDO.hold=true;SK.name=name;SK.arr=s.arr||'';SK.sec=s.sec||4;SK.lanes=s.lanes.map(l=>l.type==='drums'?{...l,state:'loading',buf:null,pads:l.pads.map(p=>({...p,i:byPath.get(p.path),buf:null})).filter(p=>p.i!=null)}:({...l,i:byPath.get(l.path),buf:null,state:'loading'})).filter(l=>l.type==='drums'?l.pads.length:l.i!=null);
 SK.saved=skSnap();UNDO.hold=false;
 const miss=s.lanes.length-SK.lanes.length;if(miss)toast(`${miss} lane${miss>1?'s are':' is'} newer than this page: run "digitalcrate build" and reload to hear the whole sketch`);SK.open=true;drawSK();drawProj();await Promise.all(SK.lanes.map(skLoad));drawSK();if(play)skPlay()}
document.addEventListener('click',async e=>{const kr=e.target.closest('[data-kitrack]');if(kr){e.stopPropagation();const k=D.kits[+kr.dataset.kitrack];kr.textContent='building…';
  try{const r=await api('api/export',{scope:'paths',paths:kitMembers(k).map(i=>S[i][F.path]),name:k.name,rack:true,reveal:true});kr.textContent=`rack ✓ (${r.count})`}catch(err){kr.textContent='error'}return}
 const ks=e.target.closest('[data-kitsk]');if(ks){e.stopPropagation();const k=D.kits[+ks.dataset.kitsk];if(SK.lanes.length)setTimeout(()=>toast('the sketch was replaced · ⌘Z brings it back'),400);skStop();SK.lanes=[];SK.name=k.name;
  // a kit was built around one key and tempo (they're in its name): use those, not whatever the project was last set to
  const m=k.name.match(/_(\d{1,2}[AB])-[^_]*_(\d+)bpm/);if(m){PROJ.key=keyFromCam(m[1].replace(/^0/,''));if(!(PROJ.link&&LINK.peers))PROJ.bpm=+m[2];
   try{localStorage.setItem('atlasProj',JSON.stringify(PROJ))}catch(err){}drawProj();toast(`sketch set to ${PROJ.key} · ${PROJ.bpm} bpm, from the kit`)}
  for(const i of kitMembers(k))await skAdd(i);skPlay();return}
 const a=e.target.closest('[data-sk]');if(a){e.stopPropagation();e.preventDefault();skAdd(+a.dataset.sk)}},true);

// ================= detail panel: ＋ sketch · pads · MIDI · project info =================
const _select=select;
select=function(i,from){if(CH.play&&CH.i!==i)chStop();_select(i,from);augment(i)};
function augment(i){const eo=$('edopen');if(!eo)return;eo.parentNode.style.flexWrap='wrap';
 eo.insertAdjacentHTML('afterend',` <button data-sk="${i}" title="add to the sketchpad">＋ sketch</button><button id="padsopen" title="play its syllables / notes from the keyboard, record a pattern">🎹 pads</button>${S[i][F.cat]!=='Percussion'&&S[i][F.cam]?'<button id="midiopen" title="notes & chords → MIDI">♪ MIDI</button>':''}${S[i][F.cat]!=='Percussion'&&!String(S[i][F.path]).startsWith('_Reference')?'<button id="chordsopen" title="chord progressions that suit this sample, played on a synth pad">🎼 chords</button>':''}`);
 eo.parentNode.insertAdjacentHTML('afterend','<div class="sub" id="pjinfo" style="margin:-4px 0 8px"></div>');
 $('editor').insertAdjacentHTML('afterend','<div class="ed" id="pads" hidden></div><div class="ed" id="midibox" hidden></div><div class="ed" id="chordbox" hidden></div>');
 document.querySelectorAll('#detail [data-pair]').forEach(b=>b.insertAdjacentHTML('beforebegin',`<button data-sk="${b.dataset.pair}" title="add to the sketchpad">＋</button><button data-savepair="${b.dataset.pair}" title="save this pair as a sketch (Kits tab), ready to open or export as aligned stems">💾</button>`));
 if(PROJ.key||PROJ.bpm)projInfo(i);if(PADS.i!==i)padsClose()}
$('detail').addEventListener('click',async e=>{const sp=e.target.closest('[data-savepair]');if(sp){e.stopPropagation();const j=+sp.dataset.savepair;
  try{const r=await api('api/pair/save',{src:S[st.sel][F.path],partner:S[j][F.path]});sp.textContent='✓';toast(`saved “${r.name}” · open it from the Kits tab`)}catch(err){toast('error: '+err.message)}return}
 if(e.target.id==='padsopen'){openPads(st.sel);return}if(e.target.id==='midiopen'){openMidi(st.sel);return}if(e.target.id==='chordsopen'){openChords(st.sel);return}});

// ---------- MIDI
// ================= chords: progressions that suit a sample, heard on a synth pad =================
// pad voices: each note = a few detuned oscillators through a lowpass, slow attack, long release, into a shared reverb
const PADV={warm:{osc:[['sawtooth',-7],['sawtooth',7]],cut:900,q:0.7,att:0.6,rel:1.6,gain:0.16},
 glass:{osc:[['triangle',0],['sine',1200]],cut:4200,q:0.4,att:0.35,rel:2.2,gain:0.2},
 strings:{osc:[['sawtooth',-12],['sawtooth',0],['sawtooth',12]],cut:2300,q:0.6,att:0.9,rel:1.8,gain:0.11,vib:5},
 rhodes:{osc:[['sine',0],['triangle',1200]],cut:3000,q:0.5,att:0.01,rel:1.2,gain:0.24,decay:1.6}};
const REVERB_IR=new Map();
function padReverb(ctx){
 const sr=ctx.sampleRate;
 let impulse=REVERB_IR.get(sr);
 if(!impulse){
  const n=Math.floor(sr*3);
  impulse=ctx.createBuffer(2,n,sr);
  for(let c=0;c<2;c++){
   const samples=impulse.getChannelData(c);
   for(let k=0;k<n;k++)samples[k]=(Math.random()*2-1)*Math.pow(1-k/n,3)
  }
  REVERB_IR.set(sr,impulse);
  PERF.ir++
 }
 const convolver=ctx.createConvolver();
 convolver.buffer=impulse;
 return convolver
}
function padChord(ctx,dest,notes,t,dur,kind){const v=PADV[kind]||PADV.warm;
 notes.forEach((n,ni)=>{const f=440*Math.pow(2,(n-69)/12),g=ctx.createGain(),lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=v.cut*(ni===0?0.6:1);lp.Q.value=v.q;
  const lvl=v.gain*(ni===0?0.8:1)/Math.sqrt(notes.length);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(lvl,t+v.att);
  if(v.decay)g.gain.setTargetAtTime(lvl*0.35,t+v.att,v.decay/3);g.gain.setValueAtTime(v.decay?lvl*0.35:lvl,t+dur);g.gain.linearRampToValueAtTime(0,t+dur+v.rel);
  lp.connect(g);g.connect(dest);
  let vibrato=null;
  if(v.vib){
   const lfo=ctx.createOscillator();
   vibrato=ctx.createGain();
   lfo.frequency.value=v.vib;vibrato.gain.value=4;lfo.connect(vibrato);
   lfo.start(t);lfo.stop(t+dur+v.rel)
  }
  v.osc.forEach(([type,cents])=>{const o=ctx.createOscillator();o.type=type;o.frequency.value=f;o.detune.value=cents;
   if(vibrato)vibrato.connect(o.detune);
   o.connect(lp);o.start(t);o.stop(t+dur+v.rel+0.05)})})}
const chLen=(r,o)=>r.follows?r.total:o.chords.length*r.step;           // one pass of the progression
const chAt=(r,c,k)=>r.follows?[c.t,c.d]:[k*r.step,r.step];             // a chord's start and length in that pass
function padProgression(ctx,dest,opt,step,t0,kind,reps=1,r=CH.res){const L=chLen(r,opt);for(let n=0;n<reps;n++)opt.chords.forEach((c,k)=>{const [a,d]=chAt(r,c,k);padChord(ctx,dest,c.notes,t0+n*L+a,d,kind)})}
// ---- basslines under the chords: patterns built from each chord's root, 3rd and 5th on the beat grid
const BASSES={off:'no bass',held:'held roots',root5:'root & fifth',pulse:'8th-note pulse',sync:'syncopated (R&B)',walk:'walking (jazz)'};
function bassAuto(r,s){if(r.follows&&!r.loop)return 'held';  // changes off any steady beat: hold the roots
 if(/jazz/i.test(s[F.genre]||''))return 'walk';return {soulful:'sync',dark:'pulse',ethereal:'held'}[r.style]||'root5'}
function chTones(c){const root=c.notes[0]%12,nm=c.name.replace(/^[A-G][b#♭♯]?/,'');
 const dim=/dim|°|ø|m7b5/.test(nm),aug=/aug|\+/.test(nm),minor=dim||/^m(?!aj)/.test(nm);
 return {root,third:root+(minor?3:4),fifth:root+(dim?6:aug?8:7)}}
// near the last note, in the bass register (E1–G2 for roots)
const bassNear=(pc,prev)=>{let best=null;for(let n=28;n<=50;n++)if(((n-pc)%12+12)%12===0&&(best===null||Math.abs(n-prev)<Math.abs(best-prev)))best=n;return best};
function bassLine(r,o,style){if(!style||style==='off')return [];const beat=60/r.tempo,out=[];let prev=36;
 const cs=o.chords.map((c,k)=>{const [a,d]=chAt(r,c,k);return {c,a,d,t:chTones(c)}});
 cs.forEach((x,k)=>{const nx=cs[(k+1)%cs.length],R=bassNear(x.t.root,prev);prev=R;const F5=R+((x.t.fifth-x.t.root+12)%12),T3=R+((x.t.third-x.t.root+12)%12);
  const beats=[];for(let b=Math.ceil(x.a/beat-1e-6);b*beat<x.a+x.d-1e-6;b++)beats.push(b*beat);if(beats.length&&beats[0]-x.a<beat*0.25)beats[0]=x.a;else beats.unshift(x.a);  // the chord change always gets its root, even off the grid
  const end=x.a+x.d,add=(n,t,d,v=1)=>{if(t<end-1e-4)out.push({n,t,d:Math.min(d,end-t),v})};
  const bar=b=>Math.round(b/beat)%4;
  if(style==='held')add(R,x.a,x.d,0.9);
  else if(style==='root5')beats.forEach(t=>{const p=bar(t);if(p===0||t===x.a)add(R,t,beat*1.9);else if(p===2)add(F5,t,beat*1.9,0.85)});
  else if(style==='pulse')beats.forEach(t=>{add(R,t,beat*0.45,bar(t)===0?1:0.8);add(bar(t)===3?R+12:R,t+beat/2,beat*0.4,0.7)});
  else if(style==='sync')beats.forEach(t=>{const p=bar(t);if(p===0||t===x.a)add(R,t,beat*1.3);if(p===1)add(R,t+beat/2,beat*0.4,0.75);if(p===2)add(R+12,t+beat/2,beat*0.35,0.7);if(p===3)add(F5,t+beat/2,beat*0.45,0.8)});
  else if(style==='walk'){const nR=bassNear(nx.t.root,R),tones=[R,T3,F5,R+12,F5,T3];
   beats.forEach((t,j)=>{let n;if(j===0)n=R;else if(j===beats.length-1)n=nR+(nR>=R?-1:1);else n=tones[j%tones.length];add(n,t,beat*0.9,j===0?1:0.85)})}});
 return out}
function bassNote(ctx,dest,n,t,d,v=1){const f=440*Math.pow(2,(n-69)/12),g=ctx.createGain(),lp=ctx.createBiquadFilter();lp.type='lowpass';lp.Q.value=2;
 lp.frequency.setValueAtTime(900,t);lp.frequency.exponentialRampToValueAtTime(260,t+0.25);
 const lvl=0.32*v;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(lvl,t+0.006);g.gain.setTargetAtTime(lvl*0.7,t+0.006,0.12);
 g.gain.setValueAtTime(lvl*0.7,t+Math.max(0.01,d-0.04));g.gain.linearRampToValueAtTime(0,t+d+0.06);lp.connect(g);g.connect(dest);
 [['sawtooth',0,0.5],['sine',0,1],['sine',-1200,0.6]].forEach(([type,cents,amp])=>{const o=ctx.createOscillator(),og=ctx.createGain();og.gain.value=amp;o.type=type;o.frequency.value=f;o.detune.value=cents;o.connect(og);og.connect(lp);o.start(t);o.stop(t+d+0.1)})}
function bassProgression(ctx,dest,r,o,t0,style){bassLine(r,o,style).forEach(b=>bassNote(ctx,dest,b.n,t0+b.t,b.d,b.v))}
const CH={i:null,res:null,bpc:1,pad:null,lvl:0.8,play:null,bass:null,blvl:0.8};window.CH=CH;window.bassLine=(r,o,st)=>bassLine(r,o,st);window.chAt=chAt;window.BASSES=BASSES;
async function openChords(i,keep){const box=$('chordbox');if(!keep){if(!box.hidden&&CH.i===i){chStop();box.hidden=true;return}}box.hidden=false;CH.i=i;
 box.innerHTML='<div class="sub">listening to the notes and working out chords…</div>';
 const s=S[i],bpm=s[F.kind]==='loop'?'':(PROJ.bpm||90);
 try{const r=await api(`api/chords?path=${encodeURIComponent(s[F.path])}&bpc=${CH.bpc}${bpm?'&bpm='+bpm:''}`);if(st.sel!==i)return;CH.res=r;CH.pad=CH.pad||r.timbre;if(!CH.bassPicked)CH.bass=bassAuto(r,s);drawChords()}
 catch(e){box.innerHTML='<div class="sub">chords failed: '+esc(e.message)+'</div>'}}
function drawChords(){const r=CH.res,box=$('chordbox');if(!r)return;
 box.innerHTML=`<div class="edrow"><b>🎼 ${esc(r.key)}</b>${hq('chords')}<span class="sub">${esc(r.style)} flavour (${r.moods.map(esc).join(', ')}) · ${r.follows?`follows the sample's own changes: ${r.own.map(esc).join(' → ')}`:`${r.steps} chords × ${r.bars_per_chord} bar at ${r.tempo} bpm${r.loop?'':' (project tempo)'}`}</span></div>
 <div class="edrow sub"><label ${r.follows?'hidden':''}>chord every <select id="chbpc"><option value="1" ${CH.bpc===1?'selected':''}>1 bar</option><option value="2" ${CH.bpc===2?'selected':''}>2 bars</option></select></label>
  <label>pad <select id="chpad">${r.pads.map(p=>`<option ${p===CH.pad?'selected':''}>${p}</option>`).join('')}</select></label>
  <label>pad level <input type="range" id="chlvl" min="0" max="1.5" step="0.05" value="${CH.lvl}" style="width:80px"></label><label>bass <select id="chbass">${Object.entries(BASSES).map(([k,v])=>`<option value="${k}" ${k===CH.bass?'selected':''}>${v}${k===bassAuto(r,S[CH.i])?' ✓':''}</option>`).join('')}</select></label><label ${CH.bass==='off'?'hidden':''} id="chblw">bass level <input type="range" id="chblvl" min="0" max="1.5" step="0.05" value="${CH.blvl}" style="width:70px"></label><button id="chstop">■ stop</button></div>
 ${r.options.map((o,k)=>`<div class="chopt"><button class="play" data-chplay="${k}" title="the sample with this progression">▶</button>${o.label?`<span class="chlab">${esc(o.label)}</span>`:''}
  <div class="chs">${o.chords.map((c,ci)=>`<span class="chd" data-chone="${k}:${ci}" title="fit ${c.fit} · click to hear this chord"><b>${esc(c.name)}</b><i>${esc(c.roman)}</i></span>`).join('')}</div>
  <span class="sub" title="how well the chords' notes match what the sample plays">${Math.round(o.fit*100)}%</span>
  <div class="chbtn"><button data-chmidi="${k}" title="the chords as a MIDI clip, in your Ableton User Library/Chords">⇩ MIDI</button><button data-chsk="${k}" title="render the pad as a new sample and put it in the sketchpad with this sample">＋ sketch</button></div></div>`).join('')||'<div class="sub">no confident suggestions for this one</div>'}
 <div class="kbd" id="chkeys"></div>
 <div class="hint">Click a chord to hear it alone. ${r.follows?"This sample has chords of its own, so suggestions change where it does: “follows” enriches its chords in another register, “reharmonized” swaps in chords that still contain what it plays;":"Chords follow the sample's key and what it plays in each bar;"} the flavour comes from its mood. Voiced ${r.register[0]<55?'below':'above'} the sample's own register so they don't mask it.</div>`;
 chKeys([]);
 $('chbpc').onchange=e=>{CH.bpc=+e.target.value;chStop();openChords(CH.i,true)};$('chpad').onchange=e=>{CH.pad=e.target.value;if(CH.play)chPlay(CH.play.k)};
 $('chlvl').oninput=e=>{CH.lvl=+e.target.value;if(CH.play)CH.play.pg.gain.value=CH.lvl};$('chbass').onchange=e=>{CH.bass=e.target.value;CH.bassPicked=true;$('chblw').hidden=CH.bass==='off';if(CH.play)chPlay(CH.play.k)};$('chblvl').oninput=e=>{CH.blvl=+e.target.value;if(CH.play&&CH.play.bg)CH.play.bg.gain.value=CH.blvl};$('chstop').onclick=chStop}
// a piano keyboard over the register the chords use; lit keys = the chord sounding now (bass in a darker colour)
function chKeys(notes,label){const el=$('chkeys');if(!el||!CH.res)return;const lo=Math.min(36,...notes.map(n=>n-(n%12))),hi=Math.max(84,...notes.map(n=>n+1));
 const blk=n=>[1,3,6,8,10].includes(n%12),wh=[];for(let n=lo;n<=hi;n++)if(!blk(n))wh.push(n);const W=100/wh.length,on=new Set(notes),bass=notes.length?Math.min(...notes):null;
 let h=wh.map((n,k)=>`<i class="w${on.has(n)?(n===bass?' bs':' on'):''}" style="left:${k*W}%;width:${W}%">${n%12===0?`<em>C${n/12-1}</em>`:''}</i>`).join('');
 for(let n=lo;n<=hi;n++)if(blk(n)){const k=wh.filter(x=>x<n).length;h+=`<i class="b${on.has(n)?(n===bass?' bs':' on'):''}" style="left:${k*W-W*0.32}%;width:${W*0.64}%"></i>`}
 el.innerHTML=`<div class="kl">${label?esc(label):'&nbsp;'}</div><div class="kk">${h}</div>`}
function chMark(k,ci){document.querySelectorAll('[data-chone]').forEach(x=>x.classList.toggle('now',x.dataset.chone===`${k}:${ci}`));const c=CH.res&&CH.res.options[k]&&CH.res.options[k].chords[ci];
 const b=c&&CH.bass&&CH.bass!=='off'?bassLine(CH.res,CH.res.options[k],CH.bass).find(x=>Math.abs(x.t-chAt(CH.res,c,ci)[0])<1e-3):null;
 chKeys(c?(b?[b.n,...c.notes]:c.notes):[],c?`${c.name} · ${c.roman}${b?' · bass '+NOTE_NAMES[b.n%12]+(Math.floor(b.n/12)-1):''}`:'')}
const NOTE_NAMES=['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'];
const CHBUF=lruMap(8);
let chPlaySeq=0;
function chStop(){chPlaySeq++;if(!CH.play)return;const p=CH.play;CH.play=null;clearTimeout(p.timer);cancelAnimationFrame(p.raf);chMark(-1,-1);const now=AC.currentTime;p.master.gain.setTargetAtTime(0,now,0.05);setTimeout(()=>{try{p.master.disconnect()}catch(e){}},400);
 try{p.src.stop(now+0.2)}catch(e){}document.querySelectorAll('[data-chplay]').forEach(b=>b.classList.remove('playing'))}
// anything else starting to play (a sample, play-together, a variation, the sketch, the stop button) stops the chords too
const _stopAllChords=stopAll;stopAll=function(){
 clearTimeout(kPreviewT);
 const pending=[...players.values()].filter(a=>a instanceof HTMLAudioElement&&a.readyState<4);
 _stopAllChords.apply(this,arguments);
 pending.forEach(cancelPreview);
 chStop()
};
async function chPlay(k){stopAll();skStop();AC.resume();const seq=chPlaySeq,i=CH.i,r=CH.res,o=r.options[k],path=S[i][F.path];
 if(!CHBUF.has(path))CHBUF.set(path,fetch(url(path)).then(r=>r.arrayBuffer()).then(b=>AC.decodeAudioData(b)));
 const pending=CHBUF.get(path);
 let buf;
 try{buf=await pending}catch(e){if(CHBUF.get(path)===pending)CHBUF.delete(path);return}
 if(seq!==chPlaySeq||st.sel!==i)return;
 const L=chLen(r,o),master=AC.createGain();master.connect(AC.destination);const pg=AC.createGain();pg.gain.value=CH.lvl;const rv=padReverb(AC),wet=AC.createGain();wet.gain.value=0.35;
 pg.connect(master);pg.connect(rv);rv.connect(wet);wet.connect(master);
 const src=AC.createBufferSource();src.buffer=buf;src.loop=true;src.loopEnd=Math.min(buf.duration,L);const sg=AC.createGain();sg.gain.value=Math.min(4,skNorm(buf))*0.8;src.connect(sg);sg.connect(master);
 const bg=AC.createGain();bg.gain.value=CH.blvl;bg.connect(master);
 const t0=AC.currentTime+0.1;src.start(t0);CH.play={k,master,pg,bg,src,timer:null};
 const sched=n=>{if(!CH.play||CH.play.k!==k)return;padProgression(AC,pg,o,r.step,t0+n*L,CH.pad);bassProgression(AC,bg,r,o,t0+n*L,CH.bass);CH.play.timer=setTimeout(()=>sched(n+1),Math.max(50,(t0+(n+1)*L-AC.currentTime-1)*1000))};sched(0);
 let last=-1;const follow=()=>{if(!CH.play||CH.play.k!==k)return;const t=AC.currentTime-t0,tl=t<0?0:t%L;
  let ci=0;o.chords.forEach((c,j)=>{if(chAt(r,c,j)[0]<=tl+1e-6)ci=j});if(ci!==last){last=ci;chMark(k,ci)}CH.play.raf=requestAnimationFrame(follow)};follow();
 document.querySelectorAll('[data-chplay]').forEach(b=>b.classList.toggle('playing',+b.dataset.chplay===k))}
document.addEventListener('click',async e=>{const one=e.target.closest('[data-chone]');if(one){const [k,ci]=one.dataset.chone.split(':').map(Number),r=CH.res,c=r.options[k].chords[ci];
  chStop();stopAll();AC.resume();const pg=AC.createGain();pg.gain.value=CH.lvl;const rv=padReverb(AC),wet=AC.createGain();wet.gain.value=0.35;pg.connect(AC.destination);pg.connect(rv);rv.connect(wet);wet.connect(AC.destination);
  const duration=Math.min(2.5,chAt(r,c,ci)[1]),kind=CH.pad;
  padChord(AC,pg,c.notes,AC.currentTime+0.02,duration,kind);
  setTimeout(()=>{try{pg.disconnect();rv.disconnect();wet.disconnect()}catch(e){}},(duration+(PADV[kind]||PADV.warm).rel+3.5)*1000);
  chMark(k,ci);return}
 const p=e.target.closest('[data-chplay]');if(p){if(CH.play&&CH.play.k===+p.dataset.chplay)chStop();else chPlay(+p.dataset.chplay);return}
 const m=e.target.closest('[data-chmidi]');if(m){const r=CH.res,o=r.options[+m.dataset.chmidi],s=S[CH.i];
  try{await api('api/chords/midi',{name:`${s[F.artist]} - ${s[F.title]} - ${o.chords.map(c=>c.name).join(' ')}`,chords:o.chords.map(c=>c.notes),times:o.chords.map((c,j)=>chAt(r,c,j)),step:r.step,tempo:r.tempo,bass:bassLine(r,o,CH.bass).map(b=>[b.n,b.t,b.d,Math.round(70+40*b.v-30)])});m.textContent='✓ MIDI';toast(CH.bass&&CH.bass!=='off'?'MIDI clip saved (chords + bass tracks) to your Ableton User Library › Chords':'MIDI clip saved to your Ableton User Library › Chords')}catch(err){toast('error: '+err.message)}return}
 const sk=e.target.closest('[data-chsk]');if(sk){const r=CH.res,o=r.options[+sk.dataset.chsk],i=CH.i,s=S[i];sk.textContent='rendering…';
  // render offline, folding the release/reverb tail past the loop end back onto its start so the loop is seamless
  const L=chLen(r,o),render=async(build,verb)=>{const sr=44100,ctx=new OfflineAudioContext(2,Math.ceil((L+3)*sr),sr),g=ctx.createGain();g.connect(ctx.destination);
   if(verb){const rv=padReverb(ctx),wet=ctx.createGain();wet.gain.value=0.35;g.connect(rv);rv.connect(wet);wet.connect(ctx.destination)}build(ctx,g);
   const full=await ctx.startRendering(),n=Math.round(L*sr),out=new AudioBuffer({numberOfChannels:2,length:n,sampleRate:sr});
   for(let c=0;c<2;c++){const a=full.getChannelData(c),b=out.getChannelData(c);b.set(a.subarray(0,n));for(let k=n;k<a.length;k++)b[(k-n)%n]+=a[k]}return out};
  // stored as new loops (key + tempo + provenance): the pad in Chords & Keys, the bass in Bass & Sub; then all lanes go in the sketch
  const meta={parent:s[F.path],kind:r.follows?'free':'loop',bpm:r.follows?null:r.tempo,bars:r.follows?null:o.chords.length*r.bars_per_chord,key:r.key},names=o.chords.map(c=>c.name);
  try{const pad=await render((ctx,g)=>padProgression(ctx,g,o,r.step,0,CH.pad),true);
   const res=await api('api/bounce',{...meta,wav:await wavB64(pad),prefix:'Chords',category:'Chords & Keys',name:names.join(' '),tag:`chords ${CH.pad}`,ops:{chords:names,pad:CH.pad,from:s[F.id]}});
   const j=addRow(i,res.row);if(!SK.lanes.some(l=>l.path===s[F.path]))await skAdd(i);await skAdd(j);
   if(CH.bass&&CH.bass!=='off'){const bs=await render((ctx,g)=>bassProgression(ctx,g,r,o,0,CH.bass),false);
    const rb=await api('api/bounce',{...meta,wav:await wavB64(bs),prefix:'Bass',category:'Bass & Sub',name:'bass '+names.join(' '),tag:`bass ${CH.bass}`,ops:{chords:names,bass:CH.bass,from:s[F.id]}});
    await skAdd(addRow(i,rb.row))}
   sk.textContent='✓ in sketch';toast(CH.bass&&CH.bass!=='off'?'chord pad and bassline saved (★) and added to the sketchpad with the sample':'chord pad saved (★) and added to the sketchpad with the sample')}
  catch(err){sk.textContent='＋ sketch';toast('error: '+err.message)}}});
async function openMidi(i){const box=$('midibox');if(!box.hidden){box.hidden=true;return}box.hidden=false;box.innerHTML='<div class="sub">transcribing notes & chords (basic-pitch)…</div>';
 try{const s=S[i],r=await api(`api/midi?path=${encodeURIComponent(s[F.path])}${s[F.kind]==='loop'&&s[F.bpm]?'&bpm='+s[F.bpm]:''}`);if(st.sel!==i)return;
  const name=s[F.path].split('/').pop().replace(/\.wav$/,'')+'.mid';
  box.innerHTML=`<div class="edrow"><b>♪ ${r.notes.length} notes</b><span class="sub">${r.chords.length?r.chords.length+' chords (below)':'no clear chords'}</span><a href="${url(r.midi)}" download="${esc(name)}"><button>⇩ .mid</button></a><span class="sub">drag the downloaded file into a MIDI track</span></div>
  <canvas class="roll" id="roll"></canvas><div>${r.chords.map(c=>`<span class="chord" title="${c[0].toFixed(1)}–${c[1].toFixed(1)} s">${esc(c[2])}</span>`).join('')}</div>`;
  drawRoll($('roll'),r)}catch(e){box.innerHTML='<div class="sub">MIDI failed: '+esc(e.message)+'</div>'}}
function drawRoll(c,r){const dpr=devicePixelRatio||1,W=c.clientWidth*dpr,H=150*dpr;c.width=W;c.height=H;const g=c.getContext('2d');g.fillStyle='#101317';g.fillRect(0,0,W,H);
 if(!r.notes.length)return;const lo=Math.min(...r.notes.map(n=>n[2]))-2,hi=Math.max(...r.notes.map(n=>n[2]))+2,rh=H/(hi-lo+1),X=t=>t/r.dur*W;
 for(let p=lo;p<=hi;p++){if([1,3,6,8,10].includes(p%12)){g.fillStyle='rgba(255,255,255,.03)';g.fillRect(0,H-(p-lo+1)*rh,W,rh)}if(p%12===0){g.fillStyle='rgba(255,255,255,.25)';g.font=`${9*dpr}px sans-serif`;g.fillText('C'+(p/12-1),2,H-(p-lo)*rh-2)}}
 r.notes.forEach(([s,e,p,v])=>{g.fillStyle=`rgba(224,164,88,${0.35+v/127*0.65})`;g.fillRect(X(s),H-(p-lo+1)*rh+1,Math.max(2,X(e)-X(s)),Math.max(2,rh-2))})}

// ---------- vocal tuning in the editor
const _openEditor=openEditor;
openEditor=async function(i){await _openEditor(i);const box=$('editor');if(!box||box.hidden||!$('edprev')||$('edtune'))return;
 const row=$('edprev').closest('.edrow'),d=document.createElement('div');d.className='edgrid';d.id='edtune';const own=S[i][F.key];
 d.innerHTML=`<span>Tune to${hq('tune')}</span><select id="tnkey"><option value="">off</option>${PROJ.key?`<option value="${esc(PROJ.key)}">project · ${esc(PROJ.key)}</option>`:''}${own?`<option value="${esc(own)}">its own key · ${esc(own)}</option>`:''}${KEYS24.map(([c,n])=>`<option value="${n}">${c} ${n}</option>`).join('')}</select><span id="tnrep" class="sub"></span>
 <span>Strength</span><input type="range" id="tnstr" min="0" max="1" step="0.05" value="0.8"><span id="tnstrv">80%</span>
 <span>Glide</span><input type="range" id="tnspd" min="0" max="300" step="5" value="60"><span id="tnspdv">60 ms</span>
 <span>Detune</span><input type="range" id="tndet" min="-50" max="50" step="1" value="0"><span id="tndetv">0 ¢</span>
 <span>Drift</span><input type="range" id="tndri" min="0" max="40" step="1" value="0"><span id="tndriv">0 ¢</span>`;
 row.parentNode.insertBefore(d,row);
 const lab={tnstr:v=>Math.round(v*100)+'%',tnspd:v=>v+' ms'+(v<15?' (hard: audible on every engine)':v>150?' (natural)':''),tndet:v=>(v>0?'+':'')+v+' ¢',tndri:v=>v+' ¢'};
 Object.entries(lab).forEach(([id,f])=>{$(id).addEventListener('input',()=>$(id+'v').textContent=f(+$(id).value));$(id).addEventListener('change',()=>edChanged())});
 $('tnkey').addEventListener('change',async()=>{edChanged();const k=$('tnkey').value;$('tnrep').textContent='';if(!k)return;$('tnrep').textContent='measuring…';
  try{const r=await api(`api/tune/report?path=${encodeURIComponent(S[i][F.path])}&key=${encodeURIComponent(k)}`);
   $('tnrep').textContent=r.voiced?`${Math.round(r.in_key*100)}% of its notes are in ${k} · sits ${r.cents>0?'+':''}${r.cents}¢ · wobble ±${r.spread}¢`:'no clear pitch found'}catch(e){$('tnrep').textContent=''}})};
const _edParams=edParams;
edParams=function(){const p=_edParams();if($('tnkey')){p.tune_key=$('tnkey').value||null;p.tune_strength=+$('tnstr').value;p.tune_speed=+$('tnspd').value;p.tune_detune=+$('tndet').value;p.tune_drift=+$('tndri').value}return p};

// ---------- your plugins (AU/VST3 via Pedalboard) in the editor
let FXLIST=null;
const _openEditorFx=openEditor;
openEditor=async function(i){await _openEditorFx(i);const box=$('editor');if(!box||box.hidden||!$('edprev')||$('edfx')||!SERVED)return;
 if(!FXLIST){try{FXLIST=await api('api/plugins')}catch(e){FXLIST=[]}}if(!FXLIST.length||$('edfx'))return;
 const row=$('edprev').closest('.edrow'),d=document.createElement('div');d.className='edgrid';d.id='edfx';
 d.innerHTML=`<span>Plugin</span><select id="fxp"><option value="">none</option>${FXLIST.map(x=>`<option value="${esc(x.path)}">${esc(x.name)} (${x.format})</option>`).join('')}</select><span id="fxmsg" class="sub">your own effects</span>
 <span class="fxt" hidden>Tail</span><input class="fxt" hidden type="range" id="fxtail" min="0" max="12" step="0.5" value="4"><span class="fxt" hidden id="fxtailv">4 s to ring out</span><div id="fxctl" style="grid-column:1/-1;display:grid;grid-template-columns:auto 1fr auto;gap:4px 8px;align-items:center"></div>`;
 row.parentNode.insertBefore(d,row);
 $('fxtail').addEventListener('input',()=>$('fxtailv').textContent=$('fxtail').value+' s to ring out');$('fxtail').addEventListener('change',()=>edChanged());
 $('fxp').addEventListener('change',async()=>{const path=$('fxp').value,c=$('fxctl');c.innerHTML='';document.querySelectorAll('.fxt').forEach(e=>e.hidden=!path);if(!path){edChanged();return}
  $('fxmsg').textContent='loading…';let ps=[];try{ps=await api('api/plugins/params?path='+encodeURIComponent(path))}catch(e){$('fxmsg').textContent='couldn\'t load: '+e.message;return}
  if(ps.error){$('fxmsg').textContent=ps.error;return}$('fxmsg').textContent=ps.length+' controls';
  c.innerHTML=ps.slice(0,16).map(p=>p.kind==='choice'?`<span>${esc(p.name)}</span><select data-fx="${esc(p.key)}">${p.choices.map(o=>`<option ${o===p.value?'selected':''}>${esc(o)}</option>`).join('')}</select><span></span>`
   :p.kind==='bool'?`<span>${esc(p.name)}</span><input type="checkbox" data-fx="${esc(p.key)}" ${p.value?'checked':''}><span></span>`
   :`<span>${esc(p.name)}</span><input type="range" data-fx="${esc(p.key)}" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.value}"><span data-fxv="${esc(p.key)}">${+(+p.value).toFixed(2)} ${esc(p.label||'')}</span>`).join('');
  c.querySelectorAll('[data-fx]').forEach(el=>{el.addEventListener('change',()=>el.dataset.touched=1);el.addEventListener('input',()=>{el.dataset.touched=1;const v=c.querySelector(`[data-fxv="${el.dataset.fx}"]`);if(v)v.textContent=(+(+el.value).toFixed(2))+' '+(v.textContent.split(' ').slice(1).join(' '))});el.addEventListener('change',()=>edChanged())});
  edChanged()})};
const _edParamsFx=edParams;
edParams=function(){const p=_edParamsFx();if($('fxp')&&$('fxp').value){const pr={};$('fxctl').querySelectorAll('[data-fx][data-touched]').forEach(el=>{pr[el.dataset.fx]=el.type==='checkbox'?el.checked:el.tagName==='SELECT'?el.value:+el.value});
 p.plugins=[{path:$('fxp').value,params:pr}];p.tail=+$('fxtail').value}return p};

// ---------- ✨ edit suggestions, judged by your taste model (suggest.py)
let SG=null;
const _openEditorSg=openEditor;
openEditor=async function(i){await _openEditorSg(i);const box=$('editor');if(!box||box.hidden||!$('edprev')||$('edsg')||!SERVED)return;
 const row=$('edprev').closest('.edrow'),d=document.createElement('div');d.id='edsg';d.style.margin='6px 0';
 d.innerHTML=`<div class="edrow"><button id="sgbtn" title="try a dozen edits that suit this kind of sound and let your taste model pick">✨ suggest edits</button>${hq('suggest')}<span class="sub" id="sgmsg"></span></div><div id="sglist"></div>`;
 row.parentNode.insertBefore(d,row);$('sgbtn').onclick=()=>sgRun(i);
 // start working on them now, in the background, so ✨ answers at once
 for(let t=0;t<40&&!(ED&&ED.sel);t++)await new Promise(r=>setTimeout(r,100));if(ED&&ED.sel&&$('edsg'))api('api/suggest/prefetch',sgBody(i)).catch(()=>{})};
const sgBody=i=>({path:S[i][F.path],project_key:PROJ.key||'',start:ED&&ED.sel?ED.sel[0]:0,end:ED&&ED.sel?ED.sel[1]:null});
const SGREASONS=['too much','too subtle','sounds processed','wrong mood'];
const sgRate=(body)=>api('api/suggest/rate',body).catch(()=>{});
const sgFb=(x,action)=>SG&&api('api/suggest/feedback',{path:S[SG.i][F.path],id:S[SG.i][F.id],move:x.id,family:x.family,arm:x.arm,material:x.material,action}).catch(()=>{});
async function sgRun(i){const s=S[i];$('sgbtn').disabled=true;$('sglist').innerHTML='';$('sgmsg').textContent='trying a dozen edits on the selection… (a few seconds)';
 let r;try{r=await api('api/suggest',sgBody(i))}
 catch(e){$('sgbtn').disabled=false;$('sgmsg').textContent="couldn't: "+e.message;return}
 $('sgbtn').disabled=false;if(r.error){$('sgmsg').textContent=r.error;return}
 SG={i,r,run:Date.now()};const up=r.suggestions.filter(x=>x.arm==='critic'&&x.delta>0).length;
 $('sgmsg').textContent=`tried ${r.tried} · `+(up?`${up} it thinks you'd like more than the original`:'it rates the original highest, so these are the ones it minds least');
 $('sglist').innerHTML=r.suggestions.map((x,k)=>`<div class="prow" data-sgk="${k}"><button class="play" data-sgplay="${k}">▶</button><div style="min-width:0">
  <div class="name">${x.arm==='wildcard'?'<span class="badge" style="background:#5b6370" title="picked at random from the rest, to check the model">wildcard</span> ':''}${esc(x.label)}</div>
  <div class="meta">${x.delta>=0?'+':''}${x.delta.toFixed(2)} taste · ${Math.round(x.close*100)}% like the original</div></div>
  <div style="display:flex;gap:6px"><button data-sgup="${k}" title="I like this edit">👍</button><button data-sgdown="${k}" title="I don't like this edit">👎</button><button data-sguse="${k}" title="set the editor to this edit, then adjust anything">use</button></div>
  <div class="sgwhy" data-sgwhy="${k}" hidden style="grid-column:1/-1">${SGREASONS.map(w=>`<button data-sgreason="${k}" data-r="${w}">${w}</button>`).join(' ')}<span class="sub"> why? (optional)</span></div></div>`).join('');
 const L=r.learning||{};$('sgmsg').textContent+=L.ratings?` · learning from ${L.ratings} rating${L.ratings>1?'s':''}`+(L.model_on?(L.model_auc!=null?` (its edit model predicts your 👍/👎 ${Math.round(L.model_auc*100)}% of the time)`:' (edit model on)'):''):' · rate them 👍/👎 to teach it'}
async function sgApply(x){const p=x.params,set=(id,v)=>{const el=$(id);if(!el)return;if(el.type==='checkbox')el.checked=!!v;else el.value=v;el.dispatchEvent(new Event('input'))};
 set('edst',p.stretch||1);set('edpi',p.semis||0);set('edfm',false);set('edtape',!!p.tape||(!!$('eddrum')&&!p.semis));
 if($('eddrum')){set('edpunch',Math.round((p.punch||0)*100));set('eddecay',decayVal(p.decay||0));set('eddrive',Math.round((p.drive||0)*100));set('edlow',p.lowcut||0)}set('edrev',!!p.reverse);set('edtone',toneVal(p.tone||20000));
 if($('tnkey')){const k=p.tune_key||'';if(k&&![...$('tnkey').options].some(o=>o.value===k))$('tnkey').insertAdjacentHTML('beforeend',`<option value="${esc(k)}">${esc(k)}</option>`);
  $('tnkey').value=k;set('tnstr',p.tune_strength??0.8);set('tnspd',p.tune_speed??60);set('tndet',0);set('tndri',0)}
 if($('fxp')){const pl=(p.plugins||[])[0];if(($('fxp').value||'')!==(pl?pl.path:'')){$('fxp').value=pl?pl.path:'';$('fxp').dispatchEvent(new Event('change'))}
  if(pl){for(let t=0;t<50&&!$('fxctl').querySelector('[data-fx]');t++)await new Promise(r=>setTimeout(r,100));
   Object.entries(pl.params||{}).forEach(([k,v])=>{const el=$('fxctl').querySelector(`[data-fx="${CSS.escape(k)}"]`);if(!el)return;if(el.type==='checkbox')el.checked=!!v;else el.value=v;el.dataset.touched=1;el.dispatchEvent(new Event('input'))});
   if(p.tail!=null){$('fxtail').value=p.tail;$('fxtail').dispatchEvent(new Event('input'))}}}
 ED.sugg=x;edChanged();$('edmsg').textContent=`set to “${x.label}” · adjust anything, then ▶ preview edit or save as new`}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-sgplay],[data-sguse],[data-sgno],[data-sgup],[data-sgdown],[data-sgreason]');if(!b||!SG)return;e.stopPropagation();
 const k=+(b.dataset.sgplay??b.dataset.sguse??b.dataset.sgno??b.dataset.sgup??b.dataset.sgdown??b.dataset.sgreason),x=SG.r.suggestions[k];
 const base={path:S[SG.i][F.path],move:x.id,family:x.family,material:x.material,arm:x.arm,params:x.params,source:'suggestion'};
 if(b.dataset.sgup!=null||b.dataset.sgdown!=null){const up=b.dataset.sgup!=null,row=b.closest('[data-sgk]');
  row.querySelector('[data-sgup]').classList.toggle('on',up);row.querySelector('[data-sgdown]').classList.toggle('on',!up);
  row.querySelector('[data-sgwhy]').hidden=up;sgRate({...base,rating:up?1:-1});return}
 if(b.dataset.sgreason!=null){b.parentNode.querySelectorAll('[data-sgreason]').forEach(z=>z.classList.toggle('on',z===b));sgRate({...base,rating:-1,reason:b.dataset.r});return}
 if(b.dataset.sgplay!=null){const key=`sg${SG.run}_${k}`,was=players.has(key);stopAll();if(was)return;  // ids per set of suggestions: slots repeat across samples
  const a=new Audio(x.url);a.loop=true;a.play().catch(()=>{});players.set(key,a);b.classList.add('playing');
  NP={path:S[SG.i][F.path],id:S[SG.i][F.id],label:`✨ edit: ${x.label} — ${lbl(SG.i)}`,i:SG.i,edit:true};drawNP();sgFb(x,'play');return}
 if(b.dataset.sguse!=null){stopAll();await sgApply(x);sgFb(x,'apply');document.querySelectorAll('[data-sgk]').forEach(r=>r.style.background=+r.dataset.sgk===k?'#1f2630':'');return}
 sgFb(x,'dismiss');b.closest('[data-sgk]').remove()},true);
// rate your own edit (whatever the editor is set to): the same ratings teach the suggestions
const _openEditorRate=openEditor;
openEditor=async function(i){await _openEditorRate(i);const box=$('editor');if(!box||box.hidden||!$('edprev')||$('edrate')||!SERVED)return;
 const d=document.createElement('div');d.id='edrate';d.className='edrow sub';
 d.innerHTML=`<span>rate this edit:</span><button id="edup" title="I like this edit">👍</button><button id="eddown" title="I don't like this edit">👎</button><span id="edwhy" hidden>${SGREASONS.map(w=>`<button data-edr="${w}">${w}</button>`).join(' ')}</span><span id="edrmsg"></span>`;
 $('edprev').closest('.edrow').after(d);
 const send=async(rating,reason)=>{$('edrmsg').textContent='listening…';const p=edParams();
  try{await api('api/suggest/rate',{path:S[i][F.path],rating,reason:reason||null,params:p,move:ED.sugg&&!edMoved(p,ED.sugg.params)?ED.sugg.id:null,
   family:ED.sugg&&!edMoved(p,ED.sugg.params)?ED.sugg.family:null,arm:ED.sugg&&!edMoved(p,ED.sugg.params)?ED.sugg.arm:null,source:'editor'});
   $('edrmsg').textContent=reason?' noted: '+reason:' noted: it learns from this'}catch(err){$('edrmsg').textContent=' couldn\'t save the rating'}};
 $('edup').onclick=()=>{$('edup').classList.add('on');$('eddown').classList.remove('on');$('edwhy').hidden=true;send(1)};
 $('eddown').onclick=()=>{$('eddown').classList.add('on');$('edup').classList.remove('on');$('edwhy').hidden=false;send(-1)};
 $('edwhy').onclick=e=>{const r=e.target.dataset.edr;if(!r)return;$('edwhy').querySelectorAll('button').forEach(z=>z.classList.toggle('on',z===e.target));send(-1,r)}};
// has the edit been changed since a suggestion set it? (then it's your edit, not the suggestion)
const edNz=(k,v)=>{if(v==null||v===false||v==='')v={stretch:1,semis:0,tone:20000}[k]??'';return v===true?'on':typeof v==='number'?Math.round(v*100)/100:String(v)};
const edMoved=(p,q)=>['stretch','semis','tape','reverse','tune_key'].some(k=>edNz(k,p[k])!==edNz(k,q[k]))||Math.abs(Math.log((p.tone||20000)/(q.tone||20000)))>0.05;
const _edSaveSg=edSave;
edSave=async function(...a){const x=ED&&ED.sugg;const r=await _edSaveSg.apply(this,a);if(x)sgFb(x,'save');return r};

// ---------- chop pads
const PADKEYS='1234qwerasdfzxcv'.split('');
const PADS={i:null,buf:null,sl:[],voice:null,events:[],rec:false,loop:null,start:0,len:0,timer:null,clickG:null};
function padsClose(){padsStopLoop();PADS.i=null;const b=$('pads');if(b)b.hidden=true}
function mergeSlices(b,n,minLen){let s=[];for(let k=0;k<b.length-1;k++)if(b[k+1]>b[k])s.push([b[k],b[k+1]]);
 while(s.length>1&&(s.length>n||s.some(x=>x[1]-x[0]<minLen))){let k=0;s.forEach((x,j)=>{if(x[1]-x[0]<s[k][1]-s[k][0])k=j});
  const j=k===s.length-1?k-1:k===0?1:((s[k-1][1]-s[k-1][0])<(s[k+1][1]-s[k+1][0])?k-1:k+1);const a=Math.min(j,k),c=Math.max(j,k);s.splice(a,2,[s[a][0],s[c][1]])}return s}
const padBpm=()=>PROJ.bpm||(PADS.i!=null&&S[PADS.i][F.bpm])||120;
async function openPads(i){const box=$('pads');if(!box.hidden&&PADS.i===i){padsClose();return}box.hidden=false;PADS.i=i;padsStopLoop();PADS.events=[];
 box.innerHTML='<div class="sub">slicing at syllables / notes…</div>';
 try{const path=S[i][F.path],conf=PROJ.on&&(PROJ.key||PROJ.bpm);const res=await fetch(conf?conformURL(path,PROJ.key,PROJ.bpm):url(path));
  const info=JSON.parse(res.headers.get('X-Conform')||'{}'),tr=+(info.length||info.time||1);PADS.buf=await AC.decodeAudioData(await res.arrayBuffer());
  const on=await api('api/onsets?path='+encodeURIComponent(path));if(st.sel!==i)return;
  PADS.sl=mergeSlices([0,...on.onsets.map(t=>t*tr),PADS.buf.duration],16,0.08)}catch(e){box.innerHTML='<div class="sub">pads failed: '+esc(e.message)+'</div>';return}
 const env=([a,b])=>{const d=PADS.buf.getChannelData(0),sr=PADS.buf.sampleRate,i0=Math.floor(a*sr),i1=Math.floor(b*sr),n=24,st2=Math.max(1,Math.floor((i1-i0)/n)),v=[];
  for(let k=0;k<n;k++){let m=0;for(let j=i0+k*st2;j<Math.min(i1,i0+(k+1)*st2);j+=4)m=Math.max(m,Math.abs(d[j]));v.push(m)}const mx=Math.max(...v,1e-6);return v.map(x=>Math.round(x/mx*99))};
 box.innerHTML=`<div class="edrow"><b>🎹 pads</b>${hq('pads')}<span class="sub">keys 1–4 · Q–R · A–F · Z–V (or click) · ${PADS.sl.length} slices${PROJ.on&&(PROJ.key||PROJ.bpm)?' · in the project key/tempo':''}</span></div>
 <div class="sub" style="margin:-2px 0 4px">your sample cut into syllables or notes: tap keys to replay them in a new rhythm, record a pattern, or save the slices as a Drum Rack</div>
 <div class="grid16">${PADS.sl.map((sl,k)=>`<div class="pad" data-pad="${k}"><b>${PADKEYS[k].toUpperCase()}</b>${wave(env(sl),110,16,'#7d8592')}<span>${sl[0].toFixed(2)}s · ${(sl[1]-sl[0]).toFixed(2)}</span></div>`).join('')}</div>
 <div class="edrow sub"><label><input type="checkbox" id="pdmono" checked> one voice at a time (choke)</label>
 quantise <select id="pdq"><option value="0">off</option><option value="2">1/8</option><option value="4" selected>1/16</option><option value="8">1/32</option></select>
 <select id="pdbars"><option value="1">1 bar</option><option value="2" selected>2 bars</option><option value="4">4 bars</option></select> at ${padBpm()} bpm</div>
 <div class="edrow"><button id="pdrec">● record</button><button id="pdplay">▶ pattern</button><button id="pdclr">clear</button><span class="sub" id="pdmsg">record loops the bar(s) with a click; play pads to overdub</span></div>
 <div class="edrow"><input id="pdname" placeholder="name (optional)" style="flex:1;min-width:110px"><button id="pdsave" class="pill">save pattern as new sample</button><button id="pdrack" title="every slice as its own pad in an Ableton Drum Rack">⇩ chops → Drum Rack</button></div>`;
 box.querySelectorAll('[data-pad]').forEach(p=>p.onmousedown=e=>{e.preventDefault();padHit(+p.dataset.pad)});
 $('pdrec').onclick=()=>{if(PADS.rec){PADS.rec=false;$('pdrec').textContent='● record';$('pdmsg').textContent=`${PADS.events.length} hits — looping`;return}padsStartLoop(true)};
 $('pdplay').onclick=()=>{if(PADS.loop){padsStopLoop();return}if(!PADS.events.length){toast('record a pattern first');return}padsStartLoop(false)};
 $('pdclr').onclick=()=>{PADS.events=[];$('pdmsg').textContent='cleared'};
 $('pdsave').onclick=padsSave;
 $('pdrack').onclick=async()=>{$('pdrack').textContent='building…';try{const r=await api('api/export',{scope:'paths',paths:[S[i][F.path]],name:xpName(),chop:true,reveal:true});$('pdrack').textContent='rack ✓';toast(`Drum Rack of chops → ${xpName()}`)}catch(e){$('pdrack').textContent='error'}}}
function padVoice(ctx,dest,k,t){const[a,b]=PADS.sl[k],s=ctx.createBufferSource();s.buffer=PADS.buf;const g=ctx.createGain();s.connect(g);g.connect(dest);const d=b-a,f=Math.min(0.004,d/4);
 g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(1,t+f);g.gain.setValueAtTime(1,t+d-f);g.gain.linearRampToValueAtTime(0,t+d);s.start(t,a,d);return{s,g}}
function padHit(k){if(PADS.i==null||!PADS.sl[k])return;AC.resume();const now=AC.currentTime;let t=now;
 if(PADS.loop){const pos=(now-PADS.start)%PADS.len,q=+$('pdq').value,step=q?60/padBpm()/q:0;let qp=step?Math.round(pos/step)*step:pos;qp=qp%PADS.len;
  if(PADS.rec)PADS.events.push([qp,k]);}
 if($('pdmono')&&$('pdmono').checked&&PADS.voice){try{PADS.voice.g.gain.cancelScheduledValues(t);PADS.voice.g.gain.setTargetAtTime(0,t,0.006);PADS.voice.s.stop(t+0.05)}catch(e){}}
 PADS.voice=padVoice(AC,AC.destination,k,t);const el=document.querySelector(`[data-pad="${k}"]`);if(el){el.classList.add('hit');setTimeout(()=>el.classList.remove('hit'),120)}}
function padsStartLoop(rec){padsStopLoop();AC.resume();PADS.len=+$('pdbars').value*240/padBpm();PADS.start=AC.currentTime+0.1;PADS.rec=rec;PADS.loop={next:0,voices:[]};
 if(rec){$('pdrec').textContent='■ stop recording';$('pdmsg').textContent='recording — play the pads'}$('pdplay').textContent='■ stop';padsTick()}
function padsTick(){const Lp=PADS.loop;if(!Lp)return;const beat=60/padBpm();
 while(PADS.start+Lp.next*PADS.len<AC.currentTime+0.4){const t0=PADS.start+Lp.next*PADS.len;
  PADS.events.forEach(([p,k])=>{const t=t0+p;if(t>AC.currentTime+0.005){
   const v=padVoice(AC,AC.destination,k,t);
   Lp.voices.push(v);
   v.s.onended=()=>{const k=Lp.voices.indexOf(v);if(k>=0)Lp.voices.splice(k,1)}
  }});
  if(PADS.rec)for(let b=0;b<PADS.len/beat-1e-6;b++){const o=AC.createOscillator(),g=AC.createGain();o.frequency.value=b%4?1000:1600;o.connect(g);g.connect(AC.destination);const t=t0+b*beat;g.gain.setValueAtTime(0.12,t);g.gain.exponentialRampToValueAtTime(0.0001,t+0.04);o.start(t);o.stop(t+0.05)}
  Lp.next++}PADS.timer=setTimeout(padsTick,80)}
function padsStopLoop(){clearTimeout(PADS.timer);if(PADS.loop){PADS.loop.voices.forEach(v=>{try{v.s.stop()}catch(e){}})}PADS.loop=null;PADS.rec=false;if($('pdrec')){$('pdrec').textContent='● record';$('pdplay').textContent='▶ pattern'}}
async function padsSave(){if(!PADS.events.length){toast('record a pattern first');return}const bars=+$('pdbars').value,len=bars*240/padBpm(),sr=44100;
 const ctx=new OfflineAudioContext(2,Math.ceil(len*sr),sr),mono=$('pdmono').checked,ev=PADS.events.slice().sort((a,b)=>a[0]-b[0]);
 ev.forEach(([p,k],j)=>{const v=padVoice(ctx,ctx.destination,k,p);if(mono&&ev[j+1]){const t=ev[j+1][0];if(t<p+PADS.sl[k][1]-PADS.sl[k][0]){v.g.gain.cancelScheduledValues(t);v.g.gain.setValueAtTime(1,Math.max(p,t-0.006));v.g.gain.linearRampToValueAtTime(0,t);}}});
 $('pdmsg').textContent='rendering…';const buf=await ctx.startRendering();const i=PADS.i;
 try{const conf=PROJ.on&&PROJ.key;const r=await api('api/bounce',{parent:S[i][F.path],wav:await wavB64(buf),kind:'loop',bpm:padBpm(),bars,key:conf?PROJ.key:'',prefix:'Pads',name:$('pdname').value.trim(),
  tag:`pads ${ev.length} hits`,ops:{pattern:ev,slices:PADS.sl,bpm:padBpm(),conformed:!!conf}});padsStopLoop();const j=addRow(i,r.row);toast('pattern saved as a new sample (★)');select(j,'go')}
 catch(e){$('pdmsg').textContent='save failed: '+e.message}}
window.addEventListener('keydown',e=>{if(PADS.i==null||$('pads').hidden||e.metaKey||e.ctrlKey||e.altKey)return;if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
 const k=PADKEYS.indexOf(e.key.toLowerCase());if(k<0||k>=PADS.sl.length)return;e.preventDefault();e.stopImmediatePropagation();if(!e.repeat)padHit(k)},true);

// ================= export dialog: racks, conform, MIDI =================
$('expbtn').onclick=()=>{if(!SERVED){toast('needs the local server');return}
 const scope=st.tab==='F'?'favorites':'list',ids=st.tab==='F'?[...FAV.keys()]:filtered().slice(0,500).map(i=>S[i][F.path]);
 modal(`<h2 style="margin:0">Export to Ableton</h2><div class="sub">${ids.length} ${scope==='favorites'?'favourites':'samples from the current list'}${scope!=='favorites'&&filtered().length>500?' (first 500)':''} → <code>User Library/Samples/DigitalCrate/&lt;name&gt;/&lt;category&gt;/&lt;subtype&gt;/</code> with an _info.csv.</div>
 <input id="expName" placeholder="export name (e.g. Night session)" style="width:100%">
 <label class="sub"><input type="checkbox" id="expRack"> also build an Ableton <b>Drum Rack</b> (.adg) with every sample on a pad (first 128)</label>
 <label class="sub"><input type="checkbox" id="expConf" ${PROJ.key||PROJ.bpm?'':'disabled'}> conform copies to the project (${esc(PROJ.key||'no key')} · ${PROJ.bpm||'no tempo'})</label>
 <label class="sub"><input type="checkbox" id="expMidi"> add a .mid of the notes next to each tonal sample (slower)</label>
 <div class="edrow"><button id="expGo" class="pill">export</button><button data-close>close</button></div><div id="expMsg" class="sub"></div>`);
 $('expGo').onclick=async()=>{$('expMsg').textContent='copying…';const conf=$('expConf').checked;
  const body=Object.assign(scope==='favorites'?{scope}:{scope:'paths',paths:ids},{name:$('expName').value,rack:$('expRack').checked,midi:$('expMidi').checked,key:conf?PROJ.key:'',bpm:conf?PROJ.bpm:''});
  try{const r=await api('api/export',body);$('expMsg').textContent=`exported ${r.count} files${r.extra&&r.extra.length?` + ${r.extra.length} extras (racks / MIDI)`:''} to ${r.dest} (opened in Finder)`}catch(e){$('expMsg').textContent='error: '+e.message}}};

// ================= stop everything =================
$('stop').onclick=()=>{stopAll();skStop();padsStopLoop()};

window.CRATE={api,conformURL,barLen,takeIdx,laneSolo,setTab,skAdd,skStop,drawSK,openPads,openMidi,PROJ,skBar,barLen,drumAdd,sliceLoop,skSnap,LOOPS,laneHold,drumTake,perf:PERF,skPlay,skLoad,setProj,wavBytes,wavB64,lruMap,padReverb};  // hooks for tools/screenshots.py and the console
drawProj();if(PROJ.link)linkPoll();render();
})();

// ================= MIDI controller (Web MIDI: Chrome, Edge, Firefox — Safari doesn't support it) =================
// Any controller works: open 🎹, press "learn" next to an action, then the pad, key or button you want for it.
// Pads/keys also play the chop pads when those are open (the first learned "pad 1" note and the 15 above it).
const MIDI_NOTES=['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'];
const MIDI_ACTIONS=[['play','play / stop the selected sample'],['next','next sample (and play it)'],['prev','previous sample (and play it)'],
 ['star','★ favourite'],['nope','✕ not for me (and go to the next)'],['pad1','chop pad 1 (pads 2–16 follow on the next notes)']];
const MIDI={map:(()=>{try{return JSON.parse(localStorage.getItem('midiMap')||'null')}catch(e){return null}})()||{play:'n:36',next:'n:37',prev:'n:38',star:'n:39',nope:'n:40',pad1:'n:44'},
 learn:null,inputs:[],status:'',last:''};
function midiSave(){try{localStorage.setItem('midiMap',JSON.stringify(MIDI.map))}catch(e){}}
function midiRows(){return [...document.querySelectorAll('#list .row')]}
function midiStep(d){const rows=midiRows();if(!rows.length)return;let k=rows.findIndex(r=>r.classList.contains('sel'));k=k<0?0:Math.max(0,Math.min(rows.length-1,k+d));
 const i=+rows[k].dataset.i;select(i,'list');rows[k].scrollIntoView({block:'nearest'});stopAll();const b=rows[k].querySelector('[data-play]');if(b)b.click()}
function midiDo(a,k){const i=st.sel;
 if(a==='next')return midiStep(1);if(a==='prev')return midiStep(-1);
 if(a==='play'){if(players.size){stopAll();return}if(i==null){midiStep(0);return}const b=document.querySelector(`#list .row[data-i="${i}"] [data-play]`)||document.querySelector(`[data-play="${i}"]`);if(b)b.click();return}
 if(i==null)return;const s=S[i];
 if(a==='star'){const on=!FAV.has(s[F.path]);toggleFav(s[F.path],s[F.id],lbl(i));toast(on?'★ favourite':'☆ removed');return}
 if(a==='nope'){toggleDislike(s[F.path],s[F.id]);midiStep(1);return}
 if(a==='pad'&&typeof padHit==='function'&&PADS.i!=null&&!$('pads').hidden)padHit(k)}
function midiMsg(e){const [st0,d1,d2]=e.data,type=st0&0xf0;let id=null;
 if(type===0x90&&d2>0)id='n:'+d1;else if(type===0xB0&&d2>=64)id='cc:'+d1;if(!id)return;MIDI.last=id;
 if(MIDI.learn){MIDI.map[MIDI.learn]=id;Object.keys(MIDI.map).forEach(k=>{if(k!==MIDI.learn&&MIDI.map[k]===id)delete MIDI.map[k]});MIDI.learn=null;midiSave();midiPanel();return}
 const a=Object.keys(MIDI.map).find(k=>MIDI.map[k]===id&&k!=='pad1');if(a){midiDo(a);return}
 const p=MIDI.map.pad1;if(p&&p[0]==='n'&&id[0]==='n'){const k=+id.slice(2)-+p.slice(2);if(k>=0&&k<16)midiDo('pad',k)}}
async function midiInit(){if(!navigator.requestMIDIAccess){MIDI.status='this browser has no Web MIDI (use Chrome, Edge or Firefox)';return}
 try{const acc=await navigator.requestMIDIAccess();const hook=()=>{MIDI.inputs=[...acc.inputs.values()];MIDI.inputs.forEach(inp=>inp.onmidimessage=midiMsg);
  MIDI.status=MIDI.inputs.length?MIDI.inputs.map(x=>x.name).join(', '):'no controller connected';midiBtn();if(!$('modal').hidden&&$('midipanel'))midiPanel()};
  acc.onstatechange=hook;hook()}catch(e){MIDI.status='MIDI not allowed: '+e.message}midiBtn()}
function midiBtn(){let b=$('midibtn');if(!b){b=document.createElement('button');b.id='midibtn';b.onclick=()=>{midiPanel();if(!MIDI.inputs.length&&!MIDI.status)midiInit()};$('expbtn').after(b)}
 b.textContent=MIDI.inputs.length?'🎹 '+MIDI.inputs.length:'🎹';b.title='MIDI controller: '+(MIDI.status||'click to connect')}
function midiPanel(){const nm=id=>!id?'—':id[0]==='n'?`note ${id.slice(2)} (${MIDI_NOTES[+id.slice(2)%12]}${Math.floor(+id.slice(2)/12)-1})`:`CC ${id.slice(3)}`;
 modal(`<div id="midipanel"><h2 style="margin:0">🎹 MIDI controller</h2><div class="sub">${esc(MIDI.status||'connecting…')}</div>
 <div class="sub" style="margin:6px 0">Press <b>learn</b>, then the pad, key or button to use. Buttons that send CC work too (pressed = value ≥ 64).${MIDI.last?` Last received: ${esc(nm(MIDI.last))}.`:''}</div>
 <div style="display:grid;grid-template-columns:1fr auto auto;gap:6px 10px;align-items:center">${MIDI_ACTIONS.map(([k,l])=>`<span>${esc(l)}</span><span class="sub">${esc(nm(MIDI.map[k]))}</span><button data-midilearn="${k}">${MIDI.learn===k?'press it now…':'learn'}</button>`).join('')}</div>
 <div style="margin-top:10px;display:flex;gap:8px"><button id="midireset">reset to defaults</button><button onclick="$('modal').hidden=true">done</button></div></div>`);
 $('midireset').onclick=()=>{MIDI.map={play:'n:36',next:'n:37',prev:'n:38',star:'n:39',nope:'n:40',pad1:'n:44'};midiSave();midiPanel()}}
document.addEventListener('click',e=>{const b=e.target.closest('[data-midilearn]');if(!b)return;MIDI.learn=MIDI.learn===b.dataset.midilearn?null:b.dataset.midilearn;midiPanel();if(!MIDI.inputs.length)midiInit()});
midiBtn();if(navigator.requestMIDIAccess&&navigator.permissions)navigator.permissions.query({name:'midi'}).then(r=>{if(r.state==='granted')midiInit()}).catch(()=>{});
// ---------- the tab you were on survives a refresh
{const _rTab=render;render=function(...a){try{localStorage.setItem('dcTab',st.tab)}catch(e){}return _rTab.apply(this,a)};
 let t=null;try{t=localStorage.getItem('dcTab')}catch(e){}
 if(t&&t!=='S'&&/^[A-Z]$/.test(t)&&$('tab'+t))window.CRATE.setTab(t)}
// ---------- playback progress: a thin bar along the now-playing strip, and a playhead over the sample's waveform
// (its row and the sample panel). One animation loop, only while something plays.
{const NS='http://www.w3.org/2000/svg';let raf=0;const marked=new Set();
 const head=svg=>{if(svg._ph)return svg._ph;const W=+svg.getAttribute('width'),H=+svg.getAttribute('height');
  const sh=document.createElementNS(NS,'rect'),ln=document.createElementNS(NS,'rect');sh.setAttribute('class','phs');ln.setAttribute('class','phl');
  sh.setAttribute('height',H);ln.setAttribute('height',H);ln.setAttribute('width',1.5);svg.append(sh,ln);return svg._ph={sh,ln,W}};
 const clear=()=>{marked.forEach(svg=>{if(svg._ph){svg._ph.sh.remove();svg._ph.ln.remove();svg._ph=null}});marked.clear();const b=$('npbar');if(b)b.style.width='0'};
 function tick(){raf=0;let any=false;const seen=new Set();
  players.forEach((a,i)=>{if(typeof i!=='number'||!a||!(a.duration>0)||!isFinite(a.duration))return;any=true;const p=Math.min(1,a.currentTime/a.duration);
   document.querySelectorAll(`.row[data-i="${i}"] svg.wave${st.sel===i?',#detail svg.wave':''}`).forEach(svg=>{const h=head(svg),x=p*h.W;
    h.sh.setAttribute('width',x);h.ln.setAttribute('x',Math.max(0,x-0.75));seen.add(svg);marked.add(svg)});
   if(NP&&NP.i===i){const np=$('np');if(np&&!np.hidden){let b=$('npbar');if(!b){np.insertAdjacentHTML('afterbegin','<div id="npbar"></div>');b=$('npbar')}b.style.width=(p*100).toFixed(2)+'%'}}});
  marked.forEach(svg=>{if(!seen.has(svg)&&svg._ph){svg._ph.sh.remove();svg._ph.ln.remove();svg._ph=null;marked.delete(svg)}});
  if(players.size)raf=requestAnimationFrame(tick);else clear()}  // keeps going while anything plays (length known or not yet)
 const _drawNPp=drawNP;drawNP=function(...a){const r=_drawNPp.apply(this,a);if(!raf)raf=requestAnimationFrame(tick);return r};
 window.CRATE.progressTick=()=>tick()}
// ---------- search: typing from another tab shows the results; a sample's id always finds it, whatever the filters
{  // BYID is the app's live index of sample ids: it also knows samples that arrived after the page loaded
 $('search').addEventListener('input',()=>{if($('search').value.trim()&&!$('sndbtn').classList.contains('on')&&st.tab!=='S'&&st.tab!=='G')window.CRATE.setTab('S')});
 const _fId=filtered;filtered=function(...a){const q=$('search').value.trim().toLowerCase();
  if(!$('sndbtn').classList.contains('on')&&/^[0-9a-z]{6}$/.test(q)&&BYID.has(q)&&!GONE.has(BYID.get(q)))return [BYID.get(q)];return _fId.apply(this,a)}}
// ---------- separation grain: a "grainy" tag on rows and in the sample panel (they also rank lower by quality)
{const GR=new Set(D.grainy||[]),TIP='watery, flickering artifacts from stem separation (louder vocals or drums were pulled out of the same frequencies): it ranks lower';
 const _rowG=rowHTML;rowHTML=function(i){const h=_rowG(i);if(!GR.has(i))return h;const a=h.indexOf('<div class="name">'),b=h.indexOf('</div>',a);
  return a<0||b<0?h:h.slice(0,b)+`<span class="tag grainy" title="${TIP}">grainy</span>`+h.slice(b)};
 const _selG=select;select=function(i,from){_selG(i,from);if(!GR.has(i))return;const m=document.querySelector('#detail .meta');
  if(m&&!m.querySelector('.grb'))m.insertAdjacentHTML('afterbegin',`<span class="badge grb" title="${TIP}">grainy</span> `)};
 window.CRATE.GRAINY=GR}
// ---------- where a play came from (crate pick or wildcard, the list under a sort, search, galaxy…), sent with its
// events so the Taste page can show which sources your stars come from: the direct test of the recommendations
{const SRC=new Map(),SORTS={div:'list · diverse',you:'list · for you',vibe:"list · today's vibe",disc:'list · discover',q:'list · best quality',rnd:'list · random'};
 const here=el=>{if(el&&el.closest('#detail'))return 'sample panel (goes well with, edits)';
  if(st.tab==='C'){const k=el&&el.closest('.kit');if(k){const ks=[...document.querySelectorAll('#list .kit')];return ks.indexOf(k)===0?'crate · for you':'crate · wildcards'}return 'crate'}
  if(st.tab==='G')return 'galaxy';if(st.tab==='K')return 'kits';if(st.tab==='F')return 'favourites';if(st.tab==='A')return 'artists';if(st.tab==='Y')return 'scout';
  if(st.tab==='S'){const snd=$('sndbtn')&&$('sndbtn').classList.contains('on');if(snd||(typeof SOUND!=='undefined'&&SOUND))return 'sound search';
   if($('search').value.trim())return 'search';const v=$('sort').value;return SORTS[v]||('list · '+v)}
  return 'tab '+st.tab};
 document.addEventListener('click',e=>{const b=e.target.closest('[data-play]');if(!b)return;const i=+b.dataset.play;if(S[i])SRC.set(S[i][F.path],here(b))},true);
 const _selSrc=select;select=function(i,from){if(S[i]&&!SRC.has(S[i][F.path]))SRC.set(S[i][F.path],here(document.querySelector(`#list .row[data-i="${i}"]`)));return _selSrc(i,from)};  // arrow keys
 const _sendSrc=sendEvent;sendEvent=function(path,type,value,id,ctx){if(!SERVED)return;
  const src=SRC.get(path)||here(null);fetch('api/event',{method:'POST',body:JSON.stringify({path,type,value,id,context:Object.assign({src},ctx||{})})}).catch(()=>{});scheduleRefit()};
 window.CRATE.playSource=p=>SRC.get(p)}
// ---------- alternate takes: samples that are the same thing again in their song (the same drum hit, the same sung
// words, the same chord). A 🔁 tag on rows plays through them; the sample panel lists them; T steps to the next one.
{const TG=new Map();(D.takes||[]).forEach(g=>g.forEach(i=>TG.set(i,g)));
 // the groups also come from the server by sample id, so samples newer than the page file (mined since the last
 // build, arriving while you work) have their takes too; asked again whenever samples have arrived
 let tkN=-1;async function takesRefresh(){if(!SERVED||tkN===S.length)return;const n=S.length;let r;try{r=await (await fetch('api/takes')).json()}catch(e){return}
  tkN=n;TG.clear();(r.groups||[]).forEach(ids=>{const g=ids.map(id=>BYID.get(id)).filter(i=>i!=null);if(g.length>1)g.forEach(i=>TG.set(i,g))});
  if(st.tab==='S'||st.tab==='C'){const m=document.querySelector('main'),y=m?m.scrollTop:0;render();if(m)m.scrollTop=y}}
 takesRefresh();setInterval(takesRefresh,5000);
 const live=i=>(TG.get(i)||[]).filter(j=>S[j]&&!GONE.has(j)&&!TASTE.disliked.has(S[j][F.path]));
 const at=j=>{const t=S[j][F.start]||0;return `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`};
 let seq=0;
 // play every take once, back to back, starting at `from`; stopping (or playing anything else) ends it
 function playTakes(i,from){const g=live(i);if(g.length<2)return;const my=++seq;let k=Math.max(0,g.indexOf(from??g[0]));stopAll();
  const next=()=>{if(my!==seq||k>=g.length)return;const j=g[k++];toggle(j,null,{loop:false});const a=players.get(j);if(!a)return;
   const prev=a.onended;a.onended=()=>{if(prev)prev();if(my===seq)setTimeout(next,160)}};next()}
 const TIP='other takes of this in the same song (the same hit, words or chord again): click to play through them all';
 const _rowT=rowHTML;rowHTML=function(i){const h=_rowT(i),n=live(i).length;if(n<2)return h;const a=h.indexOf('<div class="name">'),b=h.indexOf('</div>',a);
  return a<0||b<0?h:h.slice(0,b)+`<span class="tag takes" data-takes="${i}" title="${TIP}">🔁 ${n} takes</span>`+h.slice(b)};
 document.addEventListener('click',e=>{const t=e.target.closest('[data-takes]');if(t){e.stopPropagation();e.preventDefault();playTakes(+t.dataset.takes);return}
  const all=e.target.closest('#tkall');if(all){e.stopPropagation();playTakes(+all.dataset.i)}},true);
 const _selT=select;select=function(i,from){_selT(i,from);const g=live(i);if(g.length<2)return;const m=document.querySelector('#detail .meta');if(!m||$('tkbox'))return;
  m.insertAdjacentHTML('afterend',`<div class="prov" id="tkbox"><b>🔁 ${g.length} takes</b> <span class="sub">the same thing again in this song</span>
   <button id="tkall" data-i="${i}" title="play every take once, back to back">▶ play all</button> <span class="sub">T: next take</span>
   ${g.map(j=>`<div class="prow${j===i?' cur':''}"><button class="play" data-play="${j}">▶</button><div class="name">@ ${at(j)} · ${S[j][F.dur]}s${S[j][F.cam]?' · '+S[j][F.cam]:''}${(typeof WORDS!=='undefined'&&WORDS[j])?` · <span class="sub">“${esc(String(WORDS[j]).slice(0,40))}”</span>`:''}${j===i?' · <span class="sub">this one</span>':''}</div><div style="display:flex;gap:6px">${star(S[j][F.path],S[j][F.id],lbl(j))}${j===i?'':`<button data-go="${j}" title="open this take">→</button>`}</div></div>`).join('')}</div>`);mark()};
 document.addEventListener('keydown',e=>{if(e.key!=='t'&&e.key!=='T')return;if(e.metaKey||e.ctrlKey||e.altKey)return;const el=document.activeElement;if(el&&/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))return;
  if(st.sel==null)return;const g=live(st.sel);if(g.length<2){toast('no other takes of this one');return}e.preventDefault();seq++;
  const j=g[(g.indexOf(st.sel)+1)%g.length];stopAll();select(j,'go');toggle(j,null,{loop:false})});
 window.CRATE.takesOf=live;window.CRATE.playTakes=playTakes}
// ---------- 📸 stem blends: the stem mixer's low-end duck, its snapshots, and the view that plays two of them side by
// side (docs/plans/blend.md). This block comes before the stem mixer's own: that one builds its chains with
// BLEND.mkChain, sets them with BLEND.applyChain, and hands over its own functions with BLEND.init(hooks) before the
// tab is first drawn.
(function () {
  const BL = {};
  BL.MAX_SNAPS = 8;
  BL.BARS = [2, 4, 8, 16];                                                     // a transition's length
  BL.WINS = { all: [0, 1], first: [0, 0.5], second: [0.5, 1], cut: [0.5, 0.5] };  // when in it a layer changes
  BL.STYLES = ['filter', 'xfade'];
  BL.DUCK = { fc: 120, keyLp: 100, smooth: 20, scale: 13, db: 3, max: 12 };
  // At 0.08 RMS the test vocal drops Tops by 3.0 / 12.0 dB. At 12 dB, Other drops about 8 dB near
  // 250 and 500 Hz and less than 1.5 dB at 60 Hz, 4 kHz and 8 kHz. Between phrases both recover.
  BL.VDUCK = { hp: 150, smooth: 6, scale: 18, fc: 10, bands: [250, 500, 1000, 2000, 4000, 8000],
    q: 1.92, bscale: 46, db: 3, max: 12 };
  // A 125 Hz test kick takes 2.1 dB off Other at the default amount. At 12 dB it takes 7.3 dB off in
  // the 16–40 ms window, 12.7 dB during the hit, and 0.1 dB in the 60–100 ms after it ends.
  BL.GDUCK = { smooth: 30, bands: [125, ...BL.VDUCK.bands], q: 1.92, bscale: 12, db: 2, max: 12 };
  BL.DUCKED = { bass: 'lows', tops: 'vocals', other: 'vocals' };
  BL.Q = -3.0103;      // Web Audio's lowpass / highpass Q is in dB: this is Butterworth (no resonance)
  BL.STAGES = 2;       // biquads per filter: 2 = 24 dB / octave
  BL.EDGE = 0.05;      // the share of a filter handoff, at each end, over which the part's gain opens or closes
  BL.clamp01 = x => Math.max(0, Math.min(1, x));

  // ---------------------------------------------------------------- the maths

  // where a layer is (0 = the left snapshot's part, 1 = the right one's) when the master is at m
  BL.layerPos = (m, win) => {
    const [a, b] = BL.WINS[win] || BL.WINS.all;
    return a === b ? (m >= a ? 1 : 0) : BL.clamp01((m - a) / (b - a));
  };

  // a layer at position p: the gains of its outgoing (a) and incoming (b) part, the outgoing part's highpass and
  // the incoming part's lowpass, in Hz. 0 and nyq park a filter: at those cutoffs a biquad passes everything.
  BL.blendAt = (style, p, nyq) => {
    if (p <= 0) return { ga: 1, gb: 0, hp: 0, lp: nyq };
    if (p >= 1) return { ga: 0, gb: 1, hp: 0, lp: nyq };
    if (style === 'xfade') return { ga: Math.cos(p * Math.PI / 2), gb: Math.sin(p * Math.PI / 2), hp: 0, lp: nyq };
    const fc = 20 * Math.pow(1000, p);
    return { ga: Math.min(1, (1 - p) / BL.EDGE), gb: Math.min(1, p / BL.EDGE), hp: fc, lp: fc };
  };

  // ---------------------------------------------------------------- the audio graph

  // a short ramp: unlike setTargetAtTime it ends, so a filter goes back to cheap processing afterwards
  BL.ramp = (param, v, t) => {
    param.cancelScheduledValues(t);
    param.setValueAtTime(param.value, t);
    param.linearRampToValueAtTime(v, t + 0.03);
  };

  // one side of a blend: highpass -> lowpass -> gain
  BL.mkXf = ctx => {
    const mk = (type, f0) => Array.from({ length: BL.STAGES }, () => {
      const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = f0; f.Q.value = BL.Q; return f;
    });
    const h = mk('highpass', 0), l = mk('lowpass', ctx.sampleRate / 2), g = ctx.createGain(), all = [...h, ...l, g];
    all.forEach((n, i) => { if (i) all[i - 1].connect(n); });
    return { in: all[0], out: g, h, l, g };
  };
  BL.setXf = (x, o, t) => {   // o: {gain, hp, lp}
    x.g.gain.setTargetAtTime(o.gain, t, 0.02);
    x.h.forEach(f => BL.ramp(f.frequency, o.hp, t));
    x.l.forEach(f => BL.ramp(f.frequency, o.lp, t));
  };

  // Rectify, smooth and scale the key, then clamp its level to 0..1.
  const duckEnv = (ctx, input, type, frequency, q, smooth, scale) => {
    const filter = ctx.createBiquadFilter(), rect = ctx.createWaveShaper(),
      ksm = ctx.createBiquadFilter(), ksc = ctx.createGain(), lim = ctx.createWaveShaper();
    filter.type = type; filter.frequency.value = frequency; filter.Q.value = q;
    ksm.type = 'lowpass'; ksm.frequency.value = smooth; ksm.Q.value = -6.0206;   // critically damped
    rect.curve = new Float32Array([1, 0, 1]);   // |x|
    lim.curve = new Float32Array([0, 0, 1]);    // 0..1, and never above 1
    ksc.gain.value = scale;
    input.connect(filter).connect(rect).connect(ksm).connect(ksc).connect(lim);
    return lim;
  };

  BL.duckBus = ctx => {
    const input = ctx.createGain(), { keyLp, smooth, scale } = BL.DUCK;
    return { in: input, env: duckEnv(ctx, input, 'lowpass', keyLp, BL.Q, smooth, scale) };
  };
  BL.vduckBus = ctx => {
    const input = ctx.createGain(), { hp, smooth, scale, bands, q, bscale } = BL.VDUCK;
    return { in: input, env: duckEnv(ctx, input, 'highpass', hp, BL.Q, smooth, scale),
      bands: bands.map(f => duckEnv(ctx, input, 'bandpass', f, q, smooth, bscale)) };
  };
  BL.gduckBus = ctx => {
    const input = ctx.createGain(), { bands, q, smooth, bscale } = BL.GDUCK;
    return { in: input, bands: bands.map(f => duckEnv(ctx, input, 'bandpass', f, q, smooth, bscale)) };
  };

  BL.GLUE = { set: { threshold: -18, knee: 12, ratio: 2, attack: 0.03, release: 0.25 }, fade: 0.01 };
  const MASTER_SET={
   bottom:{type:'highpass',frequency:30,Q:0.707},
   top:{type:'highshelf',frequency:12000,gain:-1.5},
   glue:BL.GLUE.set,
   limiter:{threshold:-3,knee:0,ratio:20,attack:0.001,release:0.1}
  };
  const masterProbes=new Map();
  function masterProbe(set){
   const key=JSON.stringify(set);
   if(masterProbes.has(key))return masterProbes.get(key);
   const rate=48000,amount=0.001,ctx=new OfflineAudioContext(1,rate,rate);
   const tone=new OscillatorNode(ctx,{frequency:1000}),level=new GainNode(ctx,{gain:amount});
   tone.connect(level).connect(new DynamicsCompressorNode(ctx,set)).connect(ctx.destination);
   tone.start();
   const probe=ctx.startRendering().then(buffer=>{
    const data=buffer.getChannelData(0),half=data.length/2;
    let sum=0;
    for(let i=half;i<data.length;i++)sum+=data[i]*data[i];
    return Math.sqrt(sum/half)/(amount/Math.SQRT2);
   });
   masterProbes.set(key,probe);
   return probe;
  }
  async function masterChain(ctx){
   const {bottom,top,glue:glueSet,limiter:limiterSet}=MASTER_SET;
   const [glueMakeup,limiterMakeup]=await Promise.all([masterProbe(glueSet),masterProbe(limiterSet)]);
   // Web Audio takes highpass Q in dB. MASTER_SET stores the linear Q factor.
   const input=new BiquadFilterNode(ctx,{...bottom,Q:20*Math.log10(bottom.Q)});
   const shelf=new BiquadFilterNode(ctx,top),glue=new DynamicsCompressorNode(ctx,glueSet);
   const trim=new GainNode(ctx,{gain:1/glueMakeup}),limiter=new DynamicsCompressorNode(ctx,limiterSet);
   const out=new GainNode(ctx,{gain:1/limiterMakeup});
   input.connect(shelf).connect(glue).connect(trim).connect(limiter).connect(out);
   return {in:input,out,glue};
  }
  const MASTER_LEVEL=0.9;

  // Keep the direct path live during calibration and use the latest switch position for a pending swap.
  BL.mxRoute = MX => {
    const { master, mast } = MX;
    if (!master) return;
    const ctx = master.context, dest = ctx.destination;
    if (!mast) { master.connect(dest); return; }
    const target = () => mast.on && mast.chain ? mast.chain.in : dest;
    if (!mast.routed) {
      mast.routed = dest;
      master.connect(dest);
      masterChain(ctx).then(chain => {
        chain.out.connect(dest);
        mast.chain = chain;
        mast.built++;
        BL.mxRoute(MX);
      }, () => {}); // A failed calibration leaves the direct route live.
      return;
    }
    if (mast.swapping || target() === mast.routed) return;
    mast.swapping = true;
    const gain = master.gain, t = ctx.currentTime, level = gain.value;
    gain.cancelScheduledValues(t);
    gain.setValueAtTime(level, t);
    gain.linearRampToValueAtTime(0, t + 0.01);
    setTimeout(() => {
      const next = target(), now = ctx.currentTime;
      gain.cancelScheduledValues(now);
      gain.setValueAtTime(0, now);
      if (next !== mast.routed) {
        master.disconnect(mast.routed);
        master.connect(next);
        mast.routed = next;
      }
      gain.linearRampToValueAtTime(MASTER_LEVEL, now + 0.01);
      mast.swapping = false;
    }, 15);
  };

  window.CRATE.masterProbe = masterProbe;
  window.CRATE.masterChain = masterChain;

  BL.drumGroup = (ctx, out, probe = masterProbe) => {
    const { set, fade } = BL.GLUE;
    const delay = Math.floor(0.006 * ctx.sampleRate) / ctx.sampleRate;
    const input = ctx.createGain(), comp = new DynamicsCompressorNode(ctx, set),
      wet = new GainNode(ctx, { gain: 0 }), dry = ctx.createGain(),
      hold = new DelayNode(ctx, { delayTime: delay }), rest = new DelayNode(ctx, { delayTime: delay });
    input.connect(comp).connect(wet).connect(out);
    input.connect(hold).connect(dry).connect(out);
    rest.connect(out);
    const g = { in: input, comp, wet, dry, rest, out, on: true };
    let makeup, from = 0, to = 0, start = 0;
    g.set = (on, t = ctx.currentTime) => {
      g.on = on;
      const next = on ? 1 : 0;
      if (!makeup || next === to) return;
      // Pick up an interrupted crossfade at its current position.
      const mix = from + (to - from) * BL.clamp01((t - start) / fade);
      const interrupting = from !== to && t > start && t <= start + fade;
      for (const [param, value, target] of [[wet.gain, mix / makeup, next / makeup], [dry.gain, 1 - mix, 1 - next]]) {
        param.cancelScheduledValues(t);
        if (interrupting) param.linearRampToValueAtTime(value, t);
        else param.setValueAtTime(value, t);
        param.linearRampToValueAtTime(target, t + fade);
      }
      from = mix; to = next; start = t;
    };
    g.ready = Promise.resolve().then(() => probe(set)).then(value => {
      if (Number.isFinite(value) && value > 0) {
        makeup = Math.max(1, value);
        g.set(g.on);
      }
      return g;
    }, () => g);
    return g;
  };

  // the mixer's output and the duck bus, made once (MX.master, MX.bus)
  BL.out = (MX, ctx) => {
    if (!MX.master) {
      MX.master = ctx.createGain(); MX.master.gain.value = MASTER_LEVEL; BL.mxRoute(MX);
      MX.bus = BL.duckBus(ctx);
      MX.bus.v = BL.vduckBus(ctx);
      MX.bus.d = BL.gduckBus(ctx);
      MX.bus.g = BL.drumGroup(ctx, MX.master);
      MX.bus.g.set(MX.glue?.on !== false);
      MX.bus.rev = BL.reverb(ctx, MX.bus.g.rest, MX.reverb);   // every chain made on this bus gets a send to it
    }
    return MX;
  };

  // ---------------------------------------------------------------- reverb
  // One reverb for the whole mixer, as on a desk: each slot sends some of itself to it, so the parts share a space.
  // It is a convolution with an impulse response made here: stereo (left and right are different noise, so it is
  // wide), highs dying away faster than lows (as in a real room), a short pre-delay so the dry sound stays in front,
  // a few early reflections, and a soft onset. Lows are kept out of it (they turn to mud), and the tail is toned down
  // a little. type: room (small, 0.7 s) · plate (dense and bright, 1.8 s) · hall (large, 3.2 s); decay overrides.
  BL.REVERBS = { room: { decay: 0.7, pre: 0.008, bright: 0.75, er: 5 }, plate: { decay: 1.8, pre: 0.012, bright: 0.9, er: 0 },
    hall: { decay: 3.2, pre: 0.028, bright: 0.6, er: 8 } };
  BL.makeIR = (ctx, type, decay) => {
    const R = BL.REVERBS[type] || BL.REVERBS.plate, T = Math.max(0.2, Math.min(8, +decay || R.decay)), sr = ctx.sampleRate,
      n = Math.ceil((T * 1.25 + R.pre) * sr), buf = ctx.createBuffer(2, n, sr), pre = Math.floor(R.pre * sr);
    let seed = 1234567;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };   // the same room every time
    const gauss = () => { let u = 0; for (let k = 0; k < 4; k++) u += rnd(); return (u - 2) * 1.2; };
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch); let lp = 0, lp2 = 0;
      // three bands of noise, each with its own decay: lows ring 15% longer, highs half as long (less for a bright plate)
      const kL = Math.exp(-2 * Math.PI * 350 / sr), kH = Math.exp(-2 * Math.PI * 3500 / sr);
      const tL = T * 1.15, tM = T, tH = T * (0.35 + 0.45 * R.bright), att = Math.floor(0.012 * sr);
      for (let i = pre; i < n; i++) {
        const t = (i - pre) / sr, x = gauss();
        lp = kL * lp + (1 - kL) * x; lp2 = kH * lp2 + (1 - kH) * x;
        const low = lp, high = x - lp2, mid = lp2 - lp;
        const e = b => Math.pow(10, -3 * t / b);                                   // -60 dB at each band's decay time
        d[i] = (low * e(tL) * 1.6 + mid * e(tM) + high * e(tH) * R.bright) * Math.min(1, (i - pre) / att);
      }
      for (let k = 0; k < R.er; k++) {                                              // early reflections: a few discrete echoes
        const at = pre + Math.floor((0.004 + rnd() * 0.05) * sr * (type === 'hall' ? 1.6 : 1));
        if (at < n) d[at] += (rnd() < 0.5 ? -1 : 1) * (0.9 - k * 0.08);
      }
    }
    let e = 0; for (let ch = 0; ch < 2; ch++) { const d = buf.getChannelData(ch); for (let i = 0; i < n; i++) e += d[i] * d[i]; }
    const g = 1 / Math.sqrt(e / 2 + 1e-12);                                         // the same loudness whatever its length
    for (let ch = 0; ch < 2; ch++) { const d = buf.getChannelData(ch); for (let i = 0; i < n; i++) d[i] *= g; }
    return buf;
  };
  BL.reverb = (ctx, out, set) => {
    const inp = ctx.createGain(), hp = ctx.createBiquadFilter(), cv = ctx.createConvolver(), lp = ctx.createBiquadFilter(), wet = ctx.createGain();
    hp.type = 'highpass'; hp.frequency.value = 180; lp.type = 'lowpass'; lp.frequency.value = 9000; wet.gain.value = 0.9; cv.normalize = false;
    inp.connect(hp); hp.connect(cv); cv.connect(lp); lp.connect(wet); wet.connect(out);
    const r = { in: inp, cv, set: (type, decay) => { cv.buffer = BL.makeIR(ctx, type, decay); r.type = type; r.decay = decay; } };
    r.set((set && set.type) || 'plate', set && set.decay);
    return r;
  };
  BL.setReverb = (MX, type, decay) => { MX.reverb = { type, decay: decay || BL.REVERBS[type].decay }; if (MX.bus && MX.bus.rev) MX.bus.rev.set(type, MX.reverb.decay); };

  BL.HARM = { drive: { gain: 0.35 }, oct: { gain: 1.35, lp: 100, hp: 50, top: 240 } };
  const harmonicsPath = (ctx, kind = 'drive') => {
    if (kind === 'oct') {
      const { lp, hp, top } = BL.HARM.oct;
      const filter = (type, frequency) => {
        const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = frequency; f.Q.value = BL.Q; return f;
      };
      const shaper = ctx.createWaveShaper(), gain = ctx.createGain();
      shaper.curve = new Float32Array([1, 0, 1]); // full-wave rectification doubles the bass frequency
      gain.gain.value = 0;
      const nodes = [filter('lowpass', lp), filter('lowpass', lp), shaper,
        filter('highpass', hp), filter('highpass', hp), filter('lowpass', top), gain];
      nodes.forEach((node, i) => { if (i) nodes[i - 1].connect(node); });
      return { in: nodes[0], out: gain, nodes };
    }
    const drive = ctx.createGain(), shaper = ctx.createWaveShaper(), hp = ctx.createBiquadFilter(),
      hp2 = ctx.createBiquadFilter(), gain = ctx.createGain(), curve = new Float32Array(1024);
    for (let k = 0; k < curve.length; k++) curve[k] = Math.tanh(3 * (k / 511.5 - 1));
    shaper.curve = curve;
    shaper.oversample = '4x';
    drive.gain.value = 6;
    gain.gain.value = 0;
    hp.type = hp2.type = 'highpass';
    hp.frequency.value = hp2.frequency.value = 110;
    drive.connect(shaper);
    shaper.connect(hp);
    hp.connect(hp2);
    hp2.connect(gain);
    return { in: drive, out: gain, nodes: [drive, shaper, hp, hp2, gain] };
  };
  const harmMeasures = new WeakMap();
  BL.harmMeasure = (buf, kind = 'drive') => {
    let byKind = harmMeasures.get(buf);
    if (!byKind) {
      byKind = new Map();
      harmMeasures.set(buf, byKind);
    }
    if (!byKind.has(kind)) {
      const measure = (async () => {
        const ctx = new OfflineAudioContext(buf.numberOfChannels, buf.length, buf.sampleRate);
        const src = ctx.createBufferSource(), path = harmonicsPath(ctx, kind);
        src.buffer = buf;
        src.connect(path.in);
        path.out.gain.value = BL.HARM[kind].gain;
        path.out.connect(ctx.destination);
        src.start();
        const wet = await ctx.startRendering();
        const dry = [], harm = [];
        for (let ch = 0; ch < buf.numberOfChannels; ch++) {
          dry.push(buf.getChannelData(ch));
          harm.push(wet.getChannelData(ch));
        }
        let dd = 0, hh = 0, dh = 0;
        for (let i = 0; i < buf.length; i++) {
          let d = 0, h = 0;
          for (let ch = 0; ch < dry.length; ch++) {
            d += dry[ch][i];
            h += harm[ch][i];
          }
          dd += d * d;
          hh += h * h;
          dh += d * h;
        }
        return dd ? { r2: hh / dd, c: dh / dd } : { r2: 0, c: 0 };
      })();
      byKind.set(kind, measure.catch(() => null));
    }
    return byKind.get(kind);
  };
  BL.harmKind = p => p.hk === 'oct' ? 'oct' : 'drive';
  BL.harmAmt = p => BL.clamp01(Number(p.harm) || 0);
  BL.harmComp = (p, hc) => {
    if (!hc || p.hup) return 1;
    const a = BL.harmAmt(p);
    const ratio = 1 + 2 * a * hc.c + a * a * hc.r2;
    return ratio > 0 ? 1 / Math.sqrt(ratio) : 1;
  };
  BL.legacyHarmDb = (p, hc) => p.hup ? -20 * Math.log10(BL.harmComp({ harm: p.harm }, hc)) : 0;

  // EQ and the bass duck, then the vocal and drum dips, volume and output. The key taps follow the volume.
  // Harmonics add overtones to help the bass carry on small speakers. The wet paths are the soft clipper (hg) and the octave (hgo).
  BL.mkChain = (ctx, out, bus) => {
    const group = bus.g?.out === out ? bus.g : null, dest = group ? group.rest : out;
    const lo = ctx.createBiquadFilter(), mid = ctx.createBiquadFilter(), hi = ctx.createBiquadFilter(),
      duck = ctx.createBiquadFilter(), dk = ctx.createGain(), vol = ctx.createGain(), key = ctx.createGain(),
      send = ctx.createGain(), dl = ctx.createDelay(2), fb = ctx.createGain(), lp = ctx.createBiquadFilter();
    lo.type = 'lowshelf'; lo.frequency.value = 200; mid.type = 'peaking'; mid.frequency.value = 1000; mid.Q.value = 0.8;
    hi.type = 'highshelf'; hi.frequency.value = 5000; lp.type = 'lowpass'; lp.frequency.value = 4500; fb.gain.value = 0.35;
    duck.type = 'lowshelf'; duck.frequency.value = BL.DUCK.fc; duck.gain.value = 0; dk.gain.value = 0; key.gain.value = 0;
    const { fc, bands, q } = BL.VDUCK, vbus = bus.v, gbus = bus.d;
    const vkey = ctx.createGain(), gkey = ctx.createGain(), vduck = ctx.createBiquadFilter(), vdk = ctx.createGain();
    vduck.type = 'highshelf'; vduck.frequency.value = fc; vdk.gain.value = 0;
    const peak = (frequency, q) => {
      const filter = ctx.createBiquadFilter();
      filter.type = 'peaking'; filter.frequency.value = frequency; filter.Q.value = q;
      return filter;
    };
    const vb = bands.map(f => peak(f, q)), glow = peak(BL.GDUCK.bands[0], BL.GDUCK.q);
    const bandFilters = [glow, ...vb];
    const amount = () => new GainNode(ctx, { gain: 0 });
    const vbk = vb.map(amount), gbk = bandFilters.map(amount);
    const inp = ctx.createGain(), harmonics = harmonicsPath(ctx), octave = harmonicsPath(ctx, 'oct');
    const hg = harmonics.out, hgo = octave.out;
    const vin = vbus || gbus ? ctx.createGain() : vol;
    inp.connect(lo); inp.connect(harmonics.in); hg.connect(vin); inp.connect(octave.in); hgo.connect(vin);
    lo.connect(mid); mid.connect(hi); hi.connect(duck); duck.connect(vin); vol.connect(dest);
    if (vin !== vol) vin.connect(vol);
    if (vbus) vol.connect(vkey);
    if (gbus) vol.connect(gkey);
    send.gain.value = 0;
    send.connect(dl); dl.connect(lp); lp.connect(fb); fb.connect(dl);
    vol.connect(key); key.connect(bus.in); bus.env.connect(dk);
    const rsend = ctx.createGain(); rsend.gain.value = 0;
    if (bus.rev) { vol.connect(rsend); rsend.connect(bus.rev.in); }
    const c = { in: inp, out, dest, group, grouped: false, lo, mid, hi, duck, dk, key, vol, send, dl, fb, lp, hg, hgo, rsend, ducked: false,
      dlyOn: false, dlyTimer: null,
      vkey, vduck, vdk, vb, vbk, vducked: false, vbanded: false, gkey, glow, gbk, gbanded: false };
    const tops = { filters: [vduck], amounts: [vdk], levels: [vbus?.env] };
    if (!vbus) tops.levels = null;
    const voice = { filters: vb, amounts: vbk, levels: vbus?.bands };
    const drums = { filters: bandFilters, amounts: gbk, levels: gbus?.bands };
    const other = gbus ? bandFilters : vb;
    let path = null, vkeyed = false, gkeyed = false;
    const wirePath = (filters, method) => {
      const nodes = [vin, ...(filters || []), vol];
      nodes.slice(0, -1).forEach((node, i) => node[method](nodes[i + 1]));
    };
    const wireAmounts = ({ amounts, levels, filters }, method) => amounts.forEach((node, i) => {
      levels[i][method](node);
      node[method](filters[i].gain);
    });
    const setDuck = (bank, flag, db, t, timeConstant) => {
      const on = !!bank.levels && db > 0;
      if (on) bank.amounts.forEach(node => node.gain.setTargetAtTime(-db, t, timeConstant));
      if (on !== c[flag]) wireAmounts(bank, on ? 'connect' : 'disconnect');
      c[flag] = on;
    };
    c.applyDucks = (s, t, timeConstant) => {
      if (vin === vol) return;
      if (vbus && !!s.vkey !== vkeyed) {
        if (s.vkey) vkey.connect(vbus.in); else vkey.disconnect(vbus.in);
        vkeyed = !!s.vkey;
      }
      if (gbus && !!s.gkey !== gkeyed) {
        if (s.gkey) gkey.connect(gbus.in); else gkey.disconnect(gbus.in);
        gkeyed = !!s.gkey;
      }
      setDuck(tops, 'vducked', s.vduck, t, timeConstant);
      setDuck(voice, 'vbanded', s.vband, t, timeConstant);
      setDuck(drums, 'gbanded', s.gband, t, timeConstant);
      const next = c.vducked ? tops.filters : c.vbanded || c.gbanded ? other : null;
      if (next !== path) {
        wirePath(path, 'disconnect');
        wirePath(next, 'connect');
        path = next;
      }
    };
    // Disconnect the shared envelope inputs and the delay feedback loop when a chain is retired.
    c.drop = () => {
      clearTimeout(c.dlyTimer);
      c.dlyTimer = null;
      c.dlyOn = false;
      bus.env.disconnect(dk);
      if (c.vducked) wireAmounts(tops, 'disconnect');
      if (c.vbanded) wireAmounts(voice, 'disconnect');
      if (c.gbanded) wireAmounts(drums, 'disconnect');
      if (vin !== vol) vin.disconnect();
      [inp, ...harmonics.nodes, ...octave.nodes, lo, mid, hi, duck, dk, vol, key, send, dl, fb, lp, rsend,
        vkey, vduck, vdk, ...vb, ...vbk, gkey, glow, ...gbk]
        .forEach(n => n.disconnect());
      c.vducked = c.vbanded = c.gbanded = false;
    };
    return c;
  };

  // s: {gain (linear), eq: [lo, mid, hi] dB, send, delay (s), key (feeds the bus), duck (dB taken off the lows, 0 = off)}
  BL.applyChain = (c, s, t) => {
    const T = 0.02, oct = s.hk === 'oct', harm = s.harm || 0;
    if (c.group && !!s.grouped !== c.grouped) {
      const dest = s.grouped ? c.group.in : c.group.rest;
      for (const node of c.dlyOn ? [c.vol, c.lp] : [c.vol]) {
        node.disconnect(c.dest);
        node.connect(dest);
      }
      c.dest = dest;
      c.grouped = !!s.grouped;
    }
    c.vol.gain.setTargetAtTime(s.gain, t, T);
    c.lo.gain.setTargetAtTime(s.eq[0], t, T); c.mid.gain.setTargetAtTime(s.eq[1], t, T); c.hi.gain.setTargetAtTime(s.eq[2], t, T);
    c.send.gain.setTargetAtTime(s.send, t, T); c.dl.delayTime.setTargetAtTime(Math.min(1.9, s.delay), t, T);
    if (s.send > 0) {
      if (c.dlyTimer !== null) { clearTimeout(c.dlyTimer); c.dlyTimer = null; }
      if (!c.dlyOn) { c.vol.connect(c.send); c.lp.connect(c.dest); c.dlyOn = true; }
    } else if (c.dlyOn && c.dlyTimer === null) {
      c.dlyTimer = setTimeout(() => {
        try { c.vol.disconnect(c.send); c.lp.disconnect(c.dest); } catch (e) {}
        c.dlyOn = false;
        c.dlyTimer = null;
      }, 4000);
    }
    c.fb.gain.setTargetAtTime(s.fb ?? 0.35, t, T);
    c.hg.gain.setTargetAtTime(oct ? 0 : BL.HARM.drive.gain * harm, t, T);
    c.hgo.gain.setTargetAtTime(oct ? BL.HARM.oct.gain * harm : 0, t, T);
    c.rsend.gain.setTargetAtTime(s.rev || 0, t, T);
    c.key.gain.setTargetAtTime(s.key ? 1 : 0, t, T);
    c.dk.gain.setTargetAtTime(-s.duck, t, T);
    const want = s.duck > 0;
    if (want !== c.ducked) { if (want) c.dk.connect(c.duck.gain); else c.dk.disconnect(c.duck.gain); c.ducked = want; }
    c.applyDucks(s, t, T);
  };

  // a part's mix settings as applyChain takes them. stem: what its slot plays.
  // o: {on (audible: not muted, not soloed out), fx, bar (seconds), hc (measure for the part's harmonics kind),
  // DT (note value -> share of a bar), duck: {on, db, ddb} | undefined}
  BL.duckDb = d => d && d.db != null ? Math.max(0, Math.min(BL.DUCK.max, +d.db)) : BL.DUCK.db;
  BL.gduckDb = d => d?.ddb != null ? Math.max(0, Math.min(BL.GDUCK.max, +d.ddb)) : BL.GDUCK.db;
  BL.mixOf = (p, stem, o) => ({
    gain: o.on ? Math.pow(10, (p.db || 0) / 20) * (o.fx ? BL.harmComp(p, o.hc) : 1) : 0,
    eq: o.fx && p.eqOn !== false ? (p.eq || [0, 0, 0]) : [0, 0, 0],
    send: o.fx && p.dlyOn !== false ? (p.dly || 0) : 0,
    fb: p.fb ?? 0.35,
    harm: o.fx ? BL.harmAmt(p) : 0,
    hk: BL.harmKind(p),
    rev: o.fx && p.revOn !== false ? (p.rev || 0) : 0,
    delay: o.bar * (o.DT[p.dt || '1/8'] || 1 / 8),
    grouped: stem === 'drums' || stem === 'tops',
    gkey: stem === 'drums' || stem === 'tops',
    key: stem === 'drums',
    duck: stem === 'bass' && !(o.duck && o.duck.on === false) ? BL.duckDb(o.duck) : 0,
    vkey: stem === 'vocals',
    vduck: stem === 'tops' && o.duck?.on !== false ? BL.duckDb(o.duck) : 0,
    vband: stem === 'other' && o.duck?.on !== false ? BL.duckDb(o.duck) : 0,
    gband: stem === 'other' && o.duck?.on !== false ? BL.gduckDb(o.duck) : 0,
  });

  // ---------------------------------------------------------------- saved state

  // trans[i] sits between snaps[i] and snaps[i + 1]: keep one per neighbouring pair, each well-formed
  BL.fixTrans = MX => {
    const n = Math.max(0, MX.snaps.length - 1);
    MX.trans = Array.from({ length: n }, (_, i) => {
      const t = MX.trans[i] || {};
      return { bars: BL.BARS.includes(t.bars) ? t.bars : 8, layers: t.layers && typeof t.layers === 'object' ? t.layers : {} };
    });
  };
  // saved state -> MX: the duck settings, the snapshots and their transitions (older saves have none of them)
  BL.adopt = (MX, sv) => {
    sv = sv || {};
    MX.duck = sv.duck && typeof sv.duck === 'object' ? sv.duck : {};
    MX.snaps = Array.isArray(sv.snaps) ? sv.snaps.slice(0, BL.MAX_SNAPS) : [];
    MX.trans = Array.isArray(sv.trans) ? sv.trans : [];
    BL.fixTrans(MX);
    MX.snapSel = null;
  };

  // ---------------------------------------------------------------- the mixer's side: the duck control

  let H = null;   // the mixer's own functions (studio.js): {MX, STEMS, ICON, PITCHED, DT, role, state, save, draw, sync, play, apply, ev, barLenM}
  BL.duckOf = id => H.MX.duck[id] || (H.MX.duck[id] = { on: true, db: BL.DUCK.db });
  // ---------------------------------------------------------------- snapshots

  BL.LETTERS = 'ABCDEFGH';
  BL.STEMVAR = { drums: '--PERC', tops: '--MEL', bass: '--BASS', vocals: '--VOX', other: '--KEYS' };
  const copy = x => JSON.parse(JSON.stringify(x));

  // a part that sounds: there, holding a song, not muted
  BL.audible = p => !!p && p.track != null && p.mute !== true;
  // the same audio: volume, EQ, delay and lock do not count
  BL.sameAudio = (a, b) => BL.audible(a) && BL.audible(b) && a.stem === b.stem && a.track === b.track &&
    a.bar0 === b.bar0 && a.n === b.n && (a.k || 1) === (b.k || 1) && !!a.legacyLoop === !!b.legacyLoop &&
    (a.cond || 0) === (b.cond || 0) && TRACKS.semis(a.off || 0, a) === TRACKS.semis(b.off || 0, b) &&
    JSON.stringify(a.cut || null) === JSON.stringify(b.cut || null) && (a.xf || 0) === (b.xf || 0);

  // one row per slot of two snapshots: [{id, stem, a, b, kind}], kind one of same, change, enter, exit, empty
  BL.diffSnaps = (A, B) => {
    const ids = [...(A.order || [])];
    (B.order || []).forEach(id => { if (!ids.includes(id)) ids.push(id); });
    return ids.map(id => {
      const pa = (A.slots || {})[id], pb = (B.slots || {})[id];
      const a = BL.audible(pa) ? pa : null, b = BL.audible(pb) ? pb : null;
      const kind = a && b ? (BL.sameAudio(a, b) ? 'same' : 'change') : b ? 'enter' : a ? 'exit' : 'empty';
      const stem = (b && b.stem) || (a && a.stem) || (B.roles || {})[id] || (A.roles || {})[id] || id;
      return { id, stem, a, b, kind };
    });
  };

  // the mixer as it is now, in the shape save() writes
  BL.snapNow = () => {
    H.save();
    const sv = JSON.parse(localStorage.getItem('dcStems') || '{}');
    return { order: sv.order || [], roles: sv.roles || {}, slots: sv.slots || {}, duck: sv.duck || {} };
  };

  // has the mixer moved on from the selected snapshot? (what you set: parts, bars, pitch, volume, mute, EQ, delay, duck)
  BL.snapSig = s => JSON.stringify([(s.order || []).map(id => {
    const p = (s.slots || {})[id];
    return [(s.roles || {})[id] || id, p && (p.track != null || p.sample) ?
      [p.track, p.sample, p.steps, p.every, p.trim || null, p.warp || 0, p.fin || 0, p.fout || 0, p.bar0, p.n, p.k || 1, p.off || 0, p.ct || 0, p.db || 0, !!p.mute,
        p.eq || [0, 0, 0], p.dly || 0, p.dt || '1/8', p.fb ?? 0.35, p.eqOn !== false, p.dlyOn !== false,
        p.rev || 0, p.revOn !== false, BL.harmAmt(p), !!p.legacyLoop, ...(p.cond ? [p.cond] : []), ...(p.hk === 'oct' ? ['oct'] : []),
        ...(p.back || (p.gate && Object.keys(p.gate).length) ? ['shot', !!p.back, p.gate || {}] : []),
        ...(p.cut && p.cut.length ? ['cut', p.cut, p.xf || 0] : [])] : null];
  }), BL.duckSig(s)]);
  // Include the default setting for tracks that have never had their Duck control touched.
  BL.duckSig = (s, roles = Object.keys(BL.DUCKED), drums = true) => (s.order || []).flatMap(id => {
    const role = s.roles?.[id] || s.slots?.[id]?.stem || id;
    if (!roles.includes(role)) return [];
    const d = s.duck?.[id], entry = [id, d?.on !== false, BL.duckDb(d)];
    if (drums && role === 'other') entry.push(BL.gduckDb(d));
    return [entry];
  });
  BL.changed = () => { const MX = H.MX, i = MX.snapSel; return i != null && !!MX.snaps[i] && BL.snapSig(BL.snapNow()) !== BL.snapSig(MX.snaps[i]); };
  // edits change the mixer, not the snapshot it came from: say so, and point at ↻ (sliders don't redraw the strip)
  BL.markSnap = () => { const b = document.getElementById('snrep'), n = document.getElementById('snnote'); if (!b) return;
    const d = BL.changed(), L = BL.LETTERS[H.MX.snapSel];
    b.classList.toggle('dirty', d); b.textContent = `↻ replace ${L}${d ? ' •' : ''}`;
    if (n) n.textContent = d ? `the mixer has changed since ${L}: ↻ keeps the change in ${L}, 📸 makes it a new snapshot` : ''; };

  BL.capture = async () => {
    const MX = H.MX;
    if (MX.snaps.length >= BL.MAX_SNAPS) { toast('8 snapshots at most: delete one first'); return false; }
    if (!MX.order.some(id => BL.audible(MX.slots[id]))) { toast('nothing to snapshot yet: 🎲 a part first'); return false; }
    if (MX.key === '' && MX.info && MX.info.key) MX.key = MX.info.key;   // the auto key is frozen
    const prev = MX.snaps[MX.snaps.length - 1], snap = BL.snapNow();
    MX.snaps.push(snap); BL.fixTrans(MX); MX.snapSel = MX.snaps.length - 1;
    const ids = prev ? BL.diffSnaps(prev, snap).filter(r => r.kind === 'change' || r.kind === 'enter').map(r => r.id)
      : snap.order.filter(id => BL.audible(snap.slots[id]));
    ids.forEach(id => H.ev('snap', id));
    H.save(); H.draw();
    return true;
  };

  // bring a snapshot back into the mixer, as opening a saved combination does
  BL.recall = async i => {
    const MX = H.MX, s = MX.snaps[i]; if (!s) return;
    // what's in the mixer now is replaced: if it isn't kept in any snapshot, it would be gone, so it can be undone
    const before = BL.snapNow(), sigB = BL.snapSig(before),
      lost = before.order.some(id => (before.slots[id] || {}).track != null) && !MX.snaps.some(x => BL.snapSig(x) === sigB);
    const was = MX.on; if (was) H.play(false);
    const put = async (st, sel) => {
      MX.order.forEach(H.retire);
      MX.order = copy(st.order); MX.roles = copy(st.roles); MX.slots = copy(st.slots); MX.duck = copy(st.duck || {});
      MX.info = null; MX.snapSel = sel;
      await H.sync();
      MX.order.forEach(H.apply);
    };
    await put(s, i);
    if (was) H.play(true);
    if (lost) {
      const t = document.getElementById('toast');
      t.innerHTML = `snapshot ${BL.LETTERS[i]} is back in the mixer; what was there wasn't in any snapshot <button id="snundo">undo</button>`;
      t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 15000);
      document.getElementById('snundo').onclick = async () => {
        t.hidden = true; const on = MX.on; if (on) H.play(false);
        await put(before, null); if (on) H.play(true); H.draw();
      };
    }
  };

  BL.replace = i => { const MX = H.MX; if (!MX.snaps[i]) return; MX.snaps[i] = BL.snapNow(); H.save(); H.draw(); };

  BL.remove = i => {
    const MX = H.MX; if (!MX.snaps[i]) return;
    MX.snaps.splice(i, 1);
    MX.trans.splice(Math.min(i, MX.trans.length - 1), 1);
    if (i > 0 && i < MX.snaps.length) MX.trans[i - 1] = { bars: 8, layers: {} };   // its two neighbours are a new pair
    BL.fixTrans(MX); MX.snapSel = null; H.save(); H.draw();
  };

  // the strip above the slots
  BL.stripHTML = () => {
    const MX = H.MX, n = MX.snaps.length, sel = MX.snapSel, L = BL.LETTERS;
    const label = i => {
      if (!i) return '<span class="sub">start</span>';
      const d = BL.diffSnaps(MX.snaps[i - 1], MX.snaps[i]).filter(r => r.kind !== 'same' && r.kind !== 'empty');
      return d.length ? d.map(r => `<span class="sndot" style="--c:var(${BL.STEMVAR[r.stem] || '--mute'})"></span>${r.stem}`).join('') : '<span class="sub">same</span>';
    };
    return `<div class="snbar" id="snbar"><span class="snlab">snapshots</span>${MX.snaps.map((s, i) =>
      `${i ? '<span class="snsep">›</span>' : ''}<button class="snchip${sel === i ? ' on' : ''}" data-sn="${i}" title="bring snapshot ${L[i]} back into the mixer"><b>${L[i]}</b>${label(i)}</button>`).join('')}
     ${sel != null && sel < n ? `<button class="tbtn" id="snrep" title="write what is playing now over snapshot ${L[sel]}">↻ replace ${L[sel]}</button><button class="tbtn" id="sndel" title="delete snapshot ${L[sel]}">🗑</button>` : ''}
     <button class="tbtn" id="sncap" title="keep every slot as it is now, as the next snapshot">📸 snapshot</button><span class="sub" id="snnote"></span><span style="flex:1"></span>
     ${n ? '<span class="sub">tempo and key belong to the strip</span>' : ''}<button class="pill" id="snplay" title="play the snapshots side by side and move from one to the next" ${n < 2 ? 'disabled' : ''}>▶ play strip</button></div>`;
  };

  // ---------------------------------------------------------------- transitions (pure: they never write to MX)

  // the settings of the transition between snaps[i] and snaps[i + 1], for every layer that differs. A layer with no
  // setting here takes the nearest earlier transition's stored one for that slot, else filter handoff over it all.
  BL.transFor = (MX, i, rows) => {
    rows = rows || BL.diffSnaps(MX.snaps[i], MX.snaps[i + 1]);
    const tr = MX.trans || [], own = tr[i] || {}, layers = {};
    for (const r of rows) {
      if (r.kind !== 'change' && r.kind !== 'enter' && r.kind !== 'exit') continue;
      let found = null;
      for (let j = i; j >= 0 && !found; j--) { const e = ((tr[j] || {}).layers || {})[r.id]; if (e && typeof e === 'object') found = e; }
      layers[r.id] = found ? { style: BL.STYLES.includes(found.style) ? found.style : 'filter', win: BL.WINS[found.win] ? found.win : 'all' }
        : { style: 'filter', win: 'all' };
    }
    return { bars: BL.BARS.includes(own.bars) ? own.bars : 8, layers };
  };

  // where a row is for the master at m: a row that does not differ follows the master; a layer ridden by hand
  // stays where the hand left it
  BL.rowPos = (row, m, T, hand) => {
    if (row.kind === 'same' || row.kind === 'empty') return m;
    const h = (hand || {})[row.id];
    if (h !== null && h !== undefined) return h;
    return BL.layerPos(m, ((T.layers || {})[row.id] || {}).win);
  };

  // the mix of a layer that stays, at m: volume, EQ and delay glide; the delay's note value flips halfway
  BL.lerpMix = (a, b, m, hc) => {
    const L = (x, y) => x + (y - x) * m, eq = p => p.eqOn === false ? [0, 0, 0] : (p.eq || [0, 0, 0]),
      dly = p => p.dlyOn === false ? 0 : (p.dly || 0), rv = p => p.revOn === false ? 0 : (p.rev || 0), ea = eq(a), eb = eq(b);
    return { db: L((a.db || 0) + BL.legacyHarmDb(a, hc), (b.db || 0) + BL.legacyHarmDb(b, hc)), eq: [0, 1, 2].map(k => L(ea[k] || 0, eb[k] || 0)), dly: L(dly(a), dly(b)), rev: L(rv(a), rv(b)), revOn: true,
      hk: (m < 0.5 ? a : b).hk, dt: (m < 0.5 ? a.dt : b.dt) || '1/8', fb: L(a.fb ?? 0.35, b.fb ?? 0.35), harm: L(BL.harmAmt(a), BL.harmAmt(b)), eqOn: true, dlyOn: true, mute: false };
  };

  // ---------------------------------------------------------------- playing the strip

  // two snapshots side by side: snaps[i] on the left, snaps[i + 1] on the right, and the sound moving between them
  const PB = {
    on: false, playing: false, ready: false, nextReady: true,
    i: 0, m: 0, hand: {}, auto: false, hold: 8,
    rows: [], T: null, info: [{}, {}], missing: {}, t0: 0,
    cache: new Map(),   // buffer key -> Promise<AudioBuffer>
    voices: new Map(),  // slot id + '|' + buffer key -> voice
    seq: 0,             // which load is the current one
  };

  const PITCHED_STEMS = new Set(['bass', 'vocals', 'other']);
  const fmtDb = x => (x < 0 ? '−' : '') + Math.abs(Math.round(x * 10) / 10);

  // what the server says about one snapshot's audible parts: their shift, source tempo and key
  const infoOf = async snap => {
    const MX = H.MX, slots = {};
    (snap.order || []).forEach(id => {
      const p = (snap.slots || {})[id];
      if (BL.audible(p)) slots[id] = { stem: p.stem, track: p.track, bar0: p.bar0, n: p.n, k: p.k || 1, off: p.off || 0 };
    });
    if (!Object.keys(slots).length) return { slots: {} };
    try { return await window.CRATE.api('api/stems/info', { state: { bpm: MX.bpm, key: MX.key || null, slots } }); }
    catch (e) { return null; }   // no answer at all: not the same as "this song is no longer prepared"
  };
  const semisOf = (info, id) => (((info || {}).slots || {})[id] || {}).semis || 0;
  const keyOf = (p, semis) => [p.track, p.stem, p.bar0, p.n, p.k || 1, H.MX.bpm, TRACKS.semis(semis, p), !!p.legacyLoop, !!p.kit, p.cond || 0].join('|');
  // a part's audio at the mixer's tempo, rendered by the server once and shared
  const bufferOf = (key, p, semis) => {
    if (!PB.cache.has(key)) {
      const pr = (async () => {
        const r = await window.CRATE.api('api/stems/render', { track: p.track, stem: p.stem, bar0: p.bar0, n: p.n, k: p.k || 1, bpm: H.MX.bpm, semis: TRACKS.semis(semis, p), legacy: !!p.legacyLoop, cond: p.cond, cut: p.cut && p.cut.length ? p.cut : undefined, xf: p.xf || undefined });
        const ab = await (await fetch(url(r.url))).arrayBuffer();
        return await AC.decodeAudioData(ab);
      })();
      pr.catch(() => { if (PB.cache.get(key) === pr) PB.cache.delete(key); });   // a failure is tried again next time
      PB.cache.set(key, pr);
    }
    return PB.cache.get(key);
  };

  const startVoice = v => {
    if (v.src || !v.buf) return;
    const when = AC.currentTime + 0.03, src = AC.createBufferSource(), g = AC.createGain(), d = v.buf.duration;
    src.buffer = v.buf; src.loop = true; src.connect(g); g.connect(v.xf.in);
    g.gain.setValueAtTime(0, when); g.gain.linearRampToValueAtTime(1, when + 0.012);
    src.start(when, (((when - PB.t0) % d) + d) % d);
    v.src = src; v.g = g; v.t = when;
  };
  const stopVoice = (v, t) => {
    if (!v.src) return;
    t = t || AC.currentTime;
    try { v.g.gain.setTargetAtTime(0, t, 0.006); v.src.stop(t + 0.05); } catch (e) { }
    v.src = null; v.g = null;
  };
  const dropVoice = v => {
    stopVoice(v);
    setTimeout(() => { try { v.chain.drop(); v.xf.out.disconnect(); } catch (e) { } }, 150);   // after the fade
  };
  const newVoice = (id, { key, buf, measures }) => {
    const MX = H.MX; BL.out(MX, AC);
    const xf = BL.mkXf(AC), chain = BL.mkChain(AC, MX.master, MX.bus);
    xf.out.connect(chain.in);
    return { id, key, buf, measures, xf, chain, src: null, g: null, t: 0, set: null };
  };

  // make snaps[i] and snaps[i + 1] the pair that plays. true: loaded; false: the server did not answer, and the
  // pair that was playing is left as it was; null: a newer load or a close took over.
  PB.load = async i => {
    const MX = H.MX, my = ++PB.seq;
    PB.ready = false;
    if (MX.snaps.slice(i, i + 2).some(s => Object.values(s.slots || {}).some(p => p?.kit))) {
      await H.refreshSongs();
      if (my !== PB.seq) return null;
    }
    if (H.split()) {
      await H.sync();
      if (my !== PB.seq) return null;
    }
    const A = MX.snaps[i], B = MX.snaps[i + 1];
    if (!A || !B) return null;
    const info = await Promise.all([infoOf(A), infoOf(B)]);
    if (my !== PB.seq) return null;
    if (!info[0] || !info[1]) {
      toast(`could not load ${BL.LETTERS[i]} and ${BL.LETTERS[i + 1]}: the server did not answer, try again`);
      PB.ready = PB.rows.length > 0 && !!PB.T;   // what was playing still is
      return false;
    }
    PB.info = info; PB.missing = {};
    const sides = [copy(A), copy(B)], tag = ['a', 'b'];
    const drop = (s, id) => { PB.missing[tag[s] + ':' + id] = true; delete sides[s].slots[id]; };
    // a part whose song is no longer prepared gets no answer from the server
    sides.forEach((snap, s) => Object.keys(snap.slots || {}).forEach(id => {
      if (BL.audible(snap.slots[id]) && !((info[s].slots || {})[id])) drop(s, id);
    }));
    // every part's audio; a part whose render fails counts as missing too
    const want = [];
    BL.diffSnaps(sides[0], sides[1]).forEach(r => {
      if (r.a) want.push({ s: 0, id: r.id, p: r.a, semis: semisOf(info[0], r.id), same: r.kind === 'same' });   // a layer that stays: one voice
      if (r.b && r.kind !== 'same') want.push({ s: 1, id: r.id, p: r.b, semis: semisOf(info[1], r.id) });
    });
    want.forEach(w => { w.key = keyOf(w.p, w.semis); });
    const got = await Promise.allSettled(want.map(async w => {
      const buf = await bufferOf(w.key, w.p, w.semis);
      const parts = w.same ? [w.p, sides[1].slots[w.id]] : [w.p];
      const kinds = new Set(parts.map(BL.harmKind));
      if (parts.some(p => p.hup)) kinds.add('drive');
      const measures = {};
      await Promise.all([...kinds].map(async kind => { measures[kind] = await BL.harmMeasure(buf, kind); }));
      return { key: w.key, buf, measures };
    }));
    if (my !== PB.seq) return null;
    const bufs = {};
    want.forEach((w, k) => {
      if (got[k].status === 'fulfilled') bufs[w.s + ':' + w.id] = got[k].value;
      else { drop(w.s, w.id); if (w.same) drop(1, w.id); }
    });
    PB.rows = BL.diffSnaps(sides[0], sides[1]);
    PB.T = BL.transFor(MX, i, PB.rows);
    // voices: keep the ones still needed (they keep playing), drop the rest, make the missing ones
    const old = PB.voices, keep = new Map();
    const voiceFor = (id, b) => {
      const ident = id + '|' + b.key;
      let v = keep.get(ident) || old.get(ident);
      if (!v) v = newVoice(id, b);
      else Object.assign(v.measures, b.measures);
      keep.set(ident, v);
      return v;
    };
    for (const r of PB.rows) {
      r.va = r.vb = null;
      if (r.kind === 'empty') continue;
      const ba = bufs['0:' + r.id], bb = r.kind === 'same' ? ba : bufs['1:' + r.id];
      if (r.a && ba) r.va = voiceFor(r.id, ba);
      if (r.b && bb) r.vb = r.kind === 'same' ? r.va : voiceFor(r.id, bb);
    }
    old.forEach((v, ident) => { if (!keep.has(ident)) dropVoice(v); });
    PB.voices = keep;
    PB.used.set(i, new Set(want.filter(w => w.s === 0).map(w => w.key)));
    PB.used.set(i + 1, new Set(want.filter(w => w.s === 1 || w.same).map(w => w.key)));
    prune();
    PB.nextReady = !MX.snaps[i + 2];
    PB.ready = true;
    applyPB();
    if (PB.playing) PB.voices.forEach(startVoice);
    H.draw();
    PB.prefetch();
    return true;
  };

  // apply the whole state: every voice's blend filter and chain
  const applyPB = () => {
    if (!PB.ready || !PB.T) return;
    const t = AC.currentTime, nyq = AC.sampleRate / 2, MX = H.MX, A = MX.snaps[PB.i] || {}, B = MX.snaps[PB.i + 1] || {};
    const o = { on: true, fx: MX.fx !== false, bar: H.barLenM(), DT: H.DT };
    for (const r of PB.rows) {
      if (r.kind === 'empty') continue;
      const set = (v, x, part, duck) => {
        v.set = x;
        BL.setXf(v.xf, x, t);
        BL.applyChain(v.chain, BL.mixOf(part, part.stem || r.stem, { ...o, duck, hc: v.measures[BL.harmKind(part)] }), t);
      };
      if (r.kind === 'same') { if (r.va) set(r.va, { gain: 1, hp: 0, lp: nyq }, BL.lerpMix(r.a, r.b, PB.m, o.fx ? r.va.measures.drive : null), ((PB.m < 0.5 ? A : B).duck || {})[r.id]); continue; }
      const b = BL.blendAt(PB.T.layers[r.id].style, PB.pos(r.id), nyq);
      if (r.va) set(r.va, { gain: b.ga, hp: b.hp, lp: nyq }, r.a, (A.duck || {})[r.id]);
      if (r.vb) set(r.vb, { gain: b.gb, hp: 0, lp: b.lp }, r.b, (B.duck || {})[r.id]);
    }
  };

  PB.pos = id => { const r = PB.rows.find(x => x.id === id); return r && PB.T ? BL.rowPos(r, PB.m, PB.T, PB.hand) : null; };
  const differs = r => r.kind === 'change' || r.kind === 'enter' || r.kind === 'exit';
  PB.atEnd = side => PB.rows.filter(differs).every(r => PB.pos(r.id) === side);
  PB.voice = (id, side) => { const r = PB.rows.find(x => x.id === id); return (r && (side === 'a' ? r.va : r.vb)) || null; };

  PB.play = on => {
    if (on) {
      if (PB.playing) return;
      AC.resume(); PB.t0 = AC.currentTime + 0.05; PB.playing = true;
      PB.voices.forEach(startVoice);
    } else {
      PB.playing = false;
      PB.voices.forEach(v => stopVoice(v));
    }
  };

  PB.setMaster = m => { PB.m = BL.clamp01(m); applyPB(); PB.paint(); };
  PB.setHand = (id, p) => { PB.hand[id] = BL.clamp01(p); applyPB(); PB.paint(); };
  // a layer's entry in its transition is always the complete {style, win}
  const setLayer = (id, k, v) => {
    const MX = H.MX, tr = MX.trans[PB.i]; if (!tr || !PB.T || !PB.T.layers[id]) return;
    tr.layers[id] = { ...PB.T.layers[id], [k]: v };
    H.save(); PB.T = BL.transFor(MX, PB.i, PB.rows); applyPB(); H.draw();
  };
  PB.setStyle = (id, style) => setLayer(id, 'style', style);
  PB.setWin = (id, win) => setLayer(id, 'win', win);
  PB.setBars = n => {
    const MX = H.MX, tr = MX.trans[PB.i]; if (!tr || !BL.BARS.includes(n)) return;
    tr.bars = n; H.save(); PB.T = BL.transFor(MX, PB.i, PB.rows);
    // auto moving: the new length changes its speed from where the master is, not its position
    if (PB.auto && PB.ph && PB.ph.kind === 'move') PB.ph = { kind: 'move', from: AC.currentTime, m0: PB.m };
    applyPB(); H.draw();
  };

  PB.open = async i => {
    const MX = H.MX;
    if (MX.on) H.play(false);
    PB.on = true; PB.i = i; PB.m = 0; PB.hand = {};
    H.draw();
    await PB.load(i);
    if (!PB.on || PB.i !== i) return;
    PB.play(true); H.draw();
  };
  PB.close = () => {
    if (PB.auto) PB.setAuto(false);   // no timer outlives the view
    PB.seq++;
    PB.play(false);
    PB.voices.forEach(dropVoice); PB.voices = new Map(); PB.rows = []; PB.T = null; PB.ready = false;
    PB.cache.clear(); PB.used.clear(); PB.nextReady = true;
    PB.on = false; PB.auto = false;
    H.draw();
  };

  // where each side stands, for its label: [left, right]
  const sideWords = () => {
    const e0 = PB.atEnd(0), e1 = PB.atEnd(1);
    if (e0 && e1) return PB.m < 0.5 ? ['playing', 'next'] : ['silent', 'playing'];
    if (e0) return ['playing', 'next'];
    if (e1) return ['silent', 'playing'];
    return ['going out', 'coming in'];
  };
  // ▶ only fully on the right with the next snapshot loaded; ◀ only fully on the left
  const canNext = () => PB.ready && !!H.MX.snaps[PB.i + 2] && PB.nextReady && PB.atEnd(1);
  const canPrev = () => PB.ready && PB.i > 0 && PB.atEnd(0);
  // the arrows: [enabled, class, text] for ▶ and ◀
  const arrows = () => {
    const MX = H.MX, LT = BL.LETTERS, i = PB.i, more = !!MX.snaps[i + 2], n = canNext();
    return {
      next: [n, n ? 'pill' : 'tbtn', more ? `${LT[i + 1]} · ${LT[i + 2]} ▶` : `${LT[i + 1]} is last`],
      prev: [canPrev(), 'tbtn', i > 0 ? `◀ ${LT[i - 1]} · ${LT[i]}` : '◀'],
    };
  };

  // move the view on (dir 1: the right snapshot goes left, the next comes in) or back (dir -1). The snapshot that
  // stays keeps its voices, so it never stops sounding.
  PB.advance = async dir => {
    if (dir === 1 ? !canNext() : !canPrev()) return false;
    const was = { i: PB.i, m: PB.m, hand: PB.hand };
    PB.i += dir; PB.m = dir === 1 ? 0 : 1; PB.hand = {};
    const r = await PB.load(PB.i);
    if (r === false) {   // the pair that was playing still is: stay on it
      Object.assign(PB, was); applyPB(); H.draw();
      return false;
    }
    return r === true;
  };

  // the buffer keys each snapshot uses, as last loaded: index -> Set
  PB.used = new Map();
  // load the snapshot after the pair while the pair plays
  PB.prefetch = async () => {
    const MX = H.MX, i = PB.i, my = PB.seq, C = MX.snaps[i + 2];
    PB.nextReady = !C;
    if (!C) return;
    const info = await infoOf(C);
    if (my !== PB.seq || PB.i !== i) return;
    if (!info) { PB.nextReady = true; PB.paint(); return; }   // ▶ asks again, and says so if it still cannot load
    const keys = new Set(), work = [];
    (C.order || []).forEach(id => {
      const p = (C.slots || {})[id];
      if (!BL.audible(p) || !(info.slots || {})[id]) return;   // the server does not answer for a song no longer prepared
      const semis = semisOf(info, id), key = keyOf(p, semis);
      keys.add(key); work.push(bufferOf(key, p, semis).then(buf => BL.harmMeasure(buf, BL.harmKind(p))));
    });
    PB.used.set(i + 2, keys);
    await Promise.allSettled(work);   // a failed render counts as loaded: that part will show as missing
    if (my !== PB.seq || PB.i !== i) return;
    PB.nextReady = true; PB.paint();
  };
  // keep only the audio of the snapshots around the pair
  const prune = () => {
    const keep = new Set();
    for (let j = PB.i - 1; j <= PB.i + 2; j++) (PB.used.get(j) || []).forEach(k => keep.add(k));
    [...PB.used.keys()].forEach(j => { if (j < PB.i - 1 || j > PB.i + 2) PB.used.delete(j); });
    [...PB.cache.keys()].forEach(k => { if (!keep.has(k)) PB.cache.delete(k); });
  };
  const setArrow = (el, [on, cls, txt]) => { if (!el) return; el.disabled = !on; el.className = cls; el.textContent = txt; };

  // ---------------------------------------------------------------- auto: hold, move across, move on, again

  PB.ph = null;   // null, or {kind: 'hold' | 'move', from (audio-clock time on a bar line), m0}
  let autoTimer = 0, ticking = false;
  const barL = () => H.barLenM();
  const nextBar = () => PB.t0 + Math.ceil((AC.currentTime - PB.t0) / barL() - 1e-6) * barL();
  const moveMaster = m => { PB.m = BL.clamp01(m); applyPB(); };   // auto's own setter: it does not switch auto off
  const moveDur = ph => (1 - ph.m0) * PB.T.bars * barL();

  const tick = async () => {
    if (ticking || !PB.auto || !PB.ph || !PB.ready || !PB.T) return;   // while a pair loads, wait
    ticking = true;
    try {
      const L = barL(), now = AC.currentTime, ph = PB.ph;
      if (ph.kind === 'hold') {
        if (now >= ph.from + PB.hold * L) PB.ph = { kind: 'move', from: ph.from + PB.hold * L, m0: 0 };
      } else {
        const dur = moveDur(ph), x = dur > 0 ? (now - ph.from) / dur : (now >= ph.from ? 1 : 0);
        if (x < 1) { if (x >= 0) moveMaster(ph.m0 + (1 - ph.m0) * x); }
        else {
          moveMaster(1);
          if (!H.MX.snaps[PB.i + 2]) PB.setAuto(false);   // the last snapshot: it stays
          else if (PB.nextReady) {
            if (await PB.advance(1)) {
              // hold from where the move ended, or, after a long wait for the next snapshot, from the next bar line:
              // the hold and the transition are never skipped
              const end = ph.from + dur;
              if (PB.auto) PB.ph = { kind: 'hold', from: AC.currentTime - end > barL() / 2 ? nextBar() : end };
            } else if (PB.auto) PB.setAuto(false);   // the server did not answer (load said so): stop where it stands
          }
          // not loaded yet: try again next tick
        }
      }
      PB.paint();
    } finally { ticking = false; }
  };

  PB.setAuto = async on => {
    clearInterval(autoTimer); autoTimer = 0;
    if (!on) { PB.auto = false; PB.ph = null; PB.paint(); return; }   // in place: a slider being grabbed stays
    if (!PB.playing) PB.play(true);
    PB.hand = {}; PB.auto = true;
    if (PB.m >= 1) {
      if (!H.MX.snaps[PB.i + 2]) PB.auto = false;
      else PB.ph = { kind: 'move', from: nextBar(), m0: 1 };   // moves on at the next bar line, once the next is loaded
    } else PB.ph = PB.m <= 0 ? { kind: 'hold', from: nextBar() } : { kind: 'move', from: nextBar(), m0: PB.m };
    if (PB.auto) autoTimer = setInterval(tick, 25);
    H.draw();
  };
  PB.setHold = bars => { PB.hold = +bars > 0 ? +bars : 8; PB.paint(); };

  // the status line: where auto is
  const statText = () => {
    const ph = PB.ph; if (!PB.auto || !ph || !PB.T) return '';
    const L = barL(), now = AC.currentTime, LT = BL.LETTERS, cl = (b, n) => Math.max(1, Math.min(n, b));
    if (ph.kind === 'hold') return `holding ${LT[PB.i]} · bar ${cl(Math.floor((now - ph.from) / L) + 1, PB.hold)} of ${PB.hold}`;
    const n = PB.T.bars;
    return `moving to ${LT[PB.i + 1]} · bar ${cl(Math.floor(ph.m0 * n + (now - ph.from) / L) + 1, n)} of ${n}`;
  };

  // update the open view in place: never redraw while a slider is being dragged
  PB.paint = () => {
    if (!$('pb')) return;
    const fill = (el, p) => { el.value = Math.round(p * 100); el.style.setProperty('--a', 0); el.style.setProperty('--b', p.toFixed(4)); };
    document.querySelectorAll('#pb [data-pbpos]').forEach(el => { const p = PB.pos(el.dataset.pbpos); if (p != null) fill(el, p); });
    const m = $('pbm'); if (m) fill(m, PB.m);
    PB.rows.forEach(r => {
      const p = PB.pos(r.id), d = differs(r);
      const a = document.querySelector(`#pb [data-pbside="a"][data-pbslot="${r.id}"]`), b = document.querySelector(`#pb [data-pbside="b"][data-pbslot="${r.id}"]`);
      if (a) a.classList.toggle('off', d && p === 1);
      if (b) b.classList.toggle('off', d && p === 0);
    });
    const w = sideWords(), sides = document.querySelectorAll('#pb .pbside .sub'), lets = document.querySelectorAll('#pb .pbletter');
    if (sides[0]) sides[0].textContent = w[0];
    if (sides[1]) sides[1].textContent = w[1];
    if (lets[0]) lets[0].classList.toggle('idle', w[0] === 'silent');
    if (lets[1]) lets[1].classList.toggle('idle', w[1] === 'next');
    const ar = arrows(); setArrow($('pbnext'), ar.next); setArrow($('pbprev'), ar.prev);
    const s = $('pbstat'); if (s) s.textContent = statText();
    const au = $('pbauto'); if (au) { au.textContent = `auto ${PB.auto ? 'on' : 'off'}`; au.classList.toggle('on', PB.auto); }
  };

  // one slot's card: the part, its bars and where it comes from, and its waveform
  const cardHTML = (r, side) => {
    const MX = H.MX, s = side === 'a' ? 0 : 1, p = r[side], ICON = H.ICON || {};
    const snap = MX.snaps[PB.i + s] || {}, info = (PB.info[s] || {}).slots || {};
    const head = `<div class="pbslot" data-pbside="${side}" data-pbslot="${esc(r.id)}">`;
    if (!p) {
      const there = (snap.slots || {})[r.id], word = PB.missing[side + ':' + r.id] ? 'missing' : there && there.track != null && there.mute ? 'muted' : 'empty';
      return `${head}<div class="mxname">${ICON[r.stem] || ''} ${esc(r.stem)}</div><div class="mxsrc"><span class="sub">${word}</span></div></div>`;
    }
    const I = info[r.id] || {}, sm = I.semis || 0, last = p.bar0 + Math.max(1, Math.round(p.n * (p.k || 1)));
    const line = `bars ${p.bar0 + 1}–${last}${I.src_bpm != null ? ` · from ${I.src_bpm} bpm` : ''}${PITCHED_STEMS.has(p.stem) && I.key ? ` · ${I.key}${sm ? ` ${sm > 0 ? '+' : ''}${sm} st` : ''}` : ''}`;
    return `${head}<div class="mxname">${ICON[p.stem] || ''} ${esc(p.stem)}</div>
     <div class="mxsrc" title="${esc(p.artist || '')} — ${esc(p.title || '')}"><b>${esc(p.artist || '')}</b> — ${esc(p.title || '')}<br><span class="sub">${line}</span></div>
     <div class="mxwave" data-pbwave="${side}:${esc(r.id)}"><canvas></canvas><i></i></div></div>`;
  };
  // the column between: a layer's style, when it changes, and its own slider
  const midHTML = r => {
    if (r.kind === 'same') {
      const da = r.a.db || 0, db = r.b.db || 0;
      return `<div class="pbsame">same in both${da !== db ? `<br><span class="sub">volume glides ${fmtDb(da)} → ${fmtDb(db)} dB</span>` : ''}</div>`;
    }
    if (r.kind === 'empty') return '<div class="pbsame">empty in both</div>';
    const L = PB.T.layers[r.id], T = PB.T.bars, h = T / 2, id = esc(r.id), p = PB.pos(r.id);
    const opt = (v, txt, cur) => `<option value="${v}"${v === cur ? ' selected' : ''}>${txt}</option>`;
    const win = PB.hand[r.id] != null ? '<span class="tag hot">by hand</span>'
      : `<select data-pbwin="${id}">${opt('all', `bars 1–${T}`, L.win)}${opt('first', `bars 1–${h}`, L.win)}${opt('second', `bars ${h + 1}–${T}`, L.win)}${opt('cut', `cut at bar ${h + 1}`, L.win)}</select>`;
    return `<div class="pbx"><div class="pbxrow"><select data-pbstyle="${id}">${opt('filter', 'filter handoff', L.style)}${opt('xfade', 'crossfade', L.style)}</select>${win}</div>
     <label class="pbab"><span>A</span><input type="range" min="0" max="100" step="1" value="${Math.round(p * 100)}" data-pbpos="${id}"><span>B</span></label></div>`;
  };

  const waveCol = stem => getComputedStyle(document.documentElement).getPropertyValue(BL.STEMVAR[stem] || '').trim() || '#8cc0da';
  const pbWaves = () => document.querySelectorAll('#pb [data-pbwave]').forEach(box => {
    const [side, id] = box.dataset.pbwave.split(':'), v = PB.voice(id, side), r = PB.rows.find(x => x.id === id);
    if (!v || !v.buf || !r) return;
    const part = r[side] || r.a || r.b, c = box.querySelector('canvas'), dpr = devicePixelRatio || 1;
    const W = Math.round(box.clientWidth * dpr), Hh = Math.round(34 * dpr); if (!W) return;
    c.width = W; c.height = Hh;
    const g = c.getContext('2d'), d = v.buf.getChannelData(0), step = d.length / W, m = new Float32Array(W);
    let pk = 0;
    for (let x = 0; x < W; x++) { let q = 0; for (let k = Math.floor(x * step), e = Math.min(d.length, Math.floor((x + 1) * step)); k < e; k += 3) q = Math.max(q, Math.abs(d[k])); m[x] = q; pk = Math.max(pk, q); }
    g.fillStyle = waveCol(part.stem);
    for (let x = 0; x < W; x++) { const hh = Math.max(1, m[x] / (pk || 1) * Hh); g.fillRect(x, (Hh - hh) / 2, 1, hh); }
    g.fillStyle = 'rgba(255,255,255,.28)';
    for (let b = 1; b < part.n; b++) g.fillRect(Math.round(b / part.n * W), 0, 1, Hh);   // bar lines
  });
  let pbRaf = 0;
  const pbHeads = () => {
    pbRaf = 0;
    if (!PB.on || !PB.playing || st.tab !== 'M') return;
    document.querySelectorAll('#pb [data-pbwave]').forEach(box => {
      const [side, id] = box.dataset.pbwave.split(':'), v = PB.voice(id, side), el = box.querySelector('i');
      if (!v || !v.buf || !el) return;
      const d = v.buf.duration, x = ((AC.currentTime - PB.t0) % d + d) % d / d;
      el.style.left = (x * 100).toFixed(2) + '%'; el.style.display = 'block';
    });
    pbRaf = requestAnimationFrame(pbHeads);
  };

  // the playback view, in place of the mixer while it is open
  BL.pbDraw = L => {
    if (!PB.on) return false;
    const MX = H.MX, LT = BL.LETTERS, i = PB.i;
    const key = MX.key || (PB.info[0] || {}).key || 'auto';
    const chips = MX.snaps.map((s, k) => `${k ? '<span class="snsep">›</span>' : ''}<button class="snchip${k === i || k === i + 1 ? ' on' : ''}" data-pbsn="${k}"><b>${LT[k]}</b></button>`).join('');
    const hold = [4, 8, 16].map(n => `<option value="${n}"${n === PB.hold ? ' selected' : ''}>${n} bars</option>`).join('');
    const ready = PB.ready && PB.T, w = ready ? sideWords() : ['going out', 'coming in'], ar = arrows();
    const btn = (id, [on, cls, txt]) => `<button class="${cls}" id="${id}"${on ? '' : ' disabled'}>${txt}</button>`;
    let rows = '';
    if (ready) {
      rows = PB.rows.map(r => `<div class="pb3" data-pbrow="${esc(r.id)}">${cardHTML(r, 'a')}${midHTML(r)}${cardHTML(r, 'b')}</div>`).join('');
      const bars = [2, 4, 8, 16].map(n => `<option value="${n}"${n === PB.T.bars ? ' selected' : ''}>${n} bars</option>`).join('');
      rows += `<div class="pb3">
       <div class="sub" style="align-self:center;text-align:right">moves every layer at once</div>
       <div class="pbx pbmaster"><div class="pbxrow" style="justify-content:space-between"><b>master</b>
         <label class="sub">over <select id="pbbars" style="flex:none">${bars}</select></label></div>
        <label class="pbab"><span>A</span><input type="range" id="pbm" min="0" max="100" step="1" value="${Math.round(PB.m * 100)}"><span>B</span></label></div>
       <div class="sub" id="pbstat" style="align-self:center">${statText()}</div>
      </div>`;
    }
    L.innerHTML = `<div class="mx" id="pb">
     <div class="mxtop pbhead">
      <button id="pbback">◂ mixer</button><span class="snlab">playing the strip</span>${chips}
      <button id="pbplay" class="${PB.playing ? 'on' : ''}">${PB.playing ? '■ stop' : '▶ play'}</button><span class="sub">${MX.bpm} bpm · ${esc(key)}</span><span style="flex:1"></span>
      <button id="pbauto" class="${PB.auto ? 'on' : ''}">auto ${PB.auto ? 'on' : 'off'}</button>
      <label class="sub">hold <select id="pbhold">${hold}</select></label>
     </div>
     <div class="pbscroll"><div class="pbgrid">
      <div class="pb3" style="margin-bottom:6px">
       <div class="pbside">${btn('pbprev', ar.prev)}<b class="pbletter${w[0] === 'silent' ? ' idle' : ''}">${LT[i]}</b><span class="sub">${w[0]}</span></div>
       <div class="snlab" style="text-align:center;align-self:center">transition</div>
       <div class="pbside r"><span class="sub">${w[1]}</span><b class="pbletter${w[1] === 'next' ? ' idle' : ''}">${LT[i + 1]}</b>${btn('pbnext', ar.next)}</div>
      </div>
      ${rows}
     </div></div>
    </div>`;
    if (ready) { PB.paint(); pbWaves(); }
    if (PB.playing && !pbRaf) pbRaf = requestAnimationFrame(pbHeads);
    return true;
  };

  BL.init = hooks => {
    H = BL.H = hooks;
    if (!H.MX.duck || !H.MX.snaps) BL.adopt(H.MX, {});
    const L = $('list');
    L.addEventListener('click', e => {
      if (st.tab !== 'M') return;
      const t = e.target.closest('button'); if (!t) return;
      const ds = t.dataset;
      const MX = H.MX;
      if (ds.mxduckon) { const d = BL.duckOf(ds.mxduckon); d.on = d.on === false; H.apply(ds.mxduckon); H.save(); H.draw(); return; }
      if (t.id === 'sncap') { BL.capture(); return; }
      if (ds.sn != null) { BL.recall(+ds.sn); return; }
      if (t.id === 'snrep') { BL.replace(MX.snapSel); return; }
      if (t.id === 'sndel') { BL.remove(MX.snapSel); return; }
      if (t.id === 'snplay') { PB.open(0); return; }
      if (t.id === 'pbback') { PB.close(); return; }
      if (t.id === 'pbplay') { if (PB.playing && PB.auto) PB.setAuto(false); PB.play(!PB.playing); H.draw(); return; }
      if (t.id === 'pbauto') { PB.setAuto(!PB.auto); return; }
      // a hand switches auto off where it stands, then does what it does
      if (t.id === 'pbnext') { if (PB.auto) PB.setAuto(false); PB.advance(1); return; }
      if (t.id === 'pbprev') { if (PB.auto) PB.setAuto(false); PB.advance(-1); return; }
    });
    L.addEventListener('input', e => {
      if (st.tab !== 'M') return;
      const t = e.target, ds = t.dataset || {};
      // read the hand's value first: switching auto off repaints the sliders
      if (t.id === 'pbm') { const v = +t.value / 100; if (PB.auto) PB.setAuto(false); PB.setMaster(v); return; }
      if (ds.pbpos) { const v = +t.value / 100; if (PB.auto) PB.setAuto(false); PB.setHand(ds.pbpos, v); return; }
    });
    L.addEventListener('change', e => {
      if (st.tab !== 'M') return;
      const t = e.target, ds = t.dataset || {};
      if (ds.pbpos) { H.draw(); return; }   // the "by hand" tag appears
      if (ds.pbstyle) { PB.setStyle(ds.pbstyle, t.value); return; }
      if (ds.pbwin) { PB.setWin(ds.pbwin, t.value); return; }
      if (t.id === 'pbbars') { PB.setBars(+t.value); return; }
      if (t.id === 'pbhold') { PB.setHold(+t.value); return; }
    });
    window.CRATE.PB = BL.pb = PB;
  };

  window.BLEND = BL;
})();
// ---------- end of stem blends
// ---------- Mashup tracks: loop, waveform and controls
(() => {
  const TR = {};
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const step = k => k === 2 ? 2 : 1;
  const nOf = (s, k) => s / k;

  TR.MAXN = 16;
  TR.srcBars = (n, k = 1) => Math.max(1, Math.round(n * k));
  TR.floorBar = (bars, t) => {
    let lo = 0, hi = bars.length - 1;
    while (hi - lo > 1) {
      const mid = Math.floor((lo + hi) / 2);
      if (bars[mid] <= t) lo = mid;
      else hi = mid;
    }
    return lo;
  };
  TR.nearLine = (bars, t) => {
    const i = TR.floorBar(bars, t);
    return t - bars[i] < bars[i + 1] - t ? i : i + 1;
  };
  const snapped = (length, available, k) => {
    const stride = step(k);
    const limit = Math.min(TR.MAXN * k, Math.floor(available / stride) * stride);
    return clamp(Math.round(length / stride) * stride, Math.min(stride, available), limit || available);
  };
  TR.resizeEnd = (p, line, nb) => {
    const k = p.k || 1, bar0 = clamp(p.bar0, 0, nb - 1);
    const s = snapped(line - bar0, nb - bar0, k);
    return { bar0, n: Math.max(1, nOf(s, k)) };
  };
  TR.resizeStart = (p, line, nb) => {
    const k = p.k || 1, end = Math.min(nb, p.bar0 + TR.srcBars(p.n, k));
    const s = snapped(end - line, end, k);
    return { bar0: end - s, n: Math.max(1, nOf(s, k)) };
  };
  TR.moveTo = (p, bar, nb) => {
    const k = p.k || 1;
    const n = clamp(p.n, 1, Math.min(TR.MAXN, Math.floor(nb / k)));
    return { bar0: clamp(bar, 0, nb - TR.srcBars(n, k)), n };
  };
  TR.nudge = (p, d, nb) => TR.moveTo(p, p.bar0 + d * step(p.k), nb);
  TR.grow = (p, d, nb) => TR.resizeEnd(p, p.bar0 + TR.srcBars(p.n, p.k) + d * step(p.k), nb);
  TR.hit = (xa, xb, px) => {
    const a = Math.abs(px - xa), b = Math.abs(px - xb);
    if (b <= 7 && b <= a) return 'end';
    if (a <= 7) return 'start';
    return px > xa && px < xb ? 'move' : 'out';
  };
  TR.pan = (v0, v1, dt, dur) => {
    const w = Math.min(v1 - v0, dur), a = clamp(v0 + dt, 0, dur - w);
    return [a, a + w];
  };
  TR.zoom = (v0, v1, at, f, dur, minSpan) => {
    const w = v1 - v0, span = clamp(w * f, Math.min(minSpan, dur), dur);
    const a = v0 + at * (w - span);
    return TR.pan(a, a + span, 0, dur);
  };
  TR.loopView = (a, b, barLen, dur) => {
    const pad = Math.max(barLen * 2, b - a);
    return [Math.max(0, a - pad), Math.min(dur, b + pad)];
  };
  TR.barsText = p => {
    if (p.cut && p.cut.length) {
      const total = p.cut.reduce((t, c) => t + TR.pieceBars(c), 0) / (p.k || 1);
      return `${p.cut.length} piece${p.cut.length === 1 ? '' : 's'} · ${Number(total.toFixed(2))} bar${total === 1 ? '' : 's'}`;
    }
    const s = Math.min(TR.srcBars(p.n, p.k), (p.bars || Infinity) - p.bar0);
    const bars = s === 1 ? `bar ${p.bar0 + 1}` : `bars ${p.bar0 + 1}–${p.bar0 + s}`;
    return `${bars} · ${p.n} bar${p.n === 1 ? '' : 's'}`;
  };
  TR.semis = (keySemis, p) => keySemis + (p.ct || 0) / 100;

  let H;
  const field = (name, min, max, step, def, unit, after = 'apply') => ({
    min, max, step, def, unit, after,
    get: p => p[name] ?? def,
    put: (p, id, v) => { p[name] = v; },
  });
  TR.P = {
    st: field('off', -12, 12, 1, 0, 'st', 'sync'),
    ct: field('ct', -50, 50, 1, 0, 'ct', 'sync'),
  };
  const signed = v => (v > 0 ? '+' : '') + v;
  const notes = ['1/4', '1/8', '3/16', '1/16'];
  TR.fmt = (key, v) => {
    switch (TR.P[key].unit) {
      case 'st': return signed(v) + ' st';
      case 'ct': return signed(v) + ' ct';
      case 'db': return (v > 0 ? '+' : '') + v.toFixed(1) + ' dB';
      case 'cut': return v.toFixed(1) + ' dB';
      case 'pct': return v + ' %';
      case 'note': return notes[v];
      case 's': return Number(v.toFixed(2)) + ' s';
      case 'hz': return v >= 1000 ? Number((v / 1000).toFixed(2)) + ' kHz' : v + ' Hz';
      default: return String(v);
    }
  };
  const numberLabel = { st: 'semitones', ct: 'cents' };
  const paintNumber = (el, key, v) => {
    const text = TR.fmt(key, v);
    el.querySelector('output').textContent = text;
    el.style.cssText = level(key, v);
    el.setAttribute('aria-valuenow', v);
    el.setAttribute('aria-valuetext', text);
    if (key === 'harm') el.closest('.trdev').classList.toggle('mxoff', H.MX.fx === false || v === 0);
  };
  // where a value sits in its range, as a thin line under the number (from the middle for ± values)
  const level = (key, v) => {
    const spec = TR.P[key], f = clamp((v - spec.min) / (spec.max - spec.min), 0, 1) * 100;
    if (spec.unit === 'note') return '';
    const z = spec.min < 0 ? clamp(-spec.min / (spec.max - spec.min), 0, 1) * 100 : 0;
    return `--a:${Math.min(z, f).toFixed(1)}%;--w:${Math.abs(f - z).toFixed(1)}%`;
  };
  TR.num = (id, key, label) => {
    const p = H.part(id), spec = TR.P[key], v = spec.get(p, id), text = TR.fmt(key, v);
    const name = numberLabel[key] || label;
    return `<span class="trnum" tabindex="0" role="spinbutton" aria-label="${name}" aria-valuemin="${spec.min}" aria-valuemax="${spec.max}" aria-valuenow="${v}" aria-valuetext="${text}" data-v="${id}:${key}" style="${level(key, v)}" title="${name} · drag up or right for more (hold ⇧ for fine) · click to type a value · ↑ ↓ step · double-click to reset">${label ? `<span>${label}</span>` : ''}<output>${text}</output></span>`;
  };
  TR.refresh = (root = document) => {
    root.querySelectorAll('[data-v]').forEach(el => {
      const [id, key] = el.dataset.v.split(':'), p = H.part(id);
      if (p && TR.P[key]) paintNumber(el, key, TR.P[key].get(p, id));
    });
  };
  const stepped = (spec, v) => clamp(Math.round(v / spec.step) * spec.step, spec.min, spec.max);
  TR.set = (id, key, value) => {
    const p = H.part(id), spec = TR.P[key];
    if (!p || !spec || !Number.isFinite(value)) return;
    const v = stepped(spec, value);
    if (spec.after === 'sync' && v === spec.get(p, id)) return;
    spec.put(p, id, v);
    let pending;
    if (spec.after === 'sync') {
      H.pitch(id);
      if (!H.isOS(id) || p.warp) {
        p._loading = true;
        pending = H.sync();
      } else pending = H.refreshShot(id);
    } else H.apply(id);
    H.save();
    H.mark();
    TR.refresh();
    return pending;
  };
  TR.init = hooks => {
    H = hooks;
    const list = $('list');
    menus(list);
    loopControls(list);
    viewControls(list);
    let drag, typeT;
    const number = e => e.target.closest('[data-v]');
    // type a value into a number: Enter or leaving the field sets it, Esc leaves it as it was
    const type = (id, key) => {
      const el = list.querySelector(`[data-v="${CSS.escape(id + ':' + key)}"]`), p = H.part(id), spec = TR.P[key];
      if (!el || !p || el.querySelector('input')) return;
      const out = el.querySelector('output'), box = document.createElement('input');
      box.type = 'text'; box.inputMode = 'decimal'; box.className = 'trtype'; box.value = String(spec.get(p, id));
      box.setAttribute('aria-label', el.getAttribute('aria-label'));
      out.hidden = true; el.appendChild(box); box.focus(); box.select();
      let done = false;
      const close = commit => {
        if (done) return;
        done = true;
        const v = parseFloat(box.value.replace(',', '.').replace(/[^0-9.+-]/g, ''));
        box.remove(); out.hidden = false;
        if (commit && Number.isFinite(v) && H.part(id) === p) TR.set(id, key, v);
      };
      box.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Enter') close(true);
        else if (e.key === 'Escape') close(false);
      });
      box.addEventListener('blur', () => close(true));
    };
    TR.type = type;
    list.addEventListener('pointerdown', e => {
      const el = number(e);
      if (!el || e.button !== 0 || e.target.closest('input')) return;
      const [id, key] = el.dataset.v.split(':'), spec = TR.P[key], p = H.part(id);
      if (!p || !spec) return;
      e.preventDefault();
      el.focus({ preventScroll: true });
      const v = spec.get(p, id);
      drag = { el, id, key, spec, p, pointer: e.pointerId, x: e.clientX, y: e.clientY, raw: v, start: v, v, moved: false, far: 0 };
    });
    window.addEventListener('pointermove', e => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const d = drag, dy = (d.y - e.clientY) + (e.clientX - d.x);   // up or right: more
      d.y = e.clientY; d.x = e.clientX;
      if (!dy) return;
      d.far += Math.abs(dy);
      if (d.far < 3) return;                                          // a click, not a drag
      d.moved = true;
      // the whole range takes 220 px (never finer than a step every 3 px); ⇧ is five times finer
      const span = Math.max(220, 3 * (d.spec.max - d.spec.min) / d.spec.step) * (e.shiftKey ? 5 : 1);
      d.raw = clamp(d.raw + dy * (d.spec.max - d.spec.min) / span, d.spec.min, d.spec.max);
      const v = stepped(d.spec, d.raw);
      if (d.v === v) return;
      d.v = v;
      if (d.spec.after === 'apply' && H.part(d.id) === d.p) {
        d.spec.put(d.p, d.id, v);
        H.apply(d.id);
      }
      paintNumber(d.el, d.key, v);
    });
    const finish = e => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const d = drag;
      drag = null;
      if (e.type === 'pointerup' && d.moved && H.part(d.id) === d.p) TR.set(d.id, d.key, d.v);
      else if (e.type === 'pointerup' && !d.moved && d.spec.unit !== 'note') {
        // a click: type the value (a moment later, so a double-click still resets)
        clearTimeout(typeT);
        typeT = setTimeout(() => type(d.id, d.key), 280);
      } else {
        if (d.moved && d.spec.after === 'apply' && H.part(d.id) === d.p) {
          d.spec.put(d.p, d.id, d.start);
          H.apply(d.id);
        }
        TR.refresh();
      }
    };
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    list.addEventListener('keydown', e => {
      const el = number(e);
      if (!el || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
      const [id, key] = el.dataset.v.split(':'), spec = TR.P[key], p = H.part(id);
      e.preventDefault();
      e.stopPropagation();
      if (p && spec) TR.set(id, key, spec.get(p, id) + spec.step * (e.key === 'ArrowUp' ? 1 : -1));
    });
    list.addEventListener('dblclick', e => {
      const el = number(e);
      if (!el) return;
      clearTimeout(typeT);
      const [id, key] = el.dataset.v.split(':');
      TR.set(id, key, TR.P[key].def);
    });
  };

  const percent = (name, scale, max = 100, def = 0) => ({
    ...field(name, 0, max, 1, def, 'pct'),
    get: p => Math.round((p[name] ?? def * scale) / scale),
    put: (p, id, v) => { p[name] = v * scale; },
  });
  const eqBand = i => ({
    ...field('eq', -12, 12, 0.5, 0, 'db'),
    get: p => p.eq?.[i] ?? 0,
    put: (p, id, v) => { (p.eq ||= [0, 0, 0])[i] = v; },
  });
  Object.assign(TR.P, {
    g0: eqBand(0),
    g1: eqBand(1),
    g2: eqBand(2),
    dt: {
      ...field('dt', 0, 3, 1, 1, 'note'),
      get: p => Math.max(0, notes.indexOf(p.dt || '1/8')),
      put: (p, id, v) => { p.dt = notes[v]; },
    },
    fb: percent('fb', 0.01, 90, 35),
    dly: percent('dly', 0.008),
    rev: percent('rev', 0.01),
    harm: { ...percent('harm', 0.01), get: p => Math.round(BLEND.harmAmt(p) * 100) },
    duck: {
      ...field('duck', 0, BLEND.DUCK.max, 0.5, BLEND.DUCK.db, 'cut'),
      get: (p, id) => BLEND.duckDb(H.MX.duck[id]),
      put: (p, id, v) => { BLEND.duckOf(id).db = v; },
    },
    gduck: {
      ...field('gduck', 0, BLEND.GDUCK.max, 0.5, BLEND.GDUCK.db, 'cut'),
      get: (p, id) => BLEND.gduckDb(H.MX.duck[id]),
      put: (p, id, v) => { BLEND.duckOf(id).ddb = v; },
    },
  });
  TR.fxHTML = id => {
    const p = H.part(id), fx = H.MX.fx !== false;
    const device = (key, body, on = true) => `<div class="trdev${on ? '' : ' mxoff'}" data-dev="${key}">${body}</div>`;
    const toggle = (key, label, on, title = `${label} on / off`) => `<button type="button" class="trtoggle" data-mx${key}="${id}" aria-pressed="${on}" title="${title}">${label}</button>`;
    const num = (key, label) => TR.num(id, key, label);
    const eq = device('eq', toggle('eqon', 'EQ', p.eqOn !== false) +
      num('g0', 'lo') + num('g1', 'mid') + num('g2', 'hi'), fx && p.eqOn !== false);
    const dly = device('dly', toggle('dlyon', 'Delay', p.dlyOn !== false) +
      num('dt', 'time') + num('fb', 'feedback') + num('dly', 'amount'), fx && p.dlyOn !== false);
    const rev = device('rev', toggle('revon', 'Reverb', p.revOn !== false) +
      num('rev', 'amount'), fx && p.revOn !== false);
    const octave = toggle('hk', 'Octave', p.hk === 'oct',
      'Add the octave above the lows. Switch off for the driven sound and higher overtones that carry on small speakers.');
    let tail;
    if (H.isOS(id)) {
      const harmOn = BLEND.harmAmt(p) > 0;
      const expanded = H.MX.trimOpen === id;
      tail = device('harm', toggle('harm', 'Harmonics', harmOn) + octave, fx && harmOn);
      tail += device('trim', `<span>Trim</span><canvas class="mxtrim" data-mxtrim="${id}" title="drag to choose the piece that plays · drag an edge to adjust · double-click for the whole sample"></canvas>
        <output data-mxtrimlen="${id}"></output><button type="button" class="tbtn trfine" data-mxtrimopen="${id}" aria-expanded="${expanded}" title="trim, fade and warp the sample">Shape</button>`);
    } else {
      tail = device('harm', '<span class="trfxlabel">Harmonics</span>' + num('harm', 'amount') + octave, fx && BLEND.harmAmt(p) > 0);
      const role = H.role(id);
      if (role === 'bass') {
        const even = !!p.cond;
        tail += device('even', toggle('even', 'Even', even,
          'Hold stray peaks, ease heavy sub and match loudness by ear. Renders the bass again.'), even);
      }
      const duckLabel = BLEND.DUCKED[role];
      if (duckLabel) {
        const on = H.MX.duck[id]?.on !== false;
        tail += device('duck', toggle('duckon', 'Duck', on) + num('duck', duckLabel) +
          (role === 'other' ? num('gduck', 'drums') : ''), on);
      }
    }
    return `<div class="trfx">${eq}${dly}${rev}${tail}</div>`;
  };

  // the die: a solid face in the button's colour, five pips cut out of it
  TR.DIE = '<svg class="die" viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><rect x="1.5" y="1.5" width="17" height="17" rx="4.2" fill="currentColor"/><g fill="#12151a"><circle cx="6.2" cy="6.2" r="1.7"/><circle cx="13.8" cy="6.2" r="1.7"/><circle cx="10" cy="10" r="1.7"/><circle cx="6.2" cy="13.8" r="1.7"/><circle cx="13.8" cy="13.8" r="1.7"/></g></svg>';
  TR.name = role => ({ drums: 'Drums', tops: 'Tops', bass: 'Bass', vocals: 'Vocals', other: 'Other', oneshot: 'One-shot' })[role];
  let menuId = null;
  TR.isOpen = id => menuId === id;
  TR.more = (id, roles, back) => {
    const p = H.part(id), filled = p && (p.track != null || p.sample), os = H.isOS(id);
    const item = (key, label, attrs = '') => `<button type="button" data-mx${key}="${id}" ${attrs}>${label}</button>`;
    return `<button type="button" class="tbtn" data-trmore="${id}" aria-label="Track options" aria-expanded="${TR.isOpen(id)}" title="track options">⋯</button>
      <div class="trmenu">
        ${item('find', os ? 'Choose a sample' : 'Choose the song')}
        ${filled && !os ? item('alt', 'Other takes') : ''}
        ${filled && !os ? item('shot', 'Play it as a one-shot') : ''}
        ${filled && !os ? item('splice', 'Splice pieces…') : ''}
        ${filled ? item('lock', 'Keep on “all”', `aria-pressed="${!!p.lock}"`) : ''}
        ${filled ? item('dup', 'Duplicate') + item('del', 'Empty this track') : ''}
        ${!filled && back ? `<button type="button" data-mxhist="${id}:0">Bring back last part</button>` : ''}
        <label>Plays <select data-mxrole="${id}" aria-label="What this track plays">${roles.map(r => `<option value="${r}" ${r === H.role(id) ? 'selected' : ''}>${TR.name(r)}</option>`).join('')}</select></label>
        ${H.MX.order.length > 1 ? item('rm', 'Remove the track') : ''}
      </div>`;
  };
  const menuOpen = (row, on) => {
    menuId = on ? row.dataset.mxrow : null;
    row.classList.toggle('open', on);
    row.querySelector('[data-trmore]').setAttribute('aria-expanded', on);
  };
  TR.closeMenu = () => {
    const open = document.querySelector('.trk.open');
    if (open) menuOpen(open, false);
    else menuId = null;
  };
  TR.retainFocus = list => {
    const el = document.activeElement;
    const attr = ['data-v', 'data-mxwave', 'data-trmore'].find(name => el?.hasAttribute(name));
    if (!attr || !list.contains(el)) return () => {};
    const value = CSS.escape(el.getAttribute(attr));
    return () => list.querySelector(`[${attr}="${value}"]`)?.focus({ preventScroll: true });
  };
  const menus = list => {
    const close = row => { if (row) menuOpen(row, false); };
    list.addEventListener('click', e => {
      const more = e.target.closest('[data-trmore]'), open = list.querySelector('.trk.open');
      if (more) {
        const row = more.closest('.trk'), show = row !== open;
        close(open);
        if (show) menuOpen(row, true);
      } else if (e.target.closest('.trmenu button')) close(open);
    });
    list.addEventListener('change', e => {
      if (e.target.matches('[data-mxrole]')) TR.closeMenu();
    });
    document.addEventListener('pointerdown', e => {
      const open = list.querySelector('.trk.open');
      if (!open || e.target.closest('.trmenu, [data-trmore]')) return;
      close(open);
    });
    list.addEventListener('keydown', e => {
      const open = list.querySelector('.trk.open');
      if (!open || e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      close(open);
      open.querySelector('[data-trmore]').focus();
    });
  };

  const pictures = new Map();
  const pictureKey = (track, stem) => track + ':' + stem;
  TR.load = (track, stem) => {
    const key = pictureKey(track, stem);
    if (!pictures.has(key)) {
      const entry = { song: null };
      entry.pending = (async () => {
        try {
          const { url: path, rate, n, dur, bars } = await window.CRATE.api('api/stems/peaks', { track, stem });
          const response = await fetch(url(path));
          if (!response.ok) return null;
          const pk = new Uint8Array(await response.arrayBuffer());
          if (!pk.length || pk.length !== n || !(rate > 0) || !(dur > 0) || !Array.isArray(bars) || bars.length < 2) return null;
          return entry.song = { pk, rate, dur, bars };
        } catch (e) {
          return null;
        }
      })().then(song => {
        if (!song) pictures.delete(key);
        return song;
      });
      pictures.set(key, entry);
    }
    return pictures.get(key).pending;
  };
  TR.song = (track, stem) => pictures.get(pictureKey(track, stem))?.song || null;
  const slotSong = id => TR.song(H.part(id)?.track, H.role(id));
  TR.has = id => !!slotSong(id);
  TR.PIECE = ['#e0a458', '#7cc4e8', '#c79be0', '#9fd08a', '#ee8f7f', '#d8d06a'];   // a splice's pieces, in play order
  const barT = (bars, x) => { const i = clamp(Math.floor(x), 0, bars.length - 2); return bars[i] + (x - i) * (bars[i + 1] - bars[i]); };
  // where each piece comes from in the song (null for a rest)
  const cutTimes = (bars, cut) => (cut || []).map(c => c[0] == null ? null : [barT(bars, c[0]), barT(bars, Math.min(c[0] + c[1], bars.length - 1))]);
  TR.pieceBars = c => c[1] * (c[3] || 1) * (c[4] || 1);   // how long a piece plays: its bars, stretched, times its repeats
  // the stretch of the song a part takes up: its loop, or from its first piece to its last
  const spanTimes = (bars, p) => {
    const t = cutTimes(bars, p.cut).filter(Boolean);
    return t.length ? [Math.min(...t.map(q => q[0])), Math.max(...t.map(q => q[1]))] : loopTimes(bars, p);
  };
  const loopTimes = (bars, p) => {
    const from = clamp(p.bar0, 0, bars.length - 2);
    const to = Math.min(bars.length - 1, from + TR.srcBars(p.n, p.k));
    return [bars[from], bars[to]];
  };
  const surface = canvas => {
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const g = canvas.getContext('2d');
    g.scale(dpr, dpr);
    return { g, w, h, dpr };
  };
  TR.drawWave = (canvas, o) => {
    const { g, w, h, dpr } = surface(canvas), { pk, rate, bars, v0, v1, col, busy } = o;
    if (!w || !h || v1 <= v0) return;
    canvas.parentElement.classList.toggle('busy', !!busy);
    const xAt = t => (t - v0) * w / (v1 - v0);
    // a splice: its pieces lit (each numbered in the order it plays), not one loop
    const pieces = cutTimes(bars, o.cut).map(q => q && [xAt(q[0]), xAt(q[1])]);
    const tint = x => { for (let i = pieces.length - 1; i >= 0; i--) if (pieces[i] && x >= pieces[i][0] && x < pieces[i][1]) return TR.PIECE[i % TR.PIECE.length]; return null; };
    const lit = x => pieces.length ? tint(x) : x >= xa && x < xb ? col : null;
    const [a, b] = loopTimes(bars, o), xa = pieces.length ? -9 : xAt(a), xb = pieces.length ? -9 : xAt(b);
    canvas.parentElement.style.setProperty('--loop-left', xa + 'px');
    canvas.parentElement.style.setProperty('--loop-right', (xb - 2) + 'px');
    g.fillStyle = '#1a1f27';
    g.fillRect(xa, 0, xb - xa, h);
    g.font = '10px ui-monospace, Menlo, monospace';
    for (let i = TR.floorBar(bars, v0); i < bars.length && bars[i] <= v1; i++) {
      const x = xAt(bars[i]), gap = xAt(bars[i + 1]) - x;
      if (gap >= 5) {
        g.fillStyle = 'rgba(255,255,255,.07)';
        g.fillRect(x, 0, 1, h);
      }
      if (gap >= 34) {
        g.fillStyle = '#a4adba';
        g.fillText(String(i + 1), x + 4, h - 4);
      }
    }
    for (let px = 0; px < canvas.width; px++) {
      const x = px / dpr, t = v0 + x / w * (v1 - v0);
      const lo = clamp(Math.floor(t * rate), 0, pk.length - 1);
      const hi = Math.min(pk.length, Math.max(lo + 1, Math.ceil((t + (v1 - v0) / canvas.width) * rate)));
      let peak = 0;
      for (let i = lo; i < hi; i++) peak = Math.max(peak, pk[i]);
      const height = Math.max(1, peak / 255 * (h - 6));
      g.fillStyle = lit(x) || '#39404b';
      g.fillRect(x, (h - height) / 2, 1 / dpr, height);
    }
    pieces.forEach((q, i) => {   // each piece in its color, with its number in a tab above it (also when it is a sliver)
      if (!q) return;
      const c = TR.PIECE[i % TR.PIECE.length], wd = Math.max(2, q[1] - q[0]);
      g.fillStyle = 'rgba(255,255,255,.06)';
      g.fillRect(q[0], 0, wd, h);
      g.fillStyle = c;
      g.fillRect(q[0], 0, wd, 3);
      g.fillRect(q[0], 0, 1.5, h);
      g.fillRect(q[0] + wd - 1.5, 0, 1.5, h);
      g.fillRect(q[0], 0, 13, 13);
      g.fillStyle = '#111'; g.font = 'bold 10px ui-monospace, Menlo, monospace'; g.fillText(String(i + 1), q[0] + 3.5, 10);
      if (o.cut[i][2] && wd >= 30) { g.fillStyle = c; g.fillText('◀', q[0] + 17, 11); }   // played backwards
    });
    g.fillStyle = col;
    g.fillRect(xa, 0, xb - xa, 3);
    g.fillRect(xa, 0, 2, h);
    g.fillRect(xb - 2, 0, 2, h);
    if (xb - xa >= 26) {
      g.fillRect(xa, 0, 9, 11);
      g.fillRect(xb - 9, 0, 9, 11);
    }
  };
  const fallbackWave = (canvas, buffer, col) => {
    const { g, w, h } = surface(canvas), audio = buffer.getChannelData(0);
    const peaks = new Float32Array(w), step = audio.length / w;
    let max = 0;
    for (let x = 0; x < w; x++) {
      const end = Math.floor((x + 1) * step);
      for (let i = Math.floor(x * step); i < end; i += 3) peaks[x] = Math.max(peaks[x], Math.abs(audio[i]));
      max = Math.max(max, peaks[x]);
    }
    g.fillStyle = col;
    for (let x = 0; x < w; x++) {
      const amp = Math.max(1, peaks[x] / (max || 1) * h);
      g.fillRect(x, (h - amp) / 2, 1, amp);
    }
  };
  const waveBox = id => document.querySelector(`.trwave[data-mxwave="${id}"]`);
  TR.barAt = (id, clientX, half) => {
    const p = H.part(id), box = waveBox(id), song = slotSong(id);
    if (!p || !box || !song || !p._v) return null;
    const r = box.getBoundingClientRect(), t = p._v[0] + (clientX - r.left) / r.width * (p._v[1] - p._v[0]);
    const i = clamp(TR.floorBar(song.bars, t), 0, song.bars.length - 2);
    return i + (half && t >= (song.bars[i] + song.bars[i + 1]) / 2 ? 0.5 : 0);
  };
  TR.paintWave = id => {
    const p = H.part(id), box = waveBox(id);
    if (!p || !box) return;
    const canvas = box.querySelector('canvas'), col = getComputedStyle(box).getPropertyValue('--trcol').trim();
    const song = slotSong(id);
    box.classList.toggle('has-picture', !!song);
    if (song) {
      ensureView(id, song);
      const [v0, v1] = p._v;
      TR.drawWave(canvas, { ...song, bar0: p._d?.bar0 ?? p.bar0, n: p._d?.n ?? p.n, k: p.k, v0, v1, col, busy: p._busy,
        cut: p._d ? null : p.cut });
    } else if (p.buf) {
      fallbackWave(canvas, p.buf, col);
    }
  };
  TR.playhead = (id, phase) => {
    const song = slotSong(id), p = H.part(id);
    if (!song || !p._v) return phase;
    const playing = p._playingLoop?.track === p.track ? p._playingLoop : p;
    const [v0, v1] = p._v, cut = playing.cut || [], pieces = cutTimes(song.bars, cut);
    if (pieces.length) {   // a splice: through each piece in turn (again for a repeat, slower for a stretch, backwards)
      const bar = song.bars[1] - song.bars[0];
      const dur = cut.map((c, i) => (pieces[i] ? pieces[i][1] - pieces[i][0] : c[1] * bar) * (c[3] || 1) * (c[4] || 1));
      let at = phase * dur.reduce((t, d) => t + d, 0);
      for (let i = 0; i < cut.length; i++) {
        if (at <= dur[i]) {
          if (!pieces[i]) return -1;   // a rest: nothing of the song plays
          const one = dur[i] / (cut[i][4] || 1);
          let f = at >= dur[i] ? 1 : (at % one) / one;
          if (cut[i][2]) f = 1 - f;
          return (pieces[i][0] + f * (pieces[i][1] - pieces[i][0]) - v0) / (v1 - v0);
        }
        at -= dur[i];
      }
    }
    const [a, b] = loopTimes(song.bars, playing);
    return (a + phase * (b - a) - v0) / (v1 - v0);
  };

  TR.setLoop = async (id, bar0, n) => {
    const p = H.part(id), song = slotSong(id);
    const nb = song ? song.bars.length - 1 : p?.bars;
    if (!nb || H.isOS(id) || !Number.isFinite(bar0) || !Number.isFinite(n)) return;
    const next = TR.moveTo({ ...p, n: Math.round(n) }, Math.round(bar0), nb);
    if (next.bar0 === p.bar0 && next.n === p.n) return;
    const request = {};
    p._loopRequest = request;
    p._busy = false;
    const timer = setTimeout(() => {
      if (H.part(id) !== p || p._loopRequest !== request || !p._loading) return;
      p._busy = true;
      TR.paintWave(id);
    }, 150);
    try {
      const pending = H.loop(id, next.bar0, next.n);
      const label = waveBox(id)?.closest('.trk').querySelector('.trbars');
      if (label) label.textContent = TR.barsText(p);
      TR.paintWave(id);
      await pending;
    } finally {
      clearTimeout(timer);
      if (p._loopRequest === request) {
        delete p._loopRequest;
        p._busy = false;
        TR.paintWave(id);
      }
    }
  };
  const geometry = box => {
    const id = box.dataset.mxwave, p = H.part(id), song = slotSong(id);
    if (!song || !p._v) return null;
    const [v0, v1] = p._v, rect = box.getBoundingClientRect(), [a, b] = loopTimes(song.bars, p);
    const pxPerSecond = rect.width / (v1 - v0);
    const xAt = t => rect.left + (t - v0) * pxPerSecond;
    const tAt = x => v0 + (x - rect.left) / pxPerSecond;
    return { id, p, song, xAt, tAt, hit: x => TR.hit(xAt(a), xAt(b), x) };
  };
  const lineAt = (bars, t) => {
    const i = TR.floorBar(bars, t);
    return i + clamp((t - bars[i]) / (bars[i + 1] - bars[i]), 0, 1);
  };
  const cursors = { start: 'ew-resize', end: 'ew-resize', move: 'grab', out: 'pointer' };
  const loopControls = list => {
    let drag;
    list.addEventListener('pointerdown', e => {
      const box = e.target.closest('.trwave');
      if (!box || e.button !== 0 || e.target.closest('button')) return;
      const g = geometry(box);
      if (!g) return;
      const { p, song, tAt } = g, x = e.clientX, mode = g.hit(x);
      e.preventDefault();
      box.focus({ preventScroll: true });
      list.setPointerCapture(e.pointerId);
      drag = {
        ...g, x, mode, pointer: e.pointerId, moved: false,
        loop: { bar0: p.bar0, n: p.n, k: p.k }, view: p._v.slice(),
        offset: TR.floorBar(song.bars, tAt(x)) - p.bar0,
      };
    });
    window.addEventListener('pointermove', e => {
      const x = e.clientX;
      if (!drag) {
        const box = e.target.closest?.('.trwave');
        const g = box && geometry(box);
        if (g) box.style.cursor = cursors[g.hit(x)];
        return;
      }
      const d = drag;
      if (e.pointerId !== d.pointer || H.part(d.id) !== d.p) return;
      d.moved ||= Math.abs(x - d.x) > 3;
      if (!d.moved) return;
      if (d.mode === 'out') {
        const [v0, v1] = d.view;
        if (v1 - v0 < d.song.dur) TR.view(d.id, ...TR.pan(v0, v1, d.tAt(d.x) - d.tAt(x), d.song.dur));
        return;
      }
      const bars = d.song.bars, nb = bars.length - 1, t = d.tAt(x);
      if (d.mode === 'move') d.p._d = TR.moveTo(d.loop, TR.floorBar(bars, t) - d.offset, nb);
      else {
        const resize = d.mode === 'start' ? TR.resizeStart : TR.resizeEnd;
        d.p._d = resize(d.loop, lineAt(bars, t), nb);
      }
      TR.paintWave(d.id);
      const box = waveBox(d.id), tip = box?.querySelector('.trtip');
      if (!tip) return;
      const p = d.p._d, [a, b] = loopTimes(bars, { ...d.loop, ...p }), at = d.mode === 'end' ? b : a;
      tip.textContent = d.mode === 'move' ? TR.barsText({ ...d.loop, ...p }).split(' · ')[0] : `${p.n} bar${p.n === 1 ? '' : 's'}`;
      tip.hidden = false;
      tip.style.left = clamp(d.xAt(at) - box.getBoundingClientRect().left, 0, Math.max(0, box.clientWidth - tip.offsetWidth)) + 'px';
    });
    const finish = e => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const d = drag, p = d.p, bars = d.song.bars;
      drag = null;
      let next = p._d;
      delete p._d;
      if (H.part(d.id) !== p) return;
      const tip = waveBox(d.id)?.querySelector('.trtip');
      if (tip) tip.hidden = true;
      if (e.type === 'pointerup' && !d.moved && d.mode === 'out') {
        next = TR.moveTo(d.loop, TR.floorBar(bars, d.tAt(e.clientX)), bars.length - 1);
      }
      if (e.type === 'pointerup' && next) TR.setLoop(d.id, next.bar0, next.n);
      TR.paintWave(d.id);
    };
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    list.addEventListener('keydown', e => {
      if (!e.target.matches('.trwave') || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
      const g = geometry(e.target);
      if (!g) return;
      e.preventDefault();
      e.stopPropagation();
      const edit = e.shiftKey ? TR.grow : TR.nudge, d = e.key === 'ArrowLeft' ? -1 : 1;
      const next = edit(g.p, d, g.song.bars.length - 1);
      TR.setLoop(g.id, next.bar0, next.n);
    });
  };

  const firstBar = song => song.bars[1] - song.bars[0];
  // the view tracks open in: Loops unless you chose Whole song; your last choice is remembered (also after going to the
  // play strip and back, or a reload)
  const viewPreset = () => {
    if (!H.MX._viewPreset) {
      let saved = null;
      try { saved = localStorage.getItem('dcStemsView'); } catch (e) {}
      H.MX._viewPreset = saved === 'song' ? 'song' : 'loop';
    }
    return H.MX._viewPreset;
  };
  const ensureView = (id, song) => {
    const p = H.part(id), key = pictureKey(p.track, H.role(id));
    if (p._viewKey === key && !p._preset) return;
    const preset = p._preset || (!p._v ? viewPreset() : null);
    const [a, b] = spanTimes(song.bars, p);
    if (preset === 'loop') {
      p._v = TR.loopView(a, b, firstBar(song), song.dur);
      p._viewMode = 'loop';
    } else if (preset === 'song' || p._viewMode === 'song') {
      p._v = [0, song.dur];
      p._viewMode = 'song';
    } else {
      const half = (p._v[1] - p._v[0]) / 2, mid = (a + b) / 2;
      p._v = TR.pan(mid - half, mid + half, 0, song.dur);
      p._viewMode = 'custom';
    }
    delete p._preset;
    p._viewKey = key;
  };
  const viewActive = mode => {
    const tracks = H.MX.order.filter(id => H.part(id)?.track != null);
    if (!tracks.length) return mode === (viewPreset());
    return tracks.every(id => {
      const p = H.part(id);
      return (p._preset || p._viewMode || viewPreset()) === mode;
    });
  };
  const paintViewSwitch = () => {
    document.querySelectorAll('#trview button').forEach(b => {
      const on = viewActive(b.dataset.trview);
      b.setAttribute('aria-pressed', on);
    });
  };
  TR.view = (id, v0, v1) => {
    const p = H.part(id), song = slotSong(id);
    if (!song || !(v1 > v0)) return;
    ensureView(id, song);
    p._v = TR.pan(v0, v1, 0, song.dur);
    p._viewMode = p._v[0] === 0 && p._v[1] === song.dur ? 'song' : 'custom';
    TR.paintWave(id);
    paintViewSwitch();
  };
  const presetView = (id, mode) => {
    const p = H.part(id);
    if (p?.track == null) return;
    p._preset = mode;
    TR.paintWave(id);
  };
  const viewButton = (attr, mode, label, pressed = '') =>
    `<button type="button" class="tbtn" data-${attr}="${mode}" ${pressed}>${label}</button>`;
  TR.viewSwitch = () => `<span class="seg" id="trview" aria-label="Track views">
    ${viewButton('trview', 'song', 'Whole song', `aria-pressed="${viewActive('song')}"`)}
    ${viewButton('trview', 'loop', 'Loops', `aria-pressed="${viewActive('loop')}"`)}
    </span>`;
  TR.zoomButtons = `<span class="trzoom" aria-label="Waveform view">
    ${viewButton('trz', 'loop', 'Loop')}${viewButton('trz', 'song', 'Whole song')}
    </span>`;
  const viewControls = list => {
    list.addEventListener('click', e => {
      const global = e.target.closest('[data-trview]'), local = e.target.closest('[data-trz]');
      if (global) {
        H.MX._viewPreset = global.dataset.trview;
        try { localStorage.setItem('dcStemsView', H.MX._viewPreset); } catch (e) {}
        H.MX.order.forEach(id => presetView(id, H.MX._viewPreset));
      } else if (local) presetView(local.closest('.trwave').dataset.mxwave, local.dataset.trz);
      else return;
      paintViewSwitch();
    });
    list.addEventListener('wheel', e => {
      const box = e.target.closest('.trwave'), g = box && geometry(box);
      if (!g) return;
      const [v0, v1] = g.p._v, span = v1 - v0, dur = g.song.dur;
      let next;
      if (e.ctrlKey || e.metaKey) {
        const at = clamp((g.tAt(e.clientX) - v0) / span, 0, 1);
        next = TR.zoom(v0, v1, at, Math.exp(e.deltaY * 0.01), dur, 2 * firstBar(g.song));
      } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        next = TR.pan(v0, v1, e.deltaX * span / box.clientWidth, dur);
      } else return;
      e.preventDefault();
      TR.view(g.id, ...next);
    }, { passive: false });
  };

  window.TRACKS = TR;
})();
// ---------- 🎛 Mashup (the stem mixer; the tab was called Stems): drums, bass, vocals and "other" from different songs, on one tempo and key
// (digitalcrate/stems.py, docs/plans/stems.md). Parts are rendered by the server to exactly n bars at the tempo and
// looped here on one bar clock; volume, EQ and delay are live Web Audio.
{const api=(...args)=>window.CRATE.api(...args),TR=window.TRACKS,PROJ=window.PROJ||{};  // (this file's main part is one closure; what's appended after it gets its helpers from CRATE)
 const STEMS=['drums','tops','bass','vocals','other'],ROLES=[...STEMS,'oneshot'],ICON={drums:'🥁',tops:'🥢',bass:'🎸',vocals:'🎤',other:'🎹',oneshot:'✦'},PITCHED=new Set(['bass','vocals','other']);
 const F_=F;  // the library's sample fields (F is also a local name in places below)
 const isOS=id=>role(id)==='oneshot',has=p=>!!p&&(p.track!=null||!!p.sample);  // a one-shot slot plays a library sample at steps of a cycle; has: the slot holds something
 const KEYS=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'].flatMap(k=>[k,k+'m']);
 // slots have ids; MX.roles[id] is the stem a slot plays (several slots can play one stem); MX.slots[id] is its part
 const MX={bpm:PROJ.bpm||100,key:'',reverb:{type:'plate',decay:1.8},mast:{on:true,chain:null,built:0},glue:{on:true},slots:{},order:STEMS.slice(),roles:Object.fromEntries(STEMS.map(x=>[x,x])),on:false,t0:0,n:null,info:null,rated:0,recent:{},master:null};
 const role=id=>MX.roles[id]||id;
 try{MX.recent=JSON.parse(localStorage.getItem('dcStemsRecent')||'{}')||{}}catch(e){MX.recent={}}
 function adopt(sv){const ids=sv.order&&sv.order.length?sv.order:[...new Set([...STEMS,...Object.keys(sv.slots||{})])];MX.order=ids;MX.roles=Object.fromEntries(ids.map(id=>[id,(sv.roles||{})[id]||((sv.slots||{})[id]||{}).stem||(STEMS.includes(id)?id:'other')]))}
 // undo: every saved change of the mixer is a step (a drag is one step); ⌘Z / ⌘⇧Z walk them
 const UN={u:[],r:[],cur:null,t:0,busy:false};
 function undoNote(J){if(UN.busy)return;const o=JSON.parse(J);delete o.savedSig;delete o.snapsOf;delete o.name;const k=JSON.stringify(o);
  if(UN.cur===null){UN.cur=k;return}if(k===UN.cur)return;const now=performance.now();
  if(now-UN.t>600||!UN.u.length){UN.u.push(UN.cur);if(UN.u.length>100)UN.u.shift()}UN.t=now;UN.cur=k;UN.r=[]}
 const save=()=>{try{const J=JSON.stringify({v:5,bpm:MX.bpm,key:MX.key,name:MX.name||'',savedSig:MX.savedSig||null,snapsOf:MX.snapsOf||null,fx:MX.fx!==false,reverb:MX.reverb,master:{on:MX.mast.on},glue:{on:MX.glue.on},duck:MX.duck||{},snaps:MX.snaps||[],trans:MX.trans||[],order:MX.order,roles:MX.roles,slots:Object.fromEntries(MX.order.filter(s=>MX.slots[s]).map(s=>{const p=MX.slots[s];
   return [s,{stem:role(s),track:p.track,bar0:p.bar0,n:p.n,k:p.k||1,cut:p.cut&&p.cut.length?p.cut.map(c=>c.slice()):undefined,xf:p.cut&&p.cut.length&&p.xf||undefined,off:p.off||0,ct:p.ct||0,bars:p.bars,why:p.why,artist:p.artist,title:p.title,sample:p.sample,sid:p.sid,sub:p.sub,cat:p.cat,dur:p.dur,key:p.key,semis:p.semis,steps:p.steps,every:p.every,trim:p.trim||null,warp:p.warp||0,fin:p.fin||0,fout:p.fout||0,back:p.back||undefined,gate:p.gate&&Object.keys(p.gate).length?{...p.gate}:undefined,fit:p.fit,db:p.db||0,mute:!!p.mute,lock:!!p.lock,eq:p.eq||[0,0,0],dly:p.dly||0,dt:p.dt||'1/8',fb:p.fb??0.35,eqOn:p.eqOn!==false,dlyOn:p.dlyOn!==false,rev:p.rev||0,revOn:p.revOn!==false,harm:p.harm==null?null:BLEND.harmAmt(p),hup:p.hup||undefined,legacyLoop:p.legacyLoop||undefined,kit:p.kit||undefined,hk:p.hk==='oct'?'oct':undefined,cond:p.cond||undefined}]}))});localStorage.setItem('dcStems',J);undoNote(J)}catch(e){}};
 const sig=(v=5,legacyShape=false)=>JSON.stringify({bpm:MX.bpm,key:MX.key||'',fx:MX.fx!==false,reverb:[MX.reverb.type,MX.reverb.decay],duck:BLEND.duckSig(MX,v<4?['bass']:undefined,v>=5),...(MX.mast.on?{}:{master:{on:false}}),...(MX.glue.on?{}:{glue:{on:false}}),
  snaps:MX.snaps||[],trans:MX.trans||[],slots:MX.order.map(id=>{
   const p=MX.slots[id];
   if(!has(p))return [role(id),null];
   const part=[p.track,p.sample,p.steps,p.every,p.trim||null,p.bar0,p.n,p.k||1,p.off||0,p.db||0,!!p.mute,
    p.eq||[0,0,0],p.dly||0,p.dt||'1/8',p.eqOn!==false,p.dlyOn!==false,p.rev||0,p.revOn!==false];
   const shape=[p.warp||0,p.fin||0,p.fout||0];
   if(legacyShape)part.splice(5,0,...shape);
   if(v>=2){
    part.push(p.ct||0,p.fb??0.35,BLEND.harmAmt(p),!!p.legacyLoop);
    if(shape.some(Boolean))part.push(...shape);
    if(p.cond)part.push(p.cond);
    if(p.hk==='oct')part.push('oct');
    if(p.back||(p.gate&&Object.keys(p.gate).length))part.push('shot',!!p.back,p.gate||{});
    if(p.cut&&p.cut.length)part.push('cut',p.cut,p.xf||0);
   }
   return [role(id),part];
  })});
 function restore(sv){
  const {order,roles,slots,snaps,trans,duck}=sv;
  MX.mast.on=sv.master?.on!==false;BLEND.mxRoute(MX);
  MX.glue.on=sv.glue?.on!==false;MX.bus?.g?.set(MX.glue.on);
  MX.slots=slots||{};
  adopt({order,roles,slots});
  BLEND.adopt(MX,{snaps,trans,duck});
  const v=sv.v||1;
  if(v>=5)return;
  const clean=MX.savedSig&&(MX.savedSig===sig(v)||(v<2&&MX.savedSig===sig(1,true)));
  for(const mix of [MX,...MX.snaps]){
   // Before v4, a Duck setting belonged to Bass even if its slot was later reassigned.
   if(v<4)for(const id of Object.keys(mix.duck||{})){
    const r=mix.roles?.[id]||mix.slots?.[id]?.stem||id;
    if(r==='other'||r==='tops')delete mix.duck[id];
   }
   if(v>=3)continue;
   Object.entries(mix.slots||{}).forEach(([id,p])=>{
    if(p?.track==null)return;
    if((mix.roles?.[id]||p.stem||id)==='drums')p.kit=true;
    if(v>=2)return;
    // Older renders left out the last bar of a full-song loop and rounded half bars to even.
    const k=p.k||1,roundsUp=k===0.5&&p.n>1&&p.n%4===1;
    if(!p.bars||TR.srcBars(p.n,k)>=p.bars||roundsUp)p.legacyLoop=true;
    if(p.harm==null)p.hup='auto';  // wait to see whether the old mixer would have enabled harmonics
    else{
     p.harm=BLEND.harmAmt(p);
     if(p.harm)p.hup=true;
    }
   });
  }
  if(clean)MX.savedSig=sig();
 }
 // Give each migrated kit its own Tops row in the mixer and across the strip, even where the row is empty.
 function splitKits(){
  const songs=new Set((MX.songs||[]).filter(song=>song.tops).map(song=>song.track));
  const mixes=[MX,...MX.snaps], splits=[];
  for(const mix of mixes){
   for(const id of mix.order||[]){
    const p=mix.slots?.[id];
    if(p?.kit&&(mix.roles?.[id]||p.stem||id)==='drums'&&songs.has(p.track))splits.push({mix,id,p});
   }
  }
  if(!splits.length)return false;
  const clean=MX.savedSig===sig();
  const used=new Set(mixes.flatMap(mix=>mix.order||[])),companions=new Map();
  for(const id of new Set(splits.map(split=>split.id))){
   const base=id+'~tops';
   let tops=base;
   if(mixes.some(mix=>has(mix.slots?.[base])||(mix.roles?.[base]&&mix.roles[base]!=='tops'))){
    let suffix=2;
    while(used.has(base+'~'+suffix))suffix++;
    tops=base+'~'+suffix;
   }
   used.add(tops);
   companions.set(id,tops);
  }
  const fields=['track','bar0','n','k','off','ct','legacyLoop','artist','title','bars','db','mute','lock',
   'eq','eqOn','dly','dt','fb','dlyOn','rev','revOn','hk'];
  for(const {mix,id,p} of splits){
   const tops=companions.get(id);
   mix.slots[tops]={stem:'tops'};
   for(const field of fields)if(p[field]!==undefined)mix.slots[tops][field]=field==='eq'?p.eq.slice():p[field];
   delete p.kit;
   delete p._key;
  }
  for(const [id,tops] of companions){
   for(const mix of mixes){
    if(mix.order.includes(tops))continue;
    const at=mix.order.indexOf(id);
    mix.order.splice(at<0?mix.order.length:at+1,0,tops);
    mix.roles[tops]='tops';
   }
  }
  if(clean)MX.savedSig=sig();
  return true;
 }
 try{
  const sv=JSON.parse(localStorage.getItem('dcStems')||'null');
  if(sv){
   MX.bpm=sv.bpm||MX.bpm;MX.key=sv.key||'';MX.name=sv.name||'';MX.savedSig=sv.savedSig||null;
   MX.snapsOf=sv.snapsOf||null;MX.fx=sv.fx!==false;
   if(sv.reverb)MX.reverb=sv.reverb;
   restore(sv);
  }
 }catch(e){}
 const dirty=()=>MX.savedSig?sig()!==MX.savedSig:MX.order.some(id=>has(MX.slots[id]));
 function markSave(){
  const b=$('mxsave');if(!b)return;
  const d=dirty(),saving=!!MX._saving;
  b.classList.toggle('dirty',d);
  b.disabled=saving;
  b.textContent=saving?'💾 saving…':d?'💾 save •':'💾 save';
  b.title=saving?'saving this combination':d?'unsaved changes: save to keep this combination (it also counts as a strong 👍)':'saved';
  BLEND.markSnap();
 }
 const state=()=>({bpm:MX.bpm,key:MX.key||null,slots:Object.fromEntries(MX.order.filter(s=>MX.slots[s]).map(s=>[s,{stem:role(s),track:MX.slots[s].track,bar0:MX.slots[s].bar0,n:MX.slots[s].n,k:MX.slots[s].k||1,off:MX.slots[s].off||0}]))});
 const barLenM=()=>240/MX.bpm,DT={'1/4':1/4,'1/8':1/8,'3/16':3/16,'1/16':1/16};
 // audio: source -> low shelf -> mid -> high shelf -> volume -> out, and volume -> send -> delay (with feedback) -> out
 function chain(stem){const p=MX.slots[stem];if(p._c)return p._c;BLEND.out(MX,AC);return p._c=BLEND.mkChain(AC,MX.master,MX.bus)}
 function apply(stem){const p=MX.slots[stem];if(!p||!p._c)return;const solo=MX.order.some(s=>MX.slots[s]&&MX.slots[s].solo);
  BLEND.applyChain(p._c,BLEND.mixOf(p,role(stem),{on:!p.mute&&(!solo||p.solo),fx:MX.fx!==false,bar:barLenM(),DT,hc:p._hc,duck:(MX.duck||{})[stem]}),AC.currentTime)}
 function initHarm(id){
  const p=MX.slots[id];
  if(!p.buf||isOS(id))return;
  const auto=p.sub>=0.85&&p.harm==null, undecided=p.hup==='auto';
  const legacy=p._legacyHc||(p.hk!=='oct'&&p._hc);
  const upgrade=(undecided?auto:p.hup)&&legacy&&MX.fx!==false;
  if(!auto&&!upgrade&&!undecided)return;
  const clean=MX.savedSig&&!dirty(), snap=MX.snaps[MX.snapSel], saved=snap?.slots[id];
  const same=saved&&BLEND.snapSig({order:[id],slots:{[id]:p}})===BLEND.snapSig({order:[id],slots:{[id]:saved}});
  const adjust=part=>{
   if(auto)part.harm=1;
   if(upgrade){part.db=Math.min(6,(part.db||0)+BLEND.legacyHarmDb(part,legacy));delete part.hup}
   else if(part.hup==='auto'){
    if(auto)part.hup=true;
    else delete part.hup;
   }
  };
  adjust(p);
  if(same&&(!upgrade||saved.hup))adjust(saved);
  if(clean)MX.savedSig=sig();
 }
 function startSrc(stem){const p=MX.slots[stem];if(!p||!p.buf||!MX.on||isOS(stem))return;const c=chain(stem),when=AC.currentTime+0.03;stopSrc(stem,when);
  const src=AC.createBufferSource(),g=AC.createGain();src.buffer=p.buf;src.loop=true;src.connect(g);g.connect(c.in);g.gain.setValueAtTime(0,when);g.gain.linearRampToValueAtTime(1,when+0.012);
  const d=p.buf.duration;src.start(when,(((when-MX.t0)%d)+d)%d);p._s={src,g};apply(stem)}  // joins at the right place in the bar
 function stopSrc(stem,when){const p=MX.slots[stem];if(!p||!p._s)return;const t=when||AC.currentTime;try{p._s.g.gain.setTargetAtTime(0,t,0.006);p._s.src.stop(t+0.05)}catch(e){}p._s=null}
 function retire(id){
  const c=MX.slots[id]?._c;
  stopSrc(id);
  // Release the duck buses after the source fade while the delay tail rings out.
  if(c)setTimeout(()=>c.applyDucks({}),150);
 }
 // one-shots: hits scheduled a little ahead on the mixer's bar clock (16 steps a bar), each through its slot's chain
 let osT=null;const osLive=new Set();
 // one hit of a one-shot: the piece you trimmed it to (the whole sample otherwise), 3 ms in and out so a cut never clicks
 const osTrim=p=>{const t=p.trim;return t&&t[1]-t[0]>0.005?t:[0,1]};
 // what a hit plays: {buf, from, len (s of buffer), rate, out (s it sounds)}. Warped: the server stretched your piece to
 // the length you chose, pitch kept, so it plays whole at normal speed. Else your trimmed piece, at your pitch offset.
 const REVERSED=new WeakMap();  // a buffer played backwards, made once
 const reversed=buf=>{let r=REVERSED.get(buf);if(!r){r=AC.createBuffer(buf.numberOfChannels,buf.length,buf.sampleRate);for(let c=0;c<buf.numberOfChannels;c++)r.copyToChannel(buf.getChannelData(c).slice().reverse(),c);REVERSED.set(buf,r)}return r};
 // (frac: the share of the piece a hit plays, from its start: a step can play half or a quarter)
 const osPlay=(p,dry=p.buf,warped=p.wbuf,frac=1)=>{let q;
  if(warped)q={buf:warped,from:0,len:warped.duration,rate:1,out:warped.duration};
  else{const rate=2**(TR.semis(p.off||0,p)/12),[a,b]=osTrim(p),d=dry.duration;q={buf:dry,from:a*d,len:(b-a)*d,rate,out:(b-a)*d/rate}}
  if(p.back){q.from=q.buf.duration-q.from-q.len;q.buf=reversed(q.buf)}
  if(frac<1){q.len*=frac;q.out*=frac}
  return q};
 function osHit(id,p,when,frac=1){const q=osPlay(p,p.buf,p.wbuf,frac),fi=Math.min(q.out/2,Math.max(0.003,(p.fin||0)/1000)),fo=Math.min(q.out/2,Math.max(0.003,(p.fout||0)/1000));
  const src=AC.createBufferSource(),g=AC.createGain();src.buffer=q.buf;src.playbackRate.value=q.rate;src.connect(g);g.connect(p._c.in);
  g.gain.setValueAtTime(0,when);g.gain.linearRampToValueAtTime(1,when+fi);g.gain.setValueAtTime(1,when+q.out-fo);g.gain.linearRampToValueAtTime(0,when+q.out);
  src.start(when,q.from,q.len);src.onended=()=>osLive.delete(src);return src}
 function osTick(){if(!MX.on)return;const now=AC.currentTime,st=barLenM()/16;
  MX.order.forEach(id=>{const p=MX.slots[id];if(!isOS(id)||!p||!p.buf||!(p.steps||[]).length)return;
   if(!p._c){chain(id);apply(id)}const cyc=(p.n||1)*16;let k=p._next!=null?p._next:Math.ceil((now-MX.t0)/st-1e-6);
   for(;MX.t0+k*st<now+0.25;k++){if(k<0||Math.floor(k/cyc)%(p.every||1)||!p.steps.includes(k%cyc))continue;
    osLive.add(osHit(id,p,Math.max(now,MX.t0+k*st),(p.gate||{})[k%cyc]||1))}
   p._next=k})}
 function play(on){MX.on=on;clearInterval(osT);osLive.forEach(x=>{try{x.stop()}catch(e){}});osLive.clear();
  if(on){AC.resume();MX.t0=AC.currentTime+0.05;MX.order.forEach(id=>{if(MX.slots[id])MX.slots[id]._next=null});MX.order.forEach(startSrc);osT=setInterval(osTick,50);osTick()}else MX.order.forEach(s=>stopSrc(s));draw()}  // (draw starts the play lines)
 // Ask for the current parts in parallel. Only the latest sync may swap audio into a slot.
 const cutKey=p=>p&&p.cut&&p.cut.length?p.cut.map(c=>(c[0]==null?'_':c[0])+'+'+c[1]+(c[2]?'r':'')+(c[3]&&c[3]!==1?'s'+c[3]:'')+(c[4]>1?'x'+c[4]:'')).join(',')+(p.xf?'~'+p.xf:''):'';
 const renderKey=(p,bpm,semis)=>[p.track,p.bar0,p.n,p.k||1,bpm,semis,!!p.legacyLoop,p.cond||0,cutKey(p)].join('|');
 let syncing=null,syncId=0;
 async function decode(path){
  const response=await fetch(path);
  if(!response.ok)throw new Error(`audio request failed (${response.status})`);
  return AC.decodeAudioData(await response.arrayBuffer());
 }
 const shotMeasures=new WeakMap();
 const sameInput=(a,b)=>a.buf===b.buf&&a.from===b.from&&a.len===b.len&&a.rate===b.rate;
 function measureInput(input,kind){
  const {buf,from,len,rate,out}=input;
  if(from===undefined)return BLEND.harmMeasure(buf,kind);
  if(kind==='drive')return null;  // driven one-shots historically play without level compensation
  if(from===0&&len===buf.duration&&rate===1)return BLEND.harmMeasure(buf,kind);
  const cached=shotMeasures.get(buf);
  if(cached&&sameInput(input,cached.input))return cached.measure;
  // Measure the same piece at the same playback rate as the hit, before its effects.
  const measure=(async()=>{
   const ctx=new OfflineAudioContext(buf.numberOfChannels,Math.max(1,Math.ceil(out*buf.sampleRate)),buf.sampleRate);
   const source=ctx.createBufferSource();
   source.buffer=buf;source.playbackRate.value=rate;source.connect(ctx.destination);source.start(0,from,len);
   return BLEND.harmMeasure(await ctx.startRendering(),kind);
  })().catch(()=>null);
  shotMeasures.set(buf,{input,measure});
  return measure;
 }
 async function acceptAudio(audio,kindOf,owns,accept){
  // A switch, render, pitch or trim edit can finish while a measurement is pending.
  while(owns()){
   const input=audio(),kind=kindOf(),hc=await measureInput(input,kind);
   if(!owns())return;
   if(kind!==kindOf()||!sameInput(input,audio()))continue;
   accept(hc);return;
  }
 }
 function refreshShot(id){
  const p=MX.slots[id];if(!p?.buf)return;
  if(p.warp)return sync();
  if(p.hk!=='oct')return;
  return acceptAudio(()=>osPlay(p),()=>BLEND.harmKind(p),()=>MX.slots[id]===p&&!!p.buf,hc=>{
   p._hc=hc;apply(id);
  });
 }
 async function syncShot(id,p,dry,dryKey,key,bpm,owns){
  const accept=(warped,warpKey)=>acceptAudio(()=>osPlay(p,dry,warped),()=>BLEND.harmKind(p),owns,hc=>{
   p.buf=dry;p._key=dryKey;p.wbuf=warped;p._wkey=warpKey;p._hc=hc;
   if(MX.on)chain(id);
   apply(id);
  });
  if(!p.warp){
   delete p._warpRequest;
   await accept(null,null);
   return;
  }
  const trim=osTrim(p),semis=TR.semis(p.off||0,p);
  const body={sample:p.sample,key:key||null,trim,beats:p.warp,bpm,semis};
  const want=[p.sample,key,...trim.map(t=>t.toFixed(5)),p.warp,bpm,semis].join('|');
  if(p._wkey===want&&p.wbuf){await accept(p.wbuf,want);return}
  p._loading=true;hint(id);
  const load=async()=>{
   const r=await api('api/stems/oswarp',body);
   return decode(url(r.url));
  };
  const request=p._warpRequest?.key===want?p._warpRequest:{key:want,pending:load()};
  p._warpRequest=request;
  try{
   const buf=await request.pending;
   await accept(buf,want);
  }catch(e){
   if(owns()){p.warp=0;toast('warp: '+e.message);await accept(null,null)}
  }finally{
   if(owns()&&p._warpRequest===request){delete p._warpRequest;p._loading=false}
  }
 }
 async function syncPart(id,info,bpm,current){
  const p=MX.slots[id],kind=role(id),os=isOS(id);
  if(!has(p))return;
  const owns=()=>current()&&MX.slots[id]===p&&role(id)===kind,conformKey=MX.key||info.key||'';
  let want,load;
  if(os){
   if(String(p.sample).startsWith('stem:')){  // a stem part turned into a one-shot: rendered at the tempo, as it was shifted then
    const [,track,stem,bar0,n,k,semis,cond,legacy]=p.sample.split(':');
    want=p.sample+'|'+bpm;
    load=async()=>{const r=await api('api/stems/render',{track:+track,stem,bar0:+bar0,n:+n,k:+k,bpm,semis:+semis,legacy:legacy==='1',cond:+cond||undefined});return {buf:await decode(url(r.url))}};
   }else{
   want=p.sample+'|'+conformKey;
   load=async()=>({buf:await decode(conformKey?window.CRATE.conformURL(p.sample,conformKey,''):url(p.sample))});
   }
  }else{
   const {track,bar0,n,cond}=p,k=p.k||1,legacy=!!p.legacyLoop;
   TR.load(track,kind).then(song=>{
    if(song&&MX.slots[id]===p&&p.track===track&&role(id)===kind)TR.paintWave(id);
   });
   p.semis=info.slots?.[id]?.semis||0;
   const semis=TR.semis(p.semis,p);
   want=renderKey(p,bpm,semis);
   load=async()=>{
    const r=await api('api/stems/render',{track,stem:kind,bar0,n,k,bpm,semis,legacy,cond,cut:p.cut&&p.cut.length?p.cut:undefined,xf:p.xf||undefined});
    const buf=await decode(url(r.url));
    return {buf,sub:r.sub||0,whole:r.whole};
   };
  }
  if(p._key===want&&p.buf){
   p._loading=false;p.err=null;
   if(os)await syncShot(id,p,p.buf,want,conformKey,bpm,owns);
   return;
  }
  p._loading=true;
  hint(id);
  const key=kind+'|'+want;
  const request=p._request?.key===key?p._request:{key,pending:load()};
  p._request=request;
  try{
   const {buf,sub,whole}=await request.pending;
   if(!owns())return;
   if(kind==='drums'){
    if(whole===false&&p.kit)return true;
    if(whole&&!p.kit){
     p.kit=true;
     const previous=MX.hist[id]?.[MX.hpos[id]];
     if(sameHistoryPart(previous,snap(id,p)))previous.kit=true;
    }
   }
   p.err=null;
   if(os)await syncShot(id,p,buf,want,conformKey,bpm,owns);
   else{
    const legacy=p.hup?await BLEND.harmMeasure(buf,'drive'):null;
    await acceptAudio(()=>({buf}),()=>BLEND.harmKind(p),owns,hc=>{
     p.buf=buf;p._key=want;p._hc=hc;p._legacyHc=legacy;
     p._playingLoop={track:p.track,bar0:p.bar0,n:p.n,k:p.k,cut:p.cut||null};
     p.sub=sub;initHarm(id);startSrc(id);
    });
   }
  }catch(e){
   if(owns())p.err=e.message;
  }finally{
   if(p._request===request&&owns()){delete p._request;p._loading=false}
  }
 }
 function sync(){
  splitKits();
  const token=++syncId,want=state(),current=()=>token===syncId;
  const task=(async()=>{
   try{
    const info=await api('api/stems/info',{state:want});
    if(!current())return;
    MX.info=info;
    const stale=await Promise.all(MX.order.map(id=>syncPart(id,info,want.bpm,current)));
    if(current()&&stale.some(Boolean)){
     await refreshSongs();
     if(current()&&splitKits()){sync();return}
    }
   }catch(e){
    if(!current())return;
    MX.order.forEach(id=>{if(MX.slots[id])MX.slots[id]._loading=false});
    toast('mashup: '+e.message);
   }
   if(current()){save();draw();prefetchSoon()}
  })();
  syncing=task.then(()=>{if(!current())return syncing});
  return syncing;
 }
 async function setLoop(id,bar0,n){
  const p=MX.slots[id];
  if(!(MX.hist[id]||[]).length)hpush(id);
  Object.assign(p,{bar0,n,cut:null,xf:0,alt:null,legacyLoop:false,_loading:true});
  hpush(id);
  save();
  markSave();
  await sync();
 }
 const hint=stem=>{const el=document.querySelector(`[data-mxrow="${stem}"] .mxsrc .sub`);if(el)el.textContent='rendering…'};
 // what you do with a part teaches the recommender: thrown out within 6 s = a weak no, kept 30 s+ = a weak yes
 function leaving(stem){const p=MX.slots[stem];if(!p||!p.since||!MX.on)return;const secs=(performance.now()-p.since)/1000;
  if(isOS(stem)){if(p.sample&&!String(p.sample).startsWith('stem:')&&secs>30&&typeof sendEvent==='function')sendEvent(p.sample,'listen',1,p.sid);return}
  if(secs<6)ev('reroll',stem);else if(secs>30)ev('kept',stem)}
 function ev(kind,stem){api('api/stems/event',{kind,stem:stem||null,state:state()}).then(r=>{MX.rated=r.rated;const el=$('mxrated');if(el)el.textContent=ratedTxt()}).catch(()=>{})}
 const ratedTxt=()=>MX.rated>=12?`recommendations learned from ${MX.rated} ratings`:`learning: ${MX.rated}/12 ratings before it adapts (👍 👎, what you keep and what you throw out)`;
 // each slot remembers the parts it has held: ↶ goes back to one you liked after trying something else, ↷ forward again
 const snap=(id,p)=>({stem:role(id),track:p.track,bar0:p.bar0,n:p.n,k:p.k||1,cut:p.cut&&p.cut.length?p.cut.map(c=>c.slice()):undefined,xf:p.cut&&p.cut.length&&p.xf||undefined,off:p.off||0,ct:p.ct||0,legacyLoop:!!p.legacyLoop,kit:p.kit||undefined,hk:p.hk==='oct'?'oct':undefined,cond:p.cond||undefined,artist:p.artist,title:p.title,bars:p.bars,why:p.why,alt:p.alt||null,sample:p.sample,sid:p.sid,sub:p.sub,cat:p.cat,dur:p.dur,key:p.key,steps:(p.steps||[]).slice(),every:p.every,trim:p.trim?p.trim.slice():null,warp:p.warp||0,fin:p.fin||0,fout:p.fout||0,back:p.back||undefined,gate:p.gate&&Object.keys(p.gate).length?{...p.gate}:undefined,fit:p.fit});
 MX.hist={};MX.hpos={};
 const sameHistoryPart=(a,b)=>a&&a.stem===b.stem&&a.track===b.track&&a.sample===b.sample&&
  a.bar0===b.bar0&&a.n===b.n&&a.k===b.k&&a.legacyLoop===b.legacyLoop;
 function hpush(id){const p=MX.slots[id];if(!has(p))return;const H=MX.hist[id]||(MX.hist[id]=[]),at=MX.hpos[id]??-1,sn=snap(id,p);
  if(sameHistoryPart(H[at],sn)&&(H[at].cond||0)===(sn.cond||0)&&H[at].hk===sn.hk)return;H.length=at+1;H.push(sn);if(H.length>40)H.shift();MX.hpos[id]=H.length-1}
 async function hgo(id,d){const H=MX.hist[id]||[],at=(MX.hpos[id]??-1)+d;if(at<0||at>=H.length)return;const p=MX.slots[id]||(MX.slots[id]={db:-2});
  MX.hpos[id]=at;delete p._hkRequest;delete p.hk;delete p._viewKey;Object.assign(p,H[at],{since:performance.now(),harm:null,hup:undefined,buf:null,_hc:null,_key:null,_next:null,wbuf:null,_wkey:null,_warpRequest:null});if(MX.roles[id]!==H[at].stem&&H[at].stem)MX.roles[id]=H[at].stem;await sync()}
 // 🎲 without the wait: once the mixer settles, each unlocked stem slot's next part is picked, rendered and decoded in
 // the background. A click then swaps it in at once, if nothing it was chosen against has changed since (the other
 // slots' parts, the tempo, the key); otherwise the click asks the server as before.
 MX.pre={};
 const ctxSig=id=>JSON.stringify([role(id),MX.bpm,MX.key,(MX.slots[id]||{}).n,MX.order.filter(x=>x!==id&&MX.slots[x]&&MX.slots[x].track!=null).map(x=>{const p=MX.slots[x];return [x,p.track,p.bar0,p.n,p.k||1,p.off||0,p.ct||0]})]);
 async function prefetch(id){const p=MX.slots[id];if(isOS(id)||!p||p.track==null||p.lock)return;
  const stem=role(id),bpm=MX.bpm,sig=ctxSig(id),cur=MX.pre[id];if(cur&&cur.sig===sig)return;
  const tok=MX.pre[id]={sig,ready:false};
  try{const r=await api('api/stems/pick',{stem,slot:id,state:state(),avoid:(MX.recent[id]||[]).slice(-60),n:p.n});if(!r.part||MX.pre[id]!==tok)return;
   const q=r.part,rr=await api('api/stems/render',{track:q.track,stem,bar0:q.bar0,n:q.n,k:q.k||1,bpm,semis:TR.semis(q.semis||0,q),cond:q.cond});
   if(rr.whole)q.kit=true;
   const buf=await decode(url(rr.url)),hc=await BLEND.harmMeasure(buf,'oct');
   if(MX.pre[id]===tok)Object.assign(tok,{part:q,buf,hc,sub:rr.sub||0,ready:true})}catch(e){if(MX.pre[id]===tok)delete MX.pre[id]}}
 let preT=0;const prefetchSoon=()=>{clearTimeout(preT);preT=setTimeout(async()=>{if(st.tab!=='M')return;for(const id of MX.order)await prefetch(id)},350)};
 async function roll(stem,quiet,track){const old=MX.slots[stem];if(old&&old.lock&&track==null)return;leaving(stem);
  const rec=MX.recent[stem]||(MX.recent[stem]=[]);
  const pre=track==null&&!isOS(stem)?MX.pre[stem]:null,hit=pre&&pre.ready&&pre.sig===ctxSig(stem)?pre:null;delete MX.pre[stem];
  let r;try{r=hit?{part:hit.part}:isOS(stem)?await api('api/stems/oneshot',Object.assign({state:state(),n:old&&old.sample?old.n:1,avoid:rec.slice(-12)},track==null?{}:{path:track})):await api('api/stems/pick',{stem:role(stem),slot:stem,state:state(),avoid:rec.slice(-60),n:old?old.n:null,track:track==null?null:track})}catch(e){toast('mashup: '+e.message);return}
  if(!r.part){if(!quiet)toast(isOS(stem)?'no one-shot found: the library has no short samples that fit':`no ${role(stem)} part fits this tempo${PITCHED.has(role(stem))?' and key':''}: try another tempo, or prepare more songs`);return}
  if(has(old)&&!(MX.hist[stem]||[]).length)hpush(stem);  // what was there before the first roll can be gone back to as well
  stopSrc(stem);const keep=old?{db:old.db,mute:old.mute,solo:old.solo,eq:old.eq,dly:old.dly,dt:old.dt,fb:old.fb,eqOn:old.eqOn,dlyOn:old.dlyOn,rev:old.rev,revOn:old.revOn,_c:old._c,_v:old._v,_viewMode:old._viewMode,_preset:old._preset}  /* (harmonics follow the part: a new one decides again) */:{db:role(stem)==='vocals'?0:-2};
  if(isOS(stem)&&old&&old.sample&&track==null){r.part.n=old.n;r.part.every=old.every;if((old.steps||[]).length)r.part.steps=old.steps.slice()}  // 🎲 swaps the sound, your placement stays
  MX.slots[stem]=Object.assign(keep,r.part,{hk:'oct',ct:0,since:performance.now(),buf:null,_key:null,_next:null});rec.push(isOS(stem)?r.part.sample:r.part.track);if(rec.length>80)rec.splice(0,rec.length-80);try{localStorage.setItem('dcStemsRecent',JSON.stringify(MX.recent))}catch(e){}hpush(stem);
  if(hit){const p=MX.slots[stem];p.buf=hit.buf;p.sub=hit.sub;p._hc=hit.hc;initHarm(stem);p._key=renderKey(p,MX.bpm,TR.semis(p.semis||0,p));p._playingLoop={track:p.track,bar0:p.bar0,n:p.n,k:p.k};startSrc(stem);draw()}  // it's playing already; sync only confirms
  await sync()}
 async function rollAll(){const pr={drums:0,tops:1,other:2,bass:3,vocals:4,oneshot:5};  // 'other' before bass and vocals: it sets the key they fit to
  for(const s of MX.order.slice().sort((a,b)=>pr[role(a)]-pr[role(b)]))if(!(MX.slots[s]&&MX.slots[s].lock))await roll(s,true);if(!MX.on&&MX.order.some(s=>has(MX.slots[s])))play(true)}
 const why=p=>{const w=p.why;if(!w)return'';return `\n\nwhy this part: active ${Math.round(w.active*100)}% · stretched ${Math.round((Math.exp(-w.stretch)-1)*100)}% · shifted ${-w.shift} st · fits the harmony ${Math.round(w.fit*100)}% · harmony still ${Math.round((w.still??0.5)*100)}%${w.sound?` · like your liked sounds ${w.sound>0?'+':''}${w.sound.toFixed(2)}`:''}`};
 // every prepared song, with a button per stem to put it in a slot
 function songsHTML(){const L=(MX.songs||[]).slice().sort((a,b)=>(a.artist+a.title).localeCompare(b.artist+b.title));
  return `<div class="mxsl2">${L.map(x=>`<div class="mxsong"><span class="mxsn" title="${esc(x.artist)} — ${esc(x.title)}"><b>${esc(x.artist)}</b> — ${esc(x.title)}</span><span class="sub">${Math.round(x.bpm)} bpm · ${x.key} · ${x.bars} bars</span><span>${STEMS.map(k=>x.stems.includes(k)?`<button class="tbtn" data-mxput="${k}:${x.track}" title="put its ${k} in a ${k} slot (its best-fitting bars)">${ICON[k]}</button>`:`<button class="tbtn" disabled title="no ${k} to speak of in this song">${ICON[k]}</button>`).join('')}</span></div>`).join('')||'<span class="sub">none yet: run “digitalcrate stems”</span>'}</div>`}
 function findHTML(stem){const F=MX.find;if(!F||F.stem!==stem)return'';
  if(isOS(stem)){const q=(F.q||'').toLowerCase().trim(),lim=2*barLenM()+0.05,out=[];
   for(let i=0;i<S.length&&out.length<16;i++){const x=S[i];if(x[F_.dur]>lim||x[F_.parent]||GONE.has(i)||TASTE.disliked.has(x[F_.path]))continue;if(x[F_.kind]!=='oneshot'&&!(x[F_.cat]==='Vocals'||x[F_.cat]==='Vocal Atmospheres'))continue;
    if(q&&!(`${x[F_.artist]} ${x[F_.title]} ${x[F_.sub]} ${x[F_.cat]} ${x[F_.id]} ${(x[F_.tags]||[]).join(' ')} ${(typeof WORDS!=='undefined'&&WORDS[i])||''}`.toLowerCase().includes(q)))continue;out.push(i)}
   return `<div class="mxfind"><button class="tbtn mxfindx" data-mxfindx="1" title="close the search (Esc)">✕</button><input id="mxq" placeholder="search your library's one-shots, drum hits and short vocals (artist, title, words, mood…)" value="${esc(F.q||'')}" style="width:340px">${out.map(i=>`<button class="tbtn" data-mxospick="${stem}:${i}" title="${esc(S[i][F_.sub])} · ${S[i][F_.dur]} s${S[i][F_.cam]?' · '+S[i][F_.cam]:''}">${esc(S[i][F_.artist])} — ${esc(S[i][F_.title])} <span class="sub">${esc(S[i][F_.sub])} · ${S[i][F_.dur]}s</span></button>`).join('')||'<span class="sub">nothing short enough matches</span>'}</div>`}const q=(F.q||'').toLowerCase(),rows=(MX.songs||[]).filter(x=>x.stems.includes(role(stem))&&(!q||(x.artist+' '+x.title).toLowerCase().includes(q))).slice(0,14);
  return `<div class="mxfind"><button class="tbtn mxfindx" data-mxfindx="1" title="close the search (Esc)">✕</button><input id="mxq" placeholder="search the ${MX.songs?MX.songs.length:''} prepared songs…" value="${esc(F.q||'')}">${rows.map(x=>`<button class="tbtn" data-mxsong="${stem}:${x.track}" title="${x.bpm} bpm · ${x.key}">${esc(x.artist)} — ${esc(x.title)} <span class="sub">${Math.round(x.bpm)} · ${x.key}</span></button>`).join('')||'<span class="sub">no prepared song matches</span>'}</div>`}
  // the whole sample, small, with the piece that plays lit: drag across it to choose the piece, drag an edge to move it
 function osTrimDraw(stem,p){if(!p.buf)return;const [a,b]=osTrim(p),D=p.buf.duration,d=p.buf.getChannelData(0);
  document.querySelectorAll(`canvas[data-mxtrim="${stem}"]`).forEach(c=>{const dpr=devicePixelRatio||1,W=Math.round(c.clientWidth*dpr),H=Math.round(c.clientHeight*dpr);if(!W||!H)return;c.width=W;c.height=H;
   const g=c.getContext('2d'),st3=d.length/W,big=c.classList.contains('big');let pk=0;const m=new Float32Array(W);
   for(let x=0;x<W;x++){let v=0;for(let k=Math.floor(x*st3),e=Math.min(d.length,Math.floor((x+1)*st3));k<e;k+=(st3>40?2:1))v=Math.max(v,Math.abs(d[k]));m[x]=v;pk=Math.max(pk,v)}
   g.fillStyle='rgba(224,164,88,.14)';g.fillRect(a*W,0,(b-a)*W,H);
   for(let x=0;x<W;x++){const h=Math.max(1,m[x]/(pk||1)*(H-(big?16:2))),inS=x>=a*W&&x<=b*W;g.fillStyle=inS?'#ffe6bf':'#4a515c';g.fillRect(x,(H-(big?12*dpr:0)-h)/2,1,h)}
   if(big){g.font=`${9.5*dpr}px ui-monospace,Menlo,monospace`;g.textBaseline='bottom';const stp=[0.01,0.02,0.05,0.1,0.2,0.5,1,2].find(q=>q/D*W>=60*dpr)||5;  // a time axis
    for(let t=0;t<=D+1e-9;t+=stp){const x=Math.round(t/D*W);g.fillStyle='rgba(255,255,255,.2)';g.fillRect(x,H-12*dpr,1,12*dpr);g.fillStyle='#8a93a0';g.fillText(t.toFixed(stp<0.1?2:1)+' s',x+3*dpr,H)}}
   if(big&&(p.fin||p.fout)){const fx=ms=>ms/1000/D*W*(p.warp&&p.wbuf?(b-a)*D/p.wbuf.duration:2**(TR.semis(p.off||0,p)/12)),hb=H-12*dpr;g.strokeStyle='#fff';g.lineWidth=1.5*dpr;g.beginPath();  // your fades, as they fall on the piece
     if(p.fin){g.moveTo(a*W,hb);g.lineTo(Math.min(b*W,a*W+fx(p.fin)),2)}if(p.fout){g.moveTo(Math.max(a*W,b*W-fx(p.fout)),2);g.lineTo(b*W,hb)}g.stroke()}
   g.fillStyle='#e0a458';[a,b].forEach((t,k)=>{const x=Math.min(W-2*dpr,Math.max(0,t*W-dpr));g.fillRect(x,0,2*dpr,H);if(big)g.fillRect(k?x-5*dpr:x,0,7*dpr,10*dpr)})});
  document.querySelectorAll(`[data-mxtrimlen="${stem}"]`).forEach(o=>o.textContent=((b-a)*D).toFixed(2)+' s');
  const tx=document.querySelector(`[data-mxtrimtxt="${stem}"]`);if(tx)tx.textContent=`start ${(a*D).toFixed(3)} s · end ${(b*D).toFixed(3)} s · length ${((b-a)*D).toFixed(3)} s`}
 // the large trim view, under the slot: the same gestures on five times the width, nudges of 5 ms, and exact times
 // a splice: the part as pieces of its song, one after the other (whole bars unless you ask for halves)
 // A piece is [bar, bars, backwards, stretch, repeats] (the last three only when they aren't 0, 1, 1); bar null: a rest.
 const cutOf=p=>p.cut&&p.cut.length?p.cut.map(c=>c.slice()):[[p.bar0,TR.srcBars(p.n||4,p.k||1)]];
 const cutTotal=cut=>cut.reduce((t,c)=>t+TR.pieceBars(c),0);
 async function setCut(id,cut){const p=MX.slots[id];if(!p||p.track==null)return;const nb=p.bars||9999;
  cut=cut.map(c=>{let [b,l,r,st,reps]=c;l=Math.max(0.5,Math.round(l*2)/2);st=[0.5,1,2].includes(+st)?+st:1;reps=Math.max(1,Math.min(16,Math.round(+reps||1)));
   if(b==null)return reps>1?[null,Math.min(16,l),0,1,reps]:[null,Math.min(16,l)];
   b=Math.max(0,Math.min(nb-0.5,Math.round(b*2)/2));l=Math.min(nb-b,l);
   return reps>1?[b,l,r?1:0,st,reps]:st!==1?[b,l,r?1:0,st]:r?[b,l,1]:[b,l]});
  if(!cut.some(c=>c[0]!=null))return;if(!(MX.hist[id]||[]).length)hpush(id);
  Object.assign(p,{cut,bar0:Math.floor(cut.find(c=>c[0]!=null)[0]),n:Math.max(1,Math.round(cutTotal(cut)/(p.k||1))),alt:null,legacyLoop:false,_loading:true});
  if(p._viewMode!=='song'&&p._viewMode!=='custom')p._preset='loop';  // the Loops view frames all the pieces
  hpush(id);save();markSave();draw();await sync()}
 function spliceHTML(id){const p=MX.slots[id];if(MX.splice!==id||!p||p.track==null||isOS(id))return'';
  const cut=cutOf(p),T=cutTotal(cut),total=T/(p.k||1),lens=[0.5,1,1.5,2,3,4,6,8],col=i=>TR.PIECE[i%TR.PIECE.length];
  const bl=(b,l)=>l===1?`bar ${b+1}`:Number.isInteger(l)&&Number.isInteger(b)?`bars ${b+1}–${b+l}`:`bar ${b+1} · ${l===0.5?'½ bar':l+' bars'}`;
  const name=([b,l,r,st,reps])=>(b==null?`rest · ${l===0.5?'½ bar':l+(l===1?' bar':' bars')}`:bl(b,l)+(r?' ◀ backwards':'')+(st===2?' · 2× long':st===0.5?' · ½× long':''))+(reps>1?' ×'+reps:'');
  const lenSel=(l,i)=>`<select data-mxpcl="${id}:${i}" title="how long this piece is">${[...new Set([...lens,l])].sort((x,y)=>x-y).map(v=>`<option value="${v}" ${v===l?'selected':''}>${v===0.5?'½ bar':v+(v===1?' bar':' bars')}</option>`).join('')}</select>`;
  const repSel=(n,i)=>`<select data-mxpcn="${id}:${i}" title="how many times this piece plays before the next one: a loop within the loop">${[...new Set([1,2,3,4,6,8,n||1])].sort((x,y)=>x-y).map(v=>`<option value="${v}" ${v===(n||1)?'selected':''}>×${v}</option>`).join('')}</select>`;
  let at=0;
  return `<div class="mxtrimbox mxsplice" data-mxsplicebox="${id}">
   <div class="mxlab" style="margin-bottom:4px">what plays, left to right (the song above shows where each piece comes from, in the same color) · drag a block to change the order</div>
   <div class="mxpcstrip" data-mxpcstrip="${id}"><canvas></canvas><i></i>${cut.map((c,i)=>{const x=at/T*100,w=TR.pieceBars(c)/T*100;at+=TR.pieceBars(c);return `<span draggable="true" data-mxpci="${id}:${i}" class="${c[0]==null?'rest':''}" style="left:${x.toFixed(2)}%;width:${w.toFixed(2)}%;--pc:${col(i)}" title="drag to change the order"><b>${i+1}</b> ${name(c)}</span>`}).join('')}</div>
   <div class="mxtrimbar"><b>Pieces</b>
   ${cut.map(([b,l,rv,st,reps],i)=>`<span class="mxpc" data-mxpci="${id}:${i}" style="--pc:${col(i)}"><i draggable="true" title="drag to change the order">${i+1}</i>${b==null?`<span class="mxlab">rest</span>${lenSel(l,i)}`:`<span class="mxlab">bar</span><input type="number" min="1" max="${p.bars||9999}" step="0.5" value="${b+1}" data-mxpcb="${id}:${i}" title="the song's bar this piece starts at · 12.5 is the middle of bar 12 (the arrows step by half a bar)">
    ${lenSel(l,i)}<select data-mxpcs="${id}:${i}" title="stretch this piece: twice as long (half speed) or half as long (double speed), its pitch kept">${[[0.5,'½× long'],[1,'as it is'],[2,'2× long']].map(([v,t])=>`<option value="${v}" ${v===(st||1)?'selected':''}>${t}</option>`).join('')}</select>`}
    ${repSel(reps,i)}${b==null?'':`<button class="tbtn mxtg${rv?' on':''}" data-mxpcrev="${id}:${i}" title="play this piece backwards">rev</button>`}<button class="tbtn" data-mxpcup="${id}:${i}" title="move this piece earlier in the order" ${i?'':'disabled'}>←</button><button class="tbtn" data-mxpcx="${id}:${i}" title="take this piece out" ${cut.length>1?'':'disabled'}>✕</button></span>`).join('')}
   <button class="tbtn" data-mxpcadd="${id}" title="another piece: the bar after the last one (then set its bar, or ⌥-click the waveform)">＋ piece</button><button class="tbtn" data-mxpcrest="${id}" title="a rest: a bar of silence between pieces">＋ rest</button>
   <span class="mxlab" style="margin-left:10px" title="crossfade at every join, and where the loop comes round: each piece runs on a moment into its song, fading out under the next one as it fades in. 0 is a clean cut">crossfade</span><input type="range" min="0" max="400" step="5" value="${p.xf||0}" data-mxpcxf="${id}" style="width:110px" title="crossfade at every join, and where the loop comes round. 0 is a clean cut"><output>${p.xf||0} ms</output>
   <span style="flex:1"></span><span class="sub">${Number(total.toFixed(2))} bar${total===1?'':'s'} in all${total%1?' · not a whole number of bars: it will drift against the other tracks':''}</span>
   ${p.cut&&p.cut.length?`<button class="tbtn" data-mxpcoff="${id}" title="back to one stretch of the song, from the first piece">one stretch again</button>`:''}<button class="tbtn" data-mxsplice="${id}">done</button></div>
   <div class="sub" style="margin-top:6px">The pieces play one after the other. <b>⌥-click</b> the waveform to add the bar under the pointer (<b>⌥⇧</b> for a half bar); each piece has its number and color there.</div></div>`}
 // the spliced part's own waveform, cut at the joins and tinted piece by piece
 function spliceDraw(id){const box=document.querySelector(`[data-mxpcstrip="${CSS.escape(id||'')}"]`),p=MX.slots[id];if(!box||!p)return;const c=box.querySelector('canvas'),dpr=devicePixelRatio||1,W=Math.round(c.clientWidth*dpr),H=Math.round(c.clientHeight*dpr);if(!W||!H)return;
  c.width=W;c.height=H;const g=c.getContext('2d'),cut=cutOf(p),T=cutTotal(cut),fresh=p.buf&&!p._loading&&p._key&&p._key.endsWith('|'+cutKey(p))&&cutKey(p);
  let at=0;cut.forEach((pc,i)=>{const l=TR.pieceBars(pc),x0=Math.round(at/T*W),x1=Math.round((at+l)/T*W);at+=l;g.fillStyle='rgba(255,255,255,.04)';g.fillRect(x0,0,x1-x0,H);
   if(fresh||(!cutKey(p)&&p.buf)){const d=p.buf.getChannelData(0),per=d.length/W;g.fillStyle=TR.PIECE[i%TR.PIECE.length];
    for(let x=x0;x<x1;x++){let m=0;for(let k=Math.floor(x*per),e=Math.min(d.length,Math.floor((x+1)*per));k<e;k+=Math.max(1,Math.floor(per/40)))m=Math.max(m,Math.abs(d[k]));const h=Math.max(1,m*(H-18)*2.2);g.fillRect(x,18+(H-18-Math.min(H-18,h))/2,1,Math.min(H-18,h))}}
   g.fillStyle='#0b0d10';g.fillRect(x1-1,0,2,H)})}
 function trimHTML(stem){const p=MX.slots[stem];if(MX.trimOpen!==stem||!p||!isOS(stem))return'';
  const nb=(w,d,l)=>`<button class="tbtn" data-mxnudge="${stem}:${w}:${d}" title="${w?'end':'start'} ${d<0?'earlier':'later'} by 5 ms (shift-click: 1 ms)">${l}</button>`;
  return `<div class="mxtrimbox"><canvas class="mxtrim big" data-mxtrim="${stem}"></canvas>
   <div class="mxtrimbar"><span class="mxlab">start</span>${nb(0,-1,'◀')}${nb(0,1,'▶')}<span class="mxlab" style="margin-left:10px">end</span>${nb(1,-1,'◀')}${nb(1,1,'▶')}
    <button class="tbtn" data-mxaud="${stem}" title="hear the piece once">▶ hear it</button><button class="tbtn" data-mxtrimall="${stem}">whole sample</button>
    <span class="sub" data-mxtrimtxt="${stem}"></span><span style="flex:1"></span><span class="sub">drag to select · drag an edge to adjust · hold shift for fine</span><button class="tbtn" data-mxtrimopen="${stem}">done</button></div>
   <div class="mxtrimbar"><span class="mxlab">fade in</span><input type="range" min="0" max="400" step="5" value="${p.fin||0}" data-mxfade="${stem}:fin" style="width:120px"><output>${p.fin||0} ms</output>
    <span class="mxlab" style="margin-left:10px">fade out</span><input type="range" min="0" max="2000" step="10" value="${p.fout||0}" data-mxfade="${stem}:fout" style="width:160px"><output>${p.fout||0} ms</output>
    <button class="tbtn mxtg${p.back?' on':''}" data-mxback="${stem}" style="margin-left:14px" title="play the piece backwards">◀ reverse</button>
    <span class="mxlab" style="margin-left:16px" title="stretch the piece to an exact length at the mashup's tempo, keeping its pitch (your pitch offset then keeps the length too)">warp</span>
    <select data-mxwarp="${stem}" title="stretch the piece to an exact length at the mashup's tempo, keeping its pitch">${[[0,'off: its own length'],[1,'fit ¼ bar'],[2,'fit ½ bar'],[4,'fit 1 bar'],[8,'fit 2 bars']].map(([v,l])=>`<option value="${v}" ${(p.warp||0)===v?'selected':''}>${l}</option>`).join('')}${p.warp&&![1,2,4,8].includes(p.warp)?`<option value="${p.warp}" selected>fit ${p.warp} beats</option>`:''}</select>
    <span class="mxlab" title="any length, in beats: a 16th note is 0.25, a dotted 8th 0.75, a bar 4. Arrow keys step by a 16th; type for anything finer (1.1, 2.33…)">or</span><input type="number" class="mxwarpn" data-mxwarpn="${stem}" min="0.1" max="32" step="0.25" value="${p.warp||''}" placeholder="${p.buf?((osTrim(p)[1]-osTrim(p)[0])*p.buf.duration/(60/MX.bpm)).toFixed(2):''}" title="any length, in beats: a 16th note is 0.25, a dotted 8th 0.75, a bar 4. Arrow keys step by a 16th; type for anything finer (1.1, 2.33…)"><span class="mxlab">beats</span>
    <span class="sub">${p.warp&&p.wbuf?`stretched ${(p.wbuf.duration/((osTrim(p)[1]-osTrim(p)[0])*p.buf.duration)).toFixed(2)}× to ${p.wbuf.duration.toFixed(2)} s`:''}</span></div></div>`}
 function osWave(stem,p,box){const c=box.querySelector('canvas.mxosw');if(!c)return;const dpr=devicePixelRatio||1,W=Math.round(c.clientWidth*dpr),H=Math.round(c.clientHeight*dpr);c.width=W;c.height=H;
   const g=c.getContext('2d'),q=osPlay(p),d=q.buf.getChannelData(0),n=p.n||1,cyc=n*barLenM(),len=q.out,wpx=Math.max(3,len/cyc*W),i0=Math.floor(q.from/q.buf.duration*q.buf.length),step=q.len/q.buf.duration*q.buf.length/wpx;
   let pk=0;const m=new Float32Array(Math.ceil(wpx));for(let x=0;x<m.length;x++){let v=0;for(let k=i0+Math.floor(x*step),e=Math.min(d.length,i0+Math.floor((x+1)*step));k<e;k+=2)v=Math.max(v,Math.abs(d[k]));m[x]=v;pk=Math.max(pk,v)}
   osTrimDraw(stem,p);
   (p.steps||[]).forEach(s=>{const x0=Math.round(s/(n*16)*W);g.fillStyle='rgba(255,255,255,.10)';g.fillRect(x0,0,Math.min(wpx,W-x0),H);  // how long it sounds
    g.fillStyle='#e0a458';g.fillRect(x0,0,Math.max(1,Math.round(dpr)),H);  // where the hit lands, under its step
    g.fillStyle='rgba(255,236,200,.9)';for(let x=0;x<m.length&&x0+x<W;x++){const h=Math.max(1,m[x]/(pk||1)*(H-4));g.fillRect(x0+x,(H-h)/2,1,h)}
    if(x0+wpx>W){g.fillStyle='rgba(255,255,255,.06)';g.fillRect(0,0,x0+wpx-W,H)}})}  // a hit near the end rings into the next time round
 function waves(){MX.order.forEach(id=>{
  if(!isOS(id)){TR.paintWave(id);return}
  const p=MX.slots[id],box=document.querySelector(`[data-mxwave="${id}"]`);
  if(p?.buf&&box)osWave(id,p,box);
 })}
 window.addEventListener('resize',()=>{if(st.tab==='M')waves()});
 function mxMeter(){
  const el=$('mxgr');if(!el)return;
  const playing=st.tab==='M'&&MX.on,chain=MX.mast.chain,text=playing&&MX.mast.on&&chain?`${chain.glue.reduction.toFixed(1)} dB`:'';
  if(el.textContent!==text)el.textContent=text;
  const gl=$('mxglgr'),group=MX.bus?.g;
  const drums=playing&&MX.glue.on&&group?.wet.gain.value>0&&MX.order.some(id=>(role(id)==='drums'||role(id)==='tops')&&has(MX.slots[id]));
  const reduction=drums?`${group.comp.reduction.toFixed(1)} dB`:'';
  if(gl&&gl.textContent!==reduction)gl.textContent=reduction;
 }
 let phRaf=0;function playheads(){phRaf=0;if(MX.mast.on||MX.glue.on)mxMeter();if(!MX.on||st.tab!=='M')return;MX.order.forEach(id=>{
  const p=MX.slots[id],el=document.querySelector(`[data-mxwave="${id}"] i`);if(!p?.buf||!el)return;
  const os=isOS(id),d=os?(p.n||1)*barLenM()*(p.every||1):p.buf.duration;
  const phase=(((AC.currentTime-MX.t0)%d)+d)%d/d,x=os?phase:TR.playhead(id,phase);
  el.style.left=(x*100).toFixed(2)+'%';el.style.display=x<0||x>1?'none':'block';
  if(MX.splice===id){const sl=document.querySelector('.mxpcstrip i');if(sl)sl.style.left=(phase*100).toFixed(2)+'%'}
 });phRaf=requestAnimationFrame(playheads)}
 // open a saved combination (also: back to it as saved, dropping what you changed since)
 function clearAll(){MX.order.forEach(retire);MX.slots={};MX.snaps=[];MX.trans=[];MX.snapSel=null;MX.snapsOf=null;MX.duck={};MX.info=null;MX.name='';MX.savedSig=null}
 async function openSaved(m){
  if(MX.on)play(false);
  MX.order.forEach(retire);
  const sv=JSON.parse(JSON.stringify(m.state));
  MX.bpm=sv.bpm||MX.bpm;MX.key=sv.key||'';MX.fx=sv.fx!==false;
  if(sv.reverb)BLEND.setReverb(MX,sv.reverb.type,sv.reverb.decay);
  MX.savedSig=null;restore(sv);MX.name=m.name;MX.snapsOf=MX.snaps.length?m.name:null;MX.info=null;
  MX.savedSig=sig();await sync();MX.order.forEach(apply);play(true);
 }
 async function refreshSaved(){try{MX.saved=(await api('api/stems/saved',{})).mixes}catch(e){MX.saved=[]}}
 async function refreshSongs(){try{const r=await api('api/stems/library',{});MX.songs=r.songs;MX.n=r.n;MX.rated=r.rated}catch(e){}}
 const dbv=v=>(v>0?'+':'')+(+v||0).toFixed(1)+' dB';
 // (replacing the list blurs a focused field, whose change handler may ask for another draw: that one waits its turn)
 let drawing=false,drawAgain=false;
 function draw(){if(drawing){drawAgain=true;return}drawing=true;try{drawNow()}finally{drawing=false}if(drawAgain){drawAgain=false;draw()}
  if(MX.splice)requestAnimationFrame(()=>spliceDraw(MX.splice))}
 function drawNow(){const L=$('list');if(st.tab!=='M'||!L)return;if(BLEND.pbDraw(L))return;const I=MX.info||{},fit=I.fit,restoreFocus=TR.retainFocus(L);
  if(MX.n===0){L.innerHTML=`<div class="empty">No songs are prepared for Mashup yet.<br>Run <code>digitalcrate stems</code> (about 2 minutes a song): it separates the sources of your favorites plus some random songs.</div>`;return}
  const row=id=>{
   const p=MX.slots[id],R=role(id),os=isOS(id),filled=has(p),color=BLEND.STEMVAR[R]||'--VOX';
   const name=`<div class="trname" draggable="true" data-mxtrdrag="${id}" title="drag to move this track up or down">${TR.name(R)}</div>`;
   const die=`<button class="tbtn trdie" data-mxroll="${id}" aria-label="New part" title="pull a part that fits" ${p?.lock?'disabled':''}>${TR.DIE}</button>`;
   const more=TR.more(id,ROLES,(MX.hist[id]||[]).length);
   const open=`<div class="trk${p?.mute?' muted':''}${TR.isOpen(id)?' open':''}" data-mxrow="${id}" style="--trcol:var(${color})">`;
   const find=findHTML(id);
   if(!filled)return `${open}<div class="trh">${name}<span class="trgroup trpick">${die}</span><div class="trsrc sub">empty</div>${more}</div></div>${find}`;

   const n=p.n||1,k=p.k||1,on=new Set(p.steps||[]),fit=p.fit||[],i=I.slots?.[id];
   const shift=TR.semis(p.semis||0,p);
   const shiftText=shift?` ${shift>0?'+':''}${Number(shift.toFixed(2))} st`:'';
   const length=os&&p.buf?osPlay(p).out.toFixed(2):(p.dur||'?');
   const sampleText=`${esc(p.sub||'one-shot')} · ${length} s${p.key?` · ${p.key}${p.semis?` ${p.semis>0?'+':''}${p.semis} st`:''}`:''} · ${on.size} hit${on.size===1?'':'s'}`;
   const rateText=k===2?' (half-time)':k===0.5?' (double-time)':'';
   const takeText=p.alt?` · take ${p.alt[0]}/${p.alt[1]}`:'';
   const subText=p.sub>=0.85?` · sub-bass${p.harm?' (+harmonics)':': silent on small speakers'}`:'';
   const songText=i?`from ${i.src_bpm} bpm${rateText}${takeText}${subText} · ${i.key}${shiftText}`:'';
   const sub=p.err?'failed: '+esc(p.err):p._loading?(os?'loading…':'rendering…'):os?sampleText:songText;
   const src=`<div class="mxsrc trsrc" title="${esc(p.artist||'')} — ${esc(p.title||'')}${sub?' · '+sub:''}${why(p)}"><b>${esc(p.artist||'')}</b> — ${esc(p.title||'')} <span class="sub">${sub}</span></div>`;
   const cycle=`<select data-mxlen="${id}" title="cycle length">${[1,2,4,8].map(l=>`<option value="${l}" ${n===l?'selected':''}>${l} bar${l===1?'':'s'}</option>`).join('')}</select>
    <select data-mxevery="${id}" title="how often it plays">${[[1,'every time'],[2,'every 2nd'],[4,'every 4th']].map(([v,l])=>`<option value="${v}" ${(p.every||1)===v?'selected':''}>${l}</option>`).join('')}</select>`;
   const history=`<button class="tbtn" data-mxhist="${id}:-1" title="back to the previous part" ${(MX.hpos[id]??-1)>0?'':'disabled'}>↶</button>
    <button class="tbtn" data-mxhist="${id}:1" title="forward again" ${(MX.hpos[id]??-1)<(MX.hist[id]||[]).length-1?'':'disabled'}>↷</button>`;
   const audition=os?`<button class="tbtn" data-mxaud="${id}" title="hear it once">▶</button>`:'';
   const mix=`<button class="tbtn${p.solo?' on':''}" data-mxsolo="${id}" title="solo">S</button><button class="tbtn${p.mute?' on':''}" data-mxmute="${id}" title="mute">M</button>
    <input type="range" min="-24" max="6" step="0.5" value="${p.db||0}" data-mxdb="${id}" aria-label="Volume" title="${dbv(p.db)} · double-click for 0 dB">`;
   const part=os?`<div class="mxwave mxsteps" data-mxwave="${id}" style="--n:${n*16};--b:${n}"><div class="mxsg">${Array.from({length:n*16},(_,j)=>`<button class="mxst${on.has(j)?' on':''}${on.has(j)&&(p.gate||{})[j]===0.5?' g2':on.has(j)&&(p.gate||{})[j]===0.25?' g4':''}${j%16===0?' bar':j%4===0?' beat':''}" data-mxstep="${id}:${j}" title="bar ${Math.floor(j/16)+1}, beat ${Math.floor(j%16/4)+1}${j%4?' + '+(j%4)+'/16':''}${on.has(j)?' · plays '+({0.5:'the first half',0.25:'the first quarter'}[(p.gate||{})[j]]||'all')+' of the piece · ⇧-click: half, a quarter, all':''}"></button>`).join('')}</div>
    <canvas class="mxosw"></canvas><div class="mxsax">${Array.from({length:n},(_,j)=>`<span style="--f:${fit[j]!=null?Math.max(0,Math.min(1,(fit[j]-0.5)*2)).toFixed(2):0}" title="${fit[j]!=null?`fits this bar's harmony ${Math.round(fit[j]*100)}%`:''}">${j+1}</span>`).join('')}</div><i></i></div>`
    :`<div class="mxwave trwave" data-mxwave="${id}" tabindex="0" aria-label="${TR.name(R)} waveform"><canvas></canvas><i></i><span class="trtip" hidden></span>${TR.zoomButtons}</div>`;
   return `${open}<div class="trh">${name}<span class="trgroup trpick">${die}${audition}${history}</span>${src}<div class="trbars">${os?cycle:TR.barsText(p)}</div>
    <span class="trgroup">${TR.num(id,'st')}${TR.num(id,'ct')}</span><span class="trgroup">${mix}</span>${more}</div>
    ${part}${TR.fxHTML(id)}</div>${trimHTML(id)}${spliceHTML(id)}${find}`;
  };
  L.innerHTML=`<div class="mx"><div class="mxtop">
    <button id="mxplay" class="${MX.on?'on':''}">${MX.on?'■ stop':'▶ play'}</button>
    <label>tempo <input id="mxbpm" type="number" min="50" max="200" step="1" value="${MX.bpm}" style="width:64px"> bpm</label>
    <label>key <select id="mxkey"><option value="">auto${!MX.key&&I.key?` (${I.key})`:''}</option>${KEYS.map(k=>`<option ${MX.key===k?'selected':''}>${k}</option>`).join('')}</select></label>
    <span class="mxmaster"><label><input id="mxmaster" type="checkbox" ${MX.mast.on?'checked':''}> MASTER</label><span id="mxgr"></span></span>
    <span class="mxmaster"><label title="light compression on Drums and Tops together"><input id="mxglue" type="checkbox" ${MX.glue.on?'checked':''}> GLUE</label><span id="mxglgr"></span></span>
    <button id="mxall" title="a new part in every unlocked slot, chosen to fit together">${TR.DIE} all</button>
    <span class="mxrate"><button id="mxup" title="this combination works: teaches the recommendations">👍</button><button id="mxdown" title="this doesn't work: teaches the recommendations, and deals a new one">👎</button></span>
    <button id="mxfx" class="${MX.fx!==false?'on':''}" title="all EQ, delay, reverb and harmonics on / off at once (your settings are kept)">FX ${MX.fx!==false?'on':'off'}</button>
    <span class="mxrvb" title="the reverb every slot's REVERB send goes to"><span class="mxlab">reverb</span><select id="mxrvtype">${Object.keys(BLEND.REVERBS).map(k=>`<option ${k===MX.reverb.type?'selected':''}>${k}</option>`).join('')}</select><input type="range" id="mxrvdecay" min="0.3" max="6" step="0.1" value="${MX.reverb.decay}" title="decay time"><output>${(+MX.reverb.decay).toFixed(1)} s</output></span>
    ${TR.viewSwitch()}
    <span class="mxfit" title="how well the pitched parts' notes agree, bar by bar, after shifting to the key (100% = the same notes)">${fit==null?'':`harmony fit <b style="color:${fit>=0.8?'var(--ok,#8fc98f)':fit>=0.65?'var(--acc)':'#d96c6c'}">${Math.round(fit*100)}%</b>`}</span>
    <span class="mxsaveg"><button id="mxnew" class="${MX._new&&Date.now()-MX._new<4000?'ask':''}" title="start a new mashup: a clean slate, with a first combination dealt (what's saved stays saved)">${MX._new&&Date.now()-MX._new<4000?'sure?':'＋ new'}</button><input id="mxname" placeholder="name this combination" value="${esc(MX.name||'')}" style="width:150px"><button id="mxsave">💾 save</button>
    ${MX.saved&&MX.saved.length?`<select id="mxload"><option value="">open a saved one…</option>${MX.saved.map(m=>`<option ${m.name===MX.name?'selected':''}>${esc(m.name)}</option>`).join('')}</select>${MX.name&&MX.saved.some(m=>m.name===MX.name)?`<button id="mxrevert" title="back to “${esc(MX.name)}” as it was last saved: drops the changes made since">↺ revert</button><button id="mxdelsaved" title="delete the saved combination “${esc(MX.name)}”">🗑</button>`:''}`:''}</span>
    <span class="mxsaveg" style="margin-left:0"><select id="mxexbars" title="how long each section is in the Live set">${[4,8,16].map(b=>`<option value="${b}" ${(MX.exBars||8)===b?'selected':''}>${b} bars each</option>`).join('')}</select><button id="mxexport" title="a Live set of this mashup, dry (no EQ, delay or reverb): a track per slot, each part a looping clip at the tempo; with snapshots, they are laid end to end with a marker each">⇩ Ableton</button></span>
    <button id="mxclear" class="${MX._clr&&Date.now()-MX._clr<4000?'ask':''}" title="a clean slate: empties every slot (locked ones too) and the snapshot strip. Saved combinations are not touched">${MX._clr&&Date.now()-MX._clr<4000?'sure?':'clear all'}</button></div>
   ${MX.ask?`<div class="mxask">The ${MX.snaps.length===1?'snapshot':MX.snaps.length+' snapshots'} above came with “${esc(MX.snapsOf)}”. Save “${esc(MX.ask)}” <button id="mxdropsn">without them</button> <button id="mxkeepsn">with them</button> <button id="mxaskno">cancel</button></div>`:''}
   ${BLEND.stripHTML()}
   ${MX.order.map(row).join('')}
   ${MX.order.length<8?`<div class="mxadd"><select id="mxaddrole">${ROLES.map(x=>`<option value="${x}">${ICON[x]} ${x==='oneshot'?'one-shot':x}</option>`).join('')}</select><button id="mxadd" title="another slot (up to 8): a second vocal, two drum layers, a pad under the keys…">＋ add slot</button></div>`:''}
   <div class="sub" style="margin-top:10px"><span id="mxrated">${ratedTxt()}</span> · stems follow the tempo and pitched parts follow the key</div>
   <details class="mxsongs" id="mxsongs" ${MX.showSongs?'open':''}><summary>${MX.n==null?'':MX.n+' '}songs prepared for Mashup</summary>${songsHTML()}</details></div>`;
  const dt=$('mxsongs');if(dt)dt.ontoggle=async()=>{MX.showSongs=dt.open;if(dt.open){await refreshSongs();const el=dt.querySelector('.mxsl2');if(el)el.outerHTML=songsHTML();const sm=dt.querySelector('summary');if(sm)sm.textContent=`${MX.n} songs prepared for Mashup`}};
  markSave();mxMeter();waves();restoreFocus();if(MX.on&&!phRaf)phRaf=requestAnimationFrame(playheads);if(MX.find&&$('mxq')){const q=$('mxq');q.focus();q.setSelectionRange(q.value.length,q.value.length)}}
 const L=$('list');
 let pressedButton=null;
 L.addEventListener('pointerdown',e=>{pressedButton=e.target.closest('button')});
 L.addEventListener('click',async e=>{if(st.tab!=='M')return;let t=e.target.closest('button');
  // the mixer may redraw between the press and the release of a click (a part finished loading): the button under the
  // pointer was replaced, and the browser hands the click to the container instead. Take the button that's there now.
  if(!t&&e.detail&&pressedButton&&!pressedButton.isConnected){
   const replacement=document.elementFromPoint(e.clientX,e.clientY)?.closest('button');
   if(replacement&&L.contains(replacement)&&replacement.id===pressedButton.id&&
      Object.entries(pressedButton.dataset).every(([key,value])=>replacement.dataset[key]===value))t=replacement;
  }
  if(!t||t.disabled)return;const ds=t.dataset;
  if(t.id==='mxplay'){play(!MX.on);return}if(t.id==='mxall'){await rollAll();return}
  if(t.id==='mxadd'){const id='s'+Date.now().toString(36);MX.order.push(id);MX.roles[id]=$('mxaddrole').value;save();draw();await roll(id);if(!MX.on)play(true);return}
  if(ds.mxrm){const id=ds.mxrm;retire(id);delete MX.slots[id];delete MX.roles[id];MX.order=MX.order.filter(x=>x!==id);if(MX.find&&MX.find.stem===id)MX.find=null;await sync();return}
  if(t.id==='mxfx'){MX.fx=MX.fx===false;MX.order.forEach(id=>{if(MX.slots[id]){initHarm(id);apply(id)}});save();draw();return}
  if(ds.mxeqon){const p=MX.slots[ds.mxeqon];p.eqOn=p.eqOn===false;apply(ds.mxeqon);save();draw();return}
  if(ds.mxrevon){const p=MX.slots[ds.mxrevon];p.revOn=p.revOn===false;apply(ds.mxrevon);save();draw();return}
  if(ds.mxhist){const [id,d]=ds.mxhist.split(':');hgo(id,+d);return}
  if(ds.mxdlyon){const p=MX.slots[ds.mxdlyon];p.dlyOn=p.dlyOn===false;apply(ds.mxdlyon);save();draw();return}
  if(ds.mxeven){
   const id=ds.mxeven,p=MX.slots[id];
   if(p.cond)delete p.cond;else p.cond=1;
   const entry=MX.hist[id]?.[MX.hpos[id]];
   if(sameHistoryPart(entry,snap(id,p)))entry.cond=p.cond;
   save();markSave();await sync();return;
  }
  if(t.id==='mxclear'){const ns=(MX.snaps||[]).length;  // a clean slate: the snapshot strip goes too (it used to stay, and tag along into the next combination)
   if(ns&&!(MX._clr&&Date.now()-MX._clr<4000)){MX._clr=Date.now();draw();toast(`this also clears ${ns===1?'the snapshot':'the '+ns+' snapshots'}: click “sure?” to clear all`);setTimeout(()=>{if(MX._clr&&Date.now()-MX._clr>=3900){MX._clr=0;draw()}},4000);return}  // (kept on MX: a redraw between the two clicks mustn't forget the first)
   MX._clr=0;clearAll();save();draw();return}
  // a new mashup: a clean slate (asking first if there is unsaved work or a strip of snapshots), dealt and playing
  if(t.id==='mxnew'){const lose=dirty(),ns=(MX.snaps||[]).length;
   if((lose||ns)&&!(MX._new&&Date.now()-MX._new<4000)){MX._new=Date.now();draw();toast(`${lose?'unsaved changes will be lost':'this clears the snapshots'}: click “sure?” to start a new mashup`);setTimeout(()=>{if(MX._new&&Date.now()-MX._new>=3900){MX._new=0;draw()}},4000);return}
   MX._new=0;clearAll();save();draw();await rollAll();if(!MX.on)play(true);return}
  if(ds.mxalt){const id=ds.mxalt,p=MX.slots[id],key=[p.track,p.n,role(id),MX.bpm].join('|');
   if(!p._alts||p._altk!==key){try{p._alts=(await api('api/stems/alts',{state:state(),slot:id})).alts;p._altk=key}catch(err){toast('mashup: '+err.message);return}}
   const A=p._alts||[];if(A.length<2){toast('no other good stretch of this in the song');return}
   const k=(Math.max(0,A.findIndex(a=>a.bar0===p.bar0))+1)%A.length,nx=A[k];p.bar0=nx.bar0;p.k=nx.k||1;if(nx.why)p.why=nx.why;
   delete p._hkRequest;p.cond=nx.cond;p.alt=[k+1,A.length];delete p.legacyLoop;delete p._viewKey;p.ct=0;p.since=performance.now();p.harm=null;delete p.hup;hpush(id);await sync();return}
  if(ds.mxdel){const s=ds.mxdel;if(MX.slots[s]&&MX.slots[s].since&&(performance.now()-MX.slots[s].since)/1000<20)ev('remove',s);retire(s);delete MX.slots[s];await sync();return}
  if(ds.mxfindx){MX.find=null;draw();return}
  if(ds.mxsplice){MX.splice=MX.splice===ds.mxsplice?null:ds.mxsplice;draw();return}
  if(ds.mxpcadd){const p=MX.slots[ds.mxpcadd],cut=cutOf(p),last=cut.filter(c=>c[0]!=null).pop();cut.push([Math.min((p.bars||9999)-1,last[0]+last[1]),1]);await setCut(ds.mxpcadd,cut);return}
  if(ds.mxpcrest){const cut=cutOf(MX.slots[ds.mxpcrest]);cut.push([null,1]);await setCut(ds.mxpcrest,cut);return}
  if(ds.mxpcrev){const [id,i]=ds.mxpcrev.split(':'),cut=cutOf(MX.slots[id]);cut[+i][2]=cut[+i][2]?0:1;await setCut(id,cut);return}
  if(ds.mxpcx){const [id,i]=ds.mxpcx.split(':'),cut=cutOf(MX.slots[id]);cut.splice(+i,1);await setCut(id,cut);return}
  if(ds.mxpcup){const [id,i]=ds.mxpcup.split(':'),cut=cutOf(MX.slots[id]);if(+i>0){[cut[+i-1],cut[+i]]=[cut[+i],cut[+i-1]];await setCut(id,cut)}return}
  if(ds.mxpcoff){const id=ds.mxpcoff,p=MX.slots[id],c=cutOf(p)[0];await setLoop(id,Math.floor(c[0]),Math.max(1,Math.round(cutTotal(cutOf(p))/(p.k||1))));return}
  // a stem part becomes a one-shot: the same audio, played where you place it in a cycle (so it can leave gaps), with a
  // one-shot's trim, fades and warp. It starts as one hit at the top of a cycle twice its length: once, then a rest.
  if(ds.mxshot){const id=ds.mxshot,p=MX.slots[id],R=role(id);if(!p||p.track==null||isOS(id))return;
   if(!(MX.hist[id]||[]).length)hpush(id);
   const n=p.n||4,cyc=[1,2,4,8].find(c=>c>=2*n)||8,semis=TR.semis(p.semis||0,p);
   stopSrc(id);
   MX.roles[id]='oneshot';
   MX.slots[id]={stem:'oneshot',sample:['stem',p.track,R,p.bar0,n,p.k||1,semis,p.cond||0,p.legacyLoop?1:0,...(cutKey(p)?[cutKey(p)]:[])].join(':'),artist:p.artist,title:p.title,
    sub:`${TR.name(R).toLowerCase()} · bars ${p.bar0+1}–${p.bar0+TR.srcBars(n,p.k||1)}`,dur:+(n*barLenM()).toFixed(2),n:cyc,steps:[0],every:1,off:0,ct:0,
    db:p.db,mute:p.mute,solo:p.solo,eq:p.eq,dly:p.dly,dt:p.dt,fb:p.fb,eqOn:p.eqOn,dlyOn:p.dlyOn,rev:p.rev,revOn:p.revOn,_c:p._c,since:performance.now()};
   apply(id);hpush(id);await sync();markSave();
   toast(`${TR.name(R)} is a one-shot now: it plays once every ${cyc} bars · click steps to place it, Shape to trim it · ↶ brings the loop back`);return}
  if(ds.mxfind){if(MX.find&&MX.find.stem===ds.mxfind){MX.find=null;draw();return}MX.find={stem:ds.mxfind,q:''};await refreshSongs();draw();return}  // (songs still being prepared show up as they finish)
  if(ds.mxdup){const id=ds.mxdup,p=MX.slots[id];if(!has(p))return;if(MX.order.length>=8){toast('the mashup is full (8 slots)');return}
   const nid='s'+Date.now().toString(36),q={};Object.keys(p).forEach(k=>{if(k[0]!=='_')q[k]=Array.isArray(p[k])?p[k].slice():p[k]});  // everything but its audio chain; the decoded audio is shared
   q.lock=false;q.solo=false;q.since=performance.now();q._key=p._key;q._hc=p._hc;q._legacyHc=p._legacyHc;q._playingLoop=p._playingLoop;MX.slots[nid]=q;MX.roles[nid]=role(id);MX.order.splice(MX.order.indexOf(id)+1,0,nid);if((MX.duck||{})[id])MX.duck[nid]=Object.assign({},MX.duck[id]);
   q._loading=!!p._loading;q._request=p._request;q._wkey=p._wkey;q._warpRequest=p._warpRequest;
   hpush(nid);if(MX.on){if(isOS(nid)){chain(nid);apply(nid)}else startSrc(nid)}
   save();draw();toast('duplicated: change the copy from here');
   if(q._loading||q.err)await sync();
   else if(isOS(nid))await refreshShot(nid);
   return}
  if(ds.mxtrimopen){MX.trimOpen=MX.trimOpen===ds.mxtrimopen?null:ds.mxtrimopen;draw();return}
  if(ds.mxtrimall){const p=MX.slots[ds.mxtrimall];p.trim=null;save();draw();refreshShot(ds.mxtrimall);return}
  if(ds.mxhk){
   const id=ds.mxhk,p=MX.slots[id];if(!p?.buf)return;
   const os=isOS(id),kind=(p._hkRequest?.kind||BLEND.harmKind(p))==='oct'?'drive':'oct';
   const request=p._hkRequest={kind};
   const audio=()=>os?osPlay(p):{buf:p.buf};
   await acceptAudio(audio,()=>kind,()=>MX.slots[id]===p&&p._hkRequest===request,hc=>{
    delete p._hkRequest;
    if(kind==='oct')p.hk='oct';else delete p.hk;
    p._hc=hc;
    const previous=MX.hist[id]?.[MX.hpos[id]];
    if(sameHistoryPart(previous,snap(id,p)))previous.hk=p.hk;
    apply(id);save();markSave();draw();
   });
   return;
  }
  if(ds.mxharm){const p=MX.slots[ds.mxharm];p.harm=!BLEND.harmAmt(p);apply(ds.mxharm);save();draw();return}
  if(ds.mxnudge){const [id,w,d]=ds.mxnudge.split(':'),p=MX.slots[id],D=p.buf?p.buf.duration:1,t=osTrim(p).slice(),stp=(e.shiftKey?0.001:0.005)/D;
   t[+w]=Math.max(0,Math.min(1,t[+w]+(+d)*stp));if(t[1]-t[0]<0.004/D)return;p.trim=t;save();refreshShot(id);osTrimDraw(id,p);const box=document.querySelector(`[data-mxwave="${id}"]`);if(box)osWave(id,p,box);return}
  if(ds.mxstep){const [id,k]=ds.mxstep.split(':'),p=MX.slots[id],st2=new Set(p.steps||[]);
   if(e.shiftKey){const g=p.gate||(p.gate={}),cur=g[+k]||1;st2.add(+k);if(cur===1)g[+k]=0.5;else if(cur===0.5)g[+k]=0.25;else delete g[+k]}
   else if(st2.has(+k)){st2.delete(+k);if(p.gate)delete p.gate[+k]}else st2.add(+k);
   p.steps=[...st2].sort((a,b)=>a-b);save();markSave();draw();return}
  if(ds.mxback){const p=MX.slots[ds.mxback];p.back=!p.back;save();markSave();draw();return}
  if(ds.mxaud){const p=MX.slots[ds.mxaud];if(p&&p.buf){AC.resume();BLEND.out(MX,AC);if(!p._c){chain(ds.mxaud);apply(ds.mxaud)}osLive.add(osHit(ds.mxaud,p,AC.currentTime+0.01))}return}
  if(ds.mxospick){const [id,i]=ds.mxospick.split(':');MX.find=null;await roll(id,false,S[+i][F_.path]);if(!MX.on)play(true);return}
  if(ds.mxput){const [k,tid]=ds.mxput.split(':'),ids=MX.order.filter(id=>role(id)===k);  // an empty slot of that kind, else an unlocked one, else a new slot
   let id=ids.find(x=>!MX.slots[x])||ids.find(x=>!MX.slots[x].lock);
   if(!id){if(MX.order.length>=8){toast(`every ${k} slot is locked and the mixer is full`);return}id='s'+Date.now().toString(36);MX.order.push(id);MX.roles[id]=k}
   await roll(id,false,+tid);if(!MX.on)play(true);return}
  if(ds.mxsong){const [s,tid]=ds.mxsong.split(':');MX.find=null;await roll(s,false,+tid);if(!MX.on)play(true);return}
  if(t.id==='mxsave'||t.id==='mxkeepsn'||t.id==='mxdropsn'){const name=($('mxname').value||'').trim()||MX.name||`Mix ${new Date().toLocaleString()}`;
   if(MX._saving)return;
   // a strip that came with another saved combination doesn't silently become part of this one
   if(t.id==='mxsave'&&(MX.snaps||[]).length&&MX.snapsOf&&MX.snapsOf!==name){MX.ask=name;draw();return}
   if(t.id==='mxdropsn'){MX.snaps=[];MX.trans=[];MX.snapSel=null}
   MX.ask=null;MX.name=name;MX.snapsOf=(MX.snaps||[]).length?name:null;save();
   const mix=JSON.parse(localStorage.getItem('dcStems')||'{}'),savedSig=sig();
   MX._saving=true;markSave();
   try{
    const r=await api('api/stems/save',{name,mix,state:state()});
    MX.rated=r.rated;MX.savedSig=savedSig;save();await refreshSaved();toast(`saved “${name}”`);
   }catch(err){toast('not saved: '+err.message+' (your combination is still here: try again)')}
   finally{MX._saving=false;draw()}
   return}
  if(t.id==='mxaskno'){MX.ask=null;draw();return}
  if(t.id==='mxexport'){const now=BLEND.snapNow(),L8='ABCDEFGH',secs=(MX.snaps||[]).length?MX.snaps.map((sn,k)=>({label:L8[k],order:sn.order,roles:sn.roles,slots:sn.slots})):[{label:MX.name||'Mashup',order:now.order,roles:now.roles,slots:now.slots}];
   const name=(MX.name||'').trim()||`Mashup ${new Date().toISOString().slice(0,10)}`;t.disabled=true;t.textContent='exporting…';
   try{const r=await api('api/stems/export',{name,bpm:MX.bpm,key:MX.key||(MX.info&&MX.info.key)||null,sections:secs,bars:MX.exBars||8});
    toast(`Live set → Mashups/${name}/${r.als} · ${r.tracks} tracks, ${r.sections} section${r.sections>1?'s':''} of ${r.bars} bars, dry`)}catch(err){toast('export failed: '+err.message)}draw();return}
  if(t.id==='mxrevert'){await refreshSaved();const m=(MX.saved||[]).find(x=>x.name===MX.name);if(!m){toast('no saved copy of this one');return}await openSaved(m);toast(`back to “${m.name}” as saved`);return}
  if(t.id==='mxdelsaved'){await api('api/stems/delete',{name:MX.name});await refreshSaved();toast(`deleted “${MX.name}”`);MX.name='';MX.savedSig=null;save();draw();return}
  if(t.id==='mxup'){ev('like');toast('👍 noted: more like this');return}
  if(t.id==='mxdown'){ev('dislike');MX.order.forEach(s=>{if(MX.slots[s])MX.slots[s].since=null});await rollAll();return}
  if(ds.mxroll){await roll(ds.mxroll);if(!MX.on)play(true);return}
  if(ds.mxlock){const p=MX.slots[ds.mxlock];p.lock=!p.lock;if(p.lock)ev('lock',ds.mxlock);save();draw();return}
  if(ds.mxsolo){const p=MX.slots[ds.mxsolo];p.solo=!p.solo;MX.order.forEach(apply);draw();return}
  if(ds.mxmute){const p=MX.slots[ds.mxmute];p.mute=!p.mute;MX.order.forEach(apply);save();draw();return}});
 L.addEventListener('input',e=>{if(st.tab!=='M')return;const t=e.target,ds=t.dataset;
  if(t.id==='mxq'){MX.find.q=t.value;draw();return}if(t.id==='mxname'){MX.name=t.value;return}
  if(ds.mxdb){MX.slots[ds.mxdb].db=+t.value;apply(ds.mxdb);t.title=dbv(+t.value)+' · double-click for 0 dB'}
  else if(ds.mxfade){const [id,w]=ds.mxfade.split(':'),p=MX.slots[id];p[w]=+t.value;t.nextElementSibling.textContent=t.value+' ms';osTrimDraw(id,p)}
  else if(ds.mxpcxf){t.nextElementSibling.textContent=t.value+' ms'}
  else if(t.id==='mxrvdecay'){t.parentNode.querySelector('output').textContent=(+t.value).toFixed(1)+' s'}markSave()});
 L.addEventListener('change',async e=>{if(st.tab!=='M')return;const t=e.target,ds=t.dataset;
  if(t.id==='mxmaster'){MX.mast.on=t.checked;BLEND.mxRoute(MX);mxMeter();save();markSave();return}
  if(t.id==='mxglue'){MX.glue.on=t.checked;MX.bus?.g?.set(MX.glue.on);mxMeter();save();markSave();return}
  if(t.id==='mxbpm'){MX.bpm=Math.max(50,Math.min(200,+t.value||100));const was=MX.on;if(was)play(false);await sync();MX.order.forEach(apply);if(was)play(true);return}
  if(t.id==='mxkey'){MX.key=t.value;await sync();return}
  if(t.id==='mxexbars'){MX.exBars=+t.value;return}
  if(t.id==='mxrvtype'){BLEND.out(MX,AC);BLEND.setReverb(MX,t.value);save();draw();return}        // a type brings its own decay
  if(t.id==='mxrvdecay'){BLEND.out(MX,AC);BLEND.setReverb(MX,MX.reverb.type,+t.value);save();markSave();return}  // (on release: the room is rebuilt)
  if(ds.mxrole){const id=ds.mxrole,old=MX.slots[id];if(MX.roles[id]===t.value)return;stopSrc(id);MX.roles[id]=t.value;  // a new role: a new part of that kind, the slot's mix settings stay
   if(old)MX.slots[id]={db:old.db,mute:old.mute,solo:old.solo,eq:old.eq,dly:old.dly,dt:old.dt,fb:old.fb,eqOn:old.eqOn,dlyOn:old.dlyOn,rev:old.rev,revOn:old.revOn,_c:old._c,n:old.n,_v:old._v,_viewMode:old._viewMode,_preset:old._preset,_blank:true};
   apply(id);  // reroute any echoes while the new part loads
   await roll(id);if(MX.slots[id]&&MX.slots[id]._blank){retire(id);delete MX.slots[id];await sync()}return}
  if(t.id==='mxload'){const m=(MX.saved||[]).find(x=>x.name===t.value);if(!m)return;await openSaved(m);return}
  if(ds.mxpcxf){const p=MX.slots[ds.mxpcxf];p.xf=+t.value;await setCut(ds.mxpcxf,cutOf(p));return}
  if(ds.mxpcb||ds.mxpcl||ds.mxpcs||ds.mxpcn){const [id,i]=(ds.mxpcb||ds.mxpcl||ds.mxpcs||ds.mxpcn).split(':'),cut=cutOf(MX.slots[id]);
   if(ds.mxpcb){const v=parseFloat(t.value);if(!Number.isFinite(v))return;cut[+i][0]=v-1}else if(ds.mxpcl)cut[+i][1]=+t.value;
   else if(ds.mxpcs){cut[+i][2]=cut[+i][2]||0;cut[+i][3]=+t.value}else{cut[+i][2]=cut[+i][2]||0;cut[+i][3]=cut[+i][3]||1;cut[+i][4]=+t.value}
   await setCut(id,cut);return}
  if(ds.mxwarp){const p=MX.slots[ds.mxwarp];p.warp=+t.value;p._next=null;await sync();return}
  if(ds.mxwarpn){const p=MX.slots[ds.mxwarpn],v=+t.value;p.warp=v>0?Math.max(0.1,Math.min(32,Math.round(v*100)/100)):0;p._next=null;await sync();return}
  if(ds.mxfade){save();return}
  if(ds.mxevery){MX.slots[ds.mxevery].every=+t.value;save();draw();return}
  if(ds.mxlen&&isOS(ds.mxlen)){const p=MX.slots[ds.mxlen];p.n=+t.value;p.steps=(p.steps||[]).filter(k=>k<p.n*16);p.fit=null;p._next=null;save();draw();
   api('api/stems/oneshot',{state:state(),n:p.n,path:p.sample}).then(r=>{if(r.part&&MX.slots[ds.mxlen]===p){p.fit=r.part.fit;save();draw()}}).catch(()=>{});return}  // how it fits each bar of the new cycle
  save()});
 L.addEventListener('keydown',e=>{if(st.tab!=='M'||e.target.id!=='mxq')return;if(e.key==='Enter'){const b=document.querySelector('.mxfind [data-mxsong]');if(b)b.click()}else if(e.key==='Escape'){MX.find=null;draw()}e.stopPropagation()});
 {let dr=null;const fr=(c,e)=>Math.max(0,Math.min(1,(e.clientX-c.getBoundingClientRect().left)/c.clientWidth));
  L.addEventListener('mousedown',e=>{const c=e.target.closest&&e.target.closest('canvas[data-mxtrim]');if(!c||st.tab!=='M')return;e.preventDefault();const id=c.dataset.mxtrim,p=MX.slots[id];if(!p||!p.buf)return;
   const f=fr(c,e),[a,b]=osTrim(p),px=6/c.clientWidth,nearA=p.trim&&Math.abs(f-a)<=px,nearB=p.trim&&Math.abs(f-b)<=px;
   dr={c,id,p,anchor:nearA&&(!nearB||Math.abs(f-a)<Math.abs(f-b))?b:nearB?a:f,moved:false,last:f,cur:nearA&&(!nearB||Math.abs(f-a)<Math.abs(f-b))?a:nearB?b:f}});
  window.addEventListener('mousemove',e=>{if(!dr)return;const raw=fr(dr.c,e);dr.cur=Math.max(0,Math.min(1,dr.cur+(raw-dr.last)*(e.shiftKey?0.1:1)));dr.last=raw;const f=dr.cur;  // shift: ten times finer
   dr.moved=true;dr.p.trim=[Math.min(dr.anchor,f),Math.max(dr.anchor,f)];osTrimDraw(dr.id,dr.p);const box=document.querySelector(`[data-mxwave="${dr.id}"]`);if(box)osWave(dr.id,dr.p,box)});
  window.addEventListener('mouseup',()=>{if(!dr)return;const {id,p,moved}=dr;dr=null;if(!moved)return;  // a plain click changes nothing (and mustn't redraw: a double-click needs the same canvas twice)
   if(!p.trim||p.trim[1]-p.trim[0]<0.01||(p.trim[0]<0.005&&p.trim[1]>0.995))p.trim=null;save();draw();refreshShot(id)});
  L.addEventListener('dblclick',e=>{const c=e.target.closest&&e.target.closest('canvas[data-mxtrim]');if(!c||st.tab!=='M')return;const p=MX.slots[c.dataset.mxtrim];if(p){p.trim=null;save();draw();refreshShot(c.dataset.mxtrim)}})}
 L.addEventListener('dblclick',e=>{if(st.tab!=='M')return;const t=e.target,ds=t.dataset||{};if(ds.mxdb){MX.slots[ds.mxdb].db=0;t.value=0;t.title=dbv(0)+' · double-click for 0 dB';apply(ds.mxdb)}
  save();markSave()});
 BLEND.init({MX,STEMS,ICON,PITCHED,DT,role,state,save,draw,sync,play,apply,retire,ev,barLenM,refreshSongs,split:splitKits});
 TR.init({MX,AC,role,isOS,refreshShot,part:id=>MX.slots[id],apply,sync,save,mark:markSave,draw,loop:setLoop,pitch:id=>{
  const p=MX.slots[id];
  hpush(id);
  const entry=MX.hist[id]?.[MX.hpos[id]];
  if(entry){entry.off=p.off;entry.ct=p.ct}
  if(isOS(id)&&p.buf)draw()
 }});
 // the tab
 $('tabY').insertAdjacentHTML('afterend',`<button id="tabM" title="recombine drums, bass, vocals and the rest from different songs">🎛 Mashup</button>`);
 $('tabM').onclick=()=>{st.tab='M';render()};
 const _rM=render;render=function(...a){$('tabM').classList.toggle('on',st.tab==='M');if(st.tab!=='M'){TR.closeMenu();document.body.classList.remove('mash');if(MX._refit){MX._refit=false;if(typeof scheduleRefit==='function')scheduleRefit()}return _rM.apply(this,a)}
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.id==='tabM'));try{localStorage.setItem('dcTab','M')}catch(e){}
  document.body.classList.add('wide','mash');['cats','subsBox','sbanner','tbanner'].forEach(id=>{if($(id))$(id).hidden=true});$('count').textContent='mashup';draw();
  if(MX.saved==null){MX.saved=[];refreshSaved().then(draw)}
  if(MX.n==null)refreshSongs().then(()=>{if(MX.n==null)MX.n=0;draw();if(MX.n&&(MX.order.some(s=>MX.slots[s])||MX.snaps.length))sync()})};
 try{if(localStorage.getItem('dcTab')==='M'){st.tab='M';render()}}catch(e){}  // back on this tab after a refresh
 // ＋ Mashup in the sample panel: a short sample goes into a one-shot slot (an empty one, else a new one)
 async function addOneShot(i){const path=S[i][F_.path];if(S[i][F_.dur]>2*barLenM()+0.05){toast(`too long for a one-shot at ${MX.bpm} bpm (two bars at most)`);return}
  let id=MX.order.find(x=>isOS(x)&&!MX.slots[x]);if(!id){if(MX.order.length>=8){toast('the mashup is full (8 slots)');return}id='s'+Date.now().toString(36);MX.order.push(id);MX.roles[id]='oneshot'}
  await roll(id,true,path);toast(MX.slots[id]?'added to Mashup as a one-shot: place its hits there':'that sample can\'t be a one-shot');save();draw()}
 window.CRATE.mxAddOneShot=addOneShot;
 const _selOS=select;select=function(i,from){_selOS(i,from);if(!SERVED||!S[i]||S[i][F_.dur]>8||S[i][F_.cat]==='Percussion'&&S[i][F_.kind]!=='oneshot')return;const xb=document.querySelector('#detail [data-xp]');
  if(xb&&!$('mxosadd'))xb.insertAdjacentHTML('afterend',`<button id="mxosadd" data-i="${i}" title="put it in the Mashup as a one-shot: it plays at the steps you choose, shifted to the mashup's key">✦ Mashup</button>`)};
 document.addEventListener('click',e=>{const b=e.target.closest('#mxosadd');if(b)addOneShot(+b.dataset.i)});
 if(typeof scheduleRefit==='function'){const _sr=scheduleRefit;scheduleRefit=function(){if(st.tab==='M'){MX._refit=true;return}_sr()}}
 const partId=p=>p?[cutKey(p),p.stem,p.track,p.sample,p.bar0,p.n,p.k||1,p.off||0,p.ct||0,!!p.legacyLoop,!!p.kit,p.cond||0,p.hk||'',p.hup||''].join('|'):'';
 async function undoGo(d){save();const from=d<0?UN.u:UN.r,to=d<0?UN.r:UN.u;if(!from.length){toast(d<0?'nothing to undo':'nothing to redo');return}
  to.push(UN.cur);UN.cur=from.pop();UN.busy=true;
  try{const sv=JSON.parse(UN.cur),old=MX.slots,keep={};
   // a slot whose part is the same keeps playing (only its settings change); the others stop and come back in
   MX.order.forEach(id=>{const o=old[id],n=(sv.slots||{})[id];if(o&&n&&partId(o)===partId(n)&&(sv.roles||{})[id]===MX.roles[id])keep[id]=o;else retire(id)});
   MX.bpm=sv.bpm||MX.bpm;MX.key=sv.key||'';MX.fx=sv.fx!==false;if(sv.reverb)BLEND.setReverb(MX,sv.reverb.type,sv.reverb.decay);
   restore(sv);Object.entries(keep).forEach(([id,o])=>{if(MX.slots[id]){MX.slots[id]=Object.assign(o,MX.slots[id])}});
   MX.info=null;await sync();MX.order.forEach(apply)}catch(e){toast('undo: '+e.message)}finally{UN.busy=false}
  save();markSave();draw();toast(d<0?'undone · ⌘⇧Z to redo':'redone')}
 // ⌘Z / ⌘⇧Z on this tab undo and redo in the mashup (not the sketch); while typing, they stay the text field's own
 window.addEventListener('keydown',e=>{if(st.tab!=='M'||!(e.metaKey||e.ctrlKey)||e.key.toLowerCase()!=='z')return;const t=e.target,tag=t.tagName;
  if(tag==='TEXTAREA'||t.isContentEditable||(tag==='INPUT'&&!['range','checkbox','button'].includes(t.type)))return;
  e.preventDefault();e.stopImmediatePropagation();if(!e.repeat)undoGo(e.shiftKey?1:-1)},true);
 window.CRATE.mxUndo=undoGo;save();
 document.addEventListener('pointerdown',e=>{if(st.tab!=='M'||!MX.splice||!e.altKey||!e.target.closest)return;const box=e.target.closest(`[data-mxwave="${CSS.escape(MX.splice)}"]`);if(!box)return;
  const id=MX.splice,b=TR.barAt(id,e.clientX,e.shiftKey);if(b==null)return;e.preventDefault();e.stopImmediatePropagation();
  const cut=cutOf(MX.slots[id]);cut.push([b,e.shiftKey?0.5:1]);setCut(id,cut)},true);
 // drag to rearrange: a splice's pieces (its blocks, or the numbers of its rows), and the tracks (by their names)
 let dragged=null;
 document.addEventListener('dragstart',e=>{if(st.tab!=='M'||!e.target.closest)return;const pc=e.target.closest('[data-mxpci]'),tr=e.target.closest('[data-mxtrdrag]');
  if(pc){const [id,i]=pc.dataset.mxpci.split(':');dragged={kind:'piece',id,i:+i}}else if(tr)dragged={kind:'track',id:tr.dataset.mxtrdrag};else return;
  e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain','')}catch(err){}});
 const dropAt=e=>{if(!dragged||!e.target.closest)return null;
  if(dragged.kind==='piece'){const pc=e.target.closest('[data-mxpci]');if(!pc)return null;const [id,i]=pc.dataset.mxpci.split(':');return id===dragged.id?{i:+i}:null}
  const row=e.target.closest('[data-mxrow]');return row&&MX.order.includes(row.dataset.mxrow)?{id:row.dataset.mxrow,row}:null};
 document.addEventListener('dragover',e=>{if(st.tab==='M'&&dropAt(e)){e.preventDefault();e.dataTransfer.dropEffect='move'}});
 document.addEventListener('dragend',()=>{dragged=null});
 document.addEventListener('drop',e=>{if(st.tab!=='M')return;const to=dropAt(e),d=dragged;dragged=null;if(!to||!d)return;e.preventDefault();
  if(d.kind==='piece'){if(to.i===d.i)return;const cut=cutOf(MX.slots[d.id]),[pc]=cut.splice(d.i,1);cut.splice(to.i,0,pc);setCut(d.id,cut);return}
  if(to.id===d.id)return;const r=to.row.getBoundingClientRect(),after=e.clientY>r.top+r.height/2,order=MX.order.filter(x=>x!==d.id);
  order.splice(order.indexOf(to.id)+(after?1:0),0,d.id);MX.order=order;save();markSave();draw()});
 // an open search closes with Esc from anywhere, or a click outside it
 window.addEventListener('keydown',e=>{if(st.tab==='M'&&e.key==='Escape'&&MX.find){MX.find=null;draw()}});
 document.addEventListener('pointerdown',e=>{if(st.tab!=='M'||!MX.find||!e.target.closest)return;if(e.target.closest('.mxfind,.trmenu,[data-trmore],[data-mxfind]'))return;MX.find=null;setTimeout(draw,0)},true);
 // ⌘S on this tab saves the mashup (not the sketch)
 window.addEventListener('keydown',e=>{if(st.tab!=='M'||!(e.metaKey||e.ctrlKey)||e.key.toLowerCase()!=='s')return;e.preventDefault();e.stopImmediatePropagation();const b=$('mxsave');if(b&&!b.disabled)b.click()},true);
 // space starts and stops the mashup (the strip while it is open), whatever control has the focus: it presses the play
 // button and nothing else. In a text or number box it is typed as usual.
 const textBox=el=>!!el&&(el.isContentEditable||el.tagName==='TEXTAREA'||el.tagName==='INPUT'&&!['range','checkbox','radio','button'].includes(el.type));
 let spaceDown=false;
 window.addEventListener('keydown',e=>{if(e.key!==' '||st.tab!=='M'||e.metaKey||e.ctrlKey||e.altKey||textBox(e.target))return;
  const b=$('pbplay')||$('mxplay');if(!b)return;
  e.preventDefault();e.stopImmediatePropagation();spaceDown=true;if(!e.repeat)b.click()},true);
 // a focused button, switch or list would act on the key's release
 window.addEventListener('keyup',e=>{if(e.key!==' '||!spaceDown)return;spaceDown=false;e.preventDefault();e.stopImmediatePropagation()},true);
 window.CRATE.TR=TRACKS;window.CRATE.mxSig=sig;window.CRATE.MX=MX;window.CRATE.mxRoll=roll;window.CRATE.mxRollAll=rollAll;window.CRATE.mxPlay=play;window.CRATE.mxSync=sync;window.CRATE.mxRefreshSongs=refreshSongs}
// ---------- sliders: keep each one's fill (--a .. --b, see studio.css) in step with its value. The fill runs from the
// minimum, or from zero when the range spans it (EQ, tune, dB), so "all the way down" and "0" both look off.
{const paint=el=>{const mn=+el.min||0,mx=el.max===''?100:+el.max,v=+el.value,span=mx-mn||1,p=Math.max(0,Math.min(1,(v-mn)/span)),z=mn<0&&mx>0?(0-mn)/span:0;
  el.style.setProperty('--a',Math.min(p,z).toFixed(4));el.style.setProperty('--b',Math.max(p,z).toFixed(4))};
 let q=0;const all=()=>{q=0;document.querySelectorAll('input[type=range]').forEach(paint)},soon=()=>{if(!q)q=requestAnimationFrame(all)};
 document.addEventListener('input',e=>{if(e.target&&e.target.type==='range')paint(e.target)},true);
 ['change','click','dblclick','keyup'].forEach(t=>document.addEventListener(t,soon,true));
 new MutationObserver(soon).observe(document.body,{childList:true,subtree:true});all()}
