"""Independent read-only fixture receipts. Never changes cricket/prediction tables."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import threading
import time
import math
from urllib.request import Request, build_opener, HTTPRedirectHandler

LICENSE='https://opendatacommons.org/licenses/odbl/1-0/'
EXPORT='https://sh-data-line.onrender.com/open-data/openligadb-fixtures'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):return None


def config():
    base=os.getenv('SH_FIXTURE_API_URL','').rstrip('/')
    key=os.getenv('SH_FIXTURE_READ_KEY','')
    if base!='https://sh-data-line.onrender.com' or not re.fullmatch(r'shdl_fixture_[A-Za-z0-9_-]{43}',key):return None
    return base,key


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS sh_fixture_current (
        id TEXT PRIMARY KEY,revision INTEGER NOT NULL,digest TEXT NOT NULL,record_json TEXT NOT NULL,listed INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sh_fixture_history (
        id TEXT NOT NULL,revision INTEGER NOT NULL,digest TEXT NOT NULL,record_json TEXT NOT NULL,received_at TEXT NOT NULL,
        PRIMARY KEY(id,revision));
        CREATE TABLE IF NOT EXISTS sh_fixture_sync (
        id INTEGER PRIMARY KEY CHECK(id=1),metadata_json TEXT,last_ok TEXT,last_error TEXT,next_due REAL NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO sh_fixture_sync(id) VALUES(1);''')


def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _stamp(value,nullable=False):
    if value is None and nullable:return
    if not isinstance(value,str):raise ValueError('Missing timestamp')
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.utcoffset() is None:raise ValueError('Timezone required')


def validate(doc):
    _json(doc)
    if (not isinstance(doc,dict) or doc.get('license')!='ODbL-1.0' or doc.get('license_url')!=LICENSE
        or doc.get('public_export_url')!=EXPORT or doc.get('live_feed_verified') is not False
        or not isinstance(doc.get('attribution'),str) or 'OpenLigaDB' not in doc['attribution']
        or not re.fullmatch(r'openligadb-fixtures:bl1:\d{4}:\d{1,3}',doc.get('dataset_id',''))
        or not isinstance(doc.get('items'),list) or len(doc['items'])>50
        or type(doc.get('total')) is not int or doc['total']!=len(doc['items'])):
        raise ValueError('Invalid licensed fixture snapshot')
    season=doc['dataset_id'].split(':')[2]
    source='openligadb-fixtures:bl1:'+season
    if (type(doc.get('published_at')) not in (int,float) or not math.isfinite(doc['published_at'])
            or not 0<doc['published_at']<=time.time()+60):raise ValueError('Invalid publication time')
    ids=set()
    for item in doc['items']:
        if (not isinstance(item,dict) or not re.fullmatch(r'shf_[a-f0-9]{64}',item.get('id',''))
            or item['id'] in ids or item.get('sport_id')!='S002'
            or type(item.get('fixture_revision')) is not int or item['fixture_revision']<1
            or item.get('status') not in ('scheduled','live','completed','unknown','postponed','cancelled','abandoned','innings_break')):
            raise ValueError('Invalid fixture identity/revision')
        for key in ('competition','competition_id','source','home_team','away_team'):
            if not isinstance(item.get(key),str) or not 1<=len(item[key])<=2000:raise ValueError('Invalid fixture text')
        native=item.get('source_fixture_id')
        if (item['source']!=source or item['competition_id']!='openligadb:bl1:'+season
            or not isinstance(native,str) or not re.fullmatch(r'[1-9][0-9]{0,15}',native)
            or item['id']!='shf_'+hashlib.sha256(_json([source,native]).encode()).hexdigest()):
            raise ValueError('Fixture scope/identity mismatch')
        for field in ('start_time_utc','source_updated_at','source_response_at'):_stamp(item.get(field),True)
        _stamp(item.get('observed_at'))
        ids.add(item['id'])
    return doc


def save(db,doc):
    validate(doc)
    received=datetime.now(timezone.utc).isoformat()
    changed=0
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE sh_fixture_current SET listed=0')
        for item in doc['items']:
            body=_json(item);digest=hashlib.sha256(body.encode()).hexdigest();revision=item['fixture_revision']
            old=db.execute('SELECT revision,digest FROM sh_fixture_current WHERE id=?',(item['id'],)).fetchone()
            if old and (revision<old['revision'] or (revision==old['revision'] and digest!=old['digest'])):
                raise ValueError('Fixture revision conflict')
            if not old or old['digest']!=digest:
                db.execute('INSERT INTO sh_fixture_history VALUES(?,?,?,?,?)',(item['id'],revision,digest,body,received));changed+=1
            db.execute('INSERT INTO sh_fixture_current VALUES(?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET '
                'revision=excluded.revision,digest=excluded.digest,record_json=excluded.record_json,listed=1',
                (item['id'],revision,digest,body))
        metadata={k:v for k,v in doc.items() if k!='items'}
        db.execute('UPDATE sh_fixture_sync SET metadata_json=?,last_ok=?,last_error=NULL,next_due=? WHERE id=1',
                   (_json(metadata),received,time.time()+60))
    return {'stored':len(doc['items']),'changed':changed}


def read(db):
    initialize(db)
    with db:
        db.execute('BEGIN')
        state=db.execute('SELECT * FROM sh_fixture_sync WHERE id=1').fetchone()
        items=[json.loads(r[0]) for r in db.execute('SELECT record_json FROM sh_fixture_current WHERE listed=1 ORDER BY id')]
    meta=json.loads(state['metadata_json']) if state['metadata_json'] else {}
    upstream_error=(meta.get('collection') or {}).get('last_error')
    receipt_stale=not state['last_ok'] or time.time()-datetime.fromisoformat(state['last_ok']).timestamp()>180
    source_stale=time.time()-meta.get('published_at',0)>7*3600
    return {**meta,'items':items,'total':len(items),'last_received_at':state['last_ok'],
        'last_error':state['last_error'],'configured':bool(config()),'live_feed_verified':False,
        'upstream_error':upstream_error,'stale':bool(receipt_stale or source_stale or upstream_error or state['last_error'])}


def sync(db,opener=None):
    initialize(db)
    cfg=config()
    if cfg is None:return {'status':'not_configured'}
    state=db.execute('SELECT next_due FROM sh_fixture_sync WHERE id=1').fetchone()
    if state['next_due']>time.time():return {'status':'not_due'}
    try:
        request=Request(cfg[0]+'/v1/provider/fixtures',headers={'X-API-Key':cfg[1],'Accept':'application/json'})
        with (opener or build_opener(NoRedirect()).open)(request,timeout=15) as response:
            data=response.read(200001)
        if len(data)>200000:raise ValueError('Oversized snapshot')
        result=save(db,json.loads(data))
        return {'status':'ok',**result}
    except Exception as exc:
        db.rollback()
        with db:db.execute('UPDATE sh_fixture_sync SET last_error=?,next_due=? WHERE id=1',
                          (type(exc).__name__,time.time()+60))
        return {'status':'error','error':type(exc).__name__}


def start(db_fn):
    if config() is None:return
    def worker():
        while True:
            try:
                with closing(db_fn()) as db:
                    result=sync(db)
                if result['status']!='not_due':print('SH fixture delivery: '+json.dumps(result),flush=True)
            except Exception as exc:print('SH fixture delivery error: '+type(exc).__name__,flush=True)
            time.sleep(10)
    threading.Thread(target=worker,name='sh-fixture-consumer',daemon=True).start()
