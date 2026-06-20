import os
import json
import glob
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

def get_latest_session():
    sessions_dir = "state/sessions"
    if not os.path.exists(sessions_dir):
        return None
    sessions = sorted(glob.glob(f"{sessions_dir}/*"), key=os.path.getctime, reverse=True)
    if not sessions:
        return None
    
    latest_dir = sessions[0]
    data = {
        "sid": os.path.basename(latest_dir),
        "nodes": [],
        "query": "N/A",
        "browser_path": "N/A",
        "browser_actions": [],
        "extracted_data": {},
        "final_table": "N/A",
        "total_cost": 0.0,
        "total_time": 0.0,
        "planner_dag": "N/A",
        "screenshots": [],
        "critic_feedback": "N/A"
    }
    
    # User goal
    query_file = os.path.join(latest_dir, "query.txt")
    if os.path.exists(query_file):
        try:
            with open(query_file, "r", encoding="utf-8") as f:
                data["query"] = f.read().strip()
        except UnicodeDecodeError:
            with open(query_file, "r", encoding="cp1252") as f:
                data["query"] = f.read().strip()
            
    # Screenshots
    browser_dirs = glob.glob(os.path.join(latest_dir, "browser", "*"))
    for bd in browser_dirs:
        for img in glob.glob(os.path.join(bd, "*.png")):
            data["screenshots"].append(img.replace("\\", "/"))
            
    nodes_dir = os.path.join(latest_dir, "nodes")
    if os.path.exists(nodes_dir):
        for node_file in sorted(glob.glob(f"{nodes_dir}/*.json")):
            try:
                with open(node_file, "r", encoding="utf-8") as f:
                    node = json.load(f)
            except UnicodeDecodeError:
                with open(node_file, "r", encoding="cp1252") as f:
                    node = json.load(f)
            except Exception as e:
                print(f"Error reading node {node_file}: {e}")
                continue

            try:
                data["nodes"].append(node)
                    
                res = node.get("result")
                if res:
                    data["total_cost"] += res.get("cost", 0.0)
                    data["total_time"] += res.get("elapsed_s", 0.0)
                    output = res.get("output", {})
                    
                    if node.get("skill") == "planner" and data["planner_dag"] == "N/A":
                        data["planner_dag"] = json.dumps(output.get("nodes", []), indent=2)
                    
                    if node.get("skill") == "browser":
                        if isinstance(output, dict):
                            data["browser_path"] = output.get("path", data["browser_path"])
                            actions = output.get("actions", [])
                            if actions:
                                data["browser_actions"].extend(actions)
                                
                    if node.get("skill") == "distiller":
                        if isinstance(output, dict) and "fields" in output:
                            data["extracted_data"] = output["fields"]
                            
                    if node.get("skill") == "critic":
                        if isinstance(output, dict) and "rationale" in output:
                            data["critic_feedback"] = output["rationale"]
                    
                    if node.get("skill") == "replay_viewer":
                        if isinstance(output, dict):
                            data["browser_path"] = output.get("browser_path", data["browser_path"])
                            data["browser_actions"] = output.get("browser_actions", data["browser_actions"])
                            data["extracted_data"] = output.get("extracted_data", data["extracted_data"])
                            data["critic_feedback"] = output.get("critic_feedback", data["critic_feedback"])
                            
                    if node.get("skill") == "formatter":
                        if isinstance(output, str):
                            data["final_table"] = output
                        elif isinstance(output, dict):
                            data["final_table"] = output.get("final_answer", json.dumps(output, indent=2))
            except Exception as e:
                print(f"Error parsing node {node_file}: {e}")
    return data

def run_orchestrator(query: str):
    def worker():
        import sys
        subprocess.run([sys.executable, "flow.py", query])
    threading.Thread(target=worker, daemon=True).start()

class APIHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/state':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            state = get_latest_session()
            response = json.dumps(state) if state else "{}"
            self.wfile.write(response.encode('utf-8'))
        else:
            # Serve static files from the frontend directory
            parsed_path = urllib.parse.urlparse(self.path)
            req_path = parsed_path.path
            if req_path == '/':
                req_path = '/index.html'
            
            filepath = os.path.join(os.path.dirname(__file__), 'frontend', req_path.lstrip('/'))
            
            if os.path.exists(filepath) and not os.path.isdir(filepath):
                self.send_response(200)
                if filepath.endswith('.html'):
                    self.send_header('Content-type', 'text/html')
                elif filepath.endswith('.css'):
                    self.send_header('Content-type', 'text/css')
                elif filepath.endswith('.jsx') or filepath.endswith('.js'):
                    self.send_header('Content-type', 'application/javascript')
                self.end_headers()
                
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        if self.path == '/api/run':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(post_data)
                query = payload.get('query', 'Compare top 3 Hugging Face text-generation models sorted by likes.')
            except json.JSONDecodeError:
                query = 'Compare top 3 Hugging Face text-generation models sorted by likes.'
                
            run_orchestrator(query)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started", "query": query}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    port = 8000
    server = HTTPServer(('localhost', port), APIHandler)
    print(f"Backend Server running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
