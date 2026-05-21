"""
Blueprint Graph → Pseudocode Converter

将蓝图 JSON 图结构转换为缩进伪代码，供 AI Agent 线性推理。

核心算法：沿 exec pin 做 DFS 遍历，遇到 Branch 生成 if/else，
遇到 Loop 生成 for/while，遇到 CallFunction 生成函数调用。
"""

import json
import sys
from typing import Optional
from collections import defaultdict


# K2Node 子类 → 伪代码模板映射
NODE_HANDLERS = {}


def handler(node_class_prefix: str):
    """装饰器：注册节点类型处理器"""
    def decorator(func):
        NODE_HANDLERS[node_class_prefix] = func
        return func
    return decorator


def graph_to_pseudocode(graph_data: dict) -> str:
    """将整个蓝图的 JSON 图结构转换为伪代码"""
    lines = []

    # 蓝图元数据
    asset_path = graph_data.get("asset_path", "unknown")
    parent_class = graph_data.get("parent_class", "")
    lines.append(f"blueprint {asset_path}")
    if parent_class:
        lines.append(f"  parent: {parent_class}")
    lines.append("")

    # 变量声明
    variables = graph_data.get("variables", [])
    if variables:
        lines.append("variables:")
        for var in variables:
            default = var.get("default_value", "")
            default_str = f" = {default}" if default and default != "None" else ""
            editable = " [editable]" if var.get("instance_editable") else ""
            lines.append(f"  {var['type']} {var['name']}{default_str}{editable}")
        lines.append("")

    # 每个图
    for graph in graph_data.get("graphs", []):
        graph_name = graph.get("name", "UnnamedGraph")
        graph_type = graph.get("graph_type", "")
        lines.append(f"graph {graph_name}" +
                     (f" ({graph_type})" if graph_type else ""))
        lines.append("")

        # 构建索引
        node_map = {n["id"]: n for n in graph.get("nodes", [])}
        pin_map = {}  # pin_id → node_id
        for node in graph.get("nodes", []):
            for pin in node.get("pins", []):
                pin_map[pin["id"]] = node["id"]

        # 边索引：从 output pin → input pin
        exec_edges = {}   # from_node_id → [(to_node_id, from_pin_name, to_pin_name)]
        data_edges = {}   # to_pin_id → from_pin_id (数据流反向查找)

        for edge in graph.get("edges", []):
            from_pin = edge["from_pin"]
            to_pin = edge["to_pin"]
            edge_type = edge.get("edge_type", "data")

            from_node_id = pin_map.get(from_pin, "")
            to_node_id = pin_map.get(to_pin, "")

            if edge_type == "exec":
                # exec 边：from_node → to_node
                from_pin_name = _pin_name_from_id(from_pin)
                to_pin_name = _pin_name_from_id(to_pin)
                if from_node_id not in exec_edges:
                    exec_edges[from_node_id] = []
                exec_edges[from_node_id].append({
                    "to_node": to_node_id,
                    "from_pin_name": from_pin_name,
                    "to_pin_name": to_pin_name,
                })
            else:
                # data 边：to_pin ← from_pin (反向查找输入)
                data_edges[to_pin] = from_pin

        # 找入口节点
        entry_nodes = _find_entry_nodes(graph, exec_edges, pin_map)

        # DFS 遍历
        visited = set()
        for entry in entry_nodes:
            _trace_exec_flow(
                node_map, exec_edges, data_edges, pin_map,
                entry, lines, indent=1, visited=visited
            )
            lines.append("")

    return "\n".join(lines)


def _pin_name_from_id(pin_id: str) -> str:
    """从 pin id 提取 pin name (n0_Condition → Condition)"""
    parts = pin_id.split("_", 1)
    return parts[1] if len(parts) > 1 else pin_id


def _find_entry_nodes(graph: dict, exec_edges: dict,
                      pin_map: dict) -> list:
    """识别入口节点（没有 exec 输入的节点）"""
    entry_nodes = []
    nodes = graph.get("nodes", [])

    # 收集所有有 exec 输入连线的节点
    nodes_with_exec_input = set()
    for from_id, targets in exec_edges.items():
        for t in targets:
            nodes_with_exec_input.add(t["to_node"])

    # 没有 exec 输入连线 + 是 K2Node_Event 或 K2Node_FunctionEntry 的节点
    for node in nodes:
        node_class = node.get("class", "")
        if node_class in ("K2Node_Event", "K2Node_FunctionEntry",
                          "K2Node_CustomEvent"):
            entry_nodes.append(node["id"])

    # 如果没找到明确的入口，用没有 exec 输入的节点
    if not entry_nodes:
        for node in nodes:
            if node["id"] not in nodes_with_exec_input:
                # 检查是否有 exec 输出
                has_exec_out = any(
                    p.get("is_exec") and p.get("direction") == "output"
                    for p in node.get("pins", [])
                )
                if has_exec_out:
                    entry_nodes.append(node["id"])

    return entry_nodes


def _resolve_data_input(pin_id: str, node_map: dict,
                        data_edges: dict, pin_map: dict,
                        depth: int = 0) -> str:
    """沿 data 边回溯，解析输入值的来源"""
    if depth > 5:  # 防止无限递归
        return "..."

    # 查找这个 pin 是否有 data 输入
    if pin_id in data_edges:
        source_pin_id = data_edges[pin_id]
        source_node_id = pin_map.get(source_pin_id, "")
        source_node = node_map.get(source_node_id, None)

        if source_node:
            source_class = source_node.get("class", "")
            source_title = source_node.get("title", "")

            if source_class == "K2Node_VariableGet":
                # 变量读取：返回变量名
                return source_title
            elif source_class == "K2Node_VariableSet":
                return source_title
            elif source_class in ("K2Node_CallFunction",):
                # 函数调用：返回函数名(...)
                return f"{source_title}(...)"
            else:
                # 其他：返回节点标题
                return source_title

    # 没有连线，使用默认值
    # 需要找到这个 pin 的默认值
    for nid, node in node_map.items():
        for pin in node.get("pins", []):
            if pin["id"] == pin_id:
                default = pin.get("default_value", "")
                if default:
                    return default
                return pin.get("name", "?")

    return "?"


def _trace_exec_flow(node_map: dict, exec_edges: dict,
                     data_edges: dict, pin_map: dict,
                     current_node_id: str, lines: list,
                     indent: int, visited: set):
    """沿 exec pin DFS 遍历，生成伪代码"""
    if current_node_id in visited:
        return
    visited.add(current_node_id)

    node = node_map.get(current_node_id, None)
    if not node:
        return

    node_class = node.get("class", "")
    title = node.get("title", "")
    comment = node.get("comment", "")
    prefix = "  " * indent

    # 注释
    if comment:
        lines.append(f"{prefix}# {comment}")

    # 查找匹配的处理器
    handler_func = None
    for prefix_key, func in NODE_HANDLERS.items():
        if node_class.startswith(prefix_key):
            handler_func = func
            break

    if handler_func:
        handler_func(
            node, node_map, exec_edges, data_edges, pin_map,
            lines, indent, visited, prefix, current_node_id
        )
    else:
        # 默认处理：输出节点标题
        lines.append(f"{prefix}{title}")
        # 继续追踪 exec 输出
        _trace_next_exec(current_node_id, node_map, exec_edges,
                         data_edges, pin_map, lines, indent, visited)


def _trace_next_exec(node_id: str, node_map: dict, exec_edges: dict,
                     data_edges: dict, pin_map: dict,
                     lines: list, indent: int, visited: set):
    """追踪节点的默认 exec 输出（非 Branch 的单 exec 输出）"""
    targets = exec_edges.get(node_id, [])
    for target in targets:
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            target["to_node"], lines, indent, visited
        )


# ============================================================================
# 节点类型处理器
# ============================================================================

@handler("K2Node_Event")
def handle_event(node, node_map, exec_edges, data_edges, pin_map,
                 lines, indent, visited, prefix, node_id):
    """事件入口：Event BeginPlay / Event Tick 等"""
    title = node.get("title", "Event")
    lines.append(f"{prefix}{title}:")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent + 1, visited)


@handler("K2Node_FunctionEntry")
def handle_function_entry(node, node_map, exec_edges, data_edges, pin_map,
                          lines, indent, visited, prefix, node_id):
    """函数入口"""
    title = node.get("title", "Function")
    # 收集参数
    params = []
    for pin in node.get("pins", []):
        if (pin.get("direction") == "output" and
                not pin.get("is_exec") and
                pin.get("name", "") not in ("", "self", "ReturnValue")):
            param_type = pin.get("pin_type", "")
            param_name = pin.get("name", "")
            params.append(f"{param_name}: {param_type}")

    params_str = ", ".join(params) if params else ""
    lines.append(f"{prefix}function {title}({params_str}):")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent + 1, visited)


@handler("K2Node_CustomEvent")
def handle_custom_event(node, node_map, exec_edges, data_edges, pin_map,
                        lines, indent, visited, prefix, node_id):
    """自定义事件"""
    title = node.get("title", "CustomEvent")
    lines.append(f"{prefix}event {title}:")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent + 1, visited)


@handler("K2Node_IfThenElse")
def handle_branch(node, node_map, exec_edges, data_edges, pin_map,
                  lines, indent, visited, prefix, node_id):
    """条件分支"""
    # 解析 Condition 输入
    condition_pin = None
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                pin.get("name", "") == "Condition"):
            condition_pin = pin
            break

    condition_str = "?"
    if condition_pin:
        condition_str = _resolve_data_input(
            condition_pin["id"], node_map, data_edges, pin_map)

    lines.append(f"{prefix}if {condition_str}:")

    # 找 True 和 False 分支
    targets = exec_edges.get(node_id, [])
    true_targets = [t for t in targets if t["from_pin_name"] == "True"]
    false_targets = [t for t in targets if t["from_pin_name"] == "False"]
    other_targets = [t for t in targets
                     if t["from_pin_name"] not in ("True", "False")]

    # True 分支
    if true_targets:
        for t in true_targets:
            _trace_exec_flow(
                node_map, exec_edges, data_edges, pin_map,
                t["to_node"], lines, indent + 1, visited)
    else:
        lines.append(f"{prefix}  # (no action)")

    # False 分支
    if false_targets:
        lines.append(f"{prefix}else:")
        for t in false_targets:
            _trace_exec_flow(
                node_map, exec_edges, data_edges, pin_map,
                t["to_node"], lines, indent + 1, visited)

    # 其他 exec 输出（如果有）
    for t in other_targets:
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            t["to_node"], lines, indent, visited)


@handler("K2Node_ForEachLoop")
def handle_for_each(node, node_map, exec_edges, data_edges, pin_map,
                    lines, indent, visited, prefix, node_id):
    """ForEach 循环"""
    # 解析 Array 输入
    array_str = "?"
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                pin.get("name", "") == "Array"):
            array_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}for item in {array_str}:")

    # LoopBody 输出
    targets = exec_edges.get(node_id, [])
    body_targets = [t for t in targets if t["from_pin_name"] == "LoopBody"]
    for t in body_targets:
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            t["to_node"], lines, indent + 1, visited)

    # Completed 输出
    completed_targets = [t for t in targets if t["from_pin_name"] == "Completed"]
    if completed_targets:
        lines.append(f"{prefix}# loop completed:")
        for t in completed_targets:
            _trace_exec_flow(
                node_map, exec_edges, data_edges, pin_map,
                t["to_node"], lines, indent, visited)


@handler("K2Node_WhileLoop")
def handle_while_loop(node, node_map, exec_edges, data_edges, pin_map,
                      lines, indent, visited, prefix, node_id):
    """While 循环"""
    condition_str = "?"
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                pin.get("name", "") == "Condition"):
            condition_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}while {condition_str}:")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent + 1, visited)


@handler("K2Node_CallFunction")
def handle_call_function(node, node_map, exec_edges, data_edges, pin_map,
                         lines, indent, visited, prefix, node_id):
    """函数调用"""
    title = node.get("title", "CallFunction")

    # 解析所有输入参数
    args = []
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                not pin.get("is_exec") and
                pin.get("name", "") not in ("self", "Target", "")):
            arg_val = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            args.append(f"{pin['name']}={arg_val}")

    args_str = ", ".join(args)
    lines.append(f"{prefix}{title}({args_str})")

    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent, visited)


@handler("K2Node_VariableGet")
def handle_variable_get(node, node_map, exec_edges, data_edges, pin_map,
                        lines, indent, visited, prefix, node_id):
    """变量读取"""
    title = node.get("title", "Variable")
    lines.append(f"{prefix}{title}")
    # VariableGet 没有 exec pin，不需要追踪


@handler("K2Node_VariableSet")
def handle_variable_set(node, node_map, exec_edges, data_edges, pin_map,
                        lines, indent, visited, prefix, node_id):
    """变量写入"""
    title = node.get("title", "Variable")
    # 解析赋值输入
    value_str = "?"
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                not pin.get("is_exec") and
                pin.get("name", "") not in ("self", "Target", "")):
            value_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}{title} = {value_str}")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent, visited)


@handler("K2Node_ReturnNode")
def handle_return(node, node_map, exec_edges, data_edges, pin_map,
                  lines, indent, visited, prefix, node_id):
    """返回节点"""
    value_str = ""
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                not pin.get("is_exec") and
                pin.get("name", "") == "ReturnValue"):
            value_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}return {value_str}" if value_str
                 else f"{prefix}return")


@handler("K2Node_SpawnActor")
def handle_spawn_actor(node, node_map, exec_edges, data_edges, pin_map,
                       lines, indent, visited, prefix, node_id):
    """生成 Actor"""
    title = node.get("title", "SpawnActor")
    lines.append(f"{prefix}{title}")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent, visited)


@handler("K2Node_MacroInstance")
def handle_macro_instance(node, node_map, exec_edges, data_edges, pin_map,
                          lines, indent, visited, prefix, node_id):
    """宏实例（简化处理，不递归展开）"""
    title = node.get("title", "Macro")
    lines.append(f"{prefix}macro {title}:")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent + 1, visited)


@handler("K2Node_Sequence")
def handle_sequence(node, node_map, exec_edges, data_edges, pin_map,
                    lines, indent, visited, prefix, node_id):
    """Sequence 节点"""
    lines.append(f"{prefix}sequence:")

    targets = exec_edges.get(node_id, [])
    # 按 Then 编号排序
    then_targets = sorted(
        [t for t in targets if t["from_pin_name"].startswith("Then")],
        key=lambda t: t["from_pin_name"]
    )

    for i, target in enumerate(then_targets):
        lines.append(f"{prefix}  step {i}:")
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            target["to_node"], lines, indent + 2, visited)


@handler("K2Node_Switch")
def handle_switch(node, node_map, exec_edges, data_edges, pin_map,
                  lines, indent, visited, prefix, node_id):
    """Switch 节点"""
    title = node.get("title", "Switch")

    # 解析选择值
    value_str = "?"
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                not pin.get("is_exec") and
                pin.get("name", "") == "Selection"):
            value_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}switch {value_str}:")

    targets = exec_edges.get(node_id, [])
    for target in targets:
        case_name = target["from_pin_name"]
        lines.append(f"{prefix}  case {case_name}:")
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            target["to_node"], lines, indent + 2, visited)


@handler("K2Node_CallParentFunction")
def handle_call_parent(node, node_map, exec_edges, data_edges, pin_map,
                       lines, indent, visited, prefix, node_id):
    """调用父类函数"""
    title = node.get("title", "CallParentFunction")
    lines.append(f"{prefix}super::{title}")
    _trace_next_exec(node_id, node_map, exec_edges, data_edges,
                     pin_map, lines, indent, visited)


@handler("K2Node_DynamicCast")
def handle_dynamic_cast(node, node_map, exec_edges, data_edges, pin_map,
                        lines, indent, visited, prefix, node_id):
    """动态类型转换"""
    title = node.get("title", "Cast")
    target_str = "?"
    for pin in node.get("pins", []):
        if (pin.get("direction") == "input" and
                not pin.get("is_exec") and
                pin.get("name", "") == "Object"):
            target_str = _resolve_data_input(
                pin["id"], node_map, data_edges, pin_map)
            break

    lines.append(f"{prefix}cast {title}({target_str}):")

    # Cast 有 CastFailed 分支
    targets = exec_edges.get(node_id, [])
    success_targets = [t for t in targets if t["from_pin_name"] != "CastFailed"]
    failed_targets = [t for t in targets if t["from_pin_name"] == "CastFailed"]

    for t in success_targets:
        _trace_exec_flow(
            node_map, exec_edges, data_edges, pin_map,
            t["to_node"], lines, indent + 1, visited)

    if failed_targets:
        lines.append(f"{prefix}catch (cast failed):")
        for t in failed_targets:
            _trace_exec_flow(
                node_map, exec_edges, data_edges, pin_map,
                t["to_node"], lines, indent + 1, visited)


@handler("K2Node_MakeStruct")
def handle_make_struct(node, node_map, exec_edges, data_edges, pin_map,
                       lines, indent, visited, prefix, node_id):
    """构造结构体"""
    title = node.get("title", "MakeStruct")
    lines.append(f"{prefix}{title}(...)")


@handler("K2Node_BreakStruct")
def handle_break_struct(node, node_map, exec_edges, data_edges, pin_map,
                        lines, indent, visited, prefix, node_id):
    """解构结构体"""
    title = node.get("title", "BreakStruct")
    lines.append(f"{prefix}break {title}")


# ============================================================================
# CLI
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python graph_to_pseudocode.py <blueprint.json>")
        print("       python graph_to_pseudocode.py <blueprint.json> --raw")
        sys.exit(1)

    json_file = sys.argv[1]
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    pseudocode = graph_to_pseudocode(data)
    print(pseudocode)


if __name__ == "__main__":
    main()
