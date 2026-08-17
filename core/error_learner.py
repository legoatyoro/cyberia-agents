import sqlite3, hashlib
from pathlib import Path
from datetime import datetime

DB = Path('.cyberia/error_patterns.db')


def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS error_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_hash TEXT UNIQUE,
            error_type TEXT,
            error_snippet TEXT,
            fix_applied TEXT,
            stack TEXT,
            success_count INTEGER DEFAULT 1,
            fail_count INTEGER DEFAULT 0,
            created_at TEXT,
            last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS generation_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson TEXT UNIQUE,
            stack TEXT,
            severity TEXT,
            learned_at TEXT,
            apply_count INTEGER DEFAULT 0
        );
    ''')
    conn.commit()
    conn.close()
    init_default_lessons()


def learn_from_error(error_snippet, fix_applied, stack='python', worked=True):
    init()
    h = hashlib.md5(error_snippet[:200].encode()).hexdigest()
    conn = sqlite3.connect(DB)
    existing = conn.execute(
        'SELECT id, success_count, fail_count FROM error_patterns WHERE error_hash=?', (h,)
    ).fetchone()
    if existing:
        if worked:
            conn.execute(
                'UPDATE error_patterns SET success_count=success_count+1, last_seen=?, fix_applied=? WHERE id=?',
                (datetime.now().isoformat(), fix_applied, existing[0])
            )
        else:
            conn.execute(
                'UPDATE error_patterns SET fail_count=fail_count+1, last_seen=? WHERE id=?',
                (datetime.now().isoformat(), existing[0])
            )
    else:
        error_type = (
            'import' if 'ImportError' in error_snippet or 'ModuleNotFound' in error_snippet else
            'syntax' if 'SyntaxError' in error_snippet else
            'type' if 'TypeError' in error_snippet else
            'runtime'
        )
        conn.execute(
            'INSERT INTO error_patterns (error_hash, error_type, error_snippet, fix_applied, stack, created_at, last_seen) VALUES (?,?,?,?,?,?,?)',
            (h, error_type, error_snippet[:500], fix_applied, stack,
             datetime.now().isoformat(), datetime.now().isoformat())
        )
    conn.commit()
    conn.close()


def add_lesson(lesson, stack='all', severity='high'):
    init_db_only()
    conn = sqlite3.connect(DB)
    conn.execute(
        'INSERT OR IGNORE INTO generation_lessons (lesson, stack, severity, learned_at) VALUES (?,?,?,?)',
        (lesson, stack, severity, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def init_db_only():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS error_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_hash TEXT UNIQUE,
            error_type TEXT,
            error_snippet TEXT,
            fix_applied TEXT,
            stack TEXT,
            success_count INTEGER DEFAULT 1,
            fail_count INTEGER DEFAULT 0,
            created_at TEXT,
            last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS generation_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson TEXT UNIQUE,
            stack TEXT,
            severity TEXT,
            learned_at TEXT,
            apply_count INTEGER DEFAULT 0
        );
    ''')
    conn.commit()
    conn.close()


def get_lessons_for_stack(stack):
    init_db_only()
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        'SELECT lesson FROM generation_lessons WHERE stack=? OR stack="all" ORDER BY apply_count DESC LIMIT 10',
        (stack,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_fix_for_error(error_snippet):
    init_db_only()
    h = hashlib.md5(error_snippet[:200].encode()).hexdigest()
    conn = sqlite3.connect(DB)
    row = conn.execute(
        'SELECT fix_applied FROM error_patterns WHERE error_hash=? AND success_count > fail_count', (h,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_stats():
    init_db_only()
    conn = sqlite3.connect(DB)
    patterns = conn.execute('SELECT COUNT(*) FROM error_patterns').fetchone()[0]
    lessons = conn.execute('SELECT COUNT(*) FROM generation_lessons').fetchone()[0]
    top_errors = conn.execute(
        'SELECT error_type, COUNT(*) as c FROM error_patterns GROUP BY error_type ORDER BY c DESC LIMIT 5'
    ).fetchall()
    conn.close()
    return {'patterns': patterns, 'lessons': lessons, 'top_errors': dict(top_errors)}


LESSONS_DJANGO = [
    'Verifier ROOT_URLCONF pointe vers config/urls.py et non app_name/urls.py',
    'AUTH_USER_MODEL ne peut etre defini que dans une seule app - jamais duplique',
    'Toutes les apps avec models.py doivent etre dans INSTALLED_APPS',
    'Ne jamais injecter pattern FastAPI dans un projet Django',
]
LESSONS_FASTAPI = [
    'Toujours ajouter uvicorn.run if __name__ == __main__ dans main.py',
    'Python 3.14 incompatible Jinja2 - utiliser f-strings HTMLResponse',
    'declarative_base depuis sqlalchemy.orm pas ext.declarative',
]
LESSONS_GENERAL = [
    'node_modules exclu de tous les rglob et scans de fichiers',
    'requirements.txt jamais de modules locaux comme packages pip',
    'subprocess Windows toujours bytes decode utf-8 errors replace',
    'python-decouple et jamais decouple seul',
    'Score projets uniquement via metrics_manager.compute_score avec project_dir',
]

_lessons_initialized = False


def init_default_lessons():
    global _lessons_initialized
    if _lessons_initialized:
        return
    _lessons_initialized = True
    init_db_only()
    conn = sqlite3.connect(DB)
    for lesson in LESSONS_DJANGO:
        conn.execute(
            'INSERT OR IGNORE INTO generation_lessons (lesson, stack, severity, learned_at) VALUES (?,?,?,?)',
            (lesson, 'django', 'critical', datetime.now().isoformat())
        )
    for lesson in LESSONS_FASTAPI:
        conn.execute(
            'INSERT OR IGNORE INTO generation_lessons (lesson, stack, severity, learned_at) VALUES (?,?,?,?)',
            (lesson, 'fastapi', 'critical', datetime.now().isoformat())
        )
    for lesson in LESSONS_GENERAL:
        conn.execute(
            'INSERT OR IGNORE INTO generation_lessons (lesson, stack, severity, learned_at) VALUES (?,?,?,?)',
            (lesson, 'all', 'high', datetime.now().isoformat())
        )
    conn.commit()
    conn.close()
