# Blueprint Graph Reader

UE5 Editor plugin that extracts Blueprint and Material graph structure as JSON for AI Agent consumption.

## Project Structure

```
blueprint-graph-reader/
├── BlueprintGraphReader.uplugin    # UE plugin manifest
├── Source/
│   └── BlueprintGraphReader/
│       ├── BlueprintGraphReader.Build.cs   # Module build config
│       ├── Public/
│       │   ├── BlueprintGraphReader.h           # Blueprint Main API (UBlueprintGraphReader)
│       │   ├── BlueprintGraphReaderModule.h     # Module registration
│       │   └── MaterialGraphReader.h            # Material Main API (UMaterialGraphReader)
│       └── Private/
│           ├── BlueprintGraphReader.cpp          # Blueprint API implementation + serialization
│           ├── BlueprintGraphReaderModule.cpp    # Module startup/shutdown
│           └── MaterialGraphReader.cpp           # Material API implementation + serialization
├── Python/
│   ├── __init__.py                # Package marker
│   ├── extract_blueprint.py       # Blueprint one-shot extraction (UE Python → JSON file)
│   ├── extract_material.py        # Material one-shot extraction (UE Python → JSON file)
│   ├── graph_to_pseudocode.py     # Blueprint JSON → indented pseudocode (22 node handlers)
│   ├── graph_to_mermaid.py        # Blueprint JSON → Mermaid flowchart
│   └── graph_to_graphify.py       # Blueprint JSON → graphify knowledge graph
├── Tests/
│   └── test_pseudocode.py         # Unit tests for pseudocode generator (8/8 pass)
└── docs/
    ├── proposal.md                # Blueprint technical design document
    ├── development-plan.md        # Blueprint 5-phase development plan
    └── material-reader-plan.md    # Material reader design & development plan
```

## Build & Install

1. Copy or symlink the entire `blueprint-graph-reader/` directory into your UE project's `Plugins/` folder
2. Regenerate project files (right-click .uproject → Generate Visual Studio project files)
3. Build the project (Editor configuration)
4. Enable the plugin in Edit → Plugins → Blueprint Graph Reader

## Blueprint Usage (Python Console in UE Editor)

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

## Material Usage (Python Console in UE Editor)

```python
import unreal

# One-shot: extract material to JSON file
import extract_material
extract_material.extract("/Game/Materials/M_Master", output_path="~/m_master.json")

# Batch extraction
extract_material.extract_all("/Game/Materials/", output_dir="~/material_graphs/")

# Or call C++ API directly via Python
mat = unreal.load_asset("/Game/Materials/M_Master")
json_str = unreal.MaterialGraphReader.extract_material_as_json(mat)

# Extract material function
mf = unreal.load_asset("/Game/Materials/MF_Noise")
json_str = unreal.MaterialGraphReader.extract_material_function_as_json(mf)

# Query single expression
expr_info = unreal.MaterialGraphReader.get_expression_info(some_expression)

# Get material property connections only
props_json = unreal.MaterialGraphReader.get_material_property_connections(mat)
```

## Blueprint JSON Schema (v1)

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

### Blueprint Graph types

| graph_type | Source |
|-----------|--------|
| `ubergraph` | UbergraphPages (EventGraph) |
| `function` | FunctionGraphs (user functions) |
| `construction_script` | FunctionGraphs named "ConstructionScript" |
| `delegate_signature` | DelegateSignatureGraphs |
| `macro` | MacroGraphs |

### Blueprint Node structure

Each node contains: `id` (n0, n1...), `class` (normalized K2Node name), `title` (truncated at 256 chars), `comment`, `position` [x, y], `pins[]`.

### Blueprint Pin structure

Each pin contains: `id` (p0, p1...), `name`, `direction` (input/output), `pin_type`, `sub_type` (object/struct only), `default_value`, `is_exec` (bool).

### Blueprint Edge structure

`from_pin` → `to_pin` with `edge_type`: `"exec"` (control flow) or `"data"` (data flow).

## Material JSON Schema (material-v1)

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"material-v1"` |
| `asset_path` | string | Material asset path |
| `material_type` | string | `Material` / `MaterialFunction` / `MaterialInstanceConstant` |
| `shading_model` | string | EMaterialShadingModel enum name |
| `blend_mode` | string | EBlendMode enum name |
| `two_sided` | bool | Two-sided rendering flag |
| `properties{}` | object | Material output connections (BaseColor, Metallic, Normal etc.) |
| `expressions[]` | array | All expression nodes with inputs/outputs/connections |
| `material_functions[]` | array | Referenced material functions |
| `comments[]` | array | Comment nodes with text, position, size, color |

### Material Expression structure

Each expression: `id` (e0, e1...), `class` (normalized name), `title`, `position` [x, y], `inputs[]` (with inline `connected_to`), `outputs[]` (name list), `properties{}` (type-specific).

### Material edge model

Connections stored inline: `input.connected_to = "e5"` — the upstream expression ID. No separate edges array (simpler than Blueprint's dual-direction pin model).

## Design Principles

- **Read-only**: Never modifies blueprint or material data
- **Editor-only**: Compiles only in Editor builds (bUsesEditorAPIs = true)
- **Pin-level modeling** (Blueprint): Preserves exec/data edge distinction via `is_exec` + `edge_type`
- **Expression-level modeling** (Material): Reads `UMaterialExpression` directly, not `UMaterialGraph` (transient editor layer)
- **Deterministic output**: Normalized class names as stable semantic signals
- **Safe ID scheme**: Sequential IDs (n0/p0 for Blueprint, e0 for Material), single-call scope
- **Title truncation**: Titles > 256 chars are truncated with "..."
- **Plugin lazy detection**: Python scripts detect C++ plugin availability at call time, not import time

## Dependencies

- UE 5.4+ (tested on 5.4/5.5)
- C++ Modules: Core, Engine, BlueprintGraph, UnrealEd, Json, JsonUtilities, Kismet, CoreUObject, EditorScriptingUtilities
- Python: `unreal` (Editor only), `json`, `sys` (stdlib only)
