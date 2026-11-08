import json, sys
from pathlib import Path
try: import jsonschema
except ImportError:
    import subprocess; subprocess.check_call([sys.executable, "-m", "pip", "install", "jsonschema"])
    import jsonschema
print("Validation script ready.")
