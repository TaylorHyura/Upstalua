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
import filecmp
import requests
import time

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
                config = json.load(f)
                # Ensure appids is a dictionary
                if 'appids' in config and isinstance(config['appids'], list):
                    # Convert old list format to new dictionary format
                    config['appids'] = {appid: "Unknown" for appid in config['appids']}
                return config
        except Exception as e:
            print(f"⚠️  Config error: {e}")
    return {'steam_path': '', 'appids': {}}

def save_config(steam_path, appids_dict):
    """Save configuration to file"""
    config = {'steam_path': steam_path, 'appids': appids_dict}
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"✅ Config saved: {len(appids_dict)} games")
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
# Steam API Functions
# =============================================================================

def get_game_name(appid):
    """Get game name from Steam API"""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if str(appid) in data and data[str(appid)]['success']:
            return data[str(appid)]['data']['name']
        
        return "Unknown"
    except requests.exceptions.RequestException:
        return "Unknown"
    except (KeyError, ValueError):
        return "Unknown"

def get_game_names(appids):
    """Get game names for multiple AppIDs with rate limiting"""
    print(f"🔍 Fetching game names from Steam API...")
    game_names = {}
    
    for i, appid in enumerate(appids):
        print(f"   📡 Querying {appid} ({i+1}/{len(appids)})...")
        game_name = get_game_name(appid)
        game_names[appid] = game_name
        
        # Rate limiting to be respectful to Steam API
        if i < len(appids) - 1:  # Don't sleep after the last one
            time.sleep(0.5)  # 500ms delay between requests
    
    return game_names

def update_game_names(appids_dict, new_appids):
    """Update game names for new AppIDs"""
    if not new_appids:
        return appids_dict
    
    # Get names only for new AppIDs
    appids_to_query = [appid for appid in new_appids if appid not in appids_dict]
    if not appids_to_query:
        return appids_dict
    
    new_game_names = get_game_names(appids_to_query)
    
    # Update the dictionary with new game names
    updated_dict = appids_dict.copy()
    for appid, name in new_game_names.items():
        updated_dict[appid] = name
    
    return updated_dict

def format_game_display(appid, game_name):
    """Format game display as 'appid = Game name'"""
    return f"{appid} = {game_name}"

# =============================================================================
# Unified File Operations
# =============================================================================

def should_backup_file(source_path, dest_path):
    """Check if file needs backup (new or modified)"""
    if not os.path.exists(dest_path):
        return True, "new"
    
    if not filecmp.cmp(source_path, dest_path, shallow=False):
        return True, "modified"
    
    return False, "unchanged"

def backup_game_files(steam_path, appids_dict, backup_type):
    """Backup function for both Lua and Stats files"""
    if backup_type == 'plugins':
        source_folder = os.path.join(steam_path, "config", "stplug-in")
        backup_subfolder = "config/stplug-in"
        file_extension = ".lua"
        display_name = "Plugin Files"
    else:  # stats
        source_folder = os.path.join(steam_path, "appcache", "stats")
        backup_subfolder = "appcache/stats"
        file_extension = ".bin"
        display_name = "Statistics Files"
    
    backup_path = os.path.join(BACKUP_FOLDER, *backup_subfolder.split('/'))
    
    if not os.path.exists(source_folder):
        print(f"❌ Source folder not found: {source_folder}")
        return False
    
    if not appids_dict:
        print(f"📝 No games specified for {display_name}")
        return True
    
    os.makedirs(backup_path, exist_ok=True)
    
    saved_files = []
    skipped_files = []
    missing_files = []
    
    appid_list = list(appids_dict.keys())
    
    for appid in appid_list:
        if backup_type == 'plugins':
            # For plugins: simple filename pattern (appid.lua)
            filename = f"{appid}{file_extension}"
            source_file = os.path.join(source_folder, filename)
            dest_file = os.path.join(backup_path, filename)
            
            if os.path.exists(source_file):
                should_backup, reason = should_backup_file(source_file, dest_file)
                if should_backup:
                    shutil.copy2(source_file, dest_file)
                    saved_files.append((filename, reason, appid, appids_dict[appid]))
                else:
                    skipped_files.append((filename, appid, appids_dict[appid]))
            else:
                missing_files.append((filename, appid, appids_dict[appid]))
                
        else:  # stats
            # For stats: pattern matching (*appid*)
            pattern = os.path.join(source_folder, f"*{appid}*")
            for source_file in glob.glob(pattern):
                if os.path.isfile(source_file):
                    filename = os.path.basename(source_file)
                    dest_file = os.path.join(backup_path, filename)
                    
                    should_backup, reason = should_backup_file(source_file, dest_file)
                    if should_backup:
                        shutil.copy2(source_file, dest_file)
                        saved_files.append((filename, reason, appid, appids_dict[appid]))
                    else:
                        skipped_files.append((filename, appid, appids_dict[appid]))
    
    return _report_backup_results(saved_files, skipped_files, missing_files, display_name, file_extension, backup_type)

def _report_backup_results(saved, skipped, missing, display_name, file_extension, backup_type):
    """Report backup results for both plugins and stats"""
    print(f"\n📁 {display_name} ({file_extension.upper()})")
    print("─" * 60)
    
    if saved:
        print(f"✅ Updated: {len(saved)} file(s)")
        
        if backup_type == 'plugins':
            # For plugins: simple list
            for filename, reason, appid, game_name in saved:
                status_icon = "🆕" if reason == "new" else "📝"
                game_display = format_game_display(appid, game_name)
                print(f"   {status_icon} {filename}")
                print(f"      🎮 {game_display} ({reason})")
        else:
            # For stats: group by AppID
            by_appid = {}
            for file, reason, appid, game_name in saved:
                by_appid.setdefault((appid, game_name), []).append((file, reason))
            
            for (appid, game_name), files in sorted(by_appid.items()):
                game_display = format_game_display(appid, game_name)
                print(f"   🎮 {game_display}:")
                for filename, reason in sorted(files):
                    status_icon = "🆕" if reason == "new" else "📝"
                    print(f"      {status_icon} {filename}")
    
    if skipped:
        print(f"📋 Unchanged: {len(skipped)} file(s)")
        
        if backup_type == 'plugins':
            # For plugins: show first few
            for filename, appid, game_name in skipped[:3]:
                game_display = format_game_display(appid, game_name)
                print(f"   ✅ {filename}")
                print(f"      🎮 {game_display}")
            if len(skipped) > 3:
                print(f"   ... and {len(skipped) - 3} more unchanged files")
        else:
            # For stats: group by AppID
            skipped_by_appid = {}
            for file, appid, game_name in skipped:
                skipped_by_appid.setdefault((appid, game_name), []).append(file)
            
            displayed = 0
            for (appid, game_name), files in sorted(skipped_by_appid.items()):
                if displayed < 3:
                    game_display = format_game_display(appid, game_name)
                    print(f"   🎮 {game_display}: {len(files)} unchanged files")
                    displayed += 1
            
            total_games = len(skipped_by_appid)
            if total_games > 3:
                print(f"   ... and {total_games - 3} more games with unchanged files")
    
    if missing:
        print(f"⚠️  Missing: {len(missing)} file(s)")
        for filename, appid, game_name in missing:
            game_display = format_game_display(appid, game_name)
            print(f"   ❌ {filename}")
            print(f"      🎮 {game_display}")
    
    # Return True if operation was successful (files were processed)
    # Only return False if there was an actual error
    if not saved and not skipped and backup_type == 'plugins':
        # For plugins, if no files at all were found, it might be an error
        print("❌ No files found or processed")
        return False
    
    # Operation successful if we processed files (even if none needed updating)
    return True

# =============================================================================
# Steam Detection
# =============================================================================

def detect_steam():
    """Auto-detect Steam installation"""
    print("🔍 Detecting Steam installation...")
    
    # Try registry first
    for hive, subkey, value_name in REGISTRY_PATHS:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                path, _ = winreg.QueryValueEx(key, value_name)
                if path and os.path.exists(path):
                    path = os.path.expandvars(path)  # Expand environment variables
                    path = path.replace("/", "\\")
                    print(f"✅ Found in registry: {path}")
                    return path
        except FileNotFoundError:
            continue
        except PermissionError:
            print(f"⚠️  Permission denied accessing registry: {subkey}")
            continue
        except Exception as e:
            print(f"⚠️  Registry error {subkey}: {e}")
            continue
    
    print("❌ Steam not found in registry")
    return None

def get_steam_from_user():
    """Get Steam path from user"""
    print("\n📁 Manual Steam Path Setup")
    print("─" * 30)
    print("Examples:")
    print("  • C:\\Program Files (x86)\\Steam")
    print("  • D:\\Steam")
    print("  • C:\\Games\\Steam")
    
    while True:
        path = input("\nEnter Steam path: ").strip()
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
            print(f"❌ {msg}")
            print("Please check the path and try again")

# =============================================================================
# AppID Management
# =============================================================================

def get_appids_from_plugins(steam_path):
    """Extract AppIDs from stplug-in folder"""
    plugin_folder = os.path.join(steam_path, "config", "stplug-in")
    
    if not os.path.exists(plugin_folder):
        print(f"❌ Plugin folder not found: {plugin_folder}")
        return []
    
    try:
        lua_files = [f for f in os.listdir(plugin_folder) 
                    if os.path.isfile(os.path.join(plugin_folder, f)) 
                    and f.lower().endswith('.lua')]
        
        if not lua_files:
            print("❌ No plugin files found")
            return []
        
        appids = [os.path.splitext(f)[0] for f in lua_files]  # Treat as text, no validation
        print(f"📄 Found {len(appids)} plugin file(s)")
        return appids
        
    except Exception as e:
        print(f"❌ Error reading plugins: {e}")
        return []

def merge_appids(existing_dict, new_appids):
    """Merge AppID lists and update game names"""
    if not existing_dict:
        existing_dict = {}
    
    if not new_appids:
        return existing_dict
    
    # Find new AppIDs that aren't in the existing dictionary
    new_appids_found = [appid for appid in new_appids if appid not in existing_dict]
    
    if new_appids_found:
        print(f"🔄 Games: {len(existing_dict)} existing + {len(new_appids_found)} new")
        print(f"📥 New AppIDs detected: {', '.join(new_appids_found)}")
    
    return existing_dict  # Game names will be updated separately

# =============================================================================
# Main Logic
# =============================================================================

def setup_steam_path():
    """Determine Steam path through multiple methods"""
    config = load_config()
    existing_path = config.get('steam_path', '')
    existing_appids = config.get('appids', {})
    
    # Use existing config if valid
    if existing_path and validate_steam_path(existing_path)[0]:
        print(f"📁 Using configured path: {existing_path}")
        if existing_appids:
            print(f"📋 {len(existing_appids)} games in configuration")
            # Show all configured games
            for appid, game_name in sorted(existing_appids.items()):
                game_display = format_game_display(appid, game_name)
                print(f"   🎮 {game_display}")
        return existing_path, existing_appids
    
    # Auto-detect
    steam_path = detect_steam()
    if steam_path:
        valid, msg = validate_steam_path(steam_path)
        if valid:
            return steam_path, existing_appids
        print(f"❌ Invalid detected path: {msg}")
    
    # User input
    return get_steam_from_user(), existing_appids

def should_update_config(new_path, old_path, new_appids, old_appids_dict):
    """Check if config needs updating"""
    path_changed = new_path != old_path
    new_appids_found = new_appids and any(appid not in old_appids_dict for appid in new_appids)
    return path_changed or new_appids_found

def run_backup(steam_path, appids_dict, detected_appids, existing_appids_dict, config_updated):
    """Execute backup operations"""
    print(f"\n🚀 Starting Backup Process")
    print("═" * 65)
    
    # Backup plugin files (.lua)
    plugins_ok = backup_game_files(steam_path, appids_dict, 'plugins')
    
    # Backup stats files (.bin)
    stats_ok = backup_game_files(steam_path, appids_dict, 'stats')
    
    _print_summary(steam_path, appids_dict, detected_appids, existing_appids_dict, config_updated, plugins_ok, stats_ok)

def _print_summary(steam_path, appids_dict, detected_appids, existing_appids_dict, config_updated, plugins_ok, stats_ok):
    """Print execution summary"""
    print(f"\n🎯 Backup Complete!")
    print("═" * 65)
    print(f"📍 Steam Path: {steam_path}")
    print(f"🎮 Total Games: {len(appids_dict)}")
    
    new_appids = [appid for appid in detected_appids if appid not in existing_appids_dict]
    
    if config_updated:
        if new_appids:
            print(f"📥 New games added: {len(new_appids)}")
            for appid in new_appids:
                game_name = appids_dict.get(appid, "Unknown")
                game_display = format_game_display(appid, game_name)
                print(f"   🎮 {game_display}")
        print(f"💾 Configuration updated")
    else:
        print(f"📋 No configuration changes needed")
    
    print(f"\n📊 Backup Results:")
    print(f"   • Plugin files (.lua): {'✅ Success' if plugins_ok else '❌ Failed'}")
    print(f"   • Statistics files (.bin): {'✅ Success' if stats_ok else '❌ Failed'}")
    
    if plugins_ok and stats_ok:
        print(f"\n✅ All operations completed successfully!")
    else:
        print(f"\n⚠️  Some operations had issues")

# =============================================================================
# Main Execution
# =============================================================================

def main():
    """Main execution flow"""
    print("🎮 Upstalua - Steam Backup Manager")
    print("═" * 65)
    
    try:
        # Setup
        steam_path, existing_appids_dict = setup_steam_path()
        if not steam_path:
            print("❌ Could not determine Steam path")
            return
        
        # Validate
        valid, msg = validate_steam_path(steam_path)
        if not valid:
            print(f"❌ Invalid Steam installation: {msg}")
            return
        
        # Detect AppIDs
        print(f"\n🔍 Scanning for plugins...")
        detected_appids = get_appids_from_plugins(steam_path)
        
        # Merge AppIDs and update game names
        merged_appids_dict = merge_appids(existing_appids_dict, detected_appids)
        
        # Update game names for new AppIDs
        if detected_appids:
            merged_appids_dict = update_game_names(merged_appids_dict, detected_appids)
        
        # Update config if needed
        config = load_config()
        old_path = config.get('steam_path', '')
        config_updated = should_update_config(steam_path, old_path, detected_appids, existing_appids_dict)
        
        if config_updated:
            if not save_config(steam_path, merged_appids_dict):
                print("❌ Failed to save configuration")
                return
        
        # Run backups
        run_backup(steam_path, merged_appids_dict, detected_appids, existing_appids_dict, config_updated)
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")

    input('\nPress Enter to exit...')

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
    return list(load_config().get('appids', {}).keys())

def get_games():
    """Get games dictionary for external scripts"""
    return load_config().get('appids', {})

def is_configured():
    """Check if configured"""
    return get_steam_path() is not None

if __name__ == "__main__":
    main()