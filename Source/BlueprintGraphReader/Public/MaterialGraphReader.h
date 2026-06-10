// Copyright 2025 radial-hks. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "Materials/MaterialInterface.h"
#include "MaterialGraphReader.generated.h"

class UMaterial;
class UMaterialFunction;
class UMaterialExpression;
class UMaterialExpressionComment;
class UMaterialExpressionTextureSample;
class UMaterialInstanceConstant;

/**
 * Material Graph Reader — 将材质节点图结构提取为 JSON 字符串，供 AI Agent 读取。
 *
 * 设计原则：
 * - 只读：不修改任何材质数据
 * - 最小接口：只暴露提取所需的核心函数
 * - Editor Only：只在编辑器模式下编译
 * - 不依赖 UMaterialGraph（编辑器瞬时重建层），直接读 ExpressionCollection
 *
 * 数据覆盖范围：
 * - UMaterial 表达式图（ExpressionCollection）
 * - UMaterialFunction 内嵌表达式
 * - UMaterialInstanceConstant（追溯到父材质表达式）
 * - 材质属性连接（BaseColor, Metallic, Roughness 等）
 * - 材质注释节点
 *
 * JSON Schema (material-v1):
 * - ID 前缀：e0, e1, e2...（expression IDs）
 * - 边模型：input.connected_to = expression_id（内联，无独立 edges 数组）
 * - outputs 为名称列表（被动连接端，无 ID）
 */
UCLASS(meta=(ScriptName="MaterialGraphReader"))
class BLUEPRINTGRAPHREADER_API UMaterialGraphReader : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * 提取 UMaterialInterface（Material / MaterialInstance）为 JSON 字符串。
     *
     * 输出 JSON 结构：
     * {
     *   "schema_version": "material-v1",
     *   "asset_path": "...",
     *   "material_type": "Material | MaterialFunction | MaterialInstanceConstant",
     *   "shading_model": "...",
     *   "blend_mode": "...",
     *   "properties": { "BaseColor": {"connected_to": "e5", ...}, ... },
     *   "expressions": [{ "id": "e0", "class": "...", "title": "...", ... }],
     *   "comments": [{ "text": "...", "position": [...], "size": [...] }]
     * }
     */
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString ExtractMaterialAsJson(UMaterialInterface* MaterialInterface);

    /**
     * 提取 UMaterialFunction 为 JSON 字符串（内嵌表达式图）。
     */
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString ExtractMaterialFunctionAsJson(UMaterialFunction* Func);

    /**
     * 获取单个 UMaterialExpression 的语义信息，返回 JSON 字符串。
     * 适用于交互式查询场景。
     */
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString GetExpressionInfo(UMaterialExpression* Expr);

    /**
     * 获取材质的属性连接信息（BaseColor, Metallic, Roughness 等），返回 JSON 字符串。
     * 仅适用于 UMaterial（非 MaterialInstance）。
     */
    UFUNCTION(BlueprintCallable, Category = "MaterialGraph")
    static FString GetMaterialPropertyConnections(UMaterial* Material);

private:
    /** 序列化 ExpressionCollection 表达式数组为 JSON 数组 */
    static TArray<TSharedPtr<FJsonValue>> SerializeExpressionCollection(
        const TArray<UMaterialExpression*>& Expressions,
        TMap<UMaterialExpression*, FString>& ExprIdMap);

    /** 序列化单个 UMaterialExpression 为 FJsonObject */
    static TSharedPtr<FJsonObject> SerializeExpression(
        UMaterialExpression* Expr,
        const FString& ExprId,
        const TMap<UMaterialExpression*, FString>& ExprIdMap);

    /** 序列化材质属性连接（BaseColor, Normal 等 EMaterialProperty 通道） */
    static TSharedPtr<FJsonObject> SerializeMaterialProperties(
        UMaterial* Material,
        const TMap<UMaterialExpression*, FString>& ExprIdMap);

    /** 序列化材质注释节点 */
    static TArray<TSharedPtr<FJsonValue>> SerializeComments(
        const TArray<UMaterialExpressionComment*>& Comments);

    /** 序列化材质实例参数覆盖 */
    static TSharedPtr<FJsonObject> SerializeMaterialInstanceParameterOverrides(
        UMaterialInstanceConstant* Instance);

    /** 将 UMaterialExpression 类名标准化（去掉 UMaterialExpression 前缀） */
    static FString GetExpressionClassName(UMaterialExpression* Expr);

    /** 获取 expression 显示标题（截断到 MaxTitleLength） */
    static FString GetExpressionTitle(UMaterialExpression* Expr);

    /** 为常见表达式类型提取额外 properties 字段 */
    static TSharedPtr<FJsonObject> SerializeExpressionProperties(UMaterialExpression* Expr);

    /** 提取 TextureSample 公共属性 */
    static TSharedPtr<FJsonObject> SerializeTextureSampleProperties(
        UMaterialExpressionTextureSample* TexSample,
        const FName* ParameterName = nullptr,
        const FName* Group = nullptr);

    /** ESamplerSourceMode 枚举值 → 字符串 */
    static FString GetSamplerSourceName(int64 SamplerSource);

    /** 表达式标题最大长度（超过时截断并加省略号） */
    static constexpr int32 MaxTitleLength = 256;

    /** Custom 节点 HLSL 代码截断长度 */
    static constexpr int32 MaxCodeLength = 2048;

    /** Comment 文本截断长度 */
    static constexpr int32 MaxCommentLength = 2048;
};
