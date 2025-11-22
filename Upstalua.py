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
import sys
import zipfile
import subprocess
import webbrowser
from pathlib import Path

# Constants
CONFIG_FILE = "config.json"
BACKUP_FOLDER = "backup"
STEAM_ESSENTIALS = ["steam.exe", "steamapps", "userdata", "config"]
REGISTRY_PATHS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")
]
RCLONE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone")
RCLONE_EXE = os.path.join(RCLONE_DIR, "rclone.exe")
RCLONE_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.conf")
GOOGLE_DRIVE_REMOTE = "gdrive:Upstalua"

# =============================================================================
# Core Functions
# =============================================================================

def load_config():
    """Load configuration from file"""
    default_config = {
        'steam_path': '', 
        'cloud_backup': {
            'enabled': True,
            'auto_upload': False,
            'remote_name': 'gdrive',
            'remote_path': 'gdrive:Upstalua'
        },
        'appids': {}
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # Merge with default config
                if 'appids' in user_config and isinstance(user_config['appids'], list):
                    user_config['appids'] = {appid: "Unknown" for appid in user_config['appids']}
                
                default_config.update(user_config)
                return default_config
        except Exception as e:
            print(f"⚠️  Config error: {e}")
    
    return default_config

def save_config(steam_path, appids_dict, cloud_backup_settings=None):
    """Save configuration to file"""
    config = load_config()  # Load existing config first
    config['steam_path'] = steam_path
    config['appids'] = appids_dict
    
    # Update cloud settings if provided
    if cloud_backup_settings:
        config['cloud_backup'].update(cloud_backup_settings)
    
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
# Cloud Backup Configuration Functions
# =============================================================================

def should_auto_upload():
    """Check if auto-upload is enabled in config"""
    config = load_config()
    return config['cloud_backup']['enabled'] and config['cloud_backup']['auto_upload']

def prompt_cloud_backup():
    """Prompt user for cloud backup based on config settings"""
    config = load_config()
    
    if not config['cloud_backup']['enabled']:
        return False
    
    if config['cloud_backup']['auto_upload']:
        print("☁️ Auto-upload enabled - starting cloud backup...")
        return True
    else:
        print(f"\n🌐 Cloud Backup (Enabled in config)")
        print("─" * 35)
        response = input("Upload backup to Google Drive? (Y/n): ").strip().lower()
        return response in ['', 'y', 'yes']  # Default to Yes

def show_cloud_settings():
    """Display current cloud backup settings"""
    config = load_config()
    cloud = config['cloud_backup']
    
    print(f"\n☁️ Current Cloud Backup Settings:")
    print(f"   • Enabled: {'Yes ✅' if cloud['enabled'] else 'No ❌'}")
    print(f"   • Auto-upload: {'Yes ✅' if cloud['auto_upload'] else 'No ⚙️'}")
    print(f"   • Destination: Google Drive/Upstalua/")

def update_cloud_settings():
    """Allow user to update cloud backup settings"""
    config = load_config()
    current = config['cloud_backup']
    
    print(f"\n⚙️  Cloud Backup Settings")
    print("─" * 25)
    
    # Toggle enabled
    enabled = input(f"Enable cloud backup? (Y/n): ").strip().lower()
    new_enabled = enabled in ['', 'y', 'yes']
    
    if new_enabled:
        # Toggle auto-upload
        auto = input(f"Auto-upload after backup? (y/N): ").strip().lower()
        new_auto = auto in ['y', 'yes']
    else:
        new_auto = False
    
    new_settings = {
        'enabled': new_enabled,
        'auto_upload': new_auto
    }
    
    # Save updated settings
    if save_config(config['steam_path'], config['appids'], new_settings):
        print("✅ Cloud settings updated!")
        show_cloud_settings()
        return True
    else:
        print("❌ Failed to update settings")
        return False

# =============================================================================
# Windows RClone Download and Setup
# =============================================================================

def download_rclone_windows():
    """Download and extract rclone for Windows"""
    print("📥 Downloading rclone for Windows...")
    
    # Latest rclone Windows 64-bit download URL
    rclone_version = "1.72.0"
    url = f"https://github.com/rclone/rclone/releases/latest/download/rclone-v{rclone_version}-windows-amd64.zip"
    download_path = os.path.join(RCLONE_DIR, "rclone.zip")
    
    try:
        # Create rclone directory
        os.makedirs(RCLONE_DIR, exist_ok=True)
        
        # Download rclone
        print(f"   Downloading from: {url}")
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded += len(chunk)
                    f.write(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"   Progress: {percent:.1f}%", end='\r')
        
        print("\n✅ Download completed")
        
        # Extract rclone
        print("📦 Extracting rclone...")
        with zipfile.ZipFile(download_path, 'r') as zip_ref:
            # Extract only rclone.exe
            for file_info in zip_ref.filelist:
                if file_info.filename.endswith('rclone.exe'):
                    zip_ref.extract(file_info, RCLONE_DIR)
                    # Rename to our expected location
                    extracted_path = os.path.join(RCLONE_DIR, file_info.filename)
                    if extracted_path != RCLONE_EXE:
                        if os.path.exists(RCLONE_EXE):
                            os.remove(RCLONE_EXE)
                        os.rename(extracted_path, RCLONE_EXE)
        
        # Clean up zip file
        try:
            os.remove(download_path)
            # Remove any extracted folders
            for item in os.listdir(RCLONE_DIR):
                if item != "rclone.exe" and item != "rclone.conf":
                    item_path = os.path.join(RCLONE_DIR, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
        except Exception as e:
            print(f"⚠️  Cleanup warning: {e}")
        
        # Verify rclone works
        if verify_rclone():
            print("✅ RClone setup completed successfully!")
            return True
        else:
            print("❌ RClone verification failed")
            return False
        
    except Exception as e:
        print(f"❌ Failed to download rclone: {e}")
        # Clean up on error
        if os.path.exists(download_path):
            try:
                os.remove(download_path)
            except:
                pass
        return False

def verify_rclone():
    """Verify that rclone works"""
    try:
        result = subprocess.run([RCLONE_EXE, 'version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def get_rclone_command():
    """Get the rclone command to use (local or system)"""
    if os.path.exists(RCLONE_EXE):
        return RCLONE_EXE
    else:
        return "rclone"  # Use system rclone if available

def is_rclone_installed():
    """Check if rclone is available (local or system)"""
    # Check local rclone first
    if os.path.exists(RCLONE_EXE) and verify_rclone():
        return True
    
    # Check system rclone
    try:
        subprocess.run(['rclone', 'version'], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False

def ensure_rclone_installed():
    """Ensure rclone is installed, download if necessary"""
    if is_rclone_installed():
        return True
    
    print("🔍 RClone not found. Downloading automatically...")
    return download_rclone_windows()

# =============================================================================
# RClone Auto-Configuration for Google Drive
# =============================================================================

def check_remote_exists(remote_name):
    """Check if a specific remote exists in rclone config"""
    if not os.path.exists(RCLONE_CONFIG_PATH):
        return False
    
    try:
        rclone_cmd = get_rclone_command()
        cmd = [rclone_cmd, 'listremotes', '--config', RCLONE_CONFIG_PATH]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        return f"{remote_name}:" in result.stdout
    except:
        return False

def setup_google_drive_remote():
    """Automatically setup Google Drive remote for rclone"""
    print("🌐 Setting up Google Drive backup...")
    
    # Ensure rclone is installed
    if not ensure_rclone_installed():
        return False
    
    # Check if remote already exists
    if check_remote_exists("gdrive"):
        print("✅ Google Drive remote already configured")
        return True
    
    print("🔐 Configuring Google Drive access...")
    print("   This will open your browser for Google authentication")
    
    try:
        rclone_cmd = get_rclone_command()
        cmd = [
            rclone_cmd, 'config', 'create',
            'gdrive',
            'drive',
            '--config', RCLONE_CONFIG_PATH
        ]
        
        # Start the configuration process
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print("\n📋 RClone Configuration Instructions:")
        print("   1. When asked 'Use auto config?' type: n")
        print("   2. A browser will open - log into your Google account")
        print("   3. Copy the authorization code and paste it back here")
        print("   4. When asked 'Configure this as a team drive?' type: n")
        print("   5. When asked 'y/e/d>:' type: y")
        print("\nPlease complete the authentication in the browser window...")
        
        # Wait for completion with timeout
        try:
            stdout, stderr = process.communicate(timeout=300)  # 5 minute timeout for manual config
            if process.returncode == 0:
                print("✅ Google Drive configured successfully!")
                return True
            else:
                print(f"❌ Configuration failed. Return code: {process.returncode}")
                if stderr:
                    print(f"Error: {stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("⏰ Configuration timed out. Please try again.")
            process.kill()
            return False
            
    except Exception as e:
        print(f"❌ Error configuring Google Drive: {e}")
        return False

def create_gdrive_folder():
    """Create Upstalua folder in Google Drive"""
    try:
        rclone_cmd = get_rclone_command()
        cmd = [rclone_cmd, 'mkdir', GOOGLE_DRIVE_REMOTE, '--config', RCLONE_CONFIG_PATH]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ Created Upstalua folder in Google Drive")
            return True
        else:
            # Folder might already exist, which is fine
            if "already exists" in result.stderr or "directory not found" in result.stderr:
                print("✅ Upstalua folder already exists in Google Drive")
                return True
            else:
                print(f"⚠️  Note: {result.stderr}")
                return True
            
    except subprocess.TimeoutExpired:
        print("❌ Timeout creating Google Drive folder")
        return False
    except Exception as e:
        print(f"❌ Error creating Google Drive folder: {e}")
        return False

def backup_to_cloud():
    """Backup local backup folder to Google Drive"""
    print("📤 Uploading backup to Google Drive...")
    
    try:
        rclone_cmd = get_rclone_command()
        cmd = [
            rclone_cmd, 'sync',
            BACKUP_FOLDER,
            GOOGLE_DRIVE_REMOTE,
            '--config', RCLONE_CONFIG_PATH,
            '--progress',
            '--transfers', '4',
            '--checkers', '8',
            '--create-empty-src-dirs'
        ]
        
        # Run with progress display
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Display progress in real-time
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                # Filter for important progress lines
                if any(x in output for x in ['Transferred:', 'Checks:', 'Elapsed time:', 'Transferring:']):
                    print(f"   {output.strip()}")
        
        return process.returncode == 0
            
    except Exception as e:
        print(f"❌ Error during cloud backup: {e}")
        return False

def verify_cloud_backup():
    """Verify cloud backup contents"""
    print("🔍 Verifying cloud backup...")
    
    try:
        rclone_cmd = get_rclone_command()
        
        # Count local files
        local_files = []
        for root, dirs, files in os.walk(BACKUP_FOLDER):
            for file in files:
                local_files.append(os.path.relpath(os.path.join(root, file), BACKUP_FOLDER))
        
        # Count cloud files
        cmd = [rclone_cmd, 'ls', GOOGLE_DRIVE_REMOTE, '--config', RCLONE_CONFIG_PATH]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print("⚠️  Could not list cloud files")
            return False
        
        cloud_files = [line.split(' ', 1)[1] for line in result.stdout.strip().split('\n') if line]
        
        print(f"📊 Backup Summary:")
        print(f"   📁 Local files: {len(local_files)}")
        print(f"   ☁️ Cloud files: {len(cloud_files)}")
        
        if len(local_files) <= len(cloud_files):
            print("✅ Backup verification successful!")
        else:
            print("⚠️  Some files may not have been uploaded")
        
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ Timeout verifying cloud backup")
        return False
    except Exception as e:
        print(f"⚠️  Could not verify backup: {e}")
        return False

def auto_cloud_backup():
    """Automatically backup to Google Drive"""
    if not os.path.exists(BACKUP_FOLDER):
        print("❌ No backup folder found. Run local backup first.")
        return False
    
    print("\n🌐 Starting cloud backup to Google Drive...")
    
    # Setup Google Drive remote
    if not setup_google_drive_remote():
        return False
    
    # Create Upstalua folder in Google Drive
    if not create_gdrive_folder():
        return False
    
    # Perform the backup
    print("📤 Uploading to Google Drive/Upstalua...")
    success = backup_to_cloud()
    
    if success:
        print("✅ Cloud backup completed!")
        verify_cloud_backup()
        return True
    return False

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
            for filename, appid, game_name in skipped:
                game_display = format_game_display(appid, game_name)
                print(f"   ✅ {filename}")
                print(f"      🎮 {game_display}")
        else:
            # For stats: group by AppID
            skipped_by_appid = {}
            for file, appid, game_name in skipped:
                skipped_by_appid.setdefault((appid, game_name), []).append(file)
            
            for (appid, game_name), files in sorted(skipped_by_appid.items()):
                game_display = format_game_display(appid, game_name)
                print(f"   🎮 {game_display}: {len(files)} unchanged files")
    
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
    print(f"\n🎯 Local Backup Complete!")
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
    
    print(f"\n📊 Local Backup Results:")
    print(f"   • Plugin files (.lua): {'✅ Success' if plugins_ok else '❌ Failed'}")
    print(f"   • Statistics files (.bin): {'✅ Success' if stats_ok else '❌ Failed'}")

# =============================================================================
# Main Execution
# =============================================================================

def main():
    """Main execution flow"""
    print("🎮 Upstalua - Steam Backup Manager (Windows)")
    print("═" * 65)
    
    # Load config early to show settings
    config = load_config()
    cloud_enabled = config['cloud_backup']['enabled']
    auto_upload = config['cloud_backup']['auto_upload']
    
    if cloud_enabled:
        cloud_status = "Auto-upload ✅" if auto_upload else "Manual upload ⚙️"
        print(f"☁️ Cloud backup: {cloud_status}")
    
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
        old_path = config.get('steam_path', '')
        config_updated = should_update_config(steam_path, old_path, detected_appids, existing_appids_dict)
        
        if config_updated:
            if not save_config(steam_path, merged_appids_dict):
                print("❌ Failed to save configuration")
                return
        
        # Run local backups
        run_backup(steam_path, merged_appids_dict, detected_appids, existing_appids_dict, config_updated)
        
        # Smart Cloud Backup based on config
        if cloud_enabled:
            if prompt_cloud_backup():
                if auto_cloud_backup():
                    print("\n🎉 All backups completed successfully!")
                    print("   📍 Local backup: ./backup/")
                    print("   ☁️ Cloud backup: Google Drive/Upstalua/")
                else:
                    print("\n⚠️  Local backup completed, but cloud backup failed")
            else:
                print("⏭️  Skipping cloud backup")
        else:
            print("⏭️  Cloud backup disabled in config")
    
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