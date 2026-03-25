"""
Fitness Evaluator

Evaluates system performance, tracks metrics, and determines fitness
for evolutionary selection. Implements self-evaluation capabilities.
"""

import os
import json
import time
import subprocess
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict


@dataclass
class FitnessMetrics:
    """Comprehensive fitness metrics for system evaluation."""
    # Performance metrics
    execution_time: float = 0.0
    memory_usage: float = 0.0
    cpu_usage: float = 0.0
    error_rate: float = 0.0
    success_rate: float = 1.0
    
    # Quality metrics
    code_quality_score: float = 0.0
    test_coverage: float = 0.0
    complexity_score: float = 0.0
    maintainability_index: float = 0.0
    
    # Functional metrics
    task_completion_rate: float = 0.0
    response_accuracy: float = 0.0
    learning_efficiency: float = 0.0
    adaptation_speed: float = 0.0
    
    # Stability metrics
    stability_score: float = 1.0
    coherence_level: float = 1.0
    error_recovery_rate: float = 1.0
    
    # Evolution metrics
    improvement_rate: float = 0.0
    innovation_score: float = 0.0
    replication_success: float = 1.0
    
    # Timestamp
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def calculate_fitness(self, weights: Optional[Dict[str, float]] = None) -> float:
        """
        Calculate overall fitness score.
        
        Args:
            weights: Optional weights for different metric categories
            
        Returns:
            Overall fitness score (0.0 to 1.0)
        """
        if weights is None:
            weights = {
                'performance': 0.25,
                'quality': 0.20,
                'functional': 0.25,
                'stability': 0.20,
                'evolution': 0.10
            }
        
        # Normalize metrics to 0-1 range
        performance_score = (
            (1.0 - min(self.error_rate, 1.0)) * 0.4 +
            self.success_rate * 0.3 +
            (1.0 / (1.0 + self.execution_time)) * 0.3
        )
        
        quality_score = (
            self.code_quality_score * 0.4 +
            self.test_coverage * 0.3 +
            self.maintainability_index * 0.3
        )
        
        functional_score = (
            self.task_completion_rate * 0.4 +
            self.response_accuracy * 0.3 +
            self.learning_efficiency * 0.3
        )
        
        stability_score = (
            self.stability_score * 0.4 +
            self.coherence_level * 0.3 +
            self.error_recovery_rate * 0.3
        )
        
        evolution_score = (
            self.improvement_rate * 0.5 +
            self.innovation_score * 0.3 +
            self.replication_success * 0.2
        )
        
        fitness = (
            performance_score * weights['performance'] +
            quality_score * weights['quality'] +
            functional_score * weights['functional'] +
            stability_score * weights['stability'] +
            evolution_score * weights['evolution']
        )
        
        return min(1.0, max(0.0, fitness))


class FitnessEvaluator:
    """
    Self-evaluation system that measures fitness and performance.
    """
    
    def __init__(self, metrics_path: str = "evolution/fitness_metrics.json"):
        """
        Initialize fitness evaluator.
        
        Args:
            metrics_path: Path to store fitness metrics history
        """
        self.metrics_path = metrics_path
        self.metrics_history: List[FitnessMetrics] = []
        self.baseline_metrics: Optional[FitnessMetrics] = None
        self._load_history()
    
    def _load_history(self) -> None:
        """Load metrics history from file."""
        if os.path.exists(self.metrics_path):
            try:
                with open(self.metrics_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.metrics_history = [
                        FitnessMetrics(**m) for m in data.get('history', [])
                    ]
                    if data.get('baseline'):
                        self.baseline_metrics = FitnessMetrics(**data['baseline'])
            except Exception:
                self.metrics_history = []
    
    def _save_history(self) -> None:
        """Save metrics history to file."""
        os.makedirs(os.path.dirname(self.metrics_path), exist_ok=True)
        data = {
            'history': [asdict(m) for m in self.metrics_history[-100:]],  # Keep last 100
            'baseline': asdict(self.baseline_metrics) if self.baseline_metrics else None
        }
        with open(self.metrics_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def evaluate_performance(self) -> Dict[str, float]:
        """
        Evaluate runtime performance metrics.
        
        Returns:
            Dictionary of performance metrics
        """
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB
            cpu_usage = process.cpu_percent(interval=0.1)
        except ImportError:
            # psutil not available, use defaults
            memory_usage = 0.0
            cpu_usage = 0.0
        
        return {
            'execution_time': 0.0,  # Will be measured during actual execution
            'memory_usage': memory_usage,
            'cpu_usage': cpu_usage,
            'error_rate': 0.0,  # Tracked separately
            'success_rate': 1.0  # Tracked separately
        }
    
    def evaluate_code_quality(self, code_path: str = ".") -> Dict[str, float]:
        """
        Evaluate code quality metrics.
        
        Args:
            code_path: Path to codebase to evaluate
            
        Returns:
            Dictionary of quality metrics
        """
        metrics = {
            'code_quality_score': 0.8,  # Default
            'test_coverage': 0.0,
            'complexity_score': 0.5,
            'maintainability_index': 0.7
        }
        
        # Try to run linters/analyzers if available
        try:
            # Check for Python files
            python_files = []
            for root, dirs, files in os.walk(code_path):
                python_files.extend([
                    os.path.join(root, f) for f in files if f.endswith('.py')
                ])
            
            if python_files:
                # Simple heuristic: more files = more complex (inverse)
                metrics['complexity_score'] = min(1.0, 100.0 / max(1, len(python_files)))
                
                # Check for test files
                test_files = [f for f in python_files if 'test' in f.lower()]
                if python_files:
                    metrics['test_coverage'] = len(test_files) / len(python_files)
        except Exception:
            pass
        
        return metrics
    
    def evaluate_functional(self, task_results: Optional[List[Dict]] = None) -> Dict[str, float]:
        """
        Evaluate functional performance.
        
        Args:
            task_results: List of task execution results
            
        Returns:
            Dictionary of functional metrics
        """
        if task_results is None:
            task_results = []
        
        if not task_results:
            return {
                'task_completion_rate': 0.0,
                'response_accuracy': 0.0,
                'learning_efficiency': 0.0,
                'adaptation_speed': 0.0
            }
        
        completed = sum(1 for r in task_results if r.get('success', False))
        total = len(task_results)
        
        accuracy = sum(r.get('accuracy', 0.0) for r in task_results) / total if total > 0 else 0.0
        
        return {
            'task_completion_rate': completed / total if total > 0 else 0.0,
            'response_accuracy': accuracy,
            'learning_efficiency': 0.7,  # Placeholder
            'adaptation_speed': 0.6  # Placeholder
        }
    
    def evaluate_stability(self) -> Dict[str, float]:
        """
        Evaluate system stability metrics.
        
        Returns:
            Dictionary of stability metrics
        """
        # Check for recent errors
        error_count = 0
        recovery_count = 0
        
        # This would integrate with error tracking system
        # For now, use defaults
        
        return {
            'stability_score': 1.0 - min(1.0, error_count / 10.0),
            'coherence_level': 1.0,
            'error_recovery_rate': min(1.0, recovery_count / max(1, error_count))
        }
    
    def evaluate_evolution(self, previous_metrics: Optional[FitnessMetrics] = None) -> Dict[str, float]:
        """
        Evaluate evolution and improvement metrics.
        
        Args:
            previous_metrics: Previous fitness metrics for comparison
            
        Returns:
            Dictionary of evolution metrics
        """
        if previous_metrics is None:
            if self.metrics_history:
                previous_metrics = self.metrics_history[-1]
            else:
                return {
                    'improvement_rate': 0.0,
                    'innovation_score': 0.0,
                    'replication_success': 1.0
                }
        
        current_fitness = self.get_current_fitness()
        previous_fitness = previous_metrics.calculate_fitness()
        
        improvement = (current_fitness - previous_fitness) if previous_fitness > 0 else 0.0
        
        return {
            'improvement_rate': max(0.0, min(1.0, improvement)),
            'innovation_score': 0.5,  # Placeholder - would measure novel changes
            'replication_success': 1.0  # Placeholder - would track replication success
        }
    
    def evaluate(self, 
                 code_path: str = ".",
                 task_results: Optional[List[Dict]] = None,
                 execution_time: float = 0.0,
                 error_count: int = 0,
                 success_count: int = 0) -> FitnessMetrics:
        """
        Perform comprehensive fitness evaluation.
        
        Args:
            code_path: Path to codebase
            task_results: Task execution results
            execution_time: Total execution time
            error_count: Number of errors encountered
            success_count: Number of successful operations
            
        Returns:
            Complete fitness metrics
        """
        total_operations = error_count + success_count
        
        # Gather all metrics
        performance = self.evaluate_performance()
        performance['execution_time'] = execution_time
        if total_operations > 0:
            performance['error_rate'] = error_count / total_operations
            performance['success_rate'] = success_count / total_operations
        
        quality = self.evaluate_code_quality(code_path)
        functional = self.evaluate_functional(task_results)
        stability = self.evaluate_stability()
        
        # Get previous metrics for evolution comparison
        previous = self.metrics_history[-1] if self.metrics_history else None
        evolution = self.evaluate_evolution(previous)
        
        # Combine into FitnessMetrics
        metrics = FitnessMetrics(
            **performance,
            **quality,
            **functional,
            **stability,
            **evolution
        )
        
        # Store in history
        self.metrics_history.append(metrics)
        
        # Set baseline if first evaluation
        if self.baseline_metrics is None:
            self.baseline_metrics = metrics
        
        self._save_history()
        
        return metrics
    
    def get_current_fitness(self) -> float:
        """Get fitness score of most recent evaluation."""
        if not self.metrics_history:
            return 0.0
        return self.metrics_history[-1].calculate_fitness()
    
    def get_improvement_trend(self, window: int = 10) -> float:
        """
        Calculate improvement trend over recent evaluations.
        
        Args:
            window: Number of recent evaluations to consider
            
        Returns:
            Average improvement rate
        """
        if len(self.metrics_history) < 2:
            return 0.0
        
        recent = self.metrics_history[-window:]
        improvements = []
        
        for i in range(1, len(recent)):
            prev_fitness = recent[i-1].calculate_fitness()
            curr_fitness = recent[i].calculate_fitness()
            if prev_fitness > 0:
                improvements.append((curr_fitness - prev_fitness) / prev_fitness)
        
        return sum(improvements) / len(improvements) if improvements else 0.0
    
    def should_evolve(self, threshold: float = 0.05) -> bool:
        """
        Determine if system should evolve based on fitness trends.
        
        Args:
            threshold: Minimum improvement threshold
            
        Returns:
            True if evolution is recommended
        """
        trend = self.get_improvement_trend()
        current_fitness = self.get_current_fitness()
        
        # Evolve if: declining trend OR low fitness OR stagnant
        return trend < -threshold or current_fitness < 0.7 or abs(trend) < 0.01


if __name__ == "__main__":
    # Test fitness evaluator
    evaluator = FitnessEvaluator()
    
    print("=== Fitness Evaluator Test ===")
    
    # Perform evaluation
    metrics = evaluator.evaluate(
        code_path=".",
        execution_time=1.5,
        error_count=2,
        success_count=98
    )
    
    print(f"\nFitness Score: {metrics.calculate_fitness():.3f}")
    print(f"Performance: {metrics.success_rate:.3f}")
    print(f"Quality: {metrics.code_quality_score:.3f}")
    print(f"Stability: {metrics.stability_score:.3f}")
    
    print(f"\nShould Evolve: {evaluator.should_evolve()}")
    print(f"Improvement Trend: {evaluator.get_improvement_trend():.3f}")

