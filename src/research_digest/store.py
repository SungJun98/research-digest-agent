"""Transactional SQLite state and a per-channel durable notification outbox."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .identity import aliases, merge_pair, merge_papers
from .models import Paper

SCHEMA = '''
CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY, paper_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS paper_delivery(paper_id TEXT, channel TEXT, notification_id TEXT, PRIMARY KEY(paper_id,channel));
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, subject TEXT, body TEXT, paper_ids TEXT, event_ids TEXT, local_day TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS deliveries(notification_id TEXT, channel TEXT, status TEXT DEFAULT 'pending', lease_until REAL DEFAULT 0, PRIMARY KEY(notification_id,channel));
CREATE TABLE IF NOT EXISTS delivery_units(notification_id TEXT, channel TEXT, unit TEXT, PRIMARY KEY(notification_id,channel,unit));
CREATE TABLE IF NOT EXISTS runs(kind TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS watch_cursors(id TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS watch_items(subject TEXT, item TEXT, PRIMARY KEY(subject,item));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, data TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cache(namespace TEXT, key TEXT, payload TEXT, PRIMARY KEY(namespace,key));
CREATE TABLE IF NOT EXISTS llm_usage(day TEXT PRIMARY KEY, count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS feedback(paper_id TEXT PRIMARY KEY, kind TEXT, topic_id TEXT, at TEXT);
'''


@dataclass
class Notification:
    id: str
    subject: str
    body: str
    pending_channels: list[str]
    paper_ids: list[str]
    event_ids: list[str]
    local_day: str | None
    kind: str


class Store:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _resolve(db, paper_id):
        row = db.execute('SELECT paper_id FROM aliases WHERE alias=?', (paper_id,)).fetchone()
        return row[0] if row else paper_id

    def resolve(self, paper_id: str) -> str:
        with self.connection() as db:
            return self._resolve(db, paper_id)

    def upsert_papers(self, papers: list[Paper]) -> None:
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._upsert_papers(db,papers)

    def ingest_mail(self, key: str, papers: list[Paper]) -> None:
        """Save candidates and acknowledge their UID in one transaction."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._upsert_papers(db,papers)
            db.execute('INSERT OR IGNORE INTO seen VALUES(?)',(key,))

    def _upsert_papers(self, db, papers):
        for paper in merge_papers(papers):
            known = set()
            for alias in aliases(paper):
                row = db.execute('SELECT paper_id FROM aliases WHERE alias=?', (alias,)).fetchone()
                if row:
                    known.add(row[0])
            root = sorted(known)[0] if known else paper.canonical_id
            combined = paper
            for old in sorted(known):
                row = db.execute('SELECT data FROM papers WHERE id=?', (old,)).fetchone()
                if row:
                    combined = merge_pair(Paper.model_validate_json(row[0]), combined)
                if old != root:
                    db.execute('INSERT OR IGNORE INTO paper_delivery SELECT ?,channel,notification_id FROM paper_delivery WHERE paper_id=?', (root, old))
                    db.execute('DELETE FROM paper_delivery WHERE paper_id=?', (old,))
                    db.execute('INSERT OR IGNORE INTO watch_items SELECT subject,? FROM watch_items WHERE item=?', (root, old))
                    db.execute('DELETE FROM watch_items WHERE item=?', (old,))
                    latest = db.execute('SELECT kind,topic_id,at FROM feedback WHERE paper_id IN (?,?) ORDER BY at DESC LIMIT 1', (root, old)).fetchone()
                    if latest:
                        db.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)', (root, *latest))
                    db.execute('DELETE FROM feedback WHERE paper_id=?', (old,))
                    db.execute('UPDATE aliases SET paper_id=? WHERE paper_id=?', (root, old))
                    db.execute('DELETE FROM papers WHERE id=?', (old,))
            db.execute('INSERT OR REPLACE INTO papers VALUES(?,?)', (root, combined.model_dump_json()))
            for alias in aliases(combined) | aliases(paper):
                db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)', (alias, root))


    def list_papers(self) -> list[Paper]:
        with self.connection() as db:
            return [Paper.model_validate_json(r[0]) for r in db.execute('SELECT data FROM papers ORDER BY id')]

    def get_paper(self, paper_id: str) -> Paper | None:
        with self.connection() as db:
            row = db.execute('SELECT data FROM papers WHERE id=?', (self._resolve(db, paper_id),)).fetchone()
            return Paper.model_validate_json(row[0]) if row else None

    def seen(self, key: str) -> bool:
        with self.connection() as db:
            return db.execute('SELECT 1 FROM seen WHERE id=?', (key,)).fetchone() is not None

    def mark_seen(self, key: str) -> None:
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO seen VALUES(?)', (key,))

    def paper_delivered(self, paper_id: str, channel: str | None = None) -> bool:
        with self.connection() as db:
            sql = 'SELECT 1 FROM paper_delivery WHERE paper_id=?'
            args = [self._resolve(db, paper_id)]
            if channel:
                sql += ' AND channel=?'
                args.append(channel)
            return db.execute(sql, args).fetchone() is not None

    def mark_paper_delivered(self, paper_id: str, channel: str, notification_id: str) -> None:
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO paper_delivery VALUES(?,?,?)', (self._resolve(db, paper_id), channel, notification_id))

    def create_notification(self, key: str, subject: str, body: str, channels: list[str], paper_ids: list[str] | None = None, event_ids: list[str] | None = None, local_day: str | None = None, kind: str = 'digest') -> None:
        with self.connection() as db:
            cursor = db.execute('INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,?,?)', (key, subject, body, json.dumps(paper_ids or []), json.dumps(event_ids or []), local_day, kind))
            if cursor.rowcount:
                for channel in channels:
                    db.execute('INSERT INTO deliveries(notification_id,channel) VALUES(?,?)', (key, channel))

    def create_notifications(self, entries: list[dict]) -> None:
        """Atomically save every channel's immutable daily payload before any send."""
        with self.connection() as db:
            for entry in entries:
                cursor = db.execute('INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,?,?)',
                    (entry['key'],entry['subject'],entry['body'],json.dumps(entry.get('paper_ids',[])),json.dumps(entry.get('event_ids',[])),entry.get('local_day'),entry.get('kind','digest')))
                if cursor.rowcount:
                    for channel in entry['channels']:
                        db.execute('INSERT INTO deliveries(notification_id,channel) VALUES(?,?)',(entry['key'],channel))

    def pending_notifications(self) -> list[Notification]:
        with self.connection() as db:
            result = []
            for row in db.execute("SELECT * FROM notifications WHERE id IN (SELECT notification_id FROM deliveries WHERE status!='delivered') ORDER BY rowid"):
                channels = [r[0] for r in db.execute("SELECT channel FROM deliveries WHERE notification_id=? AND status!='delivered' ORDER BY channel", (row['id'],))]
                result.append(Notification(row['id'], row['subject'], row['body'], channels, json.loads(row['paper_ids']), json.loads(row['event_ids']), row['local_day'], row['kind']))
            return result

    def pending_paper_ids(self, channel: str) -> set[str]:
        with self.connection() as db:
            rows = db.execute("SELECT n.paper_ids FROM notifications n JOIN deliveries d ON n.id=d.notification_id WHERE d.channel=? AND d.status!='delivered'", (channel,))
            return {self._resolve(db,paper_id) for row in rows for paper_id in json.loads(row[0])}

    def delivery_unit_done(self, key: str, channel: str, unit: str) -> bool:
        with self.connection() as db:
            return db.execute('SELECT 1 FROM delivery_units WHERE notification_id=? AND channel=? AND unit=?',(key,channel,unit)).fetchone() is not None

    def mark_delivery_unit(self, key: str, channel: str, unit: str) -> None:
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO delivery_units VALUES(?,?,?)',(key,channel,unit))

    def reserve_delivery(self, key: str, channel: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor = db.execute("UPDATE deliveries SET status='sending',lease_until=? WHERE notification_id=? AND channel=? AND (status='pending' OR (status='sending' AND lease_until<=?))", (now+300, key, channel, now))
            return cursor.rowcount == 1

    def mark_failed(self, key: str, channel: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE deliveries SET status='pending',lease_until=0 WHERE notification_id=? AND channel=?", (key, channel))

    def was_delivered(self, key: str, channel: str) -> bool:
        with self.connection() as db:
            row = db.execute('SELECT status FROM deliveries WHERE notification_id=? AND channel=?', (key, channel)).fetchone()
            return bool(row and row[0] == 'delivered')

    def mark_delivered(self, key: str, channel: str) -> None:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO deliveries VALUES(?,?,'delivered',0)", (key, channel))
            row = db.execute('SELECT paper_ids,event_ids FROM notifications WHERE id=?', (key,)).fetchone()
            if row:
                for paper_id in json.loads(row[0]):
                    db.execute('INSERT OR IGNORE INTO paper_delivery VALUES(?,?,?)', (self._resolve(db, paper_id), channel, key))
                remaining = db.execute("SELECT 1 FROM deliveries WHERE notification_id=? AND status!='delivered'", (key,)).fetchone()
                if not remaining:
                    for event_id in json.loads(row[1]):
                        db.execute('UPDATE events SET done=1 WHERE id=?', (event_id,))

    def notification_complete(self, key: str) -> bool:
        with self.connection() as db:
            exists = db.execute('SELECT 1 FROM notifications WHERE id=?', (key,)).fetchone()
            remaining = db.execute("SELECT 1 FROM deliveries WHERE notification_id=? AND status!='delivered'", (key,)).fetchone()
            return bool(exists and not remaining)

    def last_success(self, kind: str) -> str | None:
        with self.connection() as db:
            row = db.execute('SELECT value FROM runs WHERE kind=?', (kind,)).fetchone()
            return row[0] if row else None

    def set_last_success(self, kind: str, value: str | datetime | date) -> None:
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES(?,?)', (kind, value if isinstance(value, str) else value.isoformat()))

    def get_watch_cursor(self, key: str) -> str | None:
        with self.connection() as db:
            row = db.execute('SELECT value FROM watch_cursors WHERE id=?', (key,)).fetchone()
            return row[0] if row else None

    def set_watch_cursor(self, key: str, value: str) -> None:
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO watch_cursors VALUES(?,?)', (key, value))

    def watch_item_seen(self, subject: str, item: str) -> bool:
        with self.connection() as db:
            return db.execute('SELECT 1 FROM watch_items WHERE subject=? AND item=?', (subject, self._resolve(db,item))).fetchone() is not None

    def mark_watch_item_seen(self, subject: str, item: str) -> None:
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO watch_items VALUES(?,?)', (subject, self._resolve(db,item)))

    def queue_event(self, key: str, event) -> None:
        data = event.model_dump_json() if hasattr(event, 'model_dump_json') else json.dumps(event)
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO events(id,data) VALUES(?,?)', (key, data))

    def pending_events(self) -> list[dict]:
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM events WHERE done=0 ORDER BY rowid')]

    def finish_event(self, key: str) -> None:
        with self.connection() as db:
            db.execute('UPDATE events SET done=1 WHERE id=?', (key,))

    def immediate_count(self, local_day: str) -> int:
        with self.connection() as db:
            return db.execute("SELECT COUNT(*) FROM notifications WHERE kind='immediate' AND local_day=?", (local_day,)).fetchone()[0]

    def reserve_llm_request(self, day: str, limit: int) -> bool:
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO llm_usage VALUES(?,0)', (day,))
            return db.execute('UPDATE llm_usage SET count=count+1 WHERE day=? AND count<?', (day, limit)).rowcount == 1

    def llm_requests_today(self, day: str) -> int:
        with self.connection() as db:
            row = db.execute('SELECT count FROM llm_usage WHERE day=?', (day,)).fetchone()
            return row[0] if row else 0

    def get_cache(self, namespace: str, key: str) -> dict | None:
        with self.connection() as db:
            row = db.execute('SELECT payload FROM cache WHERE namespace=? AND key=?', (namespace, key)).fetchone()
            return json.loads(row[0]) if row else None

    def put_cache(self, namespace: str, key: str, payload: dict) -> None:
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)', (namespace, key, json.dumps(payload)))

    def record_feedback(self, paper_id: str, kind: str, topic_id: str | None, now: datetime) -> None:
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)', (self._resolve(db, paper_id), kind, topic_id, now.isoformat()))

    def list_feedback(self) -> list[dict]:
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM feedback ORDER BY at')]

    def snapshot_counts(self, exclude: set[str] | None = None) -> dict[str, int]:
        tables = ['papers', 'seen', 'paper_delivery', 'notifications', 'deliveries', 'delivery_units', 'runs', 'watch_cursors', 'watch_items', 'events', 'cache', 'llm_usage', 'feedback']
        with self.connection() as db:
            return {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables if t not in (exclude or set())}
