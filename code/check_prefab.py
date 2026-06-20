import sys
import importlib.util

spec = importlib.util.find_spec("prefab")
result = f"FOUND: {spec.origin}" if spec else "NOT FOUND"
with open("prefab_loc.txt", "w") as f:
    f.write(result)
