import json, hashlib
from pathlib import Path
from datetime import datetime

MANIFEST_FILE = 'cyberia_manifest.json'

def compute_hash(filepath: Path) -> str:
    try:
        content = filepath.read_bytes()
        return hashlib.md5(content).hexdigest()
    except Exception:
        return ''

def create_manifest(project_dir: Path, agent_name: str = 'BUILDER') -> dict:
    manifest = {
        'created_at': datetime.now().isoformat(),
        'agent': agent_name,
        'files': {}
    }
    EXCLUDE_DIRS = {'node_modules', '.git', '__pycache__', '.cyberia_cache', 'venv', '.venv', 'dist', 'build', '.next', 'coverage'}
    for f in project_dir.rglob('*'):
        if f.is_file() and not any(excl in f.parts for excl in EXCLUDE_DIRS):
            rel = str(f.relative_to(project_dir))
            manifest['files'][rel] = {
                'hash': compute_hash(f),
                'generated_by': agent_name,
                'modified_by_user': False
            }
    manifest_path = project_dir / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'📋 [MANIFEST] {len(manifest["files"])} fichiers indexés')
    return manifest

def load_manifest(project_dir: Path) -> dict | None:
    manifest_path = project_dir / MANIFEST_FILE
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding='utf-8'))

def detect_user_modifications(project_dir: Path) -> dict:
    manifest = load_manifest(project_dir)
    if not manifest:
        return {'has_manifest': False, 'modified_files': [], 'new_files': []}

    modified = []
    new_files = []

    for f in project_dir.rglob('*'):
        if f.is_file() and '.cyberia_cache' not in str(f) and f.name != MANIFEST_FILE:
            rel = str(f.relative_to(project_dir))
            current_hash = compute_hash(f)
            if rel in manifest['files']:
                if current_hash != manifest['files'][rel]['hash']:
                    modified.append(rel)
            else:
                new_files.append(rel)

    return {
        'has_manifest': True,
        'modified_files': modified,
        'new_files': new_files,
        'safe_to_overwrite': [f for f in manifest['files'] if f not in modified]
    }
