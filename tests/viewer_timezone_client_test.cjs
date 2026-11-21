const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
(async()=>{
 for(const [zone,expected] of [['Asia/Kolkata','5:30 PM'],['Asia/Dhaka','6:00 PM'],['Asia/Karachi','5:00 PM'],['Europe/Paris','1:00 PM']]){
  const window={localStorage:{getItem:()=>null},fetch:async()=>({ok:true,json:async()=>({timezone:zone,source:'ip_country'})})};
  vm.runInNewContext(fs.readFileSync('app/viewer_timezone.js','utf8'),{window,Intl,Date,URLSearchParams});
  await window.SHTime.ready;
  assert.ok(window.SHTime.format('2026-11-21T12:00:00Z','en-US').includes(expected));
  assert.equal(window.SHTime.source,'ip_country');
  assert.equal(window.SHTime.format('bad'),'—');
 }
 let stored='Europe/Paris';
 const w={localStorage:{getItem:k=>k==='shp_timezone'?stored:null,setItem:(k,v)=>{stored=v},removeItem:()=>{stored=''}},fetch:async()=>({ok:true,json:async()=>({timezone:'Asia/Kolkata',source:'ip_country'})})};
 vm.runInNewContext(fs.readFileSync('app/viewer_timezone.js','utf8'),{window:w,Intl,Date,URLSearchParams});
 await w.SHTime.ready;
 assert.equal(w.SHTime.timezone,'Europe/Paris');
 assert.ok(w.SHTime.format('2026-11-21T12:00:00Z','en-US').includes('1:00 PM'));
 w.SHTime.select('Asia/Dhaka');assert.equal(stored,'Asia/Dhaka');
 w.SHTime.select('');assert.equal(w.SHTime.timezone,'Asia/Kolkata');assert.equal(stored,'');
 assert.throws(()=>w.SHTime.select('invalid/timezone'));
 await w.SHTime.selectCountry('BD');assert.equal(w.SHTime.country,'BD');
 assert.throws(()=>w.SHTime.selectCountry('invalid')); 
 console.log('PASS: four-country AM/PM display, saved manual selection, automatic reset');
})().catch(e=>{console.error(e);process.exitCode=1});
