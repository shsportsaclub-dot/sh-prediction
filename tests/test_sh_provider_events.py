import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import sh_provider_events as consumer


def event(cursor=1, revision=1, identity='event-a', **changes):
    return dict(event_id=identity, sport_id='S002', competition_id='synthetic-cup',
                match_id='synthetic-match', source_id='synthetic-source',
                event_type='goal', period='1', sequence=cursor, participants=['synthetic-team'],
                score_impact={'home': 1}, extensions={}, source_timestamp='2026-11-21T01:00:00Z',
                ingestion_timestamp='2026-11-21T01:00:01Z', source_revision=1,
                source_license_reference='Synthetic test permission', data_kind='synthetic',
                source_attribution='Synthetic scorer', distribution_license_reference='Synthetic distribution',
                cursor=cursor, revision=revision, **changes)


def page(items, cursor, more=False):
    return {'items': items, 'next_cursor': cursor, 'has_more': more,
            'live_feed_verified': False, 'quota': {'remaining': 20, 'reset_epoch': 1800000060}}


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'prediction.db'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.env = patch.dict(os.environ, {'SH_DATA_API_URL': 'https://data.example',
            'SH_DATA_API_KEY': 'shdl_read_' + 'A' * 43, 'SH_DATA_PROVIDER_MODE': 'events',
            'SH_DATA_EVENT_KINDS': 'synthetic', 'SH_DATA_PROVIDER': 'SH_DATA_LINE'})
        self.env.start()

    def tearDown(self):
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def opener(self, *documents):
        remaining = iter(documents)
        def open_request(request, timeout):
            self.assertIn('/v1/provider/events?after=', request.full_url)
            self.assertNotIn('Authorization', request.headers)
            return io.BytesIO(json.dumps(next(remaining)).encode())
        return open_request

    def test_persists_same_ids_corrections_and_restart_cursor(self):
        first = consumer.sync(self.db, opener=self.opener(page([event()], 1)))
        self.assertEqual(first['inserted'], 1)
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        correction = event(2, 2)
        correction.update(correction_reason='Synthetic correction', score_impact={'home': 0})
        def opener(request, timeout):
            self.assertTrue(request.full_url.endswith('after=1'))
            return io.BytesIO(json.dumps(page([correction], 2)).encode())
        self.assertEqual(consumer.sync(self.db, opener=opener)['inserted'], 1)
        audit = consumer.audit(self.db)
        self.assertEqual([row['event']['event_id'] for row in audit['items']], ['event-a', 'event-a'])
        self.assertEqual([row['event']['revision'] for row in audit['items']], [1, 2])
        self.assertEqual(audit['items'][1]['event']['score_impact'], {'home': 0})
        self.assertEqual(audit['status']['cursor'], 2)

    def test_key_rotation_replays_without_duplicate_facts(self):
        consumer.sync(self.db, opener=self.opener(page([event()], 1)))
        with patch.dict(os.environ, {'SH_DATA_API_KEY': 'shdl_read_' + 'B' * 43}):
            result = consumer.sync(self.db, opener=self.opener(page([event()], 1)))
            self.assertEqual(result['duplicates'], 1)
            self.assertEqual(len(consumer.audit(self.db)['items']), 1)

    def test_admin_evidence_preserves_original_and_exposes_latest_receipt(self):
        consumer.sync(self.db, opener=self.opener(page([event()], 1)))
        new_delivery = event()
        new_delivery.update(source_attribution='Updated scorer', distribution_license_reference='Updated grant')
        with patch.dict(os.environ, {'SH_DATA_API_KEY': 'shdl_read_' + 'B' * 43}):
            self.assertEqual(consumer.sync(self.db, opener=self.opener(page([new_delivery], 1)))['duplicates'], 1)
        row = consumer.audit(self.db)['items'][0]
        self.assertEqual(row['event']['distribution_license_reference'], 'Synthetic distribution')
        self.assertEqual(row['latest_receipt']['distribution_license_reference'], 'Updated grant')
        self.assertEqual(row['latest_receipt']['source_attribution'], 'Updated scorer')
        self.assertEqual(row['receipt_count'], 2)

    def test_empty_filtered_page_continues_but_work_is_bounded(self):
        result = consumer.sync(self.db, opener=self.opener(page([], 200, True), page([event(201)], 201)))
        self.assertEqual((result['pages'], result['cursor'], result['inserted']), (2, 201, 1))
        result = consumer.sync(self.db, opener=self.opener(page([], 400, True), page([], 600, True)))
        self.assertEqual((result['pages'], result['cursor'], result['has_more']), (2, 600, True))

    def test_page_conflict_rolls_back_records_and_cursor(self):
        consumer.sync(self.db, opener=self.opener(page([event()], 1)))
        changed = event(3)
        changed['score_impact'] = {'home': 99}
        result = consumer.sync(self.db, opener=self.opener(page([event(2, identity='event-b'), changed], 3)))
        self.assertEqual(result['error'], 'REVISION_CONFLICT')
        audit = consumer.audit(self.db)
        self.assertEqual(len(audit['items']), 1)
        self.assertEqual(audit['status']['cursor'], 1)

    def test_invalid_page_never_advances_cursor_or_partially_inserts(self):
        cases = [page([event()], 0), page([], 0, True), page([event(), event()], 1),
                 page([dict(event(), raw_observation={'private': True})], 1),
                 page([dict(event(), source_timestamp='unknown')], 1),
                 page([dict(event(), data_kind='live')], 1),
                 page([dict(event(), revision=True)], 1)]
        for document in cases:
            with self.subTest(document=document), patch('sh_provider_events.time.time', return_value=1800000000):
                result = consumer.sync(self.db, opener=self.opener(document))
                self.assertEqual(result['error'], 'INVALID_PAGE')
                audit = consumer.audit(self.db)
                self.assertEqual(audit['items'], [])
                self.assertEqual(audit['status']['cursor'], 0)
                self.db.execute('UPDATE sh_provider_checkpoints SET retry_at=0')
                self.db.commit()

    def test_429_cooldown_persists_and_does_not_hold_database_lock(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            other = sqlite3.connect(self.path, timeout=.2)
            try:
                other.execute('CREATE TABLE IF NOT EXISTS network_lock_probe (value TEXT)')
                other.commit()
            finally:
                other.close()
            raise HTTPError(request.full_url, 429, 'throttle', {'Retry-After': '10'}, io.BytesIO(b'ignored'))
        with patch('sh_provider_events.time.time', return_value=1800000000):
            self.assertEqual(consumer.sync(self.db, opener=opener)['error'], 'HTTP_429')
            self.assertEqual(consumer.sync(self.db, opener=opener)['status'], 'cooldown')
        self.assertEqual(len(calls), 1)
        with patch('sh_provider_events.time.time', return_value=1800000011):
            self.assertEqual(consumer.sync(self.db, opener=self.opener(page([], 0)))['status'], 'ok')

    def test_auth_errors_do_not_fallback_or_disclose_credentials(self):
        for code in (401, 403):
            def opener(request, timeout):
                raise HTTPError(request.full_url, code, 'private secret text', {}, io.BytesIO(b'private'))
            result = consumer.sync(self.db, opener=opener)
            self.assertEqual(result['error'], 'HTTP_' + str(code))
            self.assertNotIn(os.environ['SH_DATA_API_KEY'], json.dumps(consumer.status(self.db)))
            self.db.execute('UPDATE sh_provider_checkpoints SET retry_at=0')
            self.db.commit()

    def test_disabled_or_invalid_configuration_makes_no_request(self):
        def unexpected(*args, **kwargs):
            self.fail('Unexpected network request')
        for change in [{'SH_DATA_PROVIDER_MODE': 'legacy'}, {'SH_DATA_API_KEY': 'master-secret'},
                       {'SH_DATA_API_URL': 'http://outside.example'}, {'SH_DATA_PROVIDER': 'off'}]:
            with patch.dict(os.environ, change):
                self.assertEqual(consumer.sync(self.db, opener=unexpected)['status'], 'not_configured')

    def test_network_response_size_is_bounded(self):
        def opener(request, timeout):
            return io.BytesIO(b' ' * (consumer.MAX_RESPONSE_BYTES + 1))
        self.assertEqual(consumer.sync(self.db, opener=opener)['error'], 'INVALID_PAGE')

    def test_structured_participants_match_the_producer_contract(self):
        item = event()
        item['participants'] = [{'id': 'team-1', 'role': 'home'}, 42]
        result = consumer.sync(self.db, opener=self.opener(page([item], 1)))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(consumer.audit(self.db)['items'][0]['event']['participants'],
                         [{'id': 'team-1', 'role': 'home'}, 42])

    @patch('sh_provider_events.time.time', return_value=1800000000)
    def test_oversized_retry_after_is_bounded_and_persisted(self, clock):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 429, 'throttle', {'Retry-After': '9' * 400}, io.BytesIO())
        self.assertEqual(consumer.sync(self.db, opener=opener)['error'], 'HTTP_429')
        self.assertTrue(1800000000 < consumer.status(self.db)['retry_at'] <= 1800086400)

    def test_transport_does_not_forward_credentials_on_redirect(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.request import Request, build_opener
        target_calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/target')
                    self.end_headers()
                else:
                    target_calls.append(self.headers.get('X-API-Key'))
                    self.send_response(200)
                    self.end_headers()
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                request = Request('http://127.0.0.1:' + str(server.server_port) + '/redirect',
                                  headers={'X-API-Key': 'synthetic-secret'})
                with self.assertRaises(HTTPError) as rejected:
                    build_opener(consumer.NoRedirect()).open(request, timeout=3)
                rejected.exception.close()
                self.assertEqual(rejected.exception.code, 302)
                self.assertEqual(target_calls, [])
            finally:
                server.shutdown()
                worker.join(timeout=2)

    def test_scheduler_routes_opt_in_mode_to_the_durable_inbox(self):
        import scheduler
        stop = threading.Event()
        def db_fn():
            c = sqlite3.connect(self.path)
            c.row_factory = sqlite3.Row
            return c
        def opener(request, timeout):
            stop.set()
            self.assertIn('/v1/provider/events?after=0', request.full_url)
            return io.BytesIO(json.dumps(page([event()], 1)).encode())
        with patch.dict(os.environ, {'CRICKETDATA_API_KEY': ''}):
            scheduler.live_loop(db_fn, opener=opener, stop=stop)
        self.assertEqual(consumer.audit(self.db)['items'][0]['event']['event_id'], 'event-a')


class ConsumerAuditHttpTests(unittest.TestCase):
    def test_admin_audit_is_private_and_does_not_require_core_migration(self):
        import test_v1 as T
        T._migrate_once()
        self.assertEqual(T.call('/api/v1/admin/bridge/sh-events')[0], 403)
        code, body = T.call('/api/v1/admin/bridge/sh-events', h=T.A)
        self.assertEqual(code, 200)
        self.assertIsInstance(body['items'], list)
        self.assertFalse(body['status']['production_verified'])
        self.assertEqual(T.call('/api/v1/admin/bridge/sh-events?after=-1', h=T.A)[0], 400)
