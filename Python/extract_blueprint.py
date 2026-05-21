"""
Blueprint Graph Extractor — 从 UE 蓝图提取 JSON 图结构

使用方式 (UE Python 控制台):
    import extract_blueprint
    extract_blueprint.extract("/Game/Blueprints/BP_Enemy", output_path="~/bp_enemy.json")
    extract_blueprint.extract_all("/Game/Blueprints/", output_dir="~/blueprint_graphs/")
"""

import unreal
import json
import os
import sys
from typing import Optional

# 检测 C++ 插件是否可用
_PLUGIN_AVAILABLE = hasattr(unreal, 'BlueprintGraphReader')


def extract(asset_path: str, output_path: Optional[str] = None) -> dict:
    """
    提取单个蓝图为 JSON 图结构。

    Args:
        asset_path: 蓝图资产路径，如 "/Game/Blueprints/BP_Enemy"
        output_path: 输出文件路径（可选），不指定则只返回 dict

    Returns:
        蓝图图结构的 dict（符合 blueprint-graph-v1 schema）
    """
    if not _PLUGIN_AVAILABLE:
        unreal.log_warning(
            "BlueprintGraphReader plugin not available. "
            "Falling back to metadata-only extraction."
        )
        return _extract_metadata_only(asset_path, output_path)

    # 加载蓝图
    bp = unreal.load_asset(asset_path)
    if not bp:
        raise ValueError(f"Failed to load blueprint: {asset_path}")

    # 确保是蓝图类型
    if not isinstance(bp, unreal.Blueprint):
        raise TypeError(f"Asset is not a Blueprint: {asset_path} (type: {type(bp)})")

    # 通过 C++ 插件一步提取
    json_str = unreal.BlueprintGraphReader.extract_blueprint_as_json(bp)
    graph_data = json.loads(json_str)

    # 写入文件
    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
        unreal.log(f"Blueprint graph saved to: {output_path}")

    return graph_data


def extract_all(content_path: str, output_dir: str,
                recursive: bool = True) -> list:
    """
    批量提取目录下所有蓝图。

    Args:
        content_path: Content Browser 路径，如 "/Game/Blueprints/"
        output_dir: 输出目录
        recursive: 是否递归扫描子目录

    Returns:
        提取结果列表 [{asset_path, output_path, node_count}, ...]
    """
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 扫描蓝图资产
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    search_options = unreal.AssetRegistrySearchOptions()
    search_options.set_editor_property("package_path", content_path)
    search_options.set_editor_property("recursive_paths", recursive)
    search_options.set_editor_property("asset_class", "Blueprint")

    assets = asset_registry.get_assets(search_options)
    results = []

    for asset_data in assets:
        asset_path = asset_data.get_editor_property("package_name")
        asset_name = asset_data.get_editor_property("asset_name")

        try:
            out_path = os.path.join(output_dir, f"{asset_name}.json")
            graph_data = extract(asset_path, output_path=out_path)

            # 统计节点数
            node_count = sum(
                len(g.get("nodes", []))
                for g in graph_data.get("graphs", [])
            )

            results.append({
                "asset_path": asset_path,
                "output_path": out_path,
                "node_count": node_count,
                "status": "ok"
            })
            unreal.log(f"Extracted: {asset_name} ({node_count} nodes)")

        except Exception as e:
            results.append({
                "asset_path": asset_path,
                "output_path": None,
                "node_count": 0,
                "status": f"error: {e}"
            })
            unreal.log_error(f"Failed to extract {asset_path}: {e}")

    # 写入索引
    index_path = os.path.join(output_dir, "_index.json")
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    unreal.log(f"Batch extraction complete: {len(results)} blueprints, "
               f"{sum(1 for r in results if r['status'] == 'ok')} succeeded")
    return results


def _extract_metadata_only(asset_path: str,
                           output_path: Optional[str] = None) -> dict:
    """无 C++ 插件时的回退模式：只提取可用 Python API 获取的元数据"""
    bp = unreal.load_asset(asset_path)
    if not bp:
        raise ValueError(f"Failed to load blueprint: {asset_path}")

    graph_data = {
        "schema_version": "v1",
        "asset_path": asset_path,
        "extraction_mode": "metadata_only",
        "graphs": [],
        "variables": [],
        "warning": "C++ BlueprintGraphReader plugin not available. "
                   "Node/Pin/Edge data requires the plugin."
    }

    # 图名列表
    graph_names = unreal.BlueprintEditorLibrary.get_blueprint_graph_names(bp)
    for name in graph_names:
        graph_data["graphs"].append({
            "name": name,
            "nodes": [],
            "edges": []
        })

    # 变量信息（Blueprint 类本身可能暴露部分变量属性）
    # 注意：这部分依赖 Blueprint 类的 Python 暴露程度，可能不完整

    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)

    return graph_data


if __name__ == "__main__":
    # 命令行模式（仅用于测试 JSON 解析，不连接 UE）
    if len(sys.argv) < 2:
        print("Usage: python extract_blueprint.py <json_file> [--stats]")
        sys.exit(1)

    json_file = sys.argv[1]
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if "--stats" in sys.argv:
        total_nodes = sum(len(g.get("nodes", [])) for g in data.get("graphs", []))
        total_edges = sum(len(g.get("edges", [])) for g in data.get("graphs", []))
        total_vars = len(data.get("variables", []))
        print(f"Asset: {data.get('asset_path', 'unknown')}")
        print(f"Graphs: {len(data.get('graphs', []))}")
        print(f"Nodes: {total_nodes}")
        print(f"Edges: {total_edges}")
        print(f"Variables: {total_vars}")
