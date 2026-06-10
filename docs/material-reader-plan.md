# Material Graph Reader — 开发计划

## 1. 目标

在现有 `BlueprintGraphReader` 插件框架上，新增 `MaterialGraphReader` 模块，实现：
- 读取 `UMaterial` / `UMaterialFunction` / `UMaterialInstance` 的节点图结构
- 输出与蓝图 schema 对齐的 JSON，供 AI Agent 消费
- 保持只读、Editor-only 的设计原则

---

## 2. 架构概述

### 2.1 数据模型差异（核心）

| 维度 | Blueprint (已有) | Material (新增) |
|---|---|---|
| 主数据源 | `UEdGraph` → `UK2Node` | `UMaterial::ExpressionCollection` → `UMaterialExpression` |
| 连接存储 | `UEdGraphPin::LinkedTo` | `FExpressionInput::Expression + OutputIndex` |
| 图的位置 | `UEdGraph` 是持久化主存储 | `UMaterialGraph` 是编辑器瞬时重建层，不可依赖 |
| 控制流 | exec/data 双引脚，核心机制 | 无 exec 引脚（Custom 输出除外） |
| 边方向 | output→input（双向可追） | FExpressionInput 存上游引用（天然方向：input←output） |

### 2.2 推荐路径

**以 `UMaterialExpression` + `FExpressionInputIterator/FExpressionOutputIterator` 为主**，不依赖 `UMaterialGraph`。

```cpp
// 核心遍历模式
for (UMaterialExpression* Expr : Material->GetExpressions())
{
    // 输入
    for (FExpressionInputIterator It{Expr}; It; ++It)
    {
        if (It->IsConnected())
        {
            // upstream: It->Expression, it->OutputIndex
        }
    }
    // 输出
    for (FExpressionOutputIterator It{Expr}; It; ++It) { ... }
}
```

### 2.3 新增文件结构

```
Source/BlueprintGraphReader/
├── Public/
│   ├── BlueprintGraphReader.h          # 保留
│   └── MaterialGraphReader.h           # 新增：C++ API
├── Private/
│   ├── BlueprintGraphReader.cpp         # 保留
│   └── MaterialGraphReader.cpp          # 新增：实现
Build.cs                                 # 无需新增依赖（UMaterialExpression 在 Engine 模块）
```

Python 层新建：

```
Python/
├── extract_material.py    # 新增：Material 提取脚本（对标 extract_blueprint.py）
└── extract_material_function.py  # 可选
```

---

## 3. JSON Schema (material-v1)

```json
{
  "schema_version": "material-v1",
  "asset_path": "/Game/Materials/M_Master.M_Master",
  "material_type": "Material | MaterialFunction | MaterialInstanceConstant",
  "shading_model": "DefaultLit | Unlit | TwoSided | ...",
  "blend_mode": "Opaque | Masked | Translucent | Additive | Modulate",
  "properties": {
    "BaseColor":    {"connected_to": "e5", "output_index": 0, "default": null},
    "Metallic":     {"connected_to": null, "default": 0.0},
    "Roughness":    {"connected_to": "e3", "output_index": 0, "default": null},
    "Normal":       {"connected_to": "e7", "output_index": 0, "default": null},
    "EmissiveColor": {"connected_to": null, "default": null},
    "Opacity":      {"connected_to": null, "default": 1.0},
    "OpacityMask":  {"connected_to": null, "default": null},
    "WorldPositionOffset": {"connected_to": null, "default": null},
    "WorldDisplacement":   {"connected_to": null, "default": null}
  },
  "expressions": [
    {
      "id": "e0",
      "class": "MaterialExpressionMultiply",
      "title": "Multiply",
      "position": [100, 200],
      "inputs": [
        {
          "name": "A",
          "type": "scalar",
          "connected_to": "e1",
          "output_index": 0,
          "default_value": "1.0"
        },
        {
          "name": "B",
          "type": "scalar",
          "connected_to": null,
          "output_index": null,
          "default_value": "0.5"
        }
      ],
      "outputs": ["Result"]
    },
    {
      "id": "e1",
      "class": "MaterialExpressionTextureSample",
      "title": "TextureSample (T_Albedo)",
      "position": [-200, 100],
      "inputs": [
        {"name": "UVs", "type": "float2", "connected_to": null, ...}
      ],
      "outputs": ["RGB", "R", "G", "B", "A"],
      "properties": {
        "texture": "T_Albedo",
        "sampler_type": "Color"
      }
    },
    {
      "id": "e5",
      "class": "MaterialExpressionScalarParameter",
      "title": "RoughnessValue",
      "position": [-400, 300],
      "inputs": [],
      "outputs": ["Value"],
      "properties": {
        "parameter_name": "RoughnessValue",
        "default_value": 0.5,
        "min": 0.0,
        "max": 1.0,
        "group": "Surface"
      }
    }
  ],
  "material_functions": [
    {
      "name": "MF_TilingNoise",
      "asset_path": "/Game/Materials/Functions/MF_TilingNoise",
      "called_from": ["e12"],
      "expression_count": 8
    }
  ],
  "comments": [
    {
      "text": "Main texture blending",
      "position": [-250, 80],
      "size": [400, 300]
    }
  ]
}
```

### 关键设计决定

1. **ID 前缀**：`e0, e1, ...` (expression) — 与蓝图 `n0` 区分
2. **input.connected_to**：指向上游 expression 的 id (output→input 方向，与蓝图 from_pin→to_pin 对齐语义)
3. **outputs 列表**：按 `FExpressionOutput::OutputName` 存储名称，无 ID（输出是"被动"连接端）
4. **material_type**：区分 Material / MaterialFunction / MaterialInstanceConstant
5. **properties 顶层**：直接映射 EMaterialProperty 枚举的 9 个材质输出通道
6. **class 字段**：去掉 `UMaterialExpression` 前缀，如 `MaterialExpressionMultiply`

---

## 4. C++ API 设计

```cpp
// MaterialGraphReader.h
UCLASS(meta=(ScriptName="MaterialGraphReader"))
class BLUEPRINTGRAPHREADER_API UMaterialGraphReader : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    // 主入口：提取 UMaterial 为 JSON
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString ExtractMaterialAsJson(UMaterialInterface* MaterialInterface);

    // 提取 MaterialFunction 为 JSON（内嵌表达式图）
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString ExtractMaterialFunctionAsJson(UMaterialFunction* Func);

    // 列出资产路径下所有 Material，返回 asset_path 列表
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static TArray<FString> ListMaterialAssets(const FString& ContentPath);

    // 获取单个 expression 的语义信息，返回 JSON 字符串
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString GetExpressionInfo(UMaterialExpression* Expr);

private:
    // 内部：序列化 ExpressionCollection 为 JSON
    static TSharedPtr<FJsonObject> SerializeExpressions(
        const TArray<UMaterialExpression*>& Expressions,
        int32& ExprIdCounter);

    // 内部：序列化单个 UMaterialExpression
    static TSharedPtr<FJsonObject> SerializeExpression(
        UMaterialExpression* Expr,
        const FString& ExprId,
        const TMap<UMaterialExpression*, FString>& ExprIdMap);

    // 内部：序列化材质属性连接（BaseColor, Normal 等）
    static TSharedPtr<FJsonObject> SerializeMaterialProperties(
        UMaterial* Material,
        const TMap<UMaterialExpression*, FString>& ExprIdMap);

    // 内部：从 FExpressionInput 提取连接信息
    static TSharedPtr<FJsonObject> SerializeInput(
        const FExpressionInput& Input,
        const TMap<UMaterialExpression*, FString>& ExprIdMap);

    // 工具：获取 expression 友好类名
    static FString GetExpressionClassName(UMaterialExpression* Expr);

    // 工具：获取 expression 显示标题
    static FString GetExpressionTitle(UMaterialExpression* Expr);
};
```

---

## 5. Python 层设计

`extract_material.py` — 对标 `extract_blueprint.py`：

```python
def extract(asset_path: str, output_path: Optional[str] = None) -> dict:
    """提取单个 Material/MaterialInstance/MaterialFunction 为 JSON"""

def extract_all(content_path: str, output_dir: str, recursive: bool = True) -> list:
    """批量提取目录下所有材质"""
```

---

## 6. Material Expression 高频类型专项处理

以下表达式有丰富元数据，需要专项序列化 `properties` 字段：

| 表达式类 | 额外序列化字段 |
|---|---|
| `MaterialExpressionScalarParameter` | `parameter_name, default_value, min, max, group` |
| `MaterialExpressionVectorParameter` | `parameter_name, default_value [R,G,B,A]` |
| `MaterialExpressionTextureSample` / `Parameter2D` | `texture (path), sampler_type, address_mode` |
| `MaterialExpressionMaterialFunctionCall` | `function_path, function_name` |
| `MaterialExpressionCustom` | `code (HLSL), output_type, inputs` |
| `MaterialExpressionConstant` | `value` |
| `MaterialExpressionStaticBool`/`StaticSwitch` | `default_value (bool)` |
| `MaterialExpressionReroute` | (无额外，但需保留位置) |
| `MaterialExpressionComment` | `text, size` → 移入 `comments[]` |
| `MaterialExpressionVertexInterpolator` | `interpolated_value` |

**通用 fallback**：对于未识别的 Expression 子类，输出 class + position + inputs/outputs，不报错。

---

## 7. 边界情况与注意事项

| 场景 | 处理方式 |
|---|---|
| `UMaterialInstance` 无自己的表达式 | 追溯到 `GetMaterial()` 读取父材质表达式，`material_type` 为 `MaterialInstanceConstant` |
| Expression 未连接 (悬空节点) | 仍然序列化，`inputs.connected_to = null` |
| 循环连接 | 使用 `TSet<UMaterialExpression*>` 防无限递归（`ContainsInputLoop` 可用） |
| 超长 HLSL (Custom 节点) | 截断到 2048 字符 + `...[truncated]` |
| 材质函数内嵌表达式 | 单独 `material_functions[]` 字段，不内联展开 |
| Material Layer / Blend | 标记 `material_type: "MaterialLayer"`（如有） |
| 未知子类 | fallback 类名，不 crash |

---

## 8. 开发阶段

### Phase 1：基础框架 (本 PR)
- [x] 创建分支 `feature/material-graph-reader`
- [ ] 添加 `MaterialGraphReader.h` 头文件
- [ ] 添加 `MaterialGraphReader.cpp` 核心实现
  - Expression 遍历 + ID 分配
  - Input 连接序列化
  - Material Properties 序列化
- [ ] 添加 `Python/extract_material.py`
- [ ] 基础测试（`Tests/test_material_pseudocode.py` 或 JSON 验证）
- [ ] 更新 `README.md` 添加 Material 部分
- [ ] 更新 `CLAUDE.md` 描述

### Phase 2：专项表达式 (后续)
- 高频表达式类型的 `properties` 字段补全
- Material Instance 参数覆盖读取
- Material Function 展开（递归）

### Phase 3：增强 (可选)
- 材质图转伪代码 (`graph_to_pseudocode.py` material 版)
- 材质图转 Mermaid (`graph_to_mermaid.py` material 版)

---

## 9. 不依赖 `UMaterialGraph` 的理由

1. `UMaterialGraph` 是 `UnrealEd` 模块类，`bUsesEditorAPIs = true` 已满足
2. 但它是**编辑器重建层**，每次打开材质编辑器都重建
3. 依赖它需要调用 `RebuildGraph()` → 有副作用（可能触发 recompile）
4. 直接读 `UMaterial::ExpressionCollection` 更轻量、无副作用、与序列化格式一致

---

## 10. 与蓝图 Reader 的对称设计

| 概念 | BlueprintReader | MaterialGraphReader |
|---|---|---|
| 主入口 | `ExtractBlueprintAsJson` | `ExtractMaterialAsJson` |
| 数据源 | `UBlueprint::UbergraphPages` | `UMaterial::ExpressionCollection` |
| 节点基类 | `UEdGraphNode` | `UMaterialExpression` |
| 连接模型 | `UEdGraphPin::LinkedTo` | `FExpressionInput::Expression` |
| ID 体系 | `n0, p0, ...` | `e0, e1, ...`（无 pin ID） |
| 边模型 | `from_pin → to_pin` | `input.connected_to = eid` (内联) |
| Python 脚本 | `extract_blueprint.py` | `extract_material.py` |
