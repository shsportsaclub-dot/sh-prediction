const assert=require('node:assert/strict');
const v=require('../app/fixture_schedule_view.js');
const rows=[
 {id:'midnight',sport_id:'S002',competition:'Cup',competition_id:'cup',status:'scheduled',start_time_utc:'2026-11-27T19:30:00Z',home_team:'A',away_team:'B',format:'T10'},
 {id:'live',sport_id:'S001',competition:'Test',competition_id:'test',status:'live',live_state_verified:true,start_time_utc:'2026-11-28T10:00:00Z',home_team:'C',away_team:'D',format:'Test'},
 {id:'unverified',sport_id:'S002',competition:'Cup',competition_id:'cup',status:'live',live_state_verified:false,start_time_utc:'2026-11-28T12:00:00Z',home_team:'A',away_team:'C',format:'T20'},
 {id:'done',sport_id:'S001',competition:'Test',competition_id:'test',status:'completed',start_time_utc:'2026-11-26T12:00:00Z',home_team:'C',away_team:'D',format:'IT20'},
 {id:'unknown',sport_id:'S002',competition:'Cup',competition_id:'cup',status:'unknown',start_time_utc:null,home_team:'A',away_team:'B',format:null}
];
const now=Date.parse('2026-11-27T12:00:00Z');
const defaults=v.initialState(new URLSearchParams());
assert.equal(defaults.sport,'S001');assert.equal(defaults.date,'today');assert.equal(defaults.view,'all');
const changed=v.changeState({...defaults,date:'all',format:'T20',competition:'IPL'},{sport:'S010'});
assert.equal(changed.date,'today');assert.equal(changed.format,'');assert.equal(changed.competition,'');
assert.equal(v.changeState({...defaults,competition:'IPL'},{format:'ODI'}).competition,'');
assert.equal(v.dayKey(rows[0].start_time_utc,'Asia/Kolkata'),'2026-11-28');
assert.equal(v.dayKey(rows[0].start_time_utc,'UTC'),'2026-11-27');
assert.equal(v.dayKey('2026-11-01T05:30:00Z','America/New_York'),'2026-11-01');
assert.equal(v.dayKey('2026-11-01T06:30:00Z','America/New_York'),'2026-11-01');
assert.equal(v.dayKey(null,'UTC'),null);
assert.equal(v.dayKey('2026-11-28T10:00:00','UTC'),null);
assert.equal(v.validDay('2026-02-30'),false);
assert.equal(v.validDay('2026-99-99'),false);
assert.equal(v.validDay('2026-11-28'),true);
assert.deepEqual(v.filter(rows,{view:'live'},'UTC',now).map(x=>x.id),['live']);
assert.deepEqual(v.filter(rows,{view:'upcoming'},'UTC',now).map(x=>x.id),['midnight']);
assert.deepEqual(v.filter(rows,{view:'results'},'UTC',now).map(x=>x.id),['done']);
assert.equal(v.filter(rows,{view:'all',format:'T20'},'UTC',now).length,1);
assert.equal(v.filter(rows,{view:'all',format:'T10'},'UTC',now).length,1);
assert.equal(v.filter(rows,{view:'all',format:'IT20'},'UTC',now).length,1);
assert.equal(v.filter(rows,{view:'all',format:'__unknown__'},'UTC',now)[0].id,'unknown');
assert.deepEqual(v.filter(rows,{view:'all',date:'today'},'Asia/Kolkata',now),[]);
assert.equal(v.filter(rows,{view:'all',date:'tomorrow',competition:'cup',q:'a'},'Asia/Kolkata',now).length,2);
assert.equal(v.filter(rows,{view:'all',sport:'S001'},'UTC',now).length,2);
assert.equal(v.filter(rows,{view:'all',date:'2026-11-28',q:'nonexistent'},'UTC',now).length,0);
assert.equal(v.groups(rows,'Asia/Kolkata')[0].day,'2026-11-26');
assert.equal(v.groups(rows,'Asia/Kolkata').at(-1).day,null);
assert.deepEqual(v.counts(rows),{all:5,live:1,upcoming:1,results:1});
console.log('PASS schedule filters, exact formats, local dates/DST, verified live and grouping');
