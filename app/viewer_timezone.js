/* Display hints only; server UTC remains authoritative for deadlines. */
(function(root){
'use strict';
const get=k=>{try{return root.localStorage.getItem(k)||''}catch(e){return ''}};
const put=(k,v)=>{try{if(v)root.localStorage.setItem(k,v);else root.localStorage.removeItem(k)}catch(e){}};
let device;try{device=Intl.DateTimeFormat().resolvedOptions().timeZone}catch(e){}
let automatic=device,manual=get('shp_timezone'),country=get('shp_phone_country'),sequence=0;
try{if(manual)new Intl.DateTimeFormat('en-US',{timeZone:manual})}catch(e){manual=''}
let zone=manual||automatic;
function format(value,locale){
 const d=new Date(value);if(!value||isNaN(d))return '—';
 const opts=zone?{timeZone:zone}:{};
 try{return d.toLocaleDateString(locale||undefined,{...opts,year:'numeric',month:'short',day:'numeric'})+', '+d.toLocaleTimeString('en-US',{...opts,hour:'numeric',minute:'2-digit',hour12:true,timeZoneName:'short'})}catch(e){return '—'}
}
const api={format,source:manual?'selected':'device',countries:{IN:'+91',PK:'+92',BD:'+880',FR:'+33'},get timezone(){return zone},get selected(){return manual},get country(){return country},select(value){
 if(value)new Intl.DateTimeFormat('en-US',{timeZone:value});
 manual=value||'';zone=manual||automatic;api.source=manual?'selected':'automatic';put('shp_timezone',manual);return zone;
},selectCountry(value){
 if(value&&!api.countries[value])throw Error('Unknown country');
 country=value;put('shp_phone_country',country);put('shp_phone_country_code',api.countries[country]||'');return refresh();
}};
function refresh(){
 const generation=++sequence;
 const query=new URLSearchParams({device_timezone:device||'',phone_code:get('shp_phone_country_code'),phone_country:country});
 return root.fetch('/api/viewer-timezone?'+query,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('timezone unavailable');return r.json()}).then(j=>{
  if(generation!==sequence)return zone;
  if(j.countries&&typeof j.countries==='object')api.countries=j.countries;
  if(j.timezone){new Intl.DateTimeFormat('en-US',{timeZone:j.timezone});automatic=j.timezone;if(!manual){zone=automatic;api.source=j.source}}
  return zone;
 }).catch(()=>zone);
}
api.ready=refresh();root.SHTime=api;
})(window);
