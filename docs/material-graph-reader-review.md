# Material Graph Reader — Code Review

**Scope**: current workspace code
**Current target**: UE `5.4.0`
**Date**: 2026-06-11
**Reviewer**: automated

## Summary

| Category | Count |
|----------|-------|
| 🔴 Critical (compile failure UE 5.4+) | 3 |
| 🟠 Design / correctness issues | 3 |
| 🟡 Medium (missing material coverage, drift) | 4 |
| ⚪ Minor / nits | 4 |

**Verdict**: Implementation is structurally sound and follows the blueprint reader's patterns faithfully. The project targets UE 5.4, so the 3 UE 5.4 API issues are blocking for this repository. There is also a correctness bug in class name generation that should be fixed before relying on the material JSON output.

---

## 🔴 Critical

### 1. `ConcreteMaterial->ShadingModel` type mismatch (UE 5.4+)

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:70-71`

```cpp
StaticEnum<EMaterialShadingModel>()->GetNameStringByValue(
    static_cast<int64>(ConcreteMaterial->ShadingModel))
```

In UE 5.4+, `UMaterial::ShadingModel` changed from `TEnumAsByte<EMaterialShadingModel>` to `FMaterialShadingModelField` (a bitmask, to support multiple shading models). `FMaterialShadingModelField` does **not** implicitly convert to any integer type — this will fail to compile.

**Fix**: Use `GetShadingModels().GetFirstShadingModel()`:

```cpp
StaticEnum<EMaterialShadingModel>()->GetNameStringByValue(
    static_cast<int64>(ConcreteMaterial->GetShadingModels().GetFirstShadingModel()))
```

For multi-shading-model materials, consider serializing all models as an array.

---

### 2. `Material->DiffuseColor` may not exist (UE 5.4+)

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:452`

```cpp
SerializePropertyInput(Material->DiffuseColor, TEXT("DiffuseColor"), PropsObj);
```

`UMaterial::DiffuseColor` was deprecated and **removed** in UE 5.4. In PBR workflow, `BaseColor` replaces it. This will be a compilation error on UE 5.4+.

**Fix**: Remove this line for the current UE 5.4 target. If pre-5.4 support is added later, guard the legacy access with an explicit version check:

```cpp
// DiffuseColor removed in UE 5.4; BaseColor is the PBR equivalent
```

---

### 3. `SamplerSourceMode` enum name

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:563-565, 593-595`

```cpp
case SamplerSourceMode::SSM_FromTextureAsset: ...
case SamplerSourceMode::SSM_Wrap: ...
case SamplerSourceMode::SSM_Clamp: ...
```

The enum is `ESamplerSourceMode` in UE5, and the values may be `SSM_Wrap_WorldGroupSettings` / `SSM_Clamp_WorldGroupSettings` (not the short form). This is a compilation error on some UE 5.x versions.

**Fix**: Prefer `StaticEnum<ESamplerSourceMode>()` for serialization to avoid hardcoding enum member names across UE 5.x versions. If a manual switch is kept, use the exact `ESamplerSourceMode` enumerators for the target engine version.

---

## 🟠 Design / Correctness

### 4. `GetExpressionClassName` double-prefix bug for base class

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:687-715`

```cpp
// Strip "UMaterialExpression" → e.g. "UMaterialExpressionAdd" → "Add"
static const FString Prefix = TEXT("UMaterialExpression");
if (ClassName.StartsWith(Prefix)) {
    ClassName.RightChopInline(Prefix.Len());
    if (ClassName.IsEmpty()) { ClassName = TEXT("MaterialExpression"); }
}
// Then at line 715:
return FString::Printf(TEXT("MaterialExpression%s"), *ClassName);
```

Scenario: expression class is literally `UMaterialExpression` (the base class):
1. Strip `UMaterialExpression` → `""` → fallback to `"MaterialExpression"`
2. `Printf("MaterialExpression%s", "MaterialExpression")` → **`"MaterialExpressionMaterialExpression"`**

This is a bug. The fix: don't re-add the prefix since the class names already contain it in UE naming convention. Change the return to just `ClassName`, and rename the function or add a comment that class names like `MaterialExpressionAdd` are the desired output.

---

### 5. O(n²) material function caller discovery

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:151-179`

For each unique material function referenced, the code re-scans all expressions to find callers:

```cpp
for (UMaterialExpression* Expr : SerializableExpressions)  // outer: find func calls
{
    // ...
    for (UMaterialExpression* OtherExpr : SerializableExpressions)  // inner: find callers
```

This is O(n·m) where n = expression count, m = unique functions. For materials with many expressions (1000+) and dozens of function calls, this adds up.

**Fix**: Build the `called_from` map in a single pass:

```cpp
TMap<UMaterialFunction*, TArray<FString>> FuncCallers;
// ... during the first pass over expressions, populate FuncCallers[Func] += ExprId
```

---

### 6. Comment code duplication

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:115-143` and `238-258`

Comment serialization is ~30 lines duplicated verbatim between `ExtractMaterialAsJson` and `ExtractMaterialFunctionAsJson`. The duplicate also reveals a bug: the function version (line 257) is **missing the `color` field** that exists in the material version (line 134-140).

**Fix**: Extract a shared helper:

```cpp
static TArray<TSharedPtr<FJsonValue>> SerializeComments(
    const TArray<UMaterialExpressionComment*>& Comments);
```

---

## 🟡 Medium

### 7. No MaterialGraphReader test coverage

No tests for `MaterialGraphReader.cpp`, no material JSON fixtures, and no material-specific serialization tests. The existing `Tests/` directory covers blueprint pseudocode conversion and semantic enhancer behavior, but not material graph extraction.

**Expected** (minimum):
- JSON schema validation on a minimal material fixture
- `GetExpressionClassName` edge cases
- `SerializeExpressionProperties` coverage for each specialized type
- `ExtractMaterialFunctionAsJson` smoke test

---

### 8. No pseudocode converter for materials

The plan (`docs/material-reader-plan.md`, Phase 3) lists pseudocode generation as optional follow-up. The current project has no `material_to_pseudocode.py`. This means the end-to-end "JSON → Agent readable" pipeline is incomplete for materials — users get JSON but no material pseudocode.

**Decision**: Fine for this PR scope per the plan, but the README should call out that pseudocode generation is blueprint-only for now.

---

### 9. Material Instance parameter overrides not captured

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:57-58`

```cpp
UMaterial* ConcreteMaterial = MaterialInterface->GetMaterial();
```

For `MaterialInstanceConstant`, this resolves to the parent material's graph, but **the instance's own parameter overrides** (scalar/vector/texture parameter values) are silently discarded. The JSON output shows the parent material's default parameter values, not the instance's actual values.

**Fix**: After resolving to parent, extract `MaterialInstanceConstant->ScalarParameterValues`, `VectorParameterValues`, `TextureParameterValues` and include them as a separate `parameter_overrides: { ... }` field.

---

### 10. `CLAUDE.md` regression: `get_node_sem_info` doesn't exist

**File**: `CLAUDE.md` (diff vs main)

```diff
-semantic = unreal.BlueprintGraphReader.get_node_semantic_info(node)
+semantic = unreal.BlueprintGraphReader.get_node_sem_info(node)
```

The C++ function is `GetNodeSemanticInfo` → Python binding is `get_node_semantic_info`. The renamed version `get_node_sem_info` is a typo and will fail at runtime.

---

## ⚪ Minor

### 11. `SamplerSourceMode` comment is misleading

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:560, 590`

```cpp
// Sampler type — SamplerSourceMode is not a UENUM, map manually
```

`ESamplerSourceMode` IS a `UENUM()` in UE5. The manual switch is still correct (and arguably better than fragile enum string mapping), but the comment is wrong.

---

### 12. Property input default values not serialized

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:430-448`

The `SerializePropertyInput` lambda omits defaults because `FExpressionInput` doesn't carry default values — the material expression that fills the property connection has the default. This is correct behavior, but the schema JSON example in `material-reader-plan.md:80` shows `"default": 0.0` for unconnected Metallic, creating a mismatch. Align the schema spec with implementation.

---

### 13. No truncation on comment text

**File**: `Source/BlueprintGraphReader/Private/MaterialGraphReader.cpp:122`

```cpp
CommentObj->SetStringField("text", Comment->Text);
```

`Comment->Text` can be arbitrarily long. Unlike `GetExpressionTitle` which truncates at 256 chars, comment text has no limit — a user could paste a novel into a comment box and produce multi-MB JSON.

---

### 14. Missing `TextureSampleParameterCube` and `TextureSampleParameterVolume` property extraction

Only `TextureSampleParameter2D` is handled for specialized properties (line 546). `TextureSampleParameterCube` and `TextureSampleParameterVolume` fall through to the generic `TextureSample` handler, which doesn't include `parameter_name`. Consider adding handlers or making the `TextureSampleParameter2D` cast broader (e.g., cast to `UMaterialExpressionTextureSample` first then check if it's a parameter type via `GetParameterName()`).

---

## No-Issue Checks (verified correct)

| Concern | Verdict |
|---------|---------|
| Module dependency — `Materials/*` includes in Engine | ✅ Engine already in PublicDependencyModuleNames |
| `FExpressionInputIterator` pattern `for (It); It; ++It)` | ✅ Correct UE pattern |
| `FExpressionOutputIterator` → `OutputName.ToString()` | ✅ Correct |
| ID uniqueness (e0, e1…) within single call | ✅ `ExprIdMap` built sequentially, no collisions |
| Null expression skip in `ExpressionCollection.Expressions` | ✅ Checked at lines 88, 218 |
| Const-correctness on `ExprIdMap` | ✅ Passed as `const TMap<...>&` to inner serializers |
| `MaterialExpressionComment` correctly excluded from expression array | ✅ Separated before `ExprIdMap` building |
| `UMaterialInterface::GetMaterial()` resolves to `UMaterial*` | ✅ Correct for both Material and MaterialInstance |
| Comment position uses `MaterialExpressionEditorX/Y` | ✅ Correct UE coordinates |
| `Custom` node HLSL truncation at `MaxCodeLength` | ✅ Capped at 2048 |

---

## Recommended Fix Order

1. Fix `ShadingModel` → `GetShadingModels().GetFirstShadingModel()` (blocks UE 5.4+ build)
2. Remove `DiffuseColor` line (blocks UE 5.4+ build)
3. Fix `SamplerSourceMode` / `ESamplerSourceMode` enum names (blocks build on some 5.x)
4. Fix `GetExpressionClassName` double-prefix bug for base class
5. Extract shared `SerializeComments` helper, fix color field inconsistency
6. Build `FuncCallers` map in one pass, eliminate O(n²)
7. Fix `CLAUDE.md` typo `get_node_sem_info` → `get_node_semantic_info`
8. Add Material Instance parameter overrides extraction
9. Add tests
