import ast, json
from pathlib import Path

class SchemaAuthority:
    """Source de vérité pour les schémas du projet généré."""

    def __init__(self):
        self.models: dict = {}
        self.routes: dict = {}
        self.env_vars: list = []

    def extract_from_models(self, models_file: Path) -> dict:
        if not models_file.exists():
            return {}
        try:
            tree = ast.parse(models_file.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    fields = {}
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            type_str = ast.unparse(item.annotation) if hasattr(ast, 'unparse') else 'unknown'
                            fields[item.target.id] = type_str
                        elif isinstance(item, ast.Assign):
                            for t in item.targets:
                                if isinstance(t, ast.Name) and not t.id.startswith('_'):
                                    fields[t.id] = 'unknown'
                    if fields:
                        self.models[node.name] = {'fields': fields}
        except Exception:
            pass
        return self.models

    def to_dict(self) -> dict:
        return {'models': self.models, 'routes': self.routes, 'env_vars': self.env_vars}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, output_dir: Path):
        (output_dir / 'schema_authority.json').write_text(self.to_json(), encoding='utf-8')
