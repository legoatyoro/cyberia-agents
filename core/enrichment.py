import sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime

DB = Path('.cyberia/enrichment.db')


def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS fix_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT, error_signature TEXT, fix_summary TEXT,
            patch TEXT, tags TEXT, success_count INTEGER DEFAULT 1,
            created_at TEXT, last_used TEXT
        );
        CREATE TABLE IF NOT EXISTS code_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, description TEXT, code TEXT,
            tags TEXT, use_count INTEGER DEFAULT 0, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS user_directives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE, value TEXT, category TEXT,
            weight INTEGER DEFAULT 5, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS improvement_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT, task TEXT, component TEXT,
            success INTEGER, impact TEXT, user_feedback INTEGER DEFAULT 0,
            created_at TEXT
        );
    ''')
    conn.commit()
    conn.close()


def save_fix_pattern(component, problem, solution, patch='', tags=None):
    init()
    sig = hashlib.md5(f'{component}:{problem[:100]}'.encode()).hexdigest()
    conn = sqlite3.connect(DB)
    existing = conn.execute('SELECT id, success_count FROM fix_patterns WHERE error_signature=?', (sig,)).fetchone()
    now = datetime.now().isoformat()
    if existing:
        conn.execute('UPDATE fix_patterns SET success_count=success_count+1, last_used=?, fix_summary=? WHERE id=?',
            (now, solution[:500], existing[0]))
    else:
        conn.execute('INSERT INTO fix_patterns (component, error_signature, fix_summary, patch, tags, created_at, last_used) VALUES (?,?,?,?,?,?,?)',
            (component, sig, solution[:500], patch[:2000], json.dumps(tags or []), now, now))
    conn.commit()
    conn.close()
    try:
        from core.memory_hub import save_exchange
        save_exchange('enrichment', f'Fix {component}: {problem[:100]} -> {solution[:100]}',
                     category='correction', confidence=1.0, force_save=True)
    except Exception:
        pass
    print(f'  [ENRICHMENT] Fix pattern sauvegarde : {component}')


def save_code_pattern(name, description, code, tags=None):
    init()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT OR REPLACE INTO code_patterns (name, description, code, tags, created_at) VALUES (?,?,?,?,?)',
        (name, description, code, json.dumps(tags or []), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    print(f'  [ENRICHMENT] Code pattern sauvegarde : {name}')


def get_fix_for_problem(problem_description):
    init()
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT fix_summary, patch, success_count FROM fix_patterns ORDER BY success_count DESC LIMIT 5').fetchall()
    conn.close()
    if not rows:
        return None
    problem_lower = problem_description.lower()
    for fix_summary, patch, count in rows:
        if any(word in fix_summary.lower() for word in problem_lower.split()[:5]):
            return {'fix_summary': fix_summary, 'patch': patch, 'confidence': min(count / 10, 1.0)}
    return None


def add_directive(key, value, category='behavior', weight=5):
    init()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT OR REPLACE INTO user_directives (key, value, category, weight, created_at) VALUES (?,?,?,?,?)',
        (key, value, category, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_directives():
    init()
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT key, value, category FROM user_directives ORDER BY weight DESC').fetchall()
    conn.close()
    return [{'key': k, 'value': v, 'category': c} for k, v, c in rows]


def log_improvement(agent, task, component, success, impact='', user_feedback=0):
    init()
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO improvement_log (agent, task, component, success, impact, user_feedback, created_at) VALUES (?,?,?,?,?,?,?)',
        (agent, task, component, int(success), impact, user_feedback, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_stats():
    init()
    conn = sqlite3.connect(DB)
    fixes = conn.execute('SELECT COUNT(*) FROM fix_patterns').fetchone()[0]
    patterns = conn.execute('SELECT COUNT(*) FROM code_patterns').fetchone()[0]
    directives = conn.execute('SELECT COUNT(*) FROM user_directives').fetchone()[0]
    improvements = conn.execute('SELECT COUNT(*) FROM improvement_log WHERE success=1').fetchone()[0]
    conn.close()
    return {'fix_patterns': fixes, 'code_patterns': patterns, 'directives': directives, 'successful_improvements': improvements}


def seed_yoro_directives():
    directives = [
        ('dag_post_actions', 'Apres un DAG toujours proposer [a] architecture [c] code [t] tests', 'behavior', 10),
        ('output_format', 'Toujours resumer les resultats DAG en max 5 lignes lisibles', 'behavior', 9),
        ('file_writing', 'Toujours ecrire les fichiers generes dans generated/<project>/', 'behavior', 10),
        ('error_handling', 'Jamais retourner du JSON brut - toujours formater pour l utilisateur', 'behavior', 9),
        ('validation', 'Toujours valider la syntaxe Python avec ast.parse avant d appliquer un patch', 'security', 10),
        ('rollback', 'Toujours creer un backup .bak avant de modifier un fichier critique', 'security', 10),
        ('memory', 'Enregistrer chaque correction reussie dans fix_patterns et memory_hub', 'learning', 9),
        ('dag_complexity', 'Utiliser le DAG pour les demandes complexes multi-agents seulement', 'behavior', 8),
        ('fastapi_preferred', 'Pour les petites APIs utiliser FastAPI + SQLite par defaut', 'technical', 7),
        ('railway_deploy', 'Deployer uniquement via git push origin main jamais Railway CLI', 'technical', 9),
    ]
    for key, value, category, weight in directives:
        add_directive(key, value, category, weight)
    save_code_pattern(
        'dag_present_to_user',
        'Formatage lisible des resultats DAG avec extraction intelligente',
        'def present_to_user(results):\n'
        '    lines = [f\'Tache: {results["root_description"]}\']\n'
        '    for sid, info in results["subtasks"].items():\n'
        '        r = info.get("result") or {}\n'
        '        summary = r.get("summary", r.get("resume", str(r)[:100]))\n'
        '        lines.append(f\'  [{info["status"]}] {sid}: {summary[:150]}\')\n'
        '    return "\\n".join(lines)',
        ['DAG', 'UX', 'supervisor'],
    )
    save_code_pattern(
        'agent_execute_with_retry',
        'Execute un agent avec retry automatique sur echec',
        'def execute_with_retry(agent, task, context, max_retries=2):\n'
        '    for attempt in range(max_retries):\n'
        '        try:\n'
        '            return agent.execute(task, context)\n'
        '        except Exception as e:\n'
        '            if attempt == max_retries-1: return {"error": str(e), "summary": "Echec apres retries"}\n'
        '    return {"error": "max retries", "summary": "Abandon"}',
        ['agent', 'robustness'],
    )
    print('  [ENRICHMENT] Directives Yoro initialisees : 10 directives, 2 code patterns')
