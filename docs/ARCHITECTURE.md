# Architecture

## Layers

### 1. Skill Spec
Portable package format for Graphsmiths.

### 2. Registry
Stores:
- contracts
- graph bodies
- retrieval artifacts
- execution evidence

### 3. Planner
Retrieves candidate skills and composes a glue graph.

### 4. Validator/Compiler
Checks typing, effects, dependencies, DAG boundedness, and required inputs.
Compiles graph into an execution plan.

### 5. Runtime
Executes nodes deterministically, captures traces, returns outputs.

## Core abstractions

### Graphsmith
Reusable package with contract and graph body.

### GlueGraph
Task-specific composition referencing multiple skills.

### Trace
Node-level execution record.

### PromotionCandidate
A recurring trace fragment that may become a reusable Graphsmith.

## Data flow

1. User goal enters planner
2. Planner retrieves candidate skills from registry
3. Planner emits GlueGraph
4. Validator checks GlueGraph
5. Runtime executes
6. Trace is stored
7. Promotion service later mines recurring fragments

## Why separate planner and runtime

The planner is probabilistic.
The runtime must remain deterministic and inspectable.
This separation is non-negotiable.
