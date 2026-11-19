/* SH PREDICTION shell (Blueprint v2.0): global header, news-style Home, Matches with filters, Series pages, Predictions.
   Original SH design; all data from our own API. Missing data says so ("Data not available from the current source"). */
"use strict";
(function(){
const NA=()=>'<div class="state">'+esc(t("data.na"))+'</div>';
const fmtTime=u=>{try{return new Date(u).toLocaleString(undefined,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}catch(e){return u}};
const short=team=>team.short_code||team.name;
function inningsOf(m){const L=m.live_score;if(L&&L.innings&&L.innings.length)return L.innings.map(i=>({team:String(i.inning||"").replace(/ Inning \d+$/,""),r:i.r,w:i.w,o:i.o}));return null}
function rrr(m){const I=inningsOf(m);if(!I||I.length<2||!/^(T20|T10|ODI|The Hundred|List A)$/.test(m.format))return null;
 const per={T10:60,T20:120,"The Hundred":100,ODI:300,"List A":300}[m.format];const tgt=I[0].r+1,b=String(I[1].o).split("."),used=(+b[0]||0)*6+(+b[1]||0),left=per-used,need=tgt-I[1].r;
 return need>0&&left>0?{need,left,rrr:(need*6/left).toFixed(2)}:null}
function liveCard(m){const I=inningsOf(m),R=rrr(m);
 const side=(team)=>{const x=I&&I.filter(i=>i.team===team.name||i.team===team.short_code).slice(-1)[0];return '<div class="lc-team"><b>'+esc(short(team))+'</b><span class="lc-sc">'+(x?x.r+'-'+x.w+' <small>('+esc(String(x.o))+')</small>':'')+'</span></div>'};
 const status=m.result_type?(m.winner_team_id?((m.winner_team_id===m.home.id?m.home.name:m.away.name)+' won'+(m.margin?' by '+m.margin:'')):m.result_type.replace("_"," ")):(m.live_score&&m.live_score.status_text)||(m.status==="scheduled"?fmtTime(m.start_utc):m.status);
 return '<a class="lcard '+(m.status==="live"?"is-live":"")+'" href="#/match/'+m.id+'"><div class="lc-top"><span class="lc-comp">'+esc(m.competition)+'</span>'+(m.status==="live"?'<span class="live-dot">LIVE</span>':'')+'</div>'+
  '<div class="muted lc-meta">'+esc([m.match_no,m.format].filter(Boolean).join(" · "))+'</div>'+side(m.home)+side(m.away)+
  (R?'<div class="lc-rrr">Need '+R.need+' from '+R.left+' balls · RRR '+R.rrr+'</div>':'')+'<div class="lc-status">'+esc(status)+'</div></a>'}
window.liveCard=liveCard;

/* ---------------- header: search, language, notifications, profile, theme, live indicator */
function header(){const H=document.getElementById("hdr");if(!H)return;
 H.innerHTML='<a href="#/live-now" class="hb" id="hlive" title="Live matches" hidden><span class="live-dot">LIVE</span></a>'+
  '<a href="#/search" class="hb" aria-label="Search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4-4"/></svg></a>'+
  '<a href="#/settings" class="hb" aria-label="'+esc(t("label.language"))+'"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></svg></a>'+
  '<a href="#/notifications" class="hb" aria-label="'+esc(t("so.notifications"))+'"><svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20h4"/></svg></a>'+
  '<button class="hb" id="htheme" aria-label="'+esc(t("label.theme"))+'"><svg viewBox="0 0 24 24"><path d="M20 14A8 8 0 1 1 10 4a6 6 0 0 0 10 10z"/></svg></button>'+
  '<a href="#/account" class="hb" aria-label="'+esc(t("acc.login"))+'"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-5 15-5 16 0"/></svg></a>';
 document.getElementById("htheme").onclick=()=>setTheme(document.documentElement.dataset.theme==="dark"?"light":"dark");
 api("/matches?status=live&limit=1").then(j=>{const b=document.getElementById("hlive");if(b)b.hidden=!j.total}).catch(()=>{})}
window.addEventListener("hashchange",header);setTimeout(header,0);

/* ---------------- Home (headline hierarchy) */
const FILTERS=[["all","home.all",""],["live","home.live","status=live"],["upcoming","home.upcoming","status=upcoming"],["results","home.results","status=results"],
 ["intl","home.international","scope=international"],["dom","home.domestic","scope=domestic"],["women","home.women","gender=women"],
 ["T20","T20","format=T20"],["ODI","ODI","format=ODI"],["Test","Test","format=Test"],["T10","T10","format=T10"]];
async function filtered(f,q,limit){const def=FILTERS.find(x=>x[0]===f)||FILTERS[0];let p=def[2];
 if(!/status=/.test(p)){const [l,u,r]=await Promise.all(["live","upcoming","results"].map(s=>api(dq("/matches?status="+s+"&limit="+limit+(p?"&"+p:"")+(q?"&q="+encodeURIComponent(q):"")))));return [...l.items,...u.items,...r.items].slice(0,limit*2)}
 return (await api(dq("/matches?"+p+"&limit="+limit+(q?"&q="+encodeURIComponent(q):"")))).items}
// sports in the owner's approved order; only Cricket has working data and code today
const SPORTS=[["cricket","Cricket","🏏",true],["tennis","Tennis","🎾",false],["football","Football","⚽",false],["badminton","Badminton","🏸",false],["kabaddi","Kabaddi","🤼",false]];
SCREENS.home=async function(el){
 el.innerHTML='<div class="sports" role="tablist" aria-label="'+esc(t("home.sports"))+'">'+SPORTS.map(([k,l,i,on])=>'<button role="tab" class="sp'+(k==="cricket"?" on":"")+'"'+(on?'':' aria-disabled="true" title="'+esc(t("home.coming_soon"))+'"')+'><span>'+i+'</span>'+esc(l)+(on?'':'<small>'+esc(t("home.coming_soon"))+'</small>')+'</button>').join("")+'</div>'+
  '<div class="qlinks">'+[["#/live-now","home.live","⏱"],["#/matches","home.upcoming","📅"],["#/series","nav.series","🏆"],["#/predictions","nav.predictions","🎯"],["#news","home.news","📰"]].map(([h,k,i])=>'<a href="'+h+'"'+(h==="#news"?' onclick="event.preventDefault();document.getElementById(\'news\').scrollIntoView({behavior:\'smooth\'})"':'')+'><span>'+i+'</span>'+esc(t(k))+'</a>').join("")+'</div>'+
  '<div class="sec"><div class="sec-h"><h2>'+esc(t("home.featured"))+'</h2><a href="#/matches">'+esc(t("nav.matches"))+' →</a></div><div class="hscroll" id="feat">'+loading()+'</div></div>'+
  '<div class="chips fbar" id="fb" role="tablist"></div><div id="fl"></div>'+
  '<div class="sec"><div class="sec-h"><h2>'+esc(t("home.featured_predictions"))+'</h2><a href="#/predictions">'+esc(t("nav.predictions"))+' →</a></div><div id="fp">'+loading()+'</div></div>'+
  '<div class="sec"><h2>'+esc(t("home.sh_features"))+'</h2><div class="shf">'+[["#/predictions","SH AI Prediction","🎯"],["#/predictions","Toss Intelligence","🪙"],["#/matches","Pitch Analyzer","🟫"],["#/series","Venue Records","🏟️"],
   ["#/matches","Fantasy XI","⭐"],["#/game","Virtual Live","🎮"],["#/social","SH Social","💬"],["#/leaderboard","Tipster Rankings","🏆"]].map(([h,l,i])=>'<a class="shf-i" href="'+h+'"><span>'+i+'</span>'+esc(l)+'</a>').join("")+'</div></div>'+
  '<div class="sec"><h2>'+esc(t("home.dashboard"))+'</h2><div id="dash">'+loading()+'</div></div>'+
  '<div class="sec"><h2>'+esc(t("home.news"))+'</h2><div id="news">'+loading()+'</div></div>';
 // A: featured live / next matches
 try{const [l,u,r]=await Promise.all(["live","upcoming","results"].map(s=>api(dq("/matches?status="+s+"&limit=8"))));const list=[...l.items,...u.items.slice(0,4),...r.items.slice(0,4)];
  $("#feat").innerHTML=list.length?list.map(liveCard).join(""):NA()}catch(e){errorS($("#feat"),e,()=>SCREENS.home(el))}
 // B: filters
 let cur=sessionStorage.getItem("shp_hf")||"all";
 const drawF=async()=>{$("#fb").innerHTML=FILTERS.map(([k,l])=>'<button role="tab" class="'+(k===cur?"on":"")+'" data-f="'+k+'">'+esc(l.indexOf(".")>0?t(l):l)+'</button>').join("");
  document.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{cur=b.dataset.f;sessionStorage.setItem("shp_hf",cur);drawF()});
  const L=$("#fl");L.innerHTML=loading();try{const items=await filtered(cur,"",10);L.innerHTML=items.length?items.map(matchCard).join(""):NA()}catch(e){errorS(L,e,drawF)}};drawF();
 // C: featured predictions
 try{const u=await api(dq("/matches?status=upcoming&limit=3"));if(!u.items.length){$("#fp").innerHTML=NA()}else{
  const sig=await Promise.all(u.items.map(m=>api("/matches/"+m.id+"/signals").catch(()=>null)));
  $("#fp").innerHTML=u.items.map((m,i)=>{const s=sig[i]&&sig[i].pre_match;return '<a class="card" href="#/match/'+m.id+'/prediction"><div class="row"><b class="grow">'+esc(short(m.home))+' vs '+esc(short(m.away))+'</b><span class="tag">'+esc(t("home.estimate"))+'</span></div><div class="muted">'+esc(m.competition)+' · '+fmtTime(m.start_utc)+'</div>'+
   (s&&s.home_win_probability!=null?probBar(s.home_win_probability,m)+'<div class="muted" style="font-size:12px">Toss call is an estimate · confidence '+esc(String(s.confidence_level||s.confidence||"—"))+'</div>':'<p class="muted">'+esc(t("data.na"))+'</p>')+'</a>'}).join("")}}catch(e){$("#fp").innerHTML=NA()}
 // E: dashboard
 try{const d=await api("/home/dashboard");const lst=(a,f)=>a&&a.length?a.map(f).join(""):'<p class="muted">'+esc(t("data.na"))+'</p>';
  $("#dash").innerHTML='<div class="dgrid"><div class="card"><h3>'+esc(t("home.upcoming_tournaments"))+'</h3>'+lst(d.upcoming_tournaments,x=>'<a class="dl" href="#/series/'+x.id+'"><b>'+esc(x.name)+'</b><span class="muted">'+fmtTime(x.starts)+' · '+x.matches+'</span></a>')+'</div>'+
   '<div class="card"><h3>'+esc(t("home.recent_series"))+'</h3>'+lst(d.recently_completed,x=>'<a class="dl" href="#/series/'+x.id+'"><b>'+esc(x.name)+'</b><span class="muted">'+x.matches+' matches</span></a>')+'</div>'+
   '<div class="card"><h3>'+esc(t("home.top_performers"))+'</h3>'+lst(d.top_batters_30d,x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.runs+' runs · '+x.matches+' m</span></div>')+lst(d.top_bowlers_30d,x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.wickets+' wkts · '+x.matches+' m</span></div>')+'</div>'+
   '<div class="card"><h3>'+esc(t("home.rankings"))+'</h3><p class="muted">'+esc(d.rankings_note)+'</p></div></div>';
  $("#news").innerHTML='<div class="card"><p class="muted">'+esc(d.news_note)+'</p><p class="muted">Match previews and reports written by SH from our own data are planned; third-party articles need a licence.</p></div>'}catch(e){$("#dash").innerHTML=NA();$("#news").innerHTML=NA()}
};

/* ---------------- Matches with the same filters */
SCREENS.matches=async function(el){
 el.innerHTML='<h2>'+esc(t("nav.matches"))+'</h2><input id="q" type="search" style="width:100%" placeholder="'+esc(t("home.search"))+'"><div class="chips fbar" id="fb"></div><div id="list">'+loading()+'</div>';
 let cur=sessionStorage.getItem("shp_mf")||"live";
 const go=async()=>{$("#fb").innerHTML=FILTERS.map(([k,l])=>'<button class="'+(k===cur?"on":"")+'" data-f="'+k+'">'+esc(l.indexOf(".")>0?t(l):l)+'</button>').join("");
  document.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{cur=b.dataset.f;sessionStorage.setItem("shp_mf",cur);go()});
  const L=$("#list");L.innerHTML=loading();try{const items=await filtered(cur,$("#q").value.trim(),30);L.innerHTML=items.length?'<div class="mgrid">'+items.map(liveCard).join("")+'</div>':NA()}catch(e){errorS(L,e,go)}};
 go();let tm;$("#q").oninput=()=>{clearTimeout(tm);tm=setTimeout(go,300)}};
SCREENS["live-now"]=async el=>{sessionStorage.setItem("shp_mf","live");location.hash="#/matches"};
document.addEventListener("click",e=>{const b=e.target.closest(".sp[aria-disabled=true]");if(b){e.preventDefault();b.classList.add("shake");setTimeout(()=>b.classList.remove("shake"),500)}});

/* ---------------- Series list and series page */
SCREENS.series=async function(el,id){
 if(id){el.innerHTML=loading();try{const d=await api("/series/"+id);const S=d.series;let tab=sessionStorage.getItem("shp_st")||"fixtures";
  el.innerHTML='<p><a href="#/series">← '+esc(t("nav.series"))+'</a></p><div class="card"><h2 style="margin:0">'+esc(S.name)+'</h2><div class="muted">'+esc([S.category,S.division,S.format].filter(Boolean).join(" · "))+'</div></div><div class="sub" id="stabs"></div><div id="sb"></div>';
  const tabs=[["fixtures","series.fixtures"],["results","series.results"],["points","series.points"],["teams","series.teams"],["stats","series.stats"]];
  const draw=()=>{$("#stabs").innerHTML=tabs.map(([k,l])=>'<a class="btn '+(k===tab?"on":"")+'" href="#" data-s="'+k+'">'+esc(t(l))+'</a>').join("");
   document.querySelectorAll("[data-s]").forEach(a=>a.onclick=e=>{e.preventDefault();tab=a.dataset.s;sessionStorage.setItem("shp_st",tab);draw()});
   const B=$("#sb");
   if(tab==="fixtures")B.innerHTML=d.fixtures.length?'<div class="mgrid">'+d.fixtures.map(liveCard).join("")+'</div>':NA();
   else if(tab==="results")B.innerHTML=d.results.length?'<div class="mgrid">'+d.results.map(liveCard).join("")+'</div>':NA();
   else if(tab==="points")B.innerHTML=d.points_table.length?'<div class="card"><table class="simple pt"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>L</th><th>T</th><th>NR</th><th>Pts</th><th>NRR</th></tr></thead><tbody>'+
     d.points_table.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.short_code||x.team)+'</b></td><td>'+x.played+'</td><td>'+x.won+'</td><td>'+x.lost+'</td><td>'+x.tied+'</td><td>'+x.no_result+'</td><td><b>'+x.points+'</b></td><td>'+(x.nrr==null?"—":(x.nrr>0?"+":"")+x.nrr.toFixed(3))+'</td></tr>').join("")+'</tbody></table><p class="muted">'+esc(d.points_rule)+'</p></div>':NA();
   else if(tab==="teams")B.innerHTML=d.teams.length?'<div class="card">'+d.teams.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b></div>').join("")+'</div>':NA();
   else B.innerHTML='<div class="dgrid"><div class="card"><h3>Most runs</h3>'+(d.top_batters.length?d.top_batters.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.runs+' ('+x.balls+' b)</span></div>').join(""):'<p class="muted">'+esc(t("data.na"))+'</p>')+'</div>'+
    '<div class="card"><h3>Most wickets</h3>'+(d.top_bowlers.length?d.top_bowlers.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.wickets+' / '+x.runs_conceded+'</span></div>').join(""):'<p class="muted">'+esc(t("data.na"))+'</p>')+'</div></div>'};draw()}
  catch(e){errorS(el,e,()=>SCREENS.series(el,id))}return}
 el.innerHTML='<h2>'+esc(t("nav.series"))+'</h2><input id="sq" type="search" style="width:100%" placeholder="'+esc(t("home.search"))+'"><div id="sl">'+loading()+'</div>';
 const go=async()=>{try{const j=await api("/series"+($("#sq").value.trim()?"?q="+encodeURIComponent($("#sq").value.trim()):""));
  $("#sl").innerHTML=j.items.length?j.items.map(x=>'<a class="card" href="#/series/'+x.id+'"><div class="row"><b class="grow">'+esc(x.name)+'</b>'+(x.live?'<span class="live-dot">LIVE</span>':'')+'</div><div class="muted">'+
   [x.live?x.live+" live":"",x.upcoming?x.upcoming+" upcoming":"",x.completed?x.completed+" completed":""].filter(Boolean).join(" · ")+(x.next_start?' · next '+fmtTime(x.next_start):'')+'</div></a>').join(""):NA()}catch(e){errorS($("#sl"),e,go)}};
 go();let tm;$("#sq").oninput=()=>{clearTimeout(tm);tm=setTimeout(go,300)}};

/* ---------------- Predictions hub */
SCREENS.predictions=async function(el){
 el.innerHTML='<h2>'+esc(t("nav.predictions"))+'</h2><div class="sub"><a class="btn on" href="#/predictions">SH AI</a><a class="btn" href="#/experts">'+esc(t("nav.experts"))+'</a><a class="btn" href="#/leaderboard">'+esc(t("so.leaderboard"))+'</a><a class="btn" href="#/accuracy">'+esc(t("nav.accuracy"))+'</a></div><div id="pp"></div>';
 await SCREENS.ai($("#pp"))};

/* More menu: everything that left the bottom bar stays one tap away */
const oldMore=SCREENS.more;
SCREENS.more=async function(el){await oldMore(el);el.insertAdjacentHTML("afterbegin",'<div class="shf" style="margin-bottom:12px">'+[["#/social","nav.social","💬"],["#/reels","nav.reels","🎬"],["#/experts","nav.experts","🧠"],["#/series","nav.series","🏆"]].map(([h,k,i])=>'<a class="shf-i" href="'+h+'"><span>'+i+'</span>'+esc(t(k))+'</a>').join("")+'</div>')};
SCREENS.search=async function(el){el.innerHTML='<h2>Search</h2><input id="gq" type="search" autofocus style="width:100%" placeholder="Team, player, series or user"><div id="gr"></div>';
 let tm;$("#gq").oninput=()=>{clearTimeout(tm);tm=setTimeout(async()=>{const q=$("#gq").value.trim();if(q.length<2){$("#gr").innerHTML="";return}
  const [m,s,u]=await Promise.all([api("/matches?q="+encodeURIComponent(q)+"&limit=10").catch(()=>({items:[]})),api("/series?q="+encodeURIComponent(q)).catch(()=>({items:[]})),api("/social/search/users?q="+encodeURIComponent(q)).catch(()=>({items:[]}))]);
  $("#gr").innerHTML='<h3>'+esc(t("nav.series"))+'</h3>'+(s.items.slice(0,5).map(x=>'<a class="card" href="#/series/'+x.id+'">'+esc(x.name)+'</a>').join("")||'<p class="muted">—</p>')+
   '<h3>'+esc(t("nav.matches"))+'</h3>'+(m.items.map(matchCard).join("")||'<p class="muted">—</p>')+'<h3>Users</h3>'+((u.items||[]).map(x=>'<a class="card" href="#/u/'+esc(x.username)+'">'+esc(x.display_name)+' @'+esc(x.username)+'</a>').join("")||'<p class="muted">—</p>')},300)}};
})();
