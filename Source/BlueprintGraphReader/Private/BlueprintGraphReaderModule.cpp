// Copyright 2025 radial-hks. All Rights Reserved.

#include "BlueprintGraphReaderModule.h"
#include "Modules/ModuleManager.h"

#define LOCTEXT_NAMESPACE "FBlueprintGraphReaderModule"

void FBlueprintGraphReaderModule::StartupModule()
{
    // Module startup — no special initialization needed
    // The UBlueprintFunctionLibrary is auto-registered by UE's reflection system
}

void FBlueprintGraphReaderModule::ShutdownModule()
{
    // Module shutdown — no cleanup needed (read-only, no allocated resources)
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FBlueprintGraphReaderModule, BlueprintGraphReader)
