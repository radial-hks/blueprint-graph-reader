// Copyright 2025 radial-hks. All Rights Reserved.

#include "MaterialGraphReader.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Materials/MaterialExpressionComment.h"
#include "Materials/MaterialExpressionIO.h"
#include "Materials/MaterialExpressionScalarParameter.h"
#include "Materials/MaterialExpressionVectorParameter.h"
#include "Materials/MaterialExpressionTextureSample.h"
#include "Materials/MaterialExpressionTextureSampleParameter2D.h"
#include "Materials/MaterialExpressionMaterialFunctionCall.h"
#include "Materials/MaterialExpressionCustom.h"
#include "Materials/MaterialExpressionConstant.h"
#include "Materials/MaterialExpressionStaticSwitch.h"
#include "Materials/MaterialExpressionStaticBool.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Materials/MaterialFunction.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

#define LOCTEXT_NAMESPACE "FMaterialGraphReaderModule"

// ============================================================================
// Public API
// ============================================================================

FString UMaterialGraphReader::ExtractMaterialAsJson(UMaterialInterface* MaterialInterface)
{
    if (!MaterialInterface)
    {
        return "{}";
    }

    TSharedPtr<FJsonObject> RootJson = MakeShared<FJsonObject>();
    RootJson->SetStringField("schema_version", "material-v1");
    RootJson->SetStringField("asset_path", MaterialInterface->GetPathName());

    // Determine material type string
    FString MaterialType;
    if (MaterialInterface->IsA(UMaterialInstanceConstant::StaticClass()))
    {
        MaterialType = "MaterialInstanceConstant";
    }
    else if (MaterialInterface->IsA(UMaterial::StaticClass()))
    {
        MaterialType = "Material";
    }
    else
    {
        MaterialType = MaterialInterface->GetClass()->GetName();
    }
    RootJson->SetStringField("material_type", MaterialType);

    // Resolve to concrete UMaterial for expression access
    UMaterial* ConcreteMaterial = MaterialInterface->GetMaterial();
    if (!ConcreteMaterial)
    {
        // Return minimal JSON if we can't resolve the material
        FString Output;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(RootJson.ToSharedRef(), Writer);
        return Output;
    }

    // Shading model & blend mode (from concrete material)
    RootJson->SetStringField("shading_model",
        StaticEnum<EMaterialShadingModel>()->GetNameStringByValue(
            static_cast<int64>(ConcreteMaterial->ShadingModel)));
    RootJson->SetStringField("blend_mode",
        StaticEnum<EBlendMode>()->GetNameStringByValue(
            static_cast<int64>(ConcreteMaterial->BlendMode)));

    // Two-sided flag
    RootJson->SetBoolField("two_sided", ConcreteMaterial->TwoSided);

    // Build expression ID map (expression pointer → "e0", "e1", ...)
    TMap<UMaterialExpression*, FString> ExprIdMap;

    // Phase 1: Assign IDs to all expressions (skip comments — they go to comments[])
    TArray<UMaterialExpression*> SerializableExpressions;
    TArray<UMaterialExpressionComment*> Comments;

    for (UMaterialExpression* Expr : ConcreteMaterial->ExpressionCollection.Expressions)
    {
        if (!Expr) continue;

        UMaterialExpressionComment* Comment = Cast<UMaterialExpressionComment>(Expr);
        if (Comment)
        {
            Comments.Add(Comment);
            continue;
        }

        FString ExprId = FString::Printf(TEXT("e%d"), ExprIdMap.Num());
        ExprIdMap.Add(Expr, ExprId);
        SerializableExpressions.Add(Expr);
    }

    // Phase 2: Serialize expressions
    TArray<TSharedPtr<FJsonValue>> ExprArray = SerializeExpressionCollection(
        SerializableExpressions, ExprIdMap);
    RootJson->SetArrayField("expressions", ExprArray);

    // Phase 3: Serialize material property connections (BaseColor, Metallic, etc.)
    if (ConcreteMaterial->IsA(UMaterial::StaticClass()))
    {
        TSharedPtr<FJsonObject> PropsObj = SerializeMaterialProperties(ConcreteMaterial, ExprIdMap);
        RootJson->SetObjectField("properties", PropsObj);
    }

    // Phase 4: Serialize comments
    if (Comments.Num() > 0)
    {
        TArray<TSharedPtr<FJsonValue>> CommentsArray;
        for (UMaterialExpressionComment* Comment : Comments)
        {
            if (!Comment) continue;
            TSharedPtr<FJsonObject> CommentObj = MakeShared<FJsonObject>();
            CommentObj->SetStringField("text", Comment->Text);

            TArray<TSharedPtr<FJsonValue>> PosArr;
            PosArr.Add(MakeShared<FJsonValueNumber>(Comment->MaterialExpressionEditorX));
            PosArr.Add(MakeShared<FJsonValueNumber>(Comment->MaterialExpressionEditorY));
            CommentObj->SetArrayField("position", PosArr);

            TArray<TSharedPtr<FJsonValue>> SizeArr;
            SizeArr.Add(MakeShared<FJsonValueNumber>(Comment->SizeX));
            SizeArr.Add(MakeShared<FJsonValueNumber>(Comment->SizeY));
            CommentObj->SetArrayField("size", SizeArr);

            // Comment color
            TArray<TSharedPtr<FJsonValue>> ColorArr;
            ColorArr.Add(MakeShared<FJsonValueNumber>(Comment->CommentColor.R));
            ColorArr.Add(MakeShared<FJsonValueNumber>(Comment->CommentColor.G));
            ColorArr.Add(MakeShared<FJsonValueNumber>(Comment->CommentColor.B));
            ColorArr.Add(MakeShared<FJsonValueNumber>(Comment->CommentColor.A));
            CommentObj->SetArrayField("color", ColorArr);

            CommentsArray.Add(MakeShared<FJsonValueObject>(CommentObj));
        }
        RootJson->SetArrayField("comments", CommentsArray);
    }

    // Phase 5: Collect referenced material functions
    TArray<TSharedPtr<FJsonValue>> FuncArray;
    TSet<FString> SeenFunctions;

    for (UMaterialExpression* Expr : SerializableExpressions)
    {
        UMaterialExpressionMaterialFunctionCall* FuncCall =
            Cast<UMaterialExpressionMaterialFunctionCall>(Expr);
        if (!FuncCall || !FuncCall->MaterialFunction) continue;

        FString FuncPath = FuncCall->MaterialFunction->GetPathName();
        if (SeenFunctions.Contains(FuncPath)) continue;
        SeenFunctions.Add(FuncPath);

        TSharedPtr<FJsonObject> FuncObj = MakeShared<FJsonObject>();
        FuncObj->SetStringField("name", FuncCall->MaterialFunction->GetName());
        FuncObj->SetStringField("asset_path", FuncPath);

        // Find which expressions reference this function
        TArray<TSharedPtr<FJsonValue>> CalledFromArray;
        for (UMaterialExpression* OtherExpr : SerializableExpressions)
        {
            UMaterialExpressionMaterialFunctionCall* OtherCall =
                Cast<UMaterialExpressionMaterialFunctionCall>(OtherExpr);
            if (OtherCall && OtherCall->MaterialFunction == FuncCall->MaterialFunction)
            {
                const FString* CallerId = ExprIdMap.Find(OtherExpr);
                if (CallerId)
                {
                    CalledFromArray.Add(MakeShared<FJsonValueString>(*CallerId));
                }
            }
        }
        FuncObj->SetArrayField("called_from", CalledFromArray);

        FuncArray.Add(MakeShared<FJsonValueObject>(FuncObj));
    }

    if (FuncArray.Num() > 0)
    {
        RootJson->SetArrayField("material_functions", FuncArray);
    }

    // Serialize to string
    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(RootJson.ToSharedRef(), Writer);
    return Output;
}

FString UMaterialGraphReader::ExtractMaterialFunctionAsJson(UMaterialFunction* Func)
{
    if (!Func)
    {
        return "{}";
    }

    TSharedPtr<FJsonObject> RootJson = MakeShared<FJsonObject>();
    RootJson->SetStringField("schema_version", "material-v1");
    RootJson->SetStringField("asset_path", Func->GetPathName());
    RootJson->SetStringField("material_type", "MaterialFunction");
    RootJson->SetStringField("name", Func->GetName());

    // Build expression ID map
    TMap<UMaterialExpression*, FString> ExprIdMap;

    TArray<UMaterialExpression*> SerializableExpressions;
    TArray<UMaterialExpressionComment*> Comments;

    for (UMaterialExpression* Expr : Func->ExpressionCollection.Expressions)
    {
        if (!Expr) continue;

        UMaterialExpressionComment* Comment = Cast<UMaterialExpressionComment>(Expr);
        if (Comment)
        {
            Comments.Add(Comment);
            continue;
        }

        FString ExprId = FString::Printf(TEXT("e%d"), ExprIdMap.Num());
        ExprIdMap.Add(Expr, ExprId);
        SerializableExpressions.Add(Expr);
    }

    // Serialize expressions
    TArray<TSharedPtr<FJsonValue>> ExprArray = SerializeExpressionCollection(
        SerializableExpressions, ExprIdMap);
    RootJson->SetArrayField("expressions", ExprArray);

    // Serialize comments
    if (Comments.Num() > 0)
    {
        TArray<TSharedPtr<FJsonValue>> CommentsArray;
        for (UMaterialExpressionComment* Comment : Comments)
        {
            if (!Comment) continue;
            TSharedPtr<FJsonObject> CommentObj = MakeShared<FJsonObject>();
            CommentObj->SetStringField("text", Comment->Text);

            TArray<TSharedPtr<FJsonValue>> PosArr;
            PosArr.Add(MakeShared<FJsonValueNumber>(Comment->MaterialExpressionEditorX));
            PosArr.Add(MakeShared<FJsonValueNumber>(Comment->MaterialExpressionEditorY));
            CommentObj->SetArrayField("position", PosArr);

            TArray<TSharedPtr<FJsonValue>> SizeArr;
            SizeArr.Add(MakeShared<FJsonValueNumber>(Comment->SizeX));
            SizeArr.Add(MakeShared<FJsonValueNumber>(Comment->SizeY));
            CommentObj->SetArrayField("size", SizeArr);

            CommentsArray.Add(MakeShared<FJsonValueObject>(CommentObj));
        }
        RootJson->SetArrayField("comments", CommentsArray);
    }

    // Serialize to string
    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(RootJson.ToSharedRef(), Writer);
    return Output;
}

FString UMaterialGraphReader::GetExpressionInfo(UMaterialExpression* Expr)
{
    if (!Expr) return "{}";

    // For single expression query, we build a minimal ExprIdMap with just this expression
    TMap<UMaterialExpression*, FString> ExprIdMap;
    ExprIdMap.Add(Expr, TEXT("e0"));

    TSharedPtr<FJsonObject> Obj = SerializeExpression(Expr, TEXT("e0"), ExprIdMap);

    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), Writer);
    return Output;
}

FString UMaterialGraphReader::GetMaterialPropertyConnections(UMaterial* Material)
{
    if (!Material) return "{}";

    // Build a temporary ExprIdMap from the material's expressions
    TMap<UMaterialExpression*, FString> ExprIdMap;
    int32 IdCounter = 0;
    for (UMaterialExpression* Expr : Material->ExpressionCollection.Expressions)
    {
        if (!Expr) continue;
        if (Cast<UMaterialExpressionComment>(Expr)) continue;
        FString ExprId = FString::Printf(TEXT("e%d"), IdCounter++);
        ExprIdMap.Add(Expr, ExprId);
    }

    TSharedPtr<FJsonObject> PropsObj = SerializeMaterialProperties(Material, ExprIdMap);

    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(PropsObj.ToSharedRef(), Writer);
    return Output;
}

// ============================================================================
// Internal Serialization
// ============================================================================

TArray<TSharedPtr<FJsonValue>> UMaterialGraphReader::SerializeExpressionCollection(
    const TArray<UMaterialExpression*>& Expressions,
    TMap<UMaterialExpression*, FString>& ExprIdMap)
{
    TArray<TSharedPtr<FJsonValue>> Result;

    for (UMaterialExpression* Expr : Expressions)
    {
        if (!Expr) continue;

        const FString* ExprIdPtr = ExprIdMap.Find(Expr);
        if (!ExprIdPtr) continue;

        TSharedPtr<FJsonObject> ExprObj = SerializeExpression(Expr, *ExprIdPtr, ExprIdMap);
        Result.Add(MakeShared<FJsonValueObject>(ExprObj));
    }

    return Result;
}

TSharedPtr<FJsonObject> UMaterialGraphReader::SerializeExpression(
    UMaterialExpression* Expr,
    const FString& ExprId,
    const TMap<UMaterialExpression*, FString>& ExprIdMap)
{
    TSharedPtr<FJsonObject> ExprObj = MakeShared<FJsonObject>();

    ExprObj->SetStringField("id", ExprId);
    ExprObj->SetStringField("class", GetExpressionClassName(Expr));
    ExprObj->SetStringField("title", GetExpressionTitle(Expr));

    // Position (MaterialExpressionEditorX/Y are in editor coordinate space)
    TArray<TSharedPtr<FJsonValue>> Position;
    Position.Add(MakeShared<FJsonValueNumber>(Expr->MaterialExpressionEditorX));
    Position.Add(MakeShared<FJsonValueNumber>(Expr->MaterialExpressionEditorY));
    ExprObj->SetArrayField("position", Position);

    // Inputs — iterate FExpressionInput via FExpressionInputIterator
    TArray<TSharedPtr<FJsonValue>> InputsArray;
    for (FExpressionInputIterator It(Expr); It; ++It)
    {
        TSharedPtr<FJsonObject> InputObj = MakeShared<FJsonObject>();
        InputObj->SetStringField("name", It->InputName.ToString());

        // Determine input type from Mask flags on FExpressionInput
        FString InputType = "unknown";
        if (It->Mask)
        {
            // Masked channels indicate vector/color type
            bool bR = It->MaskR, bG = It->MaskG, bB = It->MaskB, bA = It->MaskA;
            int32 ChannelCount = (int32)bR + (int32)bG + (int32)bB + (int32)bA;
            if (ChannelCount >= 4) InputType = "rgba";
            else if (ChannelCount >= 3) InputType = "rgb";
            else if (ChannelCount >= 2) InputType = "float2";
            else InputType = "scalar";
        }
        else
        {
            // Infer from upstream expression output or use generic "any"
            InputType = "any";
        }
        InputObj->SetStringField("type", InputType);

        // Connection info (inline: connected_to = upstream expression ID)
        if (It->Expression)
        {
            const FString* UpstreamId = ExprIdMap.Find(It->Expression);
            if (UpstreamId)
            {
                InputObj->SetStringField("connected_to", *UpstreamId);
            }
            else
            {
                InputObj->SetField("connected_to", MakeShared<FJsonValueNull>());
            }
            InputObj->SetNumberField("output_index", It->OutputIndex);
        }
        else
        {
            InputObj->SetField("connected_to", MakeShared<FJsonValueNull>());
            InputObj->SetField("output_index", MakeShared<FJsonValueNull>());
        }

        InputsArray.Add(MakeShared<FJsonValueObject>(InputObj));
    }
    ExprObj->SetArrayField("inputs", InputsArray);

    // Outputs — iterate FExpressionOutput via FExpressionOutputIterator
    TArray<TSharedPtr<FJsonValue>> OutputsArray;
    for (FExpressionOutputIterator It(Expr); It; ++It)
    {
        OutputsArray.Add(MakeShared<FJsonValueString>(It->OutputName.ToString()));
    }
    ExprObj->SetArrayField("outputs", OutputsArray);

    // Specialized properties for common expression types
    TSharedPtr<FJsonObject> SpecialProps = SerializeExpressionProperties(Expr);
    if (SpecialProps.IsValid())
    {
        ExprObj->SetObjectField("properties", SpecialProps);
    }

    // Description (if set by user in editor)
    if (!Expr->Desc.IsEmpty())
    {
        ExprObj->SetStringField("description", Expr->Desc);
    }

    return ExprObj;
}

TSharedPtr<FJsonObject> UMaterialGraphReader::SerializeMaterialProperties(
    UMaterial* Material,
    const TMap<UMaterialExpression*, FString>& ExprIdMap)
{
    TSharedPtr<FJsonObject> PropsObj = MakeShared<FJsonObject>();

    // Helper lambda to serialize a single material property connection
    auto SerializePropertyInput = [&ExprIdMap](const FExpressionInput& Input,
                                                const TCHAR* Name,
                                                TSharedPtr<FJsonObject>& OutObj)
    {
        TSharedPtr<FJsonObject> PropObj = MakeShared<FJsonObject>();
        if (Input.Expression)
        {
            const FString* UpstreamId = ExprIdMap.Find(Input.Expression);
            if (UpstreamId) PropObj->SetStringField("connected_to", *UpstreamId);
            else PropObj->SetField("connected_to", MakeShared<FJsonValueNull>());
            PropObj->SetNumberField("output_index", Input.OutputIndex);
        }
        else
        {
            PropObj->SetField("connected_to", MakeShared<FJsonValueNull>());
            PropObj->SetField("output_index", MakeShared<FJsonValueNull>());
        }
        OutObj->SetObjectField(Name, PropObj);
    };

    // Direct member access on UMaterial for each property input
    SerializePropertyInput(Material->EmissiveColor,  TEXT("EmissiveColor"), PropsObj);
    SerializePropertyInput(Material->DiffuseColor,   TEXT("DiffuseColor"), PropsObj);
    SerializePropertyInput(Material->BaseColor,      TEXT("BaseColor"), PropsObj);
    SerializePropertyInput(Material->Metallic,       TEXT("Metallic"), PropsObj);
    SerializePropertyInput(Material->Specular,       TEXT("Specular"), PropsObj);
    SerializePropertyInput(Material->Roughness,      TEXT("Roughness"), PropsObj);
    SerializePropertyInput(Material->Anisotropy,     TEXT("Anisotropy"), PropsObj);
    SerializePropertyInput(Material->Normal,         TEXT("Normal"), PropsObj);
    SerializePropertyInput(Material->Tangent,        TEXT("Tangent"), PropsObj);
    SerializePropertyInput(Material->WorldPositionOffset, TEXT("WorldPositionOffset"), PropsObj);
    SerializePropertyInput(Material->WorldDisplacement,   TEXT("WorldDisplacement"), PropsObj);
    SerializePropertyInput(Material->TessellationMultiplier, TEXT("TessellationMultiplier"), PropsObj);
    SerializePropertyInput(Material->SubsurfaceColor, TEXT("SubsurfaceColor"), PropsObj);
    SerializePropertyInput(Material->AmbientOcclusion, TEXT("AmbientOcclusion"), PropsObj);
    SerializePropertyInput(Material->Opacity,        TEXT("Opacity"), PropsObj);
    SerializePropertyInput(Material->OpacityMask,    TEXT("OpacityMask"), PropsObj);
    SerializePropertyInput(Material->PixelDepthOffset, TEXT("PixelDepthOffset"), PropsObj);
    SerializePropertyInput(Material->Refraction,     TEXT("Refraction"), PropsObj);

    return PropsObj;
}

TSharedPtr<FJsonObject> UMaterialGraphReader::SerializeExpressionInput(
    const FExpressionInput& Input,
    const TMap<UMaterialExpression*, FString>& ExprIdMap)
{
    TSharedPtr<FJsonObject> InputObj = MakeShared<FJsonObject>();

    if (Input.Expression)
    {
        const FString* UpstreamId = ExprIdMap.Find(Input.Expression);
        if (UpstreamId)
        {
            InputObj->SetStringField("connected_to", *UpstreamId);
        }
        else
        {
            InputObj->SetField("connected_to", MakeShared<FJsonValueNull>());
        }
        InputObj->SetNumberField("output_index", Input.OutputIndex);
    }
    else
    {
        InputObj->SetField("connected_to", MakeShared<FJsonValueNull>());
        InputObj->SetField("output_index", MakeShared<FJsonValueNull>());
    }

    return InputObj;
}

// ============================================================================
// Specialized Expression Property Extraction
// ============================================================================

TSharedPtr<FJsonObject> UMaterialGraphReader::SerializeExpressionProperties(UMaterialExpression* Expr)
{
    if (!Expr) return nullptr;

    // --- ScalarParameter ---
    if (UMaterialExpressionScalarParameter* ScalarParam = Cast<UMaterialExpressionScalarParameter>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetStringField("parameter_name", ScalarParam->ParameterName.ToString());
        Props->SetNumberField("default_value", ScalarParam->DefaultValue);
        Props->SetNumberField("min", ScalarParam->SliderMin);
        Props->SetNumberField("max", ScalarParam->SliderMax);
        if (!ScalarParam->Group.IsEmpty())
        {
            Props->SetStringField("group", ScalarParam->Group.ToString());
        }
        return Props;
    }

    // --- VectorParameter ---
    if (UMaterialExpressionVectorParameter* VectorParam = Cast<UMaterialExpressionVectorParameter>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetStringField("parameter_name", VectorParam->ParameterName.ToString());

        // Default value as [R, G, B, A]
        TArray<TSharedPtr<FJsonValue>> DefaultArr;
        DefaultArr.Add(MakeShared<FJsonValueNumber>(VectorParam->DefaultValue.R));
        DefaultArr.Add(MakeShared<FJsonValueNumber>(VectorParam->DefaultValue.G));
        DefaultArr.Add(MakeShared<FJsonValueNumber>(VectorParam->DefaultValue.B));
        DefaultArr.Add(MakeShared<FJsonValueNumber>(VectorParam->DefaultValue.A));
        Props->SetArrayField("default_value", DefaultArr);

        if (!VectorParam->Group.IsEmpty())
        {
            Props->SetStringField("group", VectorParam->Group.ToString());
        }
        return Props;
    }

    // --- TextureSampleParameter2D (inherits TextureSample) ---
    if (UMaterialExpressionTextureSampleParameter2D* TexParam = Cast<UMaterialExpressionTextureSampleParameter2D>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetStringField("parameter_name", TexParam->ParameterName.ToString());

        if (TexParam->Texture)
        {
            Props->SetStringField("texture", TexParam->Texture->GetPathName());
        }
        else
        {
            Props->SetField("texture", MakeShared<FJsonValueNull>());
        }

        // Sampler type — SamplerSourceMode is not a UENUM, map manually
        switch (TexParam->SamplerSource)
        {
            case SamplerSourceMode::SSM_FromTextureAsset: Props->SetStringField("sampler_type", "FromTextureAsset"); break;
            case SamplerSourceMode::SSM_Wrap: Props->SetStringField("sampler_type", "Wrap"); break;
            case SamplerSourceMode::SSM_Clamp: Props->SetStringField("sampler_type", "Clamp"); break;
            default: Props->SetStringField("sampler_type", "Unknown"); break;
        }

        if (!TexParam->Group.IsEmpty())
        {
            Props->SetStringField("group", TexParam->Group.ToString());
        }
        return Props;
    }

    // --- TextureSample (non-parameter) ---
    if (UMaterialExpressionTextureSample* TexSample = Cast<UMaterialExpressionTextureSample>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

        if (TexSample->Texture)
        {
            Props->SetStringField("texture", TexSample->Texture->GetPathName());
        }
        else
        {
            Props->SetField("texture", MakeShared<FJsonValueNull>());
        }

        // Sampler type — SamplerSourceMode is not a UENUM, map manually
        switch (TexSample->SamplerSource)
        {
            case SamplerSourceMode::SSM_FromTextureAsset: Props->SetStringField("sampler_type", "FromTextureAsset"); break;
            case SamplerSourceMode::SSM_Wrap: Props->SetStringField("sampler_type", "Wrap"); break;
            case SamplerSourceMode::SSM_Clamp: Props->SetStringField("sampler_type", "Clamp"); break;
            default: Props->SetStringField("sampler_type", "Unknown"); break;
        }

        return Props;
    }

    // --- MaterialFunctionCall ---
    if (UMaterialExpressionMaterialFunctionCall* FuncCall = Cast<UMaterialExpressionMaterialFunctionCall>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

        if (FuncCall->MaterialFunction)
        {
            Props->SetStringField("function_name", FuncCall->MaterialFunction->GetName());
            Props->SetStringField("function_path", FuncCall->MaterialFunction->GetPathName());
        }
        else
        {
            Props->SetField("function_name", MakeShared<FJsonValueNull>());
            Props->SetField("function_path", MakeShared<FJsonValueNull>());
        }
        return Props;
    }

    // --- Custom (HLSL) ---
    if (UMaterialExpressionCustom* CustomExpr = Cast<UMaterialExpressionCustom>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

        // Truncate long HLSL code
        FString Code = CustomExpr->Code;
        if (Code.Len() > MaxCodeLength)
        {
            Code = Code.Left(MaxCodeLength) + TEXT("...[truncated]");
        }
        Props->SetStringField("code", Code);

        // Output type
        Props->SetStringField("output_type",
            StaticEnum<ECustomMaterialOutputType>()->GetNameStringByValue(
                static_cast<int64>(CustomExpr->OutputType)));

        // Description
        if (!CustomExpr->Description.IsEmpty())
        {
            Props->SetStringField("description", CustomExpr->Description);
        }

        // Input parameter names
        TArray<TSharedPtr<FJsonValue>> InputNames;
        for (const FCustomInput& Input : CustomExpr->Inputs)
        {
            InputNames.Add(MakeShared<FJsonValueString>(Input.InputName.ToString()));
        }
        Props->SetArrayField("input_names", InputNames);

        return Props;
    }

    // --- Constant ---
    if (UMaterialExpressionConstant* ConstExpr = Cast<UMaterialExpressionConstant>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetNumberField("value", ConstExpr->R);
        return Props;
    }

    // --- StaticSwitch ---
    if (UMaterialExpressionStaticSwitch* StaticSwitch = Cast<UMaterialExpressionStaticSwitch>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetBoolField("default_value", StaticSwitch->DefaultValue);
        return Props;
    }

    // --- StaticBool ---
    if (UMaterialExpressionStaticBool* StaticBool = Cast<UMaterialExpressionStaticBool>(Expr))
    {
        TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
        Props->SetBoolField("default_value", StaticBool->DefaultValue);
        return Props;
    }

    // Fallback: no specialized properties
    return nullptr;
}

// ============================================================================
// Utility Functions
// ============================================================================

FString UMaterialGraphReader::GetExpressionClassName(UMaterialExpression* Expr)
{
    if (!Expr) return "Unknown";

    FString ClassName = Expr->GetClass()->GetName();

    // Strip "UMaterialExpression" prefix
    // e.g. "MaterialExpressionMultiply" from "UMaterialExpressionMultiply"
    static const FString Prefix = TEXT("UMaterialExpression");
    if (ClassName.StartsWith(Prefix))
    {
        ClassName.RightChopInline(Prefix.Len());
        // If nothing left (e.g. the class IS UMaterialExpression), use full name
        if (ClassName.IsEmpty())
        {
            ClassName = TEXT("MaterialExpression");
        }
    }
    else
    {
        // Non-standard prefix, just strip U
        if (ClassName.Len() > 1 && ClassName[0] == TEXT('U') && FChar::IsUpper(ClassName[1]))
        {
            ClassName.RightChopInline(1);
        }
    }

    // Prefix with "MaterialExpression" for clarity in the JSON
    return FString::Printf(TEXT("MaterialExpression%s"), *ClassName);
}

FString UMaterialGraphReader::GetExpressionTitle(UMaterialExpression* Expr)
{
    if (!Expr) return TEXT("Unknown");

    // UMaterialExpression does not have GetTitle() like UEdGraphNode.
    // Strategy: use Desc (user description) if set, else use class display name.
    FString Title;

    if (!Expr->Desc.IsEmpty())
    {
        Title = Expr->Desc;
    }
    else
    {
        Title = Expr->GetClass()->GetDisplayNameText().ToString();
    }

    // Truncate if too long
    if (Title.Len() > MaxTitleLength)
    {
        Title = Title.Left(MaxTitleLength - 3) + TEXT("...");
    }

    return Title;
}

FString UMaterialGraphReader::GetMaterialPropertyName(EMaterialProperty Property)
{
    return StaticEnum<EMaterialProperty>()->GetNameStringByValue(static_cast<int64>(Property));
}

#undef LOCTEXT_NAMESPACE
