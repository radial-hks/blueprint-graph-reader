using UnrealBuildTool;

public class BlueprintGraphReader : ModuleRules
{
    public BlueprintGraphReader(ReadOnlyTargetRules Target) : base(Target)
    {
        bUsesEditorAPIs = true;
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        // Public include paths
        PublicIncludePaths.AddRange(new string[]
        {
            "BlueprintGraphReader/Public",
        });

        // Private include paths
        PrivateIncludePaths.AddRange(new string[]
        {
            "BlueprintGraphReader/Private",
        });

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "Engine",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "CoreUObject",
            "BlueprintGraph",
            "UnrealEd",
            "Json",
            "JsonUtilities",
            "EditorScriptingUtilities",
            "Kismet",
        });
    }
}
