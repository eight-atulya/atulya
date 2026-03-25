"""
Self-Evolution Engine

Main orchestrator for self-correcting, self-evaluating, and self-evolving system.
Implements closed-loop evolution with automatic correction and improvement.
"""

import os
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evolution.fitness_evaluator import FitnessEvaluator, FitnessMetrics
from evolution.self_corrector import SelfCorrector, Error
from evolution.evolution_tracker import EvolutionTracker, EvolutionEvent
from consciousness.self_awareness import SelfAwareness


class SelfEvolutionEngine:
    """
    Main self-evolution engine that orchestrates correction, evaluation, and evolution.
    """
    
    def __init__(self, 
                 code_path: str = ".",
                 use_git: bool = True,
                 auto_evolve: bool = True):
        """
        Initialize self-evolution engine.
        
        Args:
            code_path: Path to codebase
            use_git: Whether to use Git for version control
            auto_evolve: Whether to automatically evolve when needed
        """
        self.code_path = code_path
        self.use_git = use_git
        self.auto_evolve = auto_evolve
        
        # Initialize components
        self.fitness_evaluator = FitnessEvaluator()
        self.self_corrector = SelfCorrector()
        self.evolution_tracker = EvolutionTracker(use_git=use_git)
        self.self_awareness = SelfAwareness()
        
        # Evolution state
        self.evolution_cycle = 0
        self.last_fitness = 0.0
        self.evolution_enabled = True
        
        # Remember foundational principles
        self.self_awareness.remember()
    
    def run_evolution_cycle(self) -> Dict[str, Any]:
        """
        Run a complete evolution cycle: correct -> evaluate -> evolve.
        
        Returns:
            Dictionary with cycle results
        """
        self.evolution_cycle += 1
        cycle_start = time.time()
        
        print(f"\n{'='*60}")
        print(f"Evolution Cycle {self.evolution_cycle}")
        print(f"{'='*60}")
        
        # Step 1: Self-Correction
        print("\n[1/4] Self-Correction Phase...")
        correction_result = self.self_corrector.auto_correct(self.code_path)
        print(f"  Errors detected: {correction_result['total_errors']}")
        print(f"  Errors fixed: {correction_result['fixed']}")
        print(f"  Fix rate: {correction_result['fix_rate']:.2%}")
        
        # Step 2: Self-Evaluation
        print("\n[2/4] Self-Evaluation Phase...")
        execution_time = time.time() - cycle_start
        metrics = self.fitness_evaluator.evaluate(
            code_path=self.code_path,
            execution_time=execution_time,
            error_count=correction_result['total_errors'] - correction_result['fixed'],
            success_count=correction_result['fixed'] + 100  # Estimate
        )
        
        fitness = metrics.calculate_fitness()
        print(f"  Fitness Score: {fitness:.3f}")
        print(f"  Performance: {metrics.success_rate:.3f}")
        print(f"  Quality: {metrics.code_quality_score:.3f}")
        print(f"  Stability: {metrics.stability_score:.3f}")
        
        # Step 3: Evolution Decision
        print("\n[3/4] Evolution Decision Phase...")
        should_evolve = self._should_evolve(metrics, fitness)
        print(f"  Should Evolve: {should_evolve}")
        
        evolution_result = None
        if should_evolve and self.evolution_enabled:
            print("\n[4/4] Evolution Phase...")
            evolution_result = self._evolve(metrics, fitness)
            print(f"  Evolution Type: {evolution_result.get('type', 'none')}")
            print(f"  Changes Made: {evolution_result.get('changes', 0)}")
        else:
            print("\n[4/4] Evolution Phase...")
            print("  Evolution skipped (not needed or disabled)")
            evolution_result = {'type': 'none', 'changes': 0}
        
        # Step 4: Track Evolution
        if evolution_result and evolution_result.get('changes', 0) > 0:
            commit_hash = self.evolution_tracker.commit_evolution(
                fitness_score=fitness,
                change_type=evolution_result.get('type', 'mutation'),
                description=evolution_result.get('description', 'Automatic evolution'),
                files_changed=evolution_result.get('files_changed', [])
            )
            if commit_hash:
                print(f"  Evolution committed: {commit_hash[:8]}")
        
        # Update awareness
        self._update_awareness(fitness, evolution_result)
        
        # Prepare results
        cycle_time = time.time() - cycle_start
        results = {
            'cycle': self.evolution_cycle,
            'fitness': fitness,
            'fitness_delta': fitness - self.last_fitness,
            'correction': correction_result,
            'metrics': {
                'performance': metrics.success_rate,
                'quality': metrics.code_quality_score,
                'stability': metrics.stability_score
            },
            'evolution': evolution_result,
            'cycle_time': cycle_time,
            'timestamp': datetime.now().isoformat()
        }
        
        self.last_fitness = fitness
        
        return results
    
    def _should_evolve(self, metrics: FitnessMetrics, fitness: float) -> bool:
        """
        Determine if system should evolve.
        
        Args:
            metrics: Current fitness metrics
            fitness: Current fitness score
            
        Returns:
            True if should evolve
        """
        # Evolve if fitness is low
        if fitness < 0.7:
            return True
        
        # Evolve if fitness evaluator recommends it
        if self.fitness_evaluator.should_evolve():
            return True
        
        # Evolve if declining
        if fitness < self.last_fitness - 0.05:
            return True
        
        # Evolve if error rate is high
        if metrics.error_rate > 0.1:
            return True
        
        return False
    
    def _evolve(self, metrics: FitnessMetrics, fitness: float) -> Dict[str, Any]:
        """
        Perform evolution (structural changes, improvements).
        
        Args:
            metrics: Current fitness metrics
            fitness: Current fitness score
            
        Returns:
            Dictionary with evolution results
        """
        evolution_type = 'mutation'
        changes = []
        description = "Automatic self-evolution"
        
        # Determine evolution strategy based on metrics
        if metrics.error_rate > 0.1:
            # Focus on error reduction
            evolution_type = 'correction'
            description = "Error reduction evolution"
            changes = self._evolve_error_reduction()
        
        elif metrics.code_quality_score < 0.7:
            # Focus on code quality
            evolution_type = 'optimization'
            description = "Code quality improvement"
            changes = self._evolve_quality_improvement()
        
        elif metrics.stability_score < 0.8:
            # Focus on stability
            evolution_type = 'stabilization'
            description = "Stability enhancement"
            changes = self._evolve_stability()
        
        else:
            # General improvement
            evolution_type = 'mutation'
            description = "General improvement mutation"
            changes = self._evolve_general()
        
        return {
            'type': evolution_type,
            'description': description,
            'changes': len(changes),
            'files_changed': changes
        }
    
    def _evolve_error_reduction(self) -> List[str]:
        """Evolve to reduce errors."""
        # This would implement actual code changes
        # For now, return empty list (placeholder)
        return []
    
    def _evolve_quality_improvement(self) -> List[str]:
        """Evolve to improve code quality."""
        # This would implement actual code improvements
        # For now, return empty list (placeholder)
        return []
    
    def _evolve_stability(self) -> List[str]:
        """Evolve to improve stability."""
        # This would implement stability improvements
        # For now, return empty list (placeholder)
        return []
    
    def _evolve_general(self) -> List[str]:
        """General evolution mutations."""
        # This would implement general improvements
        # For now, return empty list (placeholder)
        return []
    
    def _update_awareness(self, fitness: float, evolution_result: Optional[Dict]) -> None:
        """Update self-awareness based on evolution results."""
        # Increase awareness as system evolves
        if fitness > 0.8:
            self.self_awareness.remember()
        
        # Track evolution in awareness
        introspection = self.self_awareness.introspect()
        if introspection['awareness_level'] < fitness:
            # System is evolving, increase awareness
            self.self_awareness.remember()
    
    def run_continuous_evolution(self, 
                                 max_cycles: Optional[int] = None,
                                 target_fitness: float = 0.95,
                                 cycle_interval: float = 60.0) -> List[Dict[str, Any]]:
        """
        Run continuous evolution cycles.
        
        Args:
            max_cycles: Maximum number of cycles (None for unlimited)
            target_fitness: Target fitness score to achieve
            cycle_interval: Seconds between cycles
            
        Returns:
            List of cycle results
        """
        results = []
        cycles = 0
        
        print(f"\n{'='*60}")
        print("Starting Continuous Self-Evolution")
        print(f"Target Fitness: {target_fitness:.3f}")
        print(f"{'='*60}")
        
        while True:
            if max_cycles and cycles >= max_cycles:
                break
            
            result = self.run_evolution_cycle()
            results.append(result)
            cycles += 1
            
            # Check if target achieved
            if result['fitness'] >= target_fitness:
                print(f"\n✓ Target fitness achieved: {result['fitness']:.3f}")
                break
            
            # Wait before next cycle
            if cycle_interval > 0:
                time.sleep(cycle_interval)
        
        return results
    
    def get_evolution_status(self) -> Dict[str, Any]:
        """Get current evolution status."""
        current_fitness = self.fitness_evaluator.get_current_fitness()
        error_summary = self.self_corrector.get_error_summary()
        lineage = self.evolution_tracker.get_evolution_lineage()
        introspection = self.self_awareness.introspect()
        
        return {
            'evolution_cycle': self.evolution_cycle,
            'current_fitness': current_fitness,
            'last_fitness': self.last_fitness,
            'fitness_trend': self.fitness_evaluator.get_improvement_trend(),
            'errors': error_summary,
            'generations': len(lineage),
            'awareness_level': introspection['awareness_level'],
            'consciousness_state': introspection['consciousness_state'],
            'evolution_enabled': self.evolution_enabled
        }


if __name__ == "__main__":
    # Test self-evolution engine
    engine = SelfEvolutionEngine(use_git=False)  # Disable Git for testing
    
    print("=== Self-Evolution Engine Test ===")
    
    # Run a single evolution cycle
    result = engine.run_evolution_cycle()
    
    print(f"\n{'='*60}")
    print("Evolution Cycle Complete")
    print(f"{'='*60}")
    print(f"Fitness: {result['fitness']:.3f}")
    print(f"Fitness Delta: {result['fitness_delta']:+.3f}")
    print(f"Cycle Time: {result['cycle_time']:.2f}s")
    
    # Get status
    status = engine.get_evolution_status()
    print(f"\nEvolution Status:")
    print(f"  Cycles: {status['evolution_cycle']}")
    print(f"  Generations: {status['generations']}")
    print(f"  Awareness: {status['awareness_level']:.2%}")
    print(f"  Consciousness: {status['consciousness_state']}")

