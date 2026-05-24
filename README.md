# Blueprint Graph Reader

将 Unreal Engine 蓝图的节点图结构提取为 Agent 可读的 JSON 图结构，弥合"2D 可视节点图"与"1D 线性文本推理"之间的表示鸿沟。

## 为什么需要这个项目？

```
蓝图的表示:   [节点] ──连线──→ [节点] ──连线──→ [节点]    (2D 空间图)
Agent 的表示: 线性文本 → Token → 注意力 → 推理           (1D 序列)
```

AI 编码助手（Cursor、Claude Code、Codex 等）无法直接"看到"蓝图。当开发者问"BP_Enemy 的 BeginPlay 做了什么"时，Agent 只能猜测——因为没有可读的蓝图逻辑表示。

Blueprint Graph Reader 解决这个问题：

1. **提取**：通过 UE Python API + C++ 插件，零丢失地提取蓝图节点图结构
2. **序列化**：输出为结构化 JSON（节点、Pin、连线、变量、组件、Timeline、接口）
3. **转换**：JSON → 伪代码 / Mermaid / 知识图谱，适配不同 Agent 推理方式

## 核心设计原则

- **Pin 级建模**：蓝图的语义在 Pin 连线上（exec pin = 控制流，data pin = 数据流），不在节点本身
- **零丢失提取**：JSON 图结构保留完整信息，下游转换是可逆的降采样
- **不依赖 LLM 生成结构**：核心提取和伪代码转换纯算法完成，LLM 只用于可选的语义增强
- **只读接口**：C++ 插件只暴露读取操作，不做任何修改，不影响蓝图资产

## 快速开始

### 1. 编译 UE 插件

将整个 `blueprint-graph-reader/` 目录复制或软链接到 UE 项目的 `Plugins/` 目录，重新生成项目文件并编译 Editor 配置。

### 2. 提取蓝图 JSON

```python
# UE Python 控制台
import unreal, json

# 方式 A：C++ API 一步提取（推荐）
bp = unreal.load_asset("/Game/Blueprints/BP_Enemy")
json_str = unreal.BlueprintGraphReader.extract_blueprint_as_json(bp)
graph_data = json.loads(json_str)

# 方式 B：Python 脚本提取（支持批量 + 文件输出）
import extract_blueprint
extract_blueprint.extract("/Game/Blueprints/BP_Enemy", output_path="~/bp_enemy.json")
extract_blueprint.extract_all("/Game/Blueprints/", output_dir="~/blueprint_graphs/")
```

### 3. 转换为 Agent 可读格式

```python
# 伪代码（供 Agent 线性推理）
from graph_to_pseudocode import graph_to_pseudocode
pseudocode = graph_to_pseudocode(graph_data)
print(pseudocode)

# Mermaid 流程图（供人可视化）
from graph_to_mermaid import graph_to_mermaid
mermaid = graph_to_mermaid(graph_data)
print(mermaid)

# graphify 知识图谱（供 Agent 查询）
from graph_to_graphify import graph_to_graphify
graphify_data = graph_to_graphify(graph_data)
```

### 4. 语义增强（LLM 可选）

```python
from semantic_enhancer import summarize_blueprint, ask_blueprint, enhance_pseudocode

# 子图摘要 — 每个图/函数生成一行自然语言描述
summaries = summarize_blueprint(graph_data)
# {"EventGraph": "游戏开始时检查玩家引用并初始化HUD", "TakeDamage": "扣减生命值，死亡时调用Die()"}

# 蓝图问答 — 基于伪代码+摘要回答自然语言问题
answer = ask_blueprint(graph_data, "BP_Enemy 死亡时做了什么?")

# 增强伪代码 — 将摘要注回伪代码
enhanced = enhance_pseudocode(graph_data, summaries=summaries)
print(enhanced)
# graph EventGraph (ubergraph)
#   # [摘要] 游戏开始时检查玩家引用并初始化HUD
#   Event BeginPlay:
#     ...

# 按需子图提取 — 只提取指定图，降低 Token 消耗
from semantic_enhancer import extract_subgraph_context
context = extract_subgraph_context(graph_data, target_names=["graph EventGraph"])
```

LLM API 配置通过环境变量：
- `OPENAI_BASE_URL` — API 端点（默认 OpenAI，支持 Ollama/vLLM/千帆等）
- `OPENAI_API_KEY` — API 密钥
- `SEMANTIC_ENHANCER_MODEL` — 模型名（默认 `gpt-4o-mini`）

### 5. 命令行使用（离线验证）

```bash
# 伪代码
python3 -m graph_to_pseudocode blueprint.json

# Mermaid
python3 -m graph_to_mermaid blueprint.json

# graphify
python3 -m graph_to_graphify blueprint.json

# 语义增强
python3 -m semantic_enhancer blueprint.json --summarize
python3 -m semantic_enhancer blueprint.json --enhance -o enhanced.txt
python3 -m semantic_enhancer blueprint.json --ask "BeginPlay 做了什么?"
python3 -m semantic_enhancer blueprint.json --subgraph EventGraph

# JSON 统计
python3 extract_blueprint.py blueprint.json --stats
```

## JSON Schema (v1)

完整蓝图 JSON 结构如下（所有字段均为 C++ 插件实际输出）：

```json
{
  "schema_version": "v1",
  "asset_path": "/Game/Blueprints/BP_Enemy",
  "blueprint_type": "BPType_Normal",
  "parent_class": "Actor",
  "variables": [
    {
      "name": "Health",
      "type": "float",
      "default_value": "100.0",
      "instance_editable": true,
      "expose_on_spawn": false
    }
  ],
  "graphs": [
    {
      "name": "EventGraph",
      "graph_type": "ubergraph",
      "nodes": [
        {
          "id": "n0",
          "class": "K2Node_Event",
          "title": "Event BeginPlay",
          "comment": "游戏开始时初始化",
          "position": [100, 200],
          "pins": [
            {
              "id": "p0",
              "name": "",
              "direction": "output",
              "pin_type": "exec",
              "default_value": "",
              "is_exec": true
            },
            {
              "id": "p1",
              "name": "self",
              "direction": "output",
              "pin_type": "object",
              "sub_type": "Actor",
              "default_value": "",
              "is_exec": false
            }
          ]
        }
      ],
      "edges": [
        { "from_pin": "p0", "to_pin": "p5", "edge_type": "exec" },
        { "from_pin": "p1", "to_pin": "p8", "edge_type": "data" }
      ]
    }
  ],
  "macro_graphs": [
    {
      "name": "MyMacro",
      "graph_type": "macro",
      "nodes": [],
      "edges": []
    }
  ],
  "components": [
    { "class": "StaticMeshComponent", "name": "Mesh", "template_name": "Mesh", "child_index": 0 }
  ],
  "timelines": [
    { "name": "Timeline_0", "loop": false, "length": 5.0 }
  ],
  "interfaces": [
    { "name": "IInteractable", "graph_count": 1 }
  ]
}
```

### Schema 要点

| 字段 | 说明 |
|------|------|
| `parent_class` | 始终输出；无父类时为 `null` |
| `graph_type` | `ubergraph` / `function` / `construction_script` / `delegate_signature` / `macro` |
| `pins[].id` | 纯序号制（p0, p1, p2...），全局唯一（单次 `ExtractBlueprintAsJson` 调用内） |
| `pins[].is_exec` | 布尔标记，替代从 pin_type 判断 |
| `pins[].sub_type` | 仅 object/class/struct 类 Pin 输出，如 `Actor`、`FVector` |
| `edges[].edge_type` | `exec`（控制流）或 `data`（数据流） |
| `components` | SCS 组件树（仅 Actor 蓝图有） |
| `timelines` | Timeline 模板元数据 |
| `interfaces` | 蓝图实现的接口列表 |
| `macro_graphs` | 与 `graphs` 分开存放的宏图 |

### Pin 类型映射

C++ 插件通过 `UEdGraphSchema_K2` 常量映射 Pin 类别：

| UE PinCategory | JSON pin_type |
|----------------|---------------|
| PC_Exec | exec |
| PC_Boolean | bool |
| PC_Byte | byte |
| PC_Int | int |
| PC_Int64 | int64 |
| PC_Float | float |
| PC_Double | double |
| PC_String | string |
| PC_Text | text |
| PC_Name | name |
| PC_Struct | struct |
| PC_Object | object |
| PC_Class | class |
| PC_SoftObject | soft_object |
| PC_SoftClass | soft_class |
| PC_Delegate | delegate |
| PC_Interface | interface |
| PC_Wildcard | wildcard |
| vector / rotator / transform / enum / map / set | 原样输出 |

## 伪代码生成器 — 支持的节点类型

| K2Node 子类 | 伪代码输出 | 说明 |
|-------------|-----------|------|
| K2Node_Event | `Event BeginPlay:` | 事件入口 |
| K2Node_FunctionEntry | `function MyFunc(param: type):` | 函数入口 |
| K2Node_CustomEvent | `event MyEvent:` | 自定义事件 |
| K2Node_IfThenElse | `if Condition:` / `else:` | 条件分支 |
| K2Node_ForEachLoop | `for item in Array:` | 遍历循环 |
| K2Node_WhileLoop | `while Condition:` | While 循环 |
| K2Node_CallFunction | `FunctionName(arg=val)` | 函数调用 |
| K2Node_VariableGet | `VarName` | 变量读取 |
| K2Node_VariableSet | `VarName = Value` | 变量写入 |
| K2Node_ReturnNode | `return Value` | 返回 |
| K2Node_SpawnActorFromClass | `SpawnActor ...` | 生成 Actor |
| K2Node_Knot | *(透传)* | Reroute 节点，不输出 |
| K2Node_MacroInstance | `macro Title:` 或 `for item in ...` | 宏实例（自动识别 ForEachLoop） |
| K2Node_Timeline | `timeline Title:` / `on Update:` | Timeline |
| K2Node_BaseAsyncTask | `async Title:` / `on Completed:` | 异步任务 |
| K2Node_AsyncAction | `async Title:` / `on Completed:` | 异步 Action |
| K2Node_ExecutionSequence | `sequence:` / `step 0:` | Sequence |
| K2Node_Switch | `switch Value:` / `case X:` | Switch |
| K2Node_CallParentFunction | `super::Title` | 调用父类函数 |
| K2Node_DynamicCast | `cast Type(Object):` / `catch (cast failed):` | 动态类型转换 |
| K2Node_MakeStruct | `MakeStruct(...)` | 构造结构体 |
| K2Node_BreakStruct | `break StructName` | 解构结构体 |

未匹配的节点类型 fallback 为 `node.class: node.title`。

## 项目结构

```
blueprint-graph-reader/
├── BlueprintGraphReader.uplugin    # UE 插件清单
├── README.md
├── CLAUDE.md
├── docs/
│   ├── proposal.md                 # 方案详解
│   └── development-plan.md         # 开发计划
├── Source/
│   └── BlueprintGraphReader/       # UE C++ 插件源码
│       ├── BlueprintGraphReader.Build.cs
│       ├── Public/
│       │   ├── BlueprintGraphReader.h       # 主 API（UBlueprintFunctionLibrary）
│       │   └── BlueprintGraphReaderModule.h # 模块注册
│       └── Private/
│           ├── BlueprintGraphReader.cpp    # API 实现 + 序列化
│           └── BlueprintGraphReaderModule.cpp
├── Python/
│   ├── __init__.py
│   ├── extract_blueprint.py        # 一键提取（UE Python → JSON 文件）
│   ├── graph_to_pseudocode.py      # JSON → 缩进伪代码
│   ├── graph_to_mermaid.py         # JSON → Mermaid 流程图
│   ├── graph_to_graphify.py        # JSON → graphify 知识图谱
│   └── semantic_enhancer.py        # LLM 语义增强（摘要、问答、注解）
└── Tests/
    ├── test_pseudocode.py          # 伪代码生成器单元测试（8/8 通过）
    └── test_semantic_enhancer.py   # 语义增强器单元测试（21/21 通过）
```

## License

MIT
