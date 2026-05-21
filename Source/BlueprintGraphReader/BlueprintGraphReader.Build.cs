using UnrealBuildTool;

public class BlueprintGraphReader : ModuleRules
{
    public BlueprintGraphReader(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

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
