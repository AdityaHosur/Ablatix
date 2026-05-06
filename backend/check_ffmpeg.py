#!/usr/bin/env python3
"""
Quick diagnostic script to verify ffmpeg is properly installed.
Run this to troubleshoot audio processing issues.
"""

import shutil
import os
import sys

print("=" * 60)
print("ffmpeg Environment Check")
print("=" * 60)

# Check 1: imageio_ffmpeg module
print("\n1. Checking imageio_ffmpeg module...")
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    exe_path = get_ffmpeg_exe()
    if exe_path and os.path.exists(exe_path):
        print(f"   ✓ imageio_ffmpeg installed")
        print(f"   ✓ ffmpeg binary at: {exe_path}")
    else:
        print(f"   ✗ imageio_ffmpeg exists but binary not found")
except ImportError as e:
    print(f"   ✗ imageio_ffmpeg NOT installed: {e}")
    print(f"   → Run: pip install imageio-ffmpeg")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Check 2: System ffmpeg
print("\n2. Checking system ffmpeg...")
ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path:
    print(f"   ✓ System ffmpeg found at: {ffmpeg_path}")
else:
    print(f"   ✗ System ffmpeg NOT found")
    print(f"   → Install ffmpeg manually or via imageio-ffmpeg")

# Check 3: Final resolution
print("\n3. Final ffmpeg resolution...")
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    candidate = get_ffmpeg_exe()
    if candidate and os.path.exists(candidate):
        print(f"   ✓ Would use: {candidate}")
    else:
        candidate = shutil.which("ffmpeg")
        if candidate:
            print(f"   ✓ Would use system ffmpeg: {candidate}")
        else:
            print(f"   ✗ No ffmpeg available!")
except Exception:
    candidate = shutil.which("ffmpeg")
    if candidate:
        print(f"   ✓ Would use system ffmpeg: {candidate}")
    else:
        print(f"   ✗ No ffmpeg available!")

print("\n" + "=" * 60)
print("Fix: If ffmpeg is NOT found, run:")
print("  pip install imageio-ffmpeg")
print("Then restart the backend server.")
print("=" * 60)
