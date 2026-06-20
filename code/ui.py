import os
import sys
import json
import glob
import subprocess
import threading
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Button, Card, CardContent, CardHeader, Column, Grid, Row, Text, Badge, Separator
)

def run_query_background():
    def worker():
        subprocess.run([sys.executable, "flow.py", "Compare top 3 Hugging Face text-generation models sorted by likes."])
    threading.Thread(target=worker, daemon=True).start()

def get_latest_session():
    sessions_dir = "state/sessions"
    if not os.path.exists(sessions_dir):
        return None
    sessions = sorted(glob.glob(f"{sessions_dir}/*"), key=os.path.getmtime, reverse=True)
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
        with open(query_file, "r", encoding="utf-8") as f:
            data["query"] = f.read().strip()
            
    # Screenshots
    browser_dirs = glob.glob(os.path.join(latest_dir, "browser", "*"))
    for bd in browser_dirs:
        for img in glob.glob(os.path.join(bd, "*.png")):
            data["screenshots"].append(img)
            
    nodes_dir = os.path.join(latest_dir, "nodes")
    if os.path.exists(nodes_dir):
        for node_file in sorted(glob.glob(f"{nodes_dir}/*.json")):
            with open(node_file, "r", encoding="utf-8") as f:
                try:
                    node = json.load(f)
                    data["nodes"].append(node)
                    
                    res = node.get("result")
                    if res:
                        data["total_cost"] += res.get("cost", 0.0)
                        data["total_time"] += res.get("elapsed_s", 0.0)
                        output = res.get("output", {})
                        
                        if node.get("skill") == "planner" and "planner_dag" == "N/A":
                            data["planner_dag"] = json.dumps(output.get("nodes", []), indent=2)
                        
                        if node.get("skill") == "replay_viewer":
                            # The replay_viewer aggregates all data for us into a clean JSON!
                            if isinstance(output, dict):
                                data["browser_path"] = output.get("browser_path", data["browser_path"])
                                data["browser_actions"] = output.get("browser_actions", [])
                                data["extracted_data"] = output.get("extracted_data", {})
                                data["critic_feedback"] = output.get("critic_feedback", "N/A")
                                
                        if node.get("skill") == "formatter":
                            if isinstance(output, str):
                                data["final_table"] = output
                            elif isinstance(output, dict):
                                data["final_table"] = json.dumps(output, indent=2)
                except Exception as e:
                    pass
    return data

state = get_latest_session()

with PrefabApp() as app:
    with Column(gap=6, css_class="p-8 max-w-5xl mx-auto"):
        with Row(align="center"):
            Text("Agent Orchestration Monitor", variant="h2")
        
        Separator()

        if not state:
            Text("No active sessions found in state/sessions.", variant="muted")
        else:
            with Grid(min_column_width="20rem", gap=6):
                with Card():
                    with CardHeader():
                        Text("1. Original User Goal", variant="h4")
                    with CardContent():
                        Text(state["query"])
                
                with Card():
                    with CardHeader():
                        Text("8. Turn Count & Cost Summary", variant="h4")
                    with CardContent():
                        Text(f"Total Nodes: {len(state['nodes'])}")
                        Text(f"Total Cost: ${state['total_cost']:.4f}")
                        Text(f"Elapsed Time: {state['total_time']:.2f}s")
            
            with Card():
                with CardHeader():
                    Text("2. Planner DAG", variant="h4")
                with CardContent():
                    Text(str(state["planner_dag"]), css_class="whitespace-pre-wrap font-mono text-sm bg-slate-100 p-2 rounded")

            with Grid(min_column_width="20rem", gap=6):
                with Card():
                    with CardHeader():
                        Text("3. Browser Path Chosen", variant="h4")
                    with CardContent():
                        Badge(state["browser_path"])
                
                with Card():
                    with CardHeader():
                        Text("4. Browser Actions Taken", variant="h4")
                    with CardContent():
                        if state["browser_actions"]:
                            for action in state["browser_actions"]:
                                Text(f"Turn {action.get('turn')}: {action.get('action', '')} -> {action.get('outcome')}")
                        else:
                            Text("No actions recorded.", variant="muted")
            
            with Card():
                with CardHeader():
                    Text("5. Screenshots / Logs", variant="h4")
                with CardContent():
                    if state["screenshots"]:
                        for img in state["screenshots"]:
                            Text(f"Saved to: {img}", variant="muted", css_class="text-xs")
                    else:
                        Text("No screenshots available.", variant="muted")
                        
            with Card():
                with CardHeader():
                    Text("6. Extracted Data & Critic", variant="h4")
                with CardContent():
                    Text("Critic Feedback:", variant="h5")
                    Text(str(state["critic_feedback"]), variant="muted")
                    Separator()
                    if state["extracted_data"]:
                        for k, v in state["extracted_data"].items():
                            Text(f"{k}: {v}")
                    else:
                        Text("No extracted data.", variant="muted")
                        
            with Card():
                with CardHeader():
                    Text("7. Final Output (Formatter)", variant="h4")
                with CardContent():
                    Text(str(state["final_table"]), css_class="whitespace-pre-wrap font-mono text-sm")

            with Card():
                with CardHeader():
                    Text("Full Node History", variant="h4")
                with CardContent():
                    with Column(gap=2):
                        for node in state["nodes"]:
                            with Row(gap=2, align="center"):
                                Badge(str(node.get("node_id")))
                                Text(node.get("skill", "Unknown"))
                                Text(f"Status: {node.get('status')}", variant="muted")
