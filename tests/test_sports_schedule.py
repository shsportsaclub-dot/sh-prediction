import json
from pathlib import Path
import sqlite3
import sys
import unittest
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))


class SportsScheduleTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE competitions(id INTEGER PRIMARY KEY,name TEXT,category TEXT);
            CREATE TABLE teams(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE venues(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE matches(id INTEGER PRIMARY KEY,competition_id INTEGER,home_team_id INTEGER,away_team_id INTEGER,
              venue_id INTEGER,format TEXT,start_utc TEXT,status TEXT,source TEXT,updated_at TEXT,match_no TEXT,data_origin TEXT);
            CREATE TABLE live_scores(match_id INTEGER,fetched_at TEXT);
            INSERT INTO teams VALUES(1,'A'),(2,'B');
            INSERT INTO competitions VALUES(1,'T20 League','League'),(2,'ODI Cup','International'),(3,'T10 Cup','League');''')
        self.now=datetime(2026,11,22,8,tzinfo=timezone.utc)
    def tearDown(self):self.db.close()
    def add(self,id,comp,fmt,start='2026-11-22T10:00:00Z',status='scheduled',source='Owner scorer',origin='verified'):
        self.db.execute('INSERT INTO matches VALUES(?,?,1,2,NULL,?,?,?,?,?,?,?)',
            (id,comp,fmt,start,status,source,'2026-11-22T07:59:00Z','1',origin));self.db.commit()
    def read(self,**q):
        import sports_schedule
        return sports_schedule.read(self.db,{k:[v] for k,v in q.items()},now=self.now)
    def test_default_today_cricket_all_formats_then_format_leagues(self):
        self.add(1,1,'T20');self.add(2,2,'ODI');self.add(3,3,'T10')
        out=self.read(timezone='Asia/Kolkata')
        self.assertEqual(out['sport'],'S001');self.assertEqual(out['date'],'today');self.assertEqual(out['total'],3)
        self.assertEqual(len(out['leagues']),3);self.assertEqual(len(out['sports']),45)
        filtered=self.read(timezone='Asia/Kolkata',format='T20')
        self.assertEqual([r['name'] for r in filtered['leagues']],['T20 League'])
        self.assertEqual([r['format'] for r in filtered['items']],['T20'])
        self.assertTrue(all(not r['independent_sh_acquisition'] for r in out['items']))
    def test_timezone_unknown_midnight_and_demo(self):
        self.add(1,1,'T20',start='2026-11-21T19:30:00Z')
        self.add(2,1,'T20',source='Cricsheet archive',start='2026-11-22T00:00:00Z')
        self.add(3,1,'T20',origin='demo')
        self.assertEqual(self.read(timezone='Asia/Kolkata')['total'],1)
        self.assertEqual(self.read(timezone='UTC')['total'],0)
    def test_options_are_not_derived_from_one_result_page(self):
        for i in range(205):self.add(i+1,1 if i<204 else 2,'T20' if i<204 else 'ODI')
        out=self.read(timezone='UTC',limit='10')
        self.assertEqual(len(out['items']),10);self.assertEqual(out['total'],205)
        self.assertEqual(len(out['leagues']),2);self.assertEqual(out['next_offset'],10)
    def test_unconnected_sport_and_exact_format_options(self):
        self.add(1,1,'T20')
        out=self.read(timezone='UTC',sport='S010')
        self.assertEqual(out['total'],0);self.assertEqual(out['leagues'],[])
        self.assertNotIn('T20',[f['value'] for f in out['formats']])
        cricket=self.read(timezone='UTC')
        self.assertTrue({'Test','T10','T20','ODI','The Hundred','Super Six'}<={f['value'] for f in cricket['formats']})
    def test_stale_live_is_not_todays_live_and_current_test_keeps_start(self):
        self.add(1,1,'T20',start='2026-01-01T00:00:00Z',status='live')
        self.add(2,1,'Test',start='2026-11-19T08:00:00Z',status='live')
        self.db.execute("INSERT INTO live_scores VALUES(2,'2026-11-22T07:59:00Z')");self.db.commit()
        out=self.read(timezone='UTC',view='live')
        self.assertEqual(out['total'],1);self.assertEqual(out['items'][0]['start_time_utc'],'2026-11-19T08:00:00+00:00')
        self.assertEqual(out['items'][0]['schedule_day'],'2026-11-22')
    def test_invalid_scope_and_pagination(self):
        for q in [dict(sport='S999'),dict(timezone='bad/zone'),dict(limit='9999')]:
            with self.subTest(q=q),self.assertRaises(ValueError):self.read(**{'timezone':'UTC',**q})
