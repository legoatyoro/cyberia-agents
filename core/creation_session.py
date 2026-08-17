import json
from pathlib import Path
from datetime import datetime


class CreationSession:
    def __init__(self, project_name, project_dir=None):
        self.project_name = project_name
        self.project_dir = Path(project_dir) if project_dir else None
        self.session_id = f'creation_{project_name}_{datetime.now().strftime("%H%M%S")}'
        self.history = []
        self.phase = 'describe'
        self.phases = ['describe', 'generate', 'test', 'fix', 'improve', 'validate']
        self.test_results = []
        self.bugs_found = []
        self.bugs_fixed = []
        self.iterations = 0
        self.started_at = datetime.now().isoformat()

    def log(self, action, detail='', result=''):
        entry = {
            'phase': self.phase,
            'action': action,
            'detail': detail[:200],
            'result': result[:200],
            'ts': datetime.now().strftime('%H:%M:%S')
        }
        self.history.append(entry)

    def next_phase(self):
        idx = self.phases.index(self.phase) if self.phase in self.phases else 0
        if idx < len(self.phases) - 1:
            self.phase = self.phases[idx + 1]
        return self.phase

    def save(self):
        sessions_file = Path('.cyberia/creation_sessions.jsonl')
        sessions_file.parent.mkdir(exist_ok=True)
        with open(sessions_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'session_id': self.session_id,
                'project_name': self.project_name,
                'phases_completed': self.history,
                'bugs_found': len(self.bugs_found),
                'bugs_fixed': len(self.bugs_fixed),
                'iterations': self.iterations,
                'finished_at': datetime.now().isoformat()
            }, ensure_ascii=False) + '\n')

    def get_summary(self):
        return (
            f'Phase: {self.phase} | Iter: {self.iterations} | '
            f'Bugs: {len(self.bugs_found)} | Fixes: {len(self.bugs_fixed)}'
        )
