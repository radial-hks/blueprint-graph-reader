"""
Blueprint Graph → Mermaid Flowchart Converter

将蓝图 JSON 图结构转换为 Mermaid flowchart，用于可视化验证。
exec 边用实线箭头，data 边用虚线箭头。
"""

import json
import sys
from typing import Optional


def graph_to_mermaid(graph_data: dict) -> str:
    """将整个蓝图转换为 Mermaid flowchart"""
    lines = ["flowchart TD"]

    for graph in graph_data.get("graphs", []):
        graph_name = graph.get("name", "UnnamedGraph")

        # 图标题作为 subgraph
        lines.append(f"    subgraph {graph_name}")

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # 节点映射
        node_map = {n["id"]: n for n in nodes}
        pin_map = {}
        for node in nodes:
            for pin in node.get("pins", []):
                pin_map[pin["id"]] = node["id"]

        # 输出节点
        for node in nodes:
            node_id = node["id"]
            node_class = node.get("class", "")
            title = node.get("title", "")
            comment = node.get("comment", "")

            # 选择节点形状
            if "Event" in node_class or "Entry" in node_class:
                shape_start = "{{"
                shape_end = "}}"
                icon = "🎬 "
            elif "Branch" in node_class or "IfThenElse" in node_class:
                shape_start = "{"
                shape_end = "}"
                icon = "◇ "
            elif "Loop" in node_class or "ForEach" in node_class:
                shape_start = "["
                shape_end = "]"
                icon = "🔄 "
            elif "VariableSet" in node_class:
                shape_start = "[/"
                shape_end = "/]"
                icon = ""
            elif "VariableGet" in node_class:
                shape_start = "[/"
                shape_end = "/]"
                icon = ""
            elif "CallFunction" in node_class:
                shape_start = "["
                shape_end = "]"
                icon = ""
            else:
                shape_start = "["
                shape_end = "]"
                icon = ""

            label = f"{icon}{title}"
            if comment:
                label += f"\\n#{comment}"

            # Mermaid ID 不能有特殊字符
            safe_id = node_id.replace(" ", "_")
            lines.append(f"        {safe_id}{shape_start}\"{label}\"{shape_end}")

        lines.append("    end")
        lines.append("")

        # 输出边
        for edge in edges:
            from_pin = edge.get("from_pin", "")
            to_pin = edge.get("to_pin", "")
            edge_type = edge.get("edge_type", "data")

            from_node = pin_map.get(from_pin, "")
            to_node = pin_map.get(to_pin, "")

            if not from_node or not to_node:
                continue

            # 同一个节点内的 self 连接跳过
            if from_node == to_node:
                continue

            safe_from = from_node.replace(" ", "_")
            safe_to = to_node.replace(" ", "_")

            # 从 pin name 提取标签
            from_label = from_pin.split("_", 1)[-1] if "_" in from_pin else ""
            to_label = to_pin.split("_", 1)[-1] if "_" in to_pin else ""

            edge_label = from_label or to_label
            label_str = f"|{edge_label}|" if edge_label and edge_label not in ("", "exec") else ""

            if edge_type == "exec":
                # exec 边：实线箭头
                lines.append(f"    {safe_from} -->{label_str} {safe_to}")
            else:
                # data 边：虚线箭头
                lines.append(f"    {safe_from} -.->{label_str} {safe_to}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python graph_to_mermaid.py <blueprint.json>")
        sys.exit(1)

    json_file = sys.argv[1]
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    mermaid = graph_to_mermaid(data)
    print(mermaid)


if __name__ == "__main__":
    main()
