# Blueprint Graph Reader

UE5 Editor plugin that extracts Blueprint graph structure (nodes, pins, edges) as JSON for AI Agent consumption.

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
│   ├── graph_to_pseudocode.py     # JSON → indented pseudocode
│   ├── graph_to_mermaid.py        # JSON → Mermaid flowchart
│   └── graph_to_graphify.py       # JSON → graphify knowledge graph
├── Tests/
│   └── test_pseudocode.py         # Unit tests for pseudocode generator
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
# (Using the Python script)
import extract_blueprint
extract_blueprint.extract("/Game/MyActor", output_path="~/my_actor.json")

# Or call C++ API directly via Python
bp = unreal.load_asset("/Game/MyActor.MyActor")
json_str = unreal.BlueprintGraphReader.extract_blueprint_as_json(bp)
```

## Design Principles

- **Read-only**: Never modifies blueprint data
- **Editor-only**: Compiles only in Editor builds
- **Pin-level modeling**: Preserves exec/data edge distinction
- **Deterministic output**: node.class (K2Node subclass name) as stable semantic signal

## Dependencies

- UE 5.4+ (tested on 5.4/5.5)
- Modules: Core, Engine, BlueprintGraph, UnrealEd, Json, JsonUtilities, Kismet, CoreUObject, EditorScriptingUtilities
