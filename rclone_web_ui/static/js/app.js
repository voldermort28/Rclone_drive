// ==================== DOM ELEMENTS ====================
const urlInput = document.getElementById('url');
const outputDirInput = document.getElementById('output_dir');
const downloadBtn = document.getElementById('downloadBtn');
const statusSection = document.getElementById('statusSection');
const statusText = document.getElementById('statusText');
const fileText = document.getElementById('fileText');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const sizeInfo = document.getElementById('sizeInfo');
const filesListBody = document.getElementById('filesListBody');

let isPolling = false;

// ==================== TAB SWITCHING ====================
document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var tabName = this.getAttribute('data-tab');
        
        // Update active button
        document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        
        // Update active content
        document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
        var target = document.getElementById('tab-' + tabName);
        if (target) target.classList.add('active');
        
        // Load config when switching to config tab
        if (tabName === 'config') {
            loadConfig();
            loadSAInfo();
        } else if (tabName === 'history') {
            loadHistory();
        }
    });
});

// ==================== TRANSFER LOGIC ====================
downloadBtn.addEventListener('click', async () => {
    if (downloadBtn.classList.contains('btn-stop')) {
        try {
            await fetch('/api/stop', { method: 'POST' });
            downloadBtn.disabled = true;
            downloadBtn.querySelector('.btn-text').textContent = 'Đang dừng...';
        } catch (e) {
            console.error(e);
        }
        return;
    }

    const urls = urlInput.value.trim();
    if (!urls) {
        statusText.textContent = 'Vui lòng nhập ít nhất 1 link nguồn';
        statusText.style.color = '#ef4444';
        return;
    }

    try {
        isPolling = true;
        downloadBtn.disabled = false;
        downloadBtn.classList.remove('btn-primary');
        downloadBtn.classList.add('btn-stop');

        try {
            downloadBtn.querySelector('.btn-text').textContent = 'DỪNG LẠI';
        } catch (err) { console.error(err); }

        clearFiles();
        statusText.textContent = 'Đang khởi tạo...';
        statusText.style.color = '#f8fafc';
        statusSection.style.display = 'flex';

        const outputDir = outputDirInput.value;
        const payloadData = { url: urls, output_dir: outputDir };

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
                                errorObj.stack = err.trace;
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

        poll();

    } catch (e) {
        console.error(e);
        isPolling = false;
        resetUI();

        let errorHtml = '<div style="color:#ef4444; font-weight:bold; margin-bottom:5px;">' + e.message + '</div>';

        statusText.innerHTML =
            '<div style="text-align:left; background: #333; padding: 10px; border-radius: 4px; overflow: auto; max-height: 400px;">' +
                errorHtml +
                '<div style="color:#aaa; font-family:monospace; font-size: 0.8em; white-space: pre;">' + (e.stack || 'No client stack') + '</div>' +
            '</div>';
    }
});

// ==================== POLLING ====================
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
            resetUI();
            downloadBtn.querySelector('.btn-text').textContent = state.status === 'completed' ? 'Copy tiếp' : 'Thử lại';
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
}

function renderFiles(files) {
    if (!files) return;

    filesListBody.innerHTML = '';
    files.forEach(function(f, index) {
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

function resetUI() {
    downloadBtn.disabled = false;
    downloadBtn.classList.remove('btn-stop');
    downloadBtn.classList.add('btn-primary');
    downloadBtn.querySelector('.btn-text').textContent = 'Bắt đầu Copy';
}

function clearFiles() {
    filesListBody.innerHTML = '';
}

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
                editor.value = data.content || '# Chưa có cấu hình. Dán nội dung rclone.conf vào đây.\n# Ví dụ:\n# [gc]\n# type = drive\n# scope = drive\n# team_drive = \n# root_folder_id = ';
                statusEl.textContent = '📁 ' + data.path;
                statusEl.className = 'config-status';
            } else {
                editor.value = '# Lỗi tải cấu hình';
                statusEl.textContent = '❌ Không thể đọc file cấu hình';
                statusEl.className = 'config-status error';
            }
        }
    };
    xhr.send();
}

document.getElementById('loadConfigBtn').addEventListener('click', loadConfig);

document.getElementById('saveConfigBtn').addEventListener('click', function() {
    var editor = document.getElementById('configEditor');
    var statusEl = document.getElementById('configStatus');
    var content = editor.value;
    
    statusEl.textContent = 'Đang lưu...';
    statusEl.className = 'config-status';
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/config", true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                statusEl.textContent = '✅ Đã lưu cấu hình thành công!';
                statusEl.className = 'config-status success';
            } else {
                var err = JSON.parse(xhr.responseText);
                statusEl.textContent = '❌ Lỗi: ' + (err.error || 'Unknown');
                statusEl.className = 'config-status error';
            }
        }
    };
    xhr.send(JSON.stringify({ content: content }));
});

// ==================== SA MANAGEMENT ====================
var saUploadArea = document.getElementById('saUploadArea');
var saFileInput = document.getElementById('saFileInput');
var saStatus = document.getElementById('saStatus');

// Click to browse
saUploadArea.addEventListener('click', function() {
    saFileInput.click();
});

// Drag and drop
saUploadArea.addEventListener('dragover', function(e) {
    e.preventDefault();
    saUploadArea.classList.add('drag-over');
});

saUploadArea.addEventListener('dragleave', function() {
    saUploadArea.classList.remove('drag-over');
});

saUploadArea.addEventListener('drop', function(e) {
    e.preventDefault();
    saUploadArea.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
        uploadSAFile(e.dataTransfer.files[0]);
    }
});

saFileInput.addEventListener('change', function() {
    if (saFileInput.files.length > 0) {
        uploadSAFile(saFileInput.files[0]);
    }
});

function uploadSAFile(file) {
    saStatus.textContent = '⏳ Đang upload và giải nén ' + file.name + '...';
    saStatus.className = 'config-status';
    
    var formData = new FormData();
    formData.append('file', file);
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sa/upload", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                var data = JSON.parse(xhr.responseText);
                saStatus.textContent = '✅ ' + data.message;
                saStatus.className = 'config-status success';
                loadSAInfo();
            } else {
                var err = JSON.parse(xhr.responseText);
                saStatus.textContent = '❌ ' + (err.error || 'Upload failed');
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
                saInfo.innerHTML = '🔑 <span class="sa-count">' + data.count + ' Service Account(s)</span> đã sẵn sàng' +
                    '<span class="sa-clear" onclick="clearSA()">🗑️ Xóa tất cả</span>';
            } else {
                saInfo.innerHTML = '<span style="color: var(--text-muted);">Chưa có SA nào. Upload file .zip để bắt đầu.</span>';
            }
        }
    };
    xhr.send();
}

// ==================== INITIALIZATION ====================
window.addEventListener('DOMContentLoaded', () => {
    // Load persisted inputs
    const savedUrls = localStorage.getItem('rclone_urls');
    const savedDest = localStorage.getItem('rclone_dest');
    
    if (savedUrls) urlInput.value = savedUrls;
    if (savedDest) outputDirInput.value = savedDest;
    
    loadSAInfo();
    
    // Auto-resume polling if a task is already running in backend
    checkActiveTransfer();
});

async function checkActiveTransfer() {
    try {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/status", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4 && xhr.status === 200) {
                const state = JSON.parse(xhr.responseText);
                
                // Always restore the last known inputs from backend memory
                if (state.raw_urls) {
                    urlInput.value = state.raw_urls;
                    localStorage.setItem('rclone_urls', state.raw_urls);
                }
                if (state.output_dir) {
                    outputDirInput.value = state.output_dir;
                    localStorage.setItem('rclone_dest', state.output_dir);
                }
                
                if (state.status === 'downloading' || state.progress > 0 && state.status !== 'error' && state.status !== 'completed' && state.status !== 'idle') {
                    // Restore UI state for active transfer
                    isPolling = true;
                    downloadBtn.disabled = false;
                    downloadBtn.classList.remove('btn-primary');
                    downloadBtn.classList.add('btn-stop');
                    try { downloadBtn.querySelector('.btn-text').textContent = 'DỪNG LẠI'; } catch(e){}
                    statusSection.style.display = 'flex';
                    poll();
                } else if ((state.status === 'error' || state.status === 'completed') && state.raw_urls) {
                    // Show final status if finished/error but keep the inputs
                    statusSection.style.display = 'flex';
                    updateUI(state);
                    resetUI();
                    downloadBtn.querySelector('.btn-text').textContent = state.status === 'completed' ? 'Copy tiếp' : 'Thử lại';
                }
            }
        };
        xhr.send();
    } catch(e) {}
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
                var data = JSON.parse(xhr.responseText);
                renderHistory(data);
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
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 20px; color: var(--text-muted);">Trống (chưa có ghi nhận nào)</td></tr>';
        return;
    }
    
    tbody.innerHTML = '';
    records.forEach(function(rec) {
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
        
        var urls = (rec.urls || '').replace(/\n/g, '<br>');
        
        row.innerHTML = 
            '<td>' + (rec.time || 'N/A') + '</td>' +
            '<td style="word-break: break-all; max-width: 300px;">' + urls + '</td>' +
            '<td style="word-break: break-all;">' + (rec.dest || 'N/A') + '</td>' +
            '<td>' + statusHtml + '</td>';
        
        tbody.appendChild(row);
    });
}

document.getElementById('clearHistoryBtn').addEventListener('click', function() {
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

function clearSA() {
    if (!confirm('Xóa tất cả Service Accounts?')) return;
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sa/clear", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            var saStatus = document.getElementById('saStatus');
            saStatus.textContent = '🗑️ Đã xóa tất cả SA files';
            saStatus.className = 'config-status';
            loadSAInfo();
        }
    };
    xhr.send();
}
