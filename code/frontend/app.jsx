const { useState, useEffect } = React;

function App() {
    const [state, setState] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchState = () => {
        fetch('/api/state')
            .then(res => res.json())
            .then(data => {
                if (Object.keys(data).length > 0) {
                    setState(data);
                } else {
                    setState(null);
                }
            })
            .catch(e => {
                console.error("Failed to fetch state", e);
            })
            .finally(() => {
                setLoading(false);
            });
    };

    useEffect(() => {
        fetchState();
        const interval = setInterval(fetchState, 1000);
        return () => clearInterval(interval);
    }, []);

    const [query, setQuery] = useState("Compare top 3 Hugging Face text-generation models sorted by likes.");

    const runQuery = () => {
        fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        }).catch(e => {
            console.error("Failed to trigger query", e);
        });
    };

    if (loading) return <div className="loading">Initializing Monitor...</div>;

    return (
        <div className="container">
            <header className="header glass">
                <h1>Agent Orchestration Monitor</h1>
                <div className="query-input-container" style={{display: 'flex', gap: '10px', marginTop: '10px'}}>
                    <input 
                        type="text" 
                        value={query} 
                        onChange={(e) => setQuery(e.target.value)} 
                        style={{flex: 1, padding: '10px', borderRadius: '5px', border: '1px solid #ccc', background: 'rgba(255, 255, 255, 0.9)'}}
                    />
                    <button className="run-btn" onClick={runQuery}>Run Query</button>
                </div>
            </header>

            {!state ? (
                <div className="empty-state glass">No active sessions found in state/sessions.</div>
            ) : (
                <main className="dashboard">
                    <div className="grid grid-2">
                        <div className="card glass">
                            <h2>1. Original User Goal</h2>
                            <p>{state.query}</p>
                        </div>
                        <div className="card glass">
                            <h2>8. Turn Count & Cost Summary</h2>
                            <p><strong>Total Nodes:</strong> {state.nodes.length}</p>
                            <p><strong>Total Cost:</strong> ${state.total_cost.toFixed(4)}</p>
                            <p><strong>Elapsed Time:</strong> {state.total_time.toFixed(2)}s</p>
                        </div>
                    </div>

                    <div className="card glass">
                        <h2>2. Planner DAG</h2>
                        <pre className="code-block">{state.planner_dag}</pre>
                    </div>

                    <div className="grid grid-2">
                        <div className="card glass">
                            <h2>3. Browser Path Chosen</h2>
                            <span className="badge">{state.browser_path}</span>
                        </div>
                        <div className="card glass">
                            <h2>4. Browser Actions Taken</h2>
                            {state.browser_actions && state.browser_actions.length > 0 ? (
                                <ul className="action-list">
                                    {state.browser_actions.map((action, i) => (
                                        <li key={i}>
                                            <span className="turn-number">Turn {action.turn}</span>
                                            <span className="action-desc">{action.action || action.outcome}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="muted">No actions recorded.</p>
                            )}
                        </div>
                    </div>

                    <div className="card glass">
                        <h2>5. Screenshots / Logs</h2>
                        {state.screenshots && state.screenshots.length > 0 ? (
                            <div className="screenshot-list">
                                {state.screenshots.map((img, i) => (
                                    <div key={i} className="muted text-xs">Saved to: {img}</div>
                                ))}
                            </div>
                        ) : (
                            <p className="muted">No screenshots available.</p>
                        )}
                    </div>

                    <div className="card glass">
                        <h2>6. Extracted Data & Critic</h2>
                        <h3 className="section-title">Critic Feedback:</h3>
                        <p className="muted critic-feedback">{state.critic_feedback}</p>
                        <hr />
                        {state.extracted_data && Object.keys(state.extracted_data).length > 0 ? (
                            <div className="data-grid">
                                {Object.entries(state.extracted_data).map(([k, v]) => (
                                    <div key={k} className="data-row">
                                        <strong>{k}:</strong> <span>{v}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="muted">No extracted data.</p>
                        )}
                    </div>

                    <div className="card glass">
                        <h2>7. Final Output (Formatter)</h2>
                        <pre className="code-block">{state.final_table}</pre>
                    </div>

                    <div className="card glass">
                        <h2>Full Node History</h2>
                        <div className="node-history">
                            {state.nodes.map((node, i) => (
                                <div key={i} className="node-row">
                                    <span className="badge">{node.node_id}</span>
                                    <span className="node-skill">{node.skill || "Unknown"}</span>
                                    <span className="muted node-status">Status: {node.status}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </main>
            )}
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
