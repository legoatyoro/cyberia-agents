import json, sys, argparse, time as _time, concurrent.futures
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.env_loader import load_env
from core.multi_model_router_v2 import router_v2

_pipeline_start = None


def log_progress_v2(task_id, agent_name, status, action, step, total, result_preview=''):
    global _pipeline_start
    if _pipeline_start is None:
        _pipeline_start = _time.time()
    elapsed = round(_time.time() - _pipeline_start, 1)
    event = {
        'ts': _time.time(),
        'agent': agent_name,
        'status': status,
        'action': action,
        'step': step,
        'total': total,
        'elapsed': elapsed,
        'result_preview': str(result_preview)[:100],
    }
    pf = Path('.cyberia/dag_progress.jsonl')
    pf.parent.mkdir(exist_ok=True)
    with pf.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')

PIPELINE_SECU = [
    'AgentSecurite', 'AgentOWASP', 'AgentArchitecture',
    'AgentCode', 'AgentTest', 'AgentOptimisation', 'AgentMeta',
]


def _run_agent_safe(agent_tuple, task, context):
    agent_name, agent = agent_tuple
    try:
        log_progress_v2('secu', agent_name, 'START', f'Demarrage {agent_name}', 0, 7)
        result = agent.execute(task, context)
        summary = result.get('summary', '') if isinstance(result, dict) else ''
        log_progress_v2('secu', agent_name, 'DONE', f'{agent_name} termine', 1, 7, summary[:80])
        print(f'  [PIPELINE] {agent_name} OK: {summary[:60]}')
        return agent_name, result
    except Exception as e:
        log_progress_v2('secu', agent_name, 'ERROR', str(e)[:80], 0, 7)
        print(f'  [PIPELINE] {agent_name} ERREUR: {e}')
        return agent_name, {'summary': f'Erreur: {e}', 'error': str(e)}


def _merge_result(context, result):
    if not isinstance(result, dict):
        return
    context['patterns'].extend(result.get('patterns', []))
    if result.get('vulnerabilites'):
        context['vulnerabilites'] = result['vulnerabilites']
    if result.get('owasp_mapping'):
        context['owasp'] = result['owasp_mapping']
    if result.get('architecture'):
        context['architecture'] = result['architecture']
    if result.get('composants'):
        context['composants'] = result['composants']
    if result.get('fichiers'):
        context['fichiers'] = result['fichiers']


def run_secu_pipeline(description: str, write_files: bool = True) -> dict:
    load_env()
    print(f'\n[SECU_PIPELINE] Demarrage pour: {description[:60]}')

    from agents.agent_securite_v2 import AgentSecuriteV2
    from agents.agent_owasp_v2 import AgentOWASPV2
    from agents.agent_architecture_v3 import AgentArchitectureV3
    from agents.agent_code_v3 import AgentCodeV3
    from agents.agent_test_v3 import AgentTestV3
    from agents.agent_optimisation_v3 import AgentOptimisationV3
    from agents.agent_meta_v1 import AgentMetaV1

    task = {'description': description}
    context = {'patterns': [], 'agents_results': {}, 'errors': []}
    total_agents = 7

    global _pipeline_start
    _pipeline_start = None

    # Groupe 1 (parallele) : AgentSecurite + AgentOWASP
    print('  [PIPELINE] Groupe 1 (parallele): AgentSecurite + AgentOWASP')
    group1 = [('AgentSecurite', AgentSecuriteV2()), ('AgentOWASP', AgentOWASPV2())]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(_run_agent_safe, ag, task, context): ag[0] for ag in group1}
        for f in concurrent.futures.as_completed(futures):
            name, result = f.result()
            context['agents_results'][name] = result
            _merge_result(context, result)
            if isinstance(result, dict) and result.get('error'):
                context['errors'].append(f'{name}: {result["error"]}')

    # Groupe 2 : AgentArchitecture (depends de groupe 1)
    print('  [PIPELINE] Groupe 2: AgentArchitecture')
    name, result = _run_agent_safe(('AgentArchitecture', AgentArchitectureV3()), task, context)
    context['agents_results'][name] = result
    _merge_result(context, result)
    if isinstance(result, dict) and result.get('error'):
        context['errors'].append(f'{name}: {result["error"]}')

    # Groupe 3 (parallele) : AgentCode + AgentTest
    print('  [PIPELINE] Groupe 3 (parallele): AgentCode + AgentTest')
    group3 = [('AgentCode', AgentCodeV3()), ('AgentTest', AgentTestV3())]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(_run_agent_safe, ag, task, context): ag[0] for ag in group3}
        for f in concurrent.futures.as_completed(futures):
            name, result = f.result()
            context['agents_results'][name] = result
            _merge_result(context, result)
            if isinstance(result, dict) and result.get('error'):
                context['errors'].append(f'{name}: {result["error"]}')

    # Groupe 4 : AgentOptimisation puis AgentMeta
    print('  [PIPELINE] Groupe 4: AgentOptimisation + AgentMeta')
    for ag in [('AgentOptimisation', AgentOptimisationV3()), ('AgentMeta', AgentMetaV1())]:
        name, result = _run_agent_safe(ag, task, context)
        context['agents_results'][name] = result
        _merge_result(context, result)
        if isinstance(result, dict) and result.get('error'):
            context['errors'].append(f'{name}: {result["error"]}')

    if write_files and context.get('fichiers'):
        project_name = description[:25].lower().replace(' ', '-').replace('"', '') + '-secu'
        project_dir = Path('generated') / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        for f in context['fichiers']:
            if isinstance(f, dict) and f.get('path') and f.get('content'):
                fpath = project_dir / f['path']
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(str(f['content']), encoding='utf-8')
        print(f'  [PIPELINE] Fichiers ecrits dans generated/{project_name}')

    try:
        from tools.memory_hub_v3 import add_pattern
        for p in context['patterns'][:20]:
            if isinstance(p, dict):
                add_pattern(p)
            elif isinstance(p, str) and len(p) > 10:
                add_pattern({'type': 'raw', 'content': p, 'source': 'pipeline'})
    except Exception as e:
        print(f'  [PIPELINE] MemoryHub: {e}')

    done = sum(1 for r in context['agents_results'].values() if r.get('summary'))
    total = len(agents)
    print(f'\n[SECU_PIPELINE] {done}/{total} agents reussis, {len(context["errors"])} erreur(s)')
    return context


def run_scan_only(description: str) -> dict:
    from agents.agent_securite_v2 import AgentSecuriteV2
    from agents.agent_owasp_v2 import AgentOWASPV2
    task = {'description': description}
    context = {}
    sec = AgentSecuriteV2().execute(task, context)
    owasp = AgentOWASPV2().execute(task, context)
    return {
        'securite': sec,
        'owasp': owasp,
        'summary': f'{len(sec.get("vulnerabilites", []))} vulns, score OWASP: {owasp.get("score", 0)}',
    }


def run_local_mode(prompt: str) -> dict:
    from agents.agent_local import AgentLocal
    return AgentLocal().execute({'description': prompt}, {})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CYBERIA Security Pipeline')
    parser.add_argument('--pipeline', type=str, help='Pipeline securite complet')
    parser.add_argument('--scan', type=str, help='Scan rapide vulnerabilites')
    parser.add_argument('--local', type=str, help='Mode Ollama local')
    args = parser.parse_args()
    if args.pipeline:
        result = run_secu_pipeline(args.pipeline)
        print(json.dumps({'summary': f'{len(result["agents_results"])} agents', 'errors': result['errors']}, indent=2))
    elif args.scan:
        print(json.dumps(run_scan_only(args.scan), indent=2, ensure_ascii=False))
    elif args.local:
        print(json.dumps(run_local_mode(args.local), indent=2, ensure_ascii=False))
    else:
        print('Usage: python core/secu_pipeline.py --pipeline "scanner web" ou --scan "projet" ou --local "question"')
