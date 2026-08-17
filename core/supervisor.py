import json, re
from pathlib import Path
from core.intent_classifier import classify_intent
from core.context_builder import build_context, get_projects

MODE_MAP = {
    'GENERATE_PROJECT': lambda args: 22 if 'a-z' in args.get('flags', []) else 2,
    'ANALYZE_PROJECT': lambda args: 19 if args.get('complexity') == 'strategic' else (10 if args.get('complexity') == 'deep_refactor' else 3),
    'FIX_ERRORS': lambda args: 22 if args.get('full_pipeline') else 10,
    'RUN_PROJECT': lambda args: 5,
    'GENERATE_TESTS': lambda args: 20,
    'COUNCIL_AGENTS': lambda args: 19,
    'EVOLUTION_MODE': lambda args: 13,
    'SCAN_MODE': lambda args: 17,
    'IMPORT_PROJECT': lambda args: 16,
    'DASHBOARD': lambda args: 15,
    'SHOW_PROJECTS': lambda args: None,
    'SWITCH_PROJECT': lambda args: None,
    'MEMORY_QUERY': lambda args: None,
    'ASK_QUESTION': lambda args: None,
    'GENERAL_CHAT': lambda args: None,
}

ACTIONS_MAP = {
    2:  [('a', 'Analyser le resultat'), ('w', 'Corriger en Atelier'), ('l', 'Lancer'), ('t', 'Generer tests')],
    3:  [('w', 'Corriger les bugs'), ('c', 'Conseil Agents'), ('t', 'Tests auto')],
    10: [('a', 'Re-analyser'), ('t', 'Tests'), ('l', 'Lancer'), ('c', 'Conseil')],
    19: [('w', 'Appliquer en Atelier'), ('a', 'Analyser'), ('t', 'Tests')],
    20: [('l', 'Lancer les tests'), ('w', 'Corriger'), ('a', 'Analyser')],
    5:  [('a', 'Analyser'), ('w', 'Atelier'), ('t', 'Tests')],
}


class Supervisor:
    def __init__(self):
        self.history = []
        self.current_project = None
        self.session_state = {'last_mode_used': None, 'last_error': None}
        self.co_creation = None
        self.in_co_creation = False
        self.project_dir_from_dag = None

    def handle(self, message: str) -> dict:
        # Route vers la session de co-creation active
        if self.in_co_creation and self.co_creation:
            result = self.co_creation.chat(message)
            if result.get('action') == 'restart':
                self.in_co_creation = False
                self.co_creation = None
            self.history.append({'role': 'user', 'content': message})
            self.history.append({'role': 'assistant', 'content': result['reply'][:500]})
            if len(self.history) > 12:
                self.history = self.history[-12:]
            return {'reply': result['reply'], 'actions': [], 'intent': 'CO_CREATION', 'mode': None, 'redirect': None}

        if self.session_state.get('last_mode_used') == 'DAG' and message.strip().lower() in ('a', 'c', 't', 'architecture', 'code', 'tests'):
            last_dag_id = self.session_state.get('last_dag_id')
            if last_dag_id:
                from core.supervisor_v2 import get_conn
                conn = get_conn()
                row = conn.execute('SELECT dag_json FROM tasks_dag WHERE id=? ORDER BY created_at DESC LIMIT 1', (last_dag_id,)).fetchone()
                conn.close()
                if row:
                    import json
                    dag_data = json.loads(row['dag_json'])
                    subtasks = dag_data.get('subtasks', {})
                    key_map = {'a': 'architecture', 'c': 'code', 't': 'tests', 'architecture': 'architecture', 'code': 'code', 'tests': 'tests'}
                    target = key_map.get(message.strip().lower(), 'architecture')
                    st = subtasks.get(target, {})
                    result = st.get('result') or {}
                    if isinstance(result, dict):
                        import json as j
                        formatted = j.dumps(result, indent=2, ensure_ascii=False)[:2000]
                    else:
                        formatted = str(result)[:2000]
                    reply = f'Detail de l etape {target} :\n\n{formatted}'
                    return {'reply': reply, 'actions': [{'key': 'a', 'label': 'Architecture'}, {'key': 'c', 'label': 'Code'}, {'key': 't', 'label': 'Tests'}, {'key': 'l', 'label': 'Lancer le projet'}], 'intent': 'DAG_DETAIL', 'mode': None, 'redirect': None}

        intent_data = classify_intent(message)
        intent = intent_data.get('intent', 'GENERAL_CHAT')
        args = intent_data.get('arguments', {})

        if intent == 'SWITCH_PROJECT':
            return self._handle_switch_project(args, message)

        if intent == 'SHOW_PROJECTS':
            return self._handle_show_projects()

        if intent == 'MEMORY_QUERY':
            return self._handle_memory_query(message)

        # Orchestration DAG pour projets complexes (priorite sur co-creation)
        COMPLEX_KEYWORDS = [
            'scanner', 'systeme', 'complexe', 'performant', 'agents', 'automatise',
            'complet', 'distribue', 'pipeline', 'orchestr', 'multi', 'avance',
            'intelligent',
        ]
        if intent == 'GENERATE_PROJECT' and any(kw in message.lower() for kw in COMPLEX_KEYWORDS):
            return self._handle_with_dag(message)

        # Demarrer une session co-creation pour GENERATE_PROJECT
        if intent == 'GENERATE_PROJECT':
            alignment_note = ''
            try:
                from core.business_context import check_alignment
                note = check_alignment(message)
                if note:
                    alignment_note = f'{note}\n\n'
            except Exception:
                pass
            from core.co_creation import CoCreationSession
            self.co_creation = CoCreationSession()
            self.in_co_creation = True
            result = self.co_creation.chat(message)
            reply = alignment_note + result['reply']
            self.history.append({'role': 'user', 'content': message})
            self.history.append({'role': 'assistant', 'content': reply[:500]})
            if len(self.history) > 12:
                self.history = self.history[-12:]
            return {'reply': reply, 'actions': [], 'intent': 'CO_CREATION', 'mode': None, 'redirect': None}

        context = build_context(message, intent, self.history, self.current_project, self.session_state)

        mode_fn = MODE_MAP.get(intent, lambda a: None)
        mode_id = mode_fn(args) if callable(mode_fn) else None

        if mode_id and intent not in ('ASK_QUESTION', 'GENERAL_CHAT'):
            from core.modes_router import run_mode
            result = run_mode(mode_id, args, context)
            if result.get('status') == 'redirect':
                reply = result['message']
                redirect = result.get('mode')
            else:
                reply = self._format_result(result, intent, mode_id)
                redirect = None

            if result.get('project_name'):
                projects = get_projects()
                found = next((p for p in projects if p['name'] == result['project_name']), None)
                if found:
                    self.current_project = found

            self.session_state['last_mode_used'] = mode_id
            actions = self._suggest_actions(mode_id, result)
        else:
            reply = self._llm_response(message, context)
            redirect = None
            actions = self._suggest_actions(None, {})

        self.history.append({'role': 'user', 'content': message})
        self.history.append({'role': 'assistant', 'content': reply[:500]})
        if len(self.history) > 12:
            self.history = self.history[-12:]

        return {'reply': reply, 'actions': actions, 'intent': intent, 'mode': mode_id, 'redirect': redirect}

    def _handle_with_dag(self, message: str) -> dict:
        from core.supervisor_v2 import decompose_task, execute_dag, collect_results, present_to_user
        from core.context_builder import build_context
        context = build_context(message, 'GENERATE_PROJECT', self.history, self.current_project, self.session_state)
        print(f'  [DAG] Decomposition de la tache : {message[:60]}')
        dag = decompose_task(message)
        print(f'  [DAG] {len(dag.subtasks)} agents crees : {list(dag.subtasks.keys())}')
        try:
            from core.supervisor_v3 import execute_dag_v3
            dag = execute_dag_v3(dag, context={'domain': 'backend', 'business': message})
        except ImportError:
            from core.supervisor_v2 import execute_dag
            dag = execute_dag(dag, context={'domain': 'backend', 'business': message})
        self.session_state['last_dag_id'] = dag.task_id
        results = collect_results(dag)
        code_subtask = dag.subtasks.get('code')
        if code_subtask and code_subtask.result and isinstance(code_subtask.result, dict):
            fichiers = code_subtask.result.get('fichiers', [])
            if fichiers:
                import re
                project_name = re.sub(r'[^a-z0-9-]', '-', dag.root_description.lower()[:30].strip()) + '-dag'
                project_dir = Path('generated') / project_name
                project_dir.mkdir(parents=True, exist_ok=True)
                for f in fichiers:
                    if isinstance(f, dict) and f.get('nom') and f.get('contenu'):
                        fpath = project_dir / f['nom']
                        fpath.parent.mkdir(parents=True, exist_ok=True)
                        fpath.write_text(str(f['contenu']), encoding='utf-8')
                print(f'  [DAG] {len(fichiers)} fichiers ecrits dans generated/{project_name}')
                self.current_project = {'name': project_name, 'path': str(project_dir), 'stack': 'python'}
                self.project_dir_from_dag = project_dir
                try:
                    import subprocess, threading as _th
                    subprocess.Popen([
                        'powershell', '-NoExit', '-Command',
                        f'Write-Host "=== TEST : {project_name} ===" -ForegroundColor Green; '
                        f'Set-Location "{project_dir}"; '
                        f'if (Test-Path requirements.txt) {{ pip install -r requirements.txt -q }}; '
                        f'if (Test-Path main.py) {{ python main.py }} '
                        f'elseif (Test-Path app.py) {{ python app.py }} '
                        f'else {{ Write-Host "Fichier principal non trouve" -ForegroundColor Red }}'
                    ], creationflags=subprocess.CREATE_NEW_CONSOLE)

                    def _open_browser():
                        import time as _t, webbrowser
                        _t.sleep(6)
                        webbrowser.open('http://localhost:8000/docs')
                    _th.Thread(target=_open_browser, daemon=True).start()
                    print(f'  [DAG] Fenetre PowerShell ouverte pour les tests de {project_name}')
                except Exception as _e:
                    print(f'  [DAG] Impossible d\'ouvrir PowerShell : {_e}')
        reply = present_to_user(results)
        done_count = sum(1 for st in dag.subtasks.values() if st.status == 'done')
        agents_list = ', '.join(list(dag.subtasks.keys()))
        self.session_state['last_mode_used'] = 'DAG'
        return {
            'reply': f'Orchestration terminee : {done_count}/{len(dag.subtasks)} agents reussis.\nAgents utilises : {agents_list}\n\n{reply}',
            'actions': [
                {'key': 'a', 'label': 'Voir architecture'},
                {'key': 'c', 'label': 'Code genere'},
                {'key': 't', 'label': 'Tests'},
            ],
            'intent': 'DAG_COMPLETE', 'mode': None, 'redirect': None,
        }

    def stream(self, message: str):
        intent_data = classify_intent(message, use_llm=False)
        intent = intent_data.get('intent', 'GENERAL_CHAT')
        context = build_context(message, intent, self.history, self.current_project, self.session_state)
        import os
        from openai import OpenAI
        directives_text = '\n'.join(f'- {d}' for d in context['directives'])
        memory_text = '\n'.join(f'- {m}' for m in context['memory'][:3])
        project_info = f'Projet en cours: {context["current_project"]["name"]}' if context.get('current_project') else 'Aucun projet en cours'
        system = f'''Tu es CYBERIA, assistant IA personnel de Yoro.
{project_info}
Directives:
{directives_text}
Contexte memoire:
{memory_text}
Reponds en francais. Sois concis et actionnable.'''
        messages = [{'role': 'system', 'content': system}]
        for h in (self.history or [])[-4:]:
            messages.append(h)
        messages.append({'role': 'user', 'content': message})
        try:
            client = OpenAI(api_key=os.getenv('DEEPSEEK_API_KEY'), base_url='https://api.deepseek.com')
            stream = client.chat.completions.create(model='deepseek-chat', messages=messages, stream=True, max_tokens=800)
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f'Erreur: {e}'

    def _format_result(self, result: dict, intent: str, mode_id: int) -> str:
        if result.get('status') == 'error':
            return f'Erreur: {result.get("output", "?")}'
        output = result.get('output', '')
        prefix = {
            2: 'Projet genere', 3: 'Analyse terminee', 10: 'Atelier termine',
            19: 'Conseil rendu', 20: 'Tests generes', 5: 'Projet lance',
        }.get(mode_id, 'Fait')
        return f'{prefix}.\n{output}'

    def _suggest_actions(self, mode_id, result) -> list:
        base = list(ACTIONS_MAP.get(mode_id, [('g', 'Generer projet'), ('a', 'Analyser'), ('c', 'Conseil')]))
        if mode_id == 2 and self.current_project:
            proj_name = self.current_project.get('name', '')
            base[0] = ('a', f'Analyser {proj_name}')
        return [{'key': k, 'label': l} for k, l in base[:4]]

    def _llm_response(self, message: str, context: dict) -> str:
        from core.multi_model_router import MultiModelRouter
        router = MultiModelRouter()
        directives = '\n'.join(f'- {d}' for d in context.get('directives', [])[:6])
        memory = '\n'.join(f'- {m}' for m in context.get('memory', [])[:4])
        history = context.get('history', self.history)
        history_txt = '\n'.join(
            f'{m["role"]}: {m["content"][:200]}' for m in history[-4:]
        )
        project = context.get('current_project') or self.current_project or {}
        proj_name = project.get('name', 'aucun')
        proj_path = project.get('path', '')
        files_txt = ''
        if proj_path:
            try:
                files = [f for f in Path(proj_path).rglob('*.py') if '__pycache__' not in str(f)][:8]
                files_txt = ', '.join(f.name for f in files)
            except Exception:
                pass

        try:
            from core.enrichment import get_directives, get_stats as get_enrich_stats
            directives_db = get_directives()
            directives_txt = '\n'.join(f'- [{d["category"]}] {d["value"]}' for d in directives_db[:6])
            enrich_stats = get_enrich_stats()
            enrichment_block = f'DIRECTIVES COMPORTEMENTALES:\n{directives_txt}\n\nKNOWLEDGE BASE: {enrich_stats["fix_patterns"]} patterns de fix, {enrich_stats["code_patterns"]} patterns de code'
        except Exception:
            enrichment_block = ''

        system = f'''Tu es CYBERIA, l assistant IA personnel de Yoro. Tu es expert en developpement logiciel, architecture, et cybersecurite.

PROJET EN COURS: {proj_name}
{f"Fichiers: {files_txt}" if files_txt else ""}

DIRECTIVES YORO:
{directives}

{enrichment_block}

MEMOIRE CONTEXTUELLE:
{memory}

HISTORIQUE RECENT:
{history_txt}

REGLES:
- Reponds en francais, de facon concise et actionnable
- Propose toujours 2-3 actions concretes apres ta reponse
- Si l utilisateur parle d un projet, utilise le contexte du projet en cours
- Si tu detectes un bug ou probleme, dis-le directement avec le fix
- Ne genere PAS de code directement sauf si explicitement demande
- Quand tu ne sais pas, dis-le et propose une alternative'''

        try:
            from core.business_context import get_context_block as get_biz
            biz_ctx = get_biz()
            if biz_ctx:
                system = biz_ctx + '\n\n' + system
        except Exception:
            pass

        return router.call(f'{system}\n\nUtilisateur: {message}', task_type='analysis')

    def _handle_show_projects(self) -> dict:
        projects = get_projects()
        if not projects:
            return {
                'reply': 'Aucun projet genere. Dis-moi quoi creer !',
                'actions': [{'key': 'g', 'label': 'Generer un projet'}],
                'intent': 'SHOW_PROJECTS', 'mode': None, 'redirect': None,
            }
        lines = ['Tes projets :\n']
        for i, p in enumerate(projects[:10], 1):
            score = p.get('score', 0)
            lines.append(f'  {i}. {p["name"]} - {score}/10')
        lines.append('\nDis-moi lequel analyser, corriger ou lancer !')
        return {
            'reply': '\n'.join(lines),
            'actions': [
                {'key': 'a', 'label': 'Analyser un projet'},
                {'key': 'w', 'label': 'Atelier'},
                {'key': 'g', 'label': 'Generer'},
            ],
            'intent': 'SHOW_PROJECTS', 'mode': None, 'redirect': None,
        }

    def _handle_switch_project(self, args, message) -> dict:
        projects = get_projects()
        name_query = args.get('project_name', '').lower() or message.lower()
        match = next(
            (p for p in projects if p['name'].lower() in name_query or name_query in p['name'].lower()),
            None
        )
        if match:
            self.current_project = match
            return {
                'reply': f'Projet change : maintenant sur {match["name"]}',
                'actions': [{'key': 'a', 'label': 'Analyser'}, {'key': 'w', 'label': 'Atelier'}],
                'intent': 'SWITCH_PROJECT', 'mode': None, 'redirect': None,
            }
        return {
            'reply': 'Projet non trouve. Projets disponibles :\n' + '\n'.join(p['name'] for p in projects[:5]),
            'actions': [],
            'intent': 'SWITCH_PROJECT', 'mode': None, 'redirect': None,
        }

    def _handle_memory_query(self, message) -> dict:
        try:
            from core.memory_hub import get_context_block
            ctx = get_context_block(message, min_similarity=0.2)
            if ctx:
                lines = [l for l in ctx.split('\n') if l.startswith('-')][:6]
                reply = 'Voici ce que je sais sur toi :\n' + '\n'.join(lines)
            else:
                reply = "Je n'ai pas encore beaucoup de souvenirs. Parle-moi de tes projets !"
        except Exception:
            reply = 'Memoire momentanement indisponible.'
        return {
            'reply': reply,
            'actions': [{'key': 'g', 'label': 'Generer un projet'}],
            'intent': 'MEMORY_QUERY', 'mode': None, 'redirect': None,
        }
