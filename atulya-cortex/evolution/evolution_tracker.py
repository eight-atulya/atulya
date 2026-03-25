"""
Evolution Tracker

Tracks evolution through Git integration, maintains version history,
and manages evolutionary branches for self-evolution.
"""

import os
import json
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict


@dataclass
class EvolutionEvent:
    """Represents an evolution event."""
    generation: int
    timestamp: str
    fitness_score: float
    change_type: str  # mutation, crossover, replication
    description: str
    files_changed: List[str] = field(default_factory=list)
    git_commit: Optional[str] = None
    verified: bool = False
    rolled_back: bool = False


class EvolutionTracker:
    """
    Tracks evolution through Git and maintains evolution history.
    """
    
    def __init__(self, 
                 evolution_path: str = "evolution/evolution_history.json",
                 use_git: bool = True):
        """
        Initialize evolution tracker.
        
        Args:
            evolution_path: Path to store evolution history
            use_git: Whether to use Git for version control
        """
        self.evolution_path = evolution_path
        self.use_git = use_git
        self.evolution_history: List[EvolutionEvent] = []
        self.current_generation = 0
        self._load_history()
        self._init_git()
    
    def _init_git(self) -> None:
        """Initialize Git repository if not exists."""
        if not self.use_git:
            return
        
        if not os.path.exists('.git'):
            try:
                subprocess.run(['git', 'init'], 
                             capture_output=True, 
                             check=False)
                # Create initial commit if repo is empty
                try:
                    subprocess.run(['git', 'add', '.'], 
                                 capture_output=True, 
                                 check=False)
                    subprocess.run(['git', 'commit', '-m', 'Initial evolution baseline'], 
                                 capture_output=True, 
                                 check=False)
                except Exception:
                    pass
            except Exception:
                pass
    
    def _load_history(self) -> None:
        """Load evolution history from file."""
        if os.path.exists(self.evolution_path):
            try:
                with open(self.evolution_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.evolution_history = [
                        EvolutionEvent(**e) for e in data.get('history', [])
                    ]
                    self.current_generation = data.get('current_generation', 0)
            except Exception:
                self.evolution_history = []
                self.current_generation = 0
    
    def _save_history(self) -> None:
        """Save evolution history to file."""
        os.makedirs(os.path.dirname(self.evolution_path), exist_ok=True)
        data = {
            'current_generation': self.current_generation,
            'history': [asdict(e) for e in self.evolution_history]
        }
        with open(self.evolution_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def create_evolution_branch(self, branch_name: str) -> bool:
        """
        Create a new Git branch for evolution experiment.
        
        Args:
            branch_name: Name of the evolution branch
            
        Returns:
            True if branch created successfully
        """
        if not self.use_git:
            return False
        
        try:
            # Check if branch exists
            result = subprocess.run(
                ['git', 'branch', '--list', branch_name],
                capture_output=True,
                text=True
            )
            
            if branch_name in result.stdout:
                # Switch to existing branch
                subprocess.run(['git', 'checkout', branch_name], 
                            capture_output=True, 
                            check=False)
            else:
                # Create and switch to new branch
                subprocess.run(['git', 'checkout', '-b', branch_name], 
                            capture_output=True, 
                            check=False)
            return True
        except Exception:
            return False
    
    def commit_evolution(self, 
                        fitness_score: float,
                        change_type: str,
                        description: str,
                        files_changed: Optional[List[str]] = None) -> Optional[str]:
        """
        Commit evolution changes to Git.
        
        Args:
            fitness_score: Fitness score of this evolution
            change_type: Type of change (mutation, crossover, replication)
            description: Description of the evolution
            files_changed: List of files that changed
            
        Returns:
            Git commit hash if successful, None otherwise
        """
        if not self.use_git:
            return None
        
        try:
            # Stage all changes
            subprocess.run(['git', 'add', '.'], 
                         capture_output=True, 
                         check=False)
            
            # Create commit message
            commit_message = f"Evolution Gen {self.current_generation}: {description}\n"
            commit_message += f"Fitness: {fitness_score:.3f}, Type: {change_type}"
            
            # Commit
            result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Get commit hash
                commit_result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    capture_output=True,
                    text=True
                )
                commit_hash = commit_result.stdout.strip()
                
                # Record evolution event
                event = EvolutionEvent(
                    generation=self.current_generation,
                    timestamp=datetime.now().isoformat(),
                    fitness_score=fitness_score,
                    change_type=change_type,
                    description=description,
                    files_changed=files_changed or [],
                    git_commit=commit_hash
                )
                
                self.evolution_history.append(event)
                self.current_generation += 1
                self._save_history()
                
                return commit_hash
        except Exception:
            pass
        
        return None
    
    def rollback_evolution(self, generation: Optional[int] = None) -> bool:
        """
        Rollback to a previous evolution generation.
        
        Args:
            generation: Generation to rollback to, or None for previous
            
        Returns:
            True if rollback successful
        """
        if not self.evolution_history:
            return False
        
        if generation is None:
            # Rollback to previous generation
            if len(self.evolution_history) > 1:
                target_event = self.evolution_history[-2]
            else:
                return False
        else:
            # Find target generation
            target_event = None
            for event in self.evolution_history:
                if event.generation == generation:
                    target_event = event
                    break
            
            if not target_event:
                return False
        
        if not self.use_git or not target_event.git_commit:
            return False
        
        try:
            # Reset to target commit
            subprocess.run(['git', 'reset', '--hard', target_event.git_commit], 
                         capture_output=True, 
                         check=False)
            
            # Mark as rolled back
            target_event.rolled_back = True
            self._save_history()
            
            return True
        except Exception:
            return False
    
    def get_evolution_lineage(self) -> List[Dict[str, Any]]:
        """
        Get the evolution lineage (generation tree).
        
        Returns:
            List of evolution events in lineage
        """
        return [
            {
                'generation': e.generation,
                'timestamp': e.timestamp,
                'fitness': e.fitness_score,
                'type': e.change_type,
                'description': e.description,
                'commit': e.git_commit,
                'verified': e.verified,
                'rolled_back': e.rolled_back
            }
            for e in self.evolution_history
        ]
    
    def get_best_generation(self) -> Optional[EvolutionEvent]:
        """Get the generation with highest fitness score."""
        if not self.evolution_history:
            return None
        
        return max(self.evolution_history, key=lambda e: e.fitness_score)
    
    def should_replicate(self, current_fitness: float, threshold: float = 0.8) -> bool:
        """
        Determine if current generation should replicate (survival mechanism).
        
        Args:
            current_fitness: Current fitness score
            threshold: Fitness threshold for replication
            
        Returns:
            True if should replicate
        """
        if current_fitness >= threshold:
            return True
        
        # Also replicate if it's the best so far
        best = self.get_best_generation()
        if best and current_fitness >= best.fitness_score * 0.9:
            return True
        
        return False


if __name__ == "__main__":
    # Test evolution tracker
    tracker = EvolutionTracker()
    
    print("=== Evolution Tracker Test ===")
    
    # Create evolution branch
    tracker.create_evolution_branch("evolution/gen-1")
    
    # Commit an evolution
    commit_hash = tracker.commit_evolution(
        fitness_score=0.85,
        change_type="mutation",
        description="Improved self-awareness module",
        files_changed=["consciousness/self_awareness.py"]
    )
    
    print(f"\nEvolution committed: {commit_hash}")
    print(f"Current Generation: {tracker.current_generation}")
    
    # Get lineage
    lineage = tracker.get_evolution_lineage()
    print(f"\nEvolution Lineage ({len(lineage)} generations):")
    for event in lineage:
        print(f"  Gen {event['generation']}: {event['fitness']:.3f} - {event['description']}")
    
    best = tracker.get_best_generation()
    if best:
        print(f"\nBest Generation: {best.generation} (Fitness: {best.fitness_score:.3f})")

