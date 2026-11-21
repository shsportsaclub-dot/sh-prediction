/* Shared schedule behaviour. No source acquisition, scoring or invented state. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.SHFixtureView=api})(typeof window==='object'?window:this,function(){
'use strict';
const views=['all','live','upcoming','results'];
function dayKey(value,zone){
 if(typeof value!=='string'||!value.includes('T')||!/(Z|[+-]\d\d:\d\d)$/.test(value))return null;
 const date=new Date(value);if(!Number.isFinite(date.getTime()))return null;
 try{const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone||undefined,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);const get=k=>parts.find(p=>p.type===k).value;return get('year')+'-'+get('month')+'-'+get('day')}catch(e){return null}
}
function shift(day,amount){const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+amount);return d.toISOString().slice(0,10)}
function validDay(day){if(typeof day!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;const d=new Date(day+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===day}
function bucket(row){
 if(['live','innings_break'].includes(row.status)&&row.live_state_verified===true)return 'live';
 if(row.status==='scheduled')return 'upcoming';
 if(['completed','abandoned'].includes(row.status))return 'results';
 return 'other';
}
function counts(rows){return {all:rows.length,live:rows.filter(x=>bucket(x)==='live').length,upcoming:rows.filter(x=>bucket(x)==='upcoming').length,results:rows.filter(x=>bucket(x)==='results').length}}
function filter(rows,state,zone,now=Date.now()){
 const today=dayKey(new Date(now).toISOString(),zone),view=views.includes(state.view)?state.view:'upcoming';
 return rows.filter(row=>{
  if(view!=='all'&&bucket(row)!==view)return false;
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
 for(const row of rows){const day=dayKey(row.start_time_utc,zone);if(!days.has(day))days.set(day,new Map());const comps=days.get(day),id=row.competition_id||row.competition||'unknown';if(!comps.has(id))comps.set(id,{id,name:row.competition||'Competition not provided',items:[]});comps.get(id).items.push(row)}
 return [...days].sort(([a],[b])=>(a||'9999').localeCompare(b||'9999')).map(([day,competitions])=>({day,competitions:[...competitions.values()].sort((a,b)=>a.name.localeCompare(b.name))}));
}
return {dayKey,shift,validDay,bucket,filter,counts,groups};
});
