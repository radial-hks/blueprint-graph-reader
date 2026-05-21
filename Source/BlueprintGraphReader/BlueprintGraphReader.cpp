// Copyright 2025 radial-hks. All Rights Reserved.

#include "BlueprintGraphReader.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "K2Node.h"
#include "Engine/Blueprint.h"
#include "UObject/UnrealType.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

#define LOCTEXT_NAMESPACE "FBlueprintGraphReaderModule"

// ============================================================================
// 公开接口
// ============================================================================

FString UBlueprintGraphReader::ExtractBlueprintAsJson(UBlueprint* Blueprint)
{
    if (!Blueprint)
    {
        return "{}";
    }

    TSharedPtr<FJsonObject> RootJson = MakeShared<FJsonObject>();
    RootJson->SetStringField("schema_version", "v1");
    RootJson->SetStringField("asset_path", Blueprint->GetPathName());

    // Blueprint type
    RootJson->SetStringField("blueprint_type",
        StaticEnum<EBPType>()->GetNameStringByValue(static_cast<int64>(Blueprint->BlueprintType)));

    // Parent class
    if (Blueprint->ParentClass)
    {
        RootJson->SetStringField("parent_class", Blueprint->ParentClass->GetName());
    }

    // Variables
    TArray<TSharedPtr<FJsonValue>> VarsArray;
    for (const FBPVariableDescription& Var : Blueprint->NewVariables)
    {
        TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
        VarObj->SetStringField("name", Var.VarName.ToString());

        // Pin type string
        FString TypeStr;
        if (Var.VarType.PinSubCategoryObject.IsValid())
        {
            TypeStr = Var.VarType.PinSubCategoryObject->GetName();
        }
        else
        {
            TypeStr = Var.VarType.PinCategory.ToString();
        }
        VarObj->SetStringField("type", TypeStr);

        // Default value
        VarObj->SetStringField("default_value", Var.DefaultValue);

        // Flags
        VarObj->SetBoolField("instance_editable",
            Var.PropertyFlags & CPF_Edit);
        VarObj->SetBoolField("expose_on_spawn",
            Var.PropertyFlags & CPF_ExposeOnSpawn);

        VarsArray.Add(MakeShared<FJsonValueObject>(VarObj));
    }
    RootJson->SetArrayField("variables", VarsArray);

    // Graphs - Ubergraph pages (EventGraph 等)
    int32 NodeIdCounter = 0;
    TArray<TSharedPtr<FJsonValue>> GraphsArray;

    for (UEdGraph* Graph : Blueprint->UbergraphPages)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter);
            GraphObj->SetStringField("graph_type", "ubergraph");
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    // Function graphs
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter);
            GraphObj->SetStringField("graph_type", "function");
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    // Macro graphs (delegated graphs)
    for (UEdGraph* Graph : Blueprint->DelegateSignatureGraphs)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter);
            GraphObj->SetStringField("graph_type", "delegate_signature");
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    RootJson->SetArrayField("graphs", GraphsArray);

    // Serialize to string
    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(RootJson.ToSharedRef(), Writer);
    return Output;
}

TArray<FString> UBlueprintGraphReader::GetBlueprintGraphNames(UBlueprint* Blueprint)
{
    TArray<FString> Names;
    if (!Blueprint) return Names;

    for (UEdGraph* Graph : Blueprint->UbergraphPages)
    {
        if (Graph) Names.Add(Graph->GetName());
    }
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (Graph) Names.Add(Graph->GetName());
    }
    for (UEdGraph* Graph : Blueprint->DelegateSignatureGraphs)
    {
        if (Graph) Names.Add(Graph->GetName());
    }
    return Names;
}

TArray<UEdGraphNode*> UBlueprintGraphReader::GetGraphNodes(UEdGraph* Graph)
{
    TArray<UEdGraphNode*> Nodes;
    if (!Graph) return Nodes;

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (Node) Nodes.Add(Node);
    }
    return Nodes;
}

FString UBlueprintGraphReader::GetNodeSemanticInfo(UEdGraphNode* Node)
{
    if (!Node) return "{}";

    TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
    Obj->SetStringField("class", NormalizeNodeClassName(Node->GetClass()));
    Obj->SetStringField("title", Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
    Obj->SetStringField("comment", Node->NodeComment);
    Obj->SetNumberField("pos_x", Node->NodePosX);
    Obj->SetNumberField("pos_y", Node->NodePosY);

    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), Writer);
    return Output;
}

TArray<FString> UBlueprintGraphReader::GetNodePinInfo(UEdGraphNode* Node)
{
    TArray<FString> PinInfos;
    if (!Node) return PinInfos;

    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin) continue;
        if (Pin->bHidden) continue; // 跳过隐藏 Pin

        TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
        PinObj->SetStringField("name", Pin->PinName.ToString());
        PinObj->SetStringField("direction",
            Pin->Direction == EGPD_Input ? "input" : "output");
        PinObj->SetStringField("pin_type", GetPinTypeString(Pin));
        PinObj->SetStringField("default_value", Pin->DefaultValue);
        PinObj->SetBoolField("is_exec", IsExecPin(Pin));

        FString Output;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(PinObj.ToSharedRef(), Writer);
        PinInfos.Add(Output);
    }
    return PinInfos;
}

TArray<FString> UBlueprintGraphReader::GetBlueprintVariables(UBlueprint* Blueprint)
{
    TArray<FString> VarInfos;
    if (!Blueprint) return VarInfos;

    for (const FBPVariableDescription& Var : Blueprint->NewVariables)
    {
        TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
        VarObj->SetStringField("name", Var.VarName.ToString());
        VarObj->SetStringField("type",
            Var.VarType.PinSubCategoryObject.IsValid()
                ? Var.VarType.PinSubCategoryObject->GetName()
                : Var.VarType.PinCategory.ToString());
        VarObj->SetStringField("default_value", Var.DefaultValue);
        VarObj->SetBoolField("instance_editable",
            (Var.PropertyFlags & CPF_Edit) != 0);
        VarObj->SetBoolField("expose_on_spawn",
            (Var.PropertyFlags & CPF_ExposeOnSpawn) != 0);

        FString Output;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(VarObj.ToSharedRef(), Writer);
        VarInfos.Add(Output);
    }
    return VarInfos;
}

// ============================================================================
// 内部序列化
// ============================================================================

TSharedPtr<FJsonObject> UBlueprintGraphReader::SerializeGraph(UEdGraph* Graph, int32 StartNodeId)
{
    TSharedPtr<FJsonObject> GraphObj = MakeShared<FJsonObject>();
    GraphObj->SetStringField("name", Graph->GetName());

    // 节点序列化
    TMap<UEdGraphPin*, FString> PinIdMap;  // Pin → 全局唯一 Pin ID
    TArray<TSharedPtr<FJsonValue>> NodesArray;
    TArray<TSharedPtr<FJsonValue>> EdgesArray;

    int32 NodeIdx = StartNodeId;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;

        FString NodeId = FString::Printf(TEXT("n%d"), NodeIdx);
        TSharedPtr<FJsonObject> NodeObj = SerializeNode(Node, NodeId);
        NodesArray.Add(MakeShared<FJsonValueObject>(NodeObj));

        // 注册所有 Pin 到 ID 映射
        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (!Pin || Pin->bHidden) continue;
            FString PinId = FString::Printf(TEXT("n%d_%s"), NodeIdx, *Pin->PinName.ToString());
            PinIdMap.Add(Pin, PinId);
        }

        NodeIdx++;
    }

    // 边提取
    ExtractEdges(Graph, PinIdMap, EdgesArray);

    GraphObj->SetArrayField("nodes", NodesArray);
    GraphObj->SetArrayField("edges", EdgesArray);

    return GraphObj;
}

TSharedPtr<FJsonObject> UBlueprintGraphReader::SerializeNode(UEdGraphNode* Node, const FString& NodeId)
{
    TSharedPtr<FJsonObject> NodeObj = MakeShared<FJsonObject>();
    NodeObj->SetStringField("id", NodeId);
    NodeObj->SetStringField("class", NormalizeNodeClassName(Node->GetClass()));
    NodeObj->SetStringField("title", Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
    NodeObj->SetStringField("comment", Node->NodeComment);

    // Position
    TArray<TSharedPtr<FJsonValue>> Position;
    Position.Add(MakeShared<FJsonValueNumber>(Node->NodePosX));
    Position.Add(MakeShared<FJsonValueNumber>(Node->NodePosY));
    NodeObj->SetArrayField("position", Position);

    // Pins
    TArray<TSharedPtr<FJsonValue>> PinsArray;
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin || Pin->bHidden) continue;

        FString PinId = FString::Printf(TEXT("%s_%s"), *NodeId, *Pin->PinName.ToString());
        TSharedPtr<FJsonObject> PinObj = SerializePin(Pin, PinId);
        PinsArray.Add(MakeShared<FJsonValueObject>(PinObj));
    }
    NodeObj->SetArrayField("pins", PinsArray);

    return NodeObj;
}

TSharedPtr<FJsonObject> UBlueprintGraphReader::SerializePin(UEdGraphPin* Pin, const FString& PinId)
{
    TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
    PinObj->SetStringField("id", PinId);
    PinObj->SetStringField("name", Pin->PinName.ToString());
    PinObj->SetStringField("direction",
        Pin->Direction == EGPD_Input ? "input" : "output");
    PinObj->SetStringField("pin_type", GetPinTypeString(Pin));

    // Sub type (具体类型，如 Actor, FVector 等)
    if (Pin->PinType.PinSubCategoryObject.IsValid())
    {
        PinObj->SetStringField("sub_type",
            Pin->PinType.PinSubCategoryObject->GetName());
    }

    PinObj->SetStringField("default_value", Pin->DefaultValue);
    PinObj->SetBoolField("is_exec", IsExecPin(Pin));

    return PinObj;
}

void UBlueprintGraphReader::ExtractEdges(UEdGraph* Graph,
    const TMap<UEdGraphPin*, FString>& PinIdMap,
    TArray<TSharedPtr<FJsonValue>>& EdgesArray)
{
    TSet<FString> AddedEdges; // 去重

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;

        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (!Pin || Pin->bHidden) continue;
            if (Pin->Direction != EGPD_Output) continue; // 只从 output pin 出发

            FString* FromPinId = PinIdMap.Find(Pin);
            if (!FromPinId) continue;

            for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
            {
                if (!LinkedPin) continue;

                FString* ToPinId = PinIdMap.Find(LinkedPin);
                if (!ToPinId) continue;

                // 去重 key
                FString EdgeKey = *FromPinId + "->" + *ToPinId;
                if (AddedEdges.Contains(EdgeKey)) continue;
                AddedEdges.Add(EdgeKey);

                TSharedPtr<FJsonObject> EdgeObj = MakeShared<FJsonObject>();
                EdgeObj->SetStringField("from_pin", *FromPinId);
                EdgeObj->SetStringField("to_pin", *ToPinId);
                EdgeObj->SetStringField("edge_type",
                    IsExecPin(Pin) ? "exec" : "data");

                EdgesArray.Add(MakeShared<FJsonValueObject>(EdgeObj));
            }
        }
    }
}

// ============================================================================
// 工具函数
// ============================================================================

FString UBlueprintGraphReader::NormalizeNodeClassName(UClass* NodeClass)
{
    if (!NodeClass) return "Unknown";

    FString ClassName = NodeClass->GetName();

    // 移除常见的 UE 前缀: UK2Node_ → K2Node_, UEdGraphNode_ → EdGraphNode_
    if (ClassName.StartsWith("U") && ClassName.Len() > 1 && FChar::IsUpper(ClassName[1]))
    {
        // 检查是否是 UE 标准前缀
        if (ClassName.StartsWith("K2Node_") ||
            ClassName.StartsWith("EdGraphNode_") ||
            ClassName.StartsWith("AnimGraphNode_"))
        {
            // 这些类名不以 U 开头，直接返回
            return ClassName;
        }
        ClassName.RemoveAt(0); // 移除 U 前缀
    }

    // 移除 _C 后缀（如果有的话）
    if (ClassName.EndsWith("_C"))
    {
        ClassName.LeftChopInline(2);
    }

    return ClassName;
}

bool UBlueprintGraphReader::IsExecPin(UEdGraphPin* Pin)
{
    if (!Pin) return false;
    return Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Exec;
}

FString UBlueprintGraphReader::GetPinTypeString(UEdGraphPin* Pin)
{
    if (!Pin) return "unknown";

    const FString& Category = Pin->PinType.PinCategory.ToString();

    // 标准类别映射
    if (Category == "exec")          return "exec";
    if (Category == "bool")          return "bool";
    if (Category == "byte")          return "byte";
    if (Category == "int")           return "int";
    if (Category == "int64")         return "int64";
    if (Category == "float")         return "float";
    if (Category == "double")        return "double";
    if (Category == "string")        return "string";
    if (Category == "text")          return "text";
    if (Category == "name")          return "name";
    if (Category == "vector")        return "vector";
    if (Category == "rotator")       return "rotator";
    if (Category == "transform")     return "transform";
    if (Category == "object")        return "object";
    if (Category == "class")         return "class";
    if (Category == "struct")        return "struct";
    if (Category == "enum")          return "enum";
    if (Category == "delegate")      return "delegate";
    if (Category == "interface")     return "interface";
    if (Category == "softobject")    return "soft_object";
    if (Category == "softclass")     return "soft_class";
    if (Category == "wildcard")      return "wildcard";

    return Category; // fallback: 返回原始类别名
}

#undef LOCTEXT_NAMESPACE
