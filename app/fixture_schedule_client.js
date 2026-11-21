/* Sport -> Today/all formats -> format -> actual leagues. No browser credentials. */
(function(){
'use strict';
const V=SHFixtureView,$=id=>document.getElementById(id);
const labels={all:'Overview',live:'Live',schedule:'Schedule',upcoming:'Fixtures',results:'Results'};
let snapshot,state,requestId=0,fetchFailed=false,searchTimer;
const sports={};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function fromUrl(){return V.initialState(new URLSearchParams(location.search))}
function update(values,replace=false){if(Object.hasOwn(values,'sport'))clearTimeout(searchTimer);state=V.changeState(state,values);const q=new URLSearchParams();for(const k of ['view','date','sport','competition','format','q'])if(state[k]&&state[k]!==({view:'all',date:'today',sport:'S001'}[k]))q.set(k,state[k]);history[replace?'replaceState':'pushState'](null,'',location.pathname+(q.size?'?'+q:''));refresh(true)}
function dateLabel(day){return day?new Date(day+'T12:00:00Z').toLocaleDateString(undefined,{timeZone:'UTC',weekday:'short',month:'short',day:'numeric',year:'numeric'}):'Start date/time not verified'}
function options(id,entries,first,selected){const select=$(id);select.replaceChildren();for(const [value,label] of [...(first===null?[]:[['',first]]),...entries]){const o=node('option',label);o.value=value;select.append(o)}if(selected&&![...select.options].some(o=>o.value===selected)){const o=node('option','Unavailable selection');o.value=selected;select.append(o)}select.value=selected||''}
function showCentre(item){
 if(/^\/#\/match\/\d+$/.test(item.match_center_url||'')){location.href=item.match_center_url;return}
 $('detail-title').textContent=item.home_team+' vs '+item.away_team;
 const body=$('detail-body');body.replaceChildren();const tabs=node('nav',undefined,'tabs'),panel=document.createElement('div');tabs.setAttribute('aria-label','Match centre sections');
 function show(tab){panel.replaceChildren();for(const b of tabs.children)b.setAttribute('aria-pressed',String(b.textContent===tab));if(tab!=='Overview'){panel.append(node('h3',tab),node('p','This fixture source has not supplied '+tab.toLowerCase()+' observations. No scores or events are invented.','notice'));return}
 const dl=document.createElement('dl');for(const [key,value] of [['Sport',sports[item.sport_id]||item.sport_id],['Competition',item.competition],['Start',item.start_time_utc?SHTime.format(item.start_time_utc):'Not verified'],['Status',item.status],['Format',item.format||'Not provided'],['Venue',item.venue||'Not provided'],['Source',item.source_label||item.source||'Not provided']])dl.append(node('dt',key),node('dd',value));panel.append(dl)}
 for(const tab of ['Overview','Live','Scorecard','Timeline','Stats']){const button=node('button',tab);button.onclick=()=>show(tab);tabs.append(button)}body.append(tabs,panel);show('Overview');$('details').showModal();
}
function render(){
 if(!snapshot)return;
 for(const sport of snapshot.sports)sports[sport.sport_id]=sport.name;
 options('sport',snapshot.sports.map(s=>[s.sport_id,s.name]),null,state.sport);
 options('format',snapshot.formats.map(f=>[f.value,f.name+' ('+f.count+')']),'All formats',state.format);
 options('competition',snapshot.leagues.map(c=>[c.value,c.name+' ('+c.count+')']),'All leagues / series',state.competition);
 $('format').disabled=false;$('competition').disabled=!snapshot.leagues.length;
 $('search').value=state.q;
 const today=V.dayKey(new Date().toISOString(),SHTime.timezone);
 $('date').value=V.validDay(state.date)?state.date:state.date==='today'?today:state.date==='tomorrow'?V.shift(today,1):'';
 for(const view of Object.keys(labels)){
  let button=document.getElementById('view-'+view);
  if(!button){button=node('button');button.id='view-'+view;button.type='button';button.setAttribute('role','tab');button.setAttribute('aria-controls','cards');button.onclick=()=>update({view});button.onkeydown=e=>{const keys=Object.keys(labels),i=keys.indexOf(view);let next;if(e.key==='ArrowRight')next=keys[(i+1)%keys.length];if(e.key==='ArrowLeft')next=keys[(i+keys.length-1)%keys.length];if(e.key==='Home')next=keys[0];if(e.key==='End')next=keys.at(-1);if(next){e.preventDefault();update({view:next});document.getElementById('view-'+next).focus()}};$('views').append(button)}
  button.textContent=labels[view]+' ('+(snapshot.counts[view]||0)+')';button.setAttribute('aria-selected',String(state.view===view));button.tabIndex=state.view===view?0:-1;
 }
 $('cards').setAttribute('aria-labelledby','view-'+state.view);$('cards').setAttribute('aria-busy','false');
 $('quick').replaceChildren();for(const [date,label] of [['today','Today'],['tomorrow','Tomorrow'],['week','Next 7 days'],['all','All dates']]){const b=node('button',label);b.setAttribute('aria-pressed',String(state.date===date));b.onclick=()=>update({date});$('quick').append(b)}
 $('days').replaceChildren();for(const group of V.groups(snapshot.items,SHTime.timezone)){if(!group.day)continue;const b=node('button',dateLabel(group.day));b.setAttribute('aria-pressed',String(state.date===group.day));b.onclick=()=>update({date:group.day});$('days').append(b)}
 $('summary').textContent=snapshot.total+' '+(snapshot.total===1?'match':'matches')+' · '+sports[state.sport]+' · '+labels[state.view]+(fetchFailed?' · Update failed':snapshot.football_stale&&state.sport==='S002'?' · STALE football observations':'');
 $('zone-label').textContent='Times in '+(SHTime.timezone||'device time zone');
 $('coverage').textContent=state.sport==='S001'?'Existing cricket catalogue and source reports. These records are not counted as independent SH DATA LINE acquisition.':state.sport==='S002'?'SH DATA LINE independent fixture collection: one OpenLigaDB football matchday. Live event coverage is not connected.':'No current '+sports[state.sport]+' fixture source is connected. Sport/format registration is not proof of live coverage.';
 $('cards').replaceChildren();
 for(const group of V.groups(snapshot.items,SHTime.timezone)){const section=node('section',undefined,'day');section.append(node('h2',dateLabel(group.day)));for(const competition of group.competitions){const block=node('section',undefined,'competition');block.append(node('h3',competition.name));for(const item of competition.items){const row=node('article',undefined,'match'),left=document.createElement('div'),right=node('div',undefined,'right');left.append(node('h4',item.home_team+' vs '+item.away_team),node('div',(sports[item.sport_id]||item.sport_id)+' · '+(item.format||'Format not provided')+(item.ongoing_today?' · Ongoing today':''),'meta'),node('div',item.source_label||item.source,'meta'));
 const time=document.createElement('div');time.append(node('time',(item.ongoing_today?'Started: ':'')+(item.start_time_utc?SHTime.format(item.start_time_utc):'Start time not verified'+(item.match_date?' · Source date '+item.match_date:''))),node('span',item.status==='live'&&!item.source_live_reported&&!item.live_state_verified?'Live report not current':item.status,'status'));const info=node('button','Match centre');info.setAttribute('aria-label','Match centre: '+item.home_team+' vs '+item.away_team);info.onclick=()=>showCentre(item);right.append(time,info);row.append(left,right);block.append(row)}section.append(block)}$('cards').append(section)}
 if(!snapshot.total){const empty=node('div',undefined,'empty');empty.append(node('h2','No collected matches for these filters'),node('p','No current fixtures are available in this sport/date/format selection. Try All dates for the existing catalogue; missing coverage is not a worldwide no-match claim.'));const reset=node('button','Show all dates for this sport');reset.onclick=()=>update({date:'all',view:'all',competition:'',format:'',q:''});empty.append(reset);$('cards').append(empty)}
 if(snapshot.next_offset!==null){const more=node('button','Load more matches');more.onclick=()=>refresh(false,snapshot.next_offset);$('cards').append(more)}
 $('freshness').textContent='Stored observations only. '+(snapshot.archive_truncated?'Archive query capped at the latest 10,000 cricket records. ':'')+'Unknown start times are excluded from daily schedules. Match-level sources remain separate.';
}
async function refresh(clear=false,offset=0){
 const generation=++requestId;
 if(clear){snapshot=null;$('cards').replaceChildren();$('summary').textContent='Loading selected sport schedule…';$('cards').setAttribute('aria-busy','true');$('format').disabled=true;$('competition').disabled=true}
 const q=new URLSearchParams({...state,timezone:SHTime.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',offset:String(offset),limit:'200'});
 try{const response=await fetch('/api/sports-schedule?'+q,{cache:'no-store'});if(!response.ok)throw Error('schedule unavailable');const next=await response.json();if(generation!==requestId)return;if(!Array.isArray(next.items)||!Array.isArray(next.sports))throw Error('invalid schedule');
 // Refresh every loaded page so a poll does not collapse Load more back to page one.
 const loaded=!clear&&!offset&&snapshot?snapshot.items.length:0;
 while(next.next_offset!==null&&next.items.length<loaded){q.set('offset',String(next.next_offset));const pageResponse=await fetch('/api/sports-schedule?'+q,{cache:'no-store'});if(!pageResponse.ok)throw Error('schedule page unavailable');const page=await pageResponse.json();if(generation!==requestId)return;if(!Array.isArray(page.items)||!page.items.length)throw Error('invalid schedule page');next.items.push(...page.items);next.next_offset=page.next_offset}
 if(offset&&snapshot)next.items=[...new Map([...snapshot.items,...next.items].map(r=>[r.id,r])).values()];snapshot=next;fetchFailed=false;render()}catch(e){if(generation!==requestId)return;fetchFailed=true;if(snapshot)render();else{$('summary').textContent='Selected sport schedule unavailable. Please retry shortly.';$('cards').setAttribute('aria-busy','false')}}
}
async function start(){state=fromUrl();await SHTime.ready;for(const zone of new Set(['UTC',SHTime.selected,...(typeof Intl.supportedValuesOf==='function'?Intl.supportedValuesOf('timeZone'):['Asia/Kolkata','America/New_York'])].filter(Boolean))){const o=node('option',zone);o.value=zone;$('zone').append(o)}$('zone').value=SHTime.selected||'';$('zone').onchange=()=>{SHTime.select($('zone').value);refresh(true)};
 for(const id of ['sport','format','competition'])$(id).onchange=()=>update({[id]:$(id).value});
 $('search').oninput=()=>{clearTimeout(searchTimer);const text=$('search').value;searchTimer=setTimeout(()=>update({q:text},true),250)};
 $('date').onchange=()=>update({date:$('date').value||'today'});for(const [id,n] of [['previous',-1],['next',1]])$(id).onclick=()=>{const today=V.dayKey(new Date().toISOString(),SHTime.timezone),day=V.validDay(state.date)?state.date:state.date==='tomorrow'?V.shift(today,1):today;update({date:V.shift(day,n)})};
 $('reset').onclick=()=>update({sport:state.sport||'S001'});$('close-details').onclick=()=>$('details').close();window.addEventListener('popstate',()=>{state=fromUrl();refresh(true)});await refresh(true);setInterval(()=>refresh(),60000);
}
start();
})();
