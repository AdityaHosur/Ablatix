#!/usr/bin/env python3
"""
Detailed ffmpeg diagnostic - tests actual imports and downloads.
"""

import sys
import os

print("=" * 70)
print("Detailed ffmpeg Diagnostic")
print("=" * 70)

print(f"\nPython version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"Working directory: {os.getcwd()}")

# Test 1: Can we import imageio_ffmpeg?
print("\n[TEST 1] Importing imageio_ffmpeg...")
try:
    import imageio_ffmpeg
    print(f"✓ Imported successfully from: {imageio_ffmpeg.__file__}")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Can we get the ffmpeg path?
print("\n[TEST 2] Getting ffmpeg executable path...")
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg_exe = get_ffmpeg_exe()
    print(f"✓ Got path: {ffmpeg_exe}")
    
    if ffmpeg_exe:
        if os.path.exists(ffmpeg_exe):
            print(f"✓ File exists and is executable")
        else:
            print(f"✗ Path returned but file doesn't exist!")
            print(f"  Trying to download ffmpeg...")
            # Force download
            import imageio_ffmpeg.core
            imageio_ffmpeg.core.download_ffmpeg()
            ffmpeg_exe = get_ffmpeg_exe()
            print(f"  After download: {ffmpeg_exe}")
            if ffmpeg_exe and os.path.exists(ffmpeg_exe):
                print(f"✓ Download successful!")
            else:
                print(f"✗ Download failed or file still missing")
    else:
        print(f"✗ Path is None or empty")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Can we run ffmpeg?
print("\n[TEST 3] Running ffmpeg -version...")
try:
    import subprocess
    from imageio_ffmpeg import get_ffmpeg_exe
    
    ffmpeg_exe = get_ffmpeg_exe()
    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        result = subprocess.run([ffmpeg_exe, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✓ ffmpeg works!")
            first_line = result.stdout.split('\n')[0]
            print(f"  {first_line}")
        else:
            print(f"✗ ffmpeg returned error code {result.returncode}")
            print(f"  stderr: {result.stderr}")
    else:
        print(f"✗ ffmpeg path not available")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("All tests passed! ffmpeg is ready.")
print("=" * 70)
