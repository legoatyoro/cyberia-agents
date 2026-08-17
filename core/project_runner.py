import subprocess, sys, time
import sqlite3, json, re, ast
from pathlib import Path
from datetime import datetime
from enum import Enum


class FixState(Enum):
    INIT = 'init'
    RUN = 'run'
    ERROR = 'error'
    PATCH = 'patch'
    RERUN = 'rerun'
    SUCCESS = 'success'
    ABORT = 'abort'


class ErrorClass(Enum):
    CORRIGEABLE = 'corrigeable'
    ENV_CONFIG = 'env_config'
    FATAL = 'fatal'


def classify_error(error_text):
    corrigeable = ['ImportError', 'ModuleNotFoundError', 'AttributeError', 'NameError', 'SyntaxError', 'TypeError', 'ValueError']
    env_errors = ['PermissionError', 'OSError', 'ConnectionError', 'KeyError', 'SECRET_KEY', 'DATABASE_URL', 'API_KEY']
    txt = error_text.lower()
    for e in corrigeable:
        if e.lower() in txt: return ErrorClass.CORRIGEABLE
    for e in env_errors:
        if e.lower() in txt: return ErrorClass.ENV_CONFIG
    return ErrorClass.CORRIGEABLE


def compute_score(tests_ok, tests_fail, error_count):
    return max(0, tests_ok * 2 - tests_fail * 3 - error_count)


DB_RUNS = Path('.cyberia/run_stats.db')


def get_adaptive_timeout(command_key, default=20):
    try:
        DB_RUNS.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_RUNS)
        conn.execute('CREATE TABLE IF NOT EXISTS run_stats (id INTEGER PRIMARY KEY, command TEXT UNIQUE, avg_duration REAL, last_duration REAL, runs_count INTEGER)')
        row = conn.execute('SELECT avg_duration, last_duration, runs_count FROM run_stats WHERE command=?', (command_key,)).fetchone()
        conn.close()
        if row and row[2] >= 3:
            return min(max(row[1] * 2, 10), 180)
    except Exception:
        pass
    return default


def update_run_stats(command_key, duration):
    try:
        conn = sqlite3.connect(DB_RUNS)
        conn.execute('CREATE TABLE IF NOT EXISTS run_stats (id INTEGER PRIMARY KEY, command TEXT UNIQUE, avg_duration REAL, last_duration REAL, runs_count INTEGER)')
        row = conn.execute('SELECT avg_duration, runs_count FROM run_stats WHERE command=?', (command_key,)).fetchone()
        if row:
            new_avg = (row[0] * row[1] + duration) / (row[1] + 1)
            conn.execute('UPDATE run_stats SET avg_duration=?, last_duration=?, runs_count=runs_count+1 WHERE command=?', (new_avg, duration, command_key))
        else:
            conn.execute('INSERT INTO run_stats (command, avg_duration, last_duration, runs_count) VALUES (?,?,?,1)', (command_key, duration, duration))
        conn.commit()
        conn.close()
    except Exception:
        pass


class AutonomousFixLoop:
    def __init__(self, project_dir, max_iterations=5):
        self.project_dir = Path(project_dir)
        self.max_iterations = max_iterations
        self.state = FixState.INIT
        self.iterations = []
        self.consecutive_no_improvement = 0
        self.same_error_count = 0
        self.last_error_signatures = set()
        self.patched_files = {}
        self.report = {
            'project': str(project_dir),
            'started_at': datetime.now().isoformat(),
            'status': 'running',
            'iterations': [],
            'remaining_errors': [],
            'suggested_manual_actions': []
        }

    def run_project(self):
        from core.project_runner import ProjectRunner
        runner = ProjectRunner(str(self.project_dir))
        cmd_key = str(self.project_dir.name)
        timeout = get_adaptive_timeout(cmd_key, default=20)
        start = time.time()
        output, errors, code = runner.run_and_capture_errors(timeout=timeout)
        duration = time.time() - start
        update_run_stats(cmd_key, duration)
        return output, errors, code

    def get_error_signatures(self, errors):
        sigs = set()
        for e in errors:
            match = re.search(r'(Error|Exception|Traceback)[^\n]*', e)
            if match:
                sigs.add(match.group()[:80])
        return sigs

    def backup_file(self, filepath):
        p = Path(filepath)
        if p.exists():
            bak = p.with_suffix('.autobak')
            bak.write_text(p.read_text(encoding='utf-8', errors='ignore'), encoding='utf-8')
            self.patched_files[str(filepath)] = str(bak)

    def rollback_file(self, filepath):
        bak = Path(str(filepath).replace('.py', '.autobak'))
        if bak.exists():
            Path(filepath).write_text(bak.read_text(encoding='utf-8', errors='ignore'), encoding='utf-8')
            print(f'  [ROLLBACK] {Path(filepath).name} restaure')
            return True
        return False

    def propose_fix(self, errors, context=''):
        from core.multi_model_router import MultiModelRouter
        router = MultiModelRouter()
        errors_text = '\n'.join(errors[:5])
        py_files = list(self.project_dir.rglob('*.py'))
        files_ctx = '\n'.join(f'- {f.relative_to(self.project_dir)} ({f.stat().st_size} bytes)' for f in py_files[:10] if '__pycache__' not in str(f))
        prompt = f'''Tu es un expert debug Python. Corrige ces erreurs dans le projet {self.project_dir.name}.
ERREURS:
{errors_text}

FICHIERS DU PROJET:
{files_ctx}

CONTEXTE PRECEDENT: {context[:300]}

Reponds UNIQUEMENT en JSON:
{{"file": "chemin/relatif/fichier.py", "issue": "description courte", "fix_type": "import|logic|config|syntax", "original_line": "ligne originale", "fixed_line": "ligne corrigee", "explanation": "pourquoi"}}

Si tu ne peux pas corriger automatiquement:
{{"file": null, "issue": "description", "fix_type": "manual", "suggested_action": "action manuelle recommandee"}}'''
        response = router.call(prompt, task_type='fix')
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return None

    def apply_fix(self, fix_data):
        if not fix_data or not fix_data.get('file'):
            return False
        target = self.project_dir / fix_data['file']
        if not target.exists():
            return False
        self.backup_file(str(target))
        content = target.read_text(encoding='utf-8', errors='ignore')
        original = fix_data.get('original_line', '')
        fixed = fix_data.get('fixed_line', '')
        if original and fixed and original in content:
            new_content = content.replace(original, fixed, 1)
            target.write_text(new_content, encoding='utf-8')
            try:
                ast.parse(new_content)
                return True
            except SyntaxError:
                self.rollback_file(str(target))
                return False
        return False

    def run(self, on_iteration=None):
        from core.error_learner import learn_from_error
        prev_score = -1
        prev_errors = []

        for i in range(self.max_iterations):
            print(f'\n  [FIX_LOOP] Iteration {i+1}/{self.max_iterations} — etat: {self.state.value}')
            self.state = FixState.RUN
            output, errors, code = self.run_project()
            err_sigs = self.get_error_signatures(errors)
            tests_fail = len(errors)
            tests_ok = max(0, 5 - tests_fail)
            score = compute_score(tests_ok, tests_fail, len(errors))
            iter_data = {'iteration': i+1, 'return_code': code, 'errors': errors[:5], 'error_signatures': list(err_sigs), 'score': score}
            self.report['iterations'].append(iter_data)

            if on_iteration:
                on_iteration(i+1, errors, score)

            if not errors or code == 0:
                self.state = FixState.SUCCESS
                print(f'  [FIX_LOOP] Succes a l iteration {i+1}')
                break

            if err_sigs == self.last_error_signatures:
                self.same_error_count += 1
                if self.same_error_count >= 3:
                    print(f'  [FIX_LOOP] Erreur identique 3x — abandon')
                    self.state = FixState.ABORT
                    break
            else:
                self.same_error_count = 0

            if score <= prev_score and i > 0:
                self.consecutive_no_improvement += 1
                if self.consecutive_no_improvement >= 2:
                    for filepath in list(self.patched_files.keys()):
                        self.rollback_file(filepath)
                    print(f'  [FIX_LOOP] Regression detectee — rollback')
                    self.state = FixState.ABORT
                    break
            else:
                self.consecutive_no_improvement = 0

            error_class = classify_error('\n'.join(errors[:3]))
            if error_class == ErrorClass.ENV_CONFIG and i >= 2:
                action = 'Verifier les variables d environnement et la configuration de la base de donnees'
                self.report['suggested_manual_actions'].append(action)
                self.state = FixState.ABORT
                break

            self.state = FixState.PATCH
            context = '\n'.join(prev_errors[:3]) if prev_errors else ''
            fix = self.propose_fix(errors, context)
            if fix and fix.get('fix_type') != 'manual':
                applied = self.apply_fix(fix)
                if applied:
                    learn_from_error('\n'.join(errors[:3]), fix.get('explanation', ''), worked=True)
                    print(f'  [FIX_LOOP] Fix applique: {fix.get("file")} — {fix.get("issue", "")[:50]}')
                else:
                    print(f'  [FIX_LOOP] Fix non applicable')
            elif fix and fix.get('fix_type') == 'manual':
                self.report['suggested_manual_actions'].append(fix.get('suggested_action', ''))

            prev_score = score
            prev_errors = errors
            self.last_error_signatures = err_sigs

        self.report['status'] = self.state.value
        self.report['remaining_errors'] = list(self.last_error_signatures)[:5]
        self.report['finished_at'] = datetime.now().isoformat()
        report_path = self.project_dir / 'az_report.json'
        report_path.write_text(json.dumps(self.report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'  [FIX_LOOP] Rapport: {report_path}')
        return self.state, self.report


class ProjectRunner:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.process = None
        self.output_lines = []
        self.errors = []
        self.port = None
        self.running = False

    def detect_start_command(self):
        p = self.project_dir
        if (p / 'manage.py').exists():
            return [sys.executable, 'manage.py', 'runserver', '0.0.0.0:8000'], 8000
        for f in ['main.py', 'app.py', 'server.py']:
            if (p / f).exists():
                content = (p / f).read_text(encoding='utf-8', errors='ignore')
                if 'uvicorn' in content or 'fastapi' in content.lower():
                    return [sys.executable, f], 8000
                if 'Flask' in content or 'flask' in content:
                    return [sys.executable, f], 5000
        if (p / 'package.json').exists():
            return ['node', 'server.js'], 3000
        return [sys.executable, 'main.py'], 8000

    def start(self, timeout=15):
        import os
        cmd, port = self.detect_start_command()
        self.port = port
        self.output_lines = []
        self.errors = []
        try:
            self.process = subprocess.Popen(
                cmd, cwd=str(self.project_dir),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                env={**os.environ, 'PYTHONUTF8': '1'}
            )
            self.running = True
            start_time = time.time()
            started = False
            for line in iter(self.process.stdout.readline, ''):
                self.output_lines.append(line.strip())
                if any(kw in line.lower() for kw in ['running on', 'started', 'listening', 'ready', ':' + str(port)]):
                    started = True
                    break
                if 'error' in line.lower() or 'traceback' in line.lower():
                    self.errors.append(line.strip())
                if time.time() - start_time > timeout:
                    break
            return started, port
        except Exception as e:
            self.errors.append(str(e))
            return False, port

    def test_endpoint(self, path='/'):
        import urllib.request
        try:
            url = f'http://localhost:{self.port}{path}'
            r = urllib.request.urlopen(url, timeout=5)
            return r.status, r.read(500).decode('utf-8', errors='replace')
        except Exception as e:
            return 0, str(e)

    def get_errors(self):
        return [
            l for l in self.output_lines
            if 'error' in l.lower() or 'traceback' in l.lower() or 'exception' in l.lower()
        ]

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                pass
        self.running = False
        self.process = None

    def run_and_capture_errors(self, timeout=20):
        import os
        cmd, port = self.detect_start_command()
        try:
            result = subprocess.run(
                cmd, cwd=str(self.project_dir),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=timeout, env={**os.environ, 'PYTHONUTF8': '1'}
            )
            output = result.stdout + result.stderr
            errors = [
                l for l in output.splitlines()
                if any(kw in l for kw in ['Error', 'Traceback', 'Exception', 'error:'])
            ]
            return output, errors, result.returncode
        except subprocess.TimeoutExpired:
            return 'Timeout - app peut-etre demarree (verifier manuellement)', [], -1
        except Exception as e:
            return str(e), [str(e)], 1
