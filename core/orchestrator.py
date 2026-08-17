import json, time
from pathlib import Path

try:
    from core.event_bus import get_bus, publish as bus_publish, subscribe as bus_subscribe
    from core.learning_engine import record_fix_success, record_generation_feedback
    from core.component_library import auto_save_validated_files
    from core.technical_researcher import get_research_summary
    _V12_ENABLED = True
except ImportError:
    _V12_ENABLED = False
    def bus_publish(t, s, p=None): pass

try:
    from core.knowledge_base import get_rules, get_patterns, get_kb_summary
    from agents.knowledge_builder import KnowledgeBuilderAgent
    from agents.self_auditor import SelfAuditorAgent
    from agents.web_scout import WebScoutAgent
    _V14_ENABLED = True
except ImportError:
    _V14_ENABLED = False
from agents.architecte import ArchitecteAgent
from agents.builder import BuilderAgent
from agents.fixer import FixerAgent
from agents.tester import TesterAgent
from agents.security import SecurityAgent
from agents.documenter import DocumenterAgent
from agents.deployer import DeployerAgent
from agents.runner import RunnerAgent
from agents.cdc_generator import CDCGeneratorAgent
from core.context_manager import ContextManager
from core.auto_installer import auto_install_project
from cyberia_validator import validate_imports
from cyberia_test_generator import extract_routes, generate_tests
from core.metrics_manager import MetricsManager
from core.manifest_manager import create_manifest
from core.ts_validator import validate_typescript
from core.intent_detector import classify_intent
from agents.analyste import AnalysteAgent
from agents.router_expert import RouterExpertAgent
from agents.expert_builder import ExpertBuilderAgent
from agents.optimizer import OptimizerAgent
from agents.refactorer import RefactorerAgent
from agents.auto_debugger import AutoDebugger
from agents.ui_generator import UIGeneratorAgent

try:
    from core.version_checker import get_prompt_adaptations, check_compatibility
except ImportError:
    def check_compatibility(deps): return {'issues': [], 'prompt_injections': [], 'adapter_rules': []}
    def get_prompt_adaptations(deps): return ''

try:
    from core.researcher import generate_research_report
except ImportError:
    def generate_research_report(cdc, stack, project_dir): return ''

try:
    from core.domain_sanity_checker import check_domain_sanity
except ImportError:
    def check_domain_sanity(project_dir, domain): return {'domain': domain, 'checked': 0, 'issues': []}

try:
    from core.style_enforcer import StyleEnforcerAgent
except ImportError:
    class StyleEnforcerAgent:
        def run(self, project_dir): return {'success': True, 'artifacts': {}, 'errors': []}

class Orchestrator:
    def __init__(self, output_dir: Path = Path('generated')):
        self.output_dir = output_dir
        self.architecte = ArchitecteAgent()
        self.builder = BuilderAgent()
        self.fixer = FixerAgent()
        self.tester = TesterAgent()
        self.security = SecurityAgent()
        self.documenter = DocumenterAgent()
        self.deployer = DeployerAgent()
        self.runner = RunnerAgent()
        self.cdc_gen = CDCGeneratorAgent()
        self.router = RouterExpertAgent()
        self.expert_builder = ExpertBuilderAgent()
        self.optimizer = OptimizerAgent()
        self.refactorer = RefactorerAgent()
        self.style_enforcer = StyleEnforcerAgent()
        if _V14_ENABLED:
            self.kb_builder = KnowledgeBuilderAgent()
            self.self_auditor = SelfAuditorAgent()
            self.web_scout = WebScoutAgent()
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        if not _V12_ENABLED:
            return
        bus = get_bus()

        def on_fix_success(event):
            try:
                record_fix_success(
                    event.payload.get('error', ''),
                    event.payload.get('fix_type', 'unknown'),
                    event.payload.get('fix_content', ''),
                    event.payload.get('description', ''),
                    event.payload.get('project_type', '')
                )
                print(f'  🧠 Pattern mémorisé : {event.payload.get("description", "")}')
            except Exception:
                pass
        bus.subscribe('FIX_SUCCESS', on_fix_success)

        def on_generation_complete(event):
            try:
                project_path = Path(event.payload.get('project_path', ''))
                score = event.payload.get('score', 0)
                if project_path.exists() and score >= 8.5:
                    auto_save_validated_files(project_path, score)
            except Exception:
                pass
        bus.subscribe('GENERATION_COMPLETE', on_generation_complete)

        def on_server_started(event):
            try:
                record_generation_feedback(
                    event.payload.get('project', ''), 'fastapi',
                    '', '', True,
                    event.payload.get('score_before', 0),
                    event.payload.get('score', 0)
                )
            except Exception:
                pass
        bus.subscribe('SERVER_STARTED', on_server_started)

    def run(self, cdc: str, dry_run: bool = False, streaming: bool = False) -> dict:
        start = time.time()
        print('\n🤖 CYBERIA v11 — DÉMARRAGE\n' + '=' * 50)

        # Phase 0 — Enrichissement CDC si phrase courte
        cdc_output, cdc = self.cdc_gen.run(cdc)

        # Phase 1 — Architecture
        metrics_temp_dir = self.output_dir / 'temp'
        metrics_temp_dir.mkdir(parents=True, exist_ok=True)
        metrics = MetricsManager(metrics_temp_dir)

        metrics.start_agent('ARCHITECT')
        blueprint_output, blueprint = self.architecte.run(cdc, self.output_dir / 'temp')
        metrics.end_agent('ARCHITECT', True, {'project_name': blueprint.project_name})

        # v8.0 — Version compatibility check
        compat_report = check_compatibility(getattr(blueprint, 'dependencies', []) or [])

        # v14.0 — Web scout: check live package versions
        scout_summary = ''
        if _V14_ENABLED:
            try:
                scout_summary = self.web_scout.run(getattr(blueprint, 'dependencies', []) or []).artifacts.get('summary', '')
            except Exception:
                pass

        project_dir = self.output_dir / blueprint.project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Re-create metrics scoped to the actual project dir
        metrics = MetricsManager(project_dir)

        # v8.0 — Research report (knowledge base injection)
        generate_research_report(cdc, getattr(blueprint, 'stack', {}) or {}, project_dir)

        if dry_run:
            print('\n🔍 MODE DRY-RUN : blueprint généré, aucun fichier créé.')
            return {'dry_run': True, 'blueprint': blueprint.dict()}

        # Phase 1b — Routage expert
        router_output = self.router.run(cdc, blueprint.dict() if hasattr(blueprint, 'dict') else {})
        expert_plan = router_output.artifacts.get('plan', {'dominant_experts': [], 'technical_experts': []})
        print(f'🎯 Experts sélectionnés : {expert_plan.get("dominant_experts", [])}')

        # Phase 3 — Génération du code
        ctx = ContextManager(project_dir)
        ctx.schema_authority = blueprint.stack
        if _V12_ENABLED:
            try:
                ctx.research_context = get_research_summary(
                    getattr(blueprint, 'dependencies', []) or [],
                    getattr(blueprint, 'stack', {}) or {}
                )
            except Exception:
                pass
        if scout_summary:
            ctx.scout_context = scout_summary
        # Inject error lessons into generation context
        try:
            from core.error_learner import get_lessons_for_stack, init_default_lessons
            init_default_lessons()
            stack_str = str(getattr(blueprint, 'stack', '') or '').lower()
            detected_lang = (
                'django' if 'django' in stack_str else
                'fastapi' if 'fastapi' in stack_str else
                'nodejs' if 'node' in stack_str else
                'all'
            )
            lessons = get_lessons_for_stack(detected_lang)
            if lessons:
                lessons_block = '\n\nLECONS APPRISES DES ERREURS PASSEES (a respecter absolument):\n' + '\n'.join(f'- {l}' for l in lessons)
                ctx.research_context = (getattr(ctx, 'research_context', '') or '') + lessons_block
        except Exception:
            pass

        metrics.start_agent('BUILDER')
        builder_output = self.builder.run(blueprint, project_dir, ctx)
        metrics.end_agent('BUILDER', True, {'files': len(blueprint.files_to_create)})
        metrics.record('files_generated', len(blueprint.files_to_create))

        # AUTO_DEBUGGER phase 1 : tester le backend seul
        debugger = AutoDebugger()
        debug_result = debugger.run(project_dir, phase='backend')
        if debug_result.success:
            print(f'  ✅ Backend opérationnel sur port {debug_result.artifacts.get("port", 8000)}')

        # UI_GENERATOR : générer l'interface sur un backend qui fonctionne
        ui_gen = UIGeneratorAgent()
        ui_result = ui_gen.run(project_dir, blueprint=blueprint.dict() if hasattr(blueprint, 'dict') else {}, cdc=cdc)

        # AUTO_DEBUGGER phase 2 : tester backend + interface ensemble
        debug_result2 = debugger.run(project_dir, phase='backend+ui')

        # Phase 2 — Audit sécurité (après génération : fichiers réels disponibles)
        metrics.start_agent('SECURITY')
        self.security.run(project_dir)
        metrics.end_agent('SECURITY', True, {})

        # Create manifest after BUILDER
        create_manifest(project_dir)

        # FIX 7 — update .gitignore with standard exclusions
        gitignore = project_dir / '.gitignore'
        cyberia_ignore_additions = 'node_modules/\ndist/\nbuild/\n.next/\nvenv/\n__pycache__/\n*.pyc\n'
        if gitignore.exists():
            content = gitignore.read_text(encoding='utf-8')
            gitignore.write_text(content + cyberia_ignore_additions, encoding='utf-8')
        else:
            gitignore.write_text(cyberia_ignore_additions, encoding='utf-8')

        # TypeScript validation after BUILDER
        if (project_dir / 'tsconfig.json').exists():
            ts_report = validate_typescript(project_dir)
            metrics.record('ts_errors', ts_report['error_count'])
            if ts_report['error_count'] > 0:
                ts_errors_formatted = [f"TS{e['code']}: {e['message']} in {e['file']}:{e['line']}" for e in ts_report['errors']]
                metrics.start_agent('FIXER_TS')
                self.fixer.run(project_dir, ts_errors_formatted)
                metrics.end_agent('FIXER_TS', True, {'ts_errors_fixed': ts_report['error_count']})

        # Phase 4 — Correction des imports (skip pour Django)
        is_django = (project_dir / 'manage.py').exists() or (project_dir / 'backend' / 'manage.py').exists()
        if is_django:
            print('  ℹ️ Projet Django détecté — validation Python imports ignorée')
            _import_errors = []
        else:
            _import_errors = validate_imports(project_dir)
            _import_errors = [e for e in _import_errors if e.get('file', '').endswith('.py')]
            print(f'  🔍 {len(_import_errors)} erreurs Python (fichiers JS/TS ignorés)')
        if _import_errors:
            metrics.start_agent('FIXER')
            self.fixer.run(project_dir, _import_errors)
            metrics.end_agent('FIXER', True, {'errors_fixed': len(_import_errors)})
            metrics.record('errors_fixed', len(_import_errors))
            # Re-valider après le fix pour avoir le vrai compte final
            _import_errors = [e for e in validate_imports(project_dir) if e.get('file', '').endswith('.py')]

        # Phase 5 — Tests auto-générés
        routes = extract_routes(project_dir / 'main.py') if (project_dir / 'main.py').exists() else []
        if routes:
            generate_tests(project_dir, routes)

        # Phase 5b — Runner : install deps + vérification syntaxe + tests
        metrics.start_agent('RUNNER')
        runner_output = self.runner.run(project_dir)
        metrics.end_agent('RUNNER', runner_output.success, {})

        # Phase 5c — v8.0 Style enforcement
        self.style_enforcer.run(project_dir)

        # Phase 5d — v8.0 Domain sanity check
        detected_domain = self._detect_domain_from_cdc(cdc)
        check_domain_sanity(project_dir, detected_domain)

        # Phase 6 — Documentation
        self.documenter.run(blueprint, project_dir)

        # Phase 7 — Déploiement
        self.deployer.run(blueprint, project_dir)

        duration = time.time() - start
        report = {
            'project': blueprint.project_name,
            'duration_seconds': round(duration, 1),
            'files_generated': len(blueprint.files_to_create),
            'errors_remaining': len(_import_errors),   # déjà calculé — pas de 3e appel
            'runner_success': runner_output.success,
            'cdc_enriched': cdc_output.artifacts.get('enriched', False),
            'score': self._compute_score(project_dir, blueprint, _import_errors)
        }
        if _V12_ENABLED and report['score'] >= 8.5:
            try:
                bus_publish('GENERATION_COMPLETE', 'ORCHESTRATOR', {
                    'project_path': str(project_dir),
                    'project': blueprint.project_name,
                    'score': report['score']
                })
            except Exception:
                pass

        # v14.0 — Knowledge extraction and self-audit
        if _V14_ENABLED:
            try:
                if report['score'] >= 7.0:
                    self.kb_builder.run(project_dir, report['score'])
                self.self_auditor.record_project(success=report['score'] >= 7.0)
                should_audit, reason = self.self_auditor.should_audit()
                if should_audit:
                    print(f'\n🔍 [AUTO_AUDIT] Déclenchement : {reason}')
                    audit_result = self.self_auditor.run()
                    if audit_result.artifacts.get('audit'):
                        report['audit_triggered'] = True
            except Exception:
                pass
        report_path = project_dir / 'REPORT_FINAL.md'
        report_path.write_text(
            '# Rapport Final CYBERIA v7\n\n' + '\n'.join(f'- **{k}** : {v}' for k, v in report.items()),
            encoding='utf-8'
        )

        # Save metrics and print summary
        metrics_path = metrics.save()
        print(f'\n📊 Métriques sauvegardées : {metrics_path}')
        print(f'   Score métriques : {metrics.compute_score()}/10')
        print(f'\n✅ PROJET TERMINÉ en {duration:.1f}s — Score : {report["score"]}/10')
        return report

    def improve(self, project_dir: Path, request: str) -> dict:
        start = time.time()
        print(f'\n🔧 CYBERIA v7 — MODE AMÉLIORATION : {project_dir.name}\n' + '=' * 50)
        metrics = MetricsManager(project_dir)

        # Analyse du projet existant
        metrics.start_agent('ANALYSTE')
        analyste_output = AnalysteAgent().run(project_dir, request)
        plan = analyste_output.artifacts.get('plan', {})
        metrics.end_agent('ANALYSTE', analyste_output.success, {'plan_summary': plan.get('summary', '')})

        # Reconstruction du blueprint pour BUILDER à partir du plan
        files_to_work = plan.get('files_to_create', []) + plan.get('files_to_modify', [])
        print(f'  📋 Fichiers à traiter : {len(files_to_work)}')

        # Correction des imports post-modification
        errors = validate_imports(project_dir)
        if errors:
            metrics.start_agent('FIXER')
            self.fixer.run(project_dir, errors)
            metrics.end_agent('FIXER', True, {'errors_fixed': len(errors)})
            metrics.record('errors_fixed', len(errors))

        # TypeScript validation
        if (project_dir / 'tsconfig.json').exists():
            ts_report = validate_typescript(project_dir)
            metrics.record('ts_errors', ts_report['error_count'])
            if ts_report['error_count'] > 0:
                ts_errors_formatted = [f"TS{e['code']}: {e['message']} in {e['file']}:{e['line']}" for e in ts_report['errors']]
                metrics.start_agent('FIXER_TS')
                self.fixer.run(project_dir, ts_errors_formatted)
                metrics.end_agent('FIXER_TS', True, {'ts_errors_fixed': ts_report['error_count']})

        # Runner
        metrics.start_agent('RUNNER')
        runner_output = self.runner.run(project_dir)
        metrics.end_agent('RUNNER', runner_output.success, {})

        duration = time.time() - start
        metrics_path = metrics.save()
        print(f'\n📊 Métriques sauvegardées : {metrics_path}')
        print(f'\n✅ AMÉLIORATION TERMINÉE en {duration:.1f}s — Score : {metrics.compute_score()}/10')
        return {
            'project': project_dir.name,
            'duration_seconds': round(duration, 1),
            'plan': plan,
            'runner_success': runner_output.success,
            'score': metrics.compute_score()
        }

    def optimize(self, project_dir: Path) -> dict:
        print(f'⚡ [OPTIMIZER] Optimisation de {project_dir.name}...')
        opt_result = self.optimizer.run(project_dir)
        ref_result = self.refactorer.run(project_dir)
        return {
            'optimized': opt_result.artifacts.get('optimized', 0),
            'refactored': ref_result.artifacts.get('count', 0)
        }

    def _detect_domain_from_cdc(self, cdc: str) -> str:
        cdc_lower = cdc.lower()
        for domain, keywords in [
            ('finance', ['facture', 'facturation', 'comptab']),
            ('ecommerce', ['boutique', 'shop', 'panier', 'commande']),
            ('saas', ['saas', 'abonnement', 'subscription']),
            ('crm', ['crm', 'prospect', 'lead', 'pipeline']),
            ('rh', ['employe', 'conge', 'paie', 'rh']),
        ]:
            if any(kw in cdc_lower for kw in keywords):
                return domain
        return 'general'

    def _compute_score(self, project_dir: Path, blueprint, import_errors: list = None) -> float:
        from core.metrics_manager import compute_project_score
        return compute_project_score(project_dir, blueprint, import_errors)
