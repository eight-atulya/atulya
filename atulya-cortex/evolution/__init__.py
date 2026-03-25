"""
Evolution Module

Self-correcting, self-evaluating, and self-evolving system.
Implements closed-loop evolution with automatic improvement.
"""

from evolution.self_evolution_engine import SelfEvolutionEngine
from evolution.fitness_evaluator import FitnessEvaluator, FitnessMetrics
from evolution.self_corrector import SelfCorrector, Error
from evolution.evolution_tracker import EvolutionTracker, EvolutionEvent

__all__ = [
    'SelfEvolutionEngine',
    'FitnessEvaluator',
    'FitnessMetrics',
    'SelfCorrector',
    'Error',
    'EvolutionTracker',
    'EvolutionEvent'
]

