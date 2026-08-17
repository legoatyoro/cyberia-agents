import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime

DB_PATH = Path('.cyberia/memory.db')


def init_memory():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS error_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_hash TEXT UNIQUE,
            error_snippet TEXT,
            error_type TEXT,
            fix_applied TEXT,
            fix_worked INTEGER DEFAULT 0,
            occurrences INTEGER DEFAULT 1,
            last_seen TEXT,
            project_type TEXT
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            projects_created TEXT,
            errors_fixed INTEGER,
            agents_created TEXT,
            duration_minutes REAL,
            key_learnings TEXT
        );
        CREATE TABLE IF NOT EXISTS generation_stats (
            project_name TEXT PRIMARY KEY,
            project_type TEXT,
            files_count INTEGER,
            score REAL,
            errors_count INTEGER,
            auto_fixes INTEGER,
            created_at TEXT,
            stack TEXT
        );
    ''')
    conn.commit()
    conn.close()


def record_error(error_snippet: str, error_type: str, fix: str, worked: bool, project_type: str = ''):
    init_memory()
    error_hash = hashlib.md5(error_snippet[:200].encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute('SELECT id, occurrences FROM error_patterns WHERE error_hash=?', (error_hash,)).fetchone()
    if existing:
        conn.execute('''UPDATE error_patterns SET
            occurrences=occurrences+1, last_seen=?, fix_applied=?, fix_worked=?
            WHERE error_hash=?''',
            (datetime.now().isoformat(), fix, 1 if worked else 0, error_hash))
    else:
        conn.execute('''INSERT INTO error_patterns
            (error_hash, error_snippet, error_type, fix_applied, fix_worked, last_seen, project_type)
            VALUES (?,?,?,?,?,?,?)''',
            (error_hash, error_snippet[:500], error_type, fix, 1 if worked else 0,
             datetime.now().isoformat(), project_type))
    conn.commit()
    conn.close()


def find_known_fix(error_snippet: str) -> dict | None:
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    error_hash = hashlib.md5(error_snippet[:200].encode()).hexdigest()
    row = conn.execute(
        'SELECT * FROM error_patterns WHERE error_hash=? AND fix_worked=1',
        (error_hash,)
    ).fetchone()
    if not row:
        for word in error_snippet.split()[:5]:
            if len(word) > 5:
                row = conn.execute(
                    'SELECT * FROM error_patterns WHERE error_snippet LIKE ? AND fix_worked=1 ORDER BY occurrences DESC LIMIT 1',
                    (f'%{word}%',)
                ).fetchone()
                if row:
                    break
    conn.close()
    return dict(row) if row else None


def set_preference(key: str, value: str):
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?,?,?)',
                 (key, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_preference(key: str, default: str = '') -> str:
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT value FROM user_preferences WHERE key=?', (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def record_generation(project_name: str, project_type: str, files: int, score: float,
                      errors: int, fixes: int, stack: str = ''):
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''INSERT OR REPLACE INTO generation_stats
        (project_name, project_type, files_count, score, errors_count, auto_fixes, created_at, stack)
        VALUES (?,?,?,?,?,?,?,?)''',
        (project_name, project_type, files, score, errors, fixes,
         datetime.now().isoformat(), stack))
    conn.commit()
    conn.close()


def get_stats_summary() -> dict:
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute('SELECT COUNT(*) FROM generation_stats').fetchone()[0]
    avg_score = conn.execute('SELECT AVG(score) FROM generation_stats').fetchone()[0] or 0
    total_errors = conn.execute('SELECT SUM(errors_count) FROM generation_stats').fetchone()[0] or 0
    total_fixes = conn.execute('SELECT SUM(auto_fixes) FROM generation_stats').fetchone()[0] or 0
    known_patterns = conn.execute('SELECT COUNT(*) FROM error_patterns WHERE fix_worked=1').fetchone()[0]
    conn.close()
    return {
        'total_projects': total,
        'avg_score': round(avg_score, 1),
        'total_errors_seen': total_errors,
        'total_auto_fixes': total_fixes,
        'known_fix_patterns': known_patterns,
    }


def suggest_improvements(project_type: str) -> list:
    init_memory()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''SELECT error_type, fix_applied, occurrences
        FROM error_patterns
        WHERE project_type=? AND fix_worked=1
        ORDER BY occurrences DESC LIMIT 5''', (project_type,)).fetchall()
    conn.close()
    return [{'error': r[0], 'fix': r[1], 'seen': r[2]} for r in rows]


def get_combined_stats() -> dict:
    """Façade principale — fusionne memory_engine + learning_engine."""
    stats = get_stats_summary()
    try:
        from core.learning_engine import get_learning_stats
        ls = get_learning_stats()
        stats['workshop_sessions'] = ls.get('workshop_sessions', 0)
        stats['successful_generations'] = ls.get('successful_generations', 0)
        stats['known_fix_patterns'] = max(
            stats.get('known_fix_patterns', 0),
            ls.get('known_fix_patterns', 0),
        )
    except Exception:
        pass
    return stats
