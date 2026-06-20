import sqlite3
import json
db = sqlite3.connect('d:/EAG3/Assignment_9/llm_gatewayV9/gateway_v8.db')
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute('SELECT id, provider, error, attempted FROM calls ORDER BY id DESC LIMIT 5').fetchall()]
print(json.dumps(rows, indent=2))
