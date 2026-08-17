from pathlib import Path
from datetime import datetime
import json

SESSION_FILE = Path('.cyberia/project_sessions.json')

EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.md', '.env.example', '.yml', '.yaml'}
SKIP = {'node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build', '.next', 'migrations'}


def load_external_project(prompt_label='Chemin du projet a lire : '):
    chemin = input(prompt_label).strip().strip('"').strip("'")
    path = Path(chemin)
    if not path.exists():
        print(f'  Dossier introuvable : {chemin}')
        return None, None
    MAX_FILES = 20
    MAX_CHARS = 8000
    files_read = []
    parts = [f'PROJET EXTERNE : {path.name}', '=' * 50]
    all_files = sorted(
        [f for f in path.rglob('*')
         if f.is_file() and f.suffix in EXTENSIONS and not any(s in f.parts for s in SKIP)],
        key=lambda f: f.stat().st_size
    )[:MAX_FILES]
    for f in all_files:
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if len(content) > MAX_CHARS:
                content = content[:MAX_CHARS] + '\n... (tronque)'
            rel = f.relative_to(path)
            parts.append(f'\n=== {rel} ({content.count(chr(10)) + 1} lignes) ===')
            parts.append(content)
            files_read.append(str(rel))
        except Exception:
            pass
    context = '\n'.join(parts)
    print(f'  [CYBERIA a lu {len(files_read)} fichier(s) de {path.name}]')
    save_project_session(path.name, str(path), context[:200])
    return context, path


def save_project_session(project_name, project_path, context_summary=''):
    SESSION_FILE.parent.mkdir(exist_ok=True)
    sessions = []
    if SESSION_FILE.exists():
        try:
            sessions = json.loads(SESSION_FILE.read_text(encoding='utf-8'))
        except Exception:
            sessions = []
    sessions = [s for s in sessions if s.get('project_name') != project_name]
    sessions.insert(0, {
        'project_name': project_name,
        'project_path': project_path,
        'last_opened': datetime.now().isoformat(),
        'context_summary': context_summary[:200]
    })
    SESSION_FILE.write_text(json.dumps(sessions[:10], ensure_ascii=False, indent=2), encoding='utf-8')


def get_recent_projects(n=5):
    if not SESSION_FILE.exists():
        return []
    try:
        return json.loads(SESSION_FILE.read_text(encoding='utf-8'))[:n]
    except Exception:
        return []
