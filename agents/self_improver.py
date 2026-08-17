import ast, sqlite3, json, subprocess, sys, time
from pathlib import Path
from datetime import datetime
from core.multi_model_router import MultiModelRouter

DB = Path('.cyberia/self_improvement.db')

def init_db():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file TEXT, line INTEGER, issue_type TEXT,
            description TEXT, severity TEXT,
            fix_proposed TEXT, fix_applied INTEGER DEFAULT 0,
            detected_at TEXT, applied_at TEXT
        );
        CREATE TABLE IF NOT EXISTS improvement_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT, finished_at TEXT,
            files_scanned INTEGER, issues_found INTEGER,
            fixes_applied INTEGER, status TEXT
        );
    ''')
    conn.commit()
    conn.close()

def scan_syntax_errors():
    issues = []
    CORE_FILES = list(Path('core').rglob('*.py')) + list(Path('agents').rglob('*.py')) + [Path('cyberia.py')]
    for f in CORE_FILES:
        if '__pycache__' in str(f): continue
        if not f.exists(): continue
        try:
            ast.parse(f.read_text(encoding='utf-8', errors='ignore'))
        except SyntaxError as e:
            issues.append({'file': str(f), 'line': e.lineno, 'type': 'syntax_error', 'description': str(e), 'severity': 'critical'})
    return issues

def scan_import_errors():
    issues = []
    CORE_FILES = list(Path('core').rglob('*.py')) + list(Path('agents').rglob('*.py'))
    for f in CORE_FILES:
        if '__pycache__' in str(f): continue
        if not f.exists(): continue
        try:
            result = subprocess.run(
                [sys.executable, '-c',
                 f'import importlib.util; spec=importlib.util.spec_from_file_location("m","{f}"); m=importlib.util.module_from_spec(spec)'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 and 'ModuleNotFoundError' in result.stderr:
                missing = result.stderr.split('No module named')[-1].strip().strip("'").strip()
                issues.append({'file': str(f), 'line': 0, 'type': 'missing_import', 'description': f'Module manquant: {missing}', 'severity': 'high'})
        except Exception:
            pass
    return issues

def scan_with_llm(files_to_scan=None):
    issues = []
    router = MultiModelRouter()
    if files_to_scan is None:
        files_to_scan = sorted(Path('core').glob('*.py'))[:5]
    for f in files_to_scan:
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')[:3000]
            prompt = f'''Analyse ce fichier Python de CYBERIA et detecte les bugs reels (pas les avertissements de style).
Reponds UNIQUEMENT en JSON: [{{"line": N, "type": "bug|performance|logic", "description": "...", "severity": "critical|high|medium", "fix": "code fix en une ligne ou None"}}]
Si aucun bug, reponds: []

FICHIER {f.name}:
{content}'''
            response = router.call(prompt, task_type='analysis')
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                found = json.loads(match.group())
                for issue in found:
                    if issue.get('severity') in ('critical', 'high'):
                        issues.append({
                            'file': str(f),
                            'line': issue.get('line', 0),
                            'type': issue.get('type', 'bug'),
                            'description': issue.get('description', ''),
                            'severity': issue.get('severity', 'medium'),
                            'fix': issue.get('fix')
                        })
        except Exception:
            pass
    return issues

def save_issues(issues):
    init_db()
    conn = sqlite3.connect(DB)
    saved = 0
    for issue in issues:
        existing = conn.execute(
            'SELECT id FROM issues WHERE file=? AND description=? AND fix_applied=0',
            (issue['file'], issue['description'])
        ).fetchone()
        if not existing:
            conn.execute(
                'INSERT INTO issues (file, line, issue_type, description, severity, fix_proposed, detected_at) VALUES (?,?,?,?,?,?,?)',
                (issue['file'], issue.get('line', 0), issue.get('type', 'bug'), issue['description'],
                 issue.get('severity', 'medium'), issue.get('fix'), datetime.now().isoformat())
            )
            saved += 1
    conn.commit()
    conn.close()
    return saved

def get_pending_issues(severity_filter=None):
    init_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    query = 'SELECT * FROM issues WHERE fix_applied=0'
    if severity_filter:
        query += f" AND severity='{severity_filter}'"
    query += ' ORDER BY detected_at DESC LIMIT 20'
    rows = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()
    return rows

def apply_fix(issue_id, fix_code, file_path, line_num):
    try:
        p = Path(file_path)
        if not p.exists(): return False
        backup = p.with_suffix('.selfimprove.bak')
        backup.write_text(p.read_text(encoding='utf-8'), encoding='utf-8')
        lines = p.read_text(encoding='utf-8').splitlines()
        if line_num and 0 < line_num <= len(lines):
            lines[line_num - 1] = fix_code
            p.write_text('\n'.join(lines), encoding='utf-8')
        try:
            ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError:
            backup.replace(p)
            return False
        conn = sqlite3.connect(DB)
        conn.execute('UPDATE issues SET fix_applied=1, applied_at=? WHERE id=?',
                     (datetime.now().isoformat(), issue_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def run_full_scan(auto_fix=False):
    print('  [SELF_IMPROVER] Scan complet de CYBERIA...')
    start = datetime.now()
    all_issues = []

    syntax = scan_syntax_errors()
    all_issues.extend(syntax)
    print(f'  [SELF_IMPROVER] Syntaxe: {len(syntax)} probleme(s)')

    imports = scan_import_errors()
    all_issues.extend(imports)
    print(f'  [SELF_IMPROVER] Imports: {len(imports)} probleme(s)')

    llm_issues = scan_with_llm()
    all_issues.extend(llm_issues)
    print(f'  [SELF_IMPROVER] Analyse LLM: {len(llm_issues)} probleme(s)')

    saved = save_issues(all_issues)
    fixes_applied = 0

    if auto_fix:
        pending = get_pending_issues('critical')
        for issue in pending[:3]:
            if issue.get('fix_proposed') and issue['fix_proposed'] != 'None':
                if apply_fix(issue['id'], issue['fix_proposed'], issue['file'], issue['line']):
                    fixes_applied += 1
                    print(f'  [SELF_IMPROVER] Fix applique: {issue["file"]}:{issue["line"]}')

    init_db()
    conn = sqlite3.connect(DB)
    conn.execute(
        'INSERT INTO improvement_runs (started_at, finished_at, files_scanned, issues_found, fixes_applied, status) VALUES (?,?,?,?,?,?)',
        (start.isoformat(), datetime.now().isoformat(),
         len(set(i['file'] for i in all_issues)), len(all_issues), fixes_applied, 'completed')
    )
    conn.commit()
    conn.close()

    print(f'  [SELF_IMPROVER] Scan termine: {len(all_issues)} problemes, {fixes_applied} fixes auto')
    return all_issues, fixes_applied
