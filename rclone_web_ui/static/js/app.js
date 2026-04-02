// ==================== DOM ELEMENTS ====================
const urlInput = document.getElementById('url');
const outputDirInput = document.getElementById('output_dir');
const downloadBtn = document.getElementById('downloadBtn');
const stopBtn = document.getElementById('stopBtn');
const statusSection = document.getElementById('statusSection');
const statusText = document.getElementById('statusText');
const fileText = document.getElementById('fileText');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const sizeInfo = document.getElementById('sizeInfo');
const filesListBody = document.getElementById('filesListBody');

let isPolling = false;

// ==================== SMART URL HELPERS ====================
function extractDriveId(url) {
    // Strip query params like ?fbclid=... , ?usp=sharing etc.
    url = url.split('?')[0].split('#')[0];
    var m = url.match(/\/folders\/([A-Za-z0-9_-]{15,})/);
    if (m) return m[1];
    m = url.match(/\/d\/([A-Za-z0-9_-]{15,})/);
    if (m) return m[1];
    return null;
}

function convertUrlsToRclone(rawText) {
    return rawText.split('\n').map(function (line) {
        line = line.trim();
        if (!line) return '';
        if (line.indexOf('drive.google.com') > -1) {
            var id = extractDriveId(line);
            if (id) return 'gc:' + id;
        }
        return line; // Already in gc:xxx format or other remote
    }).filter(Boolean).join('\n');
}

function convertSingleUrl(raw) {
    raw = raw.trim();
    if (raw.indexOf('drive.google.com') > -1) {
        var id = extractDriveId(raw);
        if (id) return 'gc:' + id;
    }
    return raw;
}

// ==================== TAB SWITCHING ====================
document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
        var tabName = this.getAttribute('data-tab');

        // Update active button
        document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');

        // Update active content
        document.querySelectorAll('.tab-content').forEach(function (c) { c.classList.remove('active'); });
        var target = document.getElementById('tab-' + tabName);
        if (target) target.classList.add('active');

        // Load content for specific tabs
        if (tabName === 'config') {
            loadConfig();
            loadSAInfo();
        } else if (tabName === 'history') {
            loadQueue();
            loadHistory();
        }
    });
});

// ==================== TRANSFER LOGIC ====================
downloadBtn.addEventListener('click', async () => {
    const rawUrls = urlInput.value.trim();
    if (!rawUrls) {
        alert('Vui lòng nhập ít nhất 1 link nguồn');
        return;
    }

    try {
        // Convert raw URLs to rclone format
        const convertedUrls = convertUrlsToRclone(rawUrls);
        let outputDir = convertSingleUrl(outputDirInput.value.trim());

        if (!outputDir) {
            alert('Vui lòng nhập Destination (Nơi nhận)');
            return;
        }

        // If "Wrap in Parent Folder" is checked, try to get folder name
        const wrapCheckbox = document.getElementById('wrapParentFolder');
        if (wrapCheckbox && wrapCheckbox.checked) {
            const lines = rawUrls.split('\n').filter(l => l.trim());
            // Only wrap if there's a single source (not multi-source)
            if (lines.length === 1) {
                const rawLine = lines[0].trim();
                if (rawLine.indexOf('drive.google.com') > -1) {
                    try {
                        downloadBtn.querySelector('.btn-text').textContent = 'Đang lấy tên folder...';
                        downloadBtn.disabled = true;
                        const titleResp = await fetch('/api/util/scrape_title?url=' + encodeURIComponent(rawLine));
                        const titleData = await titleResp.json();
                        if (titleData.title) {
                            // Append folder name to destination
                            outputDir = outputDir.replace(/\/+$/, '') + '/' + titleData.title;
                        }
                    } catch (e) {
                        console.warn('Could not scrape title:', e);
                    }
                }
            }
        }

        const payloadData = { url: convertedUrls, output_dir: outputDir };

        const oldText = downloadBtn.querySelector('.btn-text').textContent;
        downloadBtn.querySelector('.btn-text').textContent = "Đang gửi...";
        downloadBtn.disabled = true;

        const resp = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/api/download", true);
            xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");

            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        resolve(JSON.parse(xhr.responseText));
                    } else {
                        reject(new Error('Request failed with status ' + xhr.status));
                    }
                }
            };
            xhr.onerror = function () { reject(new Error('Network request failed completely')); };
            xhr.send(JSON.stringify(payloadData));
        });

        alert(resp.message || 'Đã thêm vào hàng đợi!');

        // Save destination to history
        saveDestHistory(outputDir);

        urlInput.value = ''; // Clear source to allow adding more

        // Cleanup UI button
        downloadBtn.querySelector('.btn-text').textContent = "Thêm vào Queue (Copy)";
        downloadBtn.disabled = false;

        // Force poll to update queue count
        if (!isPolling) {
            isPolling = true;
            poll();
        }
    } catch (e) {
        console.error(e);
        alert("Lỗi khi thêm vào queue: " + e.message);
        downloadBtn.disabled = false;
        downloadBtn.querySelector('.btn-text').textContent = "Thêm vào Queue (Copy)";
    }
});

stopBtn.addEventListener('click', async () => {
    if (!confirm('Bạn có muốn dừng tiến trình ĐANG CHẠY ngay lập tức? (KHÔNG xóa queue)')) return;
    try {
        stopBtn.disabled = true;
        stopBtn.querySelector('.btn-text').textContent = 'Đang dừng...';
        await fetch('/api/stop', { method: 'POST' });
    } catch (e) {
        console.error(e);
        alert('Lỗi khi gửi lệnh dừng!');
    }
});

// ==================== DESTINATION HISTORY ====================
function saveDestHistory(path) {
    // Also save to server-side
    fetch('/api/dest_history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, name: path })
    }).catch(() => { });
}

function showDestDropdown() {
    const dropdown = document.getElementById('destDropdown');
    if (!dropdown) return;

    fetch('/api/dest_history')
        .then(r => r.json())
        .then(items => {
            if (!items || items.length === 0) {
                dropdown.style.display = 'none';
                return;
            }
            dropdown.innerHTML = '';
            items.forEach(item => {
                const row = document.createElement('div');
                row.style.cssText = 'padding:10px 14px; cursor:pointer; font-size:0.85rem; border-bottom: 1px solid var(--border-color); transition: background 0.15s;';
                row.innerHTML = '<div style="color:var(--text-primary); font-weight:500;">' + item.path + '</div>' +
                    '<div style="color:var(--text-muted); font-size:0.75rem;">' + (item.used_at || '') + '</div>';
                row.addEventListener('mouseenter', () => row.style.background = 'rgba(96,165,250,0.1)');
                row.addEventListener('mouseleave', () => row.style.background = 'transparent');
                row.addEventListener('click', () => {
                    outputDirInput.value = item.path;
                    localStorage.setItem('rclone_dest', item.path);
                    dropdown.style.display = 'none';
                });
                dropdown.appendChild(row);
            });
            dropdown.style.display = 'block';
        })
        .catch(() => { });
}

outputDirInput.addEventListener('focus', showDestDropdown);
document.addEventListener('click', function (e) {
    const dropdown = document.getElementById('destDropdown');
    if (dropdown && !outputDirInput.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
    }
});

// ==================== DRIVE EXPLORER ====================
let explorerPath = 'gc:';
let explorerHistory = ['gc:'];

const explorerModal = document.getElementById('driveExplorerModal');
const explorerList = document.getElementById('explorerList');
const explorerBreadcrumb = document.getElementById('explorerBreadcrumb');

document.getElementById('browseDestBtn').addEventListener('click', () => {
    explorerPath = 'gc:';
    explorerHistory = ['gc:'];
    explorerModal.style.display = 'flex';
    loadExplorerDir(explorerPath);
});

document.getElementById('explorerCloseBtn').addEventListener('click', () => {
    explorerModal.style.display = 'none';
});

// Click outside modal to close
explorerModal.addEventListener('click', (e) => {
    if (e.target === explorerModal) explorerModal.style.display = 'none';
});

document.getElementById('explorerSelectBtn').addEventListener('click', () => {
    outputDirInput.value = explorerPath;
    localStorage.setItem('rclone_dest', explorerPath);
    explorerModal.style.display = 'none';
});

document.getElementById('explorerNewFolderBtn').addEventListener('click', async () => {
    const name = prompt('Nhập tên thư mục mới:');
    if (!name || !name.trim()) return;

    const newPath = explorerPath + '/' + name.trim();
    try {
        const btn = document.getElementById('explorerNewFolderBtn');
        btn.textContent = '⏳ Đang tạo...';
        btn.disabled = true;

        const resp = await fetch('/api/mkdir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: newPath })
        });
        const data = await resp.json();

        btn.textContent = '➕ Tạo thư mục mới';
        btn.disabled = false;

        if (data.success) {
            loadExplorerDir(explorerPath); // Refresh
        } else {
            alert('Lỗi tạo thư mục: ' + (data.error || 'Unknown'));
        }
    } catch (e) {
        alert('Lỗi: ' + e.message);
    }
});

function loadExplorerDir(path) {
    explorerPath = path;
    explorerList.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-muted);">⏳ Đang tải...</div>';
    updateBreadcrumb();

    fetch('/api/explore?path=' + encodeURIComponent(path))
        .then(r => r.json())
        .then(items => {
            if (!items || items.length === 0) {
                explorerList.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-muted);">📂 Thư mục trống</div>';
                return;
            }
            explorerList.innerHTML = '';

            // Back button if not root
            if (explorerHistory.length > 1) {
                const backRow = document.createElement('div');
                backRow.style.cssText = 'padding:10px 20px; cursor:pointer; display:flex; align-items:center; gap:10px; border-bottom: 1px solid rgba(255,255,255,.05); transition: background 0.15s;';
                backRow.innerHTML = '<span style="font-size:1.2rem;">⬆️</span><span style="color: #60a5fa; font-weight: 500;">..</span>';
                backRow.addEventListener('mouseenter', () => backRow.style.background = 'rgba(96,165,250,0.08)');
                backRow.addEventListener('mouseleave', () => backRow.style.background = 'transparent');
                backRow.addEventListener('click', () => {
                    explorerHistory.pop();
                    loadExplorerDir(explorerHistory[explorerHistory.length - 1]);
                });
                explorerList.appendChild(backRow);
            }

            items.forEach(item => {
                const row = document.createElement('div');
                row.style.cssText = 'padding:10px 20px; cursor:pointer; display:flex; align-items:center; gap:10px; border-bottom: 1px solid rgba(255,255,255,.05); transition: background 0.15s;';
                row.innerHTML = '<span style="font-size:1.2rem;">📁</span><div><div style="color:var(--text-primary); font-weight: 500;">' + item.Name + '</div>' +
                    '<div style="font-size:0.72rem; color:var(--text-muted);">' + (item.ID || '') + '</div></div>';
                row.addEventListener('mouseenter', () => row.style.background = 'rgba(96,165,250,0.08)');
                row.addEventListener('mouseleave', () => row.style.background = 'transparent');
                row.addEventListener('click', () => {
                    const childPath = path + '/' + item.Name;
                    explorerHistory.push(childPath);
                    loadExplorerDir(childPath);
                });
                explorerList.appendChild(row);
            });
        })
        .catch(e => {
            explorerList.innerHTML = '<div style="text-align:center; padding:30px; color:#ef4444;">❌ Lỗi: ' + e.message + '</div>';
        });
}

function updateBreadcrumb() {
    const bc = document.getElementById('explorerBreadcrumb');
    const parts = explorerPath.split('/');
    let html = '';
    let accumulated = '';
    parts.forEach((part, i) => {
        accumulated += (i > 0 ? '/' : '') + part;
        const thisPath = accumulated;
        if (i > 0) html += ' <span style="color:#475569;">/</span> ';
        html += '<span style="cursor:pointer; color:#60a5fa;" data-path="' + thisPath + '">' + part + '</span>';
    });
    bc.innerHTML = html;

    // Wire up breadcrumb clicks
    bc.querySelectorAll('[data-path]').forEach(el => {
        el.addEventListener('click', () => {
            const p = el.getAttribute('data-path');
            explorerHistory = [p];
            loadExplorerDir(p);
        });
    });
}

// ==================== TRIPLE-CLICK CONFIG AUTH ====================
(function () {
    let clickCount = 0;
    let clickTimer = null;
    const headerLogo = document.getElementById('headerLogo');
    const tabBtnConfig = document.getElementById('tabBtnConfig');

    if (headerLogo && tabBtnConfig) {
        headerLogo.addEventListener('click', () => {
            clickCount++;
            if (clickTimer) clearTimeout(clickTimer);

            if (clickCount >= 3) {
                clickCount = 0;
                // Prompt for password
                const pw = prompt('🔒 Nhập mật khẩu để mở Cấu hình:');
                if (!pw) return;

                fetch('/api/auth', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pw })
                }).then(r => {
                    if (r.ok) {
                        tabBtnConfig.style.display = 'inline-flex';
                        alert('✅ Đã mở khóa tab Cấu hình!');
                    } else {
                        alert('❌ Mật khẩu sai!');
                    }
                }).catch(() => alert('❌ Lỗi kết nối!'));
            }

            clickTimer = setTimeout(() => { clickCount = 0; }, 600);
        });
    }
})();

// ==================== QUEUE & POLLING ====================
async function poll() {
    if (!isPolling) return;

    try {
        const state = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "/api/status", true);
            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        try { resolve(JSON.parse(xhr.responseText)); }
                        catch (e) { reject(e); }
                    } else { reject(new Error('Poll failed')); }
                }
            };
            xhr.send();
        });

        updateUI(state);

        // Auto-refresh queue tab if user is viewing it
        if (document.getElementById('tab-history').classList.contains('active')) {
            loadQueueLight();
        }

        // We always poll if there's an active job or queue exists
        if (state.status === 'idle' && state.queue_count === 0) {
            isPolling = false;
            stopBtn.style.display = 'none';
        } else {
            setTimeout(poll, 2000); // 2 seconds tick
        }
    } catch (e) {
        console.error('Polling error', e);
        isPolling = false;
    }
}

function updateUI(state) {
    if (state.status === 'idle') {
        if (state.queue_count > 0) {
            statusSection.style.display = 'flex';
            statusText.textContent = `Hệ thống đang chuẩn bị chạy job tiếp theo... (Còn ${state.queue_count} job trong Queue)`;
            statusText.style.color = '#f59e0b';
            stopBtn.style.display = 'none';
            progressBar.style.width = '0%';
            progressPercent.textContent = '...';
        }
        return;
    }

    statusSection.style.display = 'flex';
    statusText.textContent = state.message;

    if (state.status === 'error') {
        statusText.style.color = '#ef4444';
        stopBtn.style.display = 'none';
        stopBtn.disabled = false;
        stopBtn.querySelector('.btn-text').textContent = 'Dừng tiến trình đang chạy';
    } else if (state.status === 'completed') {
        statusText.style.color = '#10b981';
        stopBtn.style.display = 'none';
        stopBtn.disabled = false;
        stopBtn.querySelector('.btn-text').textContent = 'Dừng tiến trình đang chạy';
    } else {
        statusText.style.color = '#3b82f6';
        stopBtn.style.display = 'block';
    }

    fileText.textContent = state.file || '';

    let percent = state.progress;
    if (percent < 0) {
        progressBar.style.width = '100%';
        progressBar.classList.add('indeterminate');
        progressPercent.textContent = '...';
    } else {
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = percent + '%';
        progressPercent.textContent = Math.round(percent) + '%';
    }

    sizeInfo.textContent = '';
    renderFiles(state.files);

    const transferConsole = document.getElementById('transferConsole');
    if (transferConsole) {
        if (state.logs && state.logs.length > 0) {
            const logContent = state.logs.map(lg => {
                let color = '#a5b4fc';
                if (lg.level === 'ERROR') color = '#ef4444';
                else if (lg.level === 'WARNING') color = '#f59e0b';
                else if (lg.level === 'DEBUG') color = '#94a3b8';

                const safeMsg = (lg.message || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                return `<span style="color:${color}">[${lg.level}] ${safeMsg}</span>`;
            }).join('\n');

            const isScrolledToBottom = transferConsole.scrollHeight - transferConsole.clientHeight <= transferConsole.scrollTop + 50;
            transferConsole.innerHTML = logContent;

            if (isScrolledToBottom) {
                transferConsole.scrollTop = transferConsole.scrollHeight;
            }
        } else {
            transferConsole.innerHTML = 'Đang chờ dữ liệu console...';
        }
    }
}

function renderFiles(files) {
    if (!files || files.length === 0) {
        filesListBody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Trống</td></tr>';
        return;
    }

    filesListBody.innerHTML = '';
    files.forEach(function (f, index) {
        const row = document.createElement('tr');

        let statusHtml = '';
        if (f.status === 'downloading') {
            const pct = Math.round(f.progress || 0);
            statusHtml =
                '<div style="font-size:0.75rem; margin-bottom:2px;">' + pct + '%</div>' +
                '<div class="tbl-progress-bar">' +
                '<div class="tbl-progress-fill" style="width: ' + pct + '%"></div>' +
                '</div>';
        } else if (f.status === 'completed') {
            statusHtml = '<span class="status-badge status-completed">Hoàn thành</span>';
        } else if (f.status === 'skipped') {
            statusHtml = '<span class="status-badge status-skipped">Bỏ qua</span>';
        } else if (f.status === 'stopped') {
            statusHtml = '<span class="status-badge status-error">Đã dừng</span>';
        } else if (f.status === 'error') {
            statusHtml = '<span class="status-badge status-error" title="' + (f.message || '') + '">Lỗi</span>';
        } else {
            statusHtml = '<span class="status-badge">' + f.status + '</span>';
        }

        row.innerHTML =
            '<td>' + (index + 1) + '</td>' +
            '<td>' +
            '<div class="file-row-name">' +
            '<span class="file-icon">📄</span>' +
            '<span style="word-break: break-all;">' + f.name + '</span>' +
            (f.status === 'error' && f.message ? '<div style="color:#ef4444; font-size:0.75rem; margin-left:24px;">' + f.message + '</div>' : '') +
            '</div>' +
            '</td>' +
            '<td>' + f.progress + '%</td>' +
            '<td>' + statusHtml + '</td>';
        filesListBody.appendChild(row);
    });
}

function clearFiles() {
    filesListBody.innerHTML = '';
}

// ==================== QUEUE UI ====================
function loadQueue() {
    var tbody = document.getElementById('queueListBody');
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px;">Đang tải...</td></tr>';
    loadQueueLight();
}

function loadQueueLight() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/queue", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            renderQueue(JSON.parse(xhr.responseText));
        }
    };
    xhr.send();
}

function renderQueue(records) {
    var tbody = document.getElementById('queueListBody');
    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text-muted);">Không có tiến trình nào đang chờ</td></tr>';
        return;
    }

    tbody.innerHTML = '';
    const nowSecs = Date.now() / 1000;

    records.forEach(function (rec) {
        var row = document.createElement('tr');

        let statusHtml = '';
        let execTimeStr = '';

        if (rec.status === 'delayed') {
            statusHtml = '<span class="status-badge" style="background-color: #f59e0b; color: white;">Lỗi Quota - Chờ</span>';
            // Show countdown
            let diff = Math.round(rec.execute_at - nowSecs);
            if (diff > 0) {
                let h = Math.floor(diff / 3600);
                let m = Math.floor((diff % 3600) / 60);
                execTimeStr = `Còn ${h}h ${m}m`;
            } else {
                execTimeStr = "Đang chuẩn bị chạy...";
            }
        } else {
            statusHtml = '<span class="status-badge" style="background-color: #64748b; color: white;">Đang đợi</span>';
            execTimeStr = "Sẵn sàng";
        }

        var urls = (rec.urls || '').substring(0, 100) + ((rec.urls || '').length > 100 ? '...' : '');

        row.innerHTML =
            '<td><strong style="color: #60a5fa;">' + execTimeStr + '</strong></td>' +
            '<td style="word-break: break-all; max-width: 300px;">' + urls + '</td>' +
            '<td style="word-break: break-all;">' + (rec.dest || 'N/A') + '</td>' +
            '<td>' + statusHtml + '</td>' +
            '<td><button class="btn-secondary" style="padding: 4px 8px; font-size: 12px; border-color: #ef4444; color: #ef4444;" onclick="removeQueue(\'' + rec.id + '\')">Hủy</button></td>';

        tbody.appendChild(row);
    });
}

window.removeQueue = function (id) {
    if (!confirm("Hủy bỏ tiến trình này khỏi hàng đợi?")) return;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/queue/remove", true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            loadQueueLight();
            // Trigger poll to update queue counts quickly
            if (!isPolling) { isPolling = true; poll(); }
        }
    };
    xhr.send(JSON.stringify({ id: id }));
};

// ==================== CONFIG MANAGEMENT ====================
function loadConfig() {
    var editor = document.getElementById('configEditor');
    var statusEl = document.getElementById('configStatus');

    editor.value = 'Đang tải cấu hình...';
    statusEl.textContent = '';
    statusEl.className = 'config-status';

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/config", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                var data = JSON.parse(xhr.responseText);
                editor.value = data.content || '# Chưa có cấu hình';
                statusEl.textContent = '📁 ' + data.path;
                statusEl.className = 'config-status';
            } else {
                editor.value = '# Lỗi tải cấu hình';
                statusEl.textContent = '❌ Lỗi đọc file';
                statusEl.className = 'config-status error';
            }
        }
    };
    xhr.send();
}

document.getElementById('loadConfigBtn').addEventListener('click', loadConfig);

document.getElementById('saveConfigBtn').addEventListener('click', function () {
    var editor = document.getElementById('configEditor');
    var statusEl = document.getElementById('configStatus');
    statusEl.textContent = 'Đang lưu...';
    statusEl.className = 'config-status';

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/config", true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                statusEl.textContent = '✅ Đã lưu cấu hình!';
                statusEl.className = 'config-status success';
            } else {
                statusEl.textContent = '❌ Lỗi lưu cấu hình';
                statusEl.className = 'config-status error';
            }
        }
    };
    xhr.send(JSON.stringify({ content: editor.value }));
});

// ==================== SA MANAGEMENT ====================
var saUploadArea = document.getElementById('saUploadArea');
var saFileInput = document.getElementById('saFileInput');
var saStatus = document.getElementById('saStatus');

saUploadArea.addEventListener('click', () => saFileInput.click());
saUploadArea.addEventListener('dragover', (e) => { e.preventDefault(); saUploadArea.classList.add('drag-over'); });
saUploadArea.addEventListener('dragleave', () => saUploadArea.classList.remove('drag-over'));
saUploadArea.addEventListener('drop', (e) => {
    e.preventDefault(); saUploadArea.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) uploadSAFile(e.dataTransfer.files[0]);
});
saFileInput.addEventListener('change', () => {
    if (saFileInput.files.length > 0) uploadSAFile(saFileInput.files[0]);
});

function uploadSAFile(file) {
    saStatus.textContent = '⏳ Đang upload...';
    saStatus.className = 'config-status';
    var formData = new FormData();
    formData.append('file', file);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sa/upload", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                saStatus.textContent = '✅ Thành công!';
                saStatus.className = 'config-status success';
                loadSAInfo();
            } else {
                saStatus.textContent = '❌ Thất bại!';
                saStatus.className = 'config-status error';
            }
        }
    };
    xhr.send(formData);
}

function loadSAInfo() {
    var saInfo = document.getElementById('saInfo');
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/sa/info", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data.count > 0) {
                saInfo.innerHTML = '🔑 <span class="sa-count">' + data.count + ' SA</span>' +
                    '<span class="sa-clear" onclick="clearSA()">🗑️ Xóa tất cả</span>';
            } else {
                saInfo.innerHTML = '<span style="color: var(--text-muted);">Trống</span>';
            }
        }
    };
    xhr.send();
}

window.clearSA = function () {
    if (!confirm('Xóa tất cả Service Accounts?')) return;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sa/clear", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            saStatus.textContent = '🗑️ Đã xóa';
            saStatus.className = 'config-status';
            loadSAInfo();
        }
    };
    xhr.send();
};

// ==================== INITIALIZATION ====================
window.addEventListener('DOMContentLoaded', () => {
    const savedUrls = localStorage.getItem('rclone_urls');
    const savedDest = localStorage.getItem('rclone_dest');

    if (savedUrls) urlInput.value = savedUrls;
    if (savedDest) outputDirInput.value = savedDest;

    loadSAInfo();
    checkActiveTransfer();
});

async function checkActiveTransfer() {
    try {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/status", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4 && xhr.status === 200) {
                const state = JSON.parse(xhr.responseText);

                if (state.status !== 'idle' || state.queue_count > 0) {
                    isPolling = true;
                    poll();
                }
            }
        };
        xhr.send();
    } catch (e) { }
}

// ==================== HISTORY MANAGEMENT ====================
function loadHistory() {
    var tbody = document.getElementById('historyListBody');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 20px;">Đang tải...</td></tr>';

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/history", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                renderHistory(JSON.parse(xhr.responseText));
            } else {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #ef4444; padding: 20px;">Lỗi tải lịch sử</td></tr>';
            }
        }
    };
    xhr.send();
}

function renderHistory(records) {
    var tbody = document.getElementById('historyListBody');
    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 20px; color: var(--text-muted);">Trống</td></tr>';
        return;
    }

    tbody.innerHTML = '';
    records.forEach(function (rec) {
        var row = document.createElement('tr');

        let statusHtml = '';
        if (rec.status === 'completed') {
            statusHtml = '<span class="status-badge status-completed">Hoàn thành</span>';
        } else if (rec.status === 'error') {
            statusHtml = '<span class="status-badge status-error" title="' + (rec.message || '') + '">Lỗi</span>';
        } else if (rec.status === 'downloading' || rec.status === 'initializing') {
            statusHtml = '<span class="status-badge" style="background-color: #3b82f6; color: white;">Đang tải (' + (rec.progress || 0) + '%)</span>';
        } else {
            statusHtml = '<span class="status-badge">' + rec.status + '</span>';
        }

        var urls = (rec.urls || '').substring(0, 50) + '...';

        row.innerHTML =
            '<td>' + (rec.time || 'N/A') + '</td>' +
            '<td style="word-break: break-all; max-width: 300px;">' + urls + '</td>' +
            '<td style="word-break: break-all;">' + (rec.dest || 'N/A') + '</td>' +
            '<td>' + statusHtml + '</td>';

        tbody.appendChild(row);
    });
}

document.getElementById('clearHistoryBtn').addEventListener('click', function () {
    if (!confirm('Bạn có chắc muốn xóa sạch toàn bộ Lịch sử sao chép không?')) return;

    var tbody = document.getElementById('historyListBody');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 20px;">Đang xóa...</td></tr>';

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/history/clear", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            loadHistory();
        }
    };
    xhr.send();
});

// Save inputs on change
urlInput.addEventListener('input', () => {
    localStorage.setItem('rclone_urls', urlInput.value);
});

outputDirInput.addEventListener('input', () => {
    localStorage.setItem('rclone_dest', outputDirInput.value);
});

// ==================== VERIFY & SYNC LOGIC ====================
const verifySource = document.getElementById('verify_source');
const verifyDest = document.getElementById('verify_dest');
const btnVerifyScan = document.getElementById('btnVerifyScan');
const btnVerifyStop = document.getElementById('btnVerifyStop');
const btnVerifyFix = document.getElementById('btnVerifyFix');
const verifyStatusSection = document.getElementById('verifyStatusSection');
const verifyMessageText = document.getElementById('verifyMessageText');
const verifyMissingCount = document.getElementById('verifyMissingCount');
const verifyDifferCount = document.getElementById('verifyDifferCount');
const verifyErrorCount = document.getElementById('verifyErrorCount');
const verifyListBody = document.getElementById('verifyListBody');

let isVerifyPolling = false;

// Save verify inputs on change
if (verifySource && verifyDest) {
    verifySource.addEventListener('input', () => localStorage.setItem('verify_source', verifySource.value));
    verifyDest.addEventListener('input', () => localStorage.setItem('verify_dest', verifyDest.value));

    // Restore on load
    window.addEventListener('DOMContentLoaded', () => {
        const vSrc = localStorage.getItem('verify_source');
        const vDst = localStorage.getItem('verify_dest');
        if (vSrc) verifySource.value = vSrc;
        if (vDst) verifyDest.value = vDst;
    });
}

btnVerifyScan.addEventListener('click', async () => {
    const source = verifySource.value.trim();
    const dest = verifyDest.value.trim();

    if (!source || !dest) {
        alert('Vui lòng nhập đầy đủ Source và Destination!');
        return;
    }

    try {
        btnVerifyScan.disabled = true;

        const resp = await fetch('/api/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source, dest })
        });

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Server error');

        verifyStatusSection.style.display = 'block';
        if (!isVerifyPolling) {
            isVerifyPolling = true;
            pollVerify();
        }
    } catch (e) {
        alert(e.message);
        btnVerifyScan.disabled = false;
    }
});

btnVerifyStop.addEventListener('click', async () => {
    if (!confirm('Bạn có chắc chắn muốn dừng quá trình quét kiểm tra?')) return;
    try {
        btnVerifyStop.disabled = true;
        await fetch('/api/verify/stop', { method: 'POST' });
    } catch (e) {
        console.error(e);
    }
});

btnVerifyFix.addEventListener('click', () => {
    const source = verifySource.value.trim();
    const dest = verifyDest.value.trim();

    if (!source || !dest) return;

    // Switch to transfer tab and populate
    document.querySelector('.tab-btn[data-tab="transfer"]').click();
    urlInput.value = source;
    outputDirInput.value = dest;

    // Update localstorage so it persists naturally
    localStorage.setItem('rclone_urls', source);
    localStorage.setItem('rclone_dest', dest);

    // Highlight download button slightly
    setTimeout(() => {
        downloadBtn.focus();
    }, 100);
});

async function pollVerify() {
    if (!isVerifyPolling) return;

    try {
        const resp = await fetch('/api/verify/status');
        const state = await resp.json();

        updateVerifyUI(state);

        if (state.status === 'idle' || state.status === 'completed' || state.status === 'error') {
            isVerifyPolling = false;
            // One final button unlock if we just finished
            if (state.status !== 'idle') {
                btnVerifyScan.disabled = false;
                btnVerifyStop.style.display = 'none';
                if (state.stats.total_missing > 0 || state.stats.total_differ > 0) {
                    btnVerifyFix.style.display = 'block';
                }
            }
        } else {
            setTimeout(pollVerify, 1500);
        }
    } catch (e) {
        console.error(e);
        isVerifyPolling = false;
        btnVerifyScan.disabled = false;
    }
}

function updateVerifyUI(state) {
    if (state.status === 'idle') {
        verifyStatusSection.style.display = 'none';
        return;
    }

    verifyStatusSection.style.display = 'block';
    verifyMessageText.textContent = state.message;

    if (state.status === 'verifying') {
        verifyMessageText.style.color = '#3b82f6';
        btnVerifyStop.style.display = 'block';
        btnVerifyStop.disabled = false;
        btnVerifyScan.disabled = true;
        btnVerifyFix.style.display = 'none';
    } else if (state.status === 'completed') {
        verifyMessageText.style.color = '#10b981';
    } else if (state.status === 'error') {
        verifyMessageText.style.color = '#ef4444';
    }

    if (state.stats) {
        verifyMissingCount.textContent = `👉 Thiếu: ${state.stats.total_missing} file`;
        verifyDifferCount.textContent = `👉 Lệch dung lượng: ${state.stats.total_differ} file`;
        verifyErrorCount.textContent = `👉 Lỗi: ${state.stats.total_error}`;

        verifyListBody.innerHTML = '';
        if (state.stats.files.length === 0) {
            verifyListBody.innerHTML = '<tr><td colspan="2" style="text-align:center; color: var(--text-muted); padding: 15px;">Chưa phát hiện file lỗi/thiếu</td></tr>';
        } else {
            state.stats.files.forEach(f => {
                const tr = document.createElement('tr');
                let badge = '';
                if (f.type === 'missing') badge = '<span class="status-badge" style="background:#ef4444; color:white;">Thiếu</span>';
                if (f.type === 'differ') badge = '<span class="status-badge" style="background:#f59e0b; color:white;">Lệch Size</span>';
                if (f.type === 'error') badge = '<span class="status-badge" style="background:#64748b; color:white;">Lỗi</span>';

                tr.innerHTML = `<td>${badge}</td><td style="word-break: break-all; font-family: monospace; font-size: 0.85rem;">${f.path}</td>`;
                verifyListBody.appendChild(tr);
            });
        }
    }
}

// Check verify status on load
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch('/api/verify/status');
        const state = await resp.json();
        if (state.status === 'verifying') {
            isVerifyPolling = true;
            pollVerify();
            verifyStatusSection.style.display = 'block';
        } else if (state.status === 'completed' || state.status === 'error') {
            updateVerifyUI(state);
            if (state.stats.total_missing > 0 || state.stats.total_differ > 0) {
                btnVerifyFix.style.display = 'block';
            }
        }
    } catch (e) { }

    // Console toggle
    const consoleToggle = document.getElementById('consoleToggle');
    const transferConsole = document.getElementById('transferConsole');
    if (consoleToggle && transferConsole) {
        consoleToggle.addEventListener('click', () => {
            if (transferConsole.style.display === 'none') {
                transferConsole.style.display = 'block';
                consoleToggle.textContent = '[ Thu gọn ]';
            } else {
                transferConsole.style.display = 'none';
                consoleToggle.textContent = '[ Mở rộng ]';
            }
        });
    }
});
