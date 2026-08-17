import sqlite3, json
from pathlib import Path
from datetime import datetime

KB_PATH = Path('.cyberia/knowledge_base.db')

def init_kb():
    KB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(KB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tech TEXT NOT NULL,
            version TEXT,
            pattern_type TEXT,
            snippet TEXT,
            description TEXT,
            success_rate REAL DEFAULT 1.0,
            times_used INTEGER DEFAULT 0,
            times_failed INTEGER DEFAULT 0,
            source TEXT DEFAULT 'generated',
            created_at TEXT,
            last_used TEXT
        );
        CREATE TABLE IF NOT EXISTS relations (
            pattern_id INTEGER,
            related_id INTEGER,
            relation_type TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id),
            FOREIGN KEY(related_id) REFERENCES patterns(id)
        );
        CREATE TABLE IF NOT EXISTS cyberia_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text TEXT UNIQUE,
            rule_type TEXT,
            applies_to TEXT,
            confidence REAL DEFAULT 0.5,
            origin TEXT,
            created_at TEXT,
            validated INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger TEXT,
            analysis TEXT,
            proposals TEXT,
            applied INTEGER DEFAULT 0,
            created_at TEXT
        );
    ''')
    _seed_initial_patterns(conn)
    conn.commit()
    conn.close()

def _seed_initial_patterns(conn):
    initial = [
        ('fastapi', '0.100+', 'startup', 'uvicorn.run(app, host="0.0.0.0", port=8000)', 'Démarrage FastAPI sans reload', 'hardcoded'),
        ('fastapi', '0.100+', 'html_response', 'from fastapi.responses import HTMLResponse\nreturn HTMLResponse(html_content)', 'Jamais Jinja2 sur Python 3.14+', 'hardcoded'),
        ('sqlalchemy', '2.0', 'base', 'from sqlalchemy.orm import declarative_base\nBase = declarative_base()', 'Import correct SQLAlchemy 2.0', 'hardcoded'),
        ('sqlalchemy', '2.0', 'session', 'SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)', 'Session factory correcte', 'hardcoded'),
        ('django', '4.0+', 'decouple', 'pip install python-decouple\nfrom decouple import config', 'TOUJOURS python-decouple pas decouple', 'hardcoded'),
        ('python', '3.14', 'subprocess', 'subprocess.Popen([...], stdout=PIPE, stderr=PIPE)\nline.decode("utf-8", errors="replace")', 'Toujours bytes + decode sur Windows', 'hardcoded'),
    ]
    for tech, ver, ptype, snippet, desc, source in initial:
        existing = conn.execute('SELECT id FROM patterns WHERE tech=? AND pattern_type=?', (tech, ptype)).fetchone()
        if not existing:
            conn.execute('INSERT INTO patterns (tech, version, pattern_type, snippet, description, source, created_at) VALUES (?,?,?,?,?,?,?)',
                        (tech, ver, ptype, snippet, desc, source, datetime.now().isoformat()))

def add_pattern(tech: str, version: str, ptype: str, snippet: str, description: str, source: str = 'learned') -> int:
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    existing = conn.execute('SELECT id FROM patterns WHERE tech=? AND pattern_type=? AND snippet=?', (tech, ptype, snippet[:100])).fetchone()
    if existing:
        conn.execute('UPDATE patterns SET times_used=times_used+1, last_used=? WHERE id=?', (datetime.now().isoformat(), existing[0]))
        conn.commit()
        conn.close()
        return existing[0]
    cur = conn.execute('INSERT INTO patterns (tech, version, pattern_type, snippet, description, source, created_at) VALUES (?,?,?,?,?,?,?)',
                      (tech, version, ptype, snippet, description, source, datetime.now().isoformat()))
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid

def get_patterns(tech: str = None, ptype: str = None, min_success: float = 0.5) -> list:
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    conn.row_factory = sqlite3.Row
    query = 'SELECT * FROM patterns WHERE success_rate >= ?'
    params = [min_success]
    if tech:
        query += ' AND tech LIKE ?'
        params.append(f'%{tech}%')
    if ptype:
        query += ' AND pattern_type LIKE ?'
        params.append(f'%{ptype}%')
    query += ' ORDER BY success_rate DESC, times_used DESC LIMIT 10'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_pattern_success(pattern_id: int):
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    conn.execute('UPDATE patterns SET times_used=times_used+1, success_rate=MIN(1.0, success_rate+0.05), last_used=? WHERE id=?',
                (datetime.now().isoformat(), pattern_id))
    conn.commit()
    conn.close()

def mark_pattern_failure(pattern_id: int):
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    conn.execute('UPDATE patterns SET times_failed=times_failed+1, success_rate=MAX(0.1, success_rate-0.1) WHERE id=?', (pattern_id,))
    conn.commit()
    conn.close()

def add_rule(rule_text: str, rule_type: str, applies_to: str, origin: str = 'learned', confidence: float = 0.5):
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    existing = conn.execute('SELECT id, confidence FROM cyberia_rules WHERE rule_text=?', (rule_text,)).fetchone()
    if existing:
        new_conf = min(1.0, existing[1] + 0.1)
        conn.execute('UPDATE cyberia_rules SET confidence=? WHERE id=?', (new_conf, existing[0]))
    else:
        conn.execute('INSERT INTO cyberia_rules (rule_text, rule_type, applies_to, origin, confidence, created_at) VALUES (?,?,?,?,?,?)',
                    (rule_text, rule_type, applies_to, origin, confidence, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_rules(applies_to: str = None, min_confidence: float = 0.6) -> list:
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    conn.row_factory = sqlite3.Row
    query = 'SELECT * FROM cyberia_rules WHERE confidence >= ?'
    params = [min_confidence]
    if applies_to:
        query += ' AND applies_to LIKE ?'
        params.append(f'%{applies_to}%')
    query += ' ORDER BY confidence DESC LIMIT 20'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_kb_summary() -> dict:
    init_kb()
    conn = sqlite3.connect(KB_PATH)
    patterns = conn.execute('SELECT COUNT(*) FROM patterns').fetchone()[0]
    rules = conn.execute('SELECT COUNT(*) FROM cyberia_rules WHERE confidence >= 0.6').fetchone()[0]
    audits = conn.execute('SELECT COUNT(*) FROM audit_log WHERE applied=1').fetchone()[0]
    top = conn.execute('SELECT tech, COUNT(*) as c FROM patterns GROUP BY tech ORDER BY c DESC LIMIT 5').fetchall()
    conn.close()
    return {'total_patterns': patterns, 'validated_rules': rules, 'audits_applied': audits,
            'top_techs': [{'tech': r[0], 'count': r[1]} for r in top]}
