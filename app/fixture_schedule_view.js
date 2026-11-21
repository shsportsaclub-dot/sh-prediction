/* Shared schedule behaviour. No source acquisition, scoring or invented state. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.SHFixtureView=api})(typeof window==='object'?window:this,function(){
'use strict';
const views=['all','schedule','live','upcoming','results'];
function initialState(q){const d=q.get('date')||'today';return {view:views.includes(q.get('view'))?q.get('view'):'all',date:['all','today','tomorrow','week','unknown'].includes(d)||validDay(d)?d:'today',sport:q.get('sport')||'S001',competition:q.get('competition')||'',format:q.get('format')||'',q:q.get('q')||''}}
function changeState(state,values){if(Object.hasOwn(values,'sport'))return {...state,...values,date:'today',view:'all',competition:'',format:'',q:''};if(Object.hasOwn(values,'format'))return {...state,...values,competition:''};return {...state,...values}}
function dayKey(value,zone){
 if(typeof value!=='string'||!value.includes('T')||!/(Z|[+-]\d\d:\d\d)$/.test(value))return null;
 const date=new Date(value);if(!Number.isFinite(date.getTime()))return null;
 try{const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone||undefined,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);const get=k=>parts.find(p=>p.type===k).value;return get('year')+'-'+get('month')+'-'+get('day')}catch(e){return null}
}
function shift(day,amount){const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+amount);return d.toISOString().slice(0,10)}
function validDay(day){if(typeof day!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;const d=new Date(day+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===day}
function bucket(row){
 if(['live','innings_break'].includes(row.status)&&(row.live_state_verified===true||row.source_live_reported===true))return 'live';
 if(row.status==='scheduled')return 'upcoming';
 if(['completed','abandoned','no_result','canceled','cancelled'].includes(row.status))return 'results';
 return 'other';
}
function counts(rows){return {all:rows.length,live:rows.filter(x=>bucket(x)==='live').length,upcoming:rows.filter(x=>bucket(x)==='upcoming').length,results:rows.filter(x=>bucket(x)==='results').length}}
function filter(rows,state,zone,now=Date.now()){
 const today=dayKey(new Date(now).toISOString(),zone),view=views.includes(state.view)?state.view:'all';
 return rows.filter(row=>{
  if(!['all','schedule'].includes(view)&&bucket(row)!==view)return false;
  if(state.sport&&row.sport_id!==state.sport)return false;
  if(state.competition&&(row.competition_id||row.competition)!==state.competition)return false;
  if(state.format&&(row.format||'__unknown__')!==state.format)return false;
  const day=dayKey(row.start_time_utc,zone),date=state.date||'all';
  if(date==='today'&&day!==today)return false;
  if(date==='tomorrow'&&day!==shift(today,1))return false;
  if(date==='week'&&(!day||day<=today||day>shift(today,7)))return false;
  if(date==='unknown'&&day!==null)return false;
  if(/^\d{4}-\d{2}-\d{2}$/.test(date)&&day!==date)return false;
  if(state.q&&!([row.home_team,row.away_team,row.competition].join(' ').toLocaleLowerCase().includes(state.q.toLocaleLowerCase().trim())))return false;
  return true;
 }).sort((a,b)=>{const at=Date.parse(a.start_time_utc),bt=Date.parse(b.start_time_utc);return (Number.isFinite(at)?at:Infinity)-(Number.isFinite(bt)?bt:Infinity)||a.id.localeCompare(b.id)});
}
function groups(rows,zone){
 const days=new Map();
 for(const row of rows){const day=Object.hasOwn(row,'schedule_day')?row.schedule_day:dayKey(row.start_time_utc,zone);if(!days.has(day))days.set(day,new Map());const comps=days.get(day),id=row.competition_id||row.competition||'unknown';if(!comps.has(id))comps.set(id,{id,name:row.competition||'Competition not provided',items:[]});comps.get(id).items.push(row)}
 return [...days].sort(([a],[b])=>(a||'9999').localeCompare(b||'9999')).map(([day,competitions])=>({day,competitions:[...competitions.values()].sort((a,b)=>a.name.localeCompare(b.name))}));
}
return {dayKey,shift,validDay,initialState,changeState,bucket,filter,counts,groups};
});
