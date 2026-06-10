# Material Graph Reader — Manual Verification Checklist

Use this checklist when a real Unreal Editor environment is available. It is intended to validate behavior that cannot be proven from static checks alone: plugin compilation, UE reflection bindings, material asset traversal, and emitted JSON correctness.

## Scope

- Target engine: UE 5.4+.
- Plugin mode: Editor module enabled in a UE project.
- APIs under test:
  - `unreal.MaterialGraphReader.extract_material_as_json`
  - `unreal.MaterialGraphReader.extract_material_function_as_json`
  - `unreal.MaterialGraphReader.get_expression_info`
  - `unreal.MaterialGraphReader.get_material_property_connections`
  - `Python/extract_material.py` `extract()` and `extract_all()` wrappers

## Test Assets To Prepare

Create or identify these assets in a test UE project:

| Asset | Required content | Purpose |
|---|---|---|
| `/Game/MGR/M_BGR_Basic` | Material with scalar/vector parameters, a texture sample parameter 2D, a material function call, and at least one comment | Baseline material extraction |
| `/Game/MGR/MF_BGR_Test` | Material Function with at least two expressions and a colored comment | Material function extraction and comment consistency |
| `/Game/MGR/MI_BGR_Overrides` | Material Instance Constant based on `M_BGR_Basic`, with scalar/vector/texture overrides | `parameter_overrides` validation |
| `/Game/MGR/M_BGR_ClearCoat` | Material using Clear Coat, with connected `ClearCoat` and `ClearCoatRoughness` inputs | UE5 clear-coat property coverage |
| `/Game/MGR/M_BGR_TextureKinds` | Material with TextureSampleParameter2D plus Cube or Volume texture parameter nodes if available | texture parameter property coverage |
| `/Game/MGR/M_BGR_LongComment` | Material with a comment longer than 2048 characters | comment truncation validation |

If material layers are available in the test project, add one layered material instance with layer or blend scoped parameters to validate `association` and `index` beyond global parameters.

## Input/Output Checkpoints

### 1. Plugin Build And Load

**Input**

- Copy or symlink this plugin into a UE 5.4+ project's `Plugins/` directory.
- Regenerate project files and build the Editor target.
- Enable `Blueprint Graph Reader` in the editor.

**Expected output**

- Editor starts without module load errors.
- Python console returns `True`:

```python
import unreal
hasattr(unreal, "MaterialGraphReader")
```

**Details to check**

- No compile errors involving `ShadingModel`, `DiffuseColor`, or `SamplerSourceMode`.
- No warnings about missing `MaterialGraphReader` reflected functions.
- Plugin is editor-only and does not require runtime game packaging validation for this checklist.

### 2. Direct Material Extraction

**Input**

```python
import json, unreal
mat = unreal.load_asset("/Game/MGR/M_BGR_Basic.M_BGR_Basic")
raw = unreal.MaterialGraphReader.extract_material_as_json(mat)
data = json.loads(raw)
```

**Expected output**

- `data["schema_version"] == "material-v1"`
- `data["material_type"] == "Material"`
- `data["asset_path"]` contains `M_BGR_Basic`
- `data["expressions"]` is a non-empty list
- `data["properties"]` exists

**Details to check**

- `shading_model`, `blend_mode`, and `two_sided` are present.
- `properties` contains `BaseColor`, `Metallic`, `Roughness`, `Normal`, and other standard fields when available.
- `DiffuseColor` is not present for UE 5.4+.
- Every expression has `id`, `class`, `title`, `position`, `inputs`, and `outputs`.
- Expression IDs are unique and sequential in the `e0`, `e1`, ... pattern.
- `class` values do not contain `MaterialExpressionMaterialExpression`.

### 3. Clear Coat Material Properties

**Input**

```python
mat = unreal.load_asset("/Game/MGR/M_BGR_ClearCoat.M_BGR_ClearCoat")
data = json.loads(unreal.MaterialGraphReader.extract_material_as_json(mat))
props = data["properties"]
```

**Expected output**

- `props["ClearCoat"]` exists.
- `props["ClearCoatRoughness"]` exists.
- Connected values include `connected_to` expression IDs and `output_index` numbers.

**Details to check**

- If either clear-coat input is unconnected, it still appears with `connected_to: null` and `output_index: null`.
- No other material property disappeared after adding clear-coat fields.

### 4. Material Function Extraction

**Input**

```python
func = unreal.load_asset("/Game/MGR/MF_BGR_Test.MF_BGR_Test")
data = json.loads(unreal.MaterialGraphReader.extract_material_function_as_json(func))
```

**Expected output**

- `data["material_type"] == "MaterialFunction"`
- `data["name"] == "MF_BGR_Test"`
- `data["expressions"]` is non-empty
- `data["comments"]` exists if the function has comments

**Details to check**

- Function comments include `text`, `position`, `size`, and `color`.
- Function expression IDs start at `e0` and are independent from material extraction IDs.
- No material-only fields are required for material functions, such as `properties` or `blend_mode`.

### 5. Material Instance Overrides

**Input**

```python
inst = unreal.load_asset("/Game/MGR/MI_BGR_Overrides.MI_BGR_Overrides")
data = json.loads(unreal.MaterialGraphReader.extract_material_as_json(inst))
overrides = data["parameter_overrides"]
```

**Expected output**

- `data["material_type"] == "MaterialInstanceConstant"`
- `parameter_overrides.scalar`, `parameter_overrides.vector`, and `parameter_overrides.texture` are arrays.
- Each override object includes `name`, `association`, `index`, and `value`.

**Details to check**

- Scalar `value` is a number.
- Vector `value` is a four-number array `[R, G, B, A]`.
- Texture `value` is either an asset path string or `null`.
- Global parameters should have an association string corresponding to the global association enum and a stable index value.
- Layered material parameters, if tested, should preserve distinct `association` and `index` values so same-name parameters can be disambiguated.
- The extracted graph still reflects the parent material expressions while override values reflect the instance.

### 6. Texture Sample Parameter Properties

**Input**

```python
mat = unreal.load_asset("/Game/MGR/M_BGR_TextureKinds.M_BGR_TextureKinds")
data = json.loads(unreal.MaterialGraphReader.extract_material_as_json(mat))
texture_nodes = [
    expr for expr in data["expressions"]
    if "TextureSampleParameter" in expr.get("class", "")
]
```

**Expected output**

- Texture parameter expressions include a `properties` object.
- `properties.parameter_name` exists for TextureSampleParameter2D and for Cube or Volume parameter nodes when present.
- `properties.texture` is either an asset path string or `null`.
- `properties.sampler_type` is a string from `ESamplerSourceMode` reflection.

**Details to check**

- Sampler output should be stable and should not depend on hardcoded short enum names such as `SSM_Wrap` or `SSM_Clamp`.
- Non-parameter texture sample expressions may omit `parameter_name` but should still include texture and sampler fields.
- Group names are included when a parameter group is set.

### 7. Material Function Call References

**Input**

Use `M_BGR_Basic` with one or more material function call nodes.

**Expected output**

- `data["material_functions"]` exists when a material function call is present.
- Each entry has `name`, `asset_path`, and `called_from`.
- `called_from` contains expression IDs that exist in `data["expressions"]`.

**Details to check**

- Multiple calls to the same material function should produce one material function entry with multiple `called_from` IDs.
- Calls to different functions should produce separate entries.

### 8. Comment Serialization And Truncation

**Input**

```python
mat = unreal.load_asset("/Game/MGR/M_BGR_LongComment.M_BGR_LongComment")
data = json.loads(unreal.MaterialGraphReader.extract_material_as_json(mat))
comment = data["comments"][0]
```

**Expected output**

- `comment["text"]` length is at most 2048 characters.
- Truncated text ends with `...`.
- `comment` includes `position`, `size`, and `color`.

**Details to check**

- Total comment length includes the trailing ellipsis.
- Comment color is a four-number RGBA array.
- Comment nodes are not duplicated in `expressions`.

### 9. Single Expression Query

**Input**

Select or otherwise obtain a `UMaterialExpression` reference in an editor utility script, then call:

```python
raw = unreal.MaterialGraphReader.get_expression_info(expression)
data = json.loads(raw)
```

**Expected output**

- `data["id"] == "e0"`
- `data["class"]` and `data["title"]` exist.
- `inputs`, `outputs`, and type-specific `properties` are present when applicable.

**Details to check**

- For connected inputs outside the single-expression map, `connected_to` may be `null`; this is acceptable for a single-expression query.
- `class` normalization should match the same expression class when extracted from the full material.

### 10. Material Property Connections API

**Input**

```python
mat = unreal.load_asset("/Game/MGR/M_BGR_Basic.M_BGR_Basic")
props = json.loads(unreal.MaterialGraphReader.get_material_property_connections(mat))
```

**Expected output**

- Output is a JSON object containing material property names.
- Each property object has `connected_to` and `output_index`.

**Details to check**

- IDs in `connected_to` should match the expression ID assignment order used by `extract_material_as_json` for the same material.
- Unconnected properties should use `null` for both fields.
- `ClearCoat` and `ClearCoatRoughness` should be present for UE 5.4+ builds.

### 11. Python Wrapper Extraction

**Input**

```python
import extract_material
one = extract_material.extract(
    "/Game/MGR/M_BGR_Basic",
    output_path="~/mgr_basic.json",
)
batch = extract_material.extract_all(
    "/Game/MGR/",
    output_dir="~/mgr_material_graphs",
)
```

**Expected output**

- `~/mgr_basic.json` exists and matches the direct C++ extraction schema.
- `~/mgr_material_graphs/_index.json` exists.
- Batch results include Material, MaterialInstanceConstant, and MaterialFunction assets.

**Details to check**

- `status == "ok"` for expected assets.
- `expression_count` matches the length of each output JSON `expressions` array.
- If the plugin is unavailable, wrapper fallback should emit metadata-only output and log a warning rather than pretending full graph extraction succeeded.

### 12. Error And Edge Cases

**Input**

```python
unreal.MaterialGraphReader.extract_material_as_json(None)
unreal.MaterialGraphReader.extract_material_function_as_json(None)
extract_material.extract("/Game/MGR/DoesNotExist")
```

**Expected output**

- Null C++ calls return `{}` as a JSON string.
- Invalid asset paths through the Python wrapper raise a clear exception.

**Details to check**

- No editor crash.
- Errors include the asset path or failing operation.
- Failed batch items are recorded in `_index.json` with `status` beginning with `error:`.

## JSON Consistency Checks

Run these after saving output JSON files:

```python
import json
from pathlib import Path

data = json.loads(Path("~/mgr_basic.json").expanduser().read_text())
expr_ids = {expr["id"] for expr in data.get("expressions", [])}

assert data["schema_version"] == "material-v1"
assert all(expr_id.startswith("e") for expr_id in expr_ids)

for expr in data.get("expressions", []):
    for input_pin in expr.get("inputs", []):
        target = input_pin.get("connected_to")
        assert target is None or target in expr_ids

for func in data.get("material_functions", []):
    for caller in func.get("called_from", []):
        assert caller in expr_ids
```

## Result Recording Template

| Checkpoint | Asset/API | Pass/Fail | Notes |
|---|---|---|---|
| Plugin build/load |  |  |  |
| Direct material extraction |  |  |  |
| Clear coat properties |  |  |  |
| Material function extraction |  |  |  |
| Material instance overrides |  |  |  |
| Texture parameter variants |  |  |  |
| Function call references |  |  |  |
| Comment truncation/color |  |  |  |
| Single expression query |  |  |  |
| Property connections API |  |  |  |
| Python wrapper extraction |  |  |  |
| Error/edge cases |  |  |  |

## Pass Criteria

Manual validation is complete when:

- The plugin compiles and loads in UE 5.4+.
- All direct C++ API calls return parseable JSON.
- `extract_material.py` produces equivalent JSON files and batch indexes.
- Clear-coat properties, material instance override scope metadata, texture parameter metadata, comments, and material function references are present as described above.
- No tested extraction path crashes the editor.
- Any deviation is recorded with the exact asset path, API call, observed JSON fragment, and editor log excerpt.
