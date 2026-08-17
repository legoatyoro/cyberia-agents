import subprocess, sys
from pathlib import Path


def run_mode(mode_id: int, args: dict, context: dict) -> dict:
    project_dir = None
    if context.get('current_project'):
        project_dir = Path(context['current_project']['path'])
    elif args.get('project_path'):
        project_dir = Path(args['project_path'])

    if mode_id == 2:
        description = args.get('description', context.get('message', ''))
        return _run_generation(description)
    elif mode_id == 3:
        if not project_dir or not project_dir.exists():
            try:
                projects = sorted(
                    [p for p in Path('generated').iterdir() if p.is_dir()],
                    key=lambda p: p.stat().st_mtime, reverse=True
                )
                if projects:
                    project_dir = projects[0]
            except Exception:
                pass
        return _run_analysis(project_dir)
    elif mode_id == 5:
        return _run_launch(project_dir)
    elif mode_id == 10:
        return _run_atelier(project_dir)
    elif mode_id == 15:
        subprocess.run([sys.executable, 'cyberia_dashboard.py'])
        return {'status': 'done', 'output': 'Dashboard ferme'}
    elif mode_id == 19:
        return _run_conseil(project_dir)
    elif mode_id == 20:
        return _run_tests(project_dir)
    elif mode_id == 22:
        return {'status': 'redirect', 'mode': 22, 'message': 'Mode A-Z lance en mode interactif'}
    else:
        return {'status': 'unknown', 'output': f'Mode {mode_id} non supporte'}


def _run_generation(description: str) -> dict:
    try:
        from core.orchestrator import Orchestrator
        result = Orchestrator().run(description)
        if not isinstance(result, dict):
            return {'status': 'error', 'output': f'Reponse orchestrateur invalide: {type(result)}'}
        name = (result.get('project_name')
                or result.get('project')
                or result.get('name')
                or 'projet_genere')
        files = result.get('files_generated', result.get('files', 0))
        score = result.get('score', result.get('final_score', 0))
        # Indexation en arriere-plan apres generation
        import threading
        project_path = str(Path('generated') / name)
        threading.Thread(
            target=_index_project_bg,
            args=(project_path,),
            daemon=True
        ).start()
        return {
            'status': 'success',
            'project_name': name,
            'files': files,
            'score': score,
            'output': f'Projet {name} genere ({files} fichiers, score {score}/10)',
        }
    except Exception as e:
        import traceback
        return {'status': 'error', 'output': f'{e}\n{traceback.format_exc()[-300:]}'}


def _index_project_bg(project_path: str):
    try:
        from core.project_indexer import index_project
        index_project(project_path)
    except Exception:
        pass


def _run_analysis(project_dir) -> dict:
    if not project_dir or not project_dir.exists():
        return {'status': 'error', 'output': 'Dossier projet introuvable'}
    try:
        from core.file_analyzer import FileAnalyzer
        result = FileAnalyzer().analyze_project(project_dir)
        n = result.get('files_analyzed', 0)
        if n == 0:
            all_files = [f.name for f in project_dir.rglob('*') if f.is_file()]
            return {
                'status': 'success',
                'output': f'Projet {project_dir.name} : aucun fichier source (.py/.ts/.js) trouve.\nFichiers presents : {", ".join(all_files[:10])}',
                'details': result,
            }
        return {
            'status': 'success',
            'output': f'{n} fichier(s) analyse(s) dans {project_dir.name}',
            'details': result,
        }
    except Exception as e:
        import traceback
        return {'status': 'error', 'output': f'{e}\n{traceback.format_exc()[-200:]}'}


def _run_atelier(project_dir) -> dict:
    if not project_dir:
        return {'status': 'error', 'output': 'Projet requis pour l Atelier'}
    return {
        'status': 'redirect',
        'mode': 10,
        'project': str(project_dir),
        'message': 'Lancement Mode Atelier interactif',
    }


def _run_conseil(project_dir) -> dict:
    if not project_dir:
        return {'status': 'error', 'output': 'Projet requis pour le Conseil'}
    try:
        from core.agent_council import AgentCouncil
        opinions, consensus = AgentCouncil().collaborative_review(str(project_dir))
        agents_summary = '\n'.join(
            f'{d["agent"]["name"]}: {d["opinion"][:150]}' for d in opinions.values()
        )
        return {'status': 'success', 'output': f'Consensus:\n{consensus[:400]}\n\nAgents:\n{agents_summary}'}
    except Exception as e:
        return {'status': 'error', 'output': str(e)}


def _run_launch(project_dir) -> dict:
    if not project_dir:
        return {'status': 'error', 'output': 'Projet requis pour le lancement'}
    try:
        result = subprocess.run(
            [sys.executable, 'launch.py', project_dir.name],
            capture_output=True, text=True, timeout=30
        )
        return {'status': 'success', 'output': result.stdout[:500] or 'Lance'}
    except Exception as e:
        return {'status': 'error', 'output': str(e)}


def _run_tests(project_dir) -> dict:
    if not project_dir:
        return {'status': 'error', 'output': 'Projet requis'}
    try:
        from core.test_generator import TestGenerator
        generated = TestGenerator().generate_project_tests(project_dir)
        return {
            'status': 'success',
            'output': f'{len(generated)} fichier(s) de tests generes',
            'files': generated,
        }
    except Exception as e:
        return {'status': 'error', 'output': str(e)}


def run_with_test(project_name: str) -> dict:
    from core.api_tester import ApiTester
    project_dir = Path('generated') / project_name
    if not project_dir.exists():
        return {'status': 'error', 'output': f'Projet {project_name} introuvable'}
    tester = ApiTester(str(project_dir))
    started, msg = tester.start_server()
    if started:
        results = tester.run_quick_tests()
        ok_count = sum(1 for r in results if r.get('ok'))
        tester.open_docs()
        output = (f'Serveur demarre. {ok_count}/{len(results)} endpoints repond.\n'
                  f'Docs ouvertes : {tester.base_url}/docs')
        tester.stop()
    else:
        output = f'Serveur non demarre : {msg}'
    return {'status': 'success' if started else 'error', 'output': output}
