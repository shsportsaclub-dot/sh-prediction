/* SH SOCIAL, accounts, Reels, creator dashboard, game viewer and live updates for the SH PREDICTION viewer site.
   Loaded after hub.html's main script; uses its helpers (api, t, esc, $, SCREENS, TOKEN...). */
"use strict";
const SOC={feed:sessionStorage.getItem("shp_feed")||"for_you"};
const needLogin=()=>{if(!TOKEN){location.hash="#/account";return true}return false};
const ago=u=>{const s=(Date.now()-new Date(u))/1000;return s<60?"now":s<3600?Math.floor(s/60)+"m":s<86400?Math.floor(s/3600)+"h":new Date(u).toLocaleDateString(LANG)};
const authorLine=a=>'<a href="#/u/'+esc(a.username||"")+'" style="color:inherit;text-decoration:none"><b>'+esc(a.display_name||a.username)+'</b> <span class="muted">@'+esc(a.username||"")+'</span></a>'+
 (a.verified_expert?' <span class="tag ver">Expert</span>':a.account_type==="tipster"?' <span class="tag">Tipster</span>':'')+(a.creator_verified?' <span class="tag ver">Creator</span>':'');
function mediaHtml(p){
 if(!p.media.length)return "";
 return '<div class="gal">'+p.media.map(m=>{if(!m)return "";if(m.status!=="ready")return '<div class="state">'+esc(t("so.processing"))+'</div>';
  if(m.kind==="image")return '<img loading="lazy" src="'+esc(m.urls.image_lg||m.urls.thumb)+'" alt="Photo by '+esc(p.author.username)+'" data-full="'+esc(m.urls.image_lg)+'">';
  return '<video controls playsinline preload="metadata" poster="'+esc(m.urls.thumb||"")+'" data-post="'+p.id+'" src="'+esc(m.urls.mp4)+'"></video>'}).join("")+'</div>'}
function pickHtml(p){if(!p.pick)return "";const k=p.pick,res={correct:"o-won",incorrect:"o-lost"}[k.result]||"o-unknown";
 return '<div class="card" style="margin:8px 0;background:var(--surface2)"><b>'+esc(t("so.pick"))+':</b> '+esc((k.prediction_type||"").replace("_"," "))+' · <b>'+esc(k.team||k.predicted_value)+'</b>'+(k.confidence!=null?' · '+k.confidence+'%':'')+
  '<div class="muted">Locked '+when(k.locked_at)+(k.match_result?' · Result: '+esc(k.match_result.winner||k.match_result.result_type):'')+' · <span class="'+res+'">'+esc(k.result||"pending")+'</span></div></div>'}
function pollHtml(p){if(!p.poll)return "";const tot=p.poll.votes.reduce((a,b)=>a+b,0)||1;
 return '<div>'+p.poll.options.map((o,i)=>'<button class="pv" data-p="'+p.id+'" data-o="'+i+'" style="display:block;width:100%;text-align:left;margin:4px 0">'+esc(o)+' <span class="muted">'+Math.round(100*p.poll.votes[i]/tot)+'%</span>'+(p.poll.my_vote===i?' ✓':'')+'</button>').join("")+'</div>'}
function postCard(p){const me=p.me||{};
 return '<article class="card post" data-id="'+p.id+'"><div class="row"><span class="grow">'+authorLine(p.author)+' <span class="muted">· '+ago(p.created_at)+(p.edits?' · edited':'')+'</span></span>'+(p.data_origin==="demo"?'<span class="tag demo">DEMO</span>':'')+'</div>'+
  (p.match?'<div class="muted"><a href="#/match/'+p.match.id+'/community">'+esc(p.match.home)+' vs '+esc(p.match.away)+'</a></div>':'')+
  (p.body?'<p style="white-space:pre-wrap;margin:8px 0">'+linkify(p.body)+'</p>':'')+mediaHtml(p)+pickHtml(p)+pollHtml(p)+
  '<div class="row muted" style="margin-top:8px"><button class="act lk" aria-pressed="'+!!me.liked+'">'+(me.liked?"♥":"♡")+' '+p.counts.likes+'</button><a class="btn" href="#/post/'+p.id+'">💬 '+p.counts.comments+'</a><button class="act sh">↗ '+p.counts.shares+'</button><button class="act sv" aria-pressed="'+!!me.saved+'">'+(me.saved?"★":"☆")+'</button><span class="grow"></span><span>'+p.counts.views+' '+esc(t("so.views"))+'</span>'+
  (me.is_author?'<button class="act ed">'+esc(t("so.edit"))+'</button><button class="act del">'+esc(t("so.delete"))+'</button>':(TOKEN?'<button class="act rp">'+esc(t("so.report"))+'</button>':''))+'</div></article>'}
function linkify(s){return esc(s).replace(/(^|\s)#([A-Za-z0-9_]{2,40})/g,'$1<a href="#/tag/$2">#$2</a>').replace(/(^|\s)@([a-z0-9_]{3,24})/g,'$1<a href="#/u/$2">@$2</a>')}
function bindPosts(root,reload){
 root.querySelectorAll("article.post").forEach(a=>{const id=a.dataset.id,q=s=>a.querySelector(s);
  api("/social/posts/"+id+"/view",{method:"POST",body:"{}"}).catch(()=>{});
  if(q(".lk"))q(".lk").onclick=async()=>{if(needLogin())return;const on=q(".lk").getAttribute("aria-pressed")!=="true";try{const r=await api("/social/posts/"+id+"/"+(on?"like":"unlike"),{method:"POST",body:"{}"});q(".lk").textContent=(on?"♥ ":"♡ ")+r.likes;q(".lk").setAttribute("aria-pressed",on)}catch(e){alert(e.message)}};
  if(q(".sv"))q(".sv").onclick=async()=>{if(needLogin())return;const on=q(".sv").getAttribute("aria-pressed")!=="true";await api("/social/posts/"+id+"/"+(on?"save":"unsave"),{method:"POST",body:"{}"});q(".sv").textContent=on?"★":"☆";q(".sv").setAttribute("aria-pressed",on)};
  if(q(".sh"))q(".sh").onclick=async()=>{const url=location.origin+"/#/post/"+id;try{if(navigator.share)await navigator.share({url,title:"SH PREDICTION"});else{await navigator.clipboard.writeText(url);alert("Link copied")}}catch(e){}const r=await api("/social/posts/"+id+"/share",{method:"POST",body:JSON.stringify({channel:navigator.share?"other":"link"})});q(".sh").textContent="↗ "+r.shares};
  if(q(".rp"))q(".rp").onclick=async()=>{const r=prompt(t("so.report")+" — reason?");if(r)try{await api("/social/reports",{method:"POST",body:JSON.stringify({target_type:"post",target_id:+id,reason:r})});alert("Reported")}catch(e){alert(e.message)}};
  if(q(".ed"))q(".ed").onclick=async()=>{const b=prompt(t("so.edit"),a.querySelector("p")?a.querySelector("p").innerText:"");if(b!=null){await api("/social/posts/"+id+"/edit",{method:"POST",body:JSON.stringify({body:b})});reload&&reload()}};
  if(q(".del"))q(".del").onclick=async()=>{if(confirm(t("so.delete")+"?")){await api("/social/posts/"+id+"/delete",{method:"POST",body:"{}"});a.remove()}};
  a.querySelectorAll(".pv").forEach(b=>b.onclick=async()=>{if(needLogin())return;await api("/social/posts/"+b.dataset.p+"/vote",{method:"POST",body:JSON.stringify({option:+b.dataset.o})});reload&&reload()});
  a.querySelectorAll("video").forEach(v=>watchTrack(v,v.dataset.post));
  a.querySelectorAll("img[data-full]").forEach(i=>i.onclick=()=>{const o=document.createElement("div");o.className="lightbox";o.innerHTML='<img src="'+i.dataset.full+'" alt="">';o.onclick=()=>o.remove();document.body.append(o)})})}
function watchTrack(v,id){let sent=false;const send=()=>{if(sent||!v.duration)return;sent=true;api("/social/posts/"+id+"/watch",{method:"POST",body:JSON.stringify({watched_ms:Math.round(v.currentTime*1000)})}).catch(()=>{})};v.addEventListener("pause",send);v.addEventListener("ended",()=>{v.currentTime=v.duration;send()})}

Object.assign(SCREENS,{
async social(el){
 const feeds=[["for_you","so.for_you"],["following","so.following"],["latest","so.latest"],["trending","so.trending"],["saved","so.saved"]];
 el.innerHTML='<div class="row"><h2 class="grow">'+esc(t("nav.social"))+'</h2><a class="btn primary" href="#/compose">+ '+esc(t("so.compose"))+'</a></div><input id="ss" type="search" style="width:100%" placeholder="'+esc(t("so.search"))+'"><div class="chips" id="ft" style="margin-top:8px"></div><div id="tags" class="chips"></div><div id="fd">'+loading()+'</div>';
 const draw=()=>{$("#ft").innerHTML=feeds.map(([k,l])=>'<button class="'+(k===SOC.feed?"on":"")+'" data-f="'+k+'">'+esc(t(l))+'</button>').join("");document.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{SOC.feed=b.dataset.f;sessionStorage.setItem("shp_feed",SOC.feed);draw();go()})};
 const go=async(off=0)=>{const F=$("#fd");if(!off)F.innerHTML=loading();const q=$("#ss").value.trim();
  if((SOC.feed==="following"||SOC.feed==="saved")&&!TOKEN){F.innerHTML=emptyS(t("so.login_needed"));return}
  try{const j=await api("/social/feed?feed="+(q?"search&q="+encodeURIComponent(q):SOC.feed)+"&limit=20&offset="+off+(DEMO()?"&dataset=demo":""));
   const html=j.items.map(postCard).join("")+(j.has_more?'<p><button id="more" data-o="'+(off+20)+'">More</button></p>':'');
   if(off){$("#more").parentNode.remove();F.insertAdjacentHTML("beforeend",html)}else F.innerHTML=j.items.length?html:emptyS();
   bindPosts(F,()=>go());if($("#more"))$("#more").onclick=e=>go(+e.target.dataset.o)}catch(e){errorS(F,e,()=>go())}};
 draw();go();let tm;$("#ss").oninput=()=>{clearTimeout(tm);tm=setTimeout(()=>go(),350)};
 api("/social/hashtags/trending").then(j=>{$("#tags").innerHTML=j.items.map(x=>'<a class="btn" href="#/tag/'+esc(x.tag)+'">#'+esc(x.tag)+' <span class="muted">'+x.posts+'</span></a>').join("")}).catch(()=>{})},
async tag(el,tag){el.innerHTML='<p><a href="#/social">← '+esc(t("nav.social"))+'</a></p><h2>#'+esc(tag)+'</h2><div id="fd">'+loading()+'</div>';
 try{const j=await api("/social/feed?feed=hashtag&tag="+encodeURIComponent(tag));$("#fd").innerHTML=j.items.length?j.items.map(postCard).join(""):emptyS();bindPosts($("#fd"))}catch(e){errorS($("#fd"),e,()=>SCREENS.tag(el,tag))}},
async post(el,id){el.innerHTML=loading();
 try{const [p,cm]=await Promise.all([api("/social/posts/"+id),api("/social/posts/"+id+"/comments")]);
  el.innerHTML='<p><a href="#/social">← '+esc(t("nav.social"))+'</a></p>'+postCard(p)+'<div class="card"><h3>'+esc(t("so.comment"))+'</h3>'+(cm.items.map(c=>'<div style="padding:6px 0;border-bottom:1px solid var(--line);'+(c.parent_id?'margin-left:18px':'')+'"><a href="#/u/'+esc(c.username)+'"><b>'+esc(c.display_name)+'</b></a> <span class="muted">'+ago(c.created_at)+'</span><div>'+linkify(c.body)+'</div>'+(TOKEN?'<button class="act rc" data-c="'+c.id+'" style="padding:2px 8px">↩</button>':'')+'</div>').join("")||'<p class="muted">—</p>')+
   (TOKEN?'<form id="cf" class="row" style="margin-top:8px"><input id="cb" class="grow" maxlength="1000" placeholder="'+esc(t("so.comment"))+'"><button class="primary">'+esc(t("so.post"))+'</button></form>':'<p><a href="#/account">'+esc(t("so.login_needed"))+'</a></p>')+'</div>';
  bindPosts(el,()=>SCREENS.post(el,id));let parent=null;
  el.querySelectorAll(".rc").forEach(b=>b.onclick=()=>{parent=+b.dataset.c;$("#cb").focus();$("#cb").placeholder="↩ reply"});
  if($("#cf"))$("#cf").onsubmit=async e=>{e.preventDefault();try{await api("/social/posts/"+id+"/comments",{method:"POST",body:JSON.stringify({body:$("#cb").value,parent_id:parent})});SCREENS.post(el,id)}catch(err){alert(err.message)}}}
 catch(e){errorS(el,e,()=>SCREENS.post(el,id))}},
async u(el,username){el.innerHTML=loading();
 try{const p=await api("/social/users/"+encodeURIComponent(username));const s=p.prediction_stats,me=p.me||{};
  el.innerHTML=(p.cover?'<img src="'+esc(p.cover)+'" alt="" style="width:100%;max-height:180px;object-fit:cover;border-radius:14px">':'')+'<div class="card"><div class="row">'+(p.avatar?'<img src="'+esc(p.avatar)+'" alt="" style="width:64px;height:64px;border-radius:50%;object-fit:cover">':'')+'<div class="grow"><h2 style="margin:0">'+esc(p.display_name)+'</h2><div class="muted">@'+esc(p.username)+' · joined '+esc(p.joined)+'</div></div>'+
   (me.is_me?'<a class="btn" href="#/dashboard">'+esc(t("so.dashboard"))+'</a>':TOKEN?'<button id="fw" class="'+(me.following?'':'primary')+'">'+esc(t(me.following?"so.unfollow":"so.follow"))+'</button><button id="bk">'+esc(t("so.block"))+'</button>':'')+'</div>'+
   (p.bio?'<p>'+linkify(p.bio)+'</p>':'')+'<div class="stats">'+stat(p.followers,t("so.followers"))+stat(p.posts,t("so.posts"))+stat(p.total_views,t("so.views"))+(s.settled?stat(s.accuracy+"%",t("acc.overall")):'')+'</div>'+
   (s.total_predictions?'<p class="muted">'+s.correct+' '+esc(t("acc.correct"))+' · '+s.incorrect+' '+esc(t("acc.incorrect"))+' · '+s.pending+' '+esc(t("acc.pending"))+' · settled '+s.settled+(s.recent_form?' · form '+esc(s.recent_form):'')+'</p>':'')+
   (p.badges.length?'<div class="chips">'+p.badges.map(b=>'<span class="tag ver">'+esc(b)+'</span>').join("")+'</div>':'')+'</div><div class="chips"><button class="on" data-t="posts">'+esc(t("so.posts"))+'</button>'+(s.total_predictions?'<button data-t="preds">'+esc(t("so.prediction"))+'</button>':'')+'</div><div id="ut">'+loading()+'</div>';
  if($("#fw"))$("#fw").onclick=async()=>{await api("/social/users/"+username+"/"+(me.following?"unfollow":"follow"),{method:"POST",body:"{}"});SCREENS.u(el,username)};
  if($("#bk"))$("#bk").onclick=async()=>{if(confirm(t("so.block")+"?")){await api("/social/users/"+username+"/block",{method:"POST",body:"{}"});location.hash="#/social"}};
  const tab=async k=>{document.querySelectorAll("[data-t]").forEach(b=>b.classList.toggle("on",b.dataset.t===k));const U=$("#ut");
   if(k==="posts"){const j=await api("/social/feed?feed=user&username="+encodeURIComponent(username));U.innerHTML=j.items.length?j.items.map(postCard).join(""):emptyS();bindPosts(U)}
   else{const j=await api("/social/users/"+encodeURIComponent(username)+"/predictions");U.innerHTML='<p class="muted">'+esc(j.note)+'</p><table class="simple"><tbody>'+j.items.map(x=>'<tr><td><a href="#/match/'+x.match_id+'/community">'+esc(x.home)+' v '+esc(x.away)+'</a></td><td>'+esc(x.prediction_type)+': <b>'+esc(x.pick||x.predicted_value)+'</b></td><td class="muted">'+when(x.locked_at)+'</td><td class="'+({correct:"o-won",incorrect:"o-lost"}[x.result]||"o-unknown")+'">'+esc(x.result||"pending")+'</td></tr>').join("")+'</tbody></table>'}};
  document.querySelectorAll("[data-t]").forEach(b=>b.onclick=()=>tab(b.dataset.t));tab("posts")}
 catch(e){errorS(el,e,()=>SCREENS.u(el,username))}},
async compose(el){if(needLogin())return;
 const kinds=["text","photo","video","reel","poll","prediction"];let kind="text";
 el.innerHTML='<p><a href="#/social">← '+esc(t("nav.social"))+'</a></p><h2>'+esc(t("so.compose"))+'</h2><div class="chips" id="kd"></div><div class="card"><textarea id="pb" rows="4" maxlength="5000" style="width:100%" placeholder="'+esc(t("so.write"))+'"></textarea><div id="extra"></div>'+
  '<label class="muted">'+esc(t("so.tag_match"))+'<select id="pm" style="width:100%;margin-top:4px"><option value="">—</option></select></label><p id="pmsg" class="muted" role="status"></p><button class="primary" id="go">'+esc(t("so.post"))+'</button></div>';
 const ms=await api(dq("/matches?status=upcoming&limit=50")).catch(()=>({items:[]})),ml=await api(dq("/matches?status=live&limit=20")).catch(()=>({items:[]}));
 const all=[...ml.items,...ms.items];$("#pm").innerHTML+=all.map(m=>'<option value="'+m.id+'">'+esc(m.home.name)+' vs '+esc(m.away.name)+' · '+esc(m.start_utc.slice(0,10))+'</option>').join("");
 const drawK=()=>{$("#kd").innerHTML=kinds.map(k=>'<button class="'+(k===kind?"on":"")+'" data-k="'+k+'">'+esc(t("so."+k))+'</button>').join("");document.querySelectorAll("[data-k]").forEach(b=>b.onclick=()=>{kind=b.dataset.k;drawK();extra()})};
 const extra=()=>{const X=$("#extra");
  if(kind==="photo")X.innerHTML='<input id="pf" type="file" accept="image/jpeg,image/png,image/webp" multiple style="margin:8px 0;width:100%">';
  else if(kind==="video"||kind==="reel")X.innerHTML='<input id="pf" type="file" accept="video/mp4,video/quicktime,video/webm" style="margin:8px 0;width:100%"><p class="muted">'+(kind==="reel"?"9:16 vertical, up to 90 s":"up to 180 s")+'. Only upload videos you own or have permission to use.</p>';
  else if(kind==="poll")X.innerHTML='<input class="po" placeholder="Option 1" style="width:100%;margin:4px 0"><input class="po" placeholder="Option 2" style="width:100%;margin:4px 0"><input class="po" placeholder="Option 3 (optional)" style="width:100%;margin:4px 0">';
  else if(kind==="prediction")X.innerHTML='<p class="muted">'+esc(t("ins.pick_rule"))+' <a href="#/tipster">📋 '+esc(t("td.title"))+' ›</a></p><select id="pt" style="width:100%;margin:4px 0"><option value="winner">'+esc(t("col.winner"))+'</option><option value="toss">'+esc(t("col.toss"))+'</option></select><select id="pk" style="width:100%;margin:4px 0"><option value="">'+esc(t("so.tag_match"))+'</option></select><input id="pc" type="number" min="0" max="100" placeholder="'+esc(t("ai.confidence"))+' %" style="width:100%;margin:4px 0">';
  else X.innerHTML="";
  if(kind==="prediction")$("#pm").onchange=()=>{const m=all.find(x=>x.id==$("#pm").value);$("#pk").innerHTML=m?'<option value="'+m.home.id+'">H · '+esc(m.home.name)+'</option><option value="'+m.away.id+'">A · '+esc(m.away.name)+'</option>':''}};
 drawK();extra();
 $("#go").onclick=async()=>{const msg=$("#pmsg");try{$("#go").disabled=true;const body={kind,body:$("#pb").value};if($("#pm").value)body.match_id=+$("#pm").value;
  if(kind==="photo"||kind==="video"||kind==="reel"){const fs=[...($("#pf").files||[])];if(!fs.length)throw Error("Choose a file");body.media_ids=[];for(const f of fs)body.media_ids.push(await uploadFile(f,kind==="photo"?"image":"video",kind==="reel"?"reel":"post",p=>msg.textContent=t("so.processing").replace("…","")+" "+p+"%"))}
  if(kind==="poll")body.options=[...document.querySelectorAll(".po")].map(i=>i.value.trim()).filter(Boolean);
  if(kind==="prediction"){body.kind=$("#pt").value==="toss"?"toss_prediction":"prediction";body.prediction_type=$("#pt").value;body.predicted_team_id=+$("#pk").value;if($("#pc").value)body.confidence=+$("#pc").value}
  const r=await api("/social/posts",{method:"POST",body:JSON.stringify(body)});msg.textContent=r.status==="processing"?t("so.processing"):"✓";
  if(kind==="prediction"){const P=await api("/social/posts/"+r.post_id).catch(()=>null);const m=all.find(x=>x.id==body.match_id);if(P&&P.prediction_id&&m)return changePanel(el,P.prediction_id,m,body.predicted_team_id,r.post_id)}
  location.hash="#/post/"+r.post_id}
  catch(e){msg.textContent=e.message;$("#go").disabled=false}}},
async reels(el){
 el.innerHTML='<div id="rl" class="reels" aria-label="'+esc(t("nav.reels"))+'">'+loading()+'</div>';
 try{const j=await api("/social/feed?feed=reels&limit=30"+(DEMO()?"&dataset=demo":""));const R=$("#rl");
  if(!j.items.length){R.innerHTML=emptyS();return}
  R.innerHTML=j.items.map(p=>{const m=p.media[0]||{urls:{}};return '<section class="reel" data-id="'+p.id+'"><video playsinline loop muted preload="metadata" poster="'+esc(m.urls.thumb||"")+'" src="'+esc(m.urls.mp4||"")+'"></video>'+
   '<div class="rinfo">'+authorLine(p.author)+'<p>'+linkify(p.body)+'</p></div><div class="ract"><button class="lk" aria-label="'+esc(t("so.like"))+'">'+(p.me&&p.me.liked?"♥":"♡")+'<small>'+p.counts.likes+'</small></button><a class="btn" href="#/post/'+p.id+'" aria-label="'+esc(t("so.comment"))+'">💬<small>'+p.counts.comments+'</small></a><button class="sh" aria-label="'+esc(t("so.share"))+'">↗<small>'+p.counts.shares+'</small></button><button class="sv" aria-label="'+esc(t("so.save"))+'">'+(p.me&&p.me.saved?"★":"☆")+'</button>'+(p.me&&!p.me.following_author&&!p.me.is_author?'<button class="fw" aria-label="'+esc(t("so.follow"))+'">＋</button>':'')+'<button class="mu" aria-label="mute">🔇</button></div></section>'}).join("");
  const io=new IntersectionObserver(es=>es.forEach(e=>{const v=e.target.querySelector("video");if(e.isIntersecting){v.play().catch(()=>{});api("/social/posts/"+e.target.dataset.id+"/view",{method:"POST",body:"{}"}).catch(()=>{})}else if(!v.paused){v.pause()}}),{threshold:.6});
  R.querySelectorAll(".reel").forEach(s=>{const v=s.querySelector("video"),id=s.dataset.id,j2=j.items.find(x=>x.id==id);io.observe(s);watchTrack(v,id);
   v.onclick=()=>v.paused?v.play():v.pause();
   s.querySelector(".mu").onclick=()=>{v.muted=!v.muted;s.querySelector(".mu").textContent=v.muted?"🔇":"🔊"};
   s.querySelector(".lk").onclick=async()=>{if(needLogin())return;const on=!(j2.me&&j2.me.liked);const r=await api("/social/posts/"+id+"/"+(on?"like":"unlike"),{method:"POST",body:"{}"});j2.me=Object.assign(j2.me||{},{liked:on});s.querySelector(".lk").innerHTML=(on?"♥":"♡")+'<small>'+r.likes+'</small>'};
   s.querySelector(".sv").onclick=async()=>{if(needLogin())return;const on=!(j2.me&&j2.me.saved);await api("/social/posts/"+id+"/"+(on?"save":"unsave"),{method:"POST",body:"{}"});j2.me=Object.assign(j2.me||{},{saved:on});s.querySelector(".sv").textContent=on?"★":"☆"};
   s.querySelector(".sh").onclick=async()=>{const url=location.origin+"/#/post/"+id;try{if(navigator.share)await navigator.share({url});else await navigator.clipboard.writeText(url)}catch(e){}const r=await api("/social/posts/"+id+"/share",{method:"POST",body:'{"channel":"link"}'});s.querySelector(".sh").innerHTML='↗<small>'+r.shares+'</small>'};
   const f=s.querySelector(".fw");if(f)f.onclick=async()=>{if(needLogin())return;await api("/social/users/"+j2.author.username+"/follow",{method:"POST",body:"{}"});f.remove()}})}
 catch(e){errorS($("#rl"),e,()=>SCREENS.reels(el))}},
async notifications(el){if(needLogin())return;el.innerHTML='<h2>'+esc(t("so.notifications"))+'</h2><div id="nl">'+loading()+'</div>';
 try{const j=await api("/me/notifications");const txt=n=>{const p=n.params||{};return {follow:"@"+p.by+" followed you",like:"@"+p.by+" liked your post",comment:"@"+p.by+" commented",mention:"@"+p.by+" mentioned you",new_post:"@"+p.by+" posted",media_ready:"Your video is ready",post_removed:"A post was removed: "+(p.reason||""),tipster_approved:"You are now a Tipster"}[n.kind]||n.kind};
  $("#nl").innerHTML=j.items.length?j.items.map(n=>'<a class="card" href="'+(n.params.post_id?"#/post/"+n.params.post_id:n.params.by?"#/u/"+esc(n.params.by):"#/social")+'" style="'+(n.read_at?'':'border-color:var(--brand-blue)')+'">'+esc(txt(n))+' <span class="muted">· '+ago(n.created_at)+'</span></a>').join(""):emptyS();
  api("/me/notifications/read",{method:"POST",body:'{"ids":"all"}'}).catch(()=>{})}catch(e){errorS($("#nl"),e,()=>SCREENS.notifications(el))}},
async dashboard(el){if(needLogin())return;el.innerHTML='<h2>'+esc(t("so.dashboard"))+'</h2><div id="db">'+loading()+'</div>';
 try{const d=await api("/me/dashboard");const p=d.prediction_performance;
  $("#db").innerHTML='<div class="card"><div class="stats">'+stat(d.posts,t("so.posts"))+stat(d.views,t("so.views"))+stat(d.likes,t("so.like"))+stat(d.comments,t("so.comment"))+stat(d.shares,t("so.share"))+stat(d.saves,t("so.save"))+stat(d.followers,t("so.followers"))+stat(Math.round(d.watch_time_ms/1000)+"s","Watch time")+stat(d.reel_completion_rate==null?"—":d.reel_completion_rate+"%","Reel completion")+'</div><p class="muted">'+esc(d.counting_rules)+'</p></div>'+
   '<div class="card"><h3>'+esc(t("so.prediction"))+'</h3><div class="stats">'+stat(p.accuracy==null?"—":p.accuracy+"%",t("acc.overall"))+stat(p.correct,t("acc.correct"))+stat(p.incorrect,t("acc.incorrect"))+stat(p.pending,t("acc.pending"))+stat(p.settled,"settled")+'</div></div>'+
   '<div class="card"><h3>Daily views</h3><canvas id="dv" width="700" height="160"></canvas></div><div class="card"><h3>Monthly</h3><table class="simple"><tbody>'+d.monthly.map(m=>'<tr><td>'+esc(m.month)+'</td><td>'+m.posts+' '+esc(t("so.posts"))+'</td><td>'+m.views+' '+esc(t("so.views"))+'</td></tr>').join("")+'</tbody></table></div>';
  drawBars($("#dv"),d.engagement_trend_daily_views.slice().reverse().map(x=>x.views),[])}catch(e){errorS($("#db"),e,()=>SCREENS.dashboard(el))}},
async more(el){el.innerHTML='<h2>'+esc(t("nav.more"))+'</h2>'+[["#/ai","nav.ai"],["#/assistant","nav.assistant"],["#/accuracy","nav.accuracy"],["#/leaderboard","so.leaderboard"],["#/game","game.title"],["#/notifications","so.notifications"],["#/dashboard","so.dashboard"],["#/account","acc.login"],["#/settings","nav.settings"]].map(([h,k])=>'<a class="card" href="'+h+'">'+esc(t(k))+'</a>').join("")},
async leaderboard(el){const boards=["overall","accuracy","volume","recent","followers","engagement"];let b=sessionStorage.getItem("shp_lb")||"overall";
 el.innerHTML='<h2>'+esc(t("so.leaderboard"))+'</h2><div class="chips" id="lbt"></div><div id="lb">'+loading()+'</div>';
 const go=async()=>{$("#lbt").innerHTML=boards.map(x=>'<button class="'+(x===b?"on":"")+'" data-b="'+x+'">'+x+'</button>').join("");document.querySelectorAll("[data-b]").forEach(x=>x.onclick=()=>{b=x.dataset.b;sessionStorage.setItem("shp_lb",b);go()});
  try{const j=await api("/social/leaderboard?board="+b);const sc=b==="overall";
   const row=(x,mine)=>'<tr'+(mine?' class="me-row"':'')+'><td><b>'+(x.rank?(mine?'#':'')+x.rank:'—')+'</b></td><td>'+(mine?'<b>You</b> · ':'')+'<a href="#/u/'+esc(x.username)+'">'+esc(x.display_name)+'</a>'+(x.account_type==="expert_tipster"?' <span class="tag ver">Expert</span>':'')+(mine&&x.reason?'<div class="muted" style="font-size:12px">'+esc(x.reason)+'</div>':'')+'</td>'+(sc?'<td>'+(x.score??"—")+'</td>':'')+'<td>'+(x.accuracy??"—")+'</td><td>'+(x.settled??"—")+'</td><td>'+esc(x.recent_form||"")+'</td><td>'+(x.followers??"—")+'</td></tr>';
   const me=j.me&&j.me.username?row(j.me,true):j.me?'<tr class="me-row"><td>—</td><td colspan="6"><b>You</b> · '+esc(j.me.reason)+'</td></tr>':'';
   $("#lb").innerHTML=(j.me&&j.me.rank?'<div class="card me-card"><b>Your world rank: #'+j.me.rank+'</b> of '+j.me.out_of+' tipsters</div>':'')+'<p class="muted">'+esc(j.rule)+(j.min_settled?' Minimum '+j.min_settled+' settled picks.':'')+'</p>'+((j.items.length||me)?'<table class="simple"><thead><tr><th>#</th><th></th>'+(sc?'<th>Score</th>':'')+'<th>%</th><th>settled</th><th>form</th><th>'+esc(t("so.followers"))+'</th></tr></thead><tbody>'+me+j.items.map(x=>row(x,false)).join("")+'</tbody></table>':emptyS())}catch(e){errorS($("#lb"),e,go)}};go()},
async account(el){
 if(TOKEN){let me;try{me=await api("/me")}catch(e){TOKEN="";ls.del("shp_session");return SCREENS.account(el)}
  el.innerHTML='<h2>@'+esc(me.username)+'</h2><div class="card">'+(me.email_verified?'<p class="muted">'+esc(me.email)+' ✓</p>':'<p>'+esc(t("acc.verify"))+'</p><div class="row"><input id="vc" class="grow" inputmode="numeric" maxlength="6" placeholder="'+esc(t("acc.code"))+'"><button class="primary" id="vb">'+esc(t("acc.verify"))+'</button><button id="rs">↻</button></div>')+
   '<label>'+esc(t("so.post"))+' name<br><input id="dn" value="'+esc(me.display_name)+'" style="width:100%"></label><label>Bio<br><textarea id="bi" rows="3" style="width:100%" maxlength="500">'+esc(me.bio||"")+'</textarea></label><label class="row"><input type="checkbox" id="pv" '+(me.private_profile?"checked":"")+'> '+esc(t("acc.private"))+'</label>'+
   '<label class="muted">Profile photo<input id="av" type="file" accept="image/jpeg,image/png,image/webp" style="width:100%"></label><p><button class="primary" id="sp">'+esc(t("settings.saved").replace(/./,"S"))+'</button></p><p id="am" class="muted" role="status"></p></div>'+
   (me.account_type==="viewer"?'<div class="card"><button id="ap">'+esc(t("acc.apply_tipster"))+'</button> <span class="muted">'+esc(me.tipster_application||"")+'</span></div>':'<div class="card">'+esc(me.account_type)+'</div>')+
   '<div class="card"><a class="btn" href="#/u/'+esc(me.username)+'">Profile</a> <a class="btn" href="#/dashboard">'+esc(t("so.dashboard"))+'</a> <button id="lo">'+esc(t("settings.logout"))+'</button></div><div class="card"><details><summary>'+esc(t("acc.delete"))+'</summary><p class="muted">Removes your profile, posts and media. Locked prediction records stay (anonymised) so accuracy history cannot be rewritten.</p><input id="dp" type="password" placeholder="'+esc(t("acc.password"))+'" style="width:100%"><p><button id="dl" style="background:#5b1420">'+esc(t("acc.delete"))+'</button></p></details></div>';
  const am=$("#am"),run=async(f,ok)=>{try{await f();am.textContent=ok||"✓"}catch(e){am.textContent=e.message}};
  if($("#vb"))$("#vb").onclick=()=>run(async()=>{await api("/auth/verify-email",{method:"POST",body:JSON.stringify({login:me.username,code:$("#vc").value.trim()})});SCREENS.account(el)});
  if($("#rs"))$("#rs").onclick=()=>run(()=>api("/auth/resend-verification",{method:"POST",body:JSON.stringify({login:me.username})}),"Sent");
  $("#sp").onclick=()=>run(async()=>{const b={display_name:$("#dn").value,bio:$("#bi").value,private_profile:$("#pv").checked};const f=$("#av").files[0];if(f){const mid=await uploadFile(f,"image","avatar",()=>{});b.avatar_media_id=await waitReady(mid)}await api("/me/profile",{method:"POST",body:JSON.stringify(b)})},t("settings.saved"));
  if($("#ap"))$("#ap").onclick=()=>run(async()=>{await api("/me/tipster-application",{method:"POST",body:"{}"});SCREENS.account(el)});
  $("#lo").onclick=async()=>{try{await api("/auth/logout",{method:"POST",body:"{}"})}catch(e){}TOKEN="";ls.del("shp_session");location.hash="#/home"};
  $("#dl").onclick=()=>run(async()=>{if(!confirm(t("acc.delete")+"?"))return;await api("/me/delete",{method:"POST",body:JSON.stringify({password:$("#dp").value})});TOKEN="";ls.del("shp_session");location.hash="#/home"});return}
 let mode=sessionStorage.getItem("shp_acc")||"login";
 const f=(id,l,ty)=>'<label>'+esc(t(l))+'<br><input id="'+id+'" '+(ty?'type="'+ty+'"':'')+' style="width:100%" autocomplete="'+(ty==="password"?(mode==="register"?"new-password":"current-password"):"username")+'"></label>';
 el.innerHTML='<h2>'+esc(t(mode==="register"?"acc.register":mode==="reset"?"acc.reset":"acc.login"))+'</h2><div class="card">'+
  '<label>Country / calling code<select id="login-country" aria-label="Country and calling code"><option value="">Automatic (IP/device)</option></select></label><p class="muted">Used for match times. You can change the time zone separately.</p>'+
  (mode==="login"?f("lg","acc.username")+f("pw","acc.password","password"):mode==="register"?f("un","acc.username")+f("em","acc.email","email")+f("pw","acc.password","password")+'<p class="muted">10+ characters with upper and lower case letters and a digit.</p>':f("lg","acc.email")+'<button id="sc">'+esc(t("acc.code"))+'</button>'+f("cd","acc.code")+f("pw","acc.password","password"))+
  '<p><button class="primary" id="go">'+esc(t(mode==="register"?"acc.register":mode==="reset"?"acc.reset":"acc.login"))+'</button></p><p id="am" class="muted" role="status"></p><p>'+(mode!=="login"?'<a href="#" data-m="login">'+esc(t("acc.login"))+'</a> · ':'')+(mode!=="register"?'<a href="#" data-m="register">'+esc(t("acc.register"))+'</a> · ':'')+(mode!=="reset"?'<a href="#" data-m="reset">'+esc(t("acc.forgot"))+'</a>':'')+'</p></div>';
 const countrySelect=$("#login-country");
 const fillCountries=()=>{if(!countrySelect.isConnected)return;const saved=window.SHTime.country;countrySelect.replaceChildren();const auto=document.createElement('option');auto.value='';auto.textContent='Automatic (IP/device)';countrySelect.append(auto);
 let names;try{names=new Intl.DisplayNames([LANG||'en'],{type:'region'})}catch(e){}
 const entries=Object.entries(window.SHTime.countries).map(([cc,code])=>({cc,code,name:names?names.of(cc):cc})).sort((a,b)=>a.name.localeCompare(b.name));
 for(const entry of entries){const option=document.createElement('option');option.value=entry.cc;option.textContent=entry.name+' ('+entry.code+')';countrySelect.append(option)}countrySelect.value=saved;};
 fillCountries();window.SHTime.ready.then(fillCountries);
 countrySelect.onchange=()=>{window.SHTime.selectCountry(countrySelect.value)};
 document.querySelectorAll("[data-m]").forEach(a=>a.onclick=e=>{e.preventDefault();sessionStorage.setItem("shp_acc",a.dataset.m);SCREENS.account(el)});
 const am=$("#am"),post=(p,b)=>api(p,{method:"POST",body:JSON.stringify(b)});
 if($("#sc"))$("#sc").onclick=async()=>{try{await post("/auth/request-password-reset",{login:$("#lg").value.trim()});am.textContent="If the account exists, a code was emailed."}catch(e){am.textContent=e.message}};
 $("#go").onclick=async()=>{try{
  if(mode==="register"){await post("/auth/register",{username:$("#un").value.trim(),email:$("#em").value.trim(),password:$("#pw").value});const r=await post("/auth/login",{login:$("#un").value.trim(),password:$("#pw").value});TOKEN=r.token;ls.set("shp_session",TOKEN);SCREENS.account(el);return}
  if(mode==="reset"){await post("/auth/reset-password",{login:$("#lg").value.trim(),code:$("#cd").value.trim(),new_password:$("#pw").value});sessionStorage.setItem("shp_acc","login");am.textContent="Password changed. Log in.";setTimeout(()=>SCREENS.account(el),900);return}
  const r=await post("/auth/login",{login:$("#lg").value.trim(),password:$("#pw").value});TOKEN=r.token;ls.set("shp_session",TOKEN);try{PREF=await api("/me/preferences")}catch(e){}location.hash="#/social"}catch(e){am.textContent=e.message}}},
async game(el,id){
 if(id){el.innerHTML=loading();try{const g=await api("/game/"+id);el.innerHTML='<p><a href="#/game">← '+esc(t("game.title"))+'</a></p><div class="card"><span class="tag demo">'+esc(t("game.virtual"))+'</span><h3>'+g.result.innings.map(i=>esc(i.team)+' '+i.runs+'/'+i.wickets+' ('+i.overs+')').join(" · ")+'</h3><p>'+esc(g.result.winner?g.result.winner+" won by "+g.result.margin:"Tie")+' · seed '+g.result.seed+'</p></div>'+fieldHtml()+'<div class="card" id="gl" style="max-height:260px;overflow:auto"></div>';playField(g.events,false)}catch(e){errorS(el,e,()=>SCREENS.game(el,id))}return}
 el.innerHTML='<h2>'+esc(t("game.title"))+'</h2><div class="card"><p class="muted">Our own simulation engine (Laws checked every ball). '+esc(t("game.virtual"))+'.</p><div class="row"><select id="gf"><option>T10</option><option selected>T20</option><option>ODI</option></select><button class="primary" id="gs">'+esc(t("game.simulate"))+'</button></div><p id="gm" class="muted"></p></div><div id="gls">'+loading()+'</div>';
 $("#gs").onclick=async()=>{if(needLogin())return;try{const r=await api("/game/simulate",{method:"POST",body:JSON.stringify({format:$("#gf").value})});location.hash="#/game/"+r.game_id}catch(e){$("#gm").textContent=e.message}};
 try{const j=await api("/game");$("#gls").innerHTML=j.items.map(g=>'<a class="card" href="#/game/'+g.id+'"><span class="tag demo">VIRTUAL</span> '+esc(g.format)+' · '+g.result.innings.map(i=>esc(i.team)+' '+i.runs+'/'+i.wickets).join(" v ")+'</a>').join("")||emptyS()}catch(e){errorS($("#gls"),e,()=>SCREENS.game(el))}}
});
function fieldHtml(){return '<div class="card"><canvas id="fld" width="360" height="360" style="width:100%;max-width:360px;height:auto;display:block;margin:auto" aria-label="2D field animation"></canvas><p class="muted" id="fnote"></p><div class="row"><button id="fpp">⏯</button><input id="fsp" type="range" min="1" max="8" value="3" aria-label="speed"></div></div>'}
function playField(events,recon){const cv=$("#fld");if(!cv)return;const x=cv.getContext("2d"),cs=getComputedStyle(document.documentElement);let i=0,paused=false,tm;
 $("#fnote").textContent=recon?"Reconstruction: outcomes are real recorded deliveries; ball paths are drawn because trajectories were not recorded.":"Simulated geometry from the SH game engine.";
 const log=$("#gl");
 const draw=e=>{x.clearRect(0,0,360,360);x.fillStyle="#1f6b3a";x.beginPath();x.arc(180,180,170,0,7);x.fill();x.strokeStyle="#cfe9d5";x.beginPath();x.arc(180,180,70,0,7);x.stroke();x.fillStyle="#c9b07a";x.fillRect(172,150,16,60);
  if(!e)return;const a=e.animation;x.fillStyle="#fff";x.font="14px sans-serif";x.fillText((e.over_no+"."+e.ball_in_over)+"  "+(e.is_wicket?"W":String(e.runs_bat+e.extras)),10,20);
  if(a.direction_deg!=null){const r=a.distance/85*165,ang=a.direction_deg*Math.PI/180,tx=180+Math.cos(ang)*r,ty=180-Math.sin(ang)*r;x.strokeStyle=e.is_wicket?cs.getPropertyValue("--lose"):a.result>=4?cs.getPropertyValue("--win"):"#fff";x.lineWidth=3;x.setLineDash(a.height==="air"?[6,5]:[]);x.beginPath();x.moveTo(180,190);x.lineTo(tx,ty);x.stroke();x.setLineDash([]);x.fillStyle="#fff";x.beginPath();x.arc(tx,ty,5,0,7);x.fill()}
  if(log)log.insertAdjacentHTML("afterbegin",'<div>'+esc(e.over_no+"."+e.ball_in_over)+' '+esc(e.bowler||"")+' → '+esc(e.batter||"")+': <b>'+(e.is_wicket?"W ("+esc(e.wicket_kind)+")":e.runs_bat+e.extras)+'</b>'+(e.extra_type?' '+esc(e.extra_type):'')+'</div>')};
 const step=()=>{if(paused||i>=events.length)return;draw(events[i++]);tm=setTimeout(step,1200/(+$("#fsp").value))};draw(null);step();$("#fpp").onclick=()=>{paused=!paused;if(!paused)step()}}
async function waitReady(mid){for(let k=0;k<120;k++){const r=await api("/media/uploads/"+mid);if(r.status==="ready")return mid;if(r.status==="failed")throw Error(r.error||"processing failed");await new Promise(z=>setTimeout(z,1000))}throw Error("still processing")}
async function uploadFile(file,kind,purpose,progress){
 const init=await api("/media/uploads",{method:"POST",body:JSON.stringify({kind,purpose,mime:file.type,bytes:file.size,filename:file.name})});
 let url=init.upload_url,off=0,tries=0;const CH=init.chunk_bytes;
 while(off<file.size){const part=file.slice(off,Math.min(file.size,off+CH));
  try{const r=await fetch(url,{method:"PUT",headers:{"Content-Range":"bytes "+off+"-"+(off+part.size-1)+"/"+file.size},body:part});const j=await r.json();
   if(!r.ok){if(r.status===409||r.status===403){const st=await api("/media/uploads/"+init.media_id);off=st.received_bytes;url=st.upload_url||url;if(++tries>5)throw Error(j.error?j.error.message:"upload failed");continue}throw Error(j.error?j.error.message:"upload failed")}
   off=j.received_bytes;tries=0;progress(Math.round(100*off/file.size))}
  catch(e){if(++tries>5)throw e;await new Promise(z=>setTimeout(z,1500*tries));const st=await api("/media/uploads/"+init.media_id);off=st.received_bytes;url=st.upload_url||url}}
 await api("/media/uploads/"+init.media_id+"/complete",{method:"POST",body:"{}"});return init.media_id}
/* live Match Center: Server-Sent Events refresh the Live tab without polling */
let LIVE_ES=null;
function liveSubscribe(mid,onEvent){if(LIVE_ES){LIVE_ES.close();LIVE_ES=null}if(!window.EventSource)return;LIVE_ES=new EventSource("/api/v1/matches/"+mid+"/stream");
 ["ball","probability","status"].forEach(k=>LIVE_ES.addEventListener(k,e=>{try{onEvent(k,JSON.parse(e.data))}catch(x){}}))}
window.addEventListener("hashchange",()=>{if(LIVE_ES&&!/\/live$/.test(location.hash)){LIVE_ES.close();LIVE_ES=null}});

/* 5-minute change window for a just-posted pick (owner rule), then it locks for good */
function changePanel(el,pid,m,cur,postId){const until=Date.now()+5*60*1000;
 const draw=()=>{const left=Math.max(0,Math.round((until-Date.now())/1000));
  el.innerHTML='<div class="card"><h2>✓ '+esc(t("ins.posted"))+'</h2><p>'+esc(t("ins.change_until"))+' <b>'+Math.floor(left/60)+':'+String(left%60).padStart(2,"0")+'</b></p>'+
   (left?'<div class="poll">'+[m.home,m.away].map(x=>'<button data-tm="'+x.id+'" class="'+(x.id===cur?"me":"")+'"><span>'+esc(x.name)+(x.id===cur?" ✓":"")+'</span></button>').join("")+'</div>':'<p class="muted">'+esc(t("ins.locked_now"))+'</p>')+
   '<p id="cmsg" class="muted" role="status"></p><a class="btn primary" href="#/post/'+postId+'">'+esc(t("ins.view"))+' ›</a></div>';
  el.querySelectorAll("[data-tm]").forEach(b=>b.onclick=async()=>{try{const r=await api("/predictions/"+pid+"/change",{method:"POST",body:JSON.stringify({predicted_team_id:+b.dataset.tm})});pid=r.prediction_id;cur=+b.dataset.tm;draw()}catch(e){$("#cmsg").textContent=e.message}})};
 draw();const iv=setInterval(()=>{if(!document.body.contains(el)||location.hash.indexOf("compose")<0){clearInterval(iv);return}if(Date.now()>until+1000){clearInterval(iv)}draw()},1000)}

/* ---------------- SH Tipster desk: the whole series schedule with toss and winner picks (owner's sheet layout) */
SCREENS.tipster=async function(el,cidArg){if(needLogin())return;
 el.innerHTML='<h2>'+esc(t("td.title"))+'</h2><div id="tds" class="chips"></div><div id="tdb">'+loading()+'</div>';
 let ser;try{ser=await api("/me/tipster/series")}catch(e){$("#tdb").innerHTML='<div class="state">'+esc(e.message)+'</div><p><a class="btn primary" href="#/me">'+esc(t("td.apply"))+'</a></p>';return}
 const cid=cidArg||sessionStorage.getItem("shp_tdc")||"";
 $("#tds").innerHTML=ser.items.map(s=>'<a class="btn'+(String(s.id)===String(cid)?" on":"")+'" href="#/tipster/'+s.id+'">'+esc(s.name)+(s.open_matches?' <small>('+s.open_matches+')</small>':'')+'</a>').join("")||'';
 let b;try{b=await api("/me/tipster/board"+(cid?"?competition_id="+cid:""))}catch(e){$("#tdb").innerHTML='<div class="state">'+esc(e.message)+'</div>';return}
 if(!b.series){$("#tdb").innerHTML='<div class="state">'+esc(t("td.no_series"))+'</div>';return}
 sessionStorage.setItem("shp_tdc",b.series.id);if(!cid){const a=$("#tds").querySelector('[href="#/tipster/'+b.series.id+'"]');if(a)a.classList.add("on")}
 const L=await api("/me/tipster/link").catch(()=>null),base=location.origin;
 const tm=(x,id)=>x.id===id;const nm=(m,id)=>id===m.home.id?m.home.name:id===m.away.id?m.away.name:"";
 const res=r=>r==="correct"?'<b style="color:#58c04a">✓</b>':r==="incorrect"?'<b style="color:#ef6a6a">✗</b>':'<span class="muted">'+esc(r)+'</span>';
 const pickRow=(m,kind,can)=>{const p=m.picks[kind];const open=can&&(!p||p.changeable_seconds>0);
  return '<div class="td-pk"><span class="muted">'+esc(t(kind==="toss"?"ins.pt_toss":"ins.pt_winner"))+'</span>'+
   (open?'<span class="td-btns">'+[m.home,m.away].map(x=>'<button data-m="'+m.id+'" data-k="'+kind+'" data-t="'+x.id+'"'+(p?' data-p="'+p.prediction_id+'"':'')+' class="'+(p&&p.team_id===x.id?"on":"")+'">'+esc(x.name)+'</button>').join("")+'</span>'+(p?'<small class="muted" data-cd="'+(Date.now()+p.changeable_seconds*1000)+'"></small>':'')
    :(p?'<b>'+esc(nm(m,p.team_id))+'</b> '+res(p.result)+' <small class="muted">'+esc(p.timing)+'</small>':'<span class="muted">'+esc(t(m.status==="scheduled"?"td.closed":"td.no_pick"))+'</span>'))+'</div>'};
 const rows=b.matches.map((m,i)=>'<div class="mcard"><div class="mh">'+esc(m.match_no?("Match "+m.match_no):("#"+(i+1)))+' · '+esc(new Date(m.start_utc).toLocaleString(undefined,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}))+(m.venue?' · '+esc(m.venue):'')+' · <span class="tag">'+esc(m.status)+'</span></div>'+
  '<a href="#/match/'+m.id+'"><b>'+esc(m.home.name)+'</b> <span class="muted">vs</span> <b>'+esc(m.away.name)+'</b></a>'+
  (m.toss?'<div class="muted">'+esc(t("ins.pt_toss"))+': '+esc(nm(m,m.toss.team_id))+(m.toss.decision?' · '+esc(m.toss.decision):'')+'</div>':'')+
  (m.result?'<div><b style="color:#f6d77a">'+esc(m.result.winner_id?nm(m,m.result.winner_id)+" won"+(m.result.margin?" by "+m.result.margin:""):m.result.type)+'</b></div>':'')+
  pickRow(m,"toss",m.can_pick_toss)+pickRow(m,"winner",m.can_pick_winner)+(m.picks.live_winner?'<div class="td-pk"><span class="muted">'+esc(t("ins.update"))+'</span><b>'+esc(nm(m,m.picks.live_winner.team_id))+'</b></div>':'')+'</div>').join("");
 const S=b.summary;
 $("#tdb").innerHTML='<div class="mcard dl"><span><b>'+esc(b.series.name)+'</b><div class="muted">'+S.picks+' '+esc(t("td.picks"))+' · '+S.correct+'/'+S.settled+' '+esc(t("td.correct"))+'</div></span>'+
  (L?'<a class="btn" href="'+esc(L.xlsx)+'">⬇ Excel</a>':'')+'</div>'+
  (L?'<details class="gx"><summary>'+esc(t("td.google_sheet"))+'</summary><p class="muted">'+esc(t("td.google_help"))+'</p><input readonly style="width:100%" value=\'=IMPORTDATA("'+esc(base+L.csv+"?competition_id="+b.series.id)+'")\' onclick="this.select()"><p><button class="btn" id="tdcp">'+esc(t("td.copy"))+'</button> <button class="btn" id="tdrs">'+esc(t("td.reset"))+'</button></p></details>':'')+
  '<p class="muted">'+esc(b.rule)+'</p>'+(rows||'<div class="state">—</div>');
 const cp=$("#tdcp");if(cp)cp.onclick=()=>{const i=$("#tdb input");i.select();try{navigator.clipboard.writeText(i.value)}catch(e){document.execCommand("copy")}cp.textContent="✓"};
 const rs=$("#tdrs");if(rs)rs.onclick=async()=>{await api("/me/tipster/link",{method:"POST",body:JSON.stringify({reset:true})});route()};
 el.querySelectorAll(".td-btns button").forEach(x=>x.onclick=async()=>{x.disabled=true;
  try{if(x.dataset.p)await api("/predictions/"+x.dataset.p+"/change",{method:"POST",body:JSON.stringify({predicted_team_id:+x.dataset.t})});
   else await api("/social/posts",{method:"POST",body:JSON.stringify({kind:x.dataset.k==="toss"?"toss_prediction":"prediction",prediction_type:x.dataset.k,predicted_team_id:+x.dataset.t,match_id:+x.dataset.m,body:""})});
   route()}catch(e){alert(e.message);x.disabled=false}});
 const tick=()=>{if(!document.body.contains(el))return;let any=false;el.querySelectorAll("[data-cd]").forEach(s=>{const left=Math.max(0,Math.round((+s.dataset.cd-Date.now())/1000));
  if(left>0){any=true;s.textContent=t("td.change_for")+" "+Math.floor(left/60)+":"+String(left%60).padStart(2,"0")}else{s.textContent=t("ins.locked_now")}});if(any)setTimeout(tick,1000);else if(el.querySelector("[data-cd]"))setTimeout(route,800)};tick()};
