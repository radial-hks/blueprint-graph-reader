# Blueprint Graph Reader

UE5 Editor plugin that extracts Blueprint graph structure (nodes, pins, edges, variables, components, timelines, interfaces) as JSON for AI Agent consumption.

## Project Structure

```
blueprint-graph-reader/
├── BlueprintGraphReader.uplugin    # UE plugin manifest
├── Source/
│   └── BlueprintGraphReader/
│       ├── BlueprintGraphReader.Build.cs   # Module build config
│       ├── Public/
│       │   ├── BlueprintGraphReader.h           # Main API (UBlueprintFunctionLibrary)
│       │   └── BlueprintGraphReaderModule.h     # Module registration
│       └── Private/
│           ├── BlueprintGraphReader.cpp          # API implementation + serialization
│           └── BlueprintGraphReaderModule.cpp    # Module startup/shutdown
├── Python/
│   ├── __init__.py                # Package marker
│   ├── extract_blueprint.py       # One-shot extraction (UE Python → JSON file)
│   ├── graph_to_pseudocode.py     # JSON → indented pseudocode (22 node handlers)
│   ├── graph_to_mermaid.py        # JSON → Mermaid flowchart
│   └── graph_to_graphify.py       # JSON → graphify knowledge graph
├── Tests/
│   └── test_pseudocode.py         # Unit tests for pseudocode generator (8/8 pass)
└── docs/
    ├── proposal.md                # Technical design document
    └── development-plan.md         # 5-phase development plan
```

## Build & Install

1. Copy or symlink the entire `blueprint-graph-reader/` directory into your UE project's `Plugins/` folder
2. Regenerate project files (right-click .uproject → Generate Visual Studio project files)
3. Build the project (Editor configuration)
4. Enable the plugin in Edit → Plugins → Blueprint Graph Reader

## Usage (Python Console in UE Editor)

```python
import unreal

# One-shot: extract blueprint to JSON file
import extract_blueprint
extract_blueprint.extract("/Game/MyActor", output_path="~/my_actor.json")

# Or call C++ API directly via Python
bp = unreal.load_asset("/Game/MyActor.MyActor")
json_str = unreal.BlueprintGraphReader.extract_blueprint_as_json(bp)

# Other public APIs
names = unreal.BlueprintGraphReader.get_blueprint_graph_names(bp)
nodes = unreal.BlueprintGraphReader.get_graph_nodes(graph)
pin_info = unreal.BlueprintGraphReader.get_node_pin_info(node)
semantic = unreal.BlueprintGraphReader.get_node_semantic_info(node)
vars = unreal.BlueprintGraphReader.get_blueprint_variables(bp)
```

## JSON Output Schema (v1)

Key fields in the output JSON:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"v1"` |
| `asset_path` | string | Blueprint asset path |
| `blueprint_type` | string | EBPType enum name |
| `parent_class` | string \| null | Always present; `null` if none |
| `variables[]` | array | Blueprint variables with name, type, default_value, flags |
| `graphs[]` | array | UbergraphPages + FunctionGraphs + DelegateSignatureGraphs |
| `macro_graphs[]` | array | Macro graphs (separate from `graphs`) |
| `components[]` | array | SCS component tree (Actor blueprints only) |
| `timelines[]` | array | Timeline template metadata (name, loop, length) |
| `interfaces[]` | array | Implemented interfaces (name, graph_count) |

### Graph types

| graph_type | Source |
|-----------|--------|
| `ubergraph` | UbergraphPages (EventGraph) |
| `function` | FunctionGraphs (user functions) |
| `construction_script` | FunctionGraphs named "ConstructionScript" |
| `delegate_signature` | DelegateSignatureGraphs |
| `macro` | MacroGraphs |

### Node structure

Each node contains: `id` (n0, n1...), `class` (normalized K2Node name), `title` (truncated at 256 chars), `comment`, `position` [x, y], `pins[]`.

### Pin structure

Each pin contains: `id` (p0, p1...), `name`, `direction` (input/output), `pin_type`, `sub_type` (object/struct only), `default_value`, `is_exec` (bool).

### Edge structure

`from_pin` → `to_pin` with `edge_type`: `"exec"` (control flow) or `"data"` (data flow).

## Design Principles

- **Read-only**: Never modifies blueprint data
- **Editor-only**: Compiles only in Editor builds (bUsesEditorAPIs = true)
- **Pin-level modeling**: Preserves exec/data edge distinction via `is_exec` + `edge_type`
- **Deterministic output**: `node.class` (normalized K2Node subclass name) as stable semantic signal
- **Safe ID scheme**: Pure sequential IDs (n0/n1... p0/p1...), pointer-based edge dedup
- **Title truncation**: Titles > 256 chars are truncated with "..."
- **Plugin lazy detection**: Python scripts detect C++ plugin availability at call time, not import time

## Dependencies

- UE 5.4+ (tested on 5.4/5.5)
- C++ Modules: Core, Engine, BlueprintGraph, UnrealEd, Json, JsonUtilities, Kismet, CoreUObject, EditorScriptingUtilities
- Python: `unreal` (Editor only), `json`, `sys` (stdlib only)
