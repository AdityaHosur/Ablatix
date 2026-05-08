import sys
from pathlib import Path
# Ensure backend package is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remediation import mask_text, detect_text

samples = [
    "This is harmless text.",
    "I hate you",
    "Fuck you and your motherf***er friend",
    "shut the fuck up",
    "This contains the word asshole in it",
]

for s in samples:
    print("ORIGINAL:", s)
    print("DETECTED:", detect_text(s))
    print("MASKED:", mask_text(s))
    print("---")
