# 方案详解：蓝图图结构提取为 Agent 可读格式

## 一、问题定义

### 1.1 核心矛盾

蓝本是 **2D 有向图**（节点 + Pin + 连线），而 AI Agent 的推理链是 **1D 线性序列**（Token 流）。将图结构压入序列必然面临信息丢失或扭曲。

但这个矛盾并非无解——编译器早就解决了类似问题：将 AST（树结构）线性化为字节码（序列），关键在于**保留足够的信息使推理可以还原语义**。

### 1.2 信息层级

蓝图包含的信息可以分为四个层级：

| 层级 | 信息类型 | 示例 | Agent 是否必须理解 |
|------|---------|------|-------------------|
| L1 结构 | 节点类型、Pin 连接 | K2Node_Branch → then/else | 是 |
| L2 语义 | 节点标题、变量名、函数名 | "IsValid?", "PlayerRef" | 是 |
| L3 类型 | Pin 数据类型、默认值 | float, Actor*, 100.0 | 部分必须 |
| L4 布局 | 节点坐标、注释框、颜色 | NodePosX=240, NodePosY=-160 | 否（视觉信息） |

**L1-L3 必须零丢失，L4 可降采样。** 这是 JSON Schema 设计的边界条件。

---

## 二、UE Python API 能力与缺口分析

### 2.1 已暴露的 API（可用）

| 类/函数 | 能力 | 来源 |
|--------|------|------|
| `BlueprintEditorLibrary.find_graph()` | 按名称查找蓝图图 | BlueprintEditorLibrary 模块 |
| `BlueprintEditorLibrary.find_event_graph()` | 查找 EventGraph | 同上 |
| `BlueprintEditorLibrary.remove_unused_nodes()` | 移除未使用节点 | 同上 |
| `BlueprintEditorLibrary.rename_graph()` | 重命名图 | 同上 |
| `EditorAssetLibrary.load_asset()` | 加载蓝图资产 | EditorScripting 模块 |
| `EdGraphPinType` (StructBase) | Pin 类型描述 | Engine 模块 |
| `Blueprint` 类 | 蓝图元数据（category、parent class 等） | Engine 模块 |

### 2.2 未暴露的 API（缺口，核心）

| C++ 接口 | 作用 | Python 可访问性 |
|----------|------|----------------|
| `UEdGraph::Nodes` | 获取图的所有节点 | ❌ 未暴露 |
| `UEdGraphNode::Pins` | 获取节点的所有 Pin | ❌ 未暴露 |
| `UEdGraphPin::LinkedTo` | 获取 Pin 的连接目标 | ❌ 未暴露 |
| `UEdGraphPin::Direction` | Pin 方向（输入/输出） | ❌ 未暴露 |
| `UEdGraphPin` 类本身 | Pin 的完整表示 | ❌ 未暴露到 Python |
| `UK2Node::GetNodeTitle()` | 节点标题 | ❌ 未暴露 |
| `UK2Node` 子类名 | 节点语义类型 | ❌ 未暴露 |
| `UEdGraphNode::NodeComment` | 节点注释 | ❌ 未暴露 |
| `UEdGraphNode::NodePosX/Y` | 节点位置 | ❌ 未暴露 |

### 2.3 结论

Python API 只暴露了 **"管理型"操作**（创建、查找、编译、属性修改），而 **"读取型"操作**（遍历节点、读取连线）几乎完全缺失。

**必须通过 C++ 插件补充读取接口。**

---

## 三、C++ 插件设计：BlueprintGraphReader

### 3.1 设计原则

- **只读**：不修改任何蓝图数据，不产生副作用
- **最小接口**：只暴露提取所需的 6 个核心函数
- **无外部依赖**：只依赖 Engine 和 BlueprintGraph 模块
- **Editor Only**：只在编辑器模式下编译和运行

### 3.2 接口定义

```cpp
// BlueprintGraphReader.h
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "BlueprintGraphReader.generated.h"

UCLASS()
class UBlueprintGraphReader : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    // 提取整个蓝图为 JSON 字符串（一步到位，推荐）
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static FString ExtractBlueprintAsJson(UBlueprint* Blueprint);

    // 获取蓝图的所有图名（EventGraph, 自定义函数图, 宏图等）
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetBlueprintGraphNames(UBlueprint* Blueprint);

    // 获取图中所有节点
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<UEdGraphNode*> GetGraphNodes(UEdGraph* Graph);

    // 获取节点的 Pin 列表信息（名称、方向、类型、连接）
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetNodePinInfo(UEdGraphNode* Node);

    // 获取节点语义信息（类名、标题、注释）
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static FString GetNodeSemanticInfo(UEdGraphNode* Node);

    // 获取蓝图变量列表
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetBlueprintVariables(UBlueprint* Blueprint);
};
```

### 3.3 ExtractBlueprintAsJson 实现策略

```cpp
FString UBlueprintGraphReader::ExtractBlueprintAsJson(UBlueprint* Blueprint)
{
    TSharedPtr<FJsonObject> RootJson = MakeShared<FJsonObject>();

    // 1. 蓝图元数据
    RootJson->SetStringField("asset_path", Blueprint->GetPathName());
    RootJson->SetStringField("blueprint_type",
        StaticEnum<EBPType>()->GetNameStringByValue(Blueprint->BlueprintType));
    if (Blueprint->ParentClass)
    {
        RootJson->SetStringField("parent_class", Blueprint->ParentClass->GetName());
    }

    // 2. 遍历所有图
    TArray<TSharedPtr<FJsonValue>> GraphsArray;
    for (UEdGraph* Graph : Blueprint->UbergraphPages)
    {
        GraphsArray.Add(MakeShared<FJsonValueObject>(SerializeGraph(Graph)));
    }
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        GraphsArray.Add(MakeShared<FJsonValueObject>(SerializeGraph(Graph)));
    }
    RootJson->SetArrayField("graphs", GraphsArray);

    // 3. 变量
    TArray<TSharedPtr<FJsonValue>> VarsArray;
    for (FBPVariableDescription& Var : Blueprint->NewVariables)
    {
        auto VarObj = MakeShared<FJsonObject>();
        VarObj->SetStringField("name", Var.VarName.ToString());
        VarObj->SetStringField("type", Var.VarType.ToString());
        // ... 默认值等
        VarsArray.Add(MakeShared<FJsonValueObject>(VarObj));
    }
    RootJson->SetArrayField("variables", VarsArray);

    // 序列化
    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(RootJson.ToSharedRef(), Writer);
    return Output;
}
```

---

## 四、JSON Schema 设计

### 4.1 完整 Schema

```json
{
  "$schema": "blueprint-graph-v1",
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
    },
    {
      "name": "PlayerRef",
      "type": "Actor",
      "default_value": "None",
      "instance_editable": false,
      "expose_on_spawn": true
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
              "id": "n0_exec_out",
              "name": "",
              "direction": "output",
              "pin_type": "exec",
              "sub_type": "",
              "default_value": ""
            },
            {
              "id": "n0_self_out",
              "name": "self",
              "direction": "output",
              "pin_type": "object",
              "sub_type": "Actor",
              "default_value": ""
            }
          ]
        },
        {
          "id": "n1",
          "class": "K2Node_IfThenElse",
          "title": "IsValid?",
          "comment": "",
          "position": [400, 200],
          "pins": [
            {
              "id": "n1_exec_in",
              "name": "",
              "direction": "input",
              "pin_type": "exec",
              "sub_type": "",
              "default_value": ""
            },
            {
              "id": "n1_condition_in",
              "name": "Condition",
              "direction": "input",
              "pin_type": "bool",
              "sub_type": "",
              "default_value": "false"
            },
            {
              "id": "n1_then_out",
              "name": "True",
              "direction": "output",
              "pin_type": "exec",
              "sub_type": "",
              "default_value": ""
            },
            {
              "id": "n1_else_out",
              "name": "False",
              "direction": "output",
              "pin_type": "exec",
              "sub_type": "",
              "default_value": ""
            }
          ]
        }
      ],
      "edges": [
        {
          "from_pin": "n0_exec_out",
          "to_pin": "n1_exec_in",
          "edge_type": "exec"
        },
        {
          "from_pin": "n0_self_out",
          "to_pin": "n3_target_in",
          "edge_type": "data"
        }
      ]
    }
  ]
}
```

### 4.2 设计决策

**1. Pin 级建模（而非 Node 级）**

蓝图的执行语义由 Pin 连接决定：
- **exec pin** (白色三角形) = 控制流
- **data pin** (彩色圆点) = 数据流

如果只建模 node→node 边，就丢失了"这个连接是控制流还是数据流"的关键信息。

**2. 保留 node.class（K2Node 子类名）**

这是 Agent 理解节点语义的最可靠信号：

| node.class | Agent 理解 |
|-----------|-----------|
| `K2Node_Event` | 事件入口（执行起点） |
| `K2Node_FunctionEntry` | 函数入口 |
| `K2Node_CallFunction` | 调用某个函数 |
| `K2Node_VariableGet` | 读取变量 |
| `K2Node_VariableSet` | 写入变量 |
| `K2Node_IfThenElse` | 条件分支 |
| `K2Node_ForEachLoop` | 遍历循环 |
| `K2Node_MacroInstance` | 宏实例 |
| `K2Node_Switch*` | Switch 分支 |
| `K2Node_CustomEvent` | 自定义事件 |
| `K2Node_CallParentFunction` | 调用父类函数 |
| `K2Node_SpawnActor` | 生成 Actor |
| `K2Node_DynamicCast` | 动态类型转换 |
| `K2Node_MakeStruct` | 构造结构体 |
| `K2Node_BreakStruct` | 解构结构体 |

`node.title` 是给人看的（可能是中文、可能重载），`node.class` 是给 Agent 看的（确定性语义）。

**3. edge_type 区分控制流和数据流**

```json
{"edge_type": "exec"}   // 控制流：决定执行顺序
{"edge_type": "data"}   // 数据流：决定数据传递
```

Agent 追踪控制流时只需沿 exec 边遍历，追踪数据依赖时沿 data 边回溯。

**4. 变量声明与引用分离**

变量在 `variables` 数组中声明，在 `K2Node_VariableGet/Set` 节点中通过 Pin 引用。Agent 需要同时看到两处。

---

## 五、下游转换：从 JSON 到 Agent 可读

### 5.1 JSON → 伪代码（核心，纯算法，不依赖 LLM）

```python
def graph_to_pseudocode(graph_data: dict) -> str:
    """
    沿 exec pin 做 DFS 遍历，将图结构线性化为缩进伪代码。
    Agent 可以像读代码一样推理蓝图逻辑。
    """
    lines = []
    for graph in graph_data["graphs"]:
        lines.append(f"graph {graph['name']}:")
        entry_nodes = find_entry_nodes(graph)
        for entry in entry_nodes:
            lines.append(f"  {entry['title']}:")
            trace_exec_flow(graph, entry, lines, indent=2)
    return "\n".join(lines)
```

输出示例：

```
graph EventGraph:
  Event BeginPlay:
    Branch(IsValid? → PlayerRef)
      True:
        Set Timer(duration=2.0, delegate=SpawnEnemy)
        InitializeHUD()
      False:
        PrintString("Player not found")
  Event SpawnEnemy:
    SpawnActor(EnemyClass, SpawnLocation)
    Health = 100.0
    PrintString("Enemy spawned!")
```

### 5.2 JSON → Mermaid（给人看的可视化）

```python
def graph_to_mermaid(graph_data: dict) -> str:
    """导出为 Mermaid flowchart，exec 边实线，data 边虚线"""
    lines = ["flowchart TD"]
    # ... 节点和边的转换
    return "\n".join(lines)
```

### 5.3 JSON → graphify 知识图谱（给 Agent 查询）

```python
def graph_to_graphify(graph_data: dict) -> dict:
    """转换为 graphify 的节点-边格式，接入知识图谱查询"""
    # 蓝图节点 → graph node
    # Pin 连接 → graph edge (带 edge_type 标签)
    # 变量 → graph node (带 type=variable 标签)
    pass
```

### 5.4 LLM 语义增强（可选）

对复杂子图（如状态机、行为树交互），用 LLM 生成自然语言注释：

```
Event BeginPlay:
  [AI 注释：游戏开始时检查玩家引用是否有效，
   如果有效则设置定时生成敌人，否则打印警告]
  Branch(IsValid? → PlayerRef)
    True:
      Set Timer(duration=2.0, delegate=SpawnEnemy)
    False:
      PrintString("Player not found")
```

---

## 六、替代方案对比

| 方案 | 信息完整度 | 部署门槛 | 维护成本 | Agent 推理效率 |
|------|-----------|---------|---------|---------------|
| **A. C++ 插件 + JSON** | ★★★★★ 零丢失 | ★★★ 需编译插件 | ★★★★ 接口稳定 | ★★★★ JSON→伪代码高效 |
| B. 解析 .uasset 二进制 | ★★★★ 跳过 L4 布局 | ★★ 需维护反序列化 | ★★ 格式随版本变 | ★★★ 同上 |
| C. Python 反射 hack | ★★ 不稳定 | ★★★★ 零部署 | ★ 随时可能失效 | ★★★★ 同上 |
| D. 截图 + 视觉模型 | ★ 严重丢失 | ★★★★ 零部署 | ★★★ 模型依赖 | ★ 极低 |
| E. 只导出 Copied Text | ★★ 丢失拓扑 | ★★★★ UE 内置 | ★★★★ 零维护 | ★★ 缺少连接信息 |

**推荐方案 A**：信息完整度最高，C++ 插件是一次投入、长期受益的基础设施。

---

## 七、与 unreal-python-stubhub 的关系

Blueprint Graph Reader 是 unreal-python-stubhub 的**互补项目**：

```
unreal-python-stubhub          Blueprint Graph Reader
     │                              │
     │  Python API 存根             │  蓝图图结构
     │  (15,435 个类/函数)          │  (节点/Pin/连线)
     │                              │
     └──────────┬───────────────────┘
                │
                ▼
          graphify 知识图谱
                │
                ▼
          Agent 可查询、可推理的 UE 知识网络
```

- stubhub 回答"有什么 API 可以用"
- Graph Reader 回答"蓝图逻辑是怎么组织的"
- 两者通过 graphify 统一查询，Agent 可以从 API 定义跳转到蓝图用法
