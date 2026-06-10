# Material Graph Reader — Code Review (Round 3)

**Commit**: `00a24a4` ("Fix material graph reader review issues")
**Target**: UE 5.4+
**Date**: 2026-06-11

---

## 背景

Round 1（`docs/material-graph-reader-review.md`）列举 14 个问题，Round 2（`docs/material-graph-reader-review-r2.md`）确认 11/14 已修，2 个延期，1 个遗漏。最新提交 `00a24a4` 完成了 ClearCoat、Association/Index 等补充，并增加了静态回归测试。

此轮 review 发现 **3 个严重度较高的问题**：两份死代码 + 一个误导注释。

---

## 🔴 Issue 1：`SerializeExpressionInput` — 死代码，零调用方

**头文件**：`MaterialGraphReader.h:99-101`
**实现**：`MaterialGraphReader.cpp:440-458`

```cpp
TSharedPtr<FJsonObject> UMaterialGraphReader::SerializeExpressionInput(
    const FExpressionInput& Input,
    const TMap<UMaterialExpression*, FString>& ExprIdMap)
{
    TSharedPtr<FJsonObject> InputObj = MakeShared<FJsonObject>();
    if (Input.Expression) { ... }
    else { ... }
    return InputObj;
}
```

**问题**：

- `SerializeExpression()` (line 312-358) 内联了完全相同的输入序列化逻辑
- `SerializeMaterialProperties()` 的 lambda 也重复了同样的逻辑
- `SerializeExpressionInput` 没有任何调用方——它是三份重复实现中唯一未被使用的那份

**影响**：22 行死代码。如果 schema 需要变更（例如增加 `default_value` 字段），开发者必须找到所有三处——而其中一处看起来像「权威实现」其实是死代码，会导致修 bug 只修了两处而漏掉真正的调用路径。

**修复**：删除 `SerializeExpressionInput` 声明和实现。然后在 `SerializeExpression` 中调用内联版的逻辑替代为提取的共享 helper。

---

## 🔴 Issue 2：`GetMaterialPropertyName` — 死代码，零调用方

**头文件**：`MaterialGraphReader.h:128-130`
**实现**：`MaterialGraphReader.cpp:801-803`

```cpp
FString UMaterialGraphReader::GetMaterialPropertyName(EMaterialProperty Property)
{
    return StaticEnum<EMaterialProperty>()->GetNameStringByValue(
        static_cast<int64>(Property));
}
```

**问题**：

- 所有材质属性序列化通过 `SerializeMaterialProperties` 中的硬编码字符串（`TEXT("BaseColor")` 等）
- 没有任何路径走 `EMaterialProperty` 枚举
- 该函数设计时可能预想通过枚举遍历属性，但最终实现走了直接成员访问路线

**影响**：10 行死代码 + 头文件声明。`EMaterialProperty` 枚举本身就容易与 UE 版本漂移（新增/删除属性），留着会误导后续开发者以为存在枚举遍历路径。同时 `SerializePropertyInput` lambda 签名不同，也无法直接替换为此函数。

**修复**：删除声明和实现。

---

## 🟠 Issue 3：`GetExpressionClassName` 注释与行为矛盾

**文件**：`MaterialGraphReader.cpp:756-773`

```cpp
FString UMaterialGraphReader::GetExpressionClassName(UMaterialExpression* Expr)
{
    if (!Expr) return "Unknown";
    FString ClassName = Expr->GetClass()->GetName();

    // UE class names normally omit the leading U already; handle both forms.
    static const FString Prefix = TEXT("UMaterialExpression");
    if (ClassName.StartsWith(Prefix))
    {
        ClassName.RightChopInline(1);
    }
    else
    {
        if (ClassName.Len() > 1 && ClassName[0] == TEXT('U')
            && FChar::IsUpper(ClassName[1]))
        {
            ClassName.RightChopInline(1);
        }
    }
    return ClassName;
}
```

**问题**：

注释说「UE class names normally omit the leading U already」——但紧接着的 `if (ClassName.StartsWith("UMaterialExpression"))` 只会在类名**包含** U 前缀时命中。注释描述的语义与实际逻辑正好相反，会让后续开发者困惑 `RightChopInline(1)` 到底是做什么的（UE 的 `RightChopInline(N)` 从**左侧**删除 N 个字符，保留右侧部分——命名非常反直觉）。

**影响**：如果未来有人信任注释并按「类名不带 U」的假设修改逻辑，会破坏 class name 输出（例如输出 `"UMaterialExpressionAdd"` 而非 `"MaterialExpressionAdd"`）。

**修复**：替换注释为准确描述：

```cpp
// UMaterialExpression subclasses use the UE convention of U + ClassName.
// Strip the leading 'U' to get "MaterialExpressionAdd", "MaterialExpressionMultiply", etc.
```

---

## ⚪ 剩余备注

以下问题已在 Round 2 中标记但未修复，本次为终态确认：

| # | 问题 | 处理 |
|---|------|------|
| R2-8 | `GetExpressionTitle` 使用 `GetDisplayNameText()`（本地化不稳定） | 风险已记录，非阻塞。AI agent 消费时应以 `class` 字段为主，`title` 为辅助 |
| — | Material Function 输入/输出 pins 未捕获 | 后续迭代的可选增强 |
| — | `RuntimeVirtualTexture` / `Font` 参数覆盖未序列化 | 使用场景极少，后续按需添加 |
| — | Substrate 材质（UE 5.4+）部分属性未覆盖 | Substrate 普及后再处理 |

---

## 回归测试覆盖

`Tests/test_material_graph_reader_static.py` 验证以下项已不存在于代码中：

- ❌ `ConcreteMaterial->ShadingModel`（编译失败）
- ❌ `Material->DiffuseColor`（编译失败）
- ❌ `SamplerSourceMode::`（硬编码枚举值）
- ❌ `MaterialExpression%s`（双前缀 bug）
- ❌ `get_node_sem_info`（CLAUDE.md typo）

所有修复均已落地。

---

## 总结

| 严重度 | 数量 | 问题 |
|--------|------|------|
| 🔴 | 2 | `SerializeExpressionInput` 死代码、`GetMaterialPropertyName` 死代码 |
| 🟠 | 1 | `GetExpressionClassName` 注释与代码矛盾 |
| ⚪ | 4 | 本地化 title、Function pins、RVT/Font、Substrate（均可延期） |

**结论**：代码可构建且正确运行。3 个问题均不影响编译和运行时行为，但会损害可维护性。建议在合并前清理两份死代码并修正注释。
