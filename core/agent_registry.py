import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = Path('.cyberia/agent_registry.db')


def init_registry():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS agents (
        name TEXT PRIMARY KEY,
        description TEXT,
        capabilities TEXT,
        input_schema TEXT,
        output_schema TEXT,
        path TEXT,
        created_at TEXT,
        last_used_at TEXT,
        version TEXT DEFAULT '1.0',
        llm_profile TEXT,
        tags TEXT,
        auto_generated INTEGER DEFAULT 0,
        use_count INTEGER DEFAULT 0,
        avg_score REAL DEFAULT 0.0
    )''')
    conn.commit()
    conn.close()


def register_agent(name: str, description: str, capabilities: list,
                   path: str, tags: list, auto_generated: bool = False,
                   llm_profile: dict = None):
    init_registry()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''INSERT OR REPLACE INTO agents
        (name, description, capabilities, path, created_at, tags, auto_generated, llm_profile)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (name, description, json.dumps(capabilities), path,
         datetime.now().isoformat(), json.dumps(tags),
         1 if auto_generated else 0,
         json.dumps(llm_profile or {})))
    conn.commit()
    conn.close()
    print(f'📋 [REGISTRY] Agent {name} enregistré')


def get_agent(name: str) -> dict | None:
    init_registry()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM agents WHERE name = ?', (name,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d['capabilities'] = json.loads(d['capabilities'])
        d['tags'] = json.loads(d['tags'])
        return d
    return None


def find_agents_by_capability(capability: str) -> list:
    init_registry()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM agents WHERE capabilities LIKE ?',
        (f'%{capability}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_all_agents() -> list:
    init_registry()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT name, description, tags, auto_generated, use_count, avg_score FROM agents ORDER BY use_count DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_agent_stats(name: str, score: float):
    init_registry()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''UPDATE agents SET
        use_count = use_count + 1,
        last_used_at = ?,
        avg_score = (avg_score * use_count + ?) / (use_count + 1)
        WHERE name = ?''',
        (datetime.now().isoformat(), score, name))
    conn.commit()
    conn.close()


def register_builtin_agents():
    builtins = [
        ('ARCHITECTE', 'Génère le blueprint et architecture', ['architecture', 'blueprint', 'planning'], 'agents/architecte.py', ['core', 'builtin']),
        ('BUILDER', 'Génère les fichiers du projet', ['code_generation', 'file_creation'], 'agents/builder.py', ['core', 'builtin']),
        ('EXPERT_BUILDER', 'Builder avec profils experts', ['code_generation', 'expert'], 'agents/expert_builder.py', ['expert', 'builtin']),
        ('VALIDATOR', 'Valide imports et cohérence', ['validation', 'ast', 'imports'], 'agents/validator.py', ['core', 'builtin']),
        ('FIXER', 'Corrige les erreurs automatiquement', ['bug_fix', 'correction'], 'agents/fixer.py', ['core', 'builtin']),
        ('TESTER', 'Génère et exécute les tests', ['testing', 'pytest', 'coverage'], 'agents/tester.py', ['core', 'builtin']),
        ('SECURITY', 'Audit de sécurité OWASP', ['security', 'audit', 'owasp'], 'agents/security.py', ['core', 'builtin']),
        ('RUNNER', 'Exécute et teste le projet', ['execution', 'runtime', 'testing'], 'agents/runner.py', ['core', 'builtin']),
        ('DOCUMENTER', 'Génère la documentation', ['documentation', 'readme'], 'agents/documenter.py', ['core', 'builtin']),
        ('DEPLOYER', 'Génère les fichiers de déploiement', ['docker', 'devops', 'deployment'], 'agents/deployer.py', ['core', 'builtin']),
        ('ANALYSTE', 'Analyse les projets existants', ['analysis', 'improvement'], 'agents/analyste.py', ['core', 'builtin']),
        ('CDC_GENERATOR', 'Génère les CDC depuis phrases simples', ['cdc', 'planning'], 'agents/cdc_generator.py', ['core', 'builtin']),
        ('ROUTER_EXPERT', 'Route vers les bons experts', ['routing', 'planning'], 'agents/router_expert.py', ['core', 'builtin']),
        ('OPTIMIZER', 'Optimise les performances', ['optimization', 'performance'], 'agents/optimizer.py', ['improvement', 'builtin']),
        ('REFACTORER', 'Refactore le code', ['refactoring', 'quality'], 'agents/refactorer.py', ['improvement', 'builtin']),
    ]
    for name, desc, caps, path, tags in builtins:
        register_agent(name, desc, caps, path, tags, auto_generated=False)
    print(f'📋 [REGISTRY] {len(builtins)} agents built-in enregistrés')


if __name__ == '__main__':
    register_builtin_agents()
    agents = list_all_agents()
    print(f'Total agents : {len(agents)}')
    for a in agents:
        print(f'  {a["name"]} — {a["description"]}')
