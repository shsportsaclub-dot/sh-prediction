const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
(async()=>{
 const window={addEventListener:()=>{},mcTab:{},mcLater:()=>{},SHTime:{format:(at,lang)=>'SELECTED ZONE '+at}};
 const context={window,SCREENS:{},api:async()=>{throw Error('No insights')},esc:String,t:String,LANG:'en',setTimeout:()=>{},clearInterval:()=>{},setInterval:()=>{},document:{},sessionStorage:{getItem:()=>null}};
 vm.runInNewContext(fs.readFileSync('app/match_insights.js','utf8'),context);
 const html=await window.mcTab.info({id:1,competition_id:2,competition:'Owned cup',format:'T20',start_utc:'2026-11-22T04:40:00Z',home:{id:1,name:'A'},away:{id:2,name:'B'}});
 assert.ok(html.includes('SELECTED ZONE 2026-11-22T04:40:00Z'),'Info must use selected SH viewer timezone rather than browser device timezone');
 console.log('PASS match info uses selected viewer timezone');
})().catch(e=>{console.error(e);process.exitCode=1});
