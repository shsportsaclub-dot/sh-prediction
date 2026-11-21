"""Opt-in SH DATA LINE consumer inbox; no inferred matches or scoring changes."""
import datetime
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_INT = 2**63 - 1
FACTS = ('event_id', 'sport_id', 'competition_id', 'match_id', 'source_id', 'event_type',
         'period', 'sequence', 'participants', 'score_impact', 'extensions', 'source_timestamp',
         'ingestion_timestamp', 'source_revision', 'source_license_reference', 'revision', 'data_kind')


class InvalidPage(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class ConcurrentCursor(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None  # Never forward a consumer secret to another URL.


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def selected():
    return os.getenv('SH_DATA_PROVIDER_MODE', 'legacy').lower() == 'events'


def _config():
    base = os.getenv('SH_DATA_API_URL', '').rstrip('/')
    key = os.getenv('SH_DATA_API_KEY', '')
    try:
        url = urlsplit(base)
        kinds = set(os.getenv('SH_DATA_EVENT_KINDS', 'live,historical').split(','))
        if (not selected() or os.getenv('SH_DATA_PROVIDER', '').lower() in ('off', '0', 'false', 'none')
                or url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or not re.fullmatch(r'shdl_read_[A-Za-z0-9_-]{43}', key)
                or not kinds or not kinds <= {'live', 'historical', 'synthetic'}):
            return None
        return {'origin': base, 'key': key, 'kinds': kinds,
                'feed_id': hashlib.sha256((base + '\0' + key).encode()).hexdigest()}
    except ValueError:
        return None


def _present(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='sh_provider_checkpoints'").fetchone())


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS sh_provider_schema(version INTEGER PRIMARY KEY);
    INSERT OR IGNORE INTO sh_provider_schema VALUES(1);
    CREATE TABLE IF NOT EXISTS sh_provider_checkpoints (
        feed_id TEXT PRIMARY KEY, origin TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
        last_ok TEXT, last_error TEXT, retry_at REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS sh_provider_inbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT NOT NULL,
        event_id TEXT NOT NULL, revision INTEGER NOT NULL, source_cursor INTEGER NOT NULL,
        data_kind TEXT NOT NULL, received_at TEXT NOT NULL, fingerprint TEXT NOT NULL,
        payload_json TEXT NOT NULL, UNIQUE(origin,event_id,revision), UNIQUE(origin,source_cursor));
    CREATE TABLE IF NOT EXISTS sh_provider_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, feed_id TEXT NOT NULL,
        inbox_id INTEGER NOT NULL REFERENCES sh_provider_inbox(id), source_cursor INTEGER NOT NULL,
        attribution TEXT NOT NULL, distribution_reference TEXT NOT NULL, received_at TEXT NOT NULL,
        UNIQUE(feed_id,source_cursor,attribution,distribution_reference));
    ''')
    if [row[0] for row in c.execute('SELECT version FROM sh_provider_schema')] != [1]:
        raise ValueError('Unsupported inbox schema')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _int(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INT:
        raise InvalidPage('Invalid integer')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise InvalidPage('Invalid text')
    return value


def _stamp(value):
    stamp = datetime.datetime.fromisoformat(_text(value).replace('Z', '+00:00'))
    if stamp.utcoffset() is None:
        raise InvalidPage('Timezone required')
    return stamp.astimezone(datetime.timezone.utc).isoformat()


def _validate(document, after, kinds):
    if (not isinstance(document, dict) or not isinstance(document.get('items'), list)
            or len(document['items']) > 200 or type(document.get('has_more')) is not bool):
        raise InvalidPage('Invalid page')
    _json(document)  # Reject all non-finite JSON numbers, including metadata.
    cursor = _int(document.get('next_cursor'))
    if cursor < after or (document['has_more'] and cursor <= after):
        raise InvalidPage('Cursor did not advance')
    previous = after
    records = []
    for item in document['items']:
        if not isinstance(item, dict) or {'raw_observation', 'observation_id'} & item.keys():
            raise InvalidPage('Raw audit payload is not a consumer event')
        record = {key: item[key] for key in FACTS}
        for key in ('event_id', 'sport_id', 'competition_id', 'match_id', 'source_id', 'event_type', 'period', 'source_license_reference'):
            _text(record[key])
        for key in ('revision', 'source_revision'):
            _int(record[key], 1)
        _int(record['sequence'])
        if record['data_kind'] not in kinds:
            raise InvalidPage('Data kind not enabled')
        if not re.fullmatch(r'S[0-9]{3}', record['sport_id']):
            raise InvalidPage('Stable sport ID required')
        if (not isinstance(record['participants'], list) or
                not isinstance(record['score_impact'], dict) or not isinstance(record['extensions'], dict)):
            raise InvalidPage('Invalid event fields')
        # Producer permits a JSON list, including structured participants or
        # numeric native IDs. Preserve it; never infer identities from names.
        record['source_timestamp'] = _stamp(record['source_timestamp'])
        record['ingestion_timestamp'] = _stamp(record['ingestion_timestamp'])
        if record['revision'] > 1:
            record['correction_reason'] = _text(item.get('correction_reason'))
        record['cursor'] = _int(item.get('cursor'), 1)
        if not previous < record['cursor'] <= cursor:
            raise InvalidPage('Unordered event cursors')
        previous = record['cursor']
        record['source_attribution'] = _text(item.get('source_attribution'))
        record['distribution_license_reference'] = _text(item.get('distribution_license_reference'))
        records.append(record)
    return records, cursor, document['has_more']


def _fetch(config, after, opener):
    request = urllib.request.Request(config['origin'] + '/v1/provider/events?after=' + str(after),
        headers={'X-API-Key': config['key'], 'Accept': 'application/json', 'User-Agent': 'SH-PREDICTION-Provider/1.0'})
    open_request = opener or urllib.request.build_opener(NoRedirect()).open
    with open_request(request, timeout=15) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise InvalidPage('Oversized page')
    return json.loads(body)


def _save(c, config, expected, records, cursor, received):
    c.execute('BEGIN IMMEDIATE')
    current = c.execute('SELECT cursor FROM sh_provider_checkpoints WHERE feed_id=?', (config['feed_id'],)).fetchone()[0]
    if current != expected:
        raise ConcurrentCursor('Another poll committed first')
    inserted = duplicates = 0
    for record in records:
        facts = {key: value for key, value in record.items()
                 if key not in ('cursor', 'source_attribution', 'distribution_license_reference')}
        fingerprint = hashlib.sha256(_json(facts).encode()).hexdigest()
        existing = c.execute('SELECT * FROM sh_provider_inbox WHERE origin=? AND '
            '((event_id=? AND revision=?) OR source_cursor=?)',
            (config['origin'], record['event_id'], record['revision'], record['cursor'])).fetchone()
        if existing:
            if (existing['event_id'] != record['event_id'] or existing['revision'] != record['revision'] or
                    existing['source_cursor'] != record['cursor'] or existing['fingerprint'] != fingerprint):
                raise RevisionConflict('Immutable revision changed')
            inbox_id = existing['id']
            duplicates += 1
        else:
            inbox_id = c.execute('INSERT INTO sh_provider_inbox '
                '(origin,event_id,revision,source_cursor,data_kind,received_at,fingerprint,payload_json) VALUES(?,?,?,?,?,?,?,?)',
                (config['origin'], record['event_id'], record['revision'], record['cursor'],
                 record['data_kind'], received, fingerprint, _json(record))).lastrowid
            inserted += 1
        c.execute('INSERT OR IGNORE INTO sh_provider_receipts '
            '(feed_id,inbox_id,source_cursor,attribution,distribution_reference,received_at) VALUES(?,?,?,?,?,?)',
            (config['feed_id'], inbox_id, record['cursor'], record['source_attribution'],
             record['distribution_license_reference'], received))
    c.execute('UPDATE sh_provider_checkpoints SET cursor=?,last_ok=?,last_error=NULL,retry_at=0 WHERE feed_id=?',
              (cursor, received, config['feed_id']))
    c.commit()
    return inserted, duplicates


def _retry(error):
    if error.code == 429:
        value = error.headers.get('Retry-After', '') if error.headers else ''
        try:
            if value.isdigit():
                return max(1, min(86400, int(value)))
            return max(1, min(86400, parsedate_to_datetime(value).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            return 60
    return 300 if error.code in (401, 403) else 60


def sync(c, now_fn=utcnow, opener=None, max_pages=2):
    config = _config()
    if not config:
        return {'status': 'not_configured'}
    if c.in_transaction:
        return {'status': 'error', 'error': 'CALLER_TRANSACTION'}
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ValueError('max_pages must be 1–5')
    initialize(c)
    c.execute('INSERT OR IGNORE INTO sh_provider_checkpoints(feed_id,origin) VALUES(?,?)', (config['feed_id'], config['origin']))
    c.commit()
    state = c.execute('SELECT * FROM sh_provider_checkpoints WHERE feed_id=?', (config['feed_id'],)).fetchone()
    if state['retry_at'] > time.time():
        return {'status': 'cooldown', 'retry_at': state['retry_at'], 'cursor': state['cursor']}
    cursor, inserted, duplicates, pages, more = state['cursor'], 0, 0, 0, False
    try:
        for _ in range(max_pages):
            document = _fetch(config, cursor, opener)
            records, next_cursor, more = _validate(document, cursor, config['kinds'])
            added, repeated = _save(c, config, cursor, records, next_cursor, now_fn())
            cursor, inserted, duplicates, pages = next_cursor, inserted + added, duplicates + repeated, pages + 1
            if not more:
                break
        return {'status': 'ok', 'cursor': cursor, 'inserted': inserted, 'duplicates': duplicates, 'pages': pages, 'has_more': more}
    except ConcurrentCursor:
        c.rollback()
        return {'status': 'concurrent_skip'}
    except Exception as error:
        c.rollback()
        if isinstance(error, urllib.error.HTTPError):
            code, delay = 'HTTP_' + str(error.code), _retry(error)
            error.close()
        else:
            code = ('REVISION_CONFLICT' if isinstance(error, RevisionConflict) else
                    'DATABASE_ERROR' if isinstance(error, sqlite3.Error) else
                    'INVALID_PAGE' if isinstance(error, (ValueError, TypeError, KeyError, OverflowError)) else 'NETWORK_ERROR')
            delay = 30
        c.execute('UPDATE sh_provider_checkpoints SET last_error=?,retry_at=? WHERE feed_id=? AND cursor=?',
                  (code, time.time() + delay, config['feed_id'], cursor))
        c.commit()
        return {'status': 'error', 'error': code, 'cursor': cursor}


def status(c):
    config = _config()
    out = {'mode': 'events', 'selected': selected(), 'configured': bool(config), 'cursor': 0,
           'records': 0, 'last_ok': None, 'last_error': None, 'retry_at': 0, 'production_verified': False}
    if not _present(c):
        return out
    if config:
        row = c.execute('SELECT cursor,last_ok,last_error,retry_at FROM sh_provider_checkpoints WHERE feed_id=?', (config['feed_id'],)).fetchone()
        if row:
            out.update(dict(row))
        out['records'] = c.execute('SELECT count(*) FROM sh_provider_inbox WHERE origin=?', (config['origin'],)).fetchone()[0]
    return out


def audit(c, after=0):
    _int(after)
    out = {'status': status(c), 'items': [], 'next_cursor': after}
    if not _present(c):
        return out
    rows = c.execute('SELECT id,received_at,payload_json FROM sh_provider_inbox WHERE id>? ORDER BY id LIMIT 200', (after,)).fetchall()
    for row in rows:
        receipt = c.execute('SELECT id,source_cursor,attribution,distribution_reference,received_at,'
            '(SELECT count(*) FROM sh_provider_receipts WHERE inbox_id=?) AS receipt_count '
            'FROM sh_provider_receipts WHERE inbox_id=? ORDER BY id DESC LIMIT 1', (row['id'], row['id'])).fetchone()
        latest = ({'receipt_id': receipt['id'], 'source_cursor': receipt['source_cursor'],
                   'source_attribution': receipt['attribution'],
                   'distribution_license_reference': receipt['distribution_reference'],
                   'received_at': receipt['received_at']} if receipt else None)
        out['items'].append({'inbox_id': row['id'], 'received_at': row['received_at'],
                             'event': json.loads(row['payload_json']), 'latest_receipt': latest,
                             'receipt_count': receipt['receipt_count'] if receipt else 0})
    out['next_cursor'] = rows[-1]['id'] if rows else after
    return out
