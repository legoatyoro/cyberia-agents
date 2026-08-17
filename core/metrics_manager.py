import json, time, re
from pathlib import Path
from datetime import datetime


STANDARD_FILES = ['requirements.txt', 'README.md', '.gitignore']


def check_structural_integrity(project_dir: Path) -> dict:
    issues = []
    is_django = (project_dir / 'manage.py').exists()

    if is_django:
        settings_files = list(project_dir.rglob('settings.py'))
        urls_files = list(project_dir.rglob('urls.py'))

        if settings_files:
            settings_content = settings_files[0].read_text(encoding='utf-8', errors='ignore')

            root_urlconf_match = re.search(r"ROOT_URLCONF\s*=\s*['\"]([^'\"]+)['\"]", settings_content)
            if root_urlconf_match:
                expected_module = root_urlconf_match.group(1).replace('.', '/') + '.py'
                if not (project_dir / expected_module).exists():
                    issues.append(f'ROOT_URLCONF pointe vers {expected_module} qui n\'existe pas')

            apps_dir = project_dir / 'apps'
            if apps_dir.exists():
                disk_apps = [p.name for p in apps_dir.iterdir()
                             if p.is_dir() and (p / 'models.py').exists()]
                for app_name in disk_apps:
                    if (f"apps.{app_name}" not in settings_content
                            and f"'{app_name}'" not in settings_content):
                        issues.append(f'App {app_name} présente sur disque mais absente de INSTALLED_APPS')

        user_model_files = []
        for models_file in project_dir.rglob('models.py'):
            try:
                content = models_file.read_text(encoding='utf-8', errors='ignore')
                if 'AbstractUser' in content and 'class User(' in content:
                    user_model_files.append(str(models_file.relative_to(project_dir)))
            except Exception:
                pass
        if len(user_model_files) > 1:
            issues.append(f'Modèle User dupliqué dans : {user_model_files}')

        for urls_file in urls_files:
            try:
                content = urls_file.read_text(encoding='utf-8', errors='ignore')
                includes = re.findall(r"include\(['\"]([^'\"]+)['\"]\)", content)
                for inc in includes:
                    parts = inc.split('.')
                    # Walk down the module path to find the deepest existing dir
                    check_path = project_dir
                    for part in parts[:-1]:
                        check_path = check_path / part
                    if not check_path.exists():
                        issues.append(f'URL include {inc!r} pointe vers un module inexistant')
            except Exception:
                pass

    return {'issues': issues, 'count': len(issues), 'is_django': is_django}


def compute_project_score(project_dir: Path, blueprint=None, import_errors: list = None) -> float:
    """Unified project scoring. Used by Orchestrator, ImprovementLoop, and MetricsManager."""
    from cyberia_validator import validate_imports
    from core.ts_validator import validate_typescript

    score = 10.0

    errors = import_errors if import_errors is not None else validate_imports(project_dir)
    score -= min(len(errors) * 0.5, 3.0)

    ts_report = validate_typescript(project_dir)
    score -= min(ts_report.get('error_count', 0) * 0.3, 3.0)

    if blueprint is not None:
        missing = [f for f in blueprint.files_to_create if not (project_dir / f).exists()]
    else:
        missing = [f for f in STANDARD_FILES if not (project_dir / f).exists()]
    score -= len(missing) * 0.3

    integrity = check_structural_integrity(project_dir)
    score -= min(integrity['count'] * 0.5, 3.0)

    return round(max(0.0, score), 1)

class MetricsManager:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.metrics = {
            'project': project_dir.name,
            'started_at': datetime.now().isoformat(),
            'agents': {},
            'totals': {
                'files_generated': 0,
                'errors_fixed': 0,
                'dependencies_installed': 0,
                'fixer_cycles': 0,
                'ts_errors': 0,
                'python_errors': 0
            }
        }
        self._timers = {}

    def start_agent(self, agent_name: str):
        self._timers[agent_name] = time.monotonic()
        self.metrics['agents'][agent_name] = {'started': True}

    def end_agent(self, agent_name: str, success: bool, details: dict = None):
        elapsed = time.monotonic() - self._timers.get(agent_name, time.monotonic())
        self.metrics['agents'][agent_name] = {
            'success': success,
            'duration_seconds': round(elapsed, 1),
            'details': details or {}
        }

    def record(self, key: str, value):
        if key in self.metrics['totals']:
            if isinstance(value, int):
                self.metrics['totals'][key] += value
            else:
                self.metrics['totals'][key] = value

    def compute_score(self) -> float:
        score = 10.0
        score -= min(self.metrics['totals']['ts_errors'] * 0.2, 2.0)
        score -= min(self.metrics['totals']['python_errors'] * 0.3, 2.0)
        failed = sum(1 for a in self.metrics['agents'].values() if not a.get('success', True))
        score -= min(failed * 0.5, 2.0)
        integrity = check_structural_integrity(self.project_dir)
        score -= min(integrity['count'] * 0.5, 3.0)
        if integrity['issues']:
            self.metrics['structural_issues'] = integrity['issues']
        return round(max(score, 0.0), 1)

    def save(self) -> Path:
        self.metrics['completed_at'] = datetime.now().isoformat()
        self.metrics['final_score'] = self.compute_score()
        path = self.project_dir / 'metrics.json'
        path.write_text(json.dumps(self.metrics, indent=2, ensure_ascii=False), encoding='utf-8')
        return path
