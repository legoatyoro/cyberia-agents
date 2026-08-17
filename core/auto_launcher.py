import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def detect_project_type(project_dir: Path) -> dict:
    if (project_dir / 'backend' / 'manage.py').exists():
        return {'type': 'django', 'cmd': [sys.executable, 'manage.py', 'runserver', '0.0.0.0:8000'],
                'cwd': str(project_dir / 'backend'), 'url': 'http://localhost:8000',
                'install_first': True, 'install_cmd': ['pip', 'install', '-r', 'requirements.txt', '-q']}
    if (project_dir / 'manage.py').exists():
        return {'type': 'django', 'cmd': [sys.executable, 'manage.py', 'runserver', '0.0.0.0:8000'],
                'url': 'http://localhost:8000', 'install_first': True}

    main_py = project_dir / 'main.py'
    if main_py.exists():
        content = main_py.read_text(encoding='utf-8', errors='ignore').lower()
        if 'fastapi' in content or 'uvicorn' in content:
            return {
                'type': 'fastapi',
                'cmd': [sys.executable, 'main.py'],
                'url': 'http://localhost:8000',
                'docs': 'http://localhost:8000/docs'
            }
        if 'flask' in content:
            return {
                'type': 'flask',
                'cmd': [sys.executable, 'main.py'],
                'url': 'http://localhost:5000'
            }

    if (project_dir / 'backend' / 'package.json').exists():
        return {
            'type': 'nestjs',
            'cmd': ['npm', 'run', 'start'],
            'cwd': str(project_dir / 'backend'),
            'url': 'http://localhost:3000',
            'install_first': True
        }

    if (project_dir / 'package.json').exists():
        content = (project_dir / 'package.json').read_text(encoding='utf-8', errors='ignore')
        if 'vite' in content or 'react' in content:
            return {
                'type': 'react',
                'cmd': ['npm', 'run', 'dev'],
                'url': 'http://localhost:5173',
                'install_first': True
            }

    if (project_dir / 'manage.py').exists():
        return {
            'type': 'django',
            'cmd': [sys.executable, 'manage.py', 'runserver'],
            'url': 'http://localhost:8000'
        }

    return {'type': 'unknown', 'cmd': None, 'url': None}


def install_dependencies(project_dir: Path, project_type: dict) -> bool:
    print('  Installation des dépendances...')
    ptype = project_type['type']
    cwd = Path(project_type.get('cwd', str(project_dir)))

    if ptype == 'django':
        req = cwd / 'requirements.txt'
        if req.exists():
            print(f'  📦 pip install -r {req.name}...')
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-r', str(req), '-q'],
                capture_output=True, text=True, cwd=str(cwd)
            )
            if result.returncode != 0:
                print(f'  ⚠️ pip install partiel : {result.stderr[:200]}')
        print('  🗄️ Migrations Django...')
        try:
            mig = subprocess.run(
                [sys.executable, 'manage.py', 'migrate', '--run-syncdb'],
                capture_output=True, text=True, cwd=str(cwd), timeout=60
            )
            if mig.returncode == 0:
                print('  ✅ Migrations OK')
            else:
                print(f'  ⚠️ Migration ignorée (continuité assurée) : {mig.stderr[:200]}')
        except Exception as e:
            print(f'  ⚠️ Migration ignorée (continuité assurée) : {e}')
        return True

    elif ptype in ('fastapi', 'flask'):
        req = project_dir / 'requirements.txt'
        if req.exists():
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-r', str(req), '-q'],
                capture_output=True, text=True
            )
            return result.returncode == 0

    elif project_type.get('install_first'):
        result = subprocess.run(['npm', 'install'], capture_output=True, text=True, cwd=str(cwd))
        return result.returncode == 0

    return True


def launch_project(project_dir: Path) -> dict:
    project_type = detect_project_type(project_dir)
    if not project_type['cmd']:
        print(f'  Type de projet non reconnu dans {project_dir.name}')
        return {'success': False, 'error': f'Type non reconnu'}

    print(f'\n  Lancement du projet {project_dir.name}...')
    print(f'  Type détecté : {project_type["type"]}')

    install_dependencies(project_dir, project_type)

    cwd = project_type.get('cwd', str(project_dir))
    cmd = project_type['cmd']

    print(f'  Commande : {" ".join(cmd)}')
    print(f'  URL : {project_type.get("url", "?")}')

    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print('  Démarrage', end='', flush=True)
    started = False
    timeout_seconds = 20 if project_type['type'] == 'django' else 15
    for i in range(timeout_seconds):
        time.sleep(1)
        print('.', end='', flush=True)
        if proc.poll() is not None:
            out, err = proc.communicate()
            print()
            print(f'  Processus terminé prématurément : {err.decode()[:300]}')
            return {'success': False, 'error': err.decode()[:500]}
        if project_type.get('url'):
            try:
                import urllib.request
                urllib.request.urlopen(project_type['url'], timeout=2)
                started = True
                break
            except Exception:
                pass

    print()
    if started or proc.poll() is None:
        url = project_type.get('url', '')
        docs = project_type.get('docs', '')
        print(f'\n  Projet démarré !')
        print(f'  Interface : {url}')
        if docs:
            print(f'  API Docs  : {docs}')
        print()
        ouverture = input('  Ouvrir dans le navigateur ? (o/n) : ').strip().lower()
        if ouverture == 'o':
            webbrowser.open(url)
            if docs:
                time.sleep(1)
                webbrowser.open(docs)
        print()
        print('  Appuie sur Ctrl+C pour arrêter le serveur.')
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            print('\n  Serveur arrêté.')
        return {'success': True, 'url': url, 'pid': proc.pid}
    else:
        return {'success': False, 'error': 'Démarrage timeout'}
