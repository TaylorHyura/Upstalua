#!/usr/bin/env python3
"""
Upstalua - Steam Backup Tool
Backs up Steam plugin files and game statistics
"""

import os
import json
import winreg
import shutil
import glob

# Constants
CONFIG_FILE = "config.json"
BACKUP_FOLDER = "backup"
STEAM_ESSENTIALS = ["steam.exe", "steamapps", "userdata", "config"]
REGISTRY_PATHS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")
]

# =============================================================================
# Core Functions
# =============================================================================

def load_config():
    """Load configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Config error: {e}")
    return {}

def save_config(steam_path, appids):
    """Save configuration to file"""
    config = {'steam_path': steam_path, 'appids': appids}
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"💾 Config saved: {len(appids)} appids")
        return True
    except Exception as e:
        print(f"❌ Save error: {e}")
        return False

def validate_steam_path(path):
    """Validate Steam installation"""
    if not path or not os.path.exists(path):
        return False, "Path does not exist"
    
    missing = [f for f in STEAM_ESSENTIALS if not os.path.exists(os.path.join(path, f))]
    return (len(missing) == 0, "Valid" if len(missing) == 0 else f"Missing: {missing}")

# =============================================================================
# File Operations
# =============================================================================

def backup_files(steam_path, appids, source_subpath, backup_subpath, file_type="lua"):
    """Generic file backup function"""
    source_folder = os.path.join(steam_path, *source_subpath.split('/'))
    backup_path = os.path.join(BACKUP_FOLDER, *backup_subpath.split('/'))
    
    if not os.path.exists(source_folder):
        print(f"❌ Folder missing: {source_folder}")
        return False
    
    if not appids:
        print(f"📝 No appids for {file_type} files")
        return True
    
    os.makedirs(backup_path, exist_ok=True)
    
    if file_type == "stats":
        return _backup_stats_files(source_folder, backup_path, appids)
    else:
        return _backup_lua_files(source_folder, backup_path, appids, f".{file_type}")

def _backup_lua_files(source_folder, backup_path, appids, extension):
    """Backup lua files with simple naming pattern"""
    saved, missing = [], []
    
    for appid in appids:
        filename = f"{appid}{extension}"
        source = os.path.join(source_folder, filename)
        dest = os.path.join(backup_path, filename)
        
        if os.path.exists(source):
            shutil.copy2(source, dest)
            saved.append(filename)
        else:
            missing.append(filename)
    
    return _report_backup(saved, missing, extension.strip('.'))

def _backup_stats_files(stats_folder, backup_path, appids):
    """Backup stats files with pattern matching"""
    saved_files = []
    
    for appid in appids:
        pattern = os.path.join(stats_folder, f"*{appid}*")
        for source_file in glob.glob(pattern):
            if os.path.isfile(source_file):
                filename = os.path.basename(source_file)
                shutil.copy2(source_file, os.path.join(backup_path, filename))
                saved_files.append(filename)
    
    if saved_files:
        print(f"💾 Stats: {len(saved_files)} files for {len(appids)} appids")
        # Group by appid for clean output
        by_appid = {}
        for file in saved_files:
            for appid in appids:
                if appid in file:
                    by_appid.setdefault(appid, []).append(file)
                    break
        
        for appid, files in by_appid.items():
            print(f"   🎮 {appid}: {len(files)} files")
            for filename in sorted(files):
                print(f"      📄 {filename}")
        return True
    else:
        print("❌ No stats files found")
        return False

def _report_backup(saved, missing, file_type):
    """Report backup results"""
    if saved:
        print(f"💾 {file_type.title()}: {len(saved)} files")
        for file in saved:
            print(f"   📄 {file}")
        
        if missing:
            print(f"⚠️  Missing {len(missing)} files")
        return True
    else:
        print(f"❌ No {file_type} files saved")
        return False

# =============================================================================
# Steam Detection
# =============================================================================

def detect_steam():
    """Auto-detect Steam installation"""
    print("🔍 Detecting Steam...")
    
    # Try registry first
    for hive, subkey, value_name in REGISTRY_PATHS:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                path, _ = winreg.QueryValueEx(key, value_name)
                if path and os.path.exists(path):
                    path = path.replace("/", "\\")
                    print(f"✅ Found: {path}")
                    return path
        except Exception:
            continue
    
    print("❌ Not found in registry")
    return None

def get_steam_from_user():
    """Get Steam path from user"""
    print("\n📁 Enter Steam path:")
    print("   Examples: C:\\Program Files (x86)\\Steam, D:\\Steam")
    
    while True:
        path = input("\nPath: ").strip()
        if not path:
            print("❌ Please enter a path")
            continue
        
        path = path.strip('"\'').rstrip('\\')
        if '%' in path:
            path = os.path.expandvars(path)
        
        valid, msg = validate_steam_path(path)
        if valid:
            print(f"✅ {msg}")
            return path
        else:
            print(f"❌ {msg}\n   Please check path")

# =============================================================================
# AppID Management
# =============================================================================

def get_appids_from_plugins(steam_path):
    """Extract AppIDs from stplug-in folder"""
    plugin_folder = os.path.join(steam_path, "config", "stplug-in")
    
    if not os.path.exists(plugin_folder):
        print(f"❌ Plugin folder missing: {plugin_folder}")
        return []
    
    try:
        lua_files = [f for f in os.listdir(plugin_folder) 
                    if os.path.isfile(os.path.join(plugin_folder, f)) 
                    and f.lower().endswith('.lua')]
        
        if not lua_files:
            print("❌ No plugin files found")
            return []
        
        appids = [os.path.splitext(f)[0] for f in lua_files]
        print(f"📄 Plugins: {len(appids)} appids → {appids}")
        return appids
        
    except Exception as e:
        print(f"❌ Plugin error: {e}")
        return []

def merge_appids(existing, new):
    """Merge AppID lists"""
    if not existing:
        return new
    if not new:
        return existing
    
    merged = list(set(existing + new))
    added = [a for a in new if a not in existing]
    
    print(f"🔄 AppIDs: {len(existing)} + {len(new)} = {len(merged)}")
    if added:
        print(f"📥 New: {added}")
    
    return merged

# =============================================================================
# Main Logic
# =============================================================================

def setup_steam_path():
    """Determine Steam path through multiple methods"""
    config = load_config()
    existing_path = config.get('steam_path')
    existing_appids = config.get('appids', [])
    
    # Use existing config if valid
    if existing_path and validate_steam_path(existing_path)[0]:
        print(f"📁 Using config: {existing_path}")
        if existing_appids:
            print(f"📋 Existing: {len(existing_appids)} appids")
        return existing_path, existing_appids
    
    # Auto-detect
    steam_path = detect_steam()
    if steam_path:
        valid, msg = validate_steam_path(steam_path)
        if valid:
            return steam_path, existing_appids
        print(f"❌ Invalid: {msg}")
    
    # User input
    return get_steam_from_user(), existing_appids

def should_update_config(new_path, old_path, new_appids, old_appids):
    """Check if config needs updating"""
    return (new_path != old_path) or (new_appids and set(new_appids) - set(old_appids))

def run_backup(steam_path, all_appids, detected_appids, existing_appids, config_updated):
    """Execute backup operations"""
    print(f"\n💾 Backing up files...")
    
    # Backup plugin files (only newly detected)
    lua_ok = backup_files(steam_path, detected_appids, "config/stplug-in", "config/stplug-in", "lua")
    
    # Backup stats files (all appids from config)
    stats_ok = backup_files(steam_path, all_appids, "appcache/stats", "appcache/stats", "stats")
    
    _print_summary(steam_path, all_appids, detected_appids, existing_appids, config_updated, lua_ok, stats_ok)

def _print_summary(steam_path, all_appids, detected_appids, existing_appids, config_updated, lua_ok, stats_ok):
    """Print execution summary"""
    print(f"\n🎯 Upstalua Complete!")
    print(f"📍 Steam: {steam_path}")
    print(f"🎮 AppIDs: {len(all_appids)} total")
    
    if not config_updated:
        print("   (no new appids)")
    
    new_appids = [a for a in detected_appids if a not in existing_appids]
    if new_appids:
        print(f"📥 New: {new_appids}")

# =============================================================================
# Main Execution
# =============================================================================

def main():
    """Main execution flow"""
    print("🎮 Upstalua - Steam Backup Manager")
    print("=" * 45)
    
    try:
        # Setup
        steam_path, existing_appids = setup_steam_path()
        if not steam_path:
            return
        
        # Validate
        valid, msg = validate_steam_path(steam_path)
        if not valid:
            print(f"❌ Invalid: {msg}")
            return
        
        # Detect AppIDs
        print("\n🔍 Scanning plugins...")
        detected_appids = get_appids_from_plugins(steam_path)
        all_appids = merge_appids(existing_appids, detected_appids)
        
        # Update config if needed
        config_updated = should_update_config(steam_path, existing_appids, detected_appids, existing_appids)
        if config_updated:
            if not save_config(steam_path, all_appids):
                return
        
        # Run backups
        run_backup(steam_path, all_appids, detected_appids, existing_appids, config_updated)
    
    except KeyboardInterrupt:
        print("\n\n👋 Cancelled")
    except Exception as e:
        print(f"❌ Error: {e}")

    input('Press the Enter key to exit...')

# =============================================================================
# Utility Functions
# =============================================================================

def get_steam_path():
    """Get Steam path for external scripts"""
    config = load_config()
    path = config.get('steam_path')
    return path if path and validate_steam_path(path)[0] else None

def get_appids():
    """Get AppIDs for external scripts"""
    return load_config().get('appids', [])

def is_configured():
    """Check if configured"""
    return get_steam_path() is not None

if __name__ == "__main__":
    main()