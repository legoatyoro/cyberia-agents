import json
import asyncio
from typing import Any, Dict, Optional
from datetime import datetime
import numpy as np
from scipy import stats
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, AgentStatus

class AnalyzerAgent:
    def __init__(self, event_bus: EventBus, agent_id: str = "analyzer_agent"):
        self.event_bus = event_bus
        self.agent_id = agent_id
        self.logger = print
        self._subscribe_to_events()
        
    def _subscribe_to_events(self):
        self.event_bus.subscribe("DATA_EXTRACTED", self._handle_data_extracted)
        self.event_bus.subscribe("RETRY_ANALYSIS", self._handle_retry_analysis)
        
    async def _handle_data_extracted(self, event: Event):
        self.logger(f"[{self.agent_id}] Received DATA_EXTRACTED event")
        try:
            extracted_data = event.data.get("extracted_data_json", {})
            analysis_params = event.data.get("analysis_parameters_json", {})
            
            result = await self.run(extracted_data, analysis_params)
            
            await self.event_bus.publish(Event(
                type="ANALYSIS_COMPLETED",
                source=self.agent_id,
                data={"analysis_report_json": result.output_data}
            ))
            
        except Exception as e:
            self.logger(f"[{self.agent_id}] Error processing DATA_EXTRACTED: {str(e)}")
            await self.event_bus.publish(Event(
                type="ANALYSIS_FAILED",
                source=self.agent_id,
                data={"error": str(e), "original_event": event.data}
            ))
    
    async def _handle_retry_analysis(self, event: Event):
        self.logger(f"[{self.agent_id}] Received RETRY_ANALYSIS event")
        try:
            extracted_data = event.data.get("extracted_data_json", {})
            analysis_params = event.data.get("analysis_parameters_json", {})
            
            result = await self.run(extracted_data, analysis_params)
            
            await self.event_bus.publish(Event(
                type="ANALYSIS_COMPLETED",
                source=self.agent_id,
                data={"analysis_report_json": result.output_data}
            ))
            
        except Exception as e:
            self.logger(f"[{self.agent_id}] Retry failed: {str(e)}")
            await self.event_bus.publish(Event(
                type="ANALYSIS_FAILED",
                source=self.agent_id,
                data={"error": str(e), "original_event": event.data}
            ))
    
    async def run(self, extracted_data_json: Dict[str, Any], analysis_parameters_json: Dict[str, Any]) -> AgentOutput:
        self.logger(f"[{self.agent_id}] Starting analysis...")
        
        try:
            # Convert input data to pandas DataFrame for analysis
            df = self._prepare_dataframe(extracted_data_json)
            
            # Extract analysis parameters
            anomaly_threshold = analysis_parameters_json.get("anomaly_threshold", 0.1)
            correlation_method = analysis_parameters_json.get("correlation_method", "pearson")
            confidence_level = analysis_parameters_json.get("confidence_level", 0.95)
            
            # Perform comprehensive analysis
            analysis_results = {}
            
            # 1. Anomaly Detection
            analysis_results["anomalies"] = self._detect_anomalies(df, anomaly_threshold)
            
            # 2. Vulnerability Assessment
            analysis_results["vulnerabilities"] = self._assess_vulnerabilities(df)
            
            # 3. Bottleneck Detection
            analysis_results["bottlenecks"] = self._detect_bottlenecks(df)
            
            # 4. Cross-source Correlation
            analysis_results["correlations"] = self._correlate_sources(df, correlation_method)
            
            # 5. Generate Technical Hypotheses
            analysis_results["hypotheses"] = self._generate_hypotheses(df, confidence_level)
            
            # 6. Calculate Key Performance Indicators
            analysis_results["kpis"] = self._calculate_kpis(df)
            
            # 7. Confidence Scoring
            analysis_results["confidence_scores"] = self._calculate_confidence_scores(analysis_results)
            
            # Prepare output
            output_data = {
                "analysis_id": f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "timestamp": datetime.now().isoformat(),
                "source_data_summary": self._summarize_source_data(df),
                "results": analysis_results,
                "metadata": {
                    "parameters_used": analysis_parameters_json,
                    "data_points_analyzed": len(df) if isinstance(df, pd.DataFrame) else 0,
                    "features_analyzed": list(df.columns) if isinstance(df, pd.DataFrame) else []
                }
            }
            
            self.logger(f"[{self.agent_id}] Analysis completed successfully")
            
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                output_data=output_data,
                error_message=None
            )
            
        except Exception as e:
            self.logger(f"[{self.agent_id}] Analysis failed: {str(e)}")
            return AgentOutput(
                status=AgentStatus.FAILED,
                output_data={},
                error_message=str(e)
            )
    
    def _prepare_dataframe(self, data: Dict[str, Any]) -> pd.DataFrame:
        """Convert input data to pandas DataFrame for analysis"""
        try:
            if isinstance(data, dict):
                # Handle nested JSON structure
                if "data" in data:
                    data = data["data"]
                if "records" in data:
                    data = data["records"]
                    
                # Convert to DataFrame
                if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
                    df = pd.DataFrame(data)
                elif isinstance(data, list):
                    df = pd.DataFrame(data)
                else:
                    df = pd.DataFrame([data])
                    
                # Handle missing values
                df = df.fillna(method='ffill').fillna(method='bfill').fillna(0)
                
                # Convert numeric columns
                for col in df.columns:
                    try:
                        df[col] = pd.to_numeric(df[col], errors='ignore')
                    except:
                        pass
                        
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            self.logger(f"[{self.agent_id}] Error preparing DataFrame: {str(e)}")
            return pd.DataFrame()
    
    def _detect_anomalies(self, df: pd.DataFrame, threshold: float) -> Dict[str, Any]:
        """Detect anomalies using Isolation Forest algorithm"""
        anomalies = {
            "detected": False,
            "anomaly_count": 0,
            "anomaly_details": [],
            "method_used": "isolation_forest"
        }
        
        try:
            if df.empty or len(df.columns) < 2:
                return anomalies
                
            # Select numeric columns only
            numeric_df = df.select_dtypes(include=[np.number])
            
            if numeric_df.empty:
                return anomalies
                
            # Standardize the data
            scaler = StandardScaler()
            scaled_data = scaler.fit_transform(numeric_df)
            
            # Apply Isolation Forest
            iso_forest = IsolationForest(
                contamination=threshold,
                random_state=42,
                n_estimators=100
            )
            
            predictions = iso_forest.fit_predict(scaled_data)
            
            # Identify anomalies (predictions == -1)
            anomaly_indices = np.where(predictions == -1)[0]
            
            if len(anomaly_indices) > 0:
                anomalies["detected"] = True
                anomalies["anomaly_count"] = len(anomaly_indices)
                
                for idx in anomaly_indices[:10]:  # Limit to first 10 anomalies
                    anomaly_detail = {
                        "index": int(idx),
                        "values": numeric_df.iloc[idx].to_dict(),
                        "anomaly_score": float(iso_forest.score_samples([scaled_data[idx]])[0])
                    }
                    anomalies["anomaly_details"].append(anomaly_detail)
                    
        except Exception as e:
            self.logger(f"[{self.agent_id}] Anomaly detection error: {str(e)}")
            
        return anomalies
    
    def _assess_vulnerabilities(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Assess potential vulnerabilities based on data patterns"""
        vulnerabilities = {
            "risk_level": "low",
            "vulnerabilities_found": [],
            "security_score": 100
        }
        
        try:
            if df.empty:
                return vulnerabilities
                
            # Check for common vulnerability patterns
            risk_factors = []
            
            # Check for exposed credentials or sensitive data
            sensitive_patterns = ['password', 'secret', 'key', 'token', 'credential']
            for col in df.columns:
                if any(pattern in col.lower() for pattern in sensitive_patterns):
                    risk_factors.append({
                        "type": "exposed_sensitive_data",
                        "field": col,
                        "severity": "high",
                        "description": f"Potentially sensitive data exposed in field: {col}"
                    })
            
            # Check for unusual access patterns
            if 'access_count' in df.columns:
                high_access = df[df['access_count'] > df['access_count'].quantile(0.95)]
                if not high_access.empty:
                    risk_factors.append({
                        "type": "unusual_access_pattern",
                        "severity": "medium",
                        "description": f"Detected {len(high_access)} records with unusually high access counts"
                    })
            
            # Check for configuration issues
            if 'config_version' in df.columns:
                outdated_configs = df[df['config_version'] < df['config_version'].median()]
                if len(outdated_configs) > len(df) * 0.3:
                    risk_factors.append({
                        "type": "outdated_configurations",
                        "severity": "medium",
                        "description": f"Found {len(outdated_configs)} outdated configurations"
                    })
            
            vulnerabilities["vulnerabilities_found"] = risk_factors
            
            # Calculate security score
            if risk_factors:
                severity_weights = {"high": 30, "medium": 15, "low": 5}
                total_deduction = sum(severity_weights.get(v["severity"], 0) for v in risk_factors)
                vulnerabilities["security_score"] = max(0, 100 - total_deduction)
                
                # Determine risk level
                if vulnerabilities["security_score"] < 50:
                    vulnerabilities["risk_level"] = "high"
                elif vulnerabilities["security_score"] < 80:
                    vulnerabilities["risk_level"] = "medium"
                    
        except Exception as e:
            self.logger(f"[{self.agent_id}] Vulnerability assessment error: {str(e)}")
            
        return vulnerabilities
    
    def _detect_bottlenecks(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect performance bottlenecks"""
        bottlenecks = {
            "bottlenecks_detected": False,
            "bottleneck_details": [],
            "performance_score": 100
        }
        
        try:
            if df.empty:
                return bottlenecks
                
            # Check for latency bottlenecks
            if 'latency' in df.columns:
                latency_stats = df['latency'].describe()
                if latency_stats['mean'] > latency_stats['50%'] * 2:  # Mean significantly higher than median
                    bottlenecks["bottlenecks_detected"] = True
                    bottlenecks["bottleneck_details"].append({
                        "type": "latency",
                        "metric": "response_time",
                        "severity": "high",
                        "description": f"High latency detected: mean={latency_stats['mean']:.2f}, median={latency_stats['50%']:.2f}"
                    })
            
            # Check for throughput bottlenecks
            if 'throughput' in df.columns:
                throughput_stats = df['throughput'].describe()
                if throughput_stats['min'] < throughput_stats['mean'] * 0.1:  # Significant throughput drops
                    bottlenecks["bottlenecks_detected"] = True
                    bottlenecks["bottleneck_details"].append({
                        "type": "throughput",
                        "metric": "data_processing_rate",
                        "severity": "medium",
                        "description": f"Throughput bottlenecks detected: min={throughput_stats['min']:.2f}, mean={throughput_stats['mean']:.2f}"
                    })
            
            # Check for resource utilization bottlenecks
            resource_columns = ['cpu_usage', 'memory_usage', 'disk_io']
            for col in resource_columns:
                if col in df.columns:
                    high_usage = df[df[col] > 80].shape[0]  # Over 80% utilization
                    if high_usage > len(df) * 0.2:  # More than 20% of time
                        bottlenecks["bottlenecks_detected"] = True
                        bottlenecks["bottleneck_details"].append({
                            "type": "resource_utilization",
                            "metric": col,
                            "severity": "high",
                            "description": f"High {col} detected in {high_usage} records"
                        })
            
            # Calculate performance score
            if bottlenecks["bottleneck_details"]:
                severity_weights = {"high": 25, "medium": 10, "low": 5}
                total_deduction = sum(severity_weights.get(b["severity"], 0) for b in bottlenecks["bottleneck_details"])
                bottlenecks["performance_score"] = max(0, 100 - total_deduction)
                
        except Exception as e:
            self.logger(f"[{self.agent_id}] Bottleneck detection error: {str(e)}")
            
        return bottlenecks
    
    def _correlate_sources(self, df: pd.DataFrame, method: str = "pearson") -> Dict[str, Any]:
        """Correlate information between different sources"""
        correlations = {
            "significant_correlations": [],
            "cross_source_patterns": [],
            "correlation_method": method
        }
        
        try:
            if df.empty or len(df.columns) < 2:
                return correlations
                
            # Select numeric columns
            numeric_df = df.select_dtypes(include=[np.number])
            
            if numeric_df.shape[1] < 2:
                return correlations
                
            # Calculate correlation matrix
            if method == "spearman":
                corr_matrix = numeric_df.corr(method='spearman')
            else:
                corr_matrix = numeric_df.corr(method='pearson')
            
            # Find significant correlations
            threshold = 0.7
            for i in range(len(corr_matrix.columns)):
                for j in range(i+1, len(corr_matrix.columns)):
                    corr_value = corr_matrix.iloc[i, j]
                    if abs(corr_value) >= threshold:
                        correlations["significant_correlations"].append({
                            "source_1": corr_matrix.columns[i],
                            "source_2": corr_matrix.columns[j],
                            "correlation_coefficient": round(corr_value, 3),
                            "strength": "strong" if abs(corr_value) > 0.8 else "moderate",
                            "direction": "positive" if corr_value > 0 else "negative"
                        })
            
            # Detect cross-source patterns using PCA
            if numeric_df.shape[1] >= 3:
                from sklearn.decomposition import PCA
                pca = PCA(n_components=2)
                pca_result = pca.fit_transform(StandardScaler().fit_transform(numeric_df))
                
                # Check for clustering patterns
                explained_variance = pca.explained_variance_ratio_
                if explained_variance[0] > 0.6:  # First component explains most variance
                    correlations["cross_source_patterns"].append({
                        "pattern_type": "dominant_component",
                        "explained_variance": round(float(explained_variance[0]), 3),
                        "description": "Strong common pattern detected across multiple sources"
                    })
                    
        except Exception as e:
            self.logger(f"[{self.agent_id}] Correlation analysis error: {str(e)}")
            
        return correlations
    
    def _generate_hypotheses(self, df: pd.DataFrame, confidence_level: float) -> Dict[str, Any]:
        """Generate technical hypotheses with confidence scores"""
        hypotheses = {
            "hypotheses": [],
            "overall_confidence": 0.0
        }
        
        try:
            if df.empty:
                return hypotheses
                
            hypothesis_list = []
            
            # Hypothesis 1: Performance degradation pattern
            if 'latency' in df.columns and 'timestamp' in df.columns:
                try:
                    df_sorted = df.sort_values('timestamp')
                    recent_latency = df_sorted['latency'].tail(len(df) // 4).mean()
                    historical_latency = df_sorted['latency'].head(len(df) // 4).mean()
                    
                    if recent_latency > historical_latency * 1.5:
                        hypothesis_list.append({
                            "hypothesis": "System performance degradation detected",
                            "confidence": min(0.9, 0.5 + (recent_latency / historical_latency - 1) * 0.4),
                            "evidence": f"Recent latency ({recent_latency:.2f}) is {((recent_latency/historical_latency)-1)*100:.1f}% higher than historical average ({historical_latency:.2f})",
                            "recommended_action": "Investigate recent system changes or resource constraints"
                        })
                except:
                    pass
            
            # Hypothesis 2: Security threat pattern
            if 'error_rate' in df.columns:
                error_rate = df['error_rate'].mean()
                if error_rate > 0.1:  # More than 10% error rate
                    hypothesis_list.append({
                        "hypothesis": "Potential security threat or system misconfiguration",
                        "confidence": min(0.85, 0