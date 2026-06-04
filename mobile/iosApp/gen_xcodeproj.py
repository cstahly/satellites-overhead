#!/usr/bin/env python3
"""Generate SatellitesApp.xcodeproj for the KMP iOS target."""
import os, uuid, pathlib, json

def g(): return uuid.uuid4().hex[:24].upper()

# Fixed GUIDs
PROJECT         = g()
TARGET          = g()
PRODUCTS_GROUP  = g()
ROOT_GROUP      = g()
APP_GROUP       = g()
VIEWMODELS_GRP  = g()
VIEWS_GRP       = g()
FRAMEWORKS_GRP  = g()

# Build phases
SOURCES_PHASE   = g()
FRAMEWORKS_PH   = g()
RESOURCES_PH    = g()

# Configs
PROJ_CFG_LIST   = g()
TGT_CFG_LIST    = g()
PROJ_DEBUG      = g()
PROJ_RELEASE    = g()
TGT_DEBUG       = g()
TGT_RELEASE     = g()

# Products
APP_PRODUCT     = g()

# Source files → (fileRef, buildFile)
SOURCES = {
    "SatellitesApp.swift":          (g(), g()),
    "ContentView.swift":            (g(), g()),
    "Extensions.swift":             (g(), g()),
    "ViewModels/AppState.swift":    (g(), g()),
    "Views/StatusView.swift":       (g(), g()),
    "Views/PassesView.swift":       (g(), g()),
    "Views/CapturesView.swift":     (g(), g()),
    "Views/EventsView.swift":       (g(), g()),
    "Views/SettingsView.swift":     (g(), g()),
}

# Resources
ASSETS_REF      = g()
ASSETS_BUILD    = g()
PREVIEW_GRP     = g()
PREVIEW_ASSETS  = g()
PREVIEW_BUILD   = g()

# Framework
FRAMEWORK_REF   = g()
FRAMEWORK_BUILD = g()

# Relative path from xcodeproj to xcframework release build
XCF_PATH = "../shared/build/XCFrameworks/release/Shared.xcframework"

BUNDLE_ID = "com.sdr.satellites"
TEAM_ID   = "M9FV48P37T"
APP_NAME  = "SatellitesApp"
DEPLOY    = "17.0"

def pbx_build_file(bf, ref, name, extra=""):
    extra_s = f"; settings = {{{extra}}};" if extra else ""
    return f"\t\t{bf} /* {name} in Sources */ = {{isa = PBXBuildFile; fileRef = {ref} /* {name} */{extra_s}}};\n"

def pbx_file_ref(ref, name, path, ftype):
    return f'\t\t{ref} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = {ftype}; path = {path}; sourceTree = "<group>"}};\n'

lines = [
    "// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n\tobjectVersion = 56;\n\tobjects = {\n\n",
]

# PBXBuildFile
lines.append("/* Begin PBXBuildFile section */\n")
for path, (ref, bf) in SOURCES.items():
    name = os.path.basename(path)
    lines.append(f"\t\t{bf} /* {name} in Sources */ = {{isa = PBXBuildFile; fileRef = {ref} /* {name} */; }};\n")
lines.append(f"\t\t{ASSETS_BUILD} /* Assets.xcassets in Resources */ = {{isa = PBXBuildFile; fileRef = {ASSETS_REF} /* Assets.xcassets */; }};\n")
lines.append(f"\t\t{PREVIEW_BUILD} /* Preview Assets.xcassets in Resources */ = {{isa = PBXBuildFile; fileRef = {PREVIEW_ASSETS} /* Preview Assets.xcassets */; }};\n")
lines.append(f"\t\t{FRAMEWORK_BUILD} /* Shared.xcframework in Frameworks */ = {{isa = PBXBuildFile; fileRef = {FRAMEWORK_REF} /* Shared.xcframework */; }};\n")
lines.append("/* End PBXBuildFile section */\n\n")

# PBXFileReference
lines.append("/* Begin PBXFileReference section */\n")
for path, (ref, bf) in SOURCES.items():
    name = os.path.basename(path)
    lines.append(f'\t\t{ref} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {name}; sourceTree = "<group>"; }};\n')
lines.append(f'\t\t{ASSETS_REF} /* Assets.xcassets */ = {{isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Assets.xcassets; sourceTree = "<group>"; }};\n')
lines.append(f'\t\t{PREVIEW_ASSETS} /* Preview Assets.xcassets */ = {{isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = "Preview Assets.xcassets"; sourceTree = "<group>"; }};\n')
lines.append(f'\t\t{FRAMEWORK_REF} /* Shared.xcframework */ = {{isa = PBXFileReference; lastKnownFileType = wrapper.xcframework; name = Shared.xcframework; path = {XCF_PATH}; sourceTree = "<group>"; }};\n')
lines.append(f'\t\t{APP_PRODUCT} /* {APP_NAME}.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = {APP_NAME}.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n')
lines.append("/* End PBXFileReference section */\n\n")

# PBXFrameworksBuildPhase
lines.append("/* Begin PBXFrameworksBuildPhase section */\n")
lines.append(f'\t\t{FRAMEWORKS_PH} /* Frameworks */ = {{\n\t\t\tisa = PBXFrameworksBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n\t\t\t\t{FRAMEWORK_BUILD} /* Shared.xcframework in Frameworks */,\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n')
lines.append("/* End PBXFrameworksBuildPhase section */\n\n")

# PBXGroup
lines.append("/* Begin PBXGroup section */\n")

# Root group
lines.append(f'\t\t{ROOT_GROUP} = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{APP_GROUP} /* {APP_NAME} */,\n\t\t\t\t{PRODUCTS_GROUP} /* Products */,\n\t\t\t\t{FRAMEWORKS_GRP} /* Frameworks */,\n\t\t\t);\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# Products group
lines.append(f'\t\t{PRODUCTS_GROUP} /* Products */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{APP_PRODUCT} /* {APP_NAME}.app */,\n\t\t\t);\n\t\t\tname = Products;\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# Frameworks group
lines.append(f'\t\t{FRAMEWORKS_GRP} /* Frameworks */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{FRAMEWORK_REF} /* Shared.xcframework */,\n\t\t\t);\n\t\t\tname = Frameworks;\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# ViewModels group
vm_refs = [(os.path.basename(p), r) for p, (r, b) in SOURCES.items() if p.startswith("ViewModels/")]
lines.append(f'\t\t{VIEWMODELS_GRP} /* ViewModels */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n')
for name, ref in vm_refs:
    lines.append(f'\t\t\t\t{ref} /* {name} */,\n')
lines.append(f'\t\t\t);\n\t\t\tpath = ViewModels;\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# Views group
view_refs = [(os.path.basename(p), r) for p, (r, b) in SOURCES.items() if p.startswith("Views/")]
lines.append(f'\t\t{VIEWS_GRP} /* Views */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n')
for name, ref in view_refs:
    lines.append(f'\t\t\t\t{ref} /* {name} */,\n')
lines.append(f'\t\t\t);\n\t\t\tpath = Views;\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# Preview Content group
lines.append(f'\t\t{PREVIEW_GRP} /* Preview Content */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t\t{PREVIEW_ASSETS} /* Preview Assets.xcassets */,\n\t\t\t);\n\t\t\tpath = "Preview Content";\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')

# Main app group
top_refs = [(os.path.basename(p), r) for p, (r, b) in SOURCES.items() if "/" not in p]
lines.append(f'\t\t{APP_GROUP} /* {APP_NAME} */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n')
for name, ref in top_refs:
    lines.append(f'\t\t\t\t{ref} /* {name} */,\n')
lines.append(f'\t\t\t\t{VIEWMODELS_GRP} /* ViewModels */,\n')
lines.append(f'\t\t\t\t{VIEWS_GRP} /* Views */,\n')
lines.append(f'\t\t\t\t{ASSETS_REF} /* Assets.xcassets */,\n')
lines.append(f'\t\t\t\t{PREVIEW_GRP} /* Preview Content */,\n')
lines.append(f'\t\t\t);\n\t\t\tpath = {APP_NAME};\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')
lines.append("/* End PBXGroup section */\n\n")

# PBXNativeTarget
lines.append("/* Begin PBXNativeTarget section */\n")
lines.append(f'\t\t{TARGET} /* {APP_NAME} */ = {{\n\t\t\tisa = PBXNativeTarget;\n\t\t\tbuildConfigurationList = {TGT_CFG_LIST} /* Build configuration list for PBXNativeTarget "{APP_NAME}" */;\n\t\t\tbuildPhases = (\n\t\t\t\t{SOURCES_PHASE} /* Sources */,\n\t\t\t\t{FRAMEWORKS_PH} /* Frameworks */,\n\t\t\t\t{RESOURCES_PH} /* Resources */,\n\t\t\t);\n\t\t\tbuildRules = (\n\t\t\t);\n\t\t\tdependencies = (\n\t\t\t);\n\t\t\tname = {APP_NAME};\n\t\t\tproductName = {APP_NAME};\n\t\t\tproductReference = {APP_PRODUCT} /* {APP_NAME}.app */;\n\t\t\tproductType = "com.apple.product-type.application";\n\t\t}};\n')
lines.append("/* End PBXNativeTarget section */\n\n")

# PBXProject
lines.append("/* Begin PBXProject section */\n")
lines.append(f'\t\t{PROJECT} /* Project object */ = {{\n\t\t\tisa = PBXProject;\n\t\t\tattributes = {{\n\t\t\t\tBuildIndependentTargetsInParallel = 1;\n\t\t\t\tLastSwiftUpdateCheck = 1600;\n\t\t\t\tLastUpgradeCheck = 1600;\n\t\t\t\tTargetAttributes = {{\n\t\t\t\t\t{TARGET} = {{\n\t\t\t\t\t\tCreatedOnToolsVersion = 16.0;\n\t\t\t\t\t}};\n\t\t\t\t}};\n\t\t\t}};\n\t\t\tbuildConfigurationList = {PROJ_CFG_LIST} /* Build configuration list for PBXProject "{APP_NAME}" */;\n\t\t\tcompatibilityVersion = "Xcode 14.0";\n\t\t\tdevelopmentRegion = en;\n\t\t\thasScannedForEncodings = 0;\n\t\t\tknownRegions = (\n\t\t\t\ten,\n\t\t\t\tBase,\n\t\t\t);\n\t\t\tmainGroup = {ROOT_GROUP};\n\t\t\tproductRefGroup = {PRODUCTS_GROUP} /* Products */;\n\t\t\tprojectDirPath = "";\n\t\t\tprojectRoot = "";\n\t\t\ttargets = (\n\t\t\t\t{TARGET} /* {APP_NAME} */,\n\t\t\t);\n\t\t}};\n')
lines.append("/* End PBXProject section */\n\n")

# PBXResourcesBuildPhase
lines.append("/* Begin PBXResourcesBuildPhase section */\n")
lines.append(f'\t\t{RESOURCES_PH} /* Resources */ = {{\n\t\t\tisa = PBXResourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n\t\t\t\t{ASSETS_BUILD} /* Assets.xcassets in Resources */,\n\t\t\t\t{PREVIEW_BUILD} /* Preview Assets.xcassets in Resources */,\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n')
lines.append("/* End PBXResourcesBuildPhase section */\n\n")

# PBXSourcesBuildPhase
lines.append("/* Begin PBXSourcesBuildPhase section */\n")
lines.append(f'\t\t{SOURCES_PHASE} /* Sources */ = {{\n\t\t\tisa = PBXSourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n')
for path, (ref, bf) in SOURCES.items():
    name = os.path.basename(path)
    lines.append(f'\t\t\t\t{bf} /* {name} in Sources */,\n')
lines.append(f'\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n')
lines.append("/* End PBXSourcesBuildPhase section */\n\n")

# XCBuildConfiguration
def target_cfg(guid, name):
    return (
        f'\t\t{guid} /* {name} */ = {{\n'
        f'\t\t\tisa = XCBuildConfiguration;\n'
        f'\t\t\tbuildSettings = {{\n'
        f'\t\t\t\tASETCATALOG_COMPILER_APPICON_NAME = AppIcon;\n'
        f'\t\t\t\tASETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME = AccentColor;\n'
        f'\t\t\t\tCODE_SIGN_STYLE = Automatic;\n'
        f'\t\t\t\tDEVELOPMENT_ASSET_PATHS = "\\"{APP_NAME}/Preview Content\\"";\n'
        f'\t\t\t\tDEVELOPMENT_TEAM = {TEAM_ID};\n'
        f'\t\t\t\tENABLE_PREVIEWS = YES;\n'
        f'\t\t\t\tGENERATE_INFOPLIST_FILE = YES;\n'
        f'\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;\n'
        f'\t\t\t\tINFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents = YES;\n'
        f'\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;\n'
        f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPad = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";\n'
        f'\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";\n'
        f'\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {DEPLOY};\n'
        f'\t\t\t\tLD_RUNPATH_SEARCH_PATHS = (\n'
        f'\t\t\t\t\t"$(inherited)",\n'
        f'\t\t\t\t\t"@executable_path/Frameworks",\n'
        f'\t\t\t\t);\n'
        f'\t\t\t\tMARKETING_VERSION = 1.0;\n'
        f'\t\t\t\tCURRENT_PROJECT_VERSION = 1;\n'
        f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};\n'
        f'\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";\n'
        f'\t\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;\n'
        f'\t\t\t\tSWIFT_VERSION = 5.0;\n'
        f'\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";\n'
        f'\t\t\t}};\n'
        f'\t\t\tname = {name};\n'
        f'\t\t}};\n'
    )

def proj_cfg(guid, name, extra=""):
    debug_extra = """
\t\t\t\tDEBUG_INFORMATION_FORMAT = dwarf;
\t\t\t\tENABLE_TESTABILITY = YES;
\t\t\t\tGCC_OPTIMIZATION_LEVEL = 0;
\t\t\t\tGCC_PREPROCESSOR_DEFINITIONS = (
\t\t\t\t\t"DEBUG=1",
\t\t\t\t\t"$(inherited)",
\t\t\t\t);
\t\t\t\tONLY_ACTIVE_ARCH = YES;
\t\t\t\tSWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Onone";""" if name == "Debug" else """
\t\t\t\tDEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
\t\t\t\tENABLE_NS_ASSERTIONS = NO;
\t\t\t\tSWIFT_COMPILATION_MODE = wholemodule;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-O";
\t\t\t\tVALIDATE_PRODUCT = YES;"""
    return (
        f'\t\t{guid} /* {name} */ = {{\n'
        f'\t\t\tisa = XCBuildConfiguration;\n'
        f'\t\t\tbuildSettings = {{\n'
        f'\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;\n'
        f'\t\t\t\tCLANG_ENABLE_MODULES = YES;\n'
        f'\t\t\t\tCLANG_ENABLE_OBJC_ARC = YES;\n'
        f'\t\t\t\tCOPY_PHASE_STRIP = NO;\n'
        f'\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = {DEPLOY};\n'
        f'\t\t\t\tMTL_FAST_MATH = YES;\n'
        f'\t\t\t\tSDKROOT = iphoneos;{debug_extra}\n'
        f'\t\t\t}};\n'
        f'\t\t\tname = {name};\n'
        f'\t\t}};\n'
    )

lines.append("/* Begin XCBuildConfiguration section */\n")
lines.append(proj_cfg(PROJ_DEBUG, "Debug"))
lines.append(proj_cfg(PROJ_RELEASE, "Release"))
lines.append(target_cfg(TGT_DEBUG, "Debug"))
lines.append(target_cfg(TGT_RELEASE, "Release"))
lines.append("/* End XCBuildConfiguration section */\n\n")

# XCConfigurationList
lines.append("/* Begin XCConfigurationList section */\n")
lines.append(f'\t\t{PROJ_CFG_LIST} /* Build configuration list for PBXProject "{APP_NAME}" */ = {{\n\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = (\n\t\t\t\t{PROJ_DEBUG} /* Debug */,\n\t\t\t\t{PROJ_RELEASE} /* Release */,\n\t\t\t);\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}};\n')
lines.append(f'\t\t{TGT_CFG_LIST} /* Build configuration list for PBXNativeTarget "{APP_NAME}" */ = {{\n\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = (\n\t\t\t\t{TGT_DEBUG} /* Debug */,\n\t\t\t\t{TGT_RELEASE} /* Release */,\n\t\t\t);\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}};\n')
lines.append("/* End XCConfigurationList section */\n\n")

lines.append(f'\t}};\n\trootObject = {PROJECT} /* Project object */;\n}}\n')

out = pathlib.Path("SatellitesApp.xcodeproj")
out.mkdir(exist_ok=True)
(out / "project.pbxproj").write_text("".join(lines))
print(f"Written: {out / 'project.pbxproj'}")

# Minimal Assets.xcassets
assets = pathlib.Path("SatellitesApp/Assets.xcassets")
assets.mkdir(parents=True, exist_ok=True)
(assets / "Contents.json").write_text('{"info":{"author":"xcode","version":1}}')

accent = assets / "AccentColor.colorset"
accent.mkdir(exist_ok=True)
(accent / "Contents.json").write_text('{"colors":[{"idiom":"universal"}],"info":{"author":"xcode","version":1}}')

appicon = assets / "AppIcon.appiconset"
appicon.mkdir(exist_ok=True)
(appicon / "Contents.json").write_text('{"images":[{"idiom":"universal","platform":"ios","size":"1024x1024"}],"info":{"author":"xcode","version":1}}')

# Preview Assets
preview = pathlib.Path("SatellitesApp/Preview Content/Preview Assets.xcassets")
preview.mkdir(parents=True, exist_ok=True)
(preview / "Contents.json").write_text('{"info":{"author":"xcode","version":1}}')

print("Done. Open SatellitesApp.xcodeproj in Xcode.")
