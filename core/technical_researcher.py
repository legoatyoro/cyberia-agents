import sqlite3
import subprocess
import sys
from pathlib import Path

TECH_DB = Path('.cyberia/tech_knowledge.db')

BUILT_IN_PATTERNS = {
    'sqlalchemy': {
        '2.0': [
            {'pattern': 'declarative_base', 'correct': 'from sqlalchemy.orm import declarative_base', 'wrong': 'from sqlalchemy.ext.declarative import declarative_base', 'note': 'Python 3.14 compatible'},
            {'pattern': 'session', 'correct': 'sessionmaker(bind=engine, expire_on_commit=False)', 'wrong': 'sessionmaker(bind=engine)', 'note': 'Meilleure performance'},
            {'pattern': 'query', 'correct': 'session.execute(select(Model))', 'wrong': 'session.query(Model).all()', 'note': 'SQLAlchemy 2.0 style'},
        ]
    },
    'fastapi': {
        '0.100+': [
            {'pattern': 'templates', 'correct': 'HTMLResponse avec f-strings Python', 'wrong': 'Jinja2Templates avec TemplateResponse', 'note': 'Incompatible Python 3.14'},
            {'pattern': 'startup', 'correct': 'uvicorn.run(app, host="0.0.0.0", port=8000)', 'wrong': 'uvicorn.run("main:app")', 'note': 'Pas de reload en production'},
            {'pattern': 'response_model', 'correct': 'response_model=List[Schema]', 'wrong': 'response_model=list[Schema]', 'note': 'Compatibilité Python 3.8+'},
        ]
    },
    'django': {
        '4.0+': [
            {'pattern': 'settings', 'correct': 'from decouple import config  # python-decouple', 'wrong': 'from decouple import config  # decouple (mauvais package)', 'note': 'Toujours pip install python-decouple'},
            {'pattern': 'auth', 'correct': 'rest_framework_simplejwt', 'wrong': 'djangorestframework-jwt (déprécié)', 'note': 'Utiliser simplejwt'},
        ]
    },
}

def init_tech_db():
    TECH_DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(TECH_DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS lib_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library TEXT,
            version_range TEXT,
            pattern_name TEXT,
            correct_usage TEXT,
            wrong_usage TEXT,
            note TEXT,
            python_versions TEXT,
            times_used INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS lib_versions (
            library TEXT PRIMARY KEY,
            installed_version TEXT,
            checked_at TEXT
        );
    ''')
    for lib, versions in BUILT_IN_PATTERNS.items():
        for ver_range, patterns in versions.items():
            for p in patterns:
                existing = conn.execute('SELECT id FROM lib_patterns WHERE library=? AND pattern_name=?', (lib, p['pattern'])).fetchone()
                if not existing:
                    conn.execute('INSERT INTO lib_patterns (library, version_range, pattern_name, correct_usage, wrong_usage, note) VALUES (?,?,?,?,?,?)',
                                (lib, ver_range, p['pattern'], p['correct'], p['wrong'], p['note']))
    conn.commit()
    conn.close()

def get_installed_version(library: str) -> str:
    try:
        result = subprocess.run([sys.executable, '-c', f'import {library}; print({library}.__version__)'],
                               capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'

def get_patterns_for_stack(stack: dict) -> str:
    init_tech_db()
    conn = sqlite3.connect(TECH_DB)
    conn.row_factory = sqlite3.Row
    patterns_text = []

    backend = str(stack.get('backend', '')).lower()
    is_django = 'django' in backend
    is_fastapi = 'fastapi' in backend or ('python' in backend and not is_django)

    libs_to_check = []
    if is_django:
        libs_to_check = ['django', 'rest_framework']
    elif is_fastapi:
        libs_to_check = ['fastapi', 'sqlalchemy']
    elif 'nestjs' in backend or 'node' in backend:
        libs_to_check = ['nestjs']

    if not libs_to_check:
        print(f'  ⚠️ [RESEARCHER] Stack ambigu ({backend!r}) — aucun pattern injecté pour éviter une mauvaise correspondance')
        conn.close()
        return ''

    detected_label = 'Django' if is_django else 'FastAPI' if is_fastapi else backend
    print(f'  🔍 [RESEARCHER] Stack détecté : {detected_label} → patterns: {libs_to_check}')

    for lib in libs_to_check:
        rows = conn.execute('SELECT * FROM lib_patterns WHERE library=? ORDER BY times_used DESC LIMIT 5', (lib,)).fetchall()
        if rows:
            patterns_text.append(f'\n{lib.upper()} - PATTERNS VALIDÉS :')
            for row in rows:
                row = dict(row)
                patterns_text.append(f'  ✅ {row["pattern_name"]} : {row["correct_usage"]}')
                if row.get('wrong_usage'):
                    patterns_text.append(f'  ❌ ÉVITER : {row["wrong_usage"]}')
                if row.get('note'):
                    patterns_text.append(f'  💡 {row["note"]}')
    conn.close()
    result = '\n'.join(patterns_text)
    try:
        from core.event_bus import publish
        publish('RESEARCHER_UPDATE', 'TECHNICAL_RESEARCHER', {'libs_checked': libs_to_check, 'patterns_found': len(patterns_text)})
    except Exception:
        pass
    return result

def add_pattern(library: str, pattern_name: str, correct: str, wrong: str = '', note: str = ''):
    init_tech_db()
    conn = sqlite3.connect(TECH_DB)
    conn.execute('INSERT OR REPLACE INTO lib_patterns (library, pattern_name, correct_usage, wrong_usage, note) VALUES (?,?,?,?,?)',
                (library, pattern_name, correct, wrong, note))
    conn.commit()
    conn.close()

def get_research_summary(dependencies: list, stack: dict) -> str:
    init_tech_db()
    python_ver = f'{sys.version_info.major}.{sys.version_info.minor}'
    summary = f'RECHERCHE TECHNIQUE — Python {python_ver}\n'
    effective_stack = stack if (stack and stack.get('backend')) else {}
    if not effective_stack:
        print('  ⚠️ [RESEARCHER] Stack non renseigné dans le blueprint — patterns ignorés')
    patterns = get_patterns_for_stack(effective_stack)
    if patterns:
        summary += patterns
    summary += '\n\nREMINDERS CRITIQUES :\n'
    summary += '- JAMAIS Jinja2Templates sur Python 3.14+\n'
    summary += '- TOUJOURS from sqlalchemy.orm import declarative_base\n'
    summary += '- TOUJOURS if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8000)\n'
    summary += '- requirements.txt : JAMAIS les modules locaux du projet\n'
    return summary
