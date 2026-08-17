import subprocess, json, re
from pathlib import Path

def validate_typescript(project_dir: Path) -> dict:
    tsconfig = project_dir / 'tsconfig.json'
    if not tsconfig.exists():
        return {'supported': False, 'errors': [], 'score': 10.0}

    print(f'🔍 [TS_VALIDATOR] Validation TypeScript...')
    result = subprocess.run(
        ['npx', 'tsc', '--noEmit', '--pretty', 'false'],
        capture_output=True, text=True, cwd=str(project_dir), timeout=120
    )

    errors = []
    pattern = re.compile(r'^(.+\.tsx?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.+)$', re.MULTILINE)
    for match in pattern.finditer(result.stdout + result.stderr):
        errors.append({
            'file': match.group(1),
            'line': int(match.group(2)),
            'col': int(match.group(3)),
            'code': match.group(4),
            'message': match.group(5)
        })

    score = max(0.0, 10.0 - (len(errors) * 0.3))
    report = {
        'supported': True,
        'exit_code': result.returncode,
        'errors': errors,
        'error_count': len(errors),
        'score': round(score, 1)
    }

    (project_dir / 'ts_validation_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8'
    )

    if errors:
        print(f'  ❌ {len(errors)} erreur(s) TypeScript')
    else:
        print(f'  ✅ Zéro erreur TypeScript')

    return report

def extract_missing_imports_ts(project_dir: Path) -> list:
    missing = []
    import_pattern = re.compile(r"from\s+['\"](\./[^'\"]+|\.\.\/[^'\"]+)['\"]")

    for ts_file in list(project_dir.rglob('*.ts')) + list(project_dir.rglob('*.tsx')):
        try:
            content = ts_file.read_text(encoding='utf-8')
            for match in import_pattern.finditer(content):
                rel_path = match.group(1)
                base = (ts_file.parent / rel_path).resolve()
                extensions = ['', '.ts', '.tsx', '/index.ts', '/index.tsx']
                found = any((base.parent / (base.name + ext)).exists() for ext in extensions)
                if not found:
                    missing.append({
                        'from_file': str(ts_file.relative_to(project_dir)),
                        'missing_import': rel_path,
                        'suggested_path': str(base) + '.ts'
                    })
        except Exception:
            pass

    return missing
