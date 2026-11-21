"""Isolated synthetic latency regressions; never evidence of real source latency."""
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import live
import api_v1
import cricketdata


class LiveLatency(unittest.TestCase):
    def test_commit_between_empty_read_and_wait_is_not_delayed_until_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'synthetic.sqlite3')
            c = sqlite3.connect(path)
            c.executescript("CREATE TABLE matches(id INTEGER,status TEXT,data_origin TEXT);"
                            "INSERT INTO matches VALUES(1,'live','synthetic');"
                            "CREATE TABLE live_events(id INTEGER PRIMARY KEY,match_id INTEGER,kind TEXT,payload TEXT,created_at TEXT);")
            c.close()
            sent = []
            start = time.monotonic()

            class Output(io.BytesIO):
                def write(self, data):
                    if b'event: delivery' in data:
                        sent.append(time.monotonic() - start)
                    return super().write(data)

            class Handler:
                wfile = Output()
                def send_response(self, *args): pass
                def send_header(self, *args): pass
                def end_headers(self): pass

            class Connection:
                def __init__(self):
                    self.db = sqlite3.connect(path)
                    self.db.row_factory = sqlite3.Row
                    self.injected = False
                def execute(self, sql, args=()):
                    cursor = self.db.execute(sql, args)
                    if 'SELECT * FROM live_events' not in sql or self.injected:
                        return cursor
                    self.injected = True
                    # Freeze an empty result, then commit+notify before stream waits.
                    empty = cursor.fetchall()
                    writer = sqlite3.connect(path)
                    live.publish(writer, 1, 'delivery', {'synthetic': True, 'runs': 1})
                    writer.commit(); writer.close(); live.wake()
                    class Result:
                        def fetchall(self): return empty
                    return Result()
                def commit(self): self.db.commit()
                def close(self): self.db.close()

            live.stream(Handler(), Connection, 1, max_seconds=0.5, heartbeat=0.4)
            self.assertEqual(len(sent), 1)
            self.assertLess(sent[0], 0.15, 'Committed event slept until heartbeat')

    def test_delivery_refreshes_score_without_waiting_for_animation(self):
        source = Path(__file__).resolve().parents[1] / 'app/match_insights.js'
        js = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const block=source.slice(source.indexOf('let ES=null,ESmid=null'),source.indexOf('\n})();',source.indexOf('window.addEventListener("hashchange"')));
const calls=[],handlers={};
global.window=global; global.location={hash:'#/match/123/live'};
global.document={visibilityState:'visible'};global.scrollY=0;
global.addEventListener=()=>{};global.setTimeout=()=>1;global.clearTimeout=()=>{};
global.EventSource=class{addEventListener(k,f){handlers[k]=f}close(){}};
global.mcBallReceived=(id,ev,eventId)=>calls.push(['timeline',id,ev,eventId]);
global.mcBoardRefresh=id=>calls.push(['score',id]);
global.mcFlash=ev=>calls.push(['animation',ev]);
vm.runInThisContext(block);
mcLive({id:123,status:'live'},'live');
handlers.delivery({data:JSON.stringify({runs:4,synthetic:true}),lastEventId:'81'});
assert.equal(calls[0]?.[0],'timeline','Timeline must precede score fetch and animation');
assert.equal(calls[0][1],123);
assert.equal(calls[0][3],'81');
assert.equal(calls[1]?.[0],'score','Score waits for animation callback');
assert.equal(calls.filter(x=>x[0]==='score').length,1);
assert.equal(calls[2][0],'animation');
'''
        result = subprocess.run(['node', '-e', js, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_timeline_shows_only_identified_deliveries_and_keeps_illegal_balls(self):
        source = Path(__file__).resolve().parents[1] / 'app/match_center.js'
        js = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const render=source.slice(source.indexOf('window.mcBallMarkup=function'),source.indexOf('\nfunction batTable'));
const block=source.slice(source.indexOf('/* Immediate delivery timeline'),source.indexOf('/* Board flash:'));
const elements=new Map();
class Element{constructor(){this.children=[];this.dataset={};this.textContent='';this.scrollWidth=100}
 appendChild(el){this.children.push(el);if(el.id)elements.set(el.id,el);return el}
 setAttribute(){} insertAdjacentElement(where,el){elements.set(el.id,el)}
 get firstChild(){return this.children[0]} removeChild(el){this.children.splice(this.children.indexOf(el),1)}}
const board=new Element();global.window=global;global.setTimeout=()=>1;
global.PD=m=>m.provider_detail;global.esc=x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;');
global.document={getElementById:id=>elements.get(id),querySelector:()=>board,createElement:()=>new Element()};
vm.runInThisContext(render+block);
const ball=(runs,extra='',other={})=>({runs,extra,over:'2.3',innings:1,event_key:'actual-delivery-'+eid,...other});
let eid=1;
for(const [original,label] of [[ball(1),'1'],[ball(4),'4'],[ball(6),'6'],[ball(1,'wide'),'WD'],[ball(1,'no_ball'),'NB'],[ball(0,'',{wicket:true}),'W']]){
 const event={...original,event_key:'actual-delivery-'+eid};
 mcBallReceived(123,event,String(eid++));
 assert.ok(elements.get('bs123').innerHTML.includes('>'+label+'</span>'));
}
assert.equal(mcTimelineMerge(123).length,6,'Repeated illegal balls share an over but remain separate deliveries');
mcBallReceived(123,ball(6),'6');assert.equal(mcTimelineMerge(123).length,6,'SSE retry duplicated delivery');
mcBallReceived(123,ball(4,'',{source:'scorecard'}),'7');
mcBallReceived(123,{runs:4,over:'2.3'},'8');
mcBallReceived(123,{event_key:'missing-runs',over:'2.3'},'9');
assert.equal(mcTimelineMerge(123).length,6,'Aggregate or incomplete observation invented a ball');
mcBallReceived(123,{innings_no:1,seq:12,over:'2.4',runs_bat:0,extras:0,extra_type:null,is_wicket:false},'10');
assert.ok(elements.get('bs123').innerHTML.includes('>0</span>'));
mcBallReceived(125,{innings_no:1,seq:90,over:'14.6',runs_bat:1,extras:0},'30');
mcBallReceived(125,{innings_no:2,seq:1,over:'0.1',runs_bat:4,extras:0},'31');
assert.deepEqual(mcTimelineMerge(125).map(b=>b.inning),[1,2],'Scorer innings interleaved after sequence reset');
const ownMarkup=mcBalls({id:123});assert.ok(ownMarkup.includes('>NB</span>'),'Route refresh lost identified scorer balls');
assert.ok(mcBallMarkup([{inning:1,over:0,runs:null}]).includes('<em>= —</em>'),'Missing run total was invented');
const authoritative=[{event_key:'actual-delivery-4',inning:1,over:2,ball:3,runs:1,extra:'wide'}];
mcBalls({id:124,provider_detail:{balls:authoritative}});
mcBallReceived(124,ball(1,'wide',{event_key:'actual-delivery-4'}),'20');
assert.equal(mcTimelineMerge(124).length,1,'Snapshot already included queued SSE ball');
assert.equal(mcTimelineMerge(124,[]).length,0,'Reconciled event returned after leaving history window');
'''
        result = subprocess.run(['node', '-e', js, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_provider_snapshot_and_stream_share_exact_delivery_identity(self):
        c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        c.executescript('CREATE TABLE live_events(id INTEGER PRIMARY KEY,match_id INTEGER,kind TEXT,payload TEXT,created_at TEXT);'
                       'CREATE TABLE ext_match_detail(match_id INTEGER,featured INTEGER,scorecard_json TEXT,scorecard_at TEXT,squad_json TEXT,squad_at TEXT,info_json TEXT,balls_json TEXT,balls_at TEXT,notes_json TEXT);')
        balls = [{'n':i+1,'inning':1,'over':0,'ball':1,'extra':'wd','runs':1} for i in range(3)]
        cricketdata.publish_new_balls(c, 5, balls[:1], None)
        cricketdata.publish_new_balls(c, 5, balls, None)
        c.execute('INSERT INTO ext_match_detail(match_id,featured,balls_json) VALUES(5,1,?)', (json.dumps(balls),))
        snapshot = api_v1.provider_detail(c, 5)['balls']
        streamed = [json.loads(r[0]) for r in c.execute("SELECT payload FROM live_events WHERE kind='delivery' ORDER BY id")]
        self.assertEqual(len({b.get('event_key') for b in snapshot}), 3)
        self.assertEqual([b['event_key'] for b in snapshot[1:]], [b['event_key'] for b in streamed])
