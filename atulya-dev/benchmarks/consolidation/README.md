# Consolidation Performance Benchmark

## Overview

This benchmark measures consolidation throughput (operations per second) and identifies bottlenecks in the consolidation pipeline.

## Quick Start

```bash
# Run with default settings (100 memories)
./scripts/benchmarks/run-consolidation.sh

# Run with custom number of memories
NUM_MEMORIES=50 ./scripts/benchmarks/run-consolidation.sh

# Run with different model
export ATULYA_API_CONSOLIDATION_LLM_MODEL=llama-3.1-70b-versatile
NUM_MEMORIES=100 ./scripts/benchmarks/run-consolidation.sh
```

## What It Measures

The benchmark:
1. Creates N test memories with diverse content (similar facts, contradictions, different entities)
2. Runs consolidation and measures time spent in each component:
   - **Recall**: Finding related observations
   - **LLM**: Deciding on consolidation actions
   - **Embedding**: Generating embeddings for new/updated observations
   - **DB Write**: Writing to database
3. Reports throughput (op/sec) and detailed timing breakdown

## Interpreting Results

### Metrics
- **Throughput (op/sec)**: Memories processed per second
- **Timing Breakdown**: % of time spent in each component
- **Observations Created/Updated**: Quality indicator

### Baseline Performance (groq/openai/gpt-oss-120b)
- **~0.7-1.0 op/sec** (1-1.4 seconds per memory)
- **LLM: 80-87%** of time (main bottleneck)
- **Recall: 10-17%** of time (secondary bottleneck)

## Results

See:
- `ANALYSIS.md` - Detailed bottleneck analysis
- `RESULTS.md` - Performance results and recommendations
- `benchmarks/results/` - Raw benchmark data (JSON)

## Optimizations

### Implemented
✅ Batch database queries (fixed N+1 problem)
✅ Reduced recall token budget (5000 → 2000)
✅ Limited observation results (top 15)

### Recommended
🔧 Use faster LLM model for consolidation
🔧 Enable prompt caching (if available)
🔧 Optimize prompt verbosity

See `RESULTS.md` for detailed recommendations.

## Configuration

Environment variables:
- `NUM_MEMORIES`: Number of memories to create (default: 100)
- `ATULYA_API_CONSOLIDATION_LLM_MODEL`: Model for consolidation
- `ATULYA_API_CONSOLIDATION_LLM_PROVIDER`: Provider for consolidation
- `ATULYA_API_DATABASE_URL`: Database URL
- `ATULYA_LOG_LEVEL`: Logging level (INFO for detailed logs)

## Example Output

```
Consolidation Benchmark Results
┌────────────────────────────────┬─────────────┐
│ Metric                         │ Value       │
├────────────────────────────────┼─────────────┤
│ Total Time                     │ 60.28s      │
│ Memories Processed             │ 43          │
│ Throughput                     │ 0.71 op/sec │
│ Avg Time/Memory                │ 1.402s      │
│                                │             │
│ Observations Created           │ 4           │
│ Observations Updated           │ 38          │
│ Observations Merged            │ 0           │
│ Skipped (No Durable Knowledge) │ 1           │
└────────────────────────────────┴─────────────┘

Timing breakdown:
  recall=6.295s (10.4%)
  llm=52.144s (86.5%) ← BOTTLENECK
  embedding=1.717s (2.8%)
  db_write=0.075s (0.1%)
```
