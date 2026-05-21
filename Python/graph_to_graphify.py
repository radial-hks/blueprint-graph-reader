"""
Blueprint Graph → graphify Knowledge Graph Converter

将蓝图 JSON 图结构转换为 graphify 知识图谱格式，
支持通过 graphify CLI 查询蓝图调用关系。
"""

import json
import sys
from typing import Optional


def graph_to_graphify(graph_data: dict) -> dict:
    """
    将蓝图 JSON 转换为 graphify 知识图谱格式。

    Returns:
        graphify 格式的 dict，包含 nodes 和 edges。
    """
    result = {
        "nodes": [],
        "edges": []
    }

    asset_path = graph_data.get("asset_path", "unknown")
    parent_class = graph_data.get("parent_class", "")
    bp_id = asset_path.replace("/", "_").strip("_")

    # 蓝图本身作为一个节点
    result["nodes"].append({
        "id": bp_id,
        "type": "blueprint",
        "label": asset_path.split("/")[-1],
        "properties": {
            "asset_path": asset_path,
            "parent_class": parent_class,
            "blueprint_type": graph_data.get("blueprint_type", ""),
        }
    })

    # 变量节点
    for var in graph_data.get("variables", []):
        var_id = f"{bp_id}_var_{var['name']}"
        result["nodes"].append({
            "id": var_id,
            "type": "variable",
            "label": var["name"],
            "properties": {
                "var_type": var.get("type", ""),
                "default_value": var.get("default_value", ""),
                "instance_editable": var.get("instance_editable", False),
                "expose_on_spawn": var.get("expose_on_spawn", False),
            }
        })
        # 蓝图 → 变量
        result["edges"].append({
            "source": bp_id,
            "target": var_id,
            "type": "has_variable",
        })

    # 遍历所有图中的节点
    for graph in graph_data.get("graphs", []):
        graph_name = graph.get("name", "")
        graph_type = graph.get("graph_type", "")
        graph_id = f"{bp_id}_graph_{graph_name}"

        # 图节点
        result["nodes"].append({
            "id": graph_id,
            "type": "graph",
            "label": graph_name,
            "properties": {
                "graph_type": graph_type,
            }
        })
        result["edges"].append({
            "source": bp_id,
            "target": graph_id,
            "type": "has_graph",
        })

        # 节点
        node_id_map = {}  # json node id → graphify node id
        for node in graph.get("nodes", []):
            node_class = node.get("class", "")
            title = node.get("title", "")
            comment = node.get("comment", "")

            gn_id = f"{graph_id}_node_{node['id']}"
            node_id_map[node["id"]] = gn_id

            result["nodes"].append({
                "id": gn_id,
                "type": "bp_node",
                "label": title,
                "properties": {
                    "class": node_class,
                    "comment": comment,
                }
            })
            result["edges"].append({
                "source": graph_id,
                "target": gn_id,
                "type": "contains_node",
            })

            # 如果是函数调用，额外记录被调用的函数名
            if node_class == "K2Node_CallFunction":
                result["edges"].append({
                    "source": gn_id,
                    "target": f"func:{title}",
                    "type": "calls_function",
                })
                # 添加函数节点（如果不存在）
                func_id = f"func:{title}"
                if not any(n["id"] == func_id for n in result["nodes"]):
                    result["nodes"].append({
                        "id": func_id,
                        "type": "function",
                        "label": title,
                        "properties": {}
                    })

            # 如果是变量引用，连接到变量节点
            if node_class in ("K2Node_VariableGet", "K2Node_VariableSet"):
                var_name = title
                var_id = f"{bp_id}_var_{var_name}"
                edge_type = "reads_variable" if "Get" in node_class else "writes_variable"
                result["edges"].append({
                    "source": gn_id,
                    "target": var_id,
                    "type": edge_type,
                })

        # 执行边（控制流）
        for edge in graph.get("edges", []):
            from_pin = edge.get("from_pin", "")
            to_pin = edge.get("to_pin", "")
            edge_type_str = edge.get("edge_type", "data")

            # 从 pin id 提取 node id
            from_node_json_id = from_pin.rsplit("_", 1)[0] if "_" in from_pin else ""
            to_node_json_id = to_pin.rsplit("_", 1)[0] if "_" in to_pin else ""

            from_gn_id = node_id_map.get(from_node_json_id, "")
            to_gn_id = node_id_map.get(to_node_json_id, "")

            if from_gn_id and to_gn_id:
                result["edges"].append({
                    "source": from_gn_id,
                    "target": to_gn_id,
                    "type": "exec_flow" if edge_type_str == "exec" else "data_flow",
                    "properties": {
                        "from_pin": from_pin,
                        "to_pin": to_pin,
                    }
                })

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python graph_to_graphify.py <blueprint.json> [output.json]")
        sys.exit(1)

    json_file = sys.argv[1]
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    graphify_data = graph_to_graphify(data)

    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(graphify_data, f, indent=2, ensure_ascii=False)
        print(f"Graphify data saved to: {output_file}")
    else:
        print(json.dumps(graphify_data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
