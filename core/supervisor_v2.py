from __future__ import annotations
import json, sqlite3, threading, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.agent_factory_v2 import Agent, create_predefined_agent, create_from_description

DB_PATH = Path('.cyberia/cyberia_supervisor.db')


@dataclass
class SubTask:
    id: str
    agent_type: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    status: str = 'pending'
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class TaskDAG:
    task_id: str
    root_description: str
    subtasks: Dict[str, SubTask] = field(default_factory=dict)


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY, agent_name TEXT, agent_type TEXT,
            status TEXT, input_json TEXT, output_json TEXT, error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks_dag (
            id TEXT PRIMARY KEY, root_description TEXT,
            dag_json TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agent_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT,
            agent_type TEXT, task_id TEXT, success INTEGER,
            duration REAL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS web_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT,
            query TEXT, result_json TEXT, created_at INTEGER
        );
    ''')
    conn.commit()
    conn.close()


init_db()

PROGRESS_FILE = Path('.cyberia/dag_progress.jsonl')


def log_progress(task_id, subtask_id, agent_type, status, message=''):
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    entry = json.dumps({'ts': time.time(), 'task_id': task_id, 'subtask': subtask_id,
        'agent': agent_type, 'status': status, 'message': message}, ensure_ascii=False)
    with open(PROGRESS_FILE, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')


def decompose_task(message: str, requested_agents: int = 0) -> TaskDAG:
    import re
    task_id = f'task_{int(time.time())}'
    from core.multi_model_router import MultiModelRouter
    router = MultiModelRouter()

    if requested_agents == 0:
        match = re.search(r'(\d+)\s*agent', message.lower())
        if match:
            requested_agents = min(int(match.group(1)), 20)
        else:
            requested_agents = 5

    prompt = f'''Decompose cette demande en {requested_agents} sous-taches specialisees avec dependances.
Demande : {message}
Nombre d agents demandes : {requested_agents}

Reponds UNIQUEMENT en JSON :
[
  {{"id": "t1", "agent_type": "AgentRecherche", "description": "...", "depends_on": []}},
  {{"id": "t2", "agent_type": "AgentArchitecture", "description": "...", "depends_on": ["t1"]}},
  ...
]

Types d agents disponibles : AgentRecherche, AgentArchitecture, AgentCode, AgentTest, AgentOptimisation, AgentOrchestrateur, AgentSecurite, AgentDocumentation, AgentDeploiement, AgentIntegration, AgentPerformance, AgentBDD, AgentAPI, AgentUI, AgentMonitoring

Assure-toi que les dependances forment un DAG valide (pas de cycle).
Chaque agent doit avoir une description precise et une vraie valeur ajoutee.'''

    try:
        response = router.call(prompt, task_type='architecture')
        import re as re2
        match2 = re2.search(r'\[.*\]', response, re2.DOTALL)
        if match2:
            tasks_data = json.loads(match2.group())
            subtasks = {}
            for t in tasks_data:
                subtasks[t['id']] = SubTask(
                    id=t['id'], agent_type=t['agent_type'],
                    description=t['description'], depends_on=t.get('depends_on', []))
            dag = TaskDAG(task_id=task_id, root_description=message, subtasks=subtasks)
            _persist_dag(dag)
            print(f'  [DAG] {len(subtasks)} agents planifies par LLM')
            return dag
    except Exception as e:
        print(f'  [DAG] Fallback pipeline standard ({e})')

    subtasks = {
        'research': SubTask(id='research', agent_type='AgentRecherche',
            description=f'Recherche des meilleures pratiques pour : {message}', depends_on=[]),
        'architecture': SubTask(id='architecture', agent_type='AgentArchitecture',
            description='Concevoir une architecture optimale.', depends_on=['research']),
        'code': SubTask(id='code', agent_type='AgentCode',
            description='Generer le code complet.', depends_on=['architecture']),
        'tests': SubTask(id='tests', agent_type='AgentTest',
            description='Generer et valider les tests.', depends_on=['code']),
        'optimize': SubTask(id='optimize', agent_type='AgentOptimisation',
            description='Optimiser les performances.', depends_on=['tests']),
    }
    dag = TaskDAG(task_id=task_id, root_description=message, subtasks=subtasks)
    _persist_dag(dag)
    return dag


def _persist_dag(dag: TaskDAG) -> None:
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO tasks_dag (id, root_description, dag_json) VALUES (?,?,?)',
        (dag.task_id, dag.root_description, json.dumps(_dag_to_dict(dag))))
    conn.commit()
    conn.close()


def _dag_to_dict(dag: TaskDAG) -> Dict[str, Any]:
    return {
        'task_id': dag.task_id,
        'root_description': dag.root_description,
        'subtasks': {
            sid: {
                'id': st.id, 'agent_type': st.agent_type,
                'description': st.description, 'depends_on': st.depends_on,
                'status': st.status, 'result': st.result, 'error': st.error,
            }
            for sid, st in dag.subtasks.items()
        },
    }


def execute_dag(dag: TaskDAG, context: Dict[str, Any] = None) -> TaskDAG:
    if context is None:
        context = {}
    remaining = set(dag.subtasks.keys())
    lock = threading.Lock()
    running = set()

    def run_subtask(subtask_id: str) -> None:
        st = dag.subtasks[subtask_id]
        st.status = 'running'
        _update_task(dag.task_id, st, 'running')
        log_progress(dag.task_id, subtask_id, st.agent_type, 'START', f'Demarrage {st.description[:60]}')
        start = time.time()
        agent = None
        try:
            agent = spawn_agent(st.agent_type, st.description, context)
            result = agent.execute(
                task={'task_id': dag.task_id, 'subtask_id': st.id, 'description': st.description},
                context=context,
            )
            st.result = result
            st.status = 'done'
            _update_task(dag.task_id, st, 'done', result=result)
            _done_summary = (result.get('summary', result.get('resume', str(result)[:60])) if isinstance(result, dict) else str(result)[:60])
            log_progress(dag.task_id, subtask_id, st.agent_type, 'DONE', _done_summary[:100])
            try:
                from core.enrichment import log_improvement
                log_improvement(
                    agent=st.agent_type,
                    task=st.description[:100],
                    component='supervisor_v2',
                    success=True,
                    impact=f'Etape {st.id} reussie dans DAG {dag.task_id[:20]}'
                )
            except Exception:
                pass
            _record_metrics(agent, dag.task_id, True, time.time() - start)
        except Exception as e:
            st.error = str(e)
            st.status = 'failed'
            _update_task(dag.task_id, st, 'failed', error=str(e))
            log_progress(dag.task_id, subtask_id, st.agent_type, 'ERROR', str(e)[:100])
            try:
                from core.enrichment import log_improvement
                log_improvement(
                    agent=st.agent_type,
                    task=st.description[:100],
                    component='supervisor_v2',
                    success=False,
                    impact=str(e)[:100]
                )
            except Exception:
                pass
            if agent:
                _record_metrics(agent, dag.task_id, False, time.time() - start)
        with lock:
            remaining.discard(subtask_id)
            running.discard(subtask_id)

    max_wait = 120
    start_total = time.time()
    while remaining and (time.time() - start_total) < max_wait:
        with lock:
            runnable = [
                sid for sid in remaining
                if sid not in running
                and all(dag.subtasks[dep].status == 'done' for dep in dag.subtasks[sid].depends_on)
                and not any(dag.subtasks[dep].status == 'failed' for dep in dag.subtasks[sid].depends_on)
            ]
        for sid in runnable:
            with lock:
                running.add(sid)
            t = threading.Thread(target=run_subtask, args=(sid,), daemon=True)
            t.start()
        time.sleep(0.2)

    _persist_dag(dag)
    return dag


def _update_task(task_id, subtask, status, result=None, error=None):
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO agent_tasks '
        '(id,agent_name,agent_type,status,input_json,output_json,error) VALUES (?,?,?,?,?,?,?)',
        (f'{task_id}:{subtask.id}', subtask.agent_type, subtask.agent_type, status,
         json.dumps({'description': subtask.description}),
         json.dumps(result) if result else None, error))
    conn.commit()
    conn.close()


def _record_metrics(agent, task_id, success, duration):
    conn = get_conn()
    conn.execute(
        'INSERT INTO agent_metrics (agent_name,agent_type,task_id,success,duration) VALUES (?,?,?,?,?)',
        (agent.name, agent.role, task_id, int(success), duration))
    conn.commit()
    conn.close()


def spawn_agent(agent_type: str, description: str, context: Dict[str, Any]) -> Agent:
    predefined = {
        'AgentRecherche', 'AgentArchitecture', 'AgentCode', 'AgentTest', 'AgentOptimisation',
        'AgentOrchestrateur', 'AgentSecurite', 'AgentDocumentation', 'AgentDeploiement',
        'AgentIntegration', 'AgentPerformance', 'AgentBDD', 'AgentAPI', 'AgentMonitoring',
    }
    if agent_type in predefined:
        return create_predefined_agent(agent_type, context=context)
    return create_from_description(description=description, domain=context.get('domain', 'general'))


def collect_results(dag: TaskDAG) -> Dict[str, Any]:
    return {
        'task_id': dag.task_id,
        'root_description': dag.root_description,
        'subtasks': {
            sid: {'status': st.status, 'result': st.result, 'error': st.error}
            for sid, st in dag.subtasks.items()
        },
    }


def present_to_user(results: Dict[str, Any]) -> str:
    lines = [f'Tache accomplie : {results["root_description"]}', '']
    for sid, info in results['subtasks'].items():
        status_icon = 'OK' if info['status'] == 'done' else 'ECHEC' if info['status'] == 'failed' else '...'
        r = info.get('result') or {}
        if isinstance(r, dict):
            summary = r.get('summary', r.get('resume', r.get('output', r.get('raw', ''))))
            if not summary and r.get('fichiers'):
                fichiers = r['fichiers']
                summary = f'{len(fichiers)} fichier(s) genere(s) : {chr(10).join(f["nom"] for f in fichiers[:5])}'
            if not summary and r.get('sources'):
                summary = f'{len(r["sources"])} sources trouvees'
            if not summary and r.get('optimisations'):
                summary = f'{len(r["optimisations"])} optimisation(s) proposee(s)'
            if not summary:
                summary = str(r)[:150]
        else:
            summary = str(r)[:150]
        if info['status'] == 'failed':
            summary = f'Erreur : {info["error"]}'
        lines.append(f'  [{status_icon}] {sid} : {summary[:200]}')
    lines.extend(['', 'Actions disponibles :'])
    lines.extend(['  [a] Voir architecture complete', '  [c] Voir le code genere', '  [t] Voir les tests'])
    return '\n'.join(lines)
