// Copyright 2025 radial-hks. All Rights Reserved.

#include "BlueprintGraphReader.h"
#include "BlueprintGraphReaderModule.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "K2Node.h"
#include "Kismet/EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/TimelineTemplate.h"
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

    // Parent class — 始终输出，无父类时为空字符串
    RootJson->SetStringField("parent_class",
        Blueprint->ParentClass ? Blueprint->ParentClass->GetName() : FString());

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
            TypeStr = GetPinTypeStringFromCategory(Var.VarType.PinCategory);
        }
        VarObj->SetStringField("type", TypeStr);

        // Default value
        VarObj->SetStringField("default_value", Var.DefaultValue);

        // Flags
        VarObj->SetBoolField("instance_editable",
            (Var.PropertyFlags & CPF_Edit) != 0);
        VarObj->SetBoolField("expose_on_spawn",
            (Var.PropertyFlags & CPF_ExposeOnSpawn) != 0);

        VarsArray.Add(MakeShared<FJsonValueObject>(VarObj));
    }
    RootJson->SetArrayField("variables", VarsArray);

    // Graphs - Ubergraph pages (EventGraph 等)
    int32 NodeIdCounter = 0;
    int32 PinIdCounter = 0;
    TArray<TSharedPtr<FJsonValue>> GraphsArray;

    for (UEdGraph* Graph : Blueprint->UbergraphPages)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter, PinIdCounter);
            GraphObj->SetStringField("graph_type", "ubergraph");
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    // Function graphs (includes Construction Script)
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter, PinIdCounter);
            // 标记 Construction Script
            FString GraphType = (Graph->GetName() == TEXT("ConstructionScript"))
                ? TEXT("construction_script") : TEXT("function");
            GraphObj->SetStringField("graph_type", GraphType);
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    // Delegate signature graphs
    for (UEdGraph* Graph : Blueprint->DelegateSignatureGraphs)
    {
        if (Graph)
        {
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter, PinIdCounter);
            GraphObj->SetStringField("graph_type", "delegate_signature");
            GraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
    }

    // Macro graphs — 复用 SerializeGraph
    if (Blueprint->MacroGraphs.Num() > 0)
    {
        TArray<TSharedPtr<FJsonValue>> MacroArray;
        for (UEdGraph* Graph : Blueprint->MacroGraphs)
        {
            if (!Graph) continue;
            TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Graph, NodeIdCounter, PinIdCounter);
            GraphObj->SetStringField("graph_type", "macro");
            MacroArray.Add(MakeShared<FJsonValueObject>(GraphObj));
        }
        RootJson->SetArrayField("macro_graphs", MacroArray);
    }

    RootJson->SetArrayField("graphs", GraphsArray);

    // SCS components — 组件树
    if (Blueprint->SimpleConstructionScript)
    {
        TArray<TSharedPtr<FJsonValue>> ComponentsArray;
        for (USCS_Node* SCSNode : Blueprint->SimpleConstructionScript->GetAllNodes())
        {
            if (!SCSNode) continue;
            TSharedPtr<FJsonObject> CompObj = MakeShared<FJsonObject>();
            CompObj->SetStringField("class",
                SCSNode->ComponentClass ? SCSNode->ComponentClass->GetName() : FString());
            CompObj->SetStringField("name", SCSNode->GetVariableName().ToString());
            if (SCSNode->ComponentTemplate)
            {
                CompObj->SetStringField("template_name", SCSNode->ComponentTemplate->GetName());
            }
            CompObj->SetNumberField("child_index", SCSNode->ChildIndex);
            ComponentsArray.Add(MakeShared<FJsonValueObject>(CompObj));
        }
        RootJson->SetArrayField("components", ComponentsArray);
    }

    // Timelines
    {
        TArray<TSharedPtr<FJsonValue>> TimelinesArray;
        for (UTimelineTemplate* TL : Blueprint->Timelines)
        {
            if (!TL) continue;
            TSharedPtr<FJsonObject> TLObj = MakeShared<FJsonObject>();
            TLObj->SetStringField("name", TL->GetName());
            TLObj->SetBoolField("loop", TL->bLoop);
            TLObj->SetNumberField("length", TL->TimelineLength);
            TimelinesArray.Add(MakeShared<FJsonValueObject>(TLObj));
        }
        if (TimelinesArray.Num() > 0)
        {
            RootJson->SetArrayField("timelines", TimelinesArray);
        }
    }

    // Implemented interfaces
    {
        TArray<TSharedPtr<FJsonValue>> InterfacesArray;
        for (const FBPInterfaceDescription& II : Blueprint->ImplementedInterfaces)
        {
            if (!II.Interface) continue;
            TSharedPtr<FJsonObject> IObj = MakeShared<FJsonObject>();
            IObj->SetStringField("name", II.Interface->GetName());
            IObj->SetNumberField("graph_count", II.Graphs.Num());
            InterfacesArray.Add(MakeShared<FJsonValueObject>(IObj));
        }
        if (InterfacesArray.Num() > 0)
        {
            RootJson->SetArrayField("interfaces", InterfacesArray);
        }
    }

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

    // 截断过长标题
    FString Title = Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString();
    if (Title.Len() > MaxTitleLength)
    {
        Title = Title.Left(MaxTitleLength - 3) + TEXT("...");
    }
    Obj->SetStringField("title", Title);

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
                : GetPinTypeStringFromCategory(Var.VarType.PinCategory));
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

TSharedPtr<FJsonObject> UBlueprintGraphReader::SerializeGraph(UEdGraph* Graph, int32& NodeIdCounter, int32& PinIdCounter)
{
    TSharedPtr<FJsonObject> GraphObj = MakeShared<FJsonObject>();
    GraphObj->SetStringField("name", Graph->GetName());

    // Phase 1: 先构建 PinIdMap — Pin 指针 → 唯一序号 ID
    TMap<UEdGraphPin*, FString> PinIdMap;

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;

        // 注意: hidden pin 也加入 PinIdMap, 以便 edge 提取时能解析 LinkedTo 指针
        // (如 self pin 常为 hidden, 但仍可能是 edge endpoint)
        // SerializePin 阶段仍跳过 hidden pin, 保持 JSON 精简
        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (!Pin) continue;
            FString PinId = FString::Printf(TEXT("p%d"), PinIdCounter);
            PinIdMap.Add(Pin, PinId);
            PinIdCounter++;
        }
    }

    // Phase 2: 序列化节点（通过 PinIdMap 查找 Pin ID）
    TArray<TSharedPtr<FJsonValue>> NodesArray;
    TArray<TSharedPtr<FJsonValue>> EdgesArray;

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;

        FString NodeId = FString::Printf(TEXT("n%d"), NodeIdCounter);
        TSharedPtr<FJsonObject> NodeObj = SerializeNode(Node, NodeId, PinIdMap);
        NodesArray.Add(MakeShared<FJsonValueObject>(NodeObj));

        NodeIdCounter++;
    }

    // Phase 3: 边提取
    ExtractEdges(Graph, PinIdMap, EdgesArray);

    GraphObj->SetArrayField("nodes", NodesArray);
    GraphObj->SetArrayField("edges", EdgesArray);

    return GraphObj;
}

TSharedPtr<FJsonObject> UBlueprintGraphReader::SerializeNode(UEdGraphNode* Node, const FString& NodeId,
                                                              const TMap<UEdGraphPin*, FString>& PinIdMap)
{
    TSharedPtr<FJsonObject> NodeObj = MakeShared<FJsonObject>();
    NodeObj->SetStringField("id", NodeId);
    NodeObj->SetStringField("class", NormalizeNodeClassName(Node->GetClass()));

    // 截断过长标题
    FString Title = Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString();
    if (Title.Len() > MaxTitleLength)
    {
        Title = Title.Left(MaxTitleLength - 3) + TEXT("...");
    }
    NodeObj->SetStringField("title", Title);

    NodeObj->SetStringField("comment", Node->NodeComment);

    // Position
    TArray<TSharedPtr<FJsonValue>> Position;
    Position.Add(MakeShared<FJsonValueNumber>(Node->NodePosX));
    Position.Add(MakeShared<FJsonValueNumber>(Node->NodePosY));
    NodeObj->SetArrayField("position", Position);

    // Pins — 从 PinIdMap 查找统一 ID
    TArray<TSharedPtr<FJsonValue>> PinsArray;
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin || Pin->bHidden) continue;

        const FString* PinIdPtr = PinIdMap.Find(Pin);
        FString PinId = PinIdPtr ? *PinIdPtr : FString();
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
    // 用 TPair<UEdGraphPin*, UEdGraphPin*> 去重，避免字符串拼接歧义
    TSet<TPair<UEdGraphPin*, UEdGraphPin*>> AddedEdges;

    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;

        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (!Pin) continue;
            if (Pin->Direction != EGPD_Output) continue; // 只从 output pin 出发
            // 注意: 不跳过 hidden pin — hidden pin 可能是合法 edge endpoint (如 self pin)

            FString* FromPinId = PinIdMap.Find(Pin);
            if (!FromPinId) continue;

            for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
            {
                if (!LinkedPin) continue;

                FString* ToPinId = PinIdMap.Find(LinkedPin);
                if (!ToPinId) continue;

                // 去重：用指针对而非字符串拼接
                TPair<UEdGraphPin*, UEdGraphPin*> EdgeKey(Pin, LinkedPin);
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

    // 移除 UE 标准前缀: U → 如果第二个字符是大写
    // 常见模式: UK2Node_Event → K2Node_Event, UEdGraphNode → EdGraphNode
    // 但 K2Node_*, EdGraphNode_*, AnimGraphNode_* 本身不以 U 开头
    if (ClassName.Len() > 1 && FChar::IsUpper(ClassName[0]) && FChar::IsUpper(ClassName[1]))
    {
        // UA/UF 等 double-uppercase 前缀 → 移除首字母
        // 这覆盖了 U 前缀 + 大写类名的所有情况
        ClassName.RemoveAt(0);
    }

    // 移除 _C 后缀（蓝图生成的类）
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
    return GetPinTypeStringFromCategory(Pin->PinType.PinCategory);
}

FString UBlueprintGraphReader::GetPinTypeStringFromCategory(const FName& Category)
{
    // 使用 UEdGraphSchema_K2 常量匹配，替代硬编码字符串
    const FString CategoryStr = Category.ToString();

    if (Category == UEdGraphSchema_K2::PC_Exec)        return "exec";
    if (Category == UEdGraphSchema_K2::PC_Boolean)     return "bool";
    if (Category == UEdGraphSchema_K2::PC_Byte)         return "byte";
    if (Category == UEdGraphSchema_K2::PC_Int)         return "int";
    if (Category == UEdGraphSchema_K2::PC_Int64)       return "int64";
    if (Category == UEdGraphSchema_K2::PC_Float)       return "float";
    if (Category == UEdGraphSchema_K2::PC_Double)      return "double";
    if (Category == UEdGraphSchema_K2::PC_String)      return "string";
    if (Category == UEdGraphSchema_K2::PC_Text)         return "text";
    if (Category == UEdGraphSchema_K2::PC_Name)        return "name";
    if (Category == UEdGraphSchema_K2::PC_Struct)      return "struct";
    if (Category == UEdGraphSchema_K2::PC_Object)      return "object";
    if (Category == UEdGraphSchema_K2::PC_Class)       return "class";
    if (Category == UEdGraphSchema_K2::PC_SoftObject)  return "soft_object";
    if (Category == UEdGraphSchema_K2::PC_SoftClass)   return "soft_class";
    if (Category == UEdGraphSchema_K2::PC_Delegate)     return "delegate";
    if (Category == UEdGraphSchema_K2::PC_Interface)    return "interface";
    if (Category == UEdGraphSchema_K2::PC_Wildcard)    return "wildcard";

    // UE 还有一些常用类别不在标准常量中，用字符串匹配
    if (CategoryStr == "vector")        return "vector";
    if (CategoryStr == "rotator")       return "rotator";
    if (CategoryStr == "transform")     return "transform";
    if (CategoryStr == "enum")          return "enum";
    if (CategoryStr == "map")           return "map";
    if (CategoryStr == "set")           return "set";

    return CategoryStr; // fallback: 返回原始类别名
}

#undef LOCTEXT_NAMESPACE
