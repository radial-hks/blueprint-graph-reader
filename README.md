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
2. **序列化**：输出为结构化 JSON（节点、Pin、连线、变量）
3. **转换**：JSON → 伪代码 / Mermaid / 知识图谱，适配不同 Agent 推理方式

## 核心设计原则

- **Pin 级建模**：蓝图的语义在 Pin 连线上（exec pin = 控制流，data pin = 数据流），不在节点本身
- **零丢失提取**：JSON 图结构保留完整信息，下游转换是可逆的降采样
- **不依赖 LLM 生成结构**：核心提取和伪代码转换纯算法完成，LLM 只用于可选的语义增强
- **只读接口**：C++ 插件只暴露读取操作，不做任何修改，不影响蓝图资产

## 快速开始

```bash
# 1. 编译 UE 插件（放入项目的 Plugins/ 目录）
# 2. 在 UE Python 控制台中运行
import unreal, json

bp = unreal.load_asset("/Game/Blueprints/BP_Enemy")
json_str = unreal.BlueprintGraphReader.extract_blueprint_as_json(bp)
graph_data = json.loads(json_str)
print(json.dumps(graph_data, indent=2))
```

## 项目结构

```
blueprint-graph-reader/
├── README.md
├── CLAUDE.md
├── docs/
│   ├── proposal.md              # 方案详解
│   └── development-plan.md      # 开发计划
├── Source/
│   └── BlueprintGraphReader/    # UE C++ 插件源码
│       ├── BlueprintGraphReader.Build.cs
│       ├── Public/
│       │   ├── BlueprintGraphReader.h
│       │   └── BlueprintGraphReaderModule.h
│       └── Private/
│           ├── BlueprintGraphReader.cpp
│           └── BlueprintGraphReaderModule.cpp
├── Python/
│   ├── __init__.py
│   ├── extract_blueprint.py     # 主提取脚本
│   ├── graph_to_pseudocode.py   # JSON → 伪代码
│   ├── graph_to_mermaid.py      # JSON → Mermaid
│   └── graph_to_graphify.py     # JSON → graphify 知识图谱
└── Tests/
    └── test_pseudocode.py       # 伪代码生成器单元测试
```

## License

MIT
