import ast, json, sqlite3, hashlib
from pathlib import Path

DB = Path('.cyberia/project_index.db')


def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS file_summaries (
            id INTEGER PRIMARY KEY, project_name TEXT, path TEXT,
            summary TEXT, tokens_estimated INTEGER, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS function_embeddings (
            id INTEGER PRIMARY KEY, project_name TEXT, file_path TEXT,
            symbol_name TEXT, kind TEXT, summary TEXT, embedding TEXT
        );
        CREATE TABLE IF NOT EXISTS project_graphs (
            id INTEGER PRIMARY KEY, project_name TEXT,
            graph_json TEXT, updated_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_file ON file_summaries(project_name, path);
    ''')
    conn.commit()
    conn.close()


def extract_ast_info(filepath):
    try:
        content = Path(filepath).read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content)
        info = {'classes': [], 'functions': [], 'imports': [], 'endpoints': []}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                info['classes'].append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info['functions'].append(node.name)
                for decorator in node.decorator_list:
                    d = ast.unparse(decorator) if hasattr(ast, 'unparse') else ''
                    if any(x in d for x in ['get', 'post', 'put', 'delete', 'patch']):
                        info['endpoints'].append(f'{d} {node.name}')
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    info['imports'].append(node.module)
        return info, content
    except Exception:
        return {}, ''


def build_dependency_graph(project_dir):
    path = Path(project_dir)
    graph = {}
    for f in path.rglob('*.py'):
        if '__pycache__' in str(f) or 'node_modules' in str(f):
            continue
        info, _ = extract_ast_info(f)
        rel = str(f.relative_to(path))
        internal_imports = [
            imp for imp in info.get('imports', [])
            if (path / imp.replace('.', '/') / '__init__.py').exists()
            or (path / (imp.replace('.', '/') + '.py')).exists()
        ]
        graph[rel] = internal_imports
    return graph


def generate_file_summary(filepath, ast_info, project_name):
    from core.multi_model_router import MultiModelRouter
    router = MultiModelRouter()
    name = Path(filepath).name
    classes = ', '.join(ast_info.get('classes', [])[:5])
    funcs = ', '.join(ast_info.get('functions', [])[:8])
    endpoints = ', '.join(ast_info.get('endpoints', [])[:5])
    imports = ', '.join(ast_info.get('imports', [])[:6])
    prompt = (
        f'Resume ce fichier Python en 2 phrases maximum (max 80 mots).\n'
        f'Fichier: {name}\nClasses: {classes}\nFonctions: {funcs}\n'
        f'Endpoints: {endpoints}\nImports: {imports}\n'
        f'Quel est le role de ce fichier dans le projet {project_name} ?'
    )
    try:
        return router.call(prompt, task_type='analysis')[:300]
    except Exception:
        role = ('endpoints API' if endpoints
                else 'modeles' if 'model' in name.lower()
                else 'configuration' if 'config' in name.lower()
                else 'logique metier')
        return f'Fichier {name} - {role}. Classes: {classes or "aucune"}. Fonctions: {funcs or "aucune"}'


def index_project(project_dir, force=False):
    path = Path(project_dir)
    if not path.exists():
        return False
    project_name = path.name
    init()

    py_files = [
        f for f in path.rglob('*.py')
        if '__pycache__' not in str(f) and 'node_modules' not in str(f)
    ][:30]

    print(f'  [INDEXER] Indexation de {project_name} ({len(py_files)} fichiers)...')

    conn = sqlite3.connect(DB)
    from datetime import datetime

    for f in py_files:
        rel = str(f.relative_to(path))
        if not force:
            existing = conn.execute(
                'SELECT id FROM file_summaries WHERE project_name=? AND path=?',
                (project_name, rel)
            ).fetchone()
            if existing:
                continue
        ast_info, _ = extract_ast_info(f)
        summary = generate_file_summary(str(f), ast_info, project_name)
        tokens = len(summary.split())
        conn.execute(
            'INSERT OR REPLACE INTO file_summaries '
            '(project_name, path, summary, tokens_estimated, updated_at) VALUES (?,?,?,?,?)',
            (project_name, rel, summary, tokens, datetime.now().isoformat())
        )
        print(f'  [INDEXER] {rel} -> {summary[:60]}...')

    conn.commit()

    graph = build_dependency_graph(project_dir)
    conn.execute(
        'INSERT OR REPLACE INTO project_graphs (project_name, graph_json, updated_at) VALUES (?,?,?)',
        (project_name, json.dumps(graph), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    print(f'  [INDEXER] Terminee : {len(py_files)} fichiers, {len(graph)} noeuds dans le graphe')
    return True


def get_project_context(project_name, query='', max_tokens=8000):
    init()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    summaries = conn.execute(
        'SELECT path, summary, tokens_estimated FROM file_summaries WHERE project_name=? ORDER BY tokens_estimated DESC',
        (project_name,)
    ).fetchall()

    graph_row = conn.execute(
        'SELECT graph_json FROM project_graphs WHERE project_name=?',
        (project_name,)
    ).fetchone()
    conn.close()

    if not summaries:
        return f'Projet {project_name} non indexe. Lance index_project() dabord.'

    central_files = []
    if graph_row:
        graph = json.loads(graph_row['graph_json'])
        file_importance = {}
        for f, deps in graph.items():
            for dep in deps:
                file_importance[dep] = file_importance.get(dep, 0) + 1
        central_files = sorted(file_importance.keys(), key=lambda x: -file_importance.get(x, 0))[:5]

    context_parts = [f'PROJET: {project_name}', f'FICHIERS: {len(summaries)}', '']
    if central_files:
        context_parts.append(f'FICHIERS CENTRAUX:\n' + '\n'.join(f'  {f}' for f in central_files[:3]))
        context_parts.append('')

    context_parts.append('RESUME DES MODULES:')
    total_tokens = 0
    for row in summaries:
        row = dict(row)
        if total_tokens + row['tokens_estimated'] > max_tokens:
            break
        context_parts.append(f'  {row["path"]}: {row["summary"]}')
        total_tokens += row['tokens_estimated']

    return '\n'.join(context_parts)


def get_stats():
    init()
    conn = sqlite3.connect(DB)
    projects = conn.execute('SELECT COUNT(DISTINCT project_name) FROM file_summaries').fetchone()[0]
    files = conn.execute('SELECT COUNT(*) FROM file_summaries').fetchone()[0]
    conn.close()
    return {'indexed_projects': projects, 'indexed_files': files}
