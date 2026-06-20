import prefab_ui.components as pc
import json

components = dir(pc)
with open("components_api.txt", "w") as f:
    f.write(json.dumps(components, indent=2))
