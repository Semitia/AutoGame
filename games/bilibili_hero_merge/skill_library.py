"""Shared local skill knowledge. SQLite transactions support both coop workers."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'config/hero-skills.sqlite3'


class SkillLibrary:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('CREATE TABLE IF NOT EXISTS heroes (name TEXT PRIMARY KEY, definition TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS skills (hero TEXT, title TEXT, PRIMARY KEY(hero,title))')
        db.execute('CREATE TABLE IF NOT EXISTS preferences (hero TEXT PRIMARY KEY, ordering TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS observations (hero TEXT, text TEXT, PRIMARY KEY(hero,text))')
        db.execute('CREATE TABLE IF NOT EXISTS claims (text TEXT PRIMARY KEY, hero TEXT, title TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS returned_skills (hero TEXT, title TEXT, PRIMARY KEY(hero,title))')
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, name, skills, preference=False):
        if not name:
            return
        skills = list(dict.fromkeys(s.strip() for s in skills if s.strip()))
        with self.connect() as db:
            db.executemany('INSERT OR IGNORE INTO skills SELECT ?,? WHERE NOT EXISTS (SELECT 1 FROM returned_skills WHERE hero=? AND title=?)', [(name,s,name,s) for s in skills])
            if preference:
                returned={r[0] for r in db.execute('SELECT title FROM returned_skills WHERE hero=?',(name,))}
                skills=[s for s in skills if s not in returned]
                db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', (name,json.dumps(skills)))

    def migrate_legacy_claims(self):
        """Link pre-feature confirmations only on an exact, unambiguous title."""
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS library_migrations (name TEXT PRIMARY KEY)')
            if db.execute('SELECT 1 FROM library_migrations WHERE name=\'claims-v1\'').fetchone():return
            owners={}
            for hero,title in db.execute('SELECT hero,title FROM skills'):
                owners.setdefault(title,set()).add(hero)
            for suggested,raw in db.execute('SELECT hero,text FROM observations').fetchall():
                title=raw.split()[0] if raw.split() else ''
                candidates=owners.get(title,set())
                if len(candidates)!=1:continue
                hero=next(iter(candidates))
                if suggested not in ('',hero):continue
                db.execute('INSERT OR IGNORE INTO claims VALUES (?,?,?)',(raw,hero,title))
            db.execute('INSERT INTO library_migrations VALUES (\'claims-v1\')')

    def preferred(self, name):
        with self.connect() as db:
            row = db.execute('SELECT ordering FROM preferences WHERE hero=?', (name,)).fetchone()
        return json.loads(row[0]) if row else self.choices(name)

    def choices(self, name):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT title FROM skills WHERE hero=? ORDER BY rowid', (name,))]

    def observations(self, name):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT text FROM observations o WHERE (hero=? OR hero=\'\') AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.text=o.text) GROUP BY text ORDER BY MAX(rowid) DESC LIMIT 100', (name,))]

    def claim(self, name, title, raw=None):
        """Claim a raw card globally; repeated recognition cannot re-list it."""
        name,title=name.strip(),title.strip()
        if not name or not title:raise ValueError('Hero and skill title are required')
        raw=raw or title
        with self.connect() as db:
            existing=db.execute('SELECT hero,title FROM claims WHERE text=?',(raw,)).fetchone()
            if existing and existing!=(name,title):raise ValueError('该记录已被认领，请先退回未认领池')
            db.execute('INSERT OR IGNORE INTO observations VALUES (?,?)',('',raw))
            db.execute('DELETE FROM returned_skills WHERE hero=? AND title=?',(name,title))
            db.execute('INSERT OR IGNORE INTO skills VALUES (?,?)',(name,title))
            db.execute('INSERT OR REPLACE INTO claims VALUES (?,?,?)',(raw,name,title))

    def unclaim(self, name, title):
        with self.connect() as db:
            rows=db.execute('SELECT text FROM claims WHERE hero=? AND title=?',(name,title)).fetchall()
            # Legacy/manual skills have no raw-card link. Keep at least their
            # exact title available for reassignment instead of losing them.
            for (raw,) in rows or [(title,)]:
                db.execute('INSERT OR IGNORE INTO observations VALUES (?,?)',('',raw))
            db.execute('DELETE FROM claims WHERE hero=? AND title=?',(name,title))
            db.execute('DELETE FROM skills WHERE hero=? AND title=?',(name,title))
            db.execute('INSERT OR IGNORE INTO returned_skills VALUES (?,?)',(name,title))
            row=db.execute('SELECT ordering FROM preferences WHERE hero=?',(name,)).fetchone()
            if row:
                db.execute('UPDATE preferences SET ordering=? WHERE hero=?',
                           (json.dumps([s for s in json.loads(row[0]) if s!=title]),name))

    def add_hero(self, definition):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO heroes VALUES (?,?)', (definition['name'],json.dumps(definition)))

    def definitions(self):
        import hashlib
        with self.connect() as db:
            return {'custom_'+hashlib.sha256(name.encode()).hexdigest()[:12]: json.loads(value)
                    for name,value in db.execute('SELECT name,definition FROM heroes')}

    def seed(self, profile, catalog):
        catalog = dict(catalog, **profile.get('hero_definitions', {}))
        for definition in profile.get('hero_definitions', {}).values():
            self.add_hero(definition)
        for slot in profile.get('slots', []):
            name = catalog.get(slot.get('hero'), {}).get('name')
            self.remember(name, slot.get('buff_order', []))

    def record(self, cards, heroes):
        with self.connect() as db:
            for text in cards:
                if not text.strip():
                    continue
                # Exact hero names only. Generic words like ice/sword are ambiguous.
                matches = {h['name'] for h in heroes.values() if h['name'] in text}
                name = next(iter(matches)) if len(matches) == 1 else ''
                db.execute('INSERT OR IGNORE INTO observations VALUES (?,?)', (name,text))


def record_cards(cards, config):
    try:
        SkillLibrary().record(cards, config['heroes'])
    except (OSError, sqlite3.Error):
        # Optional knowledge collection must never interrupt the battle controller.
        pass
