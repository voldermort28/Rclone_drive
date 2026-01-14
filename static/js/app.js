const urlInput = document.getElementById('url');
const outputDirInput = document.getElementById('output_dir');
const browseBtn = document.getElementById('browseBtn');
const downloadBtn = document.getElementById('downloadBtn');
const statusSection = document.getElementById('statusSection');
const statusText = document.getElementById('statusText');
const fileText = document.getElementById('fileText');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const sizeInfo = document.getElementById('sizeInfo');
const filesListBody = document.getElementById('filesListBody');


let isPolling = false;

// Directory Picker
browseBtn.addEventListener('click', async () => {
    if (!window.pywebview || !window.pywebview.api) {
        alert('Directory picker relies on app backend. Build and run app to test.');
        return;
    }
    const path = await window.pywebview.api.choose_directory();
    if (path) {
        outputDirInput.value = path;
    }
});

// Allow clicking the input itself too
outputDirInput.addEventListener('click', () => {
    browseBtn.click();
});

downloadBtn.addEventListener('click', async () => {
    // If currently downloading (Stop mode)
    if (downloadBtn.classList.contains('btn-stop')) {
        try {
            await fetch('/api/stop', { method: 'POST' });
            downloadBtn.disabled = true;
            downloadBtn.querySelector('.btn-text').textContent = 'Stopping...';
        } catch (e) {
            console.error(e);
        }
        return;
    }

    const urls = urlInput.value.trim();
    if (!urls) {
        statusText.textContent = 'Please enter at least one URL';
        statusText.style.color = '#ef4444';
        return;
    }

    try {
        isPolling = true;
        downloadBtn.disabled = false;
        downloadBtn.classList.remove('btn-primary');
        downloadBtn.classList.add('btn-stop');
        // downloadBtn.style.backgroundColor = '#ef4444'; // Removed: Handled by CSS class

        try {
            downloadBtn.querySelector('.btn-text').textContent = 'STOP';
        } catch (err) {
            console.error(err);
        }

        clearFiles();
        statusText.textContent = 'Initializing...';
        statusText.style.color = '#f8fafc';
        statusSection.style.display = 'flex';

        // DEBUG: Step 2
        statusText.textContent = "Debug: Preparing Payload...";
        const outputDir = outputDirInput.value;
        const payloadData = { url: urls, output_dir: outputDir };

        // DEBUG: Step 3
        statusText.textContent = "Debug: Sending Request (XHR)...";

        // Use XMLHttpRequest instead of fetch to avoid stricter syntax checks in some WebNodes
        await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/api/download", true);
            xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");

            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        resolve(JSON.parse(xhr.responseText));
                    } else {
                        try {
                            const err = JSON.parse(xhr.responseText);
                            const errorObj = new Error(err.error || 'Request failed');
                            if (err.trace) {
                                errorObj.stack = err.trace; // HACK: Replace client stack with server trace
                                errorObj.message += " (See Trace)";
                            }
                            reject(errorObj);
                        } catch (e) {
                            reject(new Error('Request failed with status ' + xhr.status + ': ' + xhr.responseText.substring(0, 100)));
                        }
                    }
                }
            };

            xhr.onerror = function () {
                reject(new Error('Network request failed completely'));
            };

            xhr.send(JSON.stringify(payloadData));
        });

        // DEBUG: Step 5
        statusText.textContent = "Debug: Starting Poll...";
        poll();

    } catch (e) {
        console.error(e);
        isPolling = false;
        resetUI();

        // Get User Agent for context
        const ua = navigator.userAgent;

        let errorHtml = `<div style="color:#ef4444; font-weight:bold; margin-bottom:5px;">${e.message}</div>`;
        if (e.message.includes("Server Error")) {
            // If we have trace in the error message, or if e contains it?
            // Since we throw new Error(err.error), the trace might be lost unless we attach it.
            // We can't attach extra props to Error easily in compact code, but let's assume the user sees the message.
            // Actually, let's update the XHR reject logic to include trace.
        }

        statusText.innerHTML = `
            <div style="text-align:left; background: #333; padding: 10px; border-radius: 4px; overflow: auto; max-height: 400px;">
                ${errorHtml}
                <div style="color:#aaa; font-family:monospace; font-size: 0.8em; white-space: pre;">${e.stack || 'No client stack'}</div>
            </div>
        `;
    }
});

function startPolling() {
    isPolling = true;
    poll();
}

async function poll() {
    if (!isPolling) return;

    try {
        const state = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "/api/status", true);
            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        try {
                            resolve(JSON.parse(xhr.responseText));
                        } catch (e) { reject(e); }
                    } else {
                        reject(new Error('Poll failed'));
                    }
                }
            };
            xhr.send();
        });

        updateUI(state);

        if (state.status === 'completed' || state.status === 'error') {
            isPolling = false;
            isPolling = false;
            resetUI();
            downloadBtn.querySelector('.btn-text').textContent = state.status === 'completed' ? 'Download Another' : 'Retry';
        } else {
            setTimeout(poll, 1000);
        }
    } catch (e) {
        console.error('Polling error', e);
        isPolling = false;
    }
}

function updateUI(state) {
    statusText.textContent = state.message;
    if (state.status === 'error') {
        statusText.style.color = '#ef4444';
    } else if (state.status === 'completed') {
        statusText.style.color = '#10b981';
    } else {
        statusText.style.color = '#f8fafc';
    }

    fileText.textContent = state.file || '';

    // Progress
    let percent = state.progress;
    if (percent < 0) {
        // Indeterminate
        progressBar.style.width = '100%';
        progressBar.classList.add('indeterminate');
        progressPercent.textContent = '...';
    } else {
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = percent + '%';
        progressPercent.textContent = Math.round(percent) + '%';
    }

    const downloaded = (state.downloaded_size / 1024 / 1024).toFixed(2);
    const total = state.total_size ? (state.total_size / 1024 / 1024).toFixed(2) : '?';
    sizeInfo.textContent = `${downloaded}MB / ${total}MB`;

    // Render Files Table
    renderFiles(state.files);
}

function renderFiles(files) {
    if (!files) return;

    filesListBody.innerHTML = '';
    files.forEach((f, index) => {
        const row = document.createElement('tr');

        let statusHtml = '';
        if (f.status === 'downloading') {
            const pct = Math.round(f.progress || 0);
            statusHtml = `
                <div style="font-size:0.75rem; margin-bottom:2px;">${pct}%</div>
                <div class="tbl-progress-bar">
                    <div class="tbl-progress-fill" style="width: ${pct}%"></div>
                </div>
            `;
        } else if (f.status === 'completed') {
            statusHtml = '<span class="status-badge status-completed">Completed</span>';
        } else if (f.status === 'skipped') {
            statusHtml = '<span class="status-badge status-skipped">Skipped</span>';
        } else if (f.status === 'stopped') {
            statusHtml = '<span class="status-badge status-error">Stopped</span>';
        } else if (f.status === 'error') {
            statusHtml = `<span class="status-badge status-error" title="${f.message || ''}">Error</span>`;
        } else {
            statusHtml = `<span class="status-badge">${f.status}</span>`;
        }

        const sizeStr = f.size ? (f.size / 1024 / 1024).toFixed(2) + ' MB' : '-';

        row.innerHTML = `
            <td>${index + 1}</td>
            <td>
                <div class="file-row-name">
                    <span class="file-icon">📄</span>
                    ${f.name}
                    ${f.status === 'error' && f.message ? `<div style="color:#ef4444; font-size:0.75rem; margin-left:24px;">${f.message}</div>` : ''}
                </div>
            </td>
            <td>${sizeStr}</td>
            <td>${statusHtml}</td>
        `;
        filesListBody.appendChild(row);
    });
}

function resetUI() {
    downloadBtn.disabled = false;
    downloadBtn.classList.remove('btn-stop');
    downloadBtn.classList.add('btn-primary');
    // downloadBtn.style.backgroundColor = ''; // Removed: Handled by CSS class
    downloadBtn.querySelector('.btn-text').textContent = 'Start Download';
}

function clearFiles() {
    filesListBody.innerHTML = '';
}
