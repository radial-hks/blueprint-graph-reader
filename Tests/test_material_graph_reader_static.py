"""Static regression checks for MaterialGraphReader review fixes."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MATERIAL_CPP = ROOT / "Source" / "BlueprintGraphReader" / "Private" / "MaterialGraphReader.cpp"
REVIEW_DOC = ROOT / "docs" / "material-graph-reader-review.md"
REVIEW_R2_DOC = ROOT / "docs" / "material-graph-reader-review-r2.md"
CLAUDE_MD = ROOT / "CLAUDE.md"
README_MD = ROOT / "README.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_material_reader_uses_ue54_safe_material_apis() -> None:
    source = read_text(MATERIAL_CPP)

    assert "ConcreteMaterial->ShadingModel" not in source
    assert "Material->DiffuseColor" not in source
    assert "SamplerSourceMode::" not in source
    assert "StaticEnum<ESamplerSourceMode>" in source
    assert "GetShadingModels().GetFirstShadingModel()" in source


def test_material_reader_serialization_regressions_are_fixed() -> None:
    source = read_text(MATERIAL_CPP)

    assert "SerializeComments(" in source
    assert "parameter_overrides" in source
    assert "Material->ClearCoat" in source
    assert "Material->ClearCoatRoughness" in source
    assert 'SetStringField("association"' in source
    assert 'SetNumberField("index"' in source
    assert "MaterialExpression%s" not in source
    assert "TextureSampleParameterCube" in source
    assert "TextureSampleParameterVolume" in source


def test_docs_reflect_correct_review_scope() -> None:
    review = read_text(REVIEW_DOC)
    review_r2 = read_text(REVIEW_R2_DOC)
    claude = read_text(CLAUDE_MD)
    readme = read_text(README_MD)

    assert "Current target" in review
    assert "No MaterialGraphReader test coverage" in review
    assert "Zero test coverage" not in review
    assert "get_node_sem_info" not in claude
    assert "get_node_semantic_info" in claude
    assert "graph_to_pseudocode.py" in readme
    assert "仅支持蓝图 JSON" in readme
    assert "Not fixed" not in review_r2
    assert "still wrong" not in review_r2
    assert "ClearCoat" in review_r2
    assert "association" in review_r2
