import urllib.request

files = [
    "examples/mini/hello_world.py",
    "examples/todo/app.py",
    "src/prefab/__init__.py"
]

for f in files:
    url = f"https://raw.githubusercontent.com/PrefectHQ/prefab/main/{f}"
    content = urllib.request.urlopen(url).read().decode("utf-8")
    name = f.replace("/", "_")
    with open(f"prefab_{name}", "w", encoding="utf-8") as out:
        out.write(content)

print("Downloaded.")
