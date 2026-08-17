import sys
import subprocess
import json
from pathlib import Path

COMPATIBILITY_DB = {
    'python': {
        '3.14': {
            'jinja2': {'status': 'incompatible', 'action': 'use_html_response', 'message': 'Jinja2 incompatible Python 3.14 - generer HTML pur avec f-strings'},
            'fastapi': {'status': 'ok_min', 'min_version': '0.110'},
            'sqlalchemy': {'status': 'deprecated_syntax', 'action': 'use_orm_declarative', 'message': 'Utiliser sqlalchemy.orm.declarative_base() au lieu de declarative_base()'},
        },
        '3.12': {
            'jinja2': {'status': 'ok'},
            'fastapi': {'status': 'ok'},
            'sqlalchemy': {'status': 'ok'},
        },
        '3.11': {
            'jinja2': {'status': 'ok'},
            'fastapi': {'status': 'ok'},
            'sqlalchemy': {'status': 'ok'},
        }
    },
    'node': {
        '24': {
            'nestjs': {'status': 'ok_min', 'min_version': '10'},
            'react': {'status': 'ok_min', 'min_version': '18'},
            'uuid': {'status': 'deprecated', 'message': 'Utiliser uuid@11 ou crypto.randomUUID()'},
        },
        '20': {
            'nestjs': {'status': 'ok_min', 'min_version': '9'},
            'react': {'status': 'ok_min', 'min_version': '18'},
        }
    }
}

ADAPTER_RULES = {
    'jinja2_python_3_14': {
        'rule': 'NO_JINJA2',
        'prompt_injection': 'INTERDICTION ABSOLUE : NE PAS utiliser Jinja2Templates ni TemplateResponse. Generer du HTML avec des fonctions Python retournant HTMLResponse avec des f-strings Bootstrap.'
    },
    'sqlalchemy_python_3_14': {
        'rule': 'USE_ORM_DECLARATIVE',
        'prompt_injection': 'Utiliser from sqlalchemy.orm import declarative_base au lieu de from sqlalchemy.ext.declarative import declarative_base'
    }
}


def get_python_version():
    return sys.version_info[:2]


def get_node_version():
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
        v = result.stdout.strip().lstrip('v')
        parts = v.split('.')
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def check_compatibility(dependencies: list) -> dict:
    py_ver = get_python_version()
    node_ver = get_node_version()
    py_key = f'{py_ver[0]}.{py_ver[1]}'
    node_key = str(node_ver[0]) if node_ver else None

    issues = []
    prompt_injections = []
    adapter_rules = []

    print(f'[VERSION_CHECKER] Python {py_key} | Node {node_key or "non detecte"}')

    py_compat = COMPATIBILITY_DB['python'].get(py_key, {})
    for dep in dependencies:
        dep_lower = dep.lower().split('[')[0].split('>=')[0].strip()
        if dep_lower in py_compat:
            info = py_compat[dep_lower]
            if info['status'] in ['incompatible', 'deprecated_syntax']:
                issue = {
                    'package': dep_lower,
                    'python_version': py_key,
                    'status': info['status'],
                    'message': info.get('message', ''),
                    'action': info.get('action', '')
                }
                issues.append(issue)
                rule_key = f'{dep_lower}_python_{py_key.replace(".", "_")}'
                if rule_key in ADAPTER_RULES:
                    rule = ADAPTER_RULES[rule_key]
                    prompt_injections.append(rule['prompt_injection'])
                    adapter_rules.append(rule['rule'])
                print(f'  [WARN] {dep_lower}: {info.get("message", info["status"])}')

    if node_key and COMPATIBILITY_DB['node'].get(node_key):
        node_compat = COMPATIBILITY_DB['node'][node_key]
        for dep in dependencies:
            dep_lower = dep.lower().split('[')[0].strip()
            if dep_lower in node_compat:
                info = node_compat[dep_lower]
                if info['status'] == 'deprecated':
                    issues.append({'package': dep_lower, 'node_version': node_key, 'message': info.get('message', '')})
                    print(f'  [WARN] {dep_lower}: {info.get("message", "deprecie")}')

    report = {
        'python_version': py_key,
        'node_version': node_key,
        'issues': issues,
        'prompt_injections': prompt_injections,
        'adapter_rules': adapter_rules,
        'safe_to_proceed': True
    }

    if issues:
        print(f'  [INFO] {len(issues)} incompatibilite(s) - adaptations appliquees automatiquement')
    else:
        print(f'  [OK] Toutes les dependances compatibles')

    return report


def get_prompt_adaptations(dependencies: list) -> str:
    report = check_compatibility(dependencies)
    if not report['prompt_injections']:
        return ''
    return '\n\nADAPTATIONS OBLIGATOIRES (incompatibilites detectees) :\n' + '\n'.join(
        f'- {inj}' for inj in report['prompt_injections']
    )


if __name__ == '__main__':
    print('=== Test check_compatibility ===')
    test_deps = ['jinja2', 'fastapi', 'sqlalchemy', 'uuid']
    result = check_compatibility(test_deps)
    print(f'Issues: {len(result["issues"])}')
    print(f'Prompt injections: {len(result["prompt_injections"])}')
    print(f'Adapter rules: {result["adapter_rules"]}')
    print()
    print('=== Test get_prompt_adaptations ===')
    adaptations = get_prompt_adaptations(['jinja2', 'fastapi'])
    print(f'Adaptations output length: {len(adaptations)} chars')
    if adaptations:
        print(f'Preview: {adaptations[:200]}')
    else:
        print('No adaptations needed for current Python version')
