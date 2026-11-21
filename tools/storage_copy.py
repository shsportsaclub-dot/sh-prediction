"""Explicit SQLite snapshot for storage cutover; never starts/stops the application.

Use SQLite backup (including committed WAL), validate, then publish without overwrite.
A snapshot is point-in-time evidence, not proof that writers stopped or cutover completed.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time


def _readonly(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)


def _counts(c):
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {name: c.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
            for name in tables}


def copy_database(source, destination, *, mount_root=None):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if not source.is_file():
        raise ValueError('source must be an existing database file')
    if any(os.path.lexists(str(destination) + suffix) for suffix in ('', '-wal', '-shm', '-journal')):
        raise FileExistsError('destination or database sidecar already exists')
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if mount_root is not None:
        mount_root = Path(mount_root).resolve(strict=True)
        if not os.path.ismount(mount_root) or mount_root == Path('/'):
            raise ValueError('destination mount is not a dedicated mounted filesystem')
        if not destination.is_relative_to(mount_root):
            raise ValueError('destination must be inside the specified mount')
    fd, staging = tempfile.mkstemp(prefix='.sh-storage-', suffix='.sqlite3', dir=parent)
    os.close(fd)  # mkstemp gives the snapshot owner-only permissions.
    deadline = time.monotonic() + 60

    def progress(*_):
        if time.monotonic() > deadline:
            raise TimeoutError('snapshot exceeded 60 seconds; destination not published')

    try:
        with closing(_readonly(source)) as src, closing(sqlite3.connect(staging)) as dst:
            # Pin counts and backup to one read snapshot even when upstream writers commit.
            src.execute('BEGIN')
            counts = _counts(src)
            src.backup(dst, pages=256, progress=progress, sleep=.05)
            dst.execute('PRAGMA journal_mode=DELETE')
            integrity = [r[0] for r in dst.execute('PRAGMA integrity_check')]
            if integrity != ['ok'] or _counts(dst) != counts:
                raise RuntimeError('snapshot verification failed')
        # Reopen independently before publishing; verify persisted bytes, not a cached connection.
        with closing(_readonly(Path(staging))) as restored:
            if _counts(restored) != counts:
                raise RuntimeError('reopened snapshot verification failed')
        with open(staging, 'rb') as persisted:
            digest = hashlib.file_digest(persisted, 'sha256').hexdigest()
            os.fsync(persisted.fileno())
        # Hard-link publication is atomic and refuses an existing destination (including symlinks).
        os.link(staging, destination)
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return {'integrity': 'ok', 'row_counts': counts, 'sha256': digest,
                'bytes': destination.stat().st_size, 'destination': str(destination),
                'mount_checked': mount_root is not None, 'production_cutover_verified': False}
    finally:
        os.unlink(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--mount-root', help='require destination beneath this actual disk mount')
    mode.add_argument('--snapshot-only', action='store_true', help='local/offline snapshot; makes no persistence claim')
    args = parser.parse_args()
    try:
        result = copy_database(args.source, args.destination, mount_root=args.mount_root)
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        parser.exit(1, type(exc).__name__ + ': ' + str(exc) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
