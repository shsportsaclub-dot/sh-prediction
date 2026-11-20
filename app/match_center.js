/* SH Match Center: live score header and data-driven tabs (Live, Scorecard, Squads, Graphs, H2H, Info).
   Uses, in this order: our own ball-by-ball (SH scoring / Cricsheet) -> provider scorecard (CricketData) -> score line only.
   Nothing is filled in when a source has no figure: the tab says what is missing and why. Our own layout and colours. */
"use strict";
(function(){
const later=window.mcLater||(window.mcLater=fn=>(window._mcq=window._mcq||[]).push(fn));
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

/* SH score board (owner's design): title + status, two team badges, score in the centre plate, run-rate row */
const FLAGS={"india":"🇮🇳","australia":"🇦🇺","england":"🏴\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}","new zealand":"🇳🇿","south africa":"🇿🇦","pakistan":"🇵🇰",
 "sri lanka":"🇱🇰","bangladesh":"🇧🇩","afghanistan":"🇦🇫","ireland":"🇮🇪","zimbabwe":"🇿🇼","netherlands":"🇳🇱","scotland":"🏴\u{E0067}\u{E0062}\u{E0073}\u{E0063}\u{E0074}\u{E007F}",
 "nepal":"🇳🇵","united arab emirates":"🇦🇪","uae":"🇦🇪","oman":"🇴🇲","united states of america":"🇺🇸","usa":"🇺🇸","united states":"🇺🇸","canada":"🇨🇦","namibia":"🇳🇦",
 "kenya":"🇰🇪","uganda":"🇺🇬","rwanda":"🇷🇼","papua new guinea":"🇵🇬","hong kong":"🇭🇰","singapore":"🇸🇬","malaysia":"🇲🇾","thailand":"🇹🇭","japan":"🇯🇵",
 "italy":"🇮🇹","germany":"🇩🇪","jersey":"🇯🇪","guernsey":"🇬🇬","sweden":"🇸🇪","switzerland":"🇨🇭","türkiye":"🇹🇷","turkey":"🇹🇷","denmark":"🇩🇰","bahrain":"🇧🇭",
 "qatar":"🇶🇦","kuwait":"🇰🇼","saudi arabia":"🇸🇦","nigeria":"🇳🇬","tanzania":"🇹🇿","botswana":"🇧🇼","argentina":"🇦🇷","brazil":"🇧🇷","mexico":"🇲🇽",
 "france":"🇫🇷","spain":"🇪🇸","portugal":"🇵🇹","austria":"🇦🇹","belgium":"🇧🇪","norway":"🇳🇴","finland":"🇫🇮","china":"🇨🇳","indonesia":"🇮🇩","philippines":"🇵🇭",
 "maldives":"🇲🇻","bhutan":"🇧🇹","myanmar":"🇲🇲","cambodia":"🇰🇭","mongolia":"🇲🇳","fiji":"🇫🇯","samoa":"🇼🇸","vanuatu":"🇻🇺","cook islands":"🇨🇰","sierra leone":"🇸🇱",
 "ghana":"🇬🇭","cameroon":"🇨🇲","mozambique":"🇲🇿","malawi":"🇲🇼","eswatini":"🇸🇿","lesotho":"🇱🇸","gibraltar":"🇬🇮","isle of man":"🇮🇲","cyprus":"🇨🇾","greece":"🇬🇷",
 "czech republic":"🇨🇿","hungary":"🇭🇺","romania":"🇷🇴","bulgaria":"🇧🇬","serbia":"🇷🇸","croatia":"🇭🇷","slovenia":"🇸🇮","estonia":"🇪🇪","luxembourg":"🇱🇺","malta":"🇲🇹","israel":"🇮🇱",
 "iran":"🇮🇷","bermuda":"🇧🇲","cayman islands":"🇰🇾","bahamas":"🇧🇸","belize":"🇧🇿","costa rica":"🇨🇷","panama":"🇵🇦","peru":"🇵🇪","chile":"🇨🇱","colombia":"🇨🇴","south korea":"🇰🇷"};
/* SH Team Ball Badge: the owner's approved PNG when one is in /badges, otherwise a generated SH ball (team colour leather, gold seam,
   gold short name). Original SH artwork only; never an official team logo. */
const BALL_COL={"india":"#1f4fbf","australia":"#d9a400","england":"#1d3a8a","new zealand":"#1b1b1b","south africa":"#007a4d","pakistan":"#0b6b3a",
 "sri lanka":"#1d3fa8","bangladesh":"#006a4e","west indies":"#7b1e3a","afghanistan":"#1d4fa8","ireland":"#169b62","zimbabwe":"#c40000","netherlands":"#ff6f00",
 "scotland":"#1d3fa8","nepal":"#c8102e","united arab emirates":"#00732f","uae":"#00732f","sweden":"#006aa7","switzerland":"#c8102e","türkiye":"#d50a17","turkey":"#d50a17",
 "oman":"#c8102e","usa":"#1d3a8a","canada":"#c8102e","namibia":"#003580","uganda":"#1b1b1b","kenya":"#006600","rwanda":"#00a1de","italy":"#0066cc"};
window.BADGES=window.BADGES||new Set();fetch("/badges/manifest.json").then(r=>r.json()).then(j=>(j.badges||[]).forEach(x=>BADGES.add(x))).catch(()=>{});
const slug=n=>String(n||"").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
window.ballBadge=function(team,size){size=size||52;const s=slug(team.name);
 if(BADGES.has(s+".png")||BADGES.has(s+".webp"))return '<img class="bbadge" src="/badges/'+(BADGES.has(s+".png")?s+".png":s+".webp")+'" width="'+size+'" height="'+size+'" alt="">';
 const base=String(team.name||"").toLowerCase().replace(/\s+(women|men|u-?19|u-?23)$/,"").trim();
 let h=0;for(const ch of String(team.name||""))h=(h*31+ch.charCodeAt(0))%360;
 const col=BALL_COL[base]||"hsl("+h+" 62% 34%)",code=shortName(team).replace(/-W$/,""),fs=code.length<=2?34:code.length===3?28:22,id="g"+s.slice(0,20)+size;
 return '<svg class="bbadge" width="'+size+'" height="'+size+'" viewBox="0 0 100 100" aria-hidden="true"><defs><radialGradient id="'+id+'" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".35" stop-color="'+col+'"/><stop offset="1" stop-color="#000" stop-opacity=".9"/></radialGradient></defs>'+
  '<circle cx="50" cy="50" r="47" fill="'+col+'"/><circle cx="50" cy="50" r="47" fill="url(#'+id+')"/>'+
  '<path d="M30 6 C14 30 14 70 30 94" fill="none" stroke="#e9c46a" stroke-width="2.4"/><path d="M38 4 C22 30 22 70 38 96" fill="none" stroke="#e9c46a" stroke-width="2.4"/>'+
  '<path d="M34 5 C18 30 18 70 34 95" fill="none" stroke="#f4d58d" stroke-width="5" stroke-dasharray="1.6 3.2"/>'+
  '<text x="60" y="'+(52+fs/3)+'" text-anchor="middle" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="'+fs+'" fill="#f6d77a" stroke="#5a3b00" stroke-width="1.2" paint-order="stroke">'+esc(code)+'</text>'+
  '<ellipse cx="38" cy="24" rx="16" ry="8" fill="#fff" opacity=".18"/></svg>'};
function badge(team){return '<span class="fl ball">'+ballBadge(team,54)+'</span>'}
/* short names: approved code, else the usual cricket code for a country, else initials (UAE Bulls -> UB) */
const CODES={"india":"IND","australia":"AUS","england":"ENG","new zealand":"NZ","south africa":"SA","pakistan":"PAK","sri lanka":"SL","bangladesh":"BAN",
 "west indies":"WI","afghanistan":"AFG","ireland":"IRE","zimbabwe":"ZIM","netherlands":"NED","scotland":"SCO","nepal":"NEP","united arab emirates":"UAE","uae":"UAE",
 "oman":"OMA","united states of america":"USA","usa":"USA","united states":"USA","canada":"CAN","namibia":"NAM","kenya":"KEN","uganda":"UGA","rwanda":"RWA",
 "papua new guinea":"PNG","hong kong":"HK","singapore":"SIN","malaysia":"MAL","thailand":"THA","japan":"JPN","italy":"ITA","germany":"GER","jersey":"JER",
 "sweden":"SWE","switzerland":"SUI","türkiye":"TUR","turkey":"TUR","denmark":"DEN","bahrain":"BHR","qatar":"QAT","kuwait":"KUW","saudi arabia":"KSA","nigeria":"NGA","tanzania":"TAN"};
window.shortName=function(team){if(team.short_code)return team.short_code;const n=String(team.name||"").trim(),w=/\bwomen\b/i.test(n);
 const base=n.toLowerCase().replace(/\s+(women|men|u-?19|u-?23)$/,"").trim();if(CODES[base])return CODES[base]+(w?"-W":"");
 const words=base.split(/\s+/).filter(x=>x&&!/^(women|men|cricket|club|team|xi)$/.test(x));
 const s=words.length>1?words.map(x=>x[0]).join("").slice(0,4):(words[0]||n).slice(0,3);return s.toUpperCase()+(w?"-W":"")};
window.mcBoard=function(m){const pd=PD(m),L=m.live_score;let lines=[],cr="",ev="";
 // score source order: live score line, then the provider scorecard totals (or totals worked out from the batting card), then user-reported scores
 if(L&&L.innings&&L.innings.length)L.innings.forEach(i=>lines.push({t:teamShort(m,i.inning),r:i.r,w:i.w,o:i.o}));
 if(!lines.length&&pd)pd.scorecard.forEach(i=>{let T=i.total;if(!T||T.r==null){const bat=i.batting||[];if(!bat.length)return;
   T={r:bat.reduce((a,b)=>a+(+b.r||0),0)+((i.extras&&+i.extras.total)||0),w:bat.filter(b=>b.dismissal&&!/not out|batting/i.test(b.dismissal)).length,
      o:(n=>Math.floor(n/6)+"."+(n%6))((i.bowling||[]).reduce((a,b)=>a+oversToBalls(b.o),0))}}
  lines.push({t:teamShort(m,i.inning),r:T.r,w:T.w,o:T.o})});
 if(!lines.length&&m.reported_scores&&m.reported_scores.length)m.reported_scores.forEach(s=>lines.push({t:s.team,r:s.runs,w:s.wickets,o:s.overs||"—",rep:1}));
 if(lines.length){const li=lines[lines.length-1];cr=crr(li.r,li.o)}
 if(pd){const lb=(pd.balls||[]).slice(-1)[0];if(lb&&m.status==="live")ev=lb.wicket?"WICKET":lb.runs===6?"SIX":lb.runs===4?"FOUR":""}
 const sn=shortName,full=x=>x.name;
 const toss=m.toss_winner_id?full(m.toss_winner_id===m.home.id?m.home:m.away)+" opt to "+(m.toss_decision||"—"):"";
 const res=m.result_type?(m.winner_team_id?((m.winner_team_id===m.home.id?m.home.name:m.away.name)+" won"+(m.margin?" by "+m.margin:"")):m.result_type.replace(/_/g," ")):"";
 const status=res||[(L&&L.status_text)||"",toss&&!(L&&L.status_text&&/opt/i.test(L.status_text))?toss:""].filter(Boolean).join(" - ")||(m.status==="scheduled"?new Date(m.start_utc).toLocaleString(undefined,{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}):"");
 const cur=lines[lines.length-1];
 const quota={T10:60,T20:120,"The Hundred":100,ODI:300,"List A":300}[m.format];const cells=[];
 if(cr)cells.push(["CRR",cr]);
 if(lines.length>=2&&quota){const tgt=lines[0].r+1,used=oversToBalls(lines[1].o),need=tgt-lines[1].r,left=quota-used;if(m.status==="live"&&need>0&&left>0){cells.push(["RRR",(need*6/left).toFixed(2)]);cells.push([t("mc.target"),tgt])}}
 let lead="";if(!quota&&lines.length>=2){const tot={};lines.forEach(x=>tot[x.t]=(tot[x.t]||0)+x.r);const c2=cur.t,o2=Object.keys(tot).find(k=>k!==c2);if(o2!=null){const d=tot[c2]-tot[o2];lead=c2+" "+t(d>=0?"mc.lead_by":"mc.trail_by")+" "+Math.abs(d)}}
 // title once: the full match + series name, exactly as the series lists it
 const title=m.home.name+" vs "+m.away.name+(m.match_no?", "+(/^\d+$/.test(m.match_no)?"Match "+m.match_no:m.match_no):"")+", "+m.competition;
 return '<div class="board" aria-live="polite"><div class="bt"><span>'+esc(title)+'</span></div>'+
  '<div class="bm"><div class="tm">'+badge(m.home)+'<span>'+esc(sn(m.home))+'</span></div><div class="sc">'+
  (cur?'<b>'+cur.r+'-'+cur.w+'</b><small>('+esc(String(cur.o))+')</small>':'<b>vs</b>')+(ev?'<div><span class="ev ev-'+ev.toLowerCase()+'">'+ev+'</span></div>':'')+
  '</div><div class="tm">'+badge(m.away)+'<span>'+esc(sn(m.away))+'</span></div></div>'+
  '<div class="bb"><i></i>'+(cells.length?cells.map(([a,b])=>'<span>'+esc(a)+' <b>'+esc(String(b))+'</b></span>').join(""):'<span>'+esc(m.format)+'</span>')+'<i></i></div>'+
  (lead||lines.length>1?'<div class="bl2">'+[lead].concat(lines.slice(0,-1).map(x=>esc(x.t)+" "+x.r+"-"+x.w+" ("+esc(String(x.o))+")")).filter(Boolean).join(" · ")+'</div>':'')+
  (status?'<div class="bst">'+esc(status)+'</div>':'')+'</div>'+
  '<div class="mc-meta"><span class="tag ds-'+esc(m.data_status)+'">'+esc(m.data_status_label||"")+'</span> '+(cur&&cur.rep?'USER_REPORTED · ':'')+(pd&&pd.scorecard_at?esc("Updated "+ago(pd.scorecard_at)+" · "+pd.source):L?esc("Updated "+ago(L.fetched_at)+" · "+L.source):"")+'</div>'};
/* ball-by-ball strip under the board: every received ball, newest at the right, scrolled into view */
window.mcBalls=function(m){const pd=PD(m);const B=(pd&&pd.balls)||[];if(!B.length)return "";
 const byOv=[];B.forEach(b=>{const k=b.inning+"|"+b.over;let o=byOv[byOv.length-1];if(!o||o.k!==k){o={k,over:b.over,balls:[]};byOv.push(o)}o.balls.push(b)});
 const chipOf=b=>{const x=String(b.extra||"").toLowerCase();const v=b.wicket?"W":(x==="wd"||x==="wide"?"wd":x==="nb"||x==="noball"?"nb":(x==="lb"||x==="legbyes")?(b.runs||0)+"lb":(x==="b"||x==="byes")?(b.runs||0)+"b":String(b.runs||0));
  const cls=b.wicket?"bw":b.runs>=6&&!x?"b6":b.runs===4&&!x?"b4":(b.runs||0)>0?"b1":"b0";return '<span class="bl '+cls+'">'+esc(v)+'</span>'};
 const id="bs"+m.id;setTimeout(()=>{const s=document.getElementById(id);if(s)s.scrollLeft=s.scrollWidth},50);
 return '<div class="balls" id="'+id+'" aria-label="Ball by ball">'+byOv.slice(-12).map(o=>'<span class="ov"><small>Ov '+(o.over+1)+'</small>'+o.balls.map(chipOf).join("")+'<em>= '+o.balls.reduce((a,b)=>a+(b.runs||0),0)+'</em></span>').join("")+'</div>'};

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
  return (thisOv.length&&m.status!=="live"?'<div class="card ov-strip"><b>Over '+(lastOv+1)+'</b> '+thisOv.map(ball).join("")+' <span class="muted">= '+thisOv.reduce((a,b)=>a+(b.runs||0),0)+'</span></div>':'')+
   '<div class="card"><h3>'+esc(teamShort(m,li.inning))+' batting</h3>'+batTable({batting:notOut.length?notOut:li.batting.slice(-2)})+(pship!=null?'<p class="muted">Partnership: '+pship+' (opening stand)</p>':'')+'</div>'+
   (cur.length?'<div class="card"><h3>Bowling</h3>'+bowlTable({bowling:cur})+'</div>':'')+srcNote(pd)},
 scorecard:async m=>{const pd=PD(m);if(!pd)return null;
  return pd.scorecard.map(i=>'<div class="card"><h3>'+esc(teamShort(m,i.inning)+(/inning \d+$/i.test(i.inning||"")?" · "+String(i.inning).match(/inning \d+$/i)[0].replace(/^i/,"I"):""))+(i.total?' <span class="muted">'+i.total.r+'-'+i.total.w+' ('+esc(String(i.total.o))+' ov)</span>':'')+'</h3>'+batTable(i)+
   '<dl class="kv"><dt>Extras</dt><dd>'+esc(extrasTxt(i.extras))+'</dd><dt>Total</dt><dd>'+(i.total?i.total.r+'-'+i.total.w+' ('+esc(String(i.total.o))+' ov)':'—')+'</dd></dl>'+(i.bowling.length?bowlTable(i):'')+'</div>').join("")+srcNote(pd)},
 xi:async m=>{const pd=m.provider_detail;if(!pd||!pd.squads||!pd.squads.length)return null;
  return '<div class="sq-grid">'+pd.squads.map(t=>'<div class="card"><h3>'+esc(t.team||"")+'</h3>'+t.players.map(p=>'<div class="sq-p"><span class="av">'+esc((p.name||"?").split(" ").map(x=>x[0]).join("").slice(0,2))+'</span><span><b>'+esc(p.name||"")+'</b><div class="muted">'+esc(p.role||"")+'</div></span></div>').join("")+'</div>').join("")+'</div>'+
   '<p class="muted">Squads from '+esc(pd.source)+(pd.squads_at?' · updated '+ago(pd.squads_at):'')+'. Final XI is confirmed at the toss.</p>'},
 graphs:async m=>{const pd=m.provider_detail;if(!pd||!pd.runs_per_over||!pd.runs_per_over.length||(m.data_status||"").indexOf("ball_by_ball")>=0)return null;
  later(()=>{const cv=document.getElementById("mh");if(!cv)return;const x=cv.getContext("2d"),d=pd.runs_per_over,max=Math.max(6,...d.map(v=>v.runs));x.clearRect(0,0,cv.width,cv.height);
   const w=cv.width/d.length;d.forEach((v,i)=>{const hh=(v.runs/max)*(cv.height-24);x.fillStyle=v.inning==="0"||v.inning==="1"?"#2d7ff9":"#ff8a1f";x.fillRect(i*w+3,cv.height-18-hh,w-6,hh);x.fillStyle="#9aa";x.font="10px sans-serif";x.fillText(String(v.over),i*w+w/2-4,cv.height-4)})});
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
 const id="cm"+m.id;later(()=>{const box=document.getElementById(id);if(!box)return;let f="all";
  const draw=()=>{const items=j.items.filter(b=>f==="all"||f==="overs"||(f==="w"?b.is_wicket:f==="4"?b.runs_bat===4:f==="6"?b.runs_bat===6:f==="hl"?(b.is_wicket||b.runs_bat>=4):true));
   const byOver={};j.items.forEach(b=>{const k=b.innings_no+"-"+b.over_no;(byOver[k]=byOver[k]||{r:0,w:0,inn:b.innings_no,ov:b.over_no});byOver[k].r+=(b.runs_bat||0)+(b.extras||0);byOver[k].w+=b.is_wicket?1:0});
   let last=null,out="";
   if(f==="overs"){out=Object.values(byOver).map(o=>'<div class="cm-ov"><b>Over '+(o.ov+1)+'</b><span>'+o.r+' runs · '+o.w+' wkts</span></div>').join("")}
   else items.forEach(b=>{const k=b.innings_no+"-"+b.over_no;if(k!==last&&f==="all"){const o=byOver[k];out+='<div class="cm-ov"><b>End of over '+(b.over_no+1)+'</b><span>'+o.r+' runs · '+o.w+' wkts</span></div>';last=k}
    const r=(b.runs_bat||0)+(b.extras||0),lab=b.is_wicket?"W":String(r),cls=b.is_wicket?"bw":b.runs_bat===6?"b6":b.runs_bat===4?"b4":r?"b1":"b0";
    out+='<div class="cm-b"><b>'+b.over_no+'.'+b.ball_in_over+'</b><span class="bl '+cls+'">'+esc(lab)+'</span><span>'+esc(b.generated_commentary||"")+'</span></div>'});
   box.querySelector(".cm-list").innerHTML=out||'<p class="muted">—</p>';box.querySelectorAll("[data-cf]").forEach(x=>x.classList.toggle("on",x.dataset.cf===f))};
  box.querySelectorAll("[data-cf]").forEach(x=>x.onclick=()=>{f=x.dataset.cf;draw()});draw()});
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

/* Board flash: each ball event shows its own animation on the score plate for ~2.5 s, then the score returns.
   Every event type has a different look and movement (SH originals). */
window.mcFlash=function(ev){const box=document.querySelector(".board .sc")||document.querySelector(".board");if(!box||!ev)return;
 const x=String(ev.extra||"").toLowerCase(),r=+ev.runs||0;let k,txt,sub="";
 if(ev.wicket){k="wkt";txt="WICKET";sub=ev.batter?String(ev.batter):""}
 else if(/^(wd|wide)/.test(x)){k="xtra";txt="WIDE"}else if(/^(nb|no_?ball)/.test(x)){k="xtra";txt="NO BALL"}
 else if(/^(lb|leg_?bye|legbyes)/.test(x)){k="xtra";txt=r>1?r+" LEG BYES":"LEG BYE"}else if(/^(b|bye|byes)$/.test(x)){k="xtra";txt=r>1?r+" BYES":"BYE"}
 else if(r>=6){k="six";txt="SIX"}else if(r===4){k="four";txt="FOUR"}else if(r>0){k="run";txt=r===1?"SINGLE":r+" RUNS"}else{k="dot";txt="DOT BALL"}
 let fx=box.querySelector(".fx");if(fx)fx.remove();fx=document.createElement("div");fx.className="fx fx-"+k;fx.setAttribute("role","status");
 const stumps='<svg class="fx-stumps" viewBox="0 0 60 60"><rect x="14" y="18" width="4" height="40" rx="1" fill="#f5e6c8"/><rect x="28" y="18" width="4" height="40" rx="1" fill="#f5e6c8"/><rect x="42" y="18" width="4" height="40" rx="1" fill="#f5e6c8"/><rect class="bail b1" x="14" y="14" width="16" height="3" rx="1.5" fill="#ffd23f"/><rect class="bail b2" x="30" y="14" width="16" height="3" rx="1.5" fill="#ffd23f"/></svg>';
 const run=k==="run"?'<div class="fx-pitch"><i class="c1"></i><b class="fx-ballrun" style="--n:'+Math.min(r,3)+'"></b><i class="c2"></i></div>':"";
 fx.innerHTML=(k==="six"?'<div class="fx-rays"></div>':"")+(k==="four"?'<div class="fx-sweep"></div>':"")+(k==="wkt"?stumps:"")+(k==="dot"?'<div class="fx-ring"></div>':"")+
  '<div class="fx-t">'+esc(txt)+'</div>'+(sub?'<div class="fx-s">'+esc(sub)+'</div>':"")+run;
 box.appendChild(fx);box.classList.remove("shake");if(k==="wkt"){void box.offsetWidth;box.classList.add("shake")}
 setTimeout(()=>{fx.classList.add("out");setTimeout(()=>fx.remove(),400)},2500)};

/* player photos: any element with data-ph="<player name>" gets a free-licence photo (Wikimedia Commons) when one exists;
   otherwise the initials stay. Author and licence are in the tooltip. */
(function(){const cache={},pending=new Set();let tm=null;
 const apply=root=>(root||document).querySelectorAll("[data-ph]").forEach(el=>{const p=cache[el.dataset.ph];if(p&&p.url&&!el.dataset.done){el.dataset.done=1;
  el.style.backgroundImage="url('"+p.url.replace(/'/g,"%27")+"')";el.classList.add("has-ph");el.title=el.dataset.ph+" — photo: "+p.author+", "+p.license+" ("+p.source+")"}});
 const run=()=>{const need=[...document.querySelectorAll("[data-ph]")].map(e=>e.dataset.ph).filter(n=>!(n in cache)&&!pending.has(n));
  const names=[...new Set(need)].slice(0,12);if(!names.length){apply();return}names.forEach(n=>pending.add(n));
  api("/players/photos?names="+encodeURIComponent(names.join("|"))).then(d=>{names.forEach(n=>{cache[n]=(d.photos||{})[n]||null;pending.delete(n)});apply();if(need.length>names.length)setTimeout(run,800)})
   .catch(()=>names.forEach(n=>pending.delete(n)))};
 new MutationObserver(()=>{clearTimeout(tm);tm=setTimeout(run,400)}).observe(document.getElementById("main")||document.body,{childList:true,subtree:true});
 window.phAvatar=(name,cls)=>'<span class="ph '+(cls||"")+'" data-ph="'+esc(name||"")+'">'+esc(String(name||"?").split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase())+'</span>';})();
