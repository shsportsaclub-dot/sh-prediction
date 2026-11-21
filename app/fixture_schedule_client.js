/* SH schedule controls: DOM text only, source facts only, viewer-local dates. */
(function(){
'use strict';
const V=SHFixtureView,$=id=>document.getElementById(id);
const labels={all:'All matches',live:'Live',upcoming:'Upcoming',results:'Results'};
const sports={S001:'Cricket',S002:'Football',S003:'Field Hockey',S004:'Kabaddi',S005:'Badminton',S006:'Volleyball',S007:'Basketball',S008:'Baseball',S009:'Rugby'};
let snapshot,state,fetchFailed=false;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function fromUrl(){const q=new URLSearchParams(location.search),d=q.get('date')||'all';return {view:Object.hasOwn(labels,q.get('view'))?q.get('view'):'upcoming',date:['all','today','tomorrow','week','unknown'].includes(d)||V.validDay(d)?d:'all',sport:q.get('sport')||'',competition:q.get('competition')||'',format:q.get('format')||'',q:q.get('q')||''}}
function update(values,replace=false){state={...state,...values};const q=new URLSearchParams();for(const k of ['view','date','sport','competition','format','q'])if(state[k]&&state[k]!==({view:'upcoming',date:'all'}[k]))q.set(k,state[k]);const url=location.pathname+(q.size?'?'+q:'');history[replace?'replaceState':'pushState'](null,'',url);render()}
function dateLabel(day){if(!day)return 'Start date not provided';return new Date(day+'T12:00:00Z').toLocaleDateString(undefined,{timeZone:'UTC',weekday:'short',month:'short',day:'numeric',year:'numeric'})}
function options(id,entries,first,selected){const select=$(id);select.replaceChildren();for(const [value,label] of [['',first],...entries]){const o=node('option',label);o.value=value;select.append(o)}if(selected&&![...select.options].some(o=>o.value===selected)){const o=node('option','Unavailable selection');o.value=selected;select.append(o)}select.value=selected||''}
function showDetails(item){
 $('detail-title').textContent=item.home_team+' vs '+item.away_team;
 const body=$('detail-body');body.replaceChildren();const dl=document.createElement('dl');
 for(const [key,value] of [['Sport',sports[item.sport_id]||item.sport_id],['Competition',item.competition],['Start',item.start_time_utc?SHTime.format(item.start_time_utc):'Not provided'],['Status',V.bucket(item)==='live'?item.status:(item.status==='live'?'Live state not verified':item.status)],['Format',item.format||'Not provided'],['Venue',item.venue||'Not provided'],['Source','OpenLigaDB via SH DATA LINE']]){dl.append(node('dt',key),node('dd',value))}
 body.append(dl,node('p','Scorecard, squads and live commentary are not supplied by this fixture source.','notice'));
 $('details').showModal();
}
function render(){
 if(!snapshot)return;
 const rows=snapshot.items||[],zone=SHTime.timezone;
 options('sport',[...new Set(rows.map(r=>r.sport_id))].map(id=>[id,sports[id]||id]),'All sports',state.sport);
 const scoped=rows.filter(r=>!state.sport||r.sport_id===state.sport);
 options('competition',[...new Map(scoped.map(r=>[r.competition_id||r.competition,r.competition])).entries()],'All competitions',state.competition);
 options('format',[...new Set(scoped.map(r=>r.format||'__unknown__'))].map(f=>[f,f==='__unknown__'?'Not provided':f]),'All formats',state.format);
 $('search').value=state.q;
 $('date').value=V.validDay(state.date)?state.date:'';
 const base=V.filter(rows,{...state,view:'all'},zone),counts=V.counts(base);
 for(const view of Object.keys(labels)){
  let button=document.getElementById('view-'+view);
  if(!button){button=node('button');button.id='view-'+view;button.type='button';button.setAttribute('role','tab');button.setAttribute('aria-controls','cards');button.onclick=()=>update({view});
   button.onkeydown=event=>{const keys=Object.keys(labels),i=keys.indexOf(view);let next;if(event.key==='ArrowRight')next=keys[(i+1)%keys.length];if(event.key==='ArrowLeft')next=keys[(i+keys.length-1)%keys.length];if(event.key==='Home')next=keys[0];if(event.key==='End')next=keys.at(-1);if(next){event.preventDefault();update({view:next});document.getElementById('view-'+next).focus()}};$('views').append(button)}
  button.textContent=labels[view]+' ('+counts[view]+')';button.setAttribute('aria-selected',String(state.view===view));button.tabIndex=state.view===view?0:-1;
 }
 $('cards').setAttribute('aria-labelledby','view-'+state.view);
 $('quick').replaceChildren();
 for(const [date,label] of [['all','All dates'],['today','Today'],['tomorrow','Tomorrow'],['week','Next 7 days']]){const button=node('button',label);button.setAttribute('aria-pressed',String(state.date===date));button.onclick=()=>update({date});$('quick').append(button)}
 const available=V.groups(V.filter(rows,{...state,date:'all'},zone),zone);
 $('days').replaceChildren();
 for(const group of available){const date=group.day||'unknown',button=node('button',dateLabel(group.day));button.setAttribute('aria-pressed',String(state.date===date));button.onclick=()=>update({date});$('days').append(button)}
 const items=V.filter(rows,state,zone);
 $('summary').textContent=items.length+' '+(items.length===1?'match':'matches')+' · '+labels[state.view]+((snapshot.stale||fetchFailed)?' · STALE: cached observations':'');
 $('zone-label').textContent='Times in '+(zone||'device time zone');
 $('cards').replaceChildren();
 for(const group of V.groups(items,zone)){
  const section=node('section',undefined,'day');section.append(node('h2',dateLabel(group.day)));
  for(const competition of group.competitions){const block=node('section',undefined,'competition');block.append(node('h3',competition.name));
   for(const item of competition.items){const row=node('article',undefined,'match'),left=document.createElement('div'),right=node('div',undefined,'right');left.append(node('h4',item.home_team+' vs '+item.away_team),node('div',(sports[item.sport_id]||item.sport_id)+' · '+(item.format||'Format not provided'),'meta'));
    const time=document.createElement('div');time.append(node('time',item.start_time_utc?SHTime.format(item.start_time_utc):'Start time unknown'),node('span',item.status==='live'&&V.bucket(item)!=='live'?'Live state not verified':item.status,'status'));
    const info=node('button','Match info');info.setAttribute('aria-label','Match info: '+item.home_team+' vs '+item.away_team);info.onclick=()=>showDetails(item);right.append(time,info);row.append(left,right);block.append(row)}section.append(block)}$('cards').append(section)
 }
 if(!items.length){const empty=node('div',undefined,'empty');empty.append(node('h2','No matches in this view'),node('p',state.view==='live'?'No verified live matches in the current source coverage.':'Try another date or reset filters. Available source coverage remains limited to one matchday.'));const reset=node('button','Show upcoming matches');reset.onclick=()=>update({view:'upcoming',date:'all',sport:'',competition:'',format:'',q:''});empty.append(reset);$('cards').append(empty)}
 $('freshness').textContent='Last SH receipt: '+(snapshot.last_received_at?SHTime.format(snapshot.last_received_at):'Not received')+'. Source check: '+(snapshot.collection?.last_ok?SHTime.format(new Date(snapshot.collection.last_ok*1000).toISOString()):'Unknown')+'.'+(snapshot.last_error?' Sync error: '+snapshot.last_error:'')+(snapshot.upstream_error?' Source collection error: '+snapshot.upstream_error:'');
}
async function refresh(){try{const response=await fetch('/api/provider-fixtures',{cache:'no-store'});if(!response.ok)throw Error('unavailable');const next=await response.json();if(!Array.isArray(next.items))throw Error('invalid snapshot');snapshot=next;fetchFailed=false;render()}catch(e){fetchFailed=true;if(snapshot)render();else $('summary').textContent='Schedule unavailable. Please try again shortly.'}}
async function start(){state=fromUrl();await SHTime.ready;
 const available=typeof Intl.supportedValuesOf==='function'?Intl.supportedValuesOf('timeZone'):['Asia/Kolkata','America/New_York'];
 for(const zone of new Set(['UTC',SHTime.selected,...available].filter(Boolean))){const o=node('option',zone);o.value=zone;$('zone').append(o)}$('zone').value=SHTime.selected||'';
 $('zone').onchange=()=>{SHTime.select($('zone').value);render()};
 for(const id of ['sport','competition','format'])$(id).onchange=()=>update({[id]:$(id).value,...(id==='sport'?{competition:'',format:''}:{})});
 $('search').oninput=()=>update({q:$('search').value},true);
 $('date').onchange=()=>update({date:$('date').value||'all'});
 for(const [id,offset] of [['previous',-1],['next',1]])$(id).onclick=()=>{const today=V.dayKey(new Date().toISOString(),SHTime.timezone);const base=V.validDay(state.date)?state.date:state.date==='tomorrow'?V.shift(today,1):today;update({date:V.shift(base,offset)})};
 $('reset').onclick=()=>update({view:'upcoming',date:'all',sport:'',competition:'',format:'',q:''});
 $('close-details').onclick=()=>$('details').close();
 window.addEventListener('popstate',()=>{state=fromUrl();render()});
 await refresh();setInterval(refresh,60000);
}
start();
})();
