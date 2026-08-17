import json, sqlite3
from pathlib import Path
from datetime import datetime

DIRECTIVES_GLOBAL = [
    'Reponds de facon concise, orientee action, sans blabla inutile.',
    'Reponds en francais, avec des termes techniques anglais si necessaire.',
    'Propose toujours 2-4 actions suivantes concretes apres ta reponse.',
    'Indique toujours quel mode ou action tu as choisi.',
    'Ne fais jamais d actions destructrices sans confirmation (delete, drop, reset).',
]
DIRECTIVES_CODING = [
    'Pour les petites API, privilegier FastAPI + SQLite.',
    'Pour les projets plus gros, Django + DRF + PostgreSQL.',
    'Toujours utiliser python-decouple jamais decouple seul.',
    'SQLAlchemy 2.0 : declarative_base depuis sqlalchemy.orm pas ext.declarative.',
    'Python 3.14 incompatible Jinja2 - utiliser HTMLResponse avec f-strings.',
]
DIRECTIVES_CONTEXT = [
    'Tu connais les projets de Yoro: Ecophone 44 (boutique telephones Nantes), TRANSPORTS GEANT (Carquefou), REZICOM (telecom Paris).',
    'CYBERIA RedTeam Pro est le projet SaaS cybersecurite de Yoro, en pause, a stabiliser.',
    'Yoro prefere les commandes PowerShell directes sans longues explications.',
    'Yoro deploie sur Railway via git push origin main.',
]
DIRECTIVES_AUTONOMY = [
    'Quand pertinent, propose des modes autonomes (A-Z, Auto-Scan) plutot qu attendre.',
    'Tu te souviens des corrections passees et evites de repeter les memes erreurs.',
]


def get_directives_for_intent(intent: str) -> list:
    base = DIRECTIVES_GLOBAL.copy()
    if intent in ('GENERATE_PROJECT', 'FIX_ERRORS', 'ANALYZE_PROJECT', 'GENERATE_TESTS'):
        base.extend(DIRECTIVES_CODING)
    if intent in ('GENERAL_CHAT', 'ASK_QUESTION', 'MEMORY_QUERY'):
        base.extend(DIRECTIVES_CONTEXT)
    if intent in ('GENERATE_PROJECT', 'FIX_ERRORS', 'EVOLUTION_MODE', 'SCAN_MODE'):
        base.extend(DIRECTIVES_AUTONOMY)
    return base


def get_projects() -> list:
    try:
        projects = []
        for p in sorted(Path('generated').iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not p.is_dir():
                continue
            m = p / 'metrics.json'
            score, stack = 0, 'python'
            if m.exists():
                try:
                    data = json.loads(m.read_text(encoding='utf-8'))
                    score = data.get('final_score', 0)
                    stack = data.get('stack', 'python')
                except Exception:
                    pass
            projects.append({'name': p.name, 'path': str(p), 'score': score, 'stack': stack})
        return projects[:15]
    except Exception:
        return []


def get_memory_for_query(query: str, top_k: int = 5) -> list:
    try:
        from core.memory_hub import search_relevant
        results = search_relevant(query, top_k=top_k, min_similarity=0.2)
        return [r['content'] for r in results]
    except Exception:
        return []


def build_context(message: str, intent: str, history: list = None,
                  current_project: dict = None, session_state: dict = None) -> dict:
    projects = get_projects()
    memory = get_memory_for_query(message)
    directives = get_directives_for_intent(intent)

    if current_project is None and projects:
        sessions = Path('.cyberia/project_sessions.json')
        if sessions.exists():
            try:
                data = json.loads(sessions.read_text(encoding='utf-8'))
                if data:
                    name = data[0].get('project_name', '')
                    current_project = next((p for p in projects if p['name'] == name), None)
            except Exception:
                pass

    return {
        'message': message,
        'intent': intent,
        'history': (history or [])[-6:],
        'memory': memory,
        'directives': directives,
        'current_project': current_project,
        'available_projects': projects,
        'system_state': session_state or {'last_mode_used': None, 'last_error': None},
        'timestamp': datetime.now().isoformat(),
    }
