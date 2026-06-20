function fetchState() {
    fetch('/api/state')
        .then(res => res.json())
        .then(data => {
            renderDashboard(data);
        })
        .catch(e => {
            console.error("Failed to fetch state", e);
        });
}

function runQuery() {
    const queryInput = document.getElementById('queryInput');
    const query = queryInput.value;
    
    fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query })
    }).catch(e => {
        console.error("Failed to trigger query", e);
    });
}

function renderDashboard(state) {
    const content = document.getElementById('content');
    if (!state || Object.keys(state).length === 0) {
        content.innerHTML = '<div class="empty-state glass">No active sessions found in state/sessions.</div>';
        return;
    }

    let actionsHtml = '';
    if (state.browser_actions && state.browser_actions.length > 0) {
        actionsHtml = '<ul class="action-list">' + state.browser_actions.map(action => 
            `<li><span class="turn-number">Turn ${action.turn}</span><span class="action-desc">${action.action || action.outcome}</span></li>`
        ).join('') + '</ul>';
    } else {
        actionsHtml = '<p class="muted">No actions recorded.</p>';
    }

    let screensHtml = '';
    if (state.screenshots && state.screenshots.length > 0) {
        screensHtml = '<div class="screenshot-list">' + state.screenshots.map(img => 
            `<div class="muted text-xs">Saved to: ${img}</div>`
        ).join('') + '</div>';
    } else {
        screensHtml = '<p class="muted">No screenshots available.</p>';
    }

    let dataHtml = '';
    if (state.extracted_data && Object.keys(state.extracted_data).length > 0) {
        dataHtml = '<div class="data-grid">' + Object.entries(state.extracted_data).map(([k, v]) => 
            `<div class="data-row"><strong>${k}:</strong> <span>${v}</span></div>`
        ).join('') + '</div>';
    } else {
        dataHtml = '<p class="muted">No extracted data.</p>';
    }

    let nodesHtml = '';
    if (state.nodes && state.nodes.length > 0) {
        nodesHtml = '<div class="node-history">' + state.nodes.map(node => 
            `<div class="node-row"><span class="badge">${node.node_id}</span><span class="node-skill">${node.skill || "Unknown"}</span><span class="muted node-status">Status: ${node.status}</span></div>`
        ).join('') + '</div>';
    }

    content.innerHTML = `
        <main class="dashboard">
            <div class="grid grid-2">
                <div class="card glass">
                    <h2>1. Original User Goal</h2>
                    <p>${state.query || 'N/A'}</p>
                </div>
                <div class="card glass">
                    <h2>8. Turn Count & Cost Summary</h2>
                    <p><strong>Total Nodes:</strong> ${state.nodes ? state.nodes.length : 0}</p>
                    <p><strong>Total Cost:</strong> $${(state.total_cost || 0).toFixed(4)}</p>
                    <p><strong>Elapsed Time:</strong> ${(state.total_time || 0).toFixed(2)}s</p>
                </div>
            </div>

            <div class="card glass">
                <h2>2. Planner DAG</h2>
                <pre class="code-block">${state.planner_dag || 'N/A'}</pre>
            </div>

            <div class="grid grid-2">
                <div class="card glass">
                    <h2>3. Browser Path Chosen</h2>
                    <span class="badge">${state.browser_path || 'N/A'}</span>
                </div>
                <div class="card glass">
                    <h2>4. Browser Actions Taken</h2>
                    ${actionsHtml}
                </div>
            </div>

            <div class="card glass">
                <h2>5. Screenshots / Logs</h2>
                ${screensHtml}
            </div>

            <div class="card glass">
                <h2>6. Extracted Data & Critic</h2>
                <h3 class="section-title">Critic Feedback:</h3>
                <p class="muted critic-feedback">${state.critic_feedback || 'N/A'}</p>
                <hr />
                ${dataHtml}
            </div>

            <div class="card glass">
                <h2>7. Final Output (Formatter)</h2>
                <pre class="code-block">${state.final_table || 'N/A'}</pre>
            </div>

            <div class="card glass">
                <h2>Full Node History</h2>
                ${nodesHtml}
            </div>
        </main>
    `;
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById('runBtn').addEventListener('click', runQuery);
    fetchState();
    setInterval(fetchState, 1000);
});
