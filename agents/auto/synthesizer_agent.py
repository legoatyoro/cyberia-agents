import json
import logging
from typing import Any, Dict, Optional
from datetime import datetime
from pathlib import Path

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, AgentStatus
from jinja2 import Environment, FileSystemLoader
import markdown

logger = logging.getLogger(__name__)


class SynthesizerAgent:
    """Agent responsible for synthesizing analysis reports into a coherent final document."""

    def __init__(self, event_bus: EventBus, config: Optional[Dict[str, Any]] = None):
        self.event_bus = event_bus
        self.config = config or {}
        self.name = "SYNTHESIZER_AGENT"
        self._analysis_report: Optional[Dict[str, Any]] = None
        self._task_graph: Optional[Dict[str, Any]] = None
        self._template_env = Environment(
            loader=FileSystemLoader(Path(__file__).parent.parent / "templates")
        )

        # Subscribe to required events
        self.event_bus.subscribe("ANALYSIS_COMPLETED", self._handle_analysis_completed)
        self.event_bus.subscribe("TASK_GRAPH_READY", self._handle_task_graph_ready)

    async def _handle_analysis_completed(self, event: Event) -> None:
        """Handle ANALYSIS_COMPLETED event."""
        logger.info(f"Received ANALYSIS_COMPLETED event with data: {event.data}")
        self._analysis_report = event.data.get("report")
        await self._try_synthesize()

    async def _handle_task_graph_ready(self, event: Event) -> None:
        """Handle TASK_GRAPH_READY event."""
        logger.info(f"Received TASK_GRAPH_READY event with data: {event.data}")
        self._task_graph = event.data.get("graph")
        await self._try_synthesize()

    async def _try_synthesize(self) -> None:
        """Attempt to synthesize if both inputs are available."""
        if self._analysis_report is not None and self._task_graph is not None:
            await self.run()

    async def run(self) -> AgentOutput:
        """Main execution method for the synthesizer agent."""
        try:
            logger.info(f"{self.name}: Starting synthesis process")

            # Validate inputs
            if not self._validate_inputs():
                error_msg = "Missing required inputs for synthesis"
                logger.error(f"{self.name}: {error_msg}")
                await self.event_bus.publish(Event(
                    type="SYNTHESIS_FAILED",
                    data={"error": error_msg, "timestamp": datetime.now().isoformat()}
                ))
                return AgentOutput(
                    status=AgentStatus.FAILED,
                    error=error_msg
                )

            # Generate Mermaid diagram
            mermaid_diagram = self._generate_mermaid_diagram()

            # Generate Graphviz diagram
            graphviz_diagram = self._generate_graphviz_diagram()

            # Generate recommendations
            recommendations = self._generate_recommendations()

            # Validate completeness and coherence
            validation_result = self._validate_report_completeness()

            # Generate final markdown report
            final_report = await self._generate_final_report(
                mermaid_diagram=mermaid_diagram,
                graphviz_diagram=graphviz_diagram,
                recommendations=recommendations,
                validation=validation_result
            )

            # Publish REPORT_READY event
            await self.event_bus.publish(Event(
                type="REPORT_READY",
                data={
                    "report": final_report,
                    "timestamp": datetime.now().isoformat(),
                    "agent": self.name
                }
            ))

            logger.info(f"{self.name}: Synthesis completed successfully")
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                data={"final_report_markdown": final_report}
            )

        except Exception as e:
            error_msg = f"Synthesis failed: {str(e)}"
            logger.error(f"{self.name}: {error_msg}")
            await self.event_bus.publish(Event(
                type="SYNTHESIS_FAILED",
                data={"error": error_msg, "timestamp": datetime.now().isoformat()}
            ))
            return AgentOutput(
                status=AgentStatus.FAILED,
                error=error_msg
            )

    def _validate_inputs(self) -> bool:
        """Validate that all required inputs are present and valid."""
        if not self._analysis_report:
            logger.warning(f"{self.name}: Analysis report is missing")
            return False
        if not self._task_graph:
            logger.warning(f"{self.name}: Task graph is missing")
            return False
        return True

    def _generate_mermaid_diagram(self) -> str:
        """Generate Mermaid diagram from task graph."""
        try:
            nodes = self._task_graph.get("nodes", [])
            edges = self._task_graph.get("edges", [])

            diagram_parts = ["graph TD"]
            for node in nodes:
                node_id = node.get("id", "").replace(" ", "_")
                node_label = node.get("label", node.get("id", ""))
                diagram_parts.append(f"    {node_id}[{node_label}]")

            for edge in edges:
                source = edge.get("source", "").replace(" ", "_")
                target = edge.get("target", "").replace(" ", "_")
                label = edge.get("label", "")
                if label:
                    diagram_parts.append(f"    {source} -->|{label}| {target}")
                else:
                    diagram_parts.append(f"    {source} --> {target}")

            return "\n".join(diagram_parts)
        except Exception as e:
            logger.error(f"{self.name}: Failed to generate Mermaid diagram: {e}")
            return "graph TD\n    A[Error generating diagram]"

    def _generate_graphviz_diagram(self) -> str:
        """Generate Graphviz diagram from task graph."""
        try:
            nodes = self._task_graph.get("nodes", [])
            edges = self._task_graph.get("edges", [])

            diagram_parts = ["digraph G {"]
            diagram_parts.append("    rankdir=LR;")
            diagram_parts.append("    node [shape=box, style=rounded];")

            for node in nodes:
                node_id = node.get("id", "").replace(" ", "_")
                node_label = node.get("label", node.get("id", ""))
                diagram_parts.append(f'    {node_id} [label="{node_label}"];')

            for edge in edges:
                source = edge.get("source", "").replace(" ", "_")
                target = edge.get("target", "").replace(" ", "_")
                label = edge.get("label", "")
                if label:
                    diagram_parts.append(f'    {source} -> {target} [label="{label}"];')
                else:
                    diagram_parts.append(f"    {source} -> {target};")

            diagram_parts.append("}")
            return "\n".join(diagram_parts)
        except Exception as e:
            logger.error(f"{self.name}: Failed to generate Graphviz diagram: {e}")
            return "digraph G {\n    A[Error generating diagram]\n}"

    def _generate_recommendations(self) -> list:
        """Generate prioritized recommendations from analysis report."""
        recommendations = []
        try:
            findings = self._analysis_report.get("findings", [])
            risks = self._analysis_report.get("risks", [])

            # Generate recommendations from findings
            for i, finding in enumerate(findings):
                priority = finding.get("priority", "medium")
                recommendation = {
                    "id": f"REC-{i+1:03d}",
                    "priority": priority,
                    "description": finding.get("recommendation", finding.get("description", "")),
                    "impact": finding.get("impact", "medium"),
                    "effort": finding.get("effort", "medium")
                }
                recommendations.append(recommendation)

            # Generate recommendations from risks
            for i, risk in enumerate(risks):
                priority = risk.get("severity", "medium")
                recommendation = {
                    "id": f"RISK-REC-{i+1:03d}",
                    "priority": priority,
                    "description": f"Mitigate risk: {risk.get('description', '')}",
                    "impact": "high",
                    "effort": risk.get("mitigation_effort", "medium")
                }
                recommendations.append(recommendation)

            # Sort by priority
            priority_order = {"high": 0, "medium": 1, "low": 2}
            recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))

            return recommendations
        except Exception as e:
            logger.error(f"{self.name}: Failed to generate recommendations: {e}")
            return []

    def _validate_report_completeness(self) -> Dict[str, Any]:
        """Validate the completeness and coherence of the report."""
        validation_result = {
            "is_complete": True,
            "missing_sections": [],
            "warnings": [],
            "coherence_score": 1.0
        }

        try:
            # Check required sections
            required_sections = ["summary", "findings", "recommendations", "conclusion"]
            for section in required_sections:
                if section not in self._analysis_report:
                    validation_result["is_complete"] = False
                    validation_result["missing_sections"].append(section)

            # Check for data consistency
            if self._analysis_report:
                if "findings" in self._analysis_report and "risks" in self._analysis_report:
                    if len(self._analysis_report["findings"]) == 0:
                        validation_result["warnings"].append("No findings reported")
                    if len(self._analysis_report["risks"]) == 0:
                        validation_result["warnings"].append("No risks identified")

            # Calculate coherence score
            if validation_result["missing_sections"]:
                validation_result["coherence_score"] = 1.0 - (len(validation_result["missing_sections"]) * 0.2)

        except Exception as e:
            logger.error(f"{self.name}: Validation failed: {e}")
            validation_result["is_complete"] = False
            validation_result["warnings"].append(f"Validation error: {str(e)}")

        return validation_result

    async def _generate_final_report(
        self,
        mermaid_diagram: str,
        graphviz_diagram: str,
        recommendations: list,
        validation: Dict[str, Any]
    ) -> str:
        """Generate the final markdown report."""
        try:
            # Try to use Jinja2 template if available
            try:
                template = self._template_env.get_template("synthesis_report.md.j2")
                report = template.render(
                    analysis_report=self._analysis_report,
                    task_graph=self._task_graph,
                    mermaid_diagram=mermaid_diagram,
                    graphviz_diagram=graphviz_diagram,
                    recommendations=recommendations,
                    validation=validation,
                    generated_at=datetime.now().isoformat()
                )
            except Exception:
                # Fallback to manual markdown generation
                report = self._generate_markdown_fallback(
                    mermaid_diagram, graphviz_diagram, recommendations, validation
                )

            return report

        except Exception as e:
            logger.error(f"{self.name}: Failed to generate final report: {e}")
            return f"# Synthesis Report\n\nError generating report: {str(e)}"

    def _generate_markdown_fallback(
        self,
        mermaid_diagram: str,
        graphviz_diagram: str,
        recommendations: list,
        validation: Dict[str, Any]
    ) -> str:
        """Generate markdown report without template."""
        report_parts = []

        # Title
        report_parts.append("# Synthesis Report")
        report_parts.append(f"\n*Generated at: {datetime.now().isoformat()}*\n")

        # Executive Summary
        report_parts.append("## Executive Summary")
        summary = self._analysis_report.get("summary", "No summary available")
        report_parts.append(summary)

        # Analysis Overview
        report_parts.append("\n## Analysis Overview")
        report_parts.append(f"- **Total Findings:** {len(self._analysis_report.get('findings', []))}")
        report_parts.append(f"- **Total Risks:** {len(self._analysis_report.get('risks', []))}")
        report_parts.append(f"- **Recommendations:** {len(recommendations)}")

        # Topology Diagram (Mermaid)
        report_parts.append("\n## System Topology")
        report_parts.append("")
        report_parts.append(mermaid_diagram)
        report_parts.append("")

        # Flow Diagram (Graphviz)
        report_parts.append("\n## Data Flow Diagram")
        report_parts.append("")
        report_parts.append(graphviz_diagram)
        report_parts.append("")

        # Recommendations
        report_parts.append("\n## Recommendations")
        if recommendations:
            for rec in recommendations:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                icon = priority_icon.get(rec["priority"], "⚪")
                report_parts.append(f"\n### {icon} {rec['id']} (Priority: {rec['priority'].upper()})")
                report_parts.append(f"- **Description:** {rec['description']}")
                report_parts.append(f"- **Impact:** {rec['impact']}")
                report_parts.append(f"- **Effort:** {rec['effort']}")
        else:
            report_parts.append("\nNo recommendations generated.")

        # Validation Results
        report_parts.append("\n## Report Validation")
        if validation["is_complete"]:
            report_parts.append("✅ **Status:** Complete")
        else:
            report_parts.append("❌ **Status:** Incomplete")
            if validation["missing_sections"]:
                report_parts.append(f"- Missing sections: {', '.join(validation['missing_sections'])}")

        if validation["warnings"]:
            report_parts.append("\n**Warnings:**")
            for warning in validation["warnings"]:
                report_parts.append(f"- ⚠️ {warning}")

        report_parts.append(f"\n**Coherence Score:** {validation['coherence_score']:.2f}")

        # Conclusion
        report_parts.append("\n## Conclusion")
        conclusion = self._analysis_report.get("conclusion", "No conclusion available")
        report_parts.append(conclusion)

        return "\n".join(report_parts)

    async def cleanup(self) -> None:
        """Cleanup resources."""
        self._analysis_report = None
        self._task_graph = None
        logger.info(f"{self.name}: Cleanup completed")