/* SH Match Center insights: Info, Fantasy points, Discussions, Live extras, Scorecard switcher, Points Table, Graphs.
   Data from /matches/{id}/insights and /matches/{id}/discussions; every block hides or says "not available" when its data is missing.
   Our own layout, names and colours. */
"use strict";
(function(){
const later=window.mcLater||(window.mcLater=fn=>(window._mcq=window._mcq||[]).push(fn));
const I=(m,part)=>api("/matches/"+m.id+"/insights?part="+part);
const lab=(m,s)=>s==="home"?(m.home.short_code||m.home.name):(m.away.short_code||m.away.name);
const NA=()=>'<p class="muted">'+esc(t("data.na"))+'</p>';
const sec=(title,body,right)=>'<section class="ins-sec"><h3><span>'+title+'</span>'+(right||"")+'</h3>'+body+'</section>';
const chip=b=>{const v=b.w?"W":(b.x==="wd"||b.x==="wide"?"wd":b.x==="nb"||b.x==="no_ball"?"nb":String(b.r));const cls=b.w?"bw":b.r>=6?"b6":b.r===4?"b4":b.r>0?"b1":"b0";return '<span class="bl '+cls+'">'+esc(v)+'</span>'};
function card(x){return '<div class="mcard"><div class="mh">'+esc([x.match_no?("Match "+x.match_no):"",x.competition].filter(Boolean).join(", "))+' · '+esc(x.day)+'</div><div class="mb"><div class="mi">'+
 (x.innings.length?x.innings.map(i=>'<div><b>'+esc(i.team)+'</b><span>'+i.runs+'-'+i.wickets+'</span> <small class="muted">'+esc(i.overs)+'</small></div>').join(""):'<div class="muted">'+esc(t("ins.scores_na"))+'</div>')+
 '</div><div class="mr"><b>'+esc(x.result||"—")+'</b>'+(x.id?'<a href="#/match/'+x.id+'/scorecard"><span>'+esc(t("ins.view"))+' ›</span></a>':'')+'</div></div></div>'}
const donut=(a,b)=>{const p=a+b?a/(a+b):0,R=42,C=2*Math.PI*R;return '<svg width="110" height="110" viewBox="0 0 110 110" role="img" aria-label="'+a+' / '+b+'"><circle cx="55" cy="55" r="'+R+'" fill="none" stroke="#e0626a" stroke-width="12"/>'+
 '<circle cx="55" cy="55" r="'+R+'" fill="none" stroke="#58c04a" stroke-width="12" stroke-dasharray="'+(C*(1-p))+' '+C+'" transform="rotate(-90 55 55)"/><text x="55" y="58" text-anchor="middle" fill="currentColor" font-size="20" font-weight="700">'+(a+b)+'</text><text x="55" y="74" text-anchor="middle" fill="currentColor" font-size="9" opacity=".7">'+esc(t("ins.matches"))+'</text></svg>'};

/* ---------------- Info */
window.mcTab.info=async m=>{let d;try{d=await I(m,"info")}catch(e){d=null}
 const toss=m.toss_winner_id?'<div class="toss-l">'+esc((m.toss_winner_id===m.home.id?lab(m,"home"):lab(m,"away"))+" "+t("ins.won_toss")+" "+(m.toss_decision==="bat"?t("ins.bat"):t("ins.bowl")))+'</div>':"";
 const pdi=(m.provider_detail&&m.provider_detail.info)||{};
 let out=toss+'<div class="mcard"><div class="mh">'+esc(m.match_no?("Match "+m.match_no):m.format)+'</div><a href="#/series/'+m.competition_id+'"><b>'+esc(m.competition)+' ›</b></a>'+
  '<dl class="kv" style="margin-top:8px"><dt>📅</dt><dd>'+esc(new Date(m.start_utc).toLocaleString(undefined,{weekday:"long",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}))+'</dd><dt>📍</dt><dd>'+esc(m.venue||pdi.venue||"—")+'</dd>'+
  (m.result_type?'<dt>🏁</dt><dd><b>'+esc(m.winner_team_id?((m.winner_team_id===m.home.id?m.home.name:m.away.name)+" won"+(m.margin?" by "+m.margin:"")):m.result_type)+'</b></dd>':'')+'</dl></div>';
 const sq=m.provider_detail&&m.provider_detail.squads;
 out+=sec(esc(t("mc.xi")),'<div class="mcard">'+[m.home,m.away].map(x=>'<a class="dl" href="#/match/'+m.id+'/xi"><b>'+esc(x.name)+'</b><span>'+(sq&&sq.length?"›":esc(t("ins.not_announced")))+'</span></a>').join("")+'</div>');
 if(!d)return out+NA();
 const formRow=(s,arr)=>'<div class="frow"><b>'+esc(lab(m,s))+'</b>'+(m.status==="scheduled"?'<span class="fchip" title="'+esc(t("ins.upcoming"))+'">*</span>':'')+
  (arr.length?arr.slice().map(x=>'<span class="fchip '+x.outcome+'">'+esc(x.outcome)+'</span>').join(""):'<span class="muted">'+esc(t("ins.no_matches"))+'</span>')+'</div>';
 out+=sec(esc(t("ins.team_form")),formRow("home",d.form.home)+formRow("away",d.form.away)+
  '<details class="gx"><summary>'+esc(t("ins.form_matches"))+'</summary>'+d.form.home.concat(d.form.away).sort((a,b)=>a.day<b.day?1:-1).filter((x,i,a)=>a.findIndex(y=>y.id===x.id)===i).map(card).join("")+'</details>','<small>'+esc(t("ins.last5"))+'</small>');
 const h=d.h2h;
 out+=sec(esc(t("mc.h2h")),'<div class="h2hbig"><div><strong class="c-home">'+h.home_won+'</strong><div class="hn">'+esc(lab(m,"home"))+'</div></div><div class="muted">'+h.matches+' '+esc(t("ins.matches"))+'</div><div><strong class="c-away">'+h.away_won+'</strong><div class="hn">'+esc(lab(m,"away"))+'</div></div></div>'+
  (h.items.length?h.items.map(card).join(""):NA()),'<small>'+esc(t("ins.last10"))+'</small>');
 try{const p=await I(m,"points");const rows=p.table.map((x,i)=>Object.assign({rank:i+1},x)).filter(x=>p.teams.includes(x.team_id));
  if(rows.length&&p.table.length>2)out+=sec(esc(t("ins.in_points")),'<table class="simple"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>L</th><th>NRR</th><th>Pts</th></tr></thead><tbody>'+
   rows.map(x=>'<tr><td>'+x.rank+'</td><td><b>'+esc(x.short_code||x.team)+'</b></td><td>'+x.played+'</td><td>'+x.won+'</td><td>'+x.lost+'</td><td>'+(x.nrr==null?"—":(x.nrr>0?"+":"")+x.nrr.toFixed(3))+'</td><td><b>'+x.points+'</b></td></tr>').join("")+'</tbody></table>',
   '<a href="#/match/'+m.id+'/seriesstats">'+esc(t("ins.points_table"))+' ›</a>')}catch(e){}
 const cmpId="cmp"+m.id;later(()=>{const box=document.getElementById(cmpId);if(!box)return;const draw=k=>{const C=d.comparison[k];box.querySelectorAll("[data-k]").forEach(b=>b.classList.toggle("on",b.dataset.k===k));
   const H=C&&C.home,A=C&&C.away,tb=box.querySelector(".cmpb");if(!H||!A||(!H.matches&&!A.matches)){tb.innerHTML=NA();return}
   const row=(l,a,b,hi)=>{const better=a==null||b==null||a===b?0:(hi?(a>b?1:-1):(a<b?1:-1));return '<tr><td class="'+(better>0?"gd":"")+'">'+(a==null?"—":a+(l==="ins.win"?"%":""))+'</td><td>'+esc(t(l))+'</td><td class="'+(better<0?"gd":"")+'">'+(b==null?"—":b+(l==="ins.win"?"%":""))+'</td></tr>'};
   tb.innerHTML='<table class="cmp"><tbody><tr><td><b class="c-home">'+esc(lab(m,"home"))+'</b></td><td></td><td><b class="c-away">'+esc(lab(m,"away"))+'</b></td></tr>'+row("ins.played",H.matches,A.matches,true)+row("ins.win",H.win_pct,A.win_pct,true)+row("ins.avg_score",H.avg_score,A.avg_score,true)+
    row("ins.highest",H.highest,A.highest,true)+row("ins.lowest",H.lowest,A.lowest,true)+'</tbody></table>'};
  box.querySelectorAll("[data-k]").forEach(b=>b.onclick=()=>draw(b.dataset.k));draw("overall")});
 out+=sec(esc(t("ins.team_comparison")),'<div id="'+cmpId+'"><div class="seg"><button data-k="overall">'+esc(t("ins.overall"))+'</button><button data-k="venue">'+esc(t("ins.on_venue"))+'</button></div><div class="cmpb"></div></div>','<small>'+esc(t("ins.last10"))+'</small>');
 const v=d.venue;
 if(v){let vb="";const w=v.weather;
  vb+='<div class="mcard">'+(w?'<div class="wx"><div style="font-size:40px">'+({Clear:"☀️","Mainly clear":"🌤","Partly cloudy":"⛅",Cloudy:"☁️",Fog:"🌫"}[w.condition]||(/rain|shower|drizzle/i.test(w.condition)?"🌧":/thunder/i.test(w.condition)?"⛈":"🌥"))+'</div><div style="flex:1"><div class="muted">'+esc(w.place)+'</div><div class="t">'+esc(String(w.temperature_c))+'°C</div><div>'+esc(w.condition)+'</div></div>'+
   '<div class="muted">💧 '+esc(String(w.humidity_pct??"—"))+'% '+esc(t("ins.humidity"))+'<br>🌧 '+esc(String(w.rain_chance_pct??"—"))+'% '+esc(t("ins.rain_chance"))+'</div></div><p class="muted">'+esc(t("ins.updated"))+' '+esc((w.updated||"").replace("T"," "))+' · '+esc(w.source)+'</p>':'<p class="muted">'+esc(t("mc.weather"))+': '+esc(t("data.na"))+'</p>')+'</div>';
  if(v.matches){vb+='<div class="mcard donut">'+donut(v.bat_first_win_pct*v.matches/100|0,v.matches-(v.bat_first_win_pct*v.matches/100|0))+'<div class="lg"><div><span>'+esc(t("ins.win_bat_first"))+'</span><b style="color:#e0626a">'+v.bat_first_win_pct+'%</b></div><div><span>'+esc(t("ins.win_bowl_first"))+'</span><b style="color:#58c04a">'+v.bowl_first_win_pct+'%</b></div></div></div>'+
   '<div class="mcard"><div class="dl"><span>'+esc(t("ins.avg_1st"))+'<br><b>'+v.avg_first_innings+'</b></span><span style="text-align:right">'+esc(t("ins.avg_2nd"))+'<br><b>'+v.avg_second_innings+'</b></span></div>'+
   (v.highest?'<div class="dl"><span>'+esc(t("ins.highest_total"))+'<br><b>'+v.highest.runs+'-'+v.highest.wickets+'</b> <small class="muted">('+v.highest.overs+' ov) '+esc(v.highest.team)+'</small></span><a href="#/match/'+v.highest.match_id+'/scorecard">'+esc(t("ins.view"))+' ›</a></div>':'')+
   (v.lowest?'<div class="dl"><span>'+esc(t("ins.lowest_total"))+'<br><b>'+v.lowest.runs+'-'+v.lowest.wickets+'</b> <small class="muted">('+v.lowest.overs+' ov) '+esc(v.lowest.team)+'</small></span><a href="#/match/'+v.lowest.match_id+'/scorecard">'+esc(t("ins.view"))+' ›</a></div>':'')+'</div>'}
  else vb+='<p class="muted">'+esc(t("ins.no_venue_matches"))+'</p>';
  const ps=v.pace_spin;
  vb+=sec(esc(t("ins.pace_spin")),ps?'<div class="mcard"><div class="dl"><b style="color:#58c04a">'+esc(t("ins.pace"))+' '+ps.pace+' '+esc(t("ins.wkts"))+'</b><b style="color:#e0626a">'+esc(t("ins.spin"))+' '+ps.spin+' '+esc(t("ins.wkts"))+'</b></div><div class="psbar"><i style="width:'+ps.pace_pct+'%;background:#3e8e2e"></i><i style="width:'+ps.spin_pct+'%;background:#b52a2a"></i></div><div class="dl"><span>'+ps.pace_pct+'%</span><span>'+ps.spin_pct+'%</span></div></div>':'<p class="muted">'+esc(t("data.na"))+' '+esc(v.pace_spin_note||"")+'</p>');
  const so=v.scores_at_overs;
  vb+=sec(esc(t("ins.avg_at_overs")),so?'<table class="simple"><thead><tr><th>'+esc(t("ins.over"))+'</th><th>'+esc(t("ins.inn1"))+'</th><th>'+esc(t("ins.inn2"))+'</th></tr></thead><tbody>'+so.rows.map(x=>'<tr><td>'+x.over+' '+esc(t("ins.over"))+'</td><td>'+(x.first??"—")+'</td><td>'+(x.second??"—")+'</td></tr>').join("")+'</tbody></table><p class="muted">'+so.matches+' '+esc(t("ins.matches_bbb"))+'</p>':'<p class="muted">'+esc(t("data.na"))+'</p>','<small>'+esc(t("ins.last10"))+'</small>');
  vb+=sec(esc(t("ins.recent_venue")),v.recent.length?v.recent.map(card).join(""):NA());
  out+=sec(esc(t("ins.venue_stats"))+' <small>'+esc(v.name)+'</small>',vb)}
 return out+'<p class="muted">'+esc(d.note)+'</p>'};
window.mcTabAfter=window.mcTabAfter||{};delete window.mcTabAfter.info;

/* ---------------- Player stats in series (Fantasy tab) + full-screen Analysis with independent filters */
const CAT_KEYS=["fantasy","runs","wickets","sixes","highest","figures","sr","econ"];
const catLabel=k=>t("an.cat_"+k);
async function seriesStatsBlock(m){if(!m.competition_id)return "";const cur=sessionStorage.getItem("shp_ssc")||"fantasy";let d;
 try{d=await api("/matches/"+m.id+"/insights?part=series_stats&cat="+cur)}catch(e){return ""}
 const id="ss"+m.id;
 later(()=>{const b=document.getElementById(id);if(!b)return;const on=b.querySelector(".an-cats .on");if(on)on.parentNode.scrollLeft=on.offsetLeft-on.parentNode.offsetLeft-12;b.querySelectorAll("[data-c]").forEach(x=>x.onclick=async()=>{sessionStorage.setItem("shp_ssc",x.dataset.c);
  b.outerHTML=await seriesStatsBlock(m);(window._mcq||[]).splice(0).forEach(f=>f())})});
 const list=d.items.slice(0,5).map(x=>'<div class="dl"><span><b>'+x.rank+'. '+esc(x.name)+'</b> <small class="muted">'+esc(x.team||"")+'</small></span><span><b>'+esc(x.display)+'</b> <small class="muted">'+x.inns+' '+esc(t("an.inns"))+'</small></span></div>').join("");
 return '<section class="ins-sec" id="'+id+'"><h3><span>'+esc(t("an.player_stats"))+'</span><a href="#/analysis/'+m.id+'/cat='+cur+'">'+esc(t("an.analysis"))+' ›</a></h3>'+
  '<div class="chips an-cats">'+CAT_KEYS.map(k=>'<button class="btn'+(k===cur?" on":"")+'" data-c="'+k+'">'+esc(catLabel(k))+'</button>').join("")+'</div>'+
  '<div class="mcard">'+(list||'<p class="muted">'+esc(d.empty||t("an.no_stats"))+'</p>')+'</div><p class="muted">'+esc(d.note)+'</p></section>'}
SCREENS.analysis=async function(el,mid,qs){const Q=new URLSearchParams(qs||"");const st={cat:Q.get("cat")||"fantasy",last:Q.get("last")||"",venue:Q.get("venue")==="1",vs:Q.get("vs")||"",view:Q.get("view")||"table"};
 let m;try{m=await api("/matches/"+mid)}catch(e){errorS(el,e);return}
 const H=m.home.short_code||m.home.name,A=m.away.short_code||m.away.name;
 const qstr=s=>["cat="+s.cat,s.last?"last="+s.last:"",s.venue?"venue=1":"",s.vs?"vs="+s.vs:"",s.view!=="table"?"view="+s.view:""].filter(Boolean).join("&");
 const go=s=>{location.replace("#/analysis/"+mid+"/"+qstr(s))};   // filter changes replace the entry, so Back returns to Fantasy
 el.innerHTML='<div class="an-top"><button class="btn" id="anb">‹</button><h2>'+esc(H)+' vs '+esc(A)+' '+esc(t("an.in_series"))+'</h2></div>'+
  '<div class="chips an-cats">'+CAT_KEYS.map(k=>'<button class="btn'+(k===st.cat?" on":"")+'" data-c="'+k+'">'+esc(catLabel(k))+'</button>').join("")+'</div>'+
  '<div class="chips an-f"><button class="btn'+(!st.last&&!st.venue&&!st.vs?" on":"")+'" data-f="all">'+esc(t("an.all"))+'</button><button class="btn'+(st.last?" on":"")+'" data-f="last">'+esc(t("an.last5"))+'</button>'+
  '<button class="btn'+(st.venue?" on":"")+'" data-f="venue">'+esc(t("an.at_venue"))+'</button><button class="btn'+(st.vs==="home"?" on":"")+'" data-f="vs:home">vs '+esc(H)+'</button><button class="btn'+(st.vs==="away"?" on":"")+'" data-f="vs:away">vs '+esc(A)+'</button></div><div id="anr">'+loading()+'</div>';
 el.querySelectorAll(".an-cats .on").forEach(x=>{const r=x.parentNode;r.scrollLeft=x.offsetLeft-r.offsetLeft-12});
 $("#anb").onclick=()=>{sessionStorage.setItem("shp_ssc",st.cat);if(history.length>1)history.back();else location.hash="#/match/"+mid+"/fantasy"};
 el.querySelectorAll("[data-c]").forEach(x=>x.onclick=()=>go(Object.assign({},st,{cat:x.dataset.c})));
 el.querySelectorAll("[data-f]").forEach(x=>x.onclick=()=>{const f=x.dataset.f,s=Object.assign({},st);
  if(f==="all"){s.last="";s.venue=false;s.vs=""}else if(f==="last")s.last=s.last?"":"5";else if(f==="venue")s.venue=!s.venue;else{const v=f.split(":")[1];s.vs=s.vs===v?"":v}go(s)});
 let d;try{d=await api("/matches/"+mid+"/insights?part=series_stats&"+qstr(st))}catch(e){errorS($("#anr"),e);return}
 const cols={fantasy:[["display","an.points"]],runs:[["display","an.runs"],["balls","B"],["sr","SR"],["avg","Avg"]],wickets:[["display","an.wkts"],["overs","Ov"],["econ","Econ"]],
  sixes:[["display","6s"],["fours","4s"],["runs","an.runs"]],highest:[["display","HS"],["balls","B"]],figures:[["display","an.figures"],["overs","Ov"]],sr:[["display","SR"],["runs","an.runs"],["balls","B"]],econ:[["display","Econ"],["overs","Ov"]]}[st.cat];
 const lab=k=>k.indexOf("an.")===0?t(k):k;
 const top=d.items.slice(0,3).map(x=>'<div class="an-tc"><div class="an-rk">#'+x.rank+'</div><b>'+esc(x.name.split(" ").slice(-1)[0])+'</b><small class="muted">'+esc(x.team||"")+'</small><strong>'+esc(x.display)+'</strong><small class="muted">'+x.inns+' '+esc(t("an.inns"))+'</small></div>').join("");
 const table='<table class="simple"><thead><tr><th>#</th><th>'+esc(t("an.player"))+'</th><th>'+esc(t("an.inns"))+'</th>'+cols.map(c=>'<th>'+esc(lab(c[1]))+'</th>').join("")+'</tr></thead><tbody>'+
  d.items.map(x=>'<tr><td>'+x.rank+'</td><td><b>'+esc(x.name)+'</b><div class="muted">'+esc(x.team||"")+'</div></td><td>'+x.inns+'</td>'+cols.map(c=>'<td>'+esc(x[c[0]]==null?"—":String(x[c[0]]))+'</td>').join("")+'</tr>').join("")+'</tbody></table>';
 const recent=d.recent?'<table class="simple"><thead><tr><th>'+esc(t("an.player"))+'</th><th>'+esc(t("an.match"))+'</th><th>'+esc(t("an.bat"))+'</th><th>'+esc(t("an.bowl"))+'</th><th>'+esc(t("an.points"))+'</th></tr></thead><tbody>'+
  d.recent.map(x=>'<tr><td><b>'+esc(x.name)+'</b></td><td><a href="#/match/'+x.match_id+'/scorecard">vs '+esc(x.opp||"")+'</a><div class="muted">'+esc(x.date)+'</div></td><td>'+esc(x.bat||"—")+'</td><td>'+esc(x.bowl||"—")+'</td><td>'+x.fantasy+'</td></tr>').join("")+'</tbody></table>':'';
 $("#anr").innerHTML=(d.items.length?'<div class="an-top3">'+top+'</div>':'')+
  '<div class="dl"><b>'+esc(t("an.top_players"))+'</b><label class="muted">'+esc(t("an.recent_matches"))+' <input type="checkbox" id="anv"'+(st.view==="recent"?" checked":"")+'></label></div>'+
  (d.items.length?(st.view==="recent"?recent:table):'<div class="state">'+esc(t("an.no_stats"))+'</div>')+
  '<p class="muted">'+esc(d.note)+(d.qualification?' · '+esc(t("an.qualify"))+': '+esc(d.qualification):'')+'</p>';
 $("#anv").onchange=e=>go(Object.assign({},st,{view:e.target.checked?"recent":"table"}))};

/* ---------------- Fantasy: live SH points before the SH team suggestions */
window.mcTabBefore=window.mcTabBefore||{};
/* SH Prediction XI: our best 11 on a pitch view, locked at the toss; after play, its real points and the dream team */
const ROLES=[["wicket_keeper","pxi.wk"],["batter","pxi.bat"],["all_rounder","pxi.ar"],["bowler","pxi.bowl"]];
function pitchView(m,players,key){return '<div class="pxi-pitch">'+ROLES.map(([r,l])=>{const ps=players.filter(p=>p.role===r);if(!ps.length)return "";
  return '<div class="pxi-row"><div class="pxi-rl">'+esc(t(l))+'</div><div class="pxi-ps">'+ps.map(p=>{const home=p.team_id===m.home.id,v=p[key];
   return '<div class="pxi-p"><div class="pxi-av '+(home?"h":"a")+'" data-ph="'+esc(p.name)+'">'+esc(p.name.split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase())+(p.captain?'<i class="pxi-c">C</i>':p.vice_captain?'<i class="pxi-c vc">VC</i>':'')+'</div>'+
    '<div class="pxi-n">'+esc((w=>w.length>1&&w[w.length-1].length<=2?w.slice(-2).join(" "):w[w.length-1])(p.name.split(/\s+/)))+'</div><div class="pxi-pts">'+(v==null?"—":(+v).toFixed(1))+'</div></div>'}).join("")+'</div></div>'}).join("")+'</div>'}
async function predictionXI(m){let d;try{d=await I(m,"prediction_xi")}catch(e){return ""}
 if(!d.available)return sec(esc(t("pxi.title")),'<div class="state">'+esc(d.reason)+'</div>');
 const id="pxi"+m.id,hasA=d.actual_points!=null;
 later(()=>{const b=document.getElementById(id);if(!b)return;b.querySelectorAll("[data-v]").forEach(x=>x.onclick=()=>{b.querySelectorAll("[data-v]").forEach(y=>y.classList.toggle("on",y===x));
  b.querySelectorAll(".pxi-view").forEach(v=>v.style.display=v.dataset.view===x.dataset.v?"":"none")})});
 const head='<div class="dl"><span><b>'+esc(t(d.locked?"pxi.locked":"pxi.live_until_toss"))+'</b><div class="muted">'+esc(t(d.pool_status==="playing_xi"?"pxi.from_xi":"pxi.from_squad"))+'</div></span>'+
  '<span style="text-align:right">'+esc(t("pxi.expected"))+' <b>'+d.expected_points+'</b>'+(hasA?'<br>'+esc(t("pxi.actual"))+' <b style="color:#f0b43c">'+d.actual_points+'</b>':'')+'</span></div>';
 const cmp=hasA&&d.dream_team?'<div class="mcard dl"><span>'+esc(t("pxi.dream"))+' <b>'+d.dream_team.points+'</b></span><span>'+esc(t("pxi.match_pct"))+' <b>'+(d.accuracy_pct??"—")+'%</b> · '+d.in_dream_team+'/11</span></div>':'';
 const tabs=hasA&&d.dream_team?'<div class="seg"><button class="on" data-v="xi">'+esc(t("pxi.title"))+'</button><button data-v="dream">'+esc(t("pxi.dream"))+'</button></div>':'';
 return '<section class="ins-sec" id="'+id+'"><h3><span>🎯 '+esc(t("pxi.title"))+'</span><small>'+esc(d.rule_set)+'</small></h3><div class="mcard">'+head+'</div>'+cmp+tabs+
  '<div class="pxi-view" data-view="xi">'+pitchView(m,d.players,hasA?"actual_points":"expected_points")+'</div>'+
  (hasA&&d.dream_team?'<div class="pxi-view" data-view="dream" style="display:none">'+pitchView(m,d.dream_team.players,"actual_points")+'</div>':'')+
  '<p class="muted">'+esc(d.note)+'</p></section>'}

window.mcTabBefore.fantasy=async m=>{const ss=(await predictionXI(m))+(await seriesStatsBlock(m));let d;try{d=await I(m,"fantasy")}catch(e){return ss}if(!d.players.length)return ss;
 window._fp=d;const id="fp"+m.id;
 later(()=>{const b=document.getElementById(id);if(!b)return;b.querySelectorAll("[data-fp]").forEach(x=>x.onclick=()=>fpSheet(+x.dataset.fp,m));
  const all=b.querySelector("[data-all]");if(all)all.onclick=()=>{const s=document.createElement("div");s.className="sheet";s.innerHTML='<div><div class="dl"><b>'+esc(t("ins.top_points"))+'</b><button class="btn" data-x>'+esc(t("ins.close"))+'</button></div><div class="fp-list">'+
   d.players.map((p,i)=>'<div class="dl" data-fp="'+i+'"><span><b>'+esc(p.name)+'</b><div class="muted">'+esc([p.role,p.team].filter(Boolean).join(" · "))+'</div></span><b>'+p.points.toFixed(1)+' ›</b></div>').join("")+'</div></div>';
   document.body.appendChild(s);s.onclick=e=>{if(e.target===s||e.target.closest("[data-x]"))s.remove()};s.querySelectorAll("[data-fp]").forEach(x=>x.onclick=()=>{s.remove();fpSheet(+x.dataset.fp,m)})};
  const lb=b.querySelector("[data-lb]");if(lb)lb.onclick=()=>{const s=document.createElement("div");s.className="sheet";const L=d.leaderboard;
   s.innerHTML='<div><div class="dl"><b>'+esc(t("ins.leaderboard"))+'</b><button class="btn" data-x>✕</button></div><p class="muted">'+L.teams+' '+esc(t("ins.teams"))+'</p>'+(L.items.length?L.items.map(x=>'<div class="dl"><span><b>'+esc(x.name)+'</b><div class="muted">'+x.points+' pts</div></span><span>'+esc(t("ins.rank"))+' '+x.rank+'</span></div>').join(""):NA())+'</div>';
   document.body.appendChild(s);s.onclick=e=>{if(e.target===s||e.target.closest("[data-x]"))s.remove()}}});
 return ss+'<div id="'+id+'"><div class="mcard dl"><span><b>'+d.leaderboard.teams+'</b> '+esc(t("ins.teams_playing"))+'</span><a href="javascript:void 0" data-lb>'+esc(t("ins.leaderboard"))+' ›</a></div>'+
  sec(esc(t("ins.top_points"))+(d.live?' <span class="tag" style="color:#ff6b6b">● LIVE</span>':''),'<div class="fp-cards">'+d.players.slice(0,8).map((p,i)=>'<button class="fp-card'+(p.team===lab(m,"away")||p.team===m.away.name?" aw":"")+'" data-fp="'+i+'"><small>'+esc(p.team||"")+'</small><b>'+esc(p.name)+'</b><strong>'+p.points.toFixed(1)+'</strong> <small style="display:inline">pts</small></button>').join("")+'</div>',
   '<a href="javascript:void 0" data-all>'+esc(t("ins.see_all"))+' ›</a>')+'<p class="muted">'+esc(d.rules_note)+' '+esc(t("ins.dots"))+': '+esc(d.dot_balls)+'. '+esc(t("ins.source"))+': '+esc(d.source)+'</p></div>'};
const EVL={announced:"ins.ev_announced",runs:"ins.ev_runs",fours:"4's",sixes:"6's",sr:"SR",milestone:"25/50/75/100",duck:"ins.ev_duck",dots:"ins.ev_dots",wickets:"ins.ev_wickets",lbw_bowled:"LBW/Bowled",haul:"ins.ev_haul",maidens:"ins.ev_maidens",economy:"ins.ev_economy",catches:"ins.ev_catches",three_catch:"ins.ev_3catch",stumpings:"ins.ev_stumpings",run_outs:"ins.ev_runouts"};
function fpSheet(i,m){const d=window._fp;if(!d)return;const p=d.players[i];document.querySelectorAll(".sheet").forEach(x=>x.remove());
 const s=document.createElement("div");s.className="sheet";
 s.innerHTML='<div><div class="dl"><span><b style="font-size:18px">'+esc(p.name)+'</b><div><b>'+p.points.toFixed(1)+' pts</b></div><div class="muted">'+esc([p.role,p.team].filter(Boolean).join(" · "))+'</div></span><button class="btn" data-x>✕</button></div>'+
  '<table class="simple bk"><thead><tr><th>'+esc(t("ins.event"))+'</th><th>'+esc(t("ins.actual"))+'</th><th>'+esc(t("ins.points"))+'</th></tr></thead><tbody>'+p.breakdown.map(x=>'<tr><td>'+esc(EVL[x.event]&&EVL[x.event].indexOf("ins.")===0?t(EVL[x.event]):EVL[x.event]||x.event)+'</td><td>'+(x.actual==null?"-":x.actual)+'</td><td>'+(x.points==null?"-":x.points)+'</td></tr>').join("")+'</tbody></table>'+
  '<div class="dl" style="margin-top:10px"><button class="btn" data-p '+(i?'':'disabled')+'>‹ '+esc(t("ins.prev"))+'</button><button class="btn" data-n '+(i<d.players.length-1?'':'disabled')+'>'+esc(t("ins.next"))+' ›</button></div></div>';
 document.body.appendChild(s);s.onclick=e=>{if(e.target===s||e.target.closest("[data-x]"))s.remove();if(e.target.closest("[data-p]")&&i)fpSheet(i-1,m);if(e.target.closest("[data-n]")&&i<d.players.length-1)fpSheet(i+1,m)}}

/* ---------------- Discussions */
window.mcTab.community=async m=>{const id="dz"+m.id;let sort=sessionStorage.getItem("shp_dsort")||"top";
 const load=async()=>{const box=document.getElementById(id);if(!box)return;let d;
  try{d=await api("/matches/"+m.id+"/discussions?sort="+sort)}catch(e){box.querySelector(".dz-list").innerHTML='<div class="state">'+esc(e.message||String(e))+'</div>';return}
  box.querySelectorAll("[data-s]").forEach(b=>b.classList.toggle("on",b.dataset.s===sort));
  const P=d.poll;box.querySelector(".poll").innerHTML='<div class="mcard"><b>'+esc(t("ins.who_will_win"))+'</b>'+P.options.map(o=>'<button data-v="'+o.team_id+'" class="'+(P.my_vote===o.team_id?"me":"")+'"'+(P.open?'':' disabled')+'><i style="width:'+(P.votes?o.pct:0)+'%"></i><span>'+esc(o.team)+(P.votes?' · '+o.pct+'%':'')+'</span></button>').join("")+
   '<div class="muted">'+P.votes.toLocaleString()+' '+esc(t("ins.votes"))+(P.open?'':' · '+esc(t("ins.voting_closed")))+'</div></div>';
  box.querySelectorAll("[data-v]").forEach(b=>b.onclick=async()=>{if(!TOKEN){location.hash="#/login";return}try{await api("/matches/"+m.id+"/fan-poll",{method:"POST",body:JSON.stringify({team_id:+b.dataset.v})});load()}catch(e){alert(e.message)}});
  const L=box.querySelector(".dz-list");L.innerHTML=d.items.length?d.items.map(postCard).join(""):'<div class="state">'+esc(t("ins.no_posts"))+'</div>';if(window.bindPosts)bindPosts(L,load)};
 later(()=>{const box=document.getElementById(id);if(!box)return;
  box.querySelectorAll("[data-s]").forEach(b=>b.onclick=()=>{if(b.dataset.s==="mine"&&!TOKEN){location.hash="#/login";return}sort=b.dataset.s;sessionStorage.setItem("shp_dsort",sort);load()});
  const f=box.querySelector("form");f.onsubmit=async e=>{e.preventDefault();if(!TOKEN){location.hash="#/login";return}const ta=f.querySelector("textarea"),v=ta.value.trim();if(!v)return;
   try{await api("/social/posts",{method:"POST",body:JSON.stringify({kind:"text",body:v,match_id:m.id})});ta.value="";sort="latest";load()}catch(er){alert(er.message)}};load()});
 return '<div id="'+id+'"><div class="seg"><button data-s="top">'+esc(t("ins.top"))+'</button><button data-s="latest">'+esc(t("ins.latest"))+'</button><button data-s="mine">'+esc(t("ins.my_posts"))+'</button></div>'+
  '<div class="poll"></div><form class="composer"><textarea maxlength="2000" rows="1" placeholder="'+esc(t("ins.add_post"))+'"></textarea><button class="btn primary" aria-label="'+esc(t("ins.send"))+'">➤</button></form><div class="dz-list">'+loading()+'</div>'+
  '<p class="muted"><a href="#/match/'+m.id+'/prediction">'+esc(t("so.sh_ai"))+' ›</a> · '+esc(t("ins.poll_note"))+'</p></div>'};

/* ---------------- Live + Commentary: last two overs, partnership, last wicket */
const ovStrip=x=>!x||!x.last_overs||!x.last_overs.length?"":'<div class="card ovchips">'+x.last_overs.map((o,i)=>(i?'<span class="sep"></span>':'')+'<small>'+esc(t("ins.over"))+' '+o.over+'</small>'+o.balls.map(chip).join("")+'<small>= '+o.runs+'</small>').join("")+'</div>';
const pshipLine=x=>!x||(!x.partnership&&!x.last_wicket)?"":'<div class="card dl"><span>'+esc(t("ins.pship"))+': <b>'+(x.partnership?x.partnership.runs+' ('+x.partnership.balls+')':"—")+'</b></span><span class="muted">'+esc(t("ins.last_wkt"))+': '+(x.last_wicket?esc(x.last_wicket.name)+(x.last_wicket.runs!=null?' '+x.last_wicket.runs+' ('+x.last_wicket.balls+')':''):"—")+'</span></div>';
/* Live tab in the reference order: overs strip, batters R (B) 4s 6s SR with the striker marked, partnership + last wicket, bowler W-R Ov Econ */
const baseLive=window.mcTab.live;
window.mcTab.live=async m=>{const pd=m.provider_detail;if(!pd||!pd.scorecard||!pd.scorecard.length||(m.status!=="live"&&!pd.featured))return baseLive?baseLive(m):null;
 let x=null;try{x=await I(m,"live")}catch(e){}
 const li=pd.scorecard[pd.scorecard.length-1],balls=pd.balls||[],lb=balls[balls.length-1]||{};
 const notOut=(li.batting||[]).filter(b=>/not out|batting/i.test(b.dismissal||""));const bats=notOut.length?notOut:(li.batting||[]).slice(-2);
 const same=(a,b)=>a&&b&&(a===b||String(a).split(" ").slice(-1)[0]===String(b).split(" ").slice(-1)[0]);
 const bw=(li.bowling||[]).find(b=>same(b.name,lb.bowler))||(li.bowling||[]).slice(-1)[0];
 const sr=b=>b.b?(100*(b.r||0)/b.b).toFixed(1):"—";
 return '<div class="card lv"><table class="simple lvt"><thead><tr><th>'+esc(t("an.player"))+'</th><th>R (B)</th><th>4s</th><th>6s</th><th>SR</th></tr></thead><tbody>'+
  bats.map(b=>'<tr><td>'+phAvatar(b.name)+'<b>'+esc(b.name||"")+'</b>'+(same(b.name,lb.batter)?' 🏏':'')+'</td><td><b>'+(b.r??0)+'</b> ('+(b.b??0)+')</td><td>'+(b.fours??0)+'</td><td>'+(b.sixes??0)+'</td><td>'+sr(b)+'</td></tr>').join("")+'</tbody></table>'+
  '<div class="dl lvp"><span>'+esc(t("ins.pship"))+': <b>'+(x&&x.partnership?x.partnership.runs+' ('+x.partnership.balls+')':"—")+'</b></span><span class="muted">'+esc(t("ins.last_wkt"))+': '+(x&&x.last_wicket?esc(x.last_wicket.name)+(x.last_wicket.runs!=null?' '+x.last_wicket.runs+' ('+x.last_wicket.balls+')':''):"—")+'</span></div>'+
  (bw?'<table class="simple lvt"><thead><tr><th>'+esc(t("an.bowl"))+'</th><th>W-R</th><th>Ov</th><th>Econ</th></tr></thead><tbody><tr><td>'+phAvatar(bw.name)+'<b>'+esc(bw.name||"")+'</b></td><td><b>'+(bw.w??0)+'-'+(bw.r??0)+'</b></td><td>'+esc(String(bw.o??"—"))+'</td><td>'+(bw.eco??"—")+'</td></tr></tbody></table>':'')+
  '</div><p class="muted">'+esc(t("ins.source"))+': '+esc(pd.source)+'</p>'};


/* ---------------- Scorecard: one innings at a time, with a switcher and "yet to bat" */
const baseScore=window.mcTab.scorecard;
window.mcTab.scorecard=async m=>{const pd=m.provider_detail;if(!pd||!pd.scorecard||!pd.scorecard.length)return baseScore?baseScore(m):null;
 const html=await baseScore(m);if(html==null)return null;const id="sc"+m.id,S=pd.scorecard;
 later(()=>{const box=document.getElementById(id);if(!box)return;const cards=[...box.querySelectorAll(":scope > .card")].slice(0,S.length);
  const show=k=>{cards.forEach((c,i)=>c.style.display=i===k?"":"none");box.querySelectorAll("[data-i]").forEach(b=>b.classList.toggle("on",+b.dataset.i===k))};
  box.querySelectorAll("[data-i]").forEach(b=>b.onclick=()=>show(+b.dataset.i));show(S.length-1)});
 const nm=s=>String(s||"").replace(/\s*inning\s*\d+$/i,"").trim();
 const ytb=S.map(inn=>{const team=(pd.squads||[]).find(q=>(q.team||"").toLowerCase()===nm(inn.inning).toLowerCase());if(!team||team.players.length>12)return "";
  const did=new Set(inn.batting.map(b=>(b.name||"").toLowerCase()));const rest=team.players.filter(p=>!did.has((p.name||"").toLowerCase()));
  return rest.length?'<p class="muted"><b>'+esc(t("ins.yet_to_bat"))+':</b> '+rest.map(p=>esc(p.name)).join(", ")+'</p>':""});
 return '<div id="'+id+'"><div class="inn-sw">'+S.map((inn,i)=>'<button data-i="'+i+'">'+esc(nm(inn.inning))+(inn.total?' <small>'+inn.total.r+'-'+inn.total.w+' ('+esc(String(inn.total.o))+')</small>':'')+'</button>').join("")+'</div>'+
  html.split('<div class="card">').map((part,i)=>i&&i<=S.length&&ytb[i-1]?part.replace(/<dl class="kv">/,ytb[i-1]+'<dl class="kv">'):part).join('<div class="card">')+'</div>'};

/* ---------------- Points table */
window.mcTab.seriesstats=async m=>{let d;try{d=await I(m,"points")}catch(e){return null}if(!d.table||!d.table.length)return '<div class="state">'+esc(t("data.na"))+'</div>';
 const id="pt"+m.id;later(()=>{const b=document.getElementById(id);if(!b)return;const cb=b.querySelector("input");cb.onchange=()=>b.classList.toggle("showform",cb.checked)});
 return '<div id="'+id+'"><div class="dl"><b>'+esc(t("ins.points_table"))+'</b><label class="muted">'+esc(t("ins.team_form"))+' <input type="checkbox"></label></div>'+
  '<style>#'+id+' .fcol{display:none}#'+id+'.showform .fcol{display:table-cell}#'+id+'.showform .ncol{display:none}</style><table class="simple pt"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>L</th><th>NR</th><th class="ncol">NRR</th><th class="fcol">'+esc(t("ins.form"))+'</th><th>Pts</th></tr></thead><tbody>'+
  d.table.map((x,i)=>'<tr class="'+(d.teams.includes(x.team_id)?"hl":"")+'"><td>'+(i+1)+'</td><td><b>'+esc(x.short_code||x.team)+'</b></td><td>'+x.played+'</td><td>'+x.won+'</td><td>'+x.lost+'</td><td>'+(x.no_result+x.tied)+'</td><td class="ncol">'+(x.nrr==null?"—":(x.nrr>0?"+":"")+x.nrr.toFixed(3))+'</td><td class="fcol">'+x.form.map(f=>'<span class="fchip '+f+'" style="width:20px;height:20px;font-size:10px">'+f+'</span>').join(" ")+'</td><td><b style="color:#f0b43c">'+x.points+'</b></td></tr>').join("")+'</tbody></table><p class="muted">'+esc(d.rule)+'</p>'+
  (d.other_seasons.length?sec(esc(t("ins.other_seasons")),'<div class="mcard">'+d.other_seasons.map(s=>'<a class="dl" href="#/series/'+s.id+'"><b>'+esc(s.name)+'</b><span>›</span></a>').join("")+'</div>'):'')+
  '<div class="dgrid"><div class="card"><h3>'+esc(t("ins.most_runs"))+'</h3>'+(d.top_batters.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.runs+'</span></div>').join("")||NA())+'</div><div class="card"><h3>'+esc(t("ins.most_wkts"))+'</h3>'+(d.top_bowlers.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.wickets+'</span></div>').join("")||NA())+'</div></div></div>'};

/* ---------------- Graphs: SH win probability, Manhattan, Worm, over history */
function svgLine(series,maxX,maxY,opts){const W=340,H=180,pl=30,pb=20,X=x=>pl+(W-pl-6)*x/maxX,Y=y=>H-pb-(H-pb-8)*y/maxY;let g='';
 for(let i=0;i<=4;i++){const y=maxY*i/4;g+='<line x1="'+pl+'" x2="'+W+'" y1="'+Y(y)+'" y2="'+Y(y)+'" stroke="currentColor" opacity=".12"/><text x="2" y="'+(Y(y)+4)+'" font-size="9" fill="currentColor" opacity=".7">'+Math.round(y)+'</text>'}
 (opts&&opts.marks||[]).forEach(x=>g+='<line x1="'+X(x)+'" x2="'+X(x)+'" y1="4" y2="'+(H-pb)+'" stroke="currentColor" opacity=".35" stroke-dasharray="3 3"/>');
 series.forEach(s=>{if(s.pts.length<2)return;g+='<polyline fill="none" stroke="'+s.c+'" stroke-width="2" points="'+s.pts.map(p=>X(p[0])+","+Y(p[1])).join(" ")+'"/>'+(s.dots||[]).map(p=>'<circle cx="'+X(p[0])+'" cy="'+Y(p[1])+'" r="3.5" fill="'+s.c+'"/>').join("")});
 return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" role="img">'+g+'</svg>'}
window.mcTab.graphs=async m=>{let d;try{d=await I(m,"graphs")}catch(e){return null}if(!d.innings.length)return null;
 const col=s=>s==="away"?"#ff8a1f":"#4fb3ff",nameOf=s=>s?lab(m,s):"";let out="";
 if(d.win_probability.length>1){const quota={T10:10,T20:20,"The Hundred":17,ODI:50,"List A":50}[m.format]||20;const xs=d.win_probability.map(p=>(p.innings-1)*quota+p.over);
  const last=d.win_probability[d.win_probability.length-1];
  out+=sec(esc(t("ins.win_prob")),'<div class="card">'+svgLine([{c:"#4fb3ff",pts:d.win_probability.map((p,i)=>[xs[i],p.home])},{c:"#ff8a1f",pts:d.win_probability.map((p,i)=>[xs[i],100-p.home])}],quota*2,100,{marks:[quota]})+
   '<div class="dl"><b class="c-home">■ '+esc(lab(m,"home"))+' '+last.home+'%</b><b class="c-away">'+esc(lab(m,"away"))+' '+(100-last.home).toFixed(1)+'% ■</b></div><p class="muted">'+esc(d.win_probability_note)+'</p></div>')}
 else out+='<p class="muted">'+esc(d.win_probability_note)+'</p>';
 const maxO=Math.max(...d.innings.map(i=>i.overs.length?i.overs[i.overs.length-1].over:1)),maxR=Math.max(6,...d.innings.flatMap(i=>i.overs.map(o=>o.runs)));
 const bw=320/(maxO*d.innings.length+1);
 let man='<svg viewBox="0 0 340 180" width="100%">';d.innings.forEach((inn,k)=>inn.overs.forEach(o=>{const h=150*o.runs/maxR,x=16+((o.over-1)*d.innings.length+k)*bw;man+='<rect x="'+x+'" y="'+(160-h)+'" width="'+Math.max(1,bw-1)+'" height="'+h+'" fill="'+col(inn.side)+'"/>'+(o.wickets?'<circle cx="'+(x+bw/2)+'" cy="'+(154-h)+'" r="3" fill="#ff5c5c"/>':'')}));
 for(let o=5;o<=maxO;o+=5)man+='<text x="'+(16+(o-1)*d.innings.length*bw)+'" y="176" font-size="9" fill="currentColor" opacity=".7">'+o+'</text>';man+='</svg>';
 const maxT=Math.max(10,...d.innings.flatMap(i=>i.overs.map(o=>o.total)));
 const worm=svgLine(d.innings.map(i=>({c:col(i.side),pts:[[0,0]].concat(i.overs.map(o=>[o.over,o.total])),dots:i.overs.filter(o=>o.wickets).map(o=>[o.over,o.total])})),Math.max(maxO,1),maxT);
 const legend='<div class="dl">'+d.innings.map(i=>'<b style="color:'+col(i.side)+'">■ '+esc(nameOf(i.side)||(t("ins.innings")+" "+i.innings))+'</b>').join("")+'</div>';
 out+='<details class="gx" open><summary>'+esc(t("ins.manhattan"))+'</summary>'+man+legend+'</details><details class="gx"><summary>'+esc(t("ins.worm"))+'</summary>'+worm+legend+'</details>';
 const id="oh"+m.id;later(()=>{const b=document.getElementById(id);if(!b)return;const show=k=>{b.querySelectorAll("[data-h]").forEach(x=>x.classList.toggle("on",+x.dataset.h===k));b.querySelectorAll(".ohl").forEach((x,i)=>x.style.display=i===k?"":"none")};
  b.querySelectorAll("[data-h]").forEach(x=>x.onclick=()=>show(+x.dataset.h));show(d.innings.length-1)});
 out+=sec(esc(t("mc.history")),'<div id="'+id+'"><div class="inn-sw">'+d.innings.map((i,k)=>'<button data-h="'+k+'">'+esc(nameOf(i.side)||(t("ins.innings")+" "+i.innings))+'</button>').join("")+'</div>'+
  d.innings.map(i=>'<div class="ohl">'+i.overs.slice().reverse().map(o=>'<details class="ovh-d"><summary class="ovh"><span>'+o.over+' '+esc(t("ins.over"))+'</span><span>'+esc(nameOf(i.side))+' <b>'+o.total+'/'+o.total_wickets+'</b> <small class="muted">(+'+o.runs+')</small></span></summary><div class="ovchips">'+o.balls.map(chip).join("")+'</div></details>').join("")+'</div>').join("")+'</div>');
 return out+'<p class="muted">'+esc(t("ins.source"))+': '+esc(d.source)+(d.note?' · '+esc(d.note):'')+'</p>'};
})();
/* ---------------- Tipster reports: a slow upward scroll under Live (and under Info before the match) */
(function(){
const later=window.mcLater;
const PT={toss:"ins.pt_toss",winner:"ins.pt_winner",first_innings_score:"ins.pt_1st",second_innings_score:"ins.pt_2nd",live_winner:"ins.pt_winner"};
const av=n=>esc(String(n||"?").split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase());
const res=r=>r?'<span class="res-'+esc(r)+'">'+(r==="correct"?"✓":r==="incorrect"?"✗":esc(r))+'</span>':'';
const line=x=>'<div><span class="muted">'+esc(t(PT[x.type]||x.type))+':</span> <b>'+esc(String(x.pick??"—"))+'</b>'+(x.confidence!=null?' <small class="muted">'+Math.round(x.confidence)+'%</small>':'')+' '+res(x.result)+(x.after_toss&&x.type!=="live_winner"?' <span class="tag">'+esc(t("ins.after_toss"))+'</span>':'')+'</div>'+(x.note?'<div class="muted">'+esc(x.note)+'</div>':'');
async function block(m){let d;try{d=await api("/matches/"+m.id+"/insights?part=tipsters")}catch(e){return ""}
 const W=d.window,state=W.pre_match==="open"?t("ins.window_pre"):W.pre_match==="post_toss"?t("ins.window_post"):W.update==="open"?t("ins.window_upd"):t("ins.window_closed");
 const head='<h3><span>'+esc(t("ins.tipster_reports"))+' <small>('+d.items.length+')</small></span><small>'+esc(state)+'</small></h3>';
 if(!d.items.length)return '<section class="ins-sec">'+head+'<div class="state">'+esc(t("ins.no_tipsters"))+'</div><p class="muted">'+esc(d.rule)+'</p></section>';
 const items=d.items.map(e=>'<div class="tp"><div class="who"><span class="av">'+av(e.name)+'</span><span><a href="#/u/'+esc(e.username||"")+'"><b>'+esc(e.name)+'</b></a>'+(e.verified?' <span class="tag ver">Expert</span>':'')+
  '<div class="muted">'+esc(new Date(e.first_at).toLocaleString(undefined,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}))+'</div></span></div>'+
  '<div class="pk">'+e.reports.map(line).join("")+'</div>'+(e.update?'<div class="up"><b>'+esc(t("ins.update"))+'</b>'+line(e.update)+'</div>':'')+'</div>').join("");
 const id="tp"+m.id;
 later(()=>{const w=document.getElementById(id);if(!w)return;const roll=w.querySelector(".tp-roll");
  if(roll.scrollHeight/2<=w.clientHeight+10){w.classList.add("still");roll.innerHTML=items;return}
  roll.style.setProperty("--dur",Math.max(20,Math.round(roll.scrollHeight/2/18))+"s");
  w.addEventListener("touchstart",()=>w.classList.add("paused"),{passive:true});w.addEventListener("touchend",()=>setTimeout(()=>w.classList.remove("paused"),2500),{passive:true})});
 return '<section class="ins-sec">'+head+'<div class="tp-wrap" id="'+id+'"><div class="tp-roll">'+items+items+'</div></div><p class="muted">'+esc(d.rule)+'</p></section>'}
window.mcTabEnd=window.mcTabEnd||{};
window.mcTabEnd.live=block;
window.mcTabEnd.info=m=>m.status==="scheduled"?block(m):"";
})();
/* ---------------- SH Agent Prediction (first on the page), Playing XI, Results & Stats, live refresh */
(function(){
const later=window.mcLater;
const I=(m,part)=>api("/matches/"+m.id+"/insights?part="+part);
const NA=()=>'<p class="muted">'+esc(t("data.na"))+'</p>';
const STG={pre_match:"ag.pre_match",post_toss:"ag.post_toss",playing_xi:"ag.playing_xi"};
window.mcAgent=async(m,box)=>{if(!box)return;let d;try{d=await I(m,"agent")}catch(e){return}
 const H=d.headline,L=d.live;if(!H&&!L){box.innerHTML=d.note?'<div class="agent"><b>🧠 '+esc(t("ag.title"))+'</b><p class="muted">'+esc(d.note)+'</p></div>':"";return}
 const p=L||H,hp=p.home_win_probability,ap=p.away_win_probability;
 const pick=H?(H.predicted_team||""):(hp>=50?m.home.name:m.away.name);
 box.innerHTML='<details class="agent"><summary class="ag-top"><span>🧠 <b>'+esc(t("ag.title"))+'</b> · <b>'+esc(pick)+'</b> '+Math.round(Math.max(hp,ap))+'%</span><small class="muted">'+esc(L?t("ag.live"):t(STG[H.stage]))+' ▾</small></summary>'+
  '<div class="ag-bar"><i style="width:'+hp+'%;background:#4fb3ff"></i><i style="width:'+ap+'%;background:#ff8a1f"></i></div>'+
  '<div class="dl"><b class="c-home">'+esc(m.home.short_code||m.home.name)+' '+hp+'%</b><b class="c-away">'+ap+'% '+esc(m.away.short_code||m.away.name)+'</b></div>'+
  (H?'<div class="muted">'+esc(t("ag.confidence"))+': '+esc(H.confidence_level||"—")+' · '+esc(H.model)+' · '+esc(new Date(H.created_at).toLocaleString(undefined,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}))+'</div>':'')+
  '<div class="ag-stages">'+d.stages.map(s=>'<span class="'+(s.outcome||"")+'">'+esc(t(STG[s.stage]))+': '+esc(s.predicted_team||"")+' '+s.confidence+'%'+(s.outcome==="correct"?" ✓":s.outcome==="incorrect"?" ✗":"")+'</span>').join("")+(L?'<span>'+esc(t("ag.live"))+': '+esc(t("ins.over"))+' '+L.after_over+'</span>':'')+'</div>'+
  '<p class="muted" style="margin:6px 0 0">'+esc(d.verification)+' <a href="#/match/'+m.id+'/prediction">'+esc(t("ag.why"))+' ›</a></p></details>'};

/* Playing XI: our tables first, then the XI / squad the source sent; captain and keeper marked when the source says so */
const baseXI=window.mcTab.xi;
window.mcTab.xi=async m=>{if((m.playing_xi&&m.playing_xi.length)||(m.squads&&m.squads.length))return baseXI?baseXI(m):null;
 const sq=m.provider_detail&&m.provider_detail.squads;if(!sq||!sq.length)return '<div class="state">'+esc(t("pxi.from_squad"))+' — '+esc(t("data.na"))+'</div>';
 const conf=sq.every(x=>(x.players||[]).length<=12);
 const roleTag=r=>{r=(r||"").toLowerCase();return /wk|keeper/.test(r)?"WK":/allrounder|all-rounder/.test(r.replace(/\s/g,""))?"AR":/bowl/.test(r)?"BOWL":r?"BAT":""};
 return '<p class="muted">'+esc(t(conf?"pxi.from_xi":"pxi.from_squad"))+' · '+esc(t("ins.source"))+': CricketData.org (PROVIDER_REPORTED)</p>'+sq.map(T=>{const ps=T.players||[];
  return '<div class="card"><h3>'+esc(T.team)+' <small class="muted">'+ps.length+'</small></h3><table class="simple"><tbody>'+ps.map((p,i)=>{const cap=/\(c\)|captain/i.test((p.name||"")+" "+(p.role||""));
   return '<tr'+(conf&&i>=11?' class="muted"':'')+'><td>'+(i+1)+'</td><td><b>'+esc(String(p.name||"").replace(/\s*\((c|wk|c & wk)\)/ig,""))+'</b>'+(cap?' <span class="tag">C</span>':'')+(roleTag(p.role)==="WK"?' <span class="tag">WK</span>':'')+(conf&&i>=11?' <span class="tag">'+esc(t("xi.sub"))+'</span>':'')+'</td><td class="muted">'+esc(p.role||"—")+'</td></tr>'}).join("")+'</tbody></table></div>'}).join("")};

/* Results & Stats */
window.mcTab.results=async m=>{let ag=null,tp=null,pts=null,fan=null;
 [ag,tp,pts,fan]=await Promise.all([I(m,"agent").catch(()=>null),I(m,"tipsters").catch(()=>null),I(m,"points").catch(()=>null),I(m,"fantasy").catch(()=>null)]);
 const src=(m.result_source||m.source||"");const st=/^Owner Google Sheet/.test(m.result_source||"")?"USER_REPORTED":/CricketData/i.test(m.result_source||"")?"PROVIDER_REPORTED":m.result_type?"VERIFIED":"PENDING";
 let out='<div class="card"><h3>'+esc(t("mc.results"))+'</h3>'+(m.result_type?'<div class="ag-pick" style="font-size:20px;font-weight:800">'+esc(m.winner_team_id?((m.winner_team_id===m.home.id?m.home.name:m.away.name)+" "+t("rs.won")+(m.margin?" · "+m.margin:"")):m.result_type.replace(/_/g," "))+'</div>'
  :'<div class="state">'+esc(t(m.status==="live"?"rs.in_progress":"rs.pending"))+'</div>')+
  '<p class="muted">'+esc(t("rs.status"))+': <span class="tag">'+st+'</span>'+(m.result_source?' · '+esc(m.result_source):'')+'</p>'+
  (m.reported_scores&&m.reported_scores.length?'<p>'+m.reported_scores.map(s=>'<b>'+esc(s.team)+'</b> '+s.runs+'/'+s.wickets+(s.overs?' ('+esc(s.overs)+')':'')).join(" · ")+' <span class="tag">USER_REPORTED</span></p>':'')+
  '<p class="muted">'+esc(t("rs.potm"))+': '+esc(t("data.na"))+'</p></div>';
 if(fan&&fan.players&&fan.players.length&&m.status!=="scheduled"){const P=fan.players;const by=(f)=>P.slice().sort((a,b)=>f(b)-f(a))[0];
  const ev=(p,k)=>((p.breakdown||[]).find(x=>x.event===k)||{}).actual||0;const tr=by(p=>ev(p,"runs")),tw=by(p=>ev(p,"wickets"));
  out+='<div class="card"><h3>'+esc(t("rs.top"))+'</h3><div class="dl"><span>'+esc(t("an.cat_runs"))+'</span><b>'+(ev(tr,"runs")?esc(tr.name)+' '+ev(tr,"runs"):"—")+'</b></div><div class="dl"><span>'+esc(t("an.cat_wickets"))+'</span><b>'+(ev(tw,"wickets")?esc(tw.name)+' '+ev(tw,"wickets"):"—")+'</b></div><div class="dl"><span>'+esc(t("an.cat_fantasy"))+'</span><b>'+esc(P[0].name)+' '+P[0].points+'</b></div><p class="muted">'+esc(t("rs.top_note"))+'</p></div>'}
 out+='<div class="card"><h3>'+esc(t("rs.accuracy"))+'</h3>'+(ag&&ag.stages.length?ag.stages.map(s=>'<div class="dl"><span>'+esc(t(STG[s.stage]))+'</span><b>'+esc(s.predicted_team||"")+' '+s.confidence+'% '+(s.outcome==="correct"?"✓":s.outcome==="incorrect"?"✗":"·")+'</b></div>').join(""):NA());
 if(tp&&tp.items.length){let ok=0,bad=0;tp.items.forEach(e=>e.reports.forEach(r=>{if(r.result==="correct")ok++;else if(r.result==="incorrect")bad++}));
  out+='<div class="dl"><span>'+esc(t("ins.tipster_reports"))+'</span><b>'+ok+' ✓ · '+bad+' ✗ <small class="muted">('+tp.items.length+')</small></b></div>'}
 if(m.sheet_picks){const sp=m.sheet_picks;out+='<div class="dl"><span>'+esc(t("rs.sheet_picks"))+'</span><b>'+esc([sp.toss_pick&&("Toss "+sp.toss_pick+" "+(sp.toss_mark||"")),sp.win_pick&&("Win "+sp.win_pick+" "+(sp.win_mark||""))].filter(Boolean).join(" · "))+'</b></div><p class="muted">USER_REPORTED · '+esc(sp.notes||"")+'</p>'}
 out+='</div>';
 if(pts&&pts.table&&pts.table.length){const rows=pts.table.map((x,i)=>Object.assign({rank:i+1},x)).filter(x=>pts.teams.includes(x.team_id));
  out+='<div class="card"><h3>'+esc(t("ins.in_points"))+'</h3><table class="simple"><tbody>'+rows.map(x=>'<tr><td>'+x.rank+'</td><td><b>'+esc(x.short_code||x.team)+'</b></td><td>'+x.played+' P</td><td>'+x.won+' W</td><td><b>'+x.points+'</b></td></tr>').join("")+'</tbody></table><a href="#/match/'+m.id+'/seriesstats">'+esc(t("ins.points_table"))+' ›</a></div>'}
 return out};

/* live refresh without reloading: Server-Sent Events for live matches, with a 30-second fallback when the stream drops */
let ES=null,ESmid=null,timer=null,poll=null;
window.mcLive=(m,tab)=>{const on=m.status==="live";
 if(on&&window.mcFlash&&window._mcFlashed!==m.id){window._mcFlashed=m.id;const B=(m.provider_detail&&m.provider_detail.balls)||[];const lb=B[B.length-1];if(lb)setTimeout(()=>mcFlash({runs:lb.runs,extra:lb.extra,wicket:lb.wicket,batter:lb.batter}),600)}if(!on||!window.EventSource){if(ES&&ESmid!==m.id){ES.close();ES=null;ESmid=null}return}
 const refresh=()=>{clearTimeout(timer);timer=setTimeout(()=>{if(!new RegExp("^#/match/"+m.id+"(/|$)").test(location.hash))return;const y=scrollY;route();setTimeout(()=>scrollTo(0,y),400)},1500)};
 if(ES&&ESmid===m.id)return;if(ES)ES.close();ESmid=m.id;ES=new EventSource("/api/v1/matches/"+m.id+"/stream?last_id=latest");
 ["ball","delivery","probability","status"].forEach(k=>ES.addEventListener(k,e=>{if(k==="status")return;
  if(k==="delivery"){let ev={};try{ev=JSON.parse(e.data)}catch(x){}
   // flash first, then the new score is projected into the plate; the rest of the tab refreshes a little later
   if(window.mcFlash){ev.after=()=>{if(window.mcBoardRefresh)mcBoardRefresh(m.id)};mcFlash(ev)}clearTimeout(timer);timer=setTimeout(()=>refresh(),6000);return}
  if(window.mcBoardRefresh)mcBoardRefresh(m.id);clearTimeout(timer);timer=setTimeout(()=>refresh(),3000)}));
 ES.onerror=()=>{if(!poll)poll=setInterval(()=>{if(new RegExp("^#/match/"+m.id+"(/|$)").test(location.hash)&&document.visibilityState==="visible")refresh();else{clearInterval(poll);poll=null}},30000)};
 ES.onopen=()=>{if(poll){clearInterval(poll);poll=null}}};
window.addEventListener("hashchange",()=>{if(ES&&ESmid&&!new RegExp("^#/match/"+ESmid+"(/|$)").test(location.hash)){ES.close();ES=null;ESmid=null}});
})();
