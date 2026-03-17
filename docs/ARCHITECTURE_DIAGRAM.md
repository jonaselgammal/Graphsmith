# Graphsmith Architecture

## System overview

```mermaid
flowchart TD
    Goal["User Goal<br/>(natural language)"] --> Planner

    subgraph Planner ["Planner Layer"]
        Candidates["Candidate<br/>Retrieval"] --> PromptBuilder["Prompt<br/>Builder"]
        PromptBuilder --> LLMProvider["LLM Provider<br/>(Anthropic / OpenAI / Echo)"]
        LLMProvider --> Parser["Output Parser"]
    end

    Registry["Local Registry<br/>(publish / search / fetch)"] --> Candidates

    Parser --> GlueGraph["GlueGraph<br/>(task-specific plan)"]

    GlueGraph --> Validator

    subgraph Validator ["Validation"]
        StructCheck["Structure<br/>Types · Ops · Edges"]
        DAGCheck["DAG Check"]
        BindingCheck["Binding<br/>Conflicts"]
    end

    Validator --> Runtime

    subgraph Runtime ["Deterministic Runtime"]
        TopoSort["Topological<br/>Sort"] --> Executor["Node<br/>Executor"]
        Executor --> |"skill.invoke"| SubSkill["Sub-Skill<br/>Execution"]
        SubSkill --> Executor
    end

    SkillPackages["Reusable Skill<br/>Packages<br/>(YAML)"] --> Registry
    SkillPackages --> Validator
    SkillPackages --> Runtime

    Runtime --> Outputs["Execution<br/>Outputs"]
    Runtime --> Traces["Execution<br/>Traces"]

    Traces --> Promotion["Promotion<br/>Candidate Mining"]

    style GlueGraph fill:#ffd,stroke:#aa0
    style SkillPackages fill:#dfd,stroke:#0a0
    style Registry fill:#def,stroke:#08a
```

## Key distinction: Skills vs Glue Graphs

```mermaid
flowchart LR
    subgraph Reusable ["Reusable Skills"]
        S1["text.normalize.v1"]
        S2["text.summarize.v1"]
        S3["text.extract_keywords.v1"]
    end

    subgraph TaskSpecific ["Task-Specific Glue Graph"]
        G["normalize → extract keywords"]
    end

    S1 --> |"skill.invoke"| G
    S3 --> |"skill.invoke"| G

    G --> |"ephemeral,<br/>not published"| Output["Execution Result"]
    S1 --> |"published to<br/>registry"| Registry["Registry"]
    S2 --> |"published to<br/>registry"| Registry
    S3 --> |"published to<br/>registry"| Registry

    style Reusable fill:#dfd,stroke:#0a0
    style TaskSpecific fill:#ffd,stroke:#aa0
```

## Data flow through a skill graph

```mermaid
flowchart LR
    Input["Graph Inputs<br/>input.text"] --> N1["Node: template.render<br/>config: template"]
    N1 --> |"rendered"| N2["Node: llm.generate"]
    N2 --> |"text"| Output["Graph Output<br/>summary"]

    style Input fill:#eef,stroke:#44a
    style Output fill:#efe,stroke:#4a4
```

## Module layout

```
graphsmith/
├── models/      ← Pydantic models (spec layer)
├── parser/      ← YAML package loader
├── validator/   ← Deterministic validation
├── runtime/     ← Topological executor + value store
├── ops/         ← Primitive op implementations + LLM providers
├── registry/    ← Local file registry + index
├── planner/     ← LLM planner + prompt builder + output parser
├── traces/      ← Trace persistence + promotion mining
└── cli/         ← Typer CLI (all commands)
```
