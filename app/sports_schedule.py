"""Viewer-local read-only schedule across existing sport catalogues.

Existing cricket feeds remain existing feeds, never SH-owned acquisition.
No prediction/scoring tables or source collection settings are changed here.
"""
from collections import Counter
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

import fixture_schedule

SPORTS=json.loads(Path(__file__).with_name('schedule_sports.json').read_text())
FORMAT_CATALOGUE=json.loads(Path(__file__).with_name('scoring_format_catalogue.json').read_text())
FORMATS=FORMAT_CATALOGUE['formats']


def stamp(value):
    try:
        d=datetime.fromisoformat((value or '').replace('Z','+00:00'))
        return d.astimezone(timezone.utc) if d.utcoffset() is not None else None
    except (ValueError,TypeError,OverflowError):return None


def bucket(row):
    if row['status'] in ('live','innings_break') and (row.get('source_live_reported') or row.get('live_state_verified')):return 'live'
    if row['status']=='scheduled':return 'upcoming'
    if row['status'] in ('completed','abandoned','no_result','canceled','cancelled'):return 'results'
    return 'other'


def cricket_rows(db,now):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'matches','competitions','teams','venues'}<=tables:return [],False
    live={r[0]:stamp(r[1]) for r in db.execute('SELECT match_id,fetched_at FROM live_scores')} if 'live_scores' in tables else {}
    if 'ext_match_detail' in tables:
        for row in db.execute('SELECT match_id,scorecard_at FROM ext_match_detail WHERE scorecard_at IS NOT NULL'):
            t=stamp(row[1])
            if t and (row[0] not in live or live[row[0]] is None or t>live[row[0]]):live[row[0]]=t
    rows=[]
    sql='''SELECT m.id,m.competition_id,m.format,m.start_utc,m.status,m.source,m.updated_at,m.match_no,
      c.name competition,c.category,h.name home,a.name away,v.name venue FROM matches m
      JOIN competitions c ON c.id=m.competition_id JOIN teams h ON h.id=m.home_team_id
      JOIN teams a ON a.id=m.away_team_id LEFT JOIN venues v ON v.id=m.venue_id
      WHERE m.data_origin<>'demo' ORDER BY m.start_utc DESC,m.id DESC LIMIT 10001'''
    native=db.execute(sql).fetchall()
    for r in native[:10000]:
        start=stamp(r['start_utc']);source=r['source'] or 'Unspecified source'
        date_only='cricsheet' in source.lower()
        fresh=bool(live.get(r['id']) and 0<=(now-live[r['id']]).total_seconds()<=1800)
        duration=timedelta(days=8 if r['format'] in ('Test','First-class') else 2)
        plausible=bool(start and timedelta(0)<=now-start<=duration)
        reported=r['status']=='live' and fresh and plausible and not date_only
        rows.append(dict(id='cricket:'+str(r['id']),sport_id='S001',competition_id='cricket:'+str(r['competition_id']),
            competition=r['competition'],format=r['format'],home_team=r['home'],away_team=r['away'],
            start_time_utc=start.isoformat() if start and not date_only else None,
            match_date=(r['start_utc'] or '')[:10] if date_only else None,start_time_precision='date_only' if date_only else 'source_schedule',
            status=r['status'],source=source,source_label=source,source_live_reported=reported,
            live_state_verified=False,independent_sh_acquisition=False,venue=r['venue'],match_no=r['match_no'],
            match_center_url='/#/match/'+str(r['id']),coverage_label='Existing cricket catalogue',
            source_updated_at=r['updated_at']))
    return rows,len(native)>10000


def read(db,query,*,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    get=lambda k,default='':query.get(k,[default])[0]
    sport=get('sport','S001');date=get('date','today');view=get('view','all')
    if sport not in {s['sport_id'] for s in SPORTS}:raise ValueError('Unknown sport ID')
    if view not in ('all','schedule','live','upcoming','results'):raise ValueError('Unknown schedule view')
    try:
        zone=ZoneInfo(get('timezone','UTC'));limit=int(get('limit','200'));offset=int(get('offset','0'))
        if not 1<=limit<=200 or offset<0:raise ValueError('Invalid pagination')
    except (ValueError,ZoneInfoNotFoundError,TypeError) as exc:raise ValueError('Valid timezone and pagination required') from exc
    today=now.astimezone(zone).date()
    if date=='today':days={today.isoformat()}
    elif date=='tomorrow':days={(today+timedelta(days=1)).isoformat()}
    elif date=='week':days={(today+timedelta(days=i)).isoformat() for i in range(1,8)}
    elif date in ('all','unknown'):days=None
    else:
        try:
            parsed=datetime.strptime(date,'%Y-%m-%d').date()
            if parsed.isoformat()!=date:raise ValueError()
            days={date}
        except (ValueError,TypeError) as exc:raise ValueError('Valid date required') from exc
    football=fixture_schedule.read(db)
    with db:
        db.execute('BEGIN')
        cricket,truncated=cricket_rows(db,now)
    rows=cricket+[{**r,'independent_sh_acquisition':True,'source_label':'OpenLigaDB via SH DATA LINE',
                  'coverage_label':'One football matchday','source_live_reported':False} for r in football['items']]
    dated=[]
    for row in rows:
        t=stamp(row.get('start_time_utc'));day=t.astimezone(zone).date().isoformat() if t else None
        ongoing=bool(row.get('source_live_reported') and date=='today' and day and day<today.isoformat())
        if ongoing:day=today.isoformat()
        row={**row,'schedule_day':day,'ongoing_today':ongoing}
        if date=='unknown' and t is not None:continue
        if days is not None and day not in days:continue
        dated.append(row)
    sport_rows=[r for r in dated if r['sport_id']==sport]
    format_counts=Counter(r.get('format') or '__unknown__' for r in sport_rows)
    format_values=list(dict.fromkeys(FORMATS.get(sport,[])+sorted(format_counts)))
    formats=[dict(value=f,name='Not provided' if f=='__unknown__' else f,count=format_counts[f],
                  observed=bool(format_counts[f])) for f in format_values]
    fmt=get('format');league=get('competition');search=get('q').casefold().strip()
    filtered=[r for r in sport_rows if not fmt or (r.get('format') or '__unknown__')==fmt]
    if search:filtered=[r for r in filtered if search in ' '.join([r['home_team'],r['away_team'],r['competition']]).casefold()]
    league_rows={}
    for row in filtered:
        entry=league_rows.setdefault(row['competition_id'],dict(value=row['competition_id'],name=row['competition'],count=0))
        entry['count']+=1
    if league:filtered=[r for r in filtered if r['competition_id']==league]
    counts={v:sum(bucket(r)==v for r in filtered) for v in ('live','upcoming','results')};counts['all']=counts['schedule']=len(filtered)
    if view not in ('all','schedule'):filtered=[r for r in filtered if bucket(r)==view]
    filtered.sort(key=lambda r:(r['schedule_day'] or '9999',r.get('start_time_utc') or '9999',r['id']))
    total=len(filtered);sport_counts=Counter(r['sport_id'] for r in dated)
    return dict(items=filtered[offset:offset+limit],total=total,next_offset=offset+limit if offset+limit<total else None,
        sport=sport,date=date,timezone=str(zone),view=view,formats=formats,
        leagues=sorted(league_rows.values(),key=lambda x:x['name']),counts=counts,
        sports=[{**s,'count':sport_counts[s['sport_id']]} for s in SPORTS],
        coverage='Stored observations only; existing cricket catalogue plus independent SH football fixtures',
        source_lanes_separate=True,archive_truncated=truncated,football_stale=football['stale'],
        unassigned_start_times=sum(r.get('start_time_utc') is None for r in rows),
        last_received_at=football.get('last_received_at'),live_feed_verified=False)
