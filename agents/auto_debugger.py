import subprocess
import sys
import socket
import time
import re
import threading
from pathlib import Path
from core.runtime_rules import KNOWN_ERRORS, PORT_RANGE, find_matching_error
from core.multi_model_router import get_router
from schemas.agent_schemas import AgentOutput


def find_free_port(start: int = 8000) -> int:
    for port in PORT_RANGE:
        if port < start:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    return 8099


def kill_port(port: int):
    if sys.platform == 'win32':
        try:
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True, text=True
            )
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    pid = line.strip().split()[-1]
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                   capture_output=True)
                    print(f'  🔪 Process sur port {port} tué (PID {pid})')
        except Exception:
            pass
    else:
        subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)


def check_server_ready(port: int, timeout: int = 15) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://localhost:{port}/', timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def apply_known_fix(main_file: Path, error_info: dict, stderr: str, port: int) -> bool:
    fix_type = error_info['fix_type']
    content = main_file.read_text(encoding='utf-8', errors='ignore')

    if fix_type == 'append':
        if 'uvicorn.run' not in content:
            content += error_info['fix_content'].replace(
                'port=8000', f'port={port}'
            )
            main_file.write_text(content, encoding='utf-8')
            return True

    elif fix_type == 'replace':
        if error_info['fix_old'] in content:
            content = content.replace(error_info['fix_old'], error_info['fix_new'])
            main_file.write_text(content, encoding='utf-8')
            return True

    elif fix_type == 'replace_jinja2':
        if 'Jinja2Templates' in content or 'TemplateResponse' in content:
            content = content.replace('from fastapi.templating import Jinja2Templates', '')
            content = content.replace('from starlette.templating import Jinja2Templates', '')
            content = re.sub(r'templates\s*=\s*Jinja2Templates\([^)]+\)', '', content)
            content = re.sub(
                r'return templates\.TemplateResponse\([^)]+\)',
                'return HTMLResponse("<html><body><h1>App Running</h1><a href=/docs>API Docs</a></body></html>")',
                content
            )
            if 'HTMLResponse' not in content:
                content = content.replace(
                    'from fastapi.responses import',
                    'from fastapi.responses import HTMLResponse,'
                )
            main_file.write_text(content, encoding='utf-8')
            return True

    elif fix_type == 'change_port':
        kill_port(port)
        new_port = find_free_port(port + 1)
        content = content.replace(f'port={port}', f'port={new_port}')
        main_file.write_text(content, encoding='utf-8')
        return True

    elif fix_type == 'install_module':
        match = re.search(r"No module named '([^']+)'", stderr)
        if match:
            pkg = match.group(1).split('.')[0]
            LOCAL_MODULES = {
                'database', 'models', 'schemas', 'services', 'agents',
                'api', 'utils', 'config', 'main', 'app', 'core',
                'auth', 'routers', 'middleware', 'helpers', 'constants',
                'routes', 'controllers', 'repositories', 'exceptions',
                'dependencies', 'security', 'tasks', 'workers',
                'migrations', 'seeds', 'fixtures', 'tests', 'test',
                'conftest', 'settings', 'celery', 'wsgi', 'asgi',
                'manage', 'admin', 'views', 'serializers', 'permissions',
                'signals', 'apps', 'forms', 'filters', 'validators',
                'mixins', 'managers', 'querysets', 'abstract', 'base',
                'common', 'shared', 'types', 'interfaces', 'protocols',
                'prediction_agent', 'match_agent', 'stats_agent',
                'agent_manager', 'match_service', 'stats_service',
                'prediction_service', 'notification_service',
                'export_service', 'search_service', 'kanban_service',
                'dashboard_service', 'comment_service', 'user_service',
                'project_service', 'task_service', 'auth_service',
            }
            if pkg not in LOCAL_MODULES:
                subprocess.run([sys.executable, '-m', 'pip', 'install', pkg, '-q'],
                               capture_output=True)
                return True
    return False


def deepseek_fix(main_file: Path, stderr: str, port: int) -> bool:
    router = get_router()
    content = main_file.read_text(encoding='utf-8', errors='ignore')
    prompt = f'''Un projet FastAPI Python 3.14 ne démarre pas. Corrige le fichier pour qu'il démarre.

ERREUR :
{stderr[:2000]}

CODE ACTUEL (main.py) :
{content[:4000]}

RÈGLES ABSOLUES :
- Utiliser from sqlalchemy.orm import declarative_base
- JAMAIS Jinja2Templates ou TemplateResponse
- Toujours terminer par if __name__ == '__main__': uvicorn.run(app, host='0.0.0.0', port={port})
- Route / doit retourner HTMLResponse
- Tous les imports doivent être corrects

Retourne UNIQUEMENT le fichier main.py complet et corrigé, sans markdown.'''

    fixed = router.call(prompt, task_type='debug', temperature=0.1)
    try:
        from cyberia_sanitizer import strip_markdown_artifacts
        fixed = strip_markdown_artifacts(fixed)
    except ImportError:
        pass
    if fixed and len(fixed) > 100:
        try:
            from cyberia_sanitizer import strip_markdown_artifacts
            fixed = strip_markdown_artifacts(fixed)
            import ast
            ast.parse(fixed)
            backup = main_file.with_suffix('.py.auto_debug_bak')
            if main_file.exists():
                backup.write_text(main_file.read_text(encoding='utf-8', errors='replace'), encoding='utf-8')
            main_file.write_text(fixed, encoding='utf-8')
            print(f'  💾 main.py sauvegardé ({len(fixed.splitlines())} lignes)')
            return True
        except SyntaxError as e:
            print(f'  ⚠️ Fix DeepSeek invalide syntaxiquement : {e}')
            return False
        except Exception as e:
            print(f'  ⚠️ Erreur sauvegarde : {e}')
            return False
    return False


class AutoDebugger:
    def __init__(self):
        self.name = 'AUTO_DEBUGGER'
        self.max_cycles = 5

    def run(self, project_dir: Path, phase: str = 'backend') -> AgentOutput:
        print(f'\n🔧 [{self.name}] Phase {phase} — Test de démarrage...')
        main_file = project_dir / 'main.py'
        if not main_file.exists():
            return AgentOutput(agent_name=self.name, success=False, artifacts={},
                               errors=['main.py introuvable'])

        port = find_free_port()
        kill_port(port)

        fixes_applied = []
        stderr_buffer = []

        for cycle in range(1, self.max_cycles + 1):
            print(f'  🔄 Cycle {cycle}/{self.max_cycles} (port {port})...')

            content = main_file.read_text(encoding='utf-8', errors='ignore')
            if f'port={port}' not in content and 'uvicorn.run' in content:
                content = re.sub(r'port=\d+', f'port={port}', content)
                main_file.write_text(content, encoding='utf-8')

            proc = subprocess.Popen(
                [sys.executable, str(main_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(project_dir)
            )

            stderr_lines = []

            def read_stderr():
                try:
                    for line in proc.stderr:
                        try:
                            decoded = line.decode('utf-8', errors='replace')
                        except Exception:
                            decoded = str(line)
                        stderr_lines.append(decoded)
                except Exception:
                    pass

            t = threading.Thread(target=read_stderr, daemon=True)
            t.start()

            ready = check_server_ready(port, timeout=12)

            if ready:
                proc.terminate()
                print(f'  ✅ Serveur opérationnel sur port {port} !')
                if fixes_applied and error_info:
                    try:
                        from core.learning_engine import record_fix_success
                        record_fix_success(
                            stderr[:200],
                            error_info.get('description', 'unknown'),
                            error_info.get('fix_content', '') or error_info.get('fix_new', ''),
                            error_info['description'],
                            str(project_dir.name)
                        )
                    except Exception:
                        pass
                return AgentOutput(
                    agent_name=self.name, success=True,
                    artifacts={'port': port, 'cycles': cycle, 'fixes': fixes_applied}
                )

            proc.terminate()
            t.join(timeout=2)
            stderr = ''.join(stderr_lines)
            stderr_buffer.append(stderr)

            current_content = main_file.read_text(encoding='utf-8', errors='ignore')
            error_info = find_matching_error(stderr, current_content)

            if error_info:
                print(f'  🔍 Erreur identifiée : {error_info["description"]}')
                fixed = apply_known_fix(main_file, error_info, stderr, port)
                if fixed:
                    fixes_applied.append(error_info['description'])
                    print(f'  🔧 Fix appliqué : {error_info["description"]}')
            else:
                print(f'  🧠 Erreur inconnue — envoi à DeepSeek...')
                fixed = deepseek_fix(main_file, stderr, port)
                if fixed:
                    fixes_applied.append('Fix DeepSeek générique')
                    try:
                        fixed_content = main_file.read_text(encoding='utf-8', errors='ignore')
                        from core.learning_engine import record_fix_success
                        record_fix_success(stderr[:200], 'deepseek_fix', fixed_content[:500], 'Fix généré par DeepSeek', str(project_dir.name))
                    except Exception:
                        pass

            if not fixed:
                print(f'  ⚠️ Aucun fix applicable pour ce cycle')

        return AgentOutput(
            agent_name=self.name, success=False,
            artifacts={'cycles': self.max_cycles, 'fixes': fixes_applied},
            errors=[f'Échec après {self.max_cycles} cycles', '\n'.join(stderr_buffer[-3:])]
        )
