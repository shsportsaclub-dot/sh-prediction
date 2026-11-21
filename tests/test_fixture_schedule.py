import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))


def document():
    return dict(dataset_id='openligadb-fixtures:bl1:2026:11',license='ODbL-1.0',
        license_url='https://opendatacommons.org/licenses/odbl/1-0/',
        attribution='Data from OpenLigaDB (www.openligadb.de), licensed under ODbL 1.0',
        public_export_url='https://sh-data-line.onrender.com/open-data/openligadb-fixtures',
        coverage='one_source_matchday',live_feed_verified=False,collection={'last_ok':1795275233},
        published_at=1795275233,total=1,items=[dict(id='shf_'+hashlib.sha256(json.dumps(['openligadb-fixtures:bl1:2026','1'],separators=(',',':')).encode()).hexdigest(),sport_id='S002',fixture_revision=1,source_fixture_id='1',
            competition_id='openligadb:bl1:2026',competition='Bundesliga',home_team='A',away_team='B',
            source='openligadb-fixtures:bl1:2026',start_time_utc='2026-11-27T19:30:00Z',
            source_updated_at=None,source_response_at='2026-11-21T15:42:36Z',
            observed_at='2026-11-21T15:42:37Z',status='scheduled')])


class FixtureScheduleTests(unittest.TestCase):
    def setUp(self):
        import fixture_schedule as f
        self.f=f;self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.f.initialize(self.db)
    def tearDown(self):self.db.close()
    def test_durable_revision_receipts_replay_and_missing_records(self):
        doc=document()
        self.assertEqual(self.f.save(self.db,doc)['changed'],1)
        self.assertEqual(self.f.save(self.db,doc)['changed'],0)
        correction=copy.deepcopy(doc);correction['items'][0].update(fixture_revision=2,start_time_utc='2026-11-28T19:30:00Z')
        self.assertEqual(self.f.save(self.db,correction)['changed'],1)
        with self.assertRaises(ValueError):self.f.save(self.db,doc)
        wrong=copy.deepcopy(correction);wrong['items'][0]['home_team']='Changed without revision'
        with self.assertRaises(ValueError):self.f.save(self.db,wrong)
        self.assertEqual(self.f.read(self.db)['total'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sh_fixture_history').fetchone()[0],2)
        empty={**correction,'items':[],'total':0}
        self.f.save(self.db,empty)
        self.assertEqual(self.f.read(self.db)['total'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sh_fixture_current').fetchone()[0],1)
    def test_whole_snapshot_validation_does_not_partially_write(self):
        for change in [{'license':'unknown'},{'total':2},{'live_feed_verified':True}]:
            with self.subTest(change=change),self.assertRaises(ValueError):self.f.save(self.db,{**document(),**change})
        bad=document();bad['items'][0]['start_time_utc']='2026-11-27'
        with self.assertRaises(ValueError):self.f.save(self.db,bad)
        self.assertEqual(self.f.read(self.db)['total'],0)
    def test_no_redirect_and_configured_scoped_key(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,SH_FIXTURE_API_URL='https://sh-data-line.onrender.com',SH_FIXTURE_READ_KEY='bad'):
            self.assertIsNone(self.f.config())
        self.assertIsNone(self.f.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://elsewhere.invalid'))

    def test_scope_and_identity_mismatch_are_rejected(self):
        for changes in [dict(source='other-source'),dict(competition_id='other-cup'),dict(source_fixture_id='2')]:
            doc=document();doc['items'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.f.save(self.db,doc)

    def test_upstream_error_and_old_publication_are_stale(self):
        doc=document();doc['collection']['last_error']='TimeoutError'
        self.f.save(self.db,doc)
        result=self.f.read(self.db)
        self.assertTrue(result['stale'])
        self.assertEqual(result['upstream_error'],'TimeoutError')
