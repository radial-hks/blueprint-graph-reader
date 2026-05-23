"""Tests for graph_to_pseudocode converter"""

import json
import pytest
from graph_to_pseudocode import graph_to_pseudocode


# ============================================================================
# Fixtures
# ============================================================================

def make_simple_blueprint():
    """简单蓝图：BeginPlay → Branch → PrintString"""
    return {
        "schema_version": "v1",
        "asset_path": "/Game/BP_Test",
        "blueprint_type": "BPType_Normal",
        "parent_class": "Actor",
        "variables": [
            {
                "name": "Health",
                "type": "float",
                "default_value": "100.0",
                "instance_editable": True,
                "expose_on_spawn": False
            }
        ],
        "graphs": [
            {
                "name": "EventGraph",
                "graph_type": "ubergraph",
                "nodes": [
                    {
                        "id": "n0",
                        "class": "K2Node_Event",
                        "title": "Event BeginPlay",
                        "comment": "初始化",
                        "position": [100, 200],
                        "pins": [
                            {"id": "p0", "name": "", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p1", "name": "self", "direction": "output", "pin_type": "object", "sub_type": "Actor", "default_value": "", "is_exec": False}
                        ]
                    },
                    {
                        "id": "n1",
                        "class": "K2Node_IfThenElse",
                        "title": "IsValid?",
                        "comment": "",
                        "position": [400, 200],
                        "pins": [
                            {"id": "p2", "name": "", "direction": "input", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p3", "name": "Condition", "direction": "input", "pin_type": "bool", "default_value": "false", "is_exec": False},
                            {"id": "p4", "name": "True", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p5", "name": "False", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    },
                    {
                        "id": "n2",
                        "class": "K2Node_CallFunction",
                        "title": "PrintString",
                        "comment": "",
                        "position": [700, 150],
                        "pins": [
                            {"id": "p6", "name": "", "direction": "input", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p7", "name": "InString", "direction": "input", "pin_type": "string", "default_value": "Hello", "is_exec": False},
                            {"id": "p8", "name": "", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    },
                    {
                        "id": "n3",
                        "class": "K2Node_CallFunction",
                        "title": "PrintString",
                        "comment": "",
                        "position": [700, 300],
                        "pins": [
                            {"id": "p9", "name": "", "direction": "input", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p10", "name": "InString", "direction": "input", "pin_type": "string", "default_value": "Not Found", "is_exec": False}
                        ]
                    }
                ],
                "edges": [
                    {"from_pin": "p0", "to_pin": "p2", "edge_type": "exec"},
                    {"from_pin": "p4", "to_pin": "p6", "edge_type": "exec"},
                    {"from_pin": "p5", "to_pin": "p9", "edge_type": "exec"}
                ]
            }
        ]
    }


def make_loop_blueprint():
    """带 ForEachLoop 的蓝图"""
    return {
        "schema_version": "v1",
        "asset_path": "/Game/BP_Loop",
        "parent_class": "Actor",
        "variables": [],
        "graphs": [
            {
                "name": "EventGraph",
                "graph_type": "ubergraph",
                "nodes": [
                    {
                        "id": "n0",
                        "class": "K2Node_Event",
                        "title": "Event BeginPlay",
                        "comment": "",
                        "position": [100, 200],
                        "pins": [
                            {"id": "p0", "name": "", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    },
                    {
                        "id": "n1",
                        "class": "K2Node_ForEachLoop",
                        "title": "ForEachLoop",
                        "comment": "",
                        "position": [400, 200],
                        "pins": [
                            {"id": "p1", "name": "", "direction": "input", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p2", "name": "Array", "direction": "input", "pin_type": "object", "default_value": "", "is_exec": False},
                            {"id": "p3", "name": "LoopBody", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p4", "name": "Completed", "direction": "output", "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    },
                    {
                        "id": "n2",
                        "class": "K2Node_CallFunction",
                        "title": "PrintString",
                        "comment": "",
                        "position": [700, 200],
                        "pins": [
                            {"id": "p5", "name": "", "direction": "input", "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    }
                ],
                "edges": [
                    {"from_pin": "p0", "to_pin": "p1", "edge_type": "exec"},
                    {"from_pin": "p3", "to_pin": "p5", "edge_type": "exec"}
                ]
            }
        ]
    }


# ============================================================================
# Tests
# ============================================================================

class TestPseudocode:
    def test_simple_blueprint(self):
        data = make_simple_blueprint()
        result = graph_to_pseudocode(data)

        assert "Event BeginPlay" in result
        assert "if" in result
        assert "PrintString" in result
        assert "Health" in result  # 变量声明
        assert "初始化" in result  # 注释

    def test_branch_structure(self):
        data = make_simple_blueprint()
        result = graph_to_pseudocode(data)

        # if/else 结构
        lines = result.split("\n")
        if_line = next(l for l in lines if l.strip().startswith("if"))
        assert if_line is not None

        # 应该有 else 分支
        assert "else:" in result

    def test_loop_blueprint(self):
        data = make_loop_blueprint()
        result = graph_to_pseudocode(data)

        assert "for item in" in result
        assert "PrintString" in result

    def test_variable_declaration(self):
        data = make_simple_blueprint()
        result = graph_to_pseudocode(data)

        assert "variables:" in result
        assert "float Health" in result
        assert "100.0" in result

    def test_empty_blueprint(self):
        data = {
            "schema_version": "v1",
            "asset_path": "/Game/BP_Empty",
            "graphs": []
        }
        result = graph_to_pseudocode(data)
        assert "blueprint /Game/BP_Empty" in result

    def test_comment_preserved(self):
        data = make_simple_blueprint()
        result = graph_to_pseudocode(data)
        assert "# 初始化" in result


class TestMermaid:
    def test_simple_mermaid(self):
        from graph_to_mermaid import graph_to_mermaid
        data = make_simple_blueprint()
        result = graph_to_mermaid(data)

        assert "flowchart TD" in result
        assert "EventGraph" in result


class TestGraphify:
    def test_simple_graphify(self):
        from graph_to_graphify import graph_to_graphify
        data = make_simple_blueprint()
        result = graph_to_graphify(data)

        assert "nodes" in result
        assert "edges" in result
        assert any(n["type"] == "blueprint" for n in result["nodes"])
        assert any(n["type"] == "variable" for n in result["nodes"])
