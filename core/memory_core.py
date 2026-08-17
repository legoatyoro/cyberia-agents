import sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime

DB = Path('.cyberia/memory_core.db')
_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        import os, logging
        os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
        logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
        logging.getLogger('huggingface_hub').setLevel(logging.ERROR)
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    return _MODEL


def get_embedding_model():
    return _get_model()


def _embed(text):
    try:
        return _get_model().encode(str(text)[:500]).tolist()
    except Exception:
        return []


def _init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT DEFAULT 'core',
            key TEXT,
            value TEXT,
            embedding TEXT,
            tags TEXT DEFAULT '[]',
            created_at TEXT,
            last_used_at TEXT,
            use_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_key ON memory_items(key);
        CREATE INDEX IF NOT EXISTS idx_source ON memory_items(source);
    ''')
    conn.commit()
    conn.close()


def migrate_from_legacy():
    _init()
    conn = sqlite3.connect(DB)
    migrated = 0
    try:
        hub_db = Path('.cyberia/memory_hub.db')
        if hub_db.exists():
            hub_conn = sqlite3.connect(hub_db)
            hub_conn.row_factory = sqlite3.Row
            for row in hub_conn.execute('SELECT * FROM conversation_memory'):
                row = dict(row)
                existing = conn.execute('SELECT id FROM memory_items WHERE key=?', (f'hub_{row["id"]}',)).fetchone()
                if not existing:
                    conn.execute(
                        'INSERT INTO memory_items (source, key, value, embedding, tags, created_at, last_used_at) VALUES (?,?,?,?,?,?,?)',
                        ('memory_hub', f'hub_{row["id"]}', row.get('content', ''), row.get('embedding', ''),
                         json.dumps([row.get('category', 'fact')]), row.get('created_at', datetime.now().isoformat()), datetime.now().isoformat())
                    )
                    migrated += 1
            hub_conn.close()
    except Exception as e:
        print(f'  [MIGRATION] Avertissement: {e}')
    conn.commit()
    conn.close()
    if migrated > 0:
        print(f'  [MEMORY_CORE] {migrated} items migres depuis memory_hub')
    return migrated


class MemoryCore:
    def __init__(self):
        _init()

    def save(self, key, value, tags=None, source='core'):
        import numpy as np
        _init()
        if tags is None:
            tags = []
        emb = _embed(value)
        conn = sqlite3.connect(DB)
        existing = conn.execute('SELECT id FROM memory_items WHERE key=? AND source=?', (key, source)).fetchone()
        now = datetime.now().isoformat()
        if existing:
            conn.execute(
                'UPDATE memory_items SET value=?, embedding=?, tags=?, last_used_at=? WHERE id=?',
                (value, json.dumps(emb), json.dumps(tags), now, existing[0])
            )
        else:
            conn.execute(
                'INSERT INTO memory_items (source, key, value, embedding, tags, created_at, last_used_at) VALUES (?,?,?,?,?,?,?)',
                (source, key, value, json.dumps(emb), json.dumps(tags), now, now)
            )
        conn.commit()
        conn.close()
        return key

    def get(self, key):
        _init()
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM memory_items WHERE key=?', (key,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def search(self, query, top_k=5, tags=None):
        import numpy as np
        _init()
        q_emb = np.array(_embed(query))
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM memory_items WHERE embedding IS NOT NULL AND embedding != "[]"').fetchall()
        conn.close()
        results = []
        for row in rows:
            row = dict(row)
            if tags:
                row_tags = json.loads(row.get('tags', '[]'))
                if not any(t in row_tags for t in tags):
                    continue
            try:
                emb = np.array(json.loads(row['embedding']))
                if len(emb) == 0:
                    continue
                sim = float(np.dot(q_emb, emb) / (np.linalg.norm(q_emb) * np.linalg.norm(emb) + 1e-9))
                results.append({**row, 'similarity': round(sim, 3)})
            except Exception:
                continue
        results.sort(key=lambda x: -x['similarity'])
        top = results[:top_k]
        if top:
            ids = [r['id'] for r in top]
            conn2 = sqlite3.connect(DB)
            conn2.execute(
                'UPDATE memory_items SET use_count = use_count + 1 WHERE id IN ({})'.format(
                    ','.join('?' * len(ids))),
                ids
            )
            conn2.commit()
            conn2.close()
        return top

    def stats(self):
        _init()
        conn = sqlite3.connect(DB)
        total = conn.execute('SELECT COUNT(*) FROM memory_items').fetchone()[0]
        by_source = dict(conn.execute('SELECT source, COUNT(*) FROM memory_items GROUP BY source').fetchall())
        conn.close()
        return {'total_items': total, 'by_source': by_source}


_core = None


def get_core():
    global _core
    if _core is None:
        _core = MemoryCore()
    return _core


def memory_engine_save(key, value, tags=None):
    return get_core().save(key, value, tags=tags or ['memory_engine'], source='memory_engine')


def memory_engine_search(query, top_k=5):
    return get_core().search(query, top_k=top_k, tags=['memory_engine'])


def learning_engine_log_correction(project_id, before, after):
    text = f'Correction {project_id}: {after[:200]}'
    return get_core().save(
        f'correction:{project_id}:{hashlib.md5(text.encode()).hexdigest()[:8]}',
        text, tags=['correction', 'learning_engine'], source='learning_engine'
    )


def learning_engine_get_stats():
    stats = get_core().stats()
    corrections = len(get_core().search('correction', top_k=100, tags=['correction']))
    return {'total_memories': stats['total_items'], 'corrections': corrections}
