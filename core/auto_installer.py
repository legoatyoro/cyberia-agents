import ast
import sys
import subprocess
import json
import re
import logging
from pathlib import Path
from typing import Set, Dict, List, Optional

# -------------------------------------------------------------------
# Configuration du logging
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("auto_installer")

# -------------------------------------------------------------------
# Mapping module → package pip (inchangé)
# -------------------------------------------------------------------
MODULE_TO_PACKAGE = {
    'cv2': 'opencv-python',
    'PIL': 'Pillow',
    'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4',
    'dotenv': 'python-dotenv',
    'yaml': 'pyyaml',
    'dateutil': 'python-dateutil',
    'attr': 'attrs',
    'jose': 'python-jose',
    'multipart': 'python-multipart',
    'passlib': 'passlib',
    'aiofiles': 'aiofiles',
    'httpx': 'httpx',
    'pydantic': 'pydantic',
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'sqlalchemy': 'SQLAlchemy',
    'celery': 'celery',
    'redis': 'redis',
    'stripe': 'stripe',
    'sendgrid': 'sendgrid',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'openpyxl': 'openpyxl',
    'aiohttp': 'aiohttp',
    'selenium': 'selenium',
    'playwright': 'playwright',
    'jwt': 'PyJWT',
}

# -------------------------------------------------------------------
# Construction fiable de STDLIB (ensemble des modules standard)
# -------------------------------------------------------------------
def _get_stdlib_modules() -> Set[str]:
    """Retourne un ensemble fiable des noms de modules standard Python."""
    # Python 3.10+ : sys.stdlib_module_names est disponible
    if hasattr(sys, 'stdlib_module_names'):
        return set(sys.stdlib_module_names)

    # Python < 3.10 : fallback sur une liste minimale de modules standard
    # (couvre la quasi‑totalité des cas réels)
    common_stdlib = {
        '__future__', '_thread', 'abc', 'aifc', 'argparse', 'array',
        'ast', 'asynchat', 'asyncio', 'asyncore', 'atexit', 'audioop',
        'base64', 'bdb', 'binascii', 'binhex', 'bisect', 'builtins',
        'bz2', 'calendar', 'cgi', 'cgitb', 'chunk', 'cmath', 'cmd',
        'code', 'codecs', 'codeop', 'collections', 'colorsys', 'compileall',
        'concurrent', 'configparser', 'contextlib', 'contextvars', 'copy',
        'copyreg', 'cProfile', 'crypt', 'csv', 'ctypes', 'curses',
        'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
        'distutils', 'doctest', 'email', 'encodings', 'enum', 'errno',
        'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch',
        'fractions', 'ftplib', 'functools', 'gc', 'getopt', 'getpass',
        'gettext', 'glob', 'graphlib', 'grp', 'gzip', 'hashlib',
        'heapq', 'hmac', 'html', 'http', 'idlelib', 'imaplib', 'imghdr',
        'imp', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools',
        'json', 'keyword', 'lib2to3', 'linecache', 'locale', 'logging',
        'lzma', 'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes',
        'mmap', 'modulefinder', 'multiprocessing', 'netrc', 'nis',
        'nntplib', 'numbers', 'operator', 'optparse', 'os', 'ossaudiodev',
        'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil',
        'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint',
        'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr',
        'pydoc', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib',
        'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select',
        'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site',
        'smtpd', 'smtplib', 'sndhdr', 'socket', 'socketserver', 'sqlite3',
        'ssl', 'stat', 'statistics', 'string', 'stringprep', 'struct',
        'subprocess', 'sunau', 'symtable', 'sys', 'sysconfig', 'syslog',
        'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios',
        'test', 'textwrap', 'threading', 'time', 'timeit', 'tkinter',
        'token', 'tokenize', 'trace', 'traceback', 'tracemalloc',
        'tty', 'turtle', 'turtledemo', 'types', 'typing', 'unicodedata',
        'unittest', 'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave',
        'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib',
        'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
        'zoneinfo',
    }
    logger.warning(
        "sys.stdlib_module_names non disponible. Utilisation d'une liste "
        "statique de modules standard. Certains modules rares peuvent être manquants."
    )
    return common_stdlib

STDLIB = _get_stdlib_modules()

# -------------------------------------------------------------------
# Dossiers à ignorer lors du scan du projet
# -------------------------------------------------------------------
IGNORED_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', '.venv', 'venv', 'env',
    'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache',
    '.tox', '.eggs', 'dist', 'build', '*.egg-info',
}

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
    'users', 'payments', 'products', 'clients', 'invoices',
    'quotes', 'companies', 'notifications', 'reports', 'audit',
    'dashboard', 'company', 'authentication', 'tokens', 'backends',
    'pagination', 'cache', 'choices', 'csv_export', 'pdf', 'email',
    'logging', 'validators', 'signals', 'managers', 'constants',
    'prediction_agent', 'match_agent', 'stats_agent', 'agent_manager',
    'match_service', 'stats_service', 'prediction_service',
    'notification_service', 'export_service', 'search_service',
    'kanban_service', 'dashboard_service', 'comment_service',
    'user_service', 'project_service', 'task_service', 'auth_service',
    'routers', 'kanban', 'search', 'export', 'comments',
}

PACKAGE_MAPPING = {
    'django_filters': 'django-filter',
    'rest_framework': 'djangorestframework',
    'rest_framework_simplejwt': 'djangorestframework-simplejwt',
    'drf_yasg': 'drf-yasg',
    'decouple': 'python-decouple',
    'PIL': 'Pillow',
    'magic': 'python-magic-bin',
    'cv2': 'opencv-python',
    'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4',
    'yaml': 'pyyaml',
    'dotenv': 'python-dotenv',
    'jose': 'python-jose',
    'weasyprint': 'weasyprint',
}

# -------------------------------------------------------------------
# Fonctions d'extraction des imports (améliorées)
# -------------------------------------------------------------------
def extract_imports_from_file(filepath: Path) -> Set[str]:
    """Extrait les noms de modules importés depuis un fichier Python."""
    modules: Set[str] = set()
    try:
        source = filepath.read_text(encoding='utf-8', errors='ignore')
    except (IOError, OSError) as exc:
        logger.debug("Impossible de lire %s : %s", filepath, exc)
        return modules

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        logger.debug("Erreur de syntaxe dans %s : %s", filepath, exc)
        return modules

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split('.')[0])
    return modules


def extract_imports_from_project(project_dir: Path) -> Set[str]:
    """Parcourt récursivement tous les fichiers .py du projet (hors dossiers ignorés)."""
    all_imports: Set[str] = set()
    if not project_dir.is_dir():
        logger.warning("%s n'est pas un dossier valide.", project_dir)
        return all_imports

    for py_file in project_dir.rglob('*.py'):
        # Ignorer les fichiers dans les dossiers exclus
        if any(ignored in py_file.parts for ignored in IGNORED_DIRS):
            continue
        all_imports |= extract_imports_from_file(py_file)

    # Retirer les modules standard, modules locaux et les valeurs vides / __future__
    return all_imports - STDLIB - LOCAL_MODULES - {'__future__', ''}


# -------------------------------------------------------------------
# Gestion des dépendances et installation
# -------------------------------------------------------------------
def is_installed(module: str) -> bool:
    """Vérifie si un module est disponible dans l'environnement courant."""
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def get_package_name(module: str) -> str:
    return PACKAGE_MAPPING.get(module, MODULE_TO_PACKAGE.get(module, module))


def install_package(package: str, timeout: int = 120) -> bool:
    """Installe un package pip. Retourne True si succès, False sinon."""
    # Validation simple du nom du package (sécurité)
    if not re.match(r'^[\w\-\.\[\]~=<>!@#]+$', package):
        logger.error("Nom de package invalide : %s", package)
        return False

    logger.info("Installation de %s...", package)
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package, '-q', '--disable-pip-version-check'],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info("✅ %s installé avec succès.", package)
            return True
        else:
            logger.error("❌ Échec de l'installation de %s : %s", package, result.stderr.strip())
            return False
    except subprocess.TimeoutExpired:
        logger.error("⏱️ Timeout lors de l'installation de %s (%d secondes).", package, timeout)
        return False
    except Exception as exc:
        logger.exception("Erreur inattendue lors de l'installation de %s : %s", package, exc)
        return False


def auto_install_project(project_dir: Path) -> Dict[str, List[str]]:
    """Analyse le projet et installe les dépendances manquantes."""
    logger.info("📦 [AUTO_INSTALLER] Scan des imports dans %s...", project_dir)
    all_imports = extract_imports_from_project(project_dir)
    missing = {m for m in all_imports if not is_installed(m)}

    results = {
        'installed': [],
        'failed': [],
        'already_ok': list(all_imports - missing),
    }

    if not missing:
        logger.info("✅ Toutes les dépendances sont déjà installées.")
        return results

    logger.info("📥 %d dépendance(s) manquante(s) : %s", len(missing), missing)

    for module in missing:
        package = get_package_name(module)
        # Petit délai pour éviter de surcharger pip en parallèle (optionnel)
        if install_package(package):
            results['installed'].append(package)
        else:
            results['failed'].append(package)

    return results


def auto_install_from_error(error_output: str) -> List[str]:
    """Analyse une sortie d'erreur et tente d'installer les modules manquants."""
    patterns = [
        r"ModuleNotFoundError: No module named '([\w\.]+)'",
        r"No module named '([\w\.]+)'",
        r"ImportError: cannot import name '\w+' from '([\w\.]+)'",
    ]
    installed: List[str] = []
    seen: Set[str] = set()  # éviter les doublons

    for pattern in patterns:
        for match in re.finditer(pattern, error_output):
            module = match.group(1).split('.')[0]
            if module in seen:
                continue
            seen.add(module)
            package = get_package_name(module)
            if install_package(package):
                installed.append(package)

    return installed


# -------------------------------------------------------------------
# Test simple (inchangé, sauf le message de sortie)
# -------------------------------------------------------------------
if __name__ == '__main__':
    import tempfile
    import textwrap

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / 'test_module.py').write_text(
            textwrap.dedent("""
                import os
                import json
                import fastapi
                from dotenv import load_dotenv
            """),
            encoding='utf-8'
        )
        result = auto_install_project(tmp)
        logger.info("installed  = %s", result["installed"])
        logger.info("failed     = %s", result["failed"])
        logger.info("already_ok = %d", len(result["already_ok"]))
        logger.info("auto_installer OK")