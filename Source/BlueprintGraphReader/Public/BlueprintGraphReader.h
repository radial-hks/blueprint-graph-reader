// Copyright 2025 radial-hks. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "BlueprintGraphReader.generated.h"

/**
 * Blueprint Graph Reader — 将蓝图图结构提取为 JSON 字符串，供 AI Agent 读取。
 *
 * 设计原则：
 * - 只读：不修改任何蓝图数据
 * - 最小接口：只暴露提取所需的核心函数
 * - Editor Only：只在编辑器模式下编译
 *
 * 图覆盖范围：
 * - UbergraphPages (EventGraph 等)
 * - FunctionGraphs (自定义函数，含 Construction Script)
 * - DelegateSignatureGraphs (委托签名图)
 *
 * 注意：SCS 组件模板和 Timeline 模板不作为独立 UEdGraph 存储，
 * Construction Script 作为函数图已在 FunctionGraphs 中捕获。
 */
UCLASS(meta=(ScriptName="BlueprintGraphReader"))
class BLUEPRINTGRAPHREADER_API UBlueprintGraphReader : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * 提取整个蓝图为 JSON 字符串（一步到位，推荐）。
     *
     * 输出 JSON 结构：
     * {
     *   "schema_version": "v1",
     *   "asset_path": "...",
     *   "blueprint_type": "...",
     *   "parent_class": "...",    // 始终输出，无父类时为 null
     *   "variables": [...],
     *   "graphs": [{
     *     "name": "EventGraph",
     *     "graph_type": "ubergraph",
     *     "nodes": [{ "id", "class", "title", "comment", "position", "pins": [...] }],
     *     "edges": [{ "from_pin", "to_pin", "edge_type" }]
     *   }]
     * }
     */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static FString ExtractBlueprintAsJson(UBlueprint* Blueprint);

    /** 获取蓝图的所有图名（EventGraph, 自定义函数图, 委托签名图等） */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetBlueprintGraphNames(UBlueprint* Blueprint);

    /** 获取图中所有节点 */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<UEdGraphNode*> GetGraphNodes(UEdGraph* Graph);

    /** 获取节点语义信息（类名、标题、注释），返回 JSON 字符串 */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static FString GetNodeSemanticInfo(UEdGraphNode* Node);

    /** 获取节点的 Pin 列表信息，每个 Pin 为一条 JSON 字符串 */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetNodePinInfo(UEdGraphNode* Node);

    /** 获取蓝图变量列表，每个变量为一条 JSON 字符串 */
    UFUNCTION(BlueprintCallable, Category = "BlueprintGraph")
    static TArray<FString> GetBlueprintVariables(UBlueprint* Blueprint);

private:
    /** 将单个 EdGraph 序列化为 FJsonObject */
    static TSharedPtr<FJsonObject> SerializeGraph(UEdGraph* Graph, int32& NodeIdCounter, int32& PinIdCounter);

    /** 将单个 EdGraphNode 序列化为 FJsonObject（通过 PinIdMap 查找 Pin ID） */
    static TSharedPtr<FJsonObject> SerializeNode(UEdGraphNode* Node, const FString& NodeId,
                                                 const TMap<UEdGraphPin*, FString>& PinIdMap);

    /** 将单个 EdGraphPin 序列化为 FJsonObject */
    static TSharedPtr<FJsonObject> SerializePin(UEdGraphPin* Pin, const FString& PinId);

    /** 提取边的连接关系，追加到 EdgesArray */
    static void ExtractEdges(UEdGraph* Graph, const TMap<UEdGraphPin*, FString>& PinIdMap,
                             TArray<TSharedPtr<FJsonValue>>& EdgesArray);

    /** 将 K2Node 子类名标准化（去掉 U/A 前缀和 _C 后缀） */
    static FString NormalizeNodeClassName(UClass* NodeClass);

    /** 判断 Pin 是否为 exec 类型 */
    static bool IsExecPin(UEdGraphPin* Pin);

    /** 获取 Pin 的数据类型字符串表示 */
    static FString GetPinTypeString(UEdGraphPin* Pin);

    /** 从 PinCategory FName 获取类型字符串（内部辅助） */
    static FString GetPinTypeStringFromCategory(const FName& Category);

    /** 节点标题最大长度（超过时截断并加省略号） */
    static constexpr int32 MaxTitleLength = 256;
};
