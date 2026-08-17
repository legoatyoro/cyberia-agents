from pathlib import Path
from core.llm_client import LLMClient
from core.expert_profiles import get_profile, EXPERT_PROFILES
from core.runtime_rules import get_system_prompt_rules
from schemas.agent_schemas import AgentOutput


class ExpertBuilderAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'EXPERT_BUILDER'

    def select_profile_for_file(self, filename: str, dominant_experts: list, stack: dict) -> str:
        fname = filename.lower()
        if any(fname.endswith(ext) for ext in ['.ts', '.tsx']):
            return 'EXPERT_TYPESCRIPT'
        if fname.endswith('.py'):
            return 'EXPERT_PYTHON'
        if 'model' in fname or 'entity' in fname or 'schema' in fname:
            return 'EXPERT_DATABASE'
        if 'route' in fname or 'controller' in fname or 'main' in fname:
            return 'EXPERT_API'
        if dominant_experts:
            return dominant_experts[0]
        return 'EXPERT_PYTHON'

    def generate_file(self, filename: str, blueprint, ctx, dominant_experts: list, plan: dict) -> tuple:
        profile_name = self.select_profile_for_file(filename, dominant_experts, getattr(blueprint, 'stack', {}))
        profile = get_profile(profile_name)

        # Get context - adapt to actual ContextManager interface
        try:
            context = ctx.get_context_for_file(filename)
        except (AttributeError, TypeError):
            try:
                context = ctx.get_context()
            except Exception:
                context = str(ctx)[:500] if ctx else ''

        dominant_context = ''
        if dominant_experts:
            dominant_roles = [get_profile(e).get('role', '')[:150] for e in dominant_experts]
            dominant_context = f'\nEXPERTS DOMINANTS : {dominant_experts}\nRègles métier : {dominant_roles}'

        project_name = getattr(blueprint, 'project_name', 'projet')
        stack = getattr(blueprint, 'stack', {})

        rules = get_system_prompt_rules()
        prompt = f'''{rules}

PROFIL ACTIF : {profile_name}
{profile["role"]}

CONTRAINTES STRICTES : {", ".join(profile.get("constraints", []))}
{dominant_context}

PROJET : {project_name}
STACK : {stack}
FICHIER À GÉNÉRER : {filename}

CONTEXTE DU PROJET :
{context}

RÈGLES ABSOLUES :
- Génère UNIQUEMENT le contenu du fichier {filename}
- AUCUN markdown, AUCUN backtick, AUCUNE explication
- Code immédiatement fonctionnel'''

        # Try streaming first, fall back to regular call
        try:
            code = self.llm.call_with_stream('code', prompt, streaming=False, temperature_override=profile.get('temperature', 0.2))
        except (AttributeError, TypeError):
            code = self.llm.call('code', prompt)

        # Strip markdown artifacts
        try:
            from cyberia_sanitizer import strip_markdown_artifacts, needs_reprompt
            code = strip_markdown_artifacts(code)
        except ImportError:
            pass

        return code, profile_name

    def run(self, blueprint, project_dir: Path, ctx, plan: dict) -> AgentOutput:
        dominant_experts = plan.get('dominant_experts', [])
        files_to_create = getattr(blueprint, 'files_to_create', [])
        print(f'🔨 [{self.name}] Génération experte de {len(files_to_create)} fichiers...')
        if dominant_experts:
            print(f'  🏢 Profil dominant : {dominant_experts}')

        generated = []
        errors = []
        profile_usage = {}

        try:
            from cyberia_sanitizer import strip_markdown_artifacts, needs_reprompt
        except ImportError:
            strip_markdown_artifacts = lambda x: x
            needs_reprompt = lambda x: False

        for filename in files_to_create:
            print(f'  📄 {filename}...', end='', flush=True)
            try:
                code, profile_used = self.generate_file(filename, blueprint, ctx, dominant_experts, plan)
                if needs_reprompt(code):
                    code, profile_used = self.generate_file(filename, blueprint, ctx, dominant_experts, plan)
                    code = strip_markdown_artifacts(code)

                filepath = project_dir / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(code, encoding='utf-8')

                try:
                    ctx.add_generated_file(filepath, code)
                except (AttributeError, TypeError):
                    pass

                generated.append(filename)
                profile_usage[filename] = profile_used
                print(f' ✅ [{profile_used}] ({len(code.splitlines())} lignes)')
            except Exception as e:
                errors.append(f'{filename}: {e}')
                print(f' ❌ {e}')

        try:
            ctx.save_to_disk()
        except (AttributeError, TypeError):
            pass

        return AgentOutput(
            agent_name=self.name, success=len(errors) == 0,
            artifacts={'generated': generated, 'profile_usage': profile_usage},
            errors=errors
        )
