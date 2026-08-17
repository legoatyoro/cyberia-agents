import subprocess, sys, time, json, urllib.request, urllib.error
from pathlib import Path


class ApiTester:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.process = None
        self.port = 8000
        self.base_url = f'http://localhost:{self.port}'
        self.endpoints_found = []

    def detect_port_and_type(self):
        for f in ['main.py', 'app.py', 'server.py']:
            target = self.project_dir / f
            if target.exists():
                content = target.read_text(encoding='utf-8', errors='ignore')
                if 'fastapi' in content.lower():
                    return 'fastapi', 8000
                if 'flask' in content.lower():
                    return 'flask', 5000
                if 'django' in content.lower():
                    return 'django', 8000
        if (self.project_dir / 'manage.py').exists():
            return 'django', 8000
        return 'unknown', 8000

    def extract_endpoints(self):
        endpoints = []
        for f in self.project_dir.rglob('*.py'):
            if '__pycache__' in str(f):
                continue
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                import re
                for method in ['get', 'post', 'put', 'delete', 'patch']:
                    patterns = re.findall(
                        rf'@(?:app|router)\.{method}\(["\']([^"\']+)["\']',
                        content
                    )
                    for p in patterns:
                        endpoints.append({'method': method.upper(), 'path': p, 'file': f.name})
            except Exception:
                pass
        self.endpoints_found = endpoints
        return endpoints

    def start_server(self, timeout=20):
        stack, port = self.detect_port_and_type()
        self.port = port
        self.base_url = f'http://localhost:{port}'
        if stack == 'fastapi':
            cmd = [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', str(port)]
        elif stack == 'flask':
            cmd = [sys.executable, 'app.py']
        elif stack == 'django':
            cmd = [sys.executable, 'manage.py', 'runserver', f'0.0.0.0:{port}']
        else:
            cmd = [sys.executable, 'main.py']
        try:
            self.process = subprocess.Popen(
                cmd, cwd=str(self.project_dir),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace'
            )
            for _ in range(timeout * 2):
                time.sleep(0.5)
                try:
                    urllib.request.urlopen(f'{self.base_url}/', timeout=1)
                    return True, f'Serveur demarre sur {self.base_url}'
                except Exception:
                    pass
                if self.process.poll() is not None:
                    output = self.process.stdout.read() if self.process.stdout else ''
                    return False, f'Processus termine: {output[:300]}'
            return False, 'Timeout - le serveur ne repond pas'
        except Exception as e:
            return False, str(e)

    def test_endpoint(self, method, path, body=None):
        url = f'{self.base_url}{path}'
        try:
            if method == 'GET':
                req = urllib.request.Request(url)
            else:
                data = json.dumps(body or {}).encode()
                req = urllib.request.Request(
                    url, data=data,
                    headers={'Content-Type': 'application/json'},
                    method=method
                )
            with urllib.request.urlopen(req, timeout=5) as r:
                return {'status': r.status, 'body': r.read(500).decode('utf-8', errors='replace'), 'ok': True}
        except urllib.error.HTTPError as e:
            return {'status': e.code, 'body': e.read(200).decode('utf-8', errors='replace'), 'ok': False}
        except Exception as e:
            return {'status': 0, 'body': str(e), 'ok': False}

    def run_quick_tests(self):
        results = []
        endpoints = self.extract_endpoints()
        test_endpoints = [e for e in endpoints if e['method'] == 'GET'][:5]
        if not test_endpoints:
            test_endpoints = [{'method': 'GET', 'path': '/'}, {'method': 'GET', 'path': '/health'}]
        for ep in test_endpoints:
            result = self.test_endpoint(ep['method'], ep['path'])
            results.append({**ep, **result})
            print(f'  [API_TEST] {ep["method"]} {ep["path"]} -> {result["status"]}')
        return results

    def open_docs(self):
        import webbrowser
        docs_url = f'{self.base_url}/docs'
        try:
            urllib.request.urlopen(docs_url, timeout=2)
            webbrowser.open(docs_url)
            return True, docs_url
        except Exception:
            webbrowser.open(self.base_url)
            return False, self.base_url

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                pass
            self.process = None
