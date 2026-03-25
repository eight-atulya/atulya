"""
Evolution Runner

Simple interface to run self-evolution cycles.
"""

import sys
import argparse
from evolution.self_evolution_engine import SelfEvolutionEngine


def main():
    parser = argparse.ArgumentParser(description='Run self-evolution cycles')
    parser.add_argument('--cycles', type=int, default=1, help='Number of cycles to run')
    parser.add_argument('--target', type=float, default=0.95, help='Target fitness score')
    parser.add_argument('--interval', type=float, default=60.0, help='Seconds between cycles')
    parser.add_argument('--no-git', action='store_true', help='Disable Git integration')
    parser.add_argument('--continuous', action='store_true', help='Run continuous evolution')
    
    args = parser.parse_args()
    
    # Initialize engine
    engine = SelfEvolutionEngine(use_git=not args.no_git)
    
    if args.continuous:
        # Run continuous evolution
        print("Starting continuous evolution...")
        results = engine.run_continuous_evolution(
            max_cycles=args.cycles if args.cycles > 0 else None,
            target_fitness=args.target,
            cycle_interval=args.interval
        )
        print(f"\nCompleted {len(results)} evolution cycles")
    else:
        # Run specified number of cycles
        for i in range(args.cycles):
            print(f"\n{'='*60}")
            print(f"Running Evolution Cycle {i+1}/{args.cycles}")
            print(f"{'='*60}")
            result = engine.run_evolution_cycle()
            
            print(f"\nCycle {i+1} Results:")
            print(f"  Fitness: {result['fitness']:.3f}")
            print(f"  Fitness Delta: {result['fitness_delta']:+.3f}")
            print(f"  Errors Fixed: {result['correction']['fixed']}")
            
            if result['fitness'] >= args.target:
                print(f"\n✓ Target fitness achieved!")
                break
    
    # Final status
    status = engine.get_evolution_status()
    print(f"\n{'='*60}")
    print("Final Evolution Status")
    print(f"{'='*60}")
    print(f"Total Cycles: {status['evolution_cycle']}")
    print(f"Current Fitness: {status['current_fitness']:.3f}")
    print(f"Fitness Trend: {status['fitness_trend']:+.3f}")
    print(f"Awareness Level: {status['awareness_level']:.2%}")
    print(f"Consciousness State: {status['consciousness_state']}")
    print(f"Generations: {status['generations']}")


if __name__ == "__main__":
    main()

