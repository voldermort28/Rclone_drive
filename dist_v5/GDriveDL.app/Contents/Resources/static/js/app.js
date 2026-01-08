const urlInput = document.getElementById('url');
const outputDirInput = document.getElementById('output_dir');
const downloadBtn = document.getElementById('downloadBtn');
const statusSection = document.getElementById('statusSection');
const statusText = document.getElementById('statusText');
const fileText = document.getElementById('fileText');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const sizeInfo = document.getElementById('sizeInfo');
const logsContent = document.getElementById('logsContent');

let isPolling = false;

downloadBtn.addEventListener('click', async () => {
    const url = urlInput.value.trim();
    if (!url) {
        alert('Please enter a Google Drive URL');
        return;
    }

    const outputDir = outputDirInput.value.trim() || undefined;

    // UI State: Loading
    downloadBtn.disabled = true;
    downloadBtn.querySelector('.btn-text').textContent = 'Starting...';
    statusSection.style.display = 'flex';
    clearLogs();

    try {
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, output_dir: outputDir })
        });

        if (response.ok) {
            startPolling();
        } else {
            const data = await response.json();
            alert('Error: ' + data.error);
            resetUI();
        }
    } catch (e) {
        alert('Connection error');
        resetUI();
    }
});

function startPolling() {
    isPolling = true;
    poll();
}

async function poll() {
    if (!isPolling) return;

    try {
        const response = await fetch('/api/status');
        const state = await response.json();

        updateUI(state);

        if (state.status === 'completed' || state.status === 'error') {
            isPolling = false;
            downloadBtn.disabled = false;
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

    // Logs
    // Clear old logs first if we want to sync completely, but appending is better for UX to not flicker
    // However, the backend sends ALL logs currently to keep it simple.
    logsContent.innerHTML = '';
    state.logs.forEach(log => {
        const div = document.createElement('div');
        div.className = `log-entry log-${log.level.toLowerCase()}`;
        div.textContent = `[${log.level}] ${log.message}`;
        logsContent.appendChild(div);
    });
    logsContent.scrollTop = logsContent.scrollHeight;
}

function resetUI() {
    downloadBtn.disabled = false;
    downloadBtn.querySelector('.btn-text').textContent = 'Start Download';
}

function clearLogs() {
    logsContent.innerHTML = '';
}
