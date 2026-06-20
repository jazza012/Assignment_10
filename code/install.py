import subprocess
import sys

def main():
    print(f"Using python executable: {sys.executable}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "prefab-ui"])
    print("Installation complete.")

if __name__ == "__main__":
    main()
