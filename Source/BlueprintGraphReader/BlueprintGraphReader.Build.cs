using UnrealBuildTool;

public class BlueprintGraphReader : ModuleRules
{
    public BlueprintGraphReader(ReadOnlyTargetRules Target) : base(Target)
    {
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
            "BlueprintGraph",
            "UnrealEd",
            "Json",
            "JsonUtilities",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "CoreUObject",
            "Slate",
            "SlateCore",
            "EditorScriptingUtilities",
            "Kismet",
            "ToolMenus",
        });
    }
}
