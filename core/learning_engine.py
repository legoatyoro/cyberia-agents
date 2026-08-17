import sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime

DB = Path('.cyberia/memory.db')

def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS fix_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_signature TEXT UNIQUE,
            error_type TEXT,
            fix_code TEXT,
            fix_description TEXT,
            success_count INTEGER DEFAULT 1,
            fail_count INTEGER DEFAULT 0,
            last_used TEXT,
            project_types TEXT
        );
        CREATE TABLE IF NOT EXISTS workshop_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            agent_name TEXT,
            discussion TEXT,
            applied_fixes TEXT,
            session_date TEXT
        );
        CREATE TABLE IF NOT EXISTS generation_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            project_type TEXT,
            error_encountered TEXT,
            fix_applied TEXT,
            server_started INTEGER DEFAULT 0,
            score_before REAL,
            score_after REAL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS knowledge_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            content TEXT,
            source TEXT,
            created_at TEXT,
            times_used INTEGER DEFAULT 0
        );
    ''')
    conn.commit()
    conn.close()

def record_fix_success(error_text: str, error_type: str, fix_code: str, fix_desc: str, project_type: str = ''):
    init()
    sig = hashlib.md5(error_text[:200].encode()).hexdigest()
    conn = sqlite3.connect(DB)
    existing = conn.execute('SELECT id, success_count FROM fix_patterns WHERE error_signature=?', (sig,)).fetchone()
    if existing:
        conn.execute('UPDATE fix_patterns SET success_count=success_count+1, last_used=? WHERE id=?',
                    (datetime.now().isoformat(), existing[0]))
    else:
        conn.execute('INSERT INTO fix_patterns (error_signature, error_type, fix_code, fix_description, last_used, project_types) VALUES (?,?,?,?,?,?)',
                    (sig, error_type, fix_code[:2000], fix_desc, datetime.now().isoformat(), project_type))
    conn.commit()
    conn.close()

def find_known_fix(error_text: str) -> dict | None:
    init()
    sig = hashlib.md5(error_text[:200].encode()).hexdigest()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM fix_patterns WHERE error_signature=? AND success_count > 0 ORDER BY success_count DESC LIMIT 1', (sig,)).fetchone()
    if not row:
        words = [w for w in error_text.split() if len(w) > 6][:3]
        for word in words:
            row = conn.execute('SELECT * FROM fix_patterns WHERE error_type LIKE ? AND success_count > fail_count ORDER BY success_count DESC LIMIT 1', (f'%{word}%',)).fetchone()
            if row: break
    conn.close()
    return dict(row) if row else None

def save_workshop_session(project_name: str, agent_name: str, discussion: str, fixes: list):
    init()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO workshop_memory (project_name, agent_name, discussion, applied_fixes, session_date) VALUES (?,?,?,?,?)',
                (project_name, agent_name, discussion[:3000], json.dumps(fixes), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_workshop_history(project_name: str) -> list:
    init()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM workshop_memory WHERE project_name=? ORDER BY session_date DESC LIMIT 10', (project_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def record_generation_feedback(project_name: str, project_type: str, error: str, fix: str, started: bool, score_before: float, score_after: float):
    init()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO generation_feedback (project_name, project_type, error_encountered, fix_applied, server_started, score_before, score_after, created_at) VALUES (?,?,?,?,?,?,?,?)',
                (project_name, project_type, error[:500], fix[:500], 1 if started else 0, score_before, score_after, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    if started and score_after > score_before:
        record_fix_success(error, 'generation', fix, f'Fix qui a permis de passer de {score_before} à {score_after}/10', project_type)

def get_learning_stats() -> dict:
    init()
    conn = sqlite3.connect(DB)
    patterns = conn.execute('SELECT COUNT(*) FROM fix_patterns WHERE success_count > 0').fetchone()[0]
    sessions = conn.execute('SELECT COUNT(*) FROM workshop_memory').fetchone()[0]
    feedbacks = conn.execute('SELECT COUNT(*) FROM generation_feedback WHERE server_started=1').fetchone()[0]
    conn.close()
    return {'known_fix_patterns': patterns, 'workshop_sessions': sessions, 'successful_generations': feedbacks}

def add_knowledge(topic: str, content: str, source: str = 'CYBERIA'):
    init()
    conn = sqlite3.connect(DB)
    existing = conn.execute('SELECT id FROM knowledge_updates WHERE topic=?', (topic,)).fetchone()
    if existing:
        conn.execute('UPDATE knowledge_updates SET content=?, times_used=times_used+1 WHERE id=?', (content[:2000], existing[0]))
    else:
        conn.execute('INSERT INTO knowledge_updates (topic, content, source, created_at) VALUES (?,?,?,?)',
                    (topic, content[:2000], source, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_relevant_knowledge(query: str) -> list:
    init()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    words = [w for w in query.lower().split() if len(w) > 4][:3]
    results = []
    for word in words:
        rows = conn.execute('SELECT topic, content FROM knowledge_updates WHERE topic LIKE ? OR content LIKE ? ORDER BY times_used DESC LIMIT 2', (f'%{word}%', f'%{word}%')).fetchall()
        results.extend([dict(r) for r in rows])
    conn.close()
    return results[:5]
