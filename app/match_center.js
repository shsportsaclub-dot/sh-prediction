/* SH Match Center: live score header and data-driven tabs (Live, Scorecard, Squads, Graphs, H2H, Info).
   Uses, in this order: our own ball-by-ball (SH scoring / Cricsheet) -> provider scorecard (CricketData) -> score line only.
   Nothing is filled in when a source has no figure: the tab says what is missing and why. Our own layout and colours. */
"use strict";
(function(){
const PD=m=>m.provider_detail&&m.provider_detail.scorecard&&m.provider_detail.scorecard.length?m.provider_detail:null;
const oversToBalls=o=>{if(o==null)return 0;const s=String(o).split(".");return (+s[0]||0)*6+(+s[1]||0)};
const crr=(r,o)=>{const b=oversToBalls(o);return b?(r*6/b).toFixed(2):"—"};
const lastInn=sc=>sc&&sc.length?sc[sc.length-1]:null;
const ago=at=>{if(!at)return "";const s=(Date.now()-new Date(at))/1000;return s<90?"just now":s<3600?Math.round(s/60)+" min ago":Math.round(s/3600)+" h ago"};
const titleCase=s=>String(s).replace(/\b([a-z])/g,c=>c.toUpperCase());
const teamShort=(m,name)=>{if(!name)return "";const n=String(name).replace(/ inning \d+$/i,"").trim(),l=n.toLowerCase();if(l===String(m.home.name).toLowerCase())return m.home.short_code||m.home.name;if(l===String(m.away.name).toLowerCase())return m.away.short_code||m.away.name;return n===l?titleCase(n):n};
const ball=b=>{const v=b.wicket?"W":String(b.runs||0);const cls=b.wicket?"bw":b.runs>=6?"b6":b.runs===4?"b4":b.runs>0?"b1":"b0";return '<span class="bl '+cls+'" title="'+esc((b.over+1)+"."+(b.ball||"")+" "+(b.batter||"")+" ← "+(b.bowler||""))+'">'+esc(v)+'</span>'};

window.mcHeader=function(m){
 const pd=PD(m),L=m.live_score;let lines=[],cr="",ev="";
 if(pd){pd.scorecard.forEach(i=>{if(i.total)lines.push({t:teamShort(m,i.inning),r:i.total.r,w:i.total.w,o:i.total.o})});const li=lastInn(pd.scorecard);if(li&&li.total)cr=crr(li.total.r,li.total.o);
  const lb=(pd.balls||[]).slice(-1)[0];if(lb)ev=lb.wicket?"WICKET":lb.runs===6?"SIX":lb.runs===4?"FOUR":"";}
 else if(L&&L.innings&&L.innings.length){L.innings.forEach(i=>lines.push({t:teamShort(m,i.inning),r:i.r,w:i.w,o:i.o}));const li=L.innings[L.innings.length-1];cr=crr(li.r,li.o)}
 if(!lines.length)return "";
 const toss=m.toss_winner_id?(m.toss_winner_id===m.home.id?(m.home.short_code||m.home.name):(m.away.short_code||m.away.name))+(m.toss_decision?" · "+m.toss_decision:""):"";
 const quota={T10:60,T20:120,"The Hundred":100,ODI:300,"List A":300}[m.format];let cells=[["CRR",cr]],banner="";
 if(lines.length>=2&&quota){const tgt=lines[0].r+1,used=oversToBalls(lines[1].o),need=tgt-lines[1].r,left=quota-used;cells.push([t("mc.target"),tgt]);
  if(m.status==="live"&&need>0&&left>0){cells.push(["RRR",(need*6/left).toFixed(2)]);banner=lines[1].t+" need "+need+" from "+left+" balls"}}
 else if(lines.length>=1&&quota&&m.status==="live"){cells.push([t("mc.overs_left"),((quota-oversToBalls(lines[0].o))/6).toFixed(1)])}
 if(!quota&&lines.length>=2){const tot={};lines.forEach(x=>tot[x.t]=(tot[x.t]||0)+x.r);const cur=lines[lines.length-1].t,other=Object.keys(tot).find(k=>k!==cur);
  if(other!=null){const d=tot[cur]-tot[other];banner=cur+" "+t(d>=0?"mc.lead_by":"mc.trail_by")+" "+Math.abs(d)+" runs"}}
 if(toss)cells.push(["Toss",toss]);
 return '<div class="mc-head" aria-live="polite"><div class="mc-lines">'+lines.map((x,i)=>'<div class="mc-line'+(i===lines.length-1?' cur':'')+'"><b>'+esc(x.t)+'</b> <span class="mc-score">'+x.r+'-'+x.w+'</span> <span class="muted">('+esc(String(x.o))+')</span></div>').join("")+'</div>'+
  (ev?'<div class="mc-ev ev-'+ev.toLowerCase()+'">'+ev+'</div>':'')+'</div><div class="mc-strip4" style="grid-template-columns:repeat('+cells.length+',1fr)">'+cells.map(([a,b])=>'<div>'+esc(String(a))+'<b>'+esc(String(b))+'</b></div>').join("")+'</div>'+
  (banner?'<div class="mc-lead">'+esc(banner)+'</div>':'')+'<div class="row" style="margin:6px 2px"><span class="tag ds-'+esc(m.data_status)+'">'+esc(m.data_status_label||"")+'</span></div>'+
  (pd&&pd.scorecard_at?'<div class="muted mc-fresh">Updated '+ago(pd.scorecard_at)+' · source '+esc(pd.source)+'</div>':L?'<div class="muted mc-fresh">Score updated '+ago(L.fetched_at)+' · source '+esc(L.source)+'</div>':'');
};

function batTable(inn){return '<table class="simple sc"><thead><tr><th>Batter</th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr></thead><tbody>'+
 inn.batting.map(b=>'<tr><td><b>'+esc(b.name||"")+'</b><div class="muted dis">'+esc(b.dismissal||"")+'</div></td><td><b>'+(b.r??"—")+'</b></td><td>'+(b.b??"—")+'</td><td>'+(b.fours??"—")+'</td><td>'+(b.sixes??"—")+'</td><td>'+(b.sr??"—")+'</td></tr>').join("")+'</tbody></table>'}
function bowlTable(inn){return '<table class="simple sc"><thead><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Econ</th></tr></thead><tbody>'+
 inn.bowling.map(b=>'<tr><td><b>'+esc(b.name||"")+'</b>'+((b.wd||b.nb)?'<div class="muted dis">'+(b.wd?b.wd+" wd ":"")+(b.nb?b.nb+" nb":"")+'</div>':'')+'</td><td>'+esc(String(b.o??"—"))+'</td><td>'+(b.m??"—")+'</td><td>'+(b.r??"—")+'</td><td><b>'+(b.w??"—")+'</b></td><td>'+(b.eco??"—")+'</td></tr>').join("")+'</tbody></table>'}
const extrasTxt=e=>{if(!e)return "—";const k=["b","lb","w","nb","p"].filter(x=>e[x]!=null);const tot=e.total!=null?e.total:k.reduce((a,x)=>a+(+e[x]||0),0);return tot+(k.length?' ('+k.map(x=>x+" "+e[x]).join(", ")+')':'')};
const srcNote=pd=>'<p class="muted">Source: '+esc(pd.source)+' · '+esc(pd.rule)+'</p>'+(pd.notes&&pd.notes.length?'<p class="muted">Not available: '+pd.notes.map(esc).join(" · ")+'</p>':'');

const localTime=u=>{try{return new Date(u).toLocaleString(undefined,{weekday:"short",day:"numeric",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"})}catch(e){return u}};
function scoreOnly(m){const L=m.live_score;if(!L||!L.innings||!L.innings.length)return null;
 return '<div class="card"><h3>Score</h3>'+L.innings.map(i=>'<div class="row"><b class="grow">'+esc(teamShort(m,i.inning))+'</b><span class="mc-score">'+i.r+'-'+i.w+'</span> <span class="muted">('+esc(String(i.o))+' ov)</span></div>').join("")+
  (L.status_text?'<p><b>'+esc(L.status_text)+'</b></p>':'')+'<p class="muted">Score line from '+esc(L.source)+', updated '+ago(L.fetched_at)+'. Batter-by-batter detail appears when the full scorecard for this match is received.</p></div>'}
window.mcTab={
 live:async m=>{const pd=PD(m);if(!pd||m.status!=="live"&&!pd.featured){if((m.data_status||"").indexOf("ball_by_ball")<0&&m.live_score)return scoreOnly(m);return null}   // our own ball-by-ball keeps the original Live tab
  const li=lastInn(pd.scorecard),notOut=li.batting.filter(b=>/not out/i.test(b.dismissal||"")),cur=li.bowling.slice(-1);
  const pship=notOut.length===2&&li.total&&li.total.w===0?li.total.r:null;   // only certain when no wicket has fallen
  const balls=pd.balls||[],lastOv=balls.length?balls[balls.length-1].over:null,thisOv=balls.filter(b=>b.over===lastOv);
  return (thisOv.length?'<div class="card ov-strip"><b>Over '+(lastOv+1)+'</b> '+thisOv.map(ball).join("")+' <span class="muted">= '+thisOv.reduce((a,b)=>a+(b.runs||0),0)+'</span></div>':'')+
   '<div class="card"><h3>'+esc(teamShort(m,li.inning))+' batting</h3>'+batTable({batting:notOut.length?notOut:li.batting.slice(-2)})+(pship!=null?'<p class="muted">Partnership: '+pship+' (opening stand)</p>':'')+'</div>'+
   (cur.length?'<div class="card"><h3>Bowling</h3>'+bowlTable({bowling:cur})+'</div>':'')+srcNote(pd)},
 scorecard:async m=>{const pd=PD(m);if(!pd)return null;
  return pd.scorecard.map(i=>'<div class="card"><h3>'+esc(teamShort(m,i.inning)+(/inning \d+$/i.test(i.inning||"")?" · "+String(i.inning).match(/inning \d+$/i)[0].replace(/^i/,"I"):""))+(i.total?' <span class="muted">'+i.total.r+'-'+i.total.w+' ('+esc(String(i.total.o))+' ov)</span>':'')+'</h3>'+batTable(i)+
   '<dl class="kv"><dt>Extras</dt><dd>'+esc(extrasTxt(i.extras))+'</dd><dt>Total</dt><dd>'+(i.total?i.total.r+'-'+i.total.w+' ('+esc(String(i.total.o))+' ov)':'—')+'</dd></dl>'+(i.bowling.length?bowlTable(i):'')+'</div>').join("")+srcNote(pd)},
 xi:async m=>{const pd=m.provider_detail;if(!pd||!pd.squads||!pd.squads.length)return null;
  return '<div class="sq-grid">'+pd.squads.map(t=>'<div class="card"><h3>'+esc(t.team||"")+'</h3>'+t.players.map(p=>'<div class="sq-p"><span class="av">'+esc((p.name||"?").split(" ").map(x=>x[0]).join("").slice(0,2))+'</span><span><b>'+esc(p.name||"")+'</b><div class="muted">'+esc(p.role||"")+'</div></span></div>').join("")+'</div>').join("")+'</div>'+
   '<p class="muted">Squads from '+esc(pd.source)+(pd.squads_at?' · updated '+ago(pd.squads_at):'')+'. Final XI is confirmed at the toss.</p>'},
 graphs:async m=>{const pd=m.provider_detail;if(!pd||!pd.runs_per_over||!pd.runs_per_over.length||(m.data_status||"").indexOf("ball_by_ball")>=0)return null;
  setTimeout(()=>{const cv=document.getElementById("mh");if(!cv)return;const x=cv.getContext("2d"),d=pd.runs_per_over,max=Math.max(6,...d.map(v=>v.runs));x.clearRect(0,0,cv.width,cv.height);
   const w=cv.width/d.length;d.forEach((v,i)=>{const hh=(v.runs/max)*(cv.height-24);x.fillStyle=v.inning==="0"||v.inning==="1"?"#2d7ff9":"#ff8a1f";x.fillRect(i*w+3,cv.height-18-hh,w-6,hh);x.fillStyle="#9aa";x.font="10px sans-serif";x.fillText(String(v.over),i*w+w/2-4,cv.height-4)})},0);
  return '<div class="card"><h3>Manhattan (runs per over)</h3><canvas id="mh" width="700" height="220" style="width:100%;height:auto"></canvas><p class="muted">From the '+pd.runs_per_over.length+' overs the provider sent ball rows for. Overs without ball rows are not drawn.</p></div>'},
 h2h:async m=>{const H=m.history;if(!H)return null;
  const hw=H.head_to_head.filter(x=>x.side_won==="home").length,aw=H.head_to_head.filter(x=>x.side_won==="away").length;
  const form=(f,name)=>'<div class="row"><b class="grow">'+esc(name)+'</b>'+(f.length?f.map(x=>'<span class="fm f'+x+'">'+x+'</span>').join(""):'<span class="muted">no matches recorded</span>')+'</div>';
  return '<div class="card"><h3>Form (last 5)</h3>'+form(H.home_form,m.home.name)+form(H.away_form,m.away.name)+'</div>'+
   '<div class="card"><h3>Head to head</h3><div class="row"><b class="grow c-home">'+esc(m.home.name)+' won '+hw+'</b><span class="muted">'+H.head_to_head.length+' matches</span><b class="grow c-away" style="text-align:right">'+esc(m.away.name)+' won '+aw+'</b></div>'+
   (H.head_to_head.length?H.head_to_head.map(x=>'<div class="h2h-row"><div><b>'+esc(x.winner?x.winner+' won'+(x.margin?' by '+x.margin:''):x.result_type)+'</b><div class="muted">'+(x.innings.map(i=>esc(i.team)+' '+i.runs+'/'+i.wickets).join(" · ")||"scores not recorded")+'</div></div><div style="text-align:right"><div class="muted">'+esc(x.day)+'</div><a href="#/match/'+x.id+'/scorecard">View</a></div></div>').join(""):'<p class="muted">No earlier meetings in our database.</p>')+'</div><p class="muted">'+esc(H.note)+'</p>'}
};
function matchDetails(m){const info=(m.provider_detail&&m.provider_detail.info)||{};
 const toss=m.toss_winner_id?((m.toss_winner_id===m.home.id?m.home.name:m.away.name)+' won the toss'+(m.toss_decision?' and chose to '+(m.toss_decision==="bat"?"bat":"bowl"):'')):'Not yet';
 const res=m.result_type?(m.winner_team_id?((m.winner_team_id===m.home.id?m.home.name:m.away.name)+' won'+(m.margin?' by '+m.margin:'')):m.result_type.replace("_"," ")):null;
 const rows=[["Series",esc(m.competition)],["Match",esc(m.match_no||"—")],["Format",esc(m.format)],["Date & time",esc(localTime(m.start_utc))+' <span class="muted">(your time)</span>'],
  ["Venue",esc(m.venue||info.venue||"—")],["Toss",esc(toss)],["Status",esc((m.live_score&&m.live_score.status_text)||m.status)]];
 if(res)rows.push(["Result",'<b>'+esc(res)+'</b>']);
 rows.push(["Data",'<span class="tag ds-'+esc(m.data_status)+'">'+esc(m.data_status_label||"")+'</span>']);
 return '<div class="card"><h3>Match details</h3><dl class="kv">'+rows.map(([a,b])=>'<dt>'+esc(a)+'</dt><dd>'+b+'</dd>').join("")+'</dl></div>'}
function inningsList(m,sc){const pd=PD(m);if(pd)return pd.scorecard.filter(i=>i.total).map(i=>({team:teamShort(m,i.inning),r:i.total.r,w:i.total.w,o:i.total.o}));
 if(sc&&sc.innings&&sc.innings.length)return sc.innings.map(i=>({team:i.team||(i.batting_team_id===m.home.id?m.home.name:i.batting_team_id===m.away.id?m.away.name:""),r:i.runs,w:i.wickets,o:i.overs}));const L=m.live_score;
 return L&&L.innings?L.innings.map(i=>({team:teamShort(m,i.inning),r:i.r,w:i.w,o:i.o})):[]}
window.mcTab.history=async m=>{let sc=null;try{sc=await api("/matches/"+m.id+"/scorecard")}catch(e){}
 const I=inningsList(m,sc);if(!I.length)return '<div class="state">'+esc(t("data.na"))+'</div>';
 return '<div class="card"><h3>'+esc(t("mc.innings_progression"))+'</h3>'+I.map((x,i)=>'<div class="dl"><span><b>'+esc(x.team)+'</b> <span class="muted">innings '+(i+1)+'</span></span><span><b>'+x.r+'/'+x.w+'</b> <span class="muted">('+esc(String(x.o))+' ov · RR '+crr(x.r,x.o)+')</span></span></div>').join("")+'</div>'+
  '<div class="card"><h3>Day / session breakdown</h3><p class="muted">'+esc(t("data.na"))+'. Session splits need ball times, which the current sources do not send.</p></div>'};
window.mcTab.seriesstats=async m=>{if(!m.competition_id)return '<div class="state">'+esc(t("data.na"))+'</div>';
 const d=await api("/series/"+m.competition_id);
 return '<p><a class="btn" href="#/series/'+m.competition_id+'">'+esc(d.series.name)+' →</a></p>'+(d.points_table.length?'<div class="card"><h3>'+esc(t("series.points"))+'</h3><table class="simple pt"><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>L</th><th>NR</th><th>Pts</th><th>NRR</th></tr></thead><tbody>'+
  d.points_table.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.short_code||x.team)+'</b></td><td>'+x.played+'</td><td>'+x.won+'</td><td>'+x.lost+'</td><td>'+x.no_result+'</td><td><b>'+x.points+'</b></td><td>'+(x.nrr==null?"—":(x.nrr>0?"+":"")+x.nrr.toFixed(3))+'</td></tr>').join("")+'</tbody></table><p class="muted">'+esc(d.points_rule)+'</p></div>':'')+
  '<div class="dgrid"><div class="card"><h3>Most runs</h3>'+(d.top_batters.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.runs+'</span></div>').join("")||'<p class="muted">'+esc(t("data.na"))+'</p>')+'</div><div class="card"><h3>Most wickets</h3>'+(d.top_bowlers.map(x=>'<div class="dl"><b>'+esc(x.name)+'</b><span>'+x.wickets+'</span></div>').join("")||'<p class="muted">'+esc(t("data.na"))+'</p>')+'</div></div>'};
window.mcTab.commentary=async m=>{const j=await api("/matches/"+m.id+"/commentary?limit=100&lang="+encodeURIComponent(LANG));if(!j.items.length)return '<div class="state">'+esc(t("data.na"))+'</div>';
 const id="cm"+m.id;setTimeout(()=>{const box=document.getElementById(id);if(!box)return;let f="all";
  const draw=()=>{const items=j.items.filter(b=>f==="all"||f==="overs"||(f==="w"?b.is_wicket:f==="4"?b.runs_bat===4:f==="6"?b.runs_bat===6:f==="hl"?(b.is_wicket||b.runs_bat>=4):true));
   const byOver={};j.items.forEach(b=>{const k=b.innings_no+"-"+b.over_no;(byOver[k]=byOver[k]||{r:0,w:0,inn:b.innings_no,ov:b.over_no});byOver[k].r+=(b.runs_bat||0)+(b.extras||0);byOver[k].w+=b.is_wicket?1:0});
   let last=null,out="";
   if(f==="overs"){out=Object.values(byOver).map(o=>'<div class="cm-ov"><b>Over '+(o.ov+1)+'</b><span>'+o.r+' runs · '+o.w+' wkts</span></div>').join("")}
   else items.forEach(b=>{const k=b.innings_no+"-"+b.over_no;if(k!==last&&f==="all"){const o=byOver[k];out+='<div class="cm-ov"><b>End of over '+(b.over_no+1)+'</b><span>'+o.r+' runs · '+o.w+' wkts</span></div>';last=k}
    const r=(b.runs_bat||0)+(b.extras||0),lab=b.is_wicket?"W":String(r),cls=b.is_wicket?"bw":b.runs_bat===6?"b6":b.runs_bat===4?"b4":r?"b1":"b0";
    out+='<div class="cm-b"><b>'+b.over_no+'.'+b.ball_in_over+'</b><span class="bl '+cls+'">'+esc(lab)+'</span><span>'+esc(b.generated_commentary||"")+'</span></div>'});
   box.querySelector(".cm-list").innerHTML=out||'<p class="muted">—</p>';box.querySelectorAll("[data-cf]").forEach(x=>x.classList.toggle("on",x.dataset.cf===f))};
  box.querySelectorAll("[data-cf]").forEach(x=>x.onclick=()=>{f=x.dataset.cf;draw()});draw()},0);
 return '<div id="'+id+'"><div class="chips">'+[["all","home.all"],["hl","mc.highlights"],["overs","mc.overs"],["w","W"],["4","4s"],["6","6s"]].map(([k,l])=>'<button data-cf="'+k+'">'+esc(l.indexOf(".")>0?t(l):l)+'</button>').join("")+'</div><div class="card cm-list"></div>'+
  (j.language_note?'<p class="muted">'+esc(j.language_note)+'</p>':'')+'<p class="muted">'+esc(j.note||"")+'</p></div>'};
window.mcTab.info=async m=>matchDetails(m)+'<p class="muted">Source: '+esc(m.source)+'</p>'+(m.attribution?'<p class="muted">'+esc(m.attribution.text)+' · <a href="'+esc(m.attribution.url)+'" rel="noopener" target="_blank">licence</a></p>':'');
window.mcTabAfter={
 info:m=>(function(){const v=m.history&&m.history.venue;if(!v)return "";
  return '<div class="card"><h3>Venue stats · '+esc(v.name)+'</h3>'+(v.matches?'<dl class="kv"><dt>Matches</dt><dd>'+v.matches+'</dd><dt>Avg 1st innings</dt><dd>'+v.avg_first_innings+'</dd><dt>Avg 2nd innings</dt><dd>'+v.avg_second_innings+'</dd>'+
   '<dt>Won batting first</dt><dd>'+v.bat_first_win_pct+'%</dd><dt>Won chasing</dt><dd>'+v.chase_win_pct+'%</dd>'+(v.highest?'<dt>Highest total</dt><dd>'+v.highest.runs+'-'+v.highest.wickets+' ('+v.highest.overs+' ov) by '+esc(v.highest.team)+'</dd>':'')+
   (v.lowest_all_out?'<dt>Lowest all out</dt><dd>'+v.lowest_all_out.runs+' ('+v.lowest_all_out.overs+' ov) by '+esc(v.lowest_all_out.team)+'</dd>':'')+'</dl>':'<p class="muted">No completed '+esc(m.format)+' matches at this venue in our database yet.</p>')+'<p class="muted">'+esc(m.history.note)+'</p></div>'})()
};
})();
