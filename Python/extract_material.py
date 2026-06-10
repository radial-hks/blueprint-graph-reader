"""
Material Graph Extractor — 从 UE 材质资产提取 JSON 图结构

使用方式 (UE Python 控制台):
    import extract_material
    extract_material.extract("/Game/Materials/M_Master", output_path="~/m_master.json")
    extract_material.extract_all("/Game/Materials/", output_dir="~/material_graphs/")
"""

import unreal
import json
import os
import sys
from typing import Optional


def _is_plugin_available() -> bool:
    """延迟检测 C++ 插件是否可用（每次调用时检测，而非导入时）"""
    return hasattr(unreal, 'MaterialGraphReader')


def extract(asset_path: str, output_path: Optional[str] = None) -> dict:
    """
    提取单个材质资产为 JSON 图结构。

    支持类型: Material, MaterialInstanceConstant, MaterialFunction

    Args:
        asset_path: 材质资产路径，如 "/Game/Materials/M_Master"
        output_path: 输出文件路径（可选），不指定则只返回 dict

    Returns:
        材质图结构的 dict（符合 material-v1 schema）
    """
    if not _is_plugin_available():
        unreal.log_warning(
            "MaterialGraphReader plugin not available. "
            "Falling back to metadata-only extraction."
        )
        return _extract_metadata_only(asset_path, output_path)

    # 加载资产
    asset = unreal.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Failed to load material asset: {asset_path}")

    # 根据类型调用对应的 C++ 提取函数
    # MaterialInstanceConstant 也通过 extract_material_as_json 处理（C++ 端会解析到父材质）
    if isinstance(asset, unreal.MaterialInstanceConstant):
        json_str = unreal.MaterialGraphReader.extract_material_as_json(asset)
    elif isinstance(asset, unreal.Material):
        json_str = unreal.MaterialGraphReader.extract_material_as_json(asset)
    elif isinstance(asset, unreal.MaterialFunction):
        json_str = unreal.MaterialGraphReader.extract_material_function_as_json(asset)
    else:
        raise TypeError(
            f"Asset is not a Material or MaterialFunction: "
            f"{asset_path} (type: {type(asset)})"
        )

    graph_data = json.loads(json_str)

    # 写入文件
    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
        unreal.log(f"Material graph saved to: {output_path}")

    return graph_data


def extract_all(content_path: str, output_dir: str,
                recursive: bool = True) -> list:
    """
    批量提取目录下所有材质资产（Material, MaterialInstanceConstant, MaterialFunction）。

    Args:
        content_path: Content Browser 路径，如 "/Game/Materials/"
        output_dir: 输出目录
        recursive: 是否递归扫描子目录

    Returns:
        提取结果列表 [{asset_path, output_path, expression_count, material_type}, ...]
    """
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 扫描材质资产 — 使用 ARFilter (UE 5.4+ 兼容)
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    # 需要扫描三种材质类型
    material_classes = [
        ("Material", unreal.TopLevelAssetPath("/Script/Engine", "Material")),
        ("MaterialInstanceConstant", unreal.TopLevelAssetPath("/Script/Engine", "MaterialInstanceConstant")),
        ("MaterialFunction", unreal.TopLevelAssetPath("/Script/Engine", "MaterialFunction")),
    ]

    all_assets = []

    try:
        # UE 5.1+ 推荐：class_paths (TopLevelAssetPath)
        for class_name, top_level_path in material_classes:
            ar_filter = unreal.ARFilter(
                package_paths=[content_path],
                class_paths=[top_level_path],
                recursive_paths=recursive,
            )
            assets = asset_registry.get_assets(ar_filter)
            for a in assets:
                all_assets.append((a, class_name))
    except (TypeError, AttributeError):
        # 老版本降级：class_names (FName 字符串)
        for class_name, _ in material_classes:
            ar_filter = unreal.ARFilter(
                package_paths=[content_path],
                class_names=[class_name],
                recursive_paths=recursive,
            )
            assets = asset_registry.get_assets(ar_filter)
            for a in assets:
                all_assets.append((a, class_name))

    results = []

    for asset_data, material_class in all_assets:
        asset_path = asset_data.get_editor_property("package_name")
        asset_name = asset_data.get_editor_property("asset_name")

        try:
            out_path = os.path.join(output_dir, f"{asset_name}.json")
            graph_data = extract(asset_path, output_path=out_path)

            # 统计表达式数
            expression_count = len(graph_data.get("expressions", []))

            results.append({
                "asset_path": asset_path,
                "output_path": out_path,
                "material_type": graph_data.get("material_type", material_class),
                "expression_count": expression_count,
                "status": "ok"
            })
            unreal.log(
                f"Extracted: {asset_name} "
                f"({material_class}, {expression_count} expressions)"
            )

        except Exception as e:
            results.append({
                "asset_path": asset_path,
                "output_path": None,
                "material_type": material_class,
                "expression_count": 0,
                "status": f"error: {e}"
            })
            unreal.log_error(f"Failed to extract {asset_path}: {e}")

    # 写入索引
    index_path = os.path.join(output_dir, "_index.json")
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    unreal.log(
        f"Batch extraction complete: {len(results)} material assets, "
        f"{sum(1 for r in results if r['status'] == 'ok')} succeeded"
    )
    return results


def _extract_metadata_only(asset_path: str,
                           output_path: Optional[str] = None) -> dict:
    """无 C++ 插件时的回退模式：只提取可用 Python API 获取的材质元数据"""
    asset = unreal.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Failed to load material asset: {asset_path}")

    # 检测材质类型
    if isinstance(asset, unreal.MaterialFunction):
        material_type = "MaterialFunction"
    elif isinstance(asset, unreal.MaterialInstanceConstant):
        material_type = "MaterialInstanceConstant"
    elif isinstance(asset, unreal.Material):
        material_type = "Material"
    else:
        material_type = type(asset).__name__

    graph_data = {
        "schema_version": "material-v1",
        "asset_path": asset_path,
        "material_type": material_type,
        "extraction_mode": "metadata_only",
        "expressions": [],
        "properties": {},
        "warning": "C++ MaterialGraphReader plugin not available. "
                   "Expression/Pin/Connection data requires the plugin."
    }

    # 尝试从 Material 对象提取基本属性
    if isinstance(asset, unreal.Material):
        try:
            graph_data["shading_model"] = str(
                asset.get_editor_property("shading_model")
            )
        except Exception:
            graph_data["shading_model"] = None

        try:
            graph_data["blend_mode"] = str(
                asset.get_editor_property("blend_mode")
            )
        except Exception:
            graph_data["blend_mode"] = None

    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)

    return graph_data


if __name__ == "__main__":
    # 命令行模式（仅用于测试 JSON 解析，不连接 UE）
    if len(sys.argv) < 2:
        print("Usage: python extract_material.py <json_file> [--stats]")
        sys.exit(1)

    json_file = sys.argv[1]
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if "--stats" in sys.argv:
        total_expressions = len(data.get("expressions", []))
        total_props = len(data.get("properties", {}))
        total_comments = len(data.get("comments", []))
        total_funcs = len(data.get("material_functions", []))
        print(f"Asset: {data.get('asset_path', 'unknown')}")
        print(f"Material Type: {data.get('material_type', 'unknown')}")
        print(f"Shading Model: {data.get('shading_model', 'N/A')}")
        print(f"Blend Mode: {data.get('blend_mode', 'N/A')}")
        print(f"Expressions: {total_expressions}")
        print(f"Material Properties: {total_props}")
        print(f"Material Functions: {total_funcs}")
        print(f"Comments: {total_comments}")
