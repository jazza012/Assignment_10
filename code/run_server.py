import subprocess
import sys

def main():
    try:
        # Try running prefab CLI
        subprocess.check_call([sys.executable, "-m", "prefab", "serve", "ui.py"])
    except Exception as e:
        print(f"Failed to serve: {e}")

if __name__ == "__main__":
    main()
