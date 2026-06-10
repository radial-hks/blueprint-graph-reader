# Material Graph Reader — Code Review (Round 2)

**Branch**: `feature/material-graph-reader`
**Commit**: current workspace after Round 1 fixes
**Date**: 2026-06-11
**Previous review**: `docs/material-graph-reader-review.md`
**Manual verification**: `docs/material-graph-reader-manual-verification-checklist.md`

---

## Round 1 Fix Verification

| # | Issue (Round 1) | Status |
|---|-----------------|--------|
| 1 | `ShadingModel` type mismatch UE 5.4+ | ✅ `GetShadingModels().GetFirstShadingModel()` |
| 2 | `DiffuseColor` removed in UE 5.4 | ✅ Removed from property serialization list |
| 3 | `SamplerSourceMode` enum name | ✅ `GetSamplerSourceName()` via `StaticEnum<ESamplerSourceMode>()` |
| 4 | `GetExpressionClassName` double-prefix bug | ✅ Rewritten: strips leading `U` only, returns direct class name |
| 5 | O(n²) function caller discovery | ✅ Single-pass `TMap<UMaterialFunction*, TArray<FString>> FuncCallers` |
| 6 | Comment code duplication + missing color | ✅ Extracted `SerializeComments` helper; color now consistently included |
| 7 | Zero test coverage | 🟡 Static regression checks added; UE fixture tests deferred |
| 8 | No pseudocode converter | ⬜ Deferred (Phase 3) |
| 9 | Material Instance parameter overrides not captured | ✅ `SerializeMaterialInstanceParameterOverrides` (scalar/vector/texture) |
| 10 | CLAUDE.md `get_node_sem_info` typo | ✅ Fixed: now uses `get_node_semantic_info` |
| 11 | `SamplerSourceMode` comment misleading | ✅ Removed; now uses `StaticEnum<>` |
| 12 | Property input defaults not serialized | ⬜ Accepted (FExpressionInput has no defaults) |
| 13 | Comment text no truncation | ✅ `MaxCommentLength = 2048` with truncation |
| 14 | Missing TextureSampleParameterCube/Volume | ✅ Added handlers + shared `SerializeTextureSampleProperties` |

**Score**: 11/14 fixed, 1 partially addressed, 1 deferred, 1 accepted by design. No Round 1 regression remains outstanding.

---

## Round 1 Follow-Up

### 1. CLAUDE.md API typo is fixed

**File**: `CLAUDE.md:60`

```
semantic = unreal.BlueprintGraphReader.get_node_semantic_info(node)
```

The C++ function is `GetNodeSemanticInfo` → Python binding is `get_node_semantic_info`. The README/CLAUDE example now matches the exported API.

---

## 🟡 New Issues Found

### 2. `GetExpressionTitle` fallback returns display name with localization noise

**File**: `MaterialGraphReader.cpp:792`

```cpp
Title = Expr->GetClass()->GetDisplayNameText().ToString();
```

`GetDisplayNameText()` returns localized `FText`, which can include engine metadata markers or namespace keys in non-English locales. For the `Unknown` case at line 777 (`return TEXT("Unknown")`), this is fine. But for real expressions without a `Desc`, the display name may be verbose (e.g., `"Texture Sample Parameter 2D"` instead of something concise).

**Recommendation**: Use `Expr->GetClass()->GetName()` as fallback, then strip the leading `U` — aligns with `GetExpressionClassName`:

```cpp
Title = GetExpressionClassName(Expr);
```

This gives `"MaterialExpressionTextureSampleParameter2D"` instead of `"Texture Sample Parameter 2D"` — longer but no localization surprises and matches the `class` field.

---

### 3. `SerializeComments` truncation calculation uses 1-indexed subtraction

**File**: `MaterialGraphReader.cpp:475`

```cpp
if (Text.Len() > MaxCommentLength)
    Text = Text.Left(MaxCommentLength - 3) + TEXT("...");
```

If `MaxCommentLength = 2048` and `Text.Len() = 2049`, the result is `Left(2045)` + `"..."` = 2048 chars total. This is correct but the `- 3` is inconsistent with `GetExpressionTitle` line 796 which uses `(MaxTitleLength - 3)` — both produce `MaxN - 3 + 3 = MaxN` total chars. Not a bug, but the comment could clarify: `// total output ≤ MaxCommentLength (including "...")`.

---

### 4. Material property list missing `ClearCoat` / `ClearCoatRoughness` (UE 5.1+)

**File**: `MaterialGraphReader.cpp:411-426`

The `SerializeMaterialProperties` list covers 17 standard properties but omits `ClearCoat` and `ClearCoatRoughness`, which UE5 added for the clear-coat shading model alongside the existing `Anisotropy`. These are `FScalarMaterialInput` members on `UMaterial`.

**Status**: Fixed. `Material->ClearCoat` and `Material->ClearCoatRoughness` are now serialized in `SerializeMaterialProperties`.

---

### 5. `ParameterInfo.Association` and `ParameterInfo.Index` not serialized in overrides

**File**: `MaterialGraphReader.cpp:512-553`

`SerializeMaterialInstanceParameterOverrides` serializes `Param.ParameterInfo.Name` but not `Association` (layer parameter scoping: `GlobalParameter`, `LayerParameter`, `BlendParameter`) or `Index` (which layer). For material instances used with material layers, omitting these fields makes cross-referencing ambiguous.

**Status**: Fixed. Scalar/vector/texture parameter override objects now include `"association"` and `"index"` fields alongside `"name"`.

---

## ⚪ Minor

### 6. `GetExpressionClassName` changes behavior for non-standard subclasses

**File**: `MaterialGraphReader.cpp:751-773`

```cpp
// Old behavior: if not starting with "UMaterialExpression", keep full name including U prefix
// New behavior: strip leading U from any class
if (ClassName.Len() > 1 && ClassName[0] == TEXT('U') && FChar::IsUpper(ClassName[1]))
    ClassName.RightChopInline(1);
```

For custom material expression subclasses that don't start with `UMaterialExpression`, this strips the prefix inconsistently. Example: `UMyExpression` → `MyExpression`. In practice, all `UMaterialExpression` subclasses start with `UMaterialExpression`, and `FExpressionInputIterator` etc. are internal helpers not serialized — so this is fine in practice.

---

### 7. `#include` for `ESamplerSourceMode` lives at `MaterialExpressionTextureSample.h`

`GetSamplerSourceName` uses `StaticEnum<ESamplerSourceMode>()` which resolves because `TextureSampleParameter2D.h` transitively includes the base `TextureSample.h` where `ESamplerSourceMode` is defined. No direct `#include` needed, but the dependency is implicit via the texture sample include chain. Fine.

---

## No-Regression Checks (verified unchanged since Round 1)

| Concern | Status |
|---------|--------|
| `FExpressionInputIterator` pattern | ✅ Correct |
| `FExpressionOutputIterator` pattern | ✅ Correct |
| ID uniqueness (e0, e1…) | ✅ Sequential per call |
| Null expression/comment skip | ✅ Guarded |
| `UMaterialInterface::GetMaterial()` resolution | ✅ Correct for Material/MaterialInstance |
| Const-correctness on `ExprIdMap` | ✅ Passed as `const&` |
| Custom node HLSL truncation | ✅ 2048 cap |
| `MaterialFunction` ID isolation | ✅ Separate `ExprIdMap` per `ExtractMaterialFunctionAsJson` |
| Two-sided flag extraction | ✅ `ConcreteMaterial->TwoSided` |

---

## Unchanged from Round 1 (still valid)

- **Material tests**: Static regression checks now cover the material reader fixes. UE fixture/runtime tests remain a Phase 3 item.
- **No pseudocode converter**: Users get JSON but no linear text generation. Phase 3 item.
- **Property input `default` field**: Always `null` because `FExpressionInput` carries no default value — by design.

---

## Recommended Fix Order (Round 2)

1. Consider `GetExpressionTitle` fallback to use `GetExpressionClassName` instead of display name
2. Add UE fixture/runtime tests for MaterialGraphReader (Phase 3)
3. Add material pseudocode converter if the JSON → linear text pipeline becomes in scope

For manual UE validation steps, use `docs/material-graph-reader-manual-verification-checklist.md`.
