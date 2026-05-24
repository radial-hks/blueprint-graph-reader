"""Tests for semantic_enhancer — LLM-powered annotation and Q&A for blueprint graphs.

Tests that require LLM calls are mocked; offline logic is tested directly.
"""

import json
import os
import tempfile
import pytest

from graph_to_pseudocode import graph_to_pseudocode
from semantic_enhancer import (
    split_pseudocode_by_subgraph,
    _parse_summaries,
    _cache_key,
    _read_cache,
    _write_cache,
    enhance_pseudocode,
    extract_subgraph_context,
)


# ============================================================================
# Fixtures
# ============================================================================

def make_multi_graph_blueprint():
    """多图蓝图：EventGraph + TakeDamage 函数"""
    return {
        "schema_version": "v1",
        "asset_path": "/Game/BP_Enemy",
        "parent_class": "Actor",
        "variables": [
            {"name": "Health", "type": "float", "default_value": "100.0",
             "instance_editable": True, "expose_on_spawn": False}
        ],
        "graphs": [
            {
                "name": "EventGraph",
                "graph_type": "ubergraph",
                "nodes": [
                    {
                        "id": "n0", "class": "K2Node_Event",
                        "title": "Event BeginPlay", "comment": "初始化",
                        "position": [100, 200],
                        "pins": [
                            {"id": "p0", "name": "", "direction": "output",
                             "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    },
                    {
                        "id": "n1", "class": "K2Node_CallFunction",
                        "title": "PrintString", "comment": "",
                        "position": [400, 200],
                        "pins": [
                            {"id": "p1", "name": "", "direction": "input",
                             "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p2", "name": "InString", "direction": "input",
                             "pin_type": "string", "default_value": "Hello", "is_exec": False}
                        ]
                    }
                ],
                "edges": [
                    {"from_pin": "p0", "to_pin": "p1", "edge_type": "exec"}
                ]
            },
            {
                "name": "TakeDamage",
                "graph_type": "function",
                "nodes": [
                    {
                        "id": "n10", "class": "K2Node_FunctionEntry",
                        "title": "TakeDamage", "comment": "",
                        "position": [100, 100],
                        "pins": [
                            {"id": "p10", "name": "", "direction": "output",
                             "pin_type": "exec", "default_value": "", "is_exec": True},
                            {"id": "p11", "name": "Amount", "direction": "output",
                             "pin_type": "float", "default_value": "", "is_exec": False}
                        ]
                    },
                    {
                        "id": "n11", "class": "K2Node_ReturnNode",
                        "title": "Return", "comment": "",
                        "position": [400, 100],
                        "pins": [
                            {"id": "p12", "name": "", "direction": "input",
                             "pin_type": "exec", "default_value": "", "is_exec": True}
                        ]
                    }
                ],
                "edges": [
                    {"from_pin": "p10", "to_pin": "p12", "edge_type": "exec"}
                ]
            }
        ]
    }


# ============================================================================
# 伪代码分段测试
# ============================================================================

class TestSplitPseudocode:
    def test_splits_graph_sections(self):
        data = make_multi_graph_blueprint()
        pseudocode = graph_to_pseudocode(data)
        sections = split_pseudocode_by_subgraph(pseudocode)

        # 应该有: header (blueprint + variables) + EventGraph + TakeDamage
        graph_sections = [s for s in sections if s["type"] == "graph"]
        header_sections = [s for s in sections if s["type"] == "header"]

        assert len(graph_sections) >= 2, f"Expected >= 2 graph sections, got {len(graph_sections)}"
        assert len(header_sections) >= 1, "Expected at least 1 header section"

    def test_section_names(self):
        data = make_multi_graph_blueprint()
        pseudocode = graph_to_pseudocode(data)
        sections = split_pseudocode_by_subgraph(pseudocode)

        graph_names = [s["name"] for s in sections if s["type"] == "graph"]
        assert any("EventGraph" in n for n in graph_names), f"EventGraph not in {graph_names}"
        assert any("TakeDamage" in n for n in graph_names), f"TakeDamage not in {graph_names}"

    def test_section_code_not_empty(self):
        data = make_multi_graph_blueprint()
        pseudocode = graph_to_pseudocode(data)
        sections = split_pseudocode_by_subgraph(pseudocode)

        for s in sections:
            if s["type"] == "graph":
                assert s["code"].strip(), f"Section {s['name']} has empty code"

    def test_empty_blueprint(self):
        data = {"schema_version": "v1", "asset_path": "/Game/BP_Empty", "graphs": []}
        pseudocode = graph_to_pseudocode(data)
        sections = split_pseudocode_by_subgraph(pseudocode)
        # 应该只有 header
        assert all(s["type"] == "header" for s in sections)


# ============================================================================
# 摘要解析测试
# ============================================================================

class TestParseSummaries:
    def test_colon_format(self):
        raw = "EventGraph: 游戏开始时初始化\nTakeDamage: 扣减生命值"
        result = _parse_summaries(raw)
        assert result == {
            "EventGraph": "游戏开始时初始化",
            "TakeDamage": "扣减生命值",
        }

    def test_dash_prefix(self):
        raw = "- EventGraph: 初始化\n- TakeDamage: 扣减"
        result = _parse_summaries(raw)
        assert "EventGraph" in result
        assert "TakeDamage" in result

    def test_empty_input(self):
        assert _parse_summaries("") == {}
        assert _parse_summaries("\n\n") == {}

    def test_malformed_lines_skipped(self):
        raw = "EventGraph: 初始化\nno colon line\nTakeDamage: 扣减"
        result = _parse_summaries(raw)
        assert len(result) == 2


# ============================================================================
# 缓存测试
# ============================================================================

class TestCache:
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_cache.json")
            _write_cache(path, "hello world")
            assert _read_cache(path) == "hello world"

    def test_read_nonexistent(self):
        assert _read_cache("/nonexistent/path/cache.json") is None

    def test_read_corrupt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrupt.json")
            with open(path, "w") as f:
                f.write("not json{{{")
            assert _read_cache(path) is None

    def test_cache_key_deterministic(self):
        k1 = _cache_key("bp1", "graph1", "model1", "summary")
        k2 = _cache_key("bp1", "graph1", "model1", "summary")
        assert k1 == k2

    def test_cache_key_differs_for_different_inputs(self):
        k1 = _cache_key("bp1", "graph1", "model1", "summary")
        k2 = _cache_key("bp2", "graph1", "model1", "summary")
        assert k1 != k2


# ============================================================================
# 伪代码增强测试
# ============================================================================

class TestEnhancePseudocode:
    def test_summary_annotated(self):
        data = make_multi_graph_blueprint()
        summaries = {
            "graph EventGraph": "游戏开始时打印Hello",
            "function TakeDamage": "扣减生命值并返回",
        }
        enhanced = enhance_pseudocode(data, summaries=summaries)
        assert "# [摘要] 游戏开始时打印Hello" in enhanced
        assert "# [摘要] 扣减生命值并返回" in enhanced

    def test_original_pseudocode_preserved(self):
        data = make_multi_graph_blueprint()
        summaries = {"graph EventGraph": "摘要"}
        enhanced = enhance_pseudocode(data, summaries=summaries)
        # 原始内容应在
        assert "Event BeginPlay" in enhanced
        assert "PrintString" in enhanced

    def test_empty_summaries_no_change(self):
        data = make_multi_graph_blueprint()
        original = graph_to_pseudocode(data)
        enhanced = enhance_pseudocode(data, summaries={})
        assert enhanced == original

    def test_none_summaries_tries_llm_but_fails_gracefully(self):
        data = make_multi_graph_blueprint()
        # 无 API key 时应 fallback 到原始伪代码
        original = graph_to_pseudocode(data)
        enhanced = enhance_pseudocode(data, summaries=None, use_cache=False)
        # LLM 调用会失败，但不应崩溃
        assert "Event BeginPlay" in enhanced


# ============================================================================
# 子图提取测试
# ============================================================================

class TestExtractSubgraphContext:
    def test_full_extraction(self):
        data = make_multi_graph_blueprint()
        context = extract_subgraph_context(data)
        # 应包含所有图
        assert "EventGraph" in context or "Event BeginPlay" in context
        assert "TakeDamage" in context

    def test_targeted_extraction(self):
        data = make_multi_graph_blueprint()
        # 只提取 TakeDamage
        pseudocode = graph_to_pseudocode(data)
        sections = split_pseudocode_by_subgraph(pseudocode)
        graph_names = [s["name"] for s in sections if s["type"] == "graph"]
        take_damage_name = next(n for n in graph_names if "TakeDamage" in n)

        context = extract_subgraph_context(data, target_names=[take_damage_name])
        assert "TakeDamage" in context
        # 应包含 header（变量声明）
        assert "Health" in context

    def test_max_lines_truncation(self):
        data = make_multi_graph_blueprint()
        context = extract_subgraph_context(data, max_lines=5)
        lines = context.split("\n")
        # 截断后不应超过 max_lines 太多（header + truncated graph）
        assert len(lines) <= 20  # 宽松上限


# ============================================================================
# 集成测试：伪代码 → 分段 → 摘要注回
# ============================================================================

class TestIntegration:
    def test_full_pipeline_offline(self):
        """离线全流程：JSON → 伪代码 → 分段 → 人工摘要 → 增强伪代码"""
        data = make_multi_graph_blueprint()

        # 1. 生成伪代码
        pseudocode = graph_to_pseudocode(data)
        assert "Event BeginPlay" in pseudocode

        # 2. 分段
        sections = split_pseudocode_by_subgraph(pseudocode)
        graph_sections = [s for s in sections if s["type"] == "graph"]
        assert len(graph_sections) >= 2

        # 3. 人工摘要
        summaries = {s["name"]: f"摘要: {s['name']}" for s in graph_sections}

        # 4. 增强
        enhanced = enhance_pseudocode(data, summaries=summaries)
        assert "# [摘要]" in enhanced

        # 5. 子图提取
        context = extract_subgraph_context(data, target_names=[graph_sections[0]["name"]])
        assert graph_sections[0]["name"].split("(")[0].strip() in context or "Event" in context
