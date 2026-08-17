from __future__ import annotations
import json, time, threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

from core.multi_model_router_v2 import router_v2
from core.agent_factory_v2 import Agent, create_predefined_agent, create_from_description
from core.supervisor_v2 import (
    TaskDAG, SubTask, get_conn, _persist_dag, _dag_to_dict,
    decompose_task, collect_results, present_to_user,
    PROGRESS_FILE, log_progress,
)

_PREDEFINED_AGENTS = {
    'AgentRecherche', 'AgentArchitecture', 'AgentCode', 'AgentTest', 'AgentOptimisation',
    'AgentSecurite', 'AgentSecurity', 'AgentScan', 'AgentVuln', 'AgentOrchestrateur',
    'AgentDocumentation', 'AgentDeploiement', 'AgentPerformance', 'AgentBDD',
    'AgentAPI', 'AgentMonitoring',
}


def spawn_agent_v3(agent_type: str, description: str, context: Dict[str, Any]) -> Agent:
    if agent_type in _PREDEFINED_AGENTS:
        return create_predefined_agent(agent_type, context=context)
    return create_from_description(description=description, domain=context.get('domain', 'general'))


def _update_task(task_id, subtask, status, result=None, error=None):
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO agent_tasks '
        '(id,agent_name,agent_type,status,input_json,output_json,error) VALUES (?,?,?,?,?,?,?)',
        (f'{task_id}:{subtask.id}', subtask.agent_type, subtask.agent_type, status,
         json.dumps({'description': subtask.description}),
         json.dumps(result) if result else None, error),
    )
    conn.commit()
    conn.close()


def _record_metrics(agent, task_id, success, duration):
    conn = get_conn()
    conn.execute(
        'INSERT INTO agent_metrics (agent_name,agent_type,task_id,success,duration) VALUES (?,?,?,?,?)',
        (agent.name, agent.role, task_id, int(success), duration),
    )
    conn.commit()
    conn.close()


def execute_dag_v3(dag: TaskDAG, context: Dict[str, Any] = None) -> TaskDAG:
    if context is None:
        context = {}
    remaining = set(dag.subtasks.keys())
    running = set()
    lock = threading.Lock()

    def run_subtask(subtask_id: str):
        st = dag.subtasks[subtask_id]
        st.status = 'running'
        log_progress(dag.task_id, subtask_id, st.agent_type, 'START', st.description[:60])
        _update_task(dag.task_id, st, 'running')
        start = time.time()
        agent = None
        try:
            agent = spawn_agent_v3(st.agent_type, st.description, context)
            model_info = router_v2.get_model_for_agent(st.agent_type)
            print(f'  [V3] {st.agent_type} -> modele: {model_info["provider"]}')
            result = agent.execute_with_client(
                task={'task_id': dag.task_id, 'subtask_id': st.id, 'description': st.description},
                context=context,
                client=model_info['client'],
                model_name=model_info['model'],
            )
            st.result = result
            st.status = 'done'
            summary = (
                result.get('summary', result.get('resume', str(result)[:100]))
                if isinstance(result, dict) else str(result)[:100]
            )
            log_progress(dag.task_id, subtask_id, st.agent_type, 'DONE', summary[:100])
            _update_task(dag.task_id, st, 'done', result=result)
            _record_metrics(agent, dag.task_id, True, time.time() - start)
        except Exception as e:
            st.error = str(e)
            st.status = 'failed'
            log_progress(dag.task_id, subtask_id, st.agent_type, 'ERROR', str(e)[:100])
            _update_task(dag.task_id, st, 'failed', error=str(e))
            if agent:
                _record_metrics(agent, dag.task_id, False, time.time() - start)
        with lock:
            remaining.discard(subtask_id)
            running.discard(subtask_id)

    max_wait = 180
    start_total = time.time()
    while remaining and (time.time() - start_total) < max_wait:
        with lock:
            runnable = [
                sid for sid in remaining
                if sid not in running
                and all(
                    dag.subtasks[dep].status == 'done'
                    for dep in dag.subtasks[sid].depends_on
                    if dep in dag.subtasks
                )
                and not any(
                    dag.subtasks[dep].status == 'failed'
                    for dep in dag.subtasks[sid].depends_on
                    if dep in dag.subtasks
                )
            ]
        for sid in runnable:
            with lock:
                running.add(sid)
            threading.Thread(target=run_subtask, args=(sid,), daemon=True).start()
        time.sleep(0.3)

    _persist_dag(dag)
    return dag
