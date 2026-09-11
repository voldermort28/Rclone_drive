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
const clearTempBtn = document.getElementById('clearTempBtn');

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
            loadFshareConfig();
            loadGithubConfig();
            loadFichierConfig();
            loadPixeldrainConfig();
        } else if (tabName === 'unpack') {
            loadGithubConfig();
            checkUnpackStatus();
        } else if (tabName === 'history') {
            loadQueue();
            loadHistory();
        } else if (tabName === 'pending') {
            loadPendingList();
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
        let outputDir = convertSingleUrl(outputDirInput.value.trim());

        if (!outputDir) {
            alert('Vui lòng nhập Destination (Nơi nhận)');
            return;
        }

        const filePasswordInput = document.getElementById('file_password');
        const filePassword = filePasswordInput ? filePasswordInput.value.trim() : '';

        // Send raw URLs to backend (backend will parse gc:ID and scrape titles)
        const wrapCheckbox = document.getElementById('wrapParentFolder');
        const payloadData = {
            url: urlInput.value,
            output_dir: outputDir,
            wrap: wrapCheckbox ? wrapCheckbox.checked : false,
            file_password: filePassword
        };

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
        if (filePasswordInput) filePasswordInput.value = ''; // Clear file password too

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

stopBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    showStopConfirmModal();
});

function showStopConfirmModal() {
    // Create modal if it doesn't exist yet
    let modal = document.getElementById('stopConfirmModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'stopConfirmModal';
        modal.className = 'confirm-modal-overlay';
        modal.innerHTML = `
            <div class="confirm-modal-box">
                <div class="confirm-modal-icon">⚠️</div>
                <h3 class="confirm-modal-title">Dừng tiến trình?</h3>
                <p class="confirm-modal-desc">Bạn có muốn dừng tiến trình <strong>ĐANG CHẠY</strong> ngay lập tức?<br><small style="color:var(--text-muted);">(Các job trong Queue sẽ KHÔNG bị xóa)</small></p>
                <div class="confirm-modal-actions">
                    <button type="button" id="stopModalCancel" class="btn-secondary confirm-modal-btn">Hủy</button>
                    <button type="button" id="stopModalConfirm" class="btn-primary confirm-modal-btn" style="background:#ef4444; border-color:#ef4444;">Dừng ngay</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // Wire up cancel
        document.getElementById('stopModalCancel').addEventListener('click', () => {
            modal.classList.remove('active');
        });

        // Wire up confirm
        document.getElementById('stopModalConfirm').addEventListener('click', async () => {
            modal.classList.remove('active');
            try {
                stopBtn.disabled = true;
                stopBtn.querySelector('.btn-text').textContent = 'Đang dừng...';
                await fetch('/api/stop', { method: 'POST' });
            } catch (err) {
                console.error(err);
                alert('Lỗi khi gửi lệnh dừng!');
            }
        });

        // Click overlay to dismiss
        modal.addEventListener('click', (ev) => {
            if (ev.target === modal) modal.classList.remove('active');
        });
    }

    // Show it
    modal.classList.add('active');
}

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
                dropdown.innerHTML = '<div style="padding:14px; text-align:center; color:#94a3b8; font-size:0.8rem;">📭 Chưa có lịch sử folder đích</div>';
                dropdown.style.cssText = 'display:block; position:absolute; z-index:9999; top:100%; left:0; right:0; max-height:220px; overflow-y:auto; background:#1e293b; border:1px solid #334155; border-radius:0 0 8px 8px; box-shadow:0 8px 20px rgba(0,0,0,0.5);';
                return;
            }
            dropdown.innerHTML = '';
            items.forEach(item => {
                const row = document.createElement('div');
                row.style.cssText = 'padding:10px 14px; cursor:pointer; font-size:0.85rem; border-bottom:1px solid #334155; transition:background 0.15s; background:#1e293b; display:flex; align-items:center; gap:10px;';

                // Determine display name
                let displayName = item.name || '';
                if (!displayName) {
                    const parts = item.path.split('/');
                    if (parts.length > 1) {
                        displayName = parts[parts.length - 1];
                    }
                }
                if (!displayName) displayName = 'Chưa rõ tên';

                // Shorten path for display
                let shortPath = item.path;
                if (shortPath.length > 40) {
                    shortPath = shortPath.substring(0, 18) + '...' + shortPath.substring(shortPath.length - 15);
                }

                // Info section (clickable)
                const info = document.createElement('div');
                info.style.cssText = 'flex:1; min-width:0;';
                info.innerHTML = '<div style="color:#60a5fa; font-weight:600; margin-bottom:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">📁 ' + displayName + '</div>' +
                    '<div style="color:#64748b; font-size:0.72rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + shortPath + '</div>';

                // Delete button
                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.textContent = '✕';
                delBtn.title = 'Xóa khỏi danh sách';
                delBtn.style.cssText = 'background:none; border:none; color:#ef4444; font-size:16px; cursor:pointer; padding:4px 6px; border-radius:4px; transition:background 0.15s; flex-shrink:0; line-height:1;';
                delBtn.addEventListener('mouseenter', () => delBtn.style.background = 'rgba(239,68,68,0.15)');
                delBtn.addEventListener('mouseleave', () => delBtn.style.background = 'none');
                delBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    fetch('/api/dest_history', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: item.path })
                    }).then(() => showDestDropdown());
                });

                row.appendChild(info);
                row.appendChild(delBtn);

                row.addEventListener('mouseenter', () => row.style.background = '#334155');
                row.addEventListener('mouseleave', () => row.style.background = '#1e293b');
                info.addEventListener('click', (e) => {
                    e.stopPropagation();
                    outputDirInput.value = item.path;
                    localStorage.setItem('rclone_dest', item.path);
                    dropdown.style.display = 'none';
                });
                dropdown.appendChild(row);
            });
            dropdown.style.cssText = 'display:block; position:absolute; z-index:9999; top:100%; left:0; right:0; max-height:260px; overflow-y:auto; background:#1e293b; border:1px solid #334155; border-radius:0 0 8px 8px; box-shadow:0 8px 20px rgba(0,0,0,0.5);';
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
let explorerTargetInput = null;

const explorerModal = document.getElementById('driveExplorerModal');
const explorerList = document.getElementById('explorerList');
const explorerBreadcrumb = document.getElementById('explorerBreadcrumb');

// Event listener for all Duyệt Drive buttons
document.querySelectorAll('.btn-browse-drive').forEach(btn => {
    btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-target');
        const targetInput = document.getElementById(targetId);
        if (!targetInput) return;

        explorerTargetInput = targetInput;

        let currentPath = targetInput.value.trim();
        if (!currentPath || !currentPath.startsWith('gc:')) {
            currentPath = 'gc:';
        }

        explorerPath = currentPath;

        // Build history for back button
        const parts = currentPath.split('/');
        explorerHistory = [];
        let acc = '';
        for (let i = 0; i < parts.length; i++) {
            acc += (i > 0 ? '/' : '') + parts[i];
            explorerHistory.push(acc);
        }

        explorerModal.style.display = 'flex';
        loadExplorerDir(explorerPath);
    });
});

document.getElementById('explorerCloseBtn').addEventListener('click', () => {
    explorerModal.style.display = 'none';
});

// Click outside modal to close
explorerModal.addEventListener('click', (e) => {
    if (e.target === explorerModal) explorerModal.style.display = 'none';
});

document.getElementById('explorerSelectBtn').addEventListener('click', () => {
    if (explorerTargetInput) {
        explorerTargetInput.value = explorerPath;
        
        // Map target input IDs to their respective localStorage keys
        const localStorageKeyMap = {
            'output_dir': 'rclone_dest',
            'teraboxDest': 'tb_dest',
            'fshareDest': 'fs_dest',
            'mediafireDest': 'mf_dest',
            'megaDest': 'mega_dest',
            'verify_source': 'verify_source',
            'verify_dest': 'verify_dest'
        };
        const key = localStorageKeyMap[explorerTargetInput.id];
        if (key) {
            localStorage.setItem(key, explorerPath);
        }
        
        // Trigger event inputs if needed
        explorerTargetInput.dispatchEvent(new Event('input', { bubbles: true }));
        explorerTargetInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
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
                if (path === 'gc:') {
                    explorerList.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-muted); line-height: 1.6;">📂 Thư mục gốc trống.<br><br><span style="font-size:0.9rem; color:#64748b;">Mẹo: Hãy dán ID thư mục Google Drive (VD: 1xlaPOv...) vào ô bên ngoài,<br>sau đó bấm "Duyệt Drive" để xem nội dung bên trong!</span></div>';
                } else {
                    explorerList.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-muted);">📂 Thư mục trống</div>';
                }
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

// ==================== CLEAR TEMP ACTION ====================
if (clearTempBtn) {
    clearTempBtn.addEventListener('click', async () => {
        if (!confirm('Bạn có chắc chắn muốn dừng toàn bộ tiến trình đang chạy và xóa tất cả file tạm thời?')) {
            return;
        }
        try {
            clearTempBtn.disabled = true;
            clearTempBtn.querySelector('.btn-text').textContent = 'Đang xóa...';
            const resp = await fetch('/api/clear_temp', { method: 'POST' });
            const data = await resp.json();
            alert(data.message || 'Đã dọn dẹp xong!');
        } catch (e) {
            console.error(e);
            alert('Lỗi khi dọn dẹp file tạm: ' + e.message);
        } finally {
            clearTempBtn.disabled = false;
            clearTempBtn.querySelector('.btn-text').textContent = '🧹 Xóa file tạm';
        }
    });
}

// ==================== CONFIG STATUS BADGES ====================
function checkConfigStatus() {
    fetch('/api/fshare/config')
        .then(r => r.json())
        .then(data => {
            const indicator = document.getElementById('badgeFshareIndicator');
            const text = document.getElementById('badgeFshareText');
            if (indicator && text) {
                if (data.complete) {
                    indicator.className = 'badge-indicator active';
                    text.textContent = data.email || 'VIP';
                } else {
                    indicator.className = 'badge-indicator inactive';
                    text.textContent = 'Chưa cấu hình';
                }
            }
        })
        .catch(() => {
            const indicator = document.getElementById('badgeFshareIndicator');
            const text = document.getElementById('badgeFshareText');
            if (indicator && text) {
                indicator.className = 'badge-indicator inactive';
                text.textContent = 'Lỗi kết nối';
            }
        });

    fetch('/api/terabox/cookie')
        .then(r => r.json())
        .then(data => {
            const indicator = document.getElementById('badgeTeraboxIndicator');
            const text = document.getElementById('badgeTeraboxText');
            if (indicator && text) {
                if (data.has_cookie) {
                    indicator.className = 'badge-indicator active';
                    text.textContent = 'Đã cấu hình';
                } else {
                    indicator.className = 'badge-indicator inactive';
                    text.textContent = 'Chưa cấu hình';
                }
            }
        })
        .catch(() => {
            const indicator = document.getElementById('badgeTeraboxIndicator');
            const text = document.getElementById('badgeTeraboxText');
            if (indicator && text) {
                indicator.className = 'badge-indicator inactive';
                text.textContent = 'Lỗi kết nối';
            }
        });

    fetch('/api/fichier/config')
        .then(r => r.json())
        .then(data => {
            const indicator = document.getElementById('badgeFichierIndicator');
            const text = document.getElementById('badgeFichierText');
            if (indicator && text) {
                if (data.complete) {
                    indicator.className = 'badge-indicator active';
                    indicator.style.backgroundColor = '';
                    text.textContent = 'Premium (API Key)';
                } else {
                    indicator.className = 'badge-indicator active';
                    indicator.style.backgroundColor = '#fbbf24';
                    text.textContent = 'Tự động (Free)';
                }
            }
        })
        .catch(() => {
            const indicator = document.getElementById('badgeFichierIndicator');
            const text = document.getElementById('badgeFichierText');
            if (indicator && text) {
                indicator.className = 'badge-indicator inactive';
                indicator.style.backgroundColor = '';
                text.textContent = 'Lỗi kết nối';
            }
        });

    fetch('/api/pixeldrain/config')
        .then(r => r.json())
        .then(data => {
            const indicator = document.getElementById('badgePixeldrainIndicator');
            const text = document.getElementById('badgePixeldrainText');
            if (indicator && text) {
                if (data.complete) {
                    indicator.className = 'badge-indicator active';
                    indicator.style.backgroundColor = '';
                    text.textContent = 'Pro (API Key)';
                } else {
                    indicator.className = 'badge-indicator active';
                    indicator.style.backgroundColor = '#10b981';
                    text.textContent = 'Tự động (Free)';
                }
            }
        })
        .catch(() => {
            const indicator = document.getElementById('badgePixeldrainIndicator');
            const text = document.getElementById('badgePixeldrainText');
            if (indicator && text) {
                indicator.className = 'badge-indicator inactive';
                indicator.style.backgroundColor = '';
                text.textContent = 'Lỗi kết nối';
            }
        });
}

// ==================== TERABOX COOKIE CONFIG ====================
function tbLoadCookie() {
    fetch('/api/terabox/cookie')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const tbCookieStatus = document.getElementById('teraboxCookieStatus');
            if (data.has_cookie) {
                if (tbCookieStatus) {
                    tbCookieStatus.innerHTML = '✅ Cookie đã lưu (<code>' + data.masked + '</code>)';
                    tbCookieStatus.style.color = '#22c55e';
                }
            } else {
                if (tbCookieStatus) {
                    tbCookieStatus.innerHTML = '⚠️ Chưa có cookie. Vui lòng nhập và lưu.';
                    tbCookieStatus.style.color = '#f59e0b';
                }
            }
            checkConfigStatus();
        })
        .catch(function () {
            const tbCookieStatus = document.getElementById('teraboxCookieStatus');
            if (tbCookieStatus) {
                tbCookieStatus.textContent = '❌ Không thể kiểm tra cookie.';
                tbCookieStatus.style.color = '#ef4444';
            }
        });
}

function tbSaveCookie() {
    const tbCookieInput = document.getElementById('teraboxCookie');
    const tbSaveCookieBtn = document.getElementById('teraboxSaveCookieBtn');
    if (!tbCookieInput || !tbSaveCookieBtn) return;
    var val = tbCookieInput.value.trim();
    if (!val) {
        alert('Vui lòng nhập cookie ndus!');
        return;
    }
    tbSaveCookieBtn.disabled = true;
    tbSaveCookieBtn.textContent = '⏳ Đang lưu...';

    fetch('/api/terabox/cookie', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookie: val })
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                tbCookieInput.value = '';
                tbLoadCookie();
            } else {
                alert('Lỗi: ' + (data.error || 'Không rõ'));
            }
        })
        .catch(function (e) { alert('Lỗi kết nối: ' + e); })
        .finally(function () {
            tbSaveCookieBtn.disabled = false;
            tbSaveCookieBtn.textContent = '💾 Lưu';
        });
}

var tbSaveCookieBtn = document.getElementById('teraboxSaveCookieBtn');
if (tbSaveCookieBtn) {
    tbSaveCookieBtn.addEventListener('click', tbSaveCookie);
}

// ==================== FSHARE TAB ====================
(function () {
    return; // Obsolete, replaced by unified transfer queue
    var fsAccountStatus = document.getElementById('fshareAccountStatus');
    var fsUrlInput = document.getElementById('fshareUrl');
    var fsPasswordInput = document.getElementById('fshareFilePassword');
    var fsDestInput = document.getElementById('fshareDest');
    var fsCheckBtn = document.getElementById('fshareCheckBtn');
    var fsStartBtn = document.getElementById('fshareStartBtn');
    var fsStopBtn = document.getElementById('fshareStopBtn');
    var fsResetBtn = document.getElementById('fshareResetBtn');
    var fsClearTempBtn = document.getElementById('fshareClearTempBtn');
    var fsFileInfo = document.getElementById('fshareFileInfo');
    var fsFileName = document.getElementById('fshareFileName');
    var fsFileSize = document.getElementById('fshareFileSize');
    var fsStatusSection = document.getElementById('fshareStatusSection');
    var fsStatusText = document.getElementById('fshareStatusText');
    var fsPhaseText = document.getElementById('fsharePhaseText');
    var fsProgressBar = document.getElementById('fshareProgressBar');
    var fsProgressPercent = document.getElementById('fshareProgressPercent');
    var fsProgressDetail = document.getElementById('fshareProgressDetail');
    var fsConsole = document.getElementById('fshareConsole');

    if (!fsUrlInput || !fsDestInput) return;

    var fsPollingInterval = null;
    var fsLastLogCount = 0;
    var fsRenderedLogKey = '';

    var savedFsLink = localStorage.getItem('fs_link');
    var savedFsDest = localStorage.getItem('fs_dest');
    if (savedFsLink) fsUrlInput.value = savedFsLink;
    if (savedFsDest) fsDestInput.value = savedFsDest;

    function fsLoadConfigStatus() {
        fetch('/api/fshare/config')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!fsAccountStatus) return;
                if (data.complete) {
                    fsAccountStatus.innerHTML = '✅ Fshare đã cấu hình cho <strong>' + (data.email || '') + '</strong>. Có thể tải bằng tài khoản VIP.';
                    fsAccountStatus.style.color = '#22c55e';
                    fsAccountStatus.style.borderColor = 'rgba(34,197,94,.35)';
                    fsAccountStatus.style.background = 'rgba(34,197,94,.1)';
                } else {
                    fsAccountStatus.innerHTML = '⚠️ Chưa đủ cấu hình Fshare. Mở tab Cấu hình để nhập email và password.';
                    fsAccountStatus.style.color = '#f59e0b';
                    fsAccountStatus.style.borderColor = 'rgba(245,158,11,.35)';
                    fsAccountStatus.style.background = 'rgba(245,158,11,.1)';
                }
            })
            .catch(function () {
                if (!fsAccountStatus) return;
                fsAccountStatus.textContent = '❌ Không kiểm tra được cấu hình Fshare.';
                fsAccountStatus.style.color = '#ef4444';
            });
    }

    function fsValidUrl(url) {
        if (!url) return false;
        var lines = url.split('\n').map(function(line) { return line.trim(); }).filter(Boolean);
        if (lines.length === 0) return false;
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var ok = /fshare\.vn\/file\//i.test(line) || /^[A-Za-z0-9]{8,}$/.test(line);
            if (!ok) return false;
        }
        return true;
    }

    function fsCheckInfo() {
        var rawUrl = fsUrlInput.value.trim();
        if (!rawUrl) {
            alert('Vui lòng nhập link Fshare!');
            return;
        }
        var lines = rawUrl.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
        var url = lines[0] || '';
        var filePassword = fsPasswordInput ? fsPasswordInput.value.trim() : '';

        var singleValid = url.indexOf('fshare.vn/file/') > -1 || /^[A-Za-z0-9]{8,}$/.test(url);
        if (!singleValid) {
            alert('Dòng đầu tiên không phải link Fshare file hợp lệ. Cần link dạng: https://www.fshare.vn/file/...');
            return;
        }

        fsCheckBtn.disabled = true;
        fsCheckBtn.textContent = '⏳ Đang kiểm tra...';
        fsFileInfo.style.display = 'none';

        fetch('/api/fshare/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, file_password: filePassword })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    fsFileName.textContent = (lines.length > 1 ? '[Link 1] ' : '') + (data.file_name || data.file_id || 'Fshare file');
                    fsFileSize.textContent = data.file_size_human || 'Direct link sẵn sàng';
                    fsFileInfo.style.display = 'block';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không lấy được thông tin file'));
                    fsLoadConfigStatus();
                }
            })
            .catch(function (e) { alert('Lỗi kết nối: ' + e); })
            .finally(function () {
                fsCheckBtn.disabled = false;
                fsCheckBtn.textContent = '🔍 Kiểm tra link';
            });
    }

    function fsStart() {
        var url = fsUrlInput.value.trim();
        var dest = fsDestInput.value.trim();
        var filePassword = fsPasswordInput ? fsPasswordInput.value.trim() : '';

        if (!url) { alert('Vui lòng nhập link Fshare!'); return; }
        if (!fsValidUrl(url)) { alert('Có dòng không phải link Fshare file hợp lệ.'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        localStorage.setItem('fs_link', url);
        localStorage.setItem('fs_dest', dest);

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        fsStartBtn.disabled = true;
        fsStartBtn.textContent = '⏳ Đang khởi tạo...';

        fetch('/api/fshare/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, destination: dest, file_password: filePassword })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    fsStatusSection.style.display = 'block';
                    fsConsole.textContent = 'Đang khởi tạo pipeline Fshare...\n';
                    fsLastLogCount = 0;
                    fsStartPolling();
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể bắt đầu'));
                    fsStartBtn.disabled = false;
                    fsStartBtn.textContent = '🚀 Bắt đầu tải';
                    fsLoadConfigStatus();
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
                fsStartBtn.disabled = false;
                fsStartBtn.textContent = '🚀 Bắt đầu tải';
            });
    }

    function fsStartPolling() {
        if (fsPollingInterval) clearInterval(fsPollingInterval);
        fsPollingInterval = setInterval(fsPollStatus, 2000);
        fsPollStatus();
    }

    function fsStopPolling() {
        if (fsPollingInterval) {
            clearInterval(fsPollingInterval);
            fsPollingInterval = null;
        }
    }

    function fsRenderLogs(logs, replace) {
        if (!logs || logs.length === 0) {
            if (replace) {
                fsConsole.textContent = 'Đang chờ console...';
                fsLastLogCount = 0;
                fsRenderedLogKey = '';
            }
            return;
        }

        var start = replace ? 0 : fsLastLogCount;
        var newLogs = logs.slice(start);
        if (replace) {
            fsConsole.innerHTML = '';
        } else if (newLogs.length === 0) {
            var lastLog = logs[logs.length - 1];
            var currentKey = logs.length + '|' + (lastLog.time || '') + '|' + (lastLog.msg || '');
            if (currentKey !== fsRenderedLogKey && logs.length <= fsLastLogCount) {
                newLogs = logs;
                fsConsole.innerHTML = '';
            }
        }
        if (newLogs.length === 0) return;

        var html = '';
        for (var i = newLogs.length - 1; i >= 0; i--) {
            var log = newLogs[i];
            var color = '#a5b4fc';
            if (log.level === 'ERROR') color = '#ef4444';
            else if (log.level === 'WARNING') color = '#f59e0b';
            else if (log.level === 'INFO') color = '#38bdf8';
            else if (log.level === 'DEBUG') color = '#64748b';
            var safeMsg = String(log.msg || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            html += '<span style="color:' + color + '">[' + log.time + '] ' + safeMsg + '</span>\n';
        }

        if (replace) fsConsole.innerHTML = html;
        else fsConsole.innerHTML = html + fsConsole.innerHTML;
        fsLastLogCount = logs.length;
        var last = logs[logs.length - 1];
        fsRenderedLogKey = logs.length + '|' + (last.time || '') + '|' + (last.msg || '');
        fsConsole.scrollTop = 0;
    }

    function fsUpdateStatusUI(data, replaceLogs) {
        var pct = data.progress || 0;
        fsProgressBar.style.width = pct + '%';
        fsProgressPercent.textContent = pct + '%';
        fsProgressBar.style.background = pct <= 50
            ? 'linear-gradient(90deg, #3b82f6, #60a5fa)'
            : 'linear-gradient(90deg, #22c55e, #4ade80)';

        fsStatusText.textContent = data.message || 'Đang xử lý...';
        var detail = '';
        if (data.total_items && data.total_items > 0) {
            detail += '[' + (data.current_index || 0) + '/' + data.total_items + '] ';
        }
        if (data.file_name) detail += data.file_name;
        if (data.file_size_human) detail += (detail ? ' · ' : '') + data.file_size_human;
        fsProgressDetail.textContent = detail;

        if (data.phase === 'info' || data.status === 'fetching_info') {
            fsPhaseText.textContent = '🔎 Đang lấy direct link Fshare';
        } else if (data.phase === 'download' || data.status === 'downloading') {
            fsPhaseText.textContent = '📥 Đang tải từ Fshare';
        } else if (data.phase === 'upload' || data.status === 'uploading') {
            fsPhaseText.textContent = '📤 Đang đẩy lên Google Drive';
        }

        fsRenderLogs(data.logs || [], replaceLogs);

        if (data.status === 'done') {
            fsStopPolling();
            fsStatusText.textContent = '✅ ' + (data.message || 'Hoàn tất!');
            fsStatusText.style.color = '#22c55e';
            fsPhaseText.textContent = '🎉 Xong!';
            fsStopBtn.style.display = 'none';
            fsStartBtn.disabled = false;
            fsStartBtn.textContent = '🚀 Bắt đầu tải';
        } else if (data.status === 'error') {
            fsStopPolling();
            fsStatusText.textContent = '❌ ' + (data.message || 'Lỗi!');
            fsStatusText.style.color = '#ef4444';
            fsPhaseText.textContent = '⚠️ Thất bại';
            fsStopBtn.style.display = 'none';
            fsStartBtn.disabled = false;
            fsStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'stopped') {
            fsStopPolling();
            fsStatusText.textContent = '⏹ ' + (data.message || 'Đã dừng.');
            fsStatusText.style.color = '#f59e0b';
            fsPhaseText.textContent = '⏸ Đã tạm dừng, có thể resume';
            fsStopBtn.style.display = 'none';
            fsStartBtn.disabled = false;
            fsStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading') {
            fsStartBtn.disabled = true;
            fsStartBtn.textContent = '⏳ Đang chạy...';
            fsStatusSection.style.display = 'block';
            fsStatusText.style.color = '#3b82f6';
            fsStopBtn.style.display = 'block';
        }
    }

    function fsPollStatus() {
        fetch('/api/fshare/status')
            .then(function (r) { return r.json(); })
            .then(function (data) { fsUpdateStatusUI(data, false); })
            .catch(function () { });
    }

    function fsRestoreStatus() {
        fetch('/api/fshare/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var hasLogs = data.logs && data.logs.length > 0;
                var active = data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading';
                var terminal = data.status === 'done' || data.status === 'error' || data.status === 'stopped';
                if (!hasLogs && !active && !terminal) return;
                fsStatusSection.style.display = 'block';
                fsUpdateStatusUI(data, true);
                if (active) fsStartPolling();
            })
            .catch(function () { });
    }

    function fsStop() {
        fetch('/api/fshare/stop', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function () {
                fsStopPolling();
                fsStatusText.textContent = '⏹ Đã dừng bởi người dùng.';
                fsStartBtn.disabled = false;
                fsStartBtn.textContent = '🚀 Bắt đầu tải';
            })
            .catch(function (e) { alert('Lỗi: ' + e); });
    }

    function fsReset(deleteFiles) {
        var confirmMsg = deleteFiles
            ? 'Xóa toàn bộ file tạm Fshare (.part) và trạng thái hiện tại? Sau đó sẽ tải lại từ đầu.'
            : 'Xóa trạng thái/log Fshare đang hiển thị? File .part để resume sẽ được giữ lại.';
        if (!confirm(confirmMsg)) return;

        fetch('/api/fshare/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: !!deleteFiles })
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok) throw new Error(data.error || 'Reset thất bại');
                    return data;
                });
            })
            .then(function () {
                fsStopPolling();
                fsStatusSection.style.display = 'none';
                fsStatusText.textContent = 'Đang xử lý...';
                fsPhaseText.textContent = '';
                fsProgressBar.style.width = '0%';
                fsProgressPercent.textContent = '0%';
                fsProgressDetail.textContent = '';
                fsConsole.textContent = 'Đang chờ...';
                fsLastLogCount = 0;
                fsRenderedLogKey = '';
                fsStartBtn.disabled = false;
                fsStartBtn.textContent = '🚀 Bắt đầu tải';
                fsStopBtn.style.display = 'none';
                alert(deleteFiles ? 'Đã xóa trạng thái và file tạm.' : 'Đã xóa trạng thái.');
            })
            .catch(function (e) { alert('Lỗi: ' + e.message); });
    }

    function fsQueue() {
        var url = fsUrlInput.value.trim();
        var dest = fsDestInput.value.trim();
        var filePassword = fsPasswordInput ? fsPasswordInput.value.trim() : '';

        if (!url) { alert('Vui lòng nhập link Fshare!'); return; }
        if (!fsValidUrl(url)) { alert('Có dòng không phải link Fshare file hợp lệ.'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        var queueBtn = document.getElementById('fshareQueueBtn');
        if (queueBtn) {
            queueBtn.disabled = true;
            queueBtn.textContent = '⏳ Đang thêm...';
        }

        fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, output_dir: dest, file_password: filePassword })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.message) {
                    alert(data.message);
                    fsUrlInput.value = '';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể thêm vào hàng đợi'));
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
            })
            .finally(function () {
                if (queueBtn) {
                    queueBtn.disabled = false;
                    queueBtn.textContent = '⏳ Thêm hàng đợi';
                }
            });
    }

    fsCheckBtn.addEventListener('click', fsCheckInfo);
    fsStartBtn.addEventListener('click', fsStart);
    fsStopBtn.addEventListener('click', fsStop);
    var fsQueueBtn = document.getElementById('fshareQueueBtn');
    if (fsQueueBtn) fsQueueBtn.addEventListener('click', fsQueue);
    if (fsResetBtn) fsResetBtn.addEventListener('click', function () { fsReset(false); });
    if (fsClearTempBtn) fsClearTempBtn.addEventListener('click', function () { fsReset(true); });

    fsLoadConfigStatus();
    fsRestoreStatus();
})();

// ==================== MEDIAFIRE TAB ====================
(function () {
    return; // Obsolete, replaced by unified transfer queue
    var mfUrlInput = document.getElementById('mediafireUrl');
    var mfDestInput = document.getElementById('mediafireDest');
    var mfCheckBtn = document.getElementById('mediafireCheckBtn');
    var mfStartBtn = document.getElementById('mediafireStartBtn');
    var mfStopBtn = document.getElementById('mediafireStopBtn');
    var mfResetBtn = document.getElementById('mediafireResetBtn');
    var mfClearTempBtn = document.getElementById('mediafireClearTempBtn');
    var mfFileInfo = document.getElementById('mediafireFileInfo');
    var mfFileName = document.getElementById('mediafireFileName');
    var mfFileSize = document.getElementById('mediafireFileSize');
    var mfStatusSection = document.getElementById('mediafireStatusSection');
    var mfStatusText = document.getElementById('mediafireStatusText');
    var mfPhaseText = document.getElementById('mediafirePhaseText');
    var mfProgressBar = document.getElementById('mediafireProgressBar');
    var mfProgressPercent = document.getElementById('mediafireProgressPercent');
    var mfProgressDetail = document.getElementById('mediafireProgressDetail');
    var mfConsole = document.getElementById('mediafireConsole');

    if (!mfUrlInput || !mfDestInput) return;

    var mfPollingInterval = null;
    var mfLastLogCount = 0;
    var mfRenderedLogKey = '';

    var savedMfLink = localStorage.getItem('mf_link');
    var savedMfDest = localStorage.getItem('mf_dest');
    if (savedMfLink) mfUrlInput.value = savedMfLink;
    if (savedMfDest) mfDestInput.value = savedMfDest;

    function mfValidUrl(url) {
        if (!url) return false;
        var lines = url.split('\n').map(function(line) { return line.trim(); }).filter(Boolean);
        if (lines.length === 0) return false;
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            // Check if it is a pure key/token
            if (/^[A-Za-z0-9]+$/.test(line) && line.length >= 8) {
                continue;
            }
            // Check if it is a MediaFire link
            if (line.toLowerCase().indexOf('mediafire.com') > -1) {
                continue;
            }
            return false;
        }
        return true;
    }

    function mfCheckInfo() {
        var url = mfUrlInput.value.trim();
        if (!url) {
            alert('Vui lòng nhập link MediaFire!');
            return;
        }
        if (!mfValidUrl(url)) {
            alert('Danh sách không có link MediaFire folder/file hợp lệ.');
            return;
        }

        mfCheckBtn.disabled = true;
        mfCheckBtn.textContent = '⏳ Đang kiểm tra...';
        mfFileInfo.style.display = 'none';

        fetch('/api/mediafire/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    mfFileName.textContent = data.file_name || 'MediaFire file';
                    var detail = data.file_size_human || 'Chưa có dung lượng';
                    if (data.item_count) {
                        detail += ' · ' + data.item_count + ' file';
                    }
                    if (data.folder_count) {
                        detail += ' · ' + data.folder_count + ' folder';
                    }
                    if (data.direct_file_count) {
                        detail += ' · ' + data.direct_file_count + ' link file';
                    }
                    mfFileSize.textContent = detail;
                    mfFileInfo.style.display = 'block';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không lấy được thông tin file'));
                }
            })
            .catch(function (e) { alert('Lỗi kết nối: ' + e); })
            .finally(function () {
                mfCheckBtn.disabled = false;
                mfCheckBtn.textContent = '🔍 Kiểm tra link';
            });
    }

    function mfStart() {
        var url = mfUrlInput.value.trim();
        var dest = mfDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link MediaFire!'); return; }
        if (!mfValidUrl(url)) { alert('Danh sách không có link MediaFire folder/file hợp lệ.'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        localStorage.setItem('mf_link', url);
        localStorage.setItem('mf_dest', dest);

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        mfStartBtn.disabled = true;
        mfStartBtn.textContent = '⏳ Đang khởi tạo...';

        fetch('/api/mediafire/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, destination: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    mfStatusSection.style.display = 'block';
                    mfConsole.textContent = 'Đang khởi tạo pipeline MediaFire...\n';
                    mfLastLogCount = 0;
                    mfStartPolling();
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể bắt đầu'));
                    mfStartBtn.disabled = false;
                    mfStartBtn.textContent = '🚀 Bắt đầu tải';
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
                mfStartBtn.disabled = false;
                mfStartBtn.textContent = '🚀 Bắt đầu tải';
            });
    }

    function mfStartPolling() {
        if (mfPollingInterval) clearInterval(mfPollingInterval);
        mfPollingInterval = setInterval(mfPollStatus, 2000);
        mfPollStatus();
    }

    function mfStopPolling() {
        if (mfPollingInterval) {
            clearInterval(mfPollingInterval);
            mfPollingInterval = null;
        }
    }

    function mfRenderLogs(logs, replace) {
        if (!logs || logs.length === 0) {
            if (replace) {
                mfConsole.textContent = 'Đang chờ console...';
                mfLastLogCount = 0;
                mfRenderedLogKey = '';
            }
            return;
        }

        var start = replace ? 0 : mfLastLogCount;
        var newLogs = logs.slice(start);
        if (replace) {
            mfConsole.innerHTML = '';
        } else if (newLogs.length === 0) {
            var lastLog = logs[logs.length - 1];
            var currentKey = logs.length + '|' + (lastLog.time || '') + '|' + (lastLog.msg || '');
            if (currentKey !== mfRenderedLogKey && logs.length <= mfLastLogCount) {
                newLogs = logs;
                mfConsole.innerHTML = '';
            }
        }
        if (newLogs.length === 0) return;

        var html = '';
        for (var i = newLogs.length - 1; i >= 0; i--) {
            var log = newLogs[i];
            var color = '#a5b4fc';
            if (log.level === 'ERROR') color = '#ef4444';
            else if (log.level === 'WARNING') color = '#f59e0b';
            else if (log.level === 'INFO') color = '#38bdf8';
            else if (log.level === 'DEBUG') color = '#64748b';
            var safeMsg = String(log.msg || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            html += '<span style="color:' + color + '">[' + log.time + '] ' + safeMsg + '</span>\n';
        }

        if (replace) mfConsole.innerHTML = html;
        else mfConsole.innerHTML = html + mfConsole.innerHTML;
        mfLastLogCount = logs.length;
        var last = logs[logs.length - 1];
        mfRenderedLogKey = logs.length + '|' + (last.time || '') + '|' + (last.msg || '');
        mfConsole.scrollTop = 0;
    }

    function mfUpdateStatusUI(data, replaceLogs) {
        var pct = data.progress || 0;
        mfProgressBar.style.width = pct + '%';
        mfProgressPercent.textContent = pct + '%';
        mfProgressBar.style.background = pct <= 50
            ? 'linear-gradient(90deg, #3b82f6, #60a5fa)'
            : 'linear-gradient(90deg, #22c55e, #4ade80)';

        mfStatusText.textContent = data.message || 'Đang xử lý...';
        var detail = '';
        if (data.total_items && data.total_items > 0) {
            detail += '[' + (data.current_index || 0) + '/' + data.total_items + '] ';
        }
        if (data.file_name) detail += (detail && !detail.endsWith(' ') ? ' · ' : '') + data.file_name;
        if (data.file_size_human) detail += (detail && !detail.endsWith(' ') ? ' · ' : '') + data.file_size_human;
        mfProgressDetail.textContent = detail;

        if (data.phase === 'info' || data.status === 'fetching_info') {
            mfPhaseText.textContent = '🔎 Đang expand danh sách MediaFire';
        } else if (data.phase === 'download' || data.status === 'downloading') {
            mfPhaseText.textContent = '📥 Đang tải từ MediaFire';
        } else if (data.phase === 'upload' || data.status === 'uploading') {
            mfPhaseText.textContent = '📤 Đang đẩy lên Google Drive';
        }

        mfRenderLogs(data.logs || [], replaceLogs);

        if (data.status === 'done') {
            mfStopPolling();
            mfStatusText.textContent = '✅ ' + (data.message || 'Hoàn tất!');
            mfStatusText.style.color = '#22c55e';
            mfPhaseText.textContent = '🎉 Xong!';
            mfStopBtn.style.display = 'none';
            mfStartBtn.disabled = false;
            mfStartBtn.textContent = '🚀 Bắt đầu tải';
        } else if (data.status === 'error') {
            mfStopPolling();
            mfStatusText.textContent = '❌ ' + (data.message || 'Lỗi!');
            mfStatusText.style.color = '#ef4444';
            mfPhaseText.textContent = '⚠️ Thất bại';
            mfStopBtn.style.display = 'none';
            mfStartBtn.disabled = false;
            mfStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'stopped') {
            mfStopPolling();
            mfStatusText.textContent = '⏹ ' + (data.message || 'Đã dừng.');
            mfStatusText.style.color = '#f59e0b';
            mfPhaseText.textContent = '⏸ Đã tạm dừng, có thể resume';
            mfStopBtn.style.display = 'none';
            mfStartBtn.disabled = false;
            mfStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading') {
            mfStartBtn.disabled = true;
            mfStartBtn.textContent = '⏳ Đang chạy...';
            mfStatusSection.style.display = 'block';
            mfStatusText.style.color = '#3b82f6';
            mfStopBtn.style.display = 'block';
        }
    }

    function mfPollStatus() {
        fetch('/api/mediafire/status')
            .then(function (r) { return r.json(); })
            .then(function (data) { mfUpdateStatusUI(data, false); })
            .catch(function () { });
    }

    function mfRestoreStatus() {
        fetch('/api/mediafire/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var hasLogs = data.logs && data.logs.length > 0;
                var active = data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading';
                var terminal = data.status === 'done' || data.status === 'error' || data.status === 'stopped';
                if (!hasLogs && !active && !terminal) return;
                mfStatusSection.style.display = 'block';
                mfUpdateStatusUI(data, true);
                if (active) mfStartPolling();
            })
            .catch(function () { });
    }

    function mfStop() {
        fetch('/api/mediafire/stop', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function () {
                mfStopPolling();
                mfStatusText.textContent = '⏹ Đã dừng bởi người dùng.';
                mfStartBtn.disabled = false;
                mfStartBtn.textContent = '🚀 Bắt đầu tải';
            })
            .catch(function (e) { alert('Lỗi: ' + e); });
    }

    function mfReset(deleteFiles) {
        var confirmMsg = deleteFiles
            ? 'Xóa toàn bộ file tạm MediaFire (.part) và trạng thái hiện tại? Sau đó sẽ tải lại từ đầu.'
            : 'Xóa trạng thái/log MediaFire đang hiển thị? File .part để resume sẽ được giữ lại.';
        if (!confirm(confirmMsg)) return;

        fetch('/api/mediafire/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: !!deleteFiles })
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok) throw new Error(data.error || 'Reset thất bại');
                    return data;
                });
            })
            .then(function () {
                mfStopPolling();
                mfStatusSection.style.display = 'none';
                mfStatusText.textContent = 'Đang xử lý...';
                mfPhaseText.textContent = '';
                mfProgressBar.style.width = '0%';
                mfProgressPercent.textContent = '0%';
                mfProgressDetail.textContent = '';
                mfConsole.textContent = 'Đang chờ...';
                mfLastLogCount = 0;
                mfRenderedLogKey = '';
                mfStartBtn.disabled = false;
                mfStartBtn.textContent = '🚀 Bắt đầu tải';
                mfStopBtn.style.display = 'none';
                alert(deleteFiles ? 'Đã xóa trạng thái và file tạm.' : 'Đã xóa trạng thái.');
            })
            .catch(function (e) { alert('Lỗi: ' + e.message); });
    }

    function mfQueue() {
        var url = mfUrlInput.value.trim();
        var dest = mfDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link MediaFire!'); return; }
        if (!mfValidUrl(url)) { alert('Danh sách không có link MediaFire folder/file hợp lệ.'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        var queueBtn = document.getElementById('mediafireQueueBtn');
        if (queueBtn) {
            queueBtn.disabled = true;
            queueBtn.textContent = '⏳ Đang thêm...';
        }

        fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, output_dir: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.message) {
                    alert(data.message);
                    mfUrlInput.value = '';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể thêm vào hàng đợi'));
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
            })
            .finally(function () {
                if (queueBtn) {
                    queueBtn.disabled = false;
                    queueBtn.textContent = '⏳ Thêm hàng đợi';
                }
            });
    }

    mfCheckBtn.addEventListener('click', mfCheckInfo);
    mfStartBtn.addEventListener('click', mfStart);
    mfStopBtn.addEventListener('click', mfStop);
    var mfQueueBtn = document.getElementById('mediafireQueueBtn');
    if (mfQueueBtn) mfQueueBtn.addEventListener('click', mfQueue);
    if (mfResetBtn) mfResetBtn.addEventListener('click', function () { mfReset(false); });
    if (mfClearTempBtn) mfClearTempBtn.addEventListener('click', function () { mfReset(true); });

    mfRestoreStatus();
})();

// ==================== MEGA TAB ====================
(function () {
    return; // Obsolete, replaced by unified transfer queue
    var megaUrlInput = document.getElementById('megaUrl');
    var megaDestInput = document.getElementById('megaDest');
    var megaCheckBtn = document.getElementById('megaCheckBtn');
    var megaStartBtn = document.getElementById('megaStartBtn');
    var megaStopBtn = document.getElementById('megaStopBtn');
    var megaResetBtn = document.getElementById('megaResetBtn');
    var megaClearTempBtn = document.getElementById('megaClearTempBtn');
    var megaFileInfo = document.getElementById('megaFileInfo');
    var megaFileName = document.getElementById('megaFileName');
    var megaFileSize = document.getElementById('megaFileSize');
    var megaStatusSection = document.getElementById('megaStatusSection');
    var megaStatusText = document.getElementById('megaStatusText');
    var megaPhaseText = document.getElementById('megaPhaseText');
    var megaProgressBar = document.getElementById('megaProgressBar');
    var megaProgressPercent = document.getElementById('megaProgressPercent');
    var megaProgressDetail = document.getElementById('megaProgressDetail');
    var megaConsole = document.getElementById('megaConsole');

    if (!megaUrlInput || !megaDestInput) return;

    var megaPollingInterval = null;
    var megaLastLogCount = 0;
    var megaRenderedLogKey = '';

    var savedMegaLink = localStorage.getItem('mega_link');
    var savedMegaDest = localStorage.getItem('mega_dest');
    if (savedMegaLink) megaUrlInput.value = savedMegaLink;
    if (savedMegaDest) megaDestInput.value = savedMegaDest;

    function megaValidUrl(url) {
        return /mega\.(?:nz|co\.nz|io)\/(?:folder\/|file\/|#F!|#\??!)/i.test(url);
    }

    function megaCheckInfo() {
        var url = megaUrlInput.value.trim();
        if (!url) {
            alert('Vui lòng nhập link Mega.nz!');
            return;
        }
        if (!megaValidUrl(url)) {
            alert('Link Mega.nz không hợp lệ. Phải có dạng /folder/..., /file/..., /#F! hoặc /#!');
            return;
        }

        megaCheckBtn.disabled = true;
        megaCheckBtn.textContent = '⏳ Đang kiểm tra...';
        megaFileInfo.style.display = 'none';

        fetch('/api/mega/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    megaFileName.textContent = data.folder_name || 'Mega Folder';
                    var detail = data.total_size_human || 'Chưa có dung lượng';
                    if (data.file_count) {
                        detail += ' · ' + data.file_count + ' file';
                    }
                    megaFileSize.textContent = detail;
                    megaFileInfo.style.display = 'block';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không lấy được thông tin thư mục'));
                }
            })
            .catch(function (e) { alert('Lỗi kết nối: ' + e); })
            .finally(function () {
                megaCheckBtn.disabled = false;
                megaCheckBtn.textContent = '🔍 Kiểm tra link';
            });
    }

    function megaStart() {
        var url = megaUrlInput.value.trim();
        var dest = megaDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link Mega.nz!'); return; }
        if (!megaValidUrl(url)) { alert('Link Mega.nz không hợp lệ. Phải có dạng /folder/..., /file/..., /#F! hoặc /#!'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        localStorage.setItem('mega_link', url);
        localStorage.setItem('mega_dest', dest);

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        megaStartBtn.disabled = true;
        megaStartBtn.textContent = '⏳ Đang khởi tạo...';

        fetch('/api/mega/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, destination: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    megaStatusSection.style.display = 'block';
                    megaConsole.textContent = 'Đang khởi tạo pipeline Mega...\n';
                    megaLastLogCount = 0;
                    megaStartPolling();
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể bắt đầu'));
                    megaStartBtn.disabled = false;
                    megaStartBtn.textContent = '🚀 Bắt đầu tải';
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
                megaStartBtn.disabled = false;
                megaStartBtn.textContent = '🚀 Bắt đầu tải';
            });
    }

    function megaStartPolling() {
        if (megaPollingInterval) clearInterval(megaPollingInterval);
        megaPollingInterval = setInterval(megaPollStatus, 2000);
        megaPollStatus();
    }

    function megaStopPolling() {
        if (megaPollingInterval) {
            clearInterval(megaPollingInterval);
            megaPollingInterval = null;
        }
    }

    function megaRenderLogs(logs, replace) {
        if (!logs || logs.length === 0) {
            if (replace) {
                megaConsole.textContent = 'Đang chờ console...';
                megaLastLogCount = 0;
                megaRenderedLogKey = '';
            }
            return;
        }

        var start = replace ? 0 : megaLastLogCount;
        var newLogs = logs.slice(start);
        if (replace) {
            megaConsole.innerHTML = '';
        } else if (newLogs.length === 0) {
            var lastLog = logs[logs.length - 1];
            var currentKey = logs.length + '|' + (lastLog.time || '') + '|' + (lastLog.msg || '');
            if (currentKey !== megaRenderedLogKey && logs.length <= megaLastLogCount) {
                newLogs = logs;
                megaConsole.innerHTML = '';
            }
        }
        if (newLogs.length === 0) return;

        var html = '';
        for (var i = newLogs.length - 1; i >= 0; i--) {
            var log = newLogs[i];
            var color = '#a5b4fc';
            if (log.level === 'ERROR') color = '#ef4444';
            else if (log.level === 'WARNING') color = '#f59e0b';
            else if (log.level === 'INFO') color = '#38bdf8';
            else if (log.level === 'DEBUG') color = '#64748b';
            var safeMsg = String(log.msg || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            html += '<span style="color:' + color + '">[' + log.time + '] ' + safeMsg + '</span>\n';
        }

        if (replace) megaConsole.innerHTML = html;
        else megaConsole.innerHTML = html + megaConsole.innerHTML;
        megaLastLogCount = logs.length;
        var last = logs[logs.length - 1];
        megaRenderedLogKey = logs.length + '|' + (last.time || '') + '|' + (last.msg || '');
        megaConsole.scrollTop = 0;
    }

    function megaUpdateStatusUI(data, replaceLogs) {
        var pct = data.progress || 0;
        megaProgressBar.style.width = pct + '%';
        megaProgressPercent.textContent = pct + '%';
        megaProgressBar.style.background = pct <= 50
            ? 'linear-gradient(90deg, #3b82f6, #60a5fa)'
            : 'linear-gradient(90deg, #22c55e, #4ade80)';

        megaStatusText.textContent = data.message || 'Đang xử lý...';
        var detail = '';
        if (data.total_items && data.total_items > 0) {
            detail += '[' + (data.current_index || 0) + '/' + data.total_items + '] ';
        }
        if (data.file_name) detail += (detail && !detail.endsWith(' ') ? ' · ' : '') + data.file_name;
        if (data.file_size_human) detail += (detail && !detail.endsWith(' ') ? ' · ' : '') + data.file_size_human;
        megaProgressDetail.textContent = detail;

        if (data.phase === 'info' || data.status === 'fetching_info') {
            megaPhaseText.textContent = '🔎 Đang expand danh sách Mega.nz';
        } else if (data.phase === 'download' || data.status === 'downloading') {
            megaPhaseText.textContent = '📥 Đang tải từ Mega.nz';
        } else if (data.phase === 'upload' || data.status === 'uploading') {
            megaPhaseText.textContent = '📤 Đang đẩy lên Google Drive';
        }

        megaRenderLogs(data.logs || [], replaceLogs);

        if (data.status === 'done') {
            megaStopPolling();
            megaStatusText.textContent = '✅ ' + (data.message || 'Hoàn tất!');
            megaStatusText.style.color = '#22c55e';
            megaPhaseText.textContent = '🎉 Xong!';
            megaStopBtn.style.display = 'none';
            megaStartBtn.disabled = false;
            megaStartBtn.textContent = '🚀 Bắt đầu tải';
        } else if (data.status === 'error') {
            megaStopPolling();
            megaStatusText.textContent = '❌ ' + (data.message || 'Lỗi!');
            megaStatusText.style.color = '#ef4444';
            megaPhaseText.textContent = '⚠️ Thất bại';
            megaStopBtn.style.display = 'none';
            megaStartBtn.disabled = false;
            megaStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'stopped') {
            megaStopPolling();
            megaStatusText.textContent = '⏹ ' + (data.message || 'Đã dừng.');
            megaStatusText.style.color = '#f59e0b';
            megaPhaseText.textContent = '⏸ Đã tạm dừng, có thể resume';
            megaStopBtn.style.display = 'none';
            megaStartBtn.disabled = false;
            megaStartBtn.textContent = '▶️ Resume tải';
        } else if (data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading') {
            megaStartBtn.disabled = true;
            megaStartBtn.textContent = '⏳ Đang chạy...';
            megaStatusSection.style.display = 'block';
            megaStatusText.style.color = '#3b82f6';
            megaStopBtn.style.display = 'block';
        }
    }

    function megaPollStatus() {
        fetch('/api/mega/status')
            .then(function (r) { return r.json(); })
            .then(function (data) { megaUpdateStatusUI(data, false); })
            .catch(function () { });
    }

    function megaRestoreStatus() {
        fetch('/api/mega/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var hasLogs = data.logs && data.logs.length > 0;
                var active = data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading';
                var terminal = data.status === 'done' || data.status === 'error' || data.status === 'stopped';
                if (!hasLogs && !active && !terminal) return;
                megaStatusSection.style.display = 'block';
                megaUpdateStatusUI(data, true);
                if (active) megaStartPolling();
            })
            .catch(function () { });
    }

    function megaStop() {
        fetch('/api/mega/stop', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function () {
                megaStopPolling();
                megaStatusText.textContent = '⏹ Đã dừng bởi người dùng.';
                megaStartBtn.disabled = false;
                megaStartBtn.textContent = '🚀 Bắt đầu tải';
            })
            .catch(function (e) { alert('Lỗi: ' + e); });
    }

    function megaReset(deleteFiles) {
        var confirmMsg = deleteFiles
            ? 'Xóa toàn bộ file tạm Mega (.part) và trạng thái hiện tại? Sau đó sẽ tải lại từ đầu.'
            : 'Xóa trạng thái/log Mega đang hiển thị? File .part để resume sẽ được giữ lại.';
        if (!confirm(confirmMsg)) return;

        fetch('/api/mega/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: !!deleteFiles })
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok) throw new Error(data.error || 'Reset thất bại');
                    return data;
                });
            })
            .then(function () {
                megaStopPolling();
                megaStatusSection.style.display = 'none';
                megaStatusText.textContent = 'Đang xử lý...';
                megaPhaseText.textContent = '';
                megaProgressBar.style.width = '0%';
                megaProgressPercent.textContent = '0%';
                megaProgressDetail.textContent = '';
                megaConsole.textContent = 'Đang chờ...';
                megaLastLogCount = 0;
                megaRenderedLogKey = '';
                megaStartBtn.disabled = false;
                megaStartBtn.textContent = '🚀 Bắt đầu tải';
                megaStopBtn.style.display = 'none';
                alert(deleteFiles ? 'Đã xóa trạng thái và file tạm.' : 'Đã xóa trạng thái.');
            })
            .catch(function (e) { alert('Lỗi: ' + e.message); });
    }

    function megaQueue() {
        var url = megaUrlInput.value.trim();
        var dest = megaDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link Mega.nz!'); return; }
        if (!megaValidUrl(url)) { alert('Link Mega.nz không hợp lệ. Phải có dạng /folder/..., /file/..., /#F! hoặc /#!'); return; }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        var queueBtn = document.getElementById('megaQueueBtn');
        if (queueBtn) {
            queueBtn.disabled = true;
            queueBtn.textContent = '⏳ Đang thêm...';
        }

        fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, output_dir: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.message) {
                    alert(data.message);
                    megaUrlInput.value = '';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể thêm vào hàng đợi'));
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
            })
            .finally(function () {
                if (queueBtn) {
                    queueBtn.disabled = false;
                    queueBtn.textContent = '⏳ Thêm hàng đợi';
                }
            });
    }

    megaCheckBtn.addEventListener('click', megaCheckInfo);
    megaStartBtn.addEventListener('click', megaStart);
    megaStopBtn.addEventListener('click', megaStop);
    var megaQueueBtn = document.getElementById('megaQueueBtn');
    if (megaQueueBtn) megaQueueBtn.addEventListener('click', megaQueue);
    if (megaResetBtn) megaResetBtn.addEventListener('click', function () { megaReset(false); });
    if (megaClearTempBtn) megaClearTempBtn.addEventListener('click', function () { megaReset(true); });

    megaRestoreStatus();
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

        // Auto-refresh queue and history tab if user is viewing it
        if (document.getElementById('tab-history').classList.contains('active')) {
            loadQueueLight();
            loadHistoryLight();
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

window.copyToClipboard = function(text, btnElement) {
    if (!text) return;
    function success() {
        if (btnElement) {
            var oldText = btnElement.textContent;
            btnElement.textContent = 'Copied!';
            btnElement.style.color = '#10b981';
            setTimeout(function() {
                btnElement.textContent = oldText;
                btnElement.style.color = '';
            }, 2000);
        }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(success).catch(function() {
            fallbackCopy(text, success);
        });
    } else {
        fallbackCopy(text, success);
    }
};

function fallbackCopy(text, successCallback) {
    var textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        document.execCommand('copy');
        successCallback();
    } catch (err) {
        alert('Không thể copy, vui lòng tự copy: ' + text);
    }
    document.body.removeChild(textArea);
}

function formatUrlsHtml(urlsStr) {
    if (!urlsStr) return 'N/A';
    var parts = urlsStr.split(',');
    var htmlParts = [];
    parts.forEach(function(part) {
        part = part.trim();
        if (!part) return;
        var displayUrl = part.substring(0, 50) + (part.length > 50 ? '...' : '');
        if (part.startsWith('http')) {
            htmlParts.push('<div style="display: flex; align-items: center; margin-bottom: 4px;">' +
                '<a href="' + part + '" target="_blank" style="color: #60a5fa; text-decoration: underline;" title="' + part + '">' + displayUrl + '</a>' +
                ' <button onclick="copyToClipboard(\'' + part.replace(/'/g, "\\'") + '\', this)" class="btn-secondary" style="margin-left: 6px; padding: 2px 6px; font-size: 10px; line-height: 1; border-color: #475569;" title="Copy link">Copy</button>' +
                '</div>');
        } else {
            htmlParts.push('<div style="display: flex; align-items: center; margin-bottom: 4px;">' +
                '<span title="' + part + '">' + displayUrl + '</span>' +
                ' <button onclick="copyToClipboard(\'' + part.replace(/'/g, "\\'") + '\', this)" class="btn-secondary" style="margin-left: 6px; padding: 2px 6px; font-size: 10px; line-height: 1; border-color: #475569;" title="Copy link">Copy</button>' +
                '</div>');
        }
    });
    return htmlParts.join('');
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

        var urlsHtml = formatUrlsHtml(rec.urls || '');

        var jobType = rec.type || 'rclone';
        var typeBadge = '';
        if (jobType === 'fshare') {
            typeBadge = '<span class="status-badge" style="background-color: #3b82f6; color: white; margin-right: 6px; font-size: 10px; padding: 2px 6px; display: inline-block;">Fshare</span>';
        } else if (jobType === 'mediafire') {
            typeBadge = '<span class="status-badge" style="background-color: #f97316; color: white; margin-right: 6px; font-size: 10px; padding: 2px 6px; display: inline-block;">MediaFire</span>';
        } else if (jobType === 'terabox') {
            typeBadge = '<span class="status-badge" style="background-color: #10b981; color: white; margin-right: 6px; font-size: 10px; padding: 2px 6px; display: inline-block;">Terabox</span>';
        } else if (jobType === 'mega') {
            typeBadge = '<span class="status-badge" style="background-color: #ef4444; color: white; margin-right: 6px; font-size: 10px; padding: 2px 6px; display: inline-block;">Mega</span>';
        } else {
            typeBadge = '<span class="status-badge" style="background-color: #6366f1; color: white; margin-right: 6px; font-size: 10px; padding: 2px 6px; display: inline-block;">GDrive</span>';
        }

        row.innerHTML =
            '<td><strong style="color: #60a5fa;">' + execTimeStr + '</strong></td>' +
            '<td style="word-break: break-all; max-width: 450px;">' +
            '<div style="display: flex; align-items: flex-start; flex-wrap: wrap;">' + typeBadge + '<div style="flex: 1; min-width: 0;">' + urlsHtml + '</div></div>' +
            '</td>' +
            '<td style="word-break: break-all;">' + (rec.dest || 'N/A') + '</td>' +
            '<td>' + statusHtml + '</td>' +
            '<td><button type="button" class="btn-secondary" style="padding: 4px 8px; font-size: 12px; border-color: #ef4444; color: #ef4444;" onclick="event.stopPropagation(); removeQueue(\'' + rec.id + '\')">Hủy</button></td>';

        tbody.appendChild(row);
    });
}

window.removeQueue = function (id) {
    showGenericConfirmModal(
        '🗑️',
        'Hủy tiến trình?',
        'Bạn có muốn hủy bỏ tiến trình này khỏi hàng đợi?',
        'Hủy bỏ',
        function () {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/api/queue/remove", true);
            xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4 && xhr.status === 200) {
                    loadQueueLight();
                    if (!isPolling) { isPolling = true; poll(); }
                }
            };
            xhr.send(JSON.stringify({ id: id }));
        }
    );
};

// Reusable confirm modal
function showGenericConfirmModal(icon, title, desc, confirmText, onConfirm) {
    let modal = document.getElementById('genericConfirmModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'genericConfirmModal';
        modal.className = 'confirm-modal-overlay';
        modal.innerHTML = `
            <div class="confirm-modal-box">
                <div class="confirm-modal-icon" id="gcmIcon"></div>
                <h3 class="confirm-modal-title" id="gcmTitle"></h3>
                <p class="confirm-modal-desc" id="gcmDesc"></p>
                <div class="confirm-modal-actions">
                    <button type="button" id="gcmCancel" class="btn-secondary confirm-modal-btn">Không</button>
                    <button type="button" id="gcmConfirm" class="btn-primary confirm-modal-btn" style="background:#ef4444; border-color:#ef4444;"></button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        document.getElementById('gcmCancel').addEventListener('click', (e) => {
            e.stopPropagation();
            modal.classList.remove('active');
        });
        // Removed overlay click-to-dismiss to prevent accidental flashes

    }

    document.getElementById('gcmIcon').textContent = icon;
    document.getElementById('gcmTitle').textContent = title;
    document.getElementById('gcmDesc').innerHTML = desc;
    const confirmBtn = document.getElementById('gcmConfirm');
    confirmBtn.textContent = confirmText;

    // Clone to remove old listeners
    const newBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
    newBtn.addEventListener('click', () => {
        modal.classList.remove('active');
        onConfirm();
    });

    modal.classList.add('active');
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

// ==================== FSHARE CONFIG ====================
function loadFshareConfig() {
    var email = document.getElementById('fshareConfigEmail');
    var password = document.getElementById('fshareConfigPassword');
    var status = document.getElementById('fshareConfigStatus');
    if (!email || !status) return;

    status.textContent = 'Đang tải cấu hình Fshare...';
    status.className = 'config-status';

    fetch('/api/fshare/config')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            email.value = data.email || '';
            password.value = '';
            var parts = [];
            if (data.password_masked) parts.push('password: ' + data.password_masked);
            status.textContent = data.complete
                ? '✅ Fshare đã cấu hình' + (parts.length ? ' (' + parts.join(', ') + ')' : '')
                : '⚠️ Chưa đủ cấu hình Fshare. Cần email và password.';
            status.className = data.complete ? 'config-status success' : 'config-status';
        })
        .catch(function () {
            status.textContent = '❌ Không tải được cấu hình Fshare';
            status.className = 'config-status error';
        });
}

function saveFshareConfig() {
    var email = document.getElementById('fshareConfigEmail');
    var password = document.getElementById('fshareConfigPassword');
    var status = document.getElementById('fshareConfigStatus');
    if (!email || !status) return;

    status.textContent = 'Đang lưu Fshare...';
    status.className = 'config-status';

    var payload = {
        email: email.value.trim(),
        password: password.value.trim() || '__KEEP__'
    };

    fetch('/api/fshare/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                status.textContent = data.complete ? '✅ Đã lưu cấu hình Fshare!' : '⚠️ Đã lưu, nhưng cấu hình vẫn chưa đủ.';
                status.className = data.complete ? 'config-status success' : 'config-status';
                password.value = '';
            } else {
                status.textContent = '❌ ' + (data.error || 'Lỗi lưu Fshare');
                status.className = 'config-status error';
            }
        })
        .catch(function (e) {
            status.textContent = '❌ Lỗi kết nối: ' + e;
            status.className = 'config-status error';
        });
}

var loadFshareConfigBtn = document.getElementById('loadFshareConfigBtn');
var saveFshareConfigBtn = document.getElementById('saveFshareConfigBtn');
if (loadFshareConfigBtn) loadFshareConfigBtn.addEventListener('click', loadFshareConfig);
if (saveFshareConfigBtn) saveFshareConfigBtn.addEventListener('click', saveFshareConfig);

// ==================== FICHIER CONFIG ====================
function loadFichierConfig() {
    var apiKey = document.getElementById('fichierApiKey');
    var status = document.getElementById('fichierConfigStatus');
    if (!apiKey || !status) return;

    status.textContent = 'Đang tải cấu hình 1fichier...';
    status.className = 'config-status';

    fetch('/api/fichier/config')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            apiKey.value = '';
            status.textContent = data.complete
                ? '✅ 1fichier đã cấu hình (API Key: ' + data.api_key_masked + ')'
                : 'ℹ️ Chưa cấu hình API Key. Hệ thống sẽ dùng chế độ Tự động (Free).';
            status.className = data.complete ? 'config-status success' : 'config-status';
            checkConfigStatus();
        })
        .catch(function () {
            status.textContent = '❌ Không tải được cấu hình 1fichier';
            status.className = 'config-status error';
        });
}

function saveFichierConfig() {
    var apiKey = document.getElementById('fichierApiKey');
    var status = document.getElementById('fichierConfigStatus');
    if (!apiKey || !status) return;

    status.textContent = 'Đang lưu 1fichier...';
    status.className = 'config-status';

    var payload = {
        api_key: apiKey.value.trim() || '__KEEP__'
    };

    fetch('/api/fichier/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                status.textContent = data.complete ? '✅ Đã lưu API Key 1fichier!' : 'ℹ️ Đã xóa API Key, chuyển sang chế độ Tự động (Free).';
                status.className = data.complete ? 'config-status success' : 'config-status';
                apiKey.value = '';
                checkConfigStatus();
            } else {
                status.textContent = '❌ ' + (data.error || 'Lỗi lưu 1fichier');
                status.className = 'config-status error';
            }
        })
        .catch(function (e) {
            status.textContent = '❌ Lỗi kết nối: ' + e;
            status.className = 'config-status error';
        });
}

function clearFichierConfig() {
    var apiKey = document.getElementById('fichierApiKey');
    var status = document.getElementById('fichierConfigStatus');
    if (!apiKey || !status) return;

    if (!confirm('Bạn có chắc chắn muốn xóa API Key 1fichier và chuyển về chế độ Tự động (Free)?')) {
        return;
    }

    status.textContent = 'Đang xóa API Key...';
    status.className = 'config-status';

    fetch('/api/fichier/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: '' })
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                status.textContent = 'ℹ️ Đã xóa API Key, chuyển sang chế độ Tự động (Free).';
                status.className = 'config-status success';
                apiKey.value = '';
                checkConfigStatus();
            } else {
                status.textContent = '❌ ' + (data.error || 'Lỗi xóa API Key');
                status.className = 'config-status error';
            }
        })
        .catch(function (e) {
            status.textContent = '❌ Lỗi kết nối: ' + e;
            status.className = 'config-status error';
        });
}

var loadFichierConfigBtn = document.getElementById('loadFichierConfigBtn');
var clearFichierConfigBtn = document.getElementById('clearFichierConfigBtn');
var saveFichierConfigBtn = document.getElementById('saveFichierConfigBtn');
if (loadFichierConfigBtn) loadFichierConfigBtn.addEventListener('click', loadFichierConfig);
if (clearFichierConfigBtn) clearFichierConfigBtn.addEventListener('click', clearFichierConfig);
if (saveFichierConfigBtn) saveFichierConfigBtn.addEventListener('click', saveFichierConfig);

// ==================== PIXELDRAIN CONFIG ====================
function loadPixeldrainConfig() {
    var apiKey = document.getElementById('pixeldrainApiKey');
    var status = document.getElementById('pixeldrainConfigStatus');
    if (!apiKey || !status) return;

    status.textContent = 'Đang tải cấu hình Pixeldrain...';
    status.className = 'config-status';

    fetch('/api/pixeldrain/config')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            apiKey.value = '';
            status.textContent = data.complete
                ? '✅ Pixeldrain đã cấu hình (API Key: ' + data.api_key_masked + ')'
                : 'ℹ️ Chưa cấu hình API Key. Hệ thống sẽ dùng chế độ Tự động (Free).';
            status.className = data.complete ? 'config-status success' : 'config-status';
            checkConfigStatus();
        })
        .catch(function () {
            status.textContent = '❌ Không tải được cấu hình Pixeldrain';
            status.className = 'config-status error';
        });
}

function savePixeldrainConfig() {
    var apiKey = document.getElementById('pixeldrainApiKey');
    var status = document.getElementById('pixeldrainConfigStatus');
    if (!apiKey || !status) return;

    status.textContent = 'Đang lưu Pixeldrain...';
    status.className = 'config-status';

    var payload = {
        api_key: apiKey.value.trim() || '__KEEP__'
    };

    fetch('/api/pixeldrain/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                status.textContent = data.complete ? '✅ Đã lưu API Key Pixeldrain!' : 'ℹ️ Đã xóa API Key, chuyển sang chế độ Tự động (Free).';
                status.className = data.complete ? 'config-status success' : 'config-status';
                apiKey.value = '';
                checkConfigStatus();
            } else {
                status.textContent = '❌ ' + (data.error || 'Lỗi lưu Pixeldrain');
                status.className = 'config-status error';
            }
        })
        .catch(function (e) {
            status.textContent = '❌ Lỗi kết nối: ' + e;
            status.className = 'config-status error';
        });
}

function clearPixeldrainConfig() {
    var apiKey = document.getElementById('pixeldrainApiKey');
    var status = document.getElementById('pixeldrainConfigStatus');
    if (!apiKey || !status) return;

    if (!confirm('Bạn có chắc chắn muốn xóa API Key Pixeldrain và chuyển về chế độ Tự động (Free)?')) {
        return;
    }

    status.textContent = 'Đang xóa API Key Pixeldrain...';
    status.className = 'config-status';

    fetch('/api/pixeldrain/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: '' })
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                status.textContent = 'ℹ️ Đã xóa API Key, chuyển sang chế độ Tự động (Free).';
                status.className = 'config-status success';
                apiKey.value = '';
                checkConfigStatus();
            } else {
                status.textContent = '❌ ' + (data.error || 'Lỗi xóa API Key');
                status.className = 'config-status error';
            }
        })
        .catch(function (e) {
            status.textContent = '❌ Lỗi kết nối: ' + e;
            status.className = 'config-status error';
        });
}

var loadPixeldrainConfigBtn = document.getElementById('loadPixeldrainConfigBtn');
var clearPixeldrainConfigBtn = document.getElementById('clearPixeldrainConfigBtn');
var savePixeldrainConfigBtn = document.getElementById('savePixeldrainConfigBtn');
if (loadPixeldrainConfigBtn) loadPixeldrainConfigBtn.addEventListener('click', loadPixeldrainConfig);
if (clearPixeldrainConfigBtn) clearPixeldrainConfigBtn.addEventListener('click', clearPixeldrainConfig);
if (savePixeldrainConfigBtn) savePixeldrainConfigBtn.addEventListener('click', savePixeldrainConfig);

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
    loadPendingBadge();
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
    loadHistoryLight();
}

function loadHistoryLight() {
    var tbody = document.getElementById('historyListBody');
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/history", true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                try {
                    renderHistory(JSON.parse(xhr.responseText));
                } catch(e) {}
            } else if (tbody && tbody.children.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #ef4444; padding: 20px;">Lỗi tải lịch sử</td></tr>';
            }
        }
    };
    xhr.send();
}

function renderHistory(records) {
    var tbody = document.getElementById('historyListBody');
    if (!tbody) return;
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
            var errMsg = (rec.message || 'Lỗi không xác định').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            statusHtml = '<span class="status-badge status-error" title="' + (rec.message || '') + '">Lỗi</span>' +
                (rec.message ? '<div style="font-size: 11px; color: #f87171; margin-top: 4px; word-break: break-word; max-width: 250px;">' + errMsg + '</div>' : '');
        } else if (rec.status === 'downloading' || rec.status === 'initializing') {
            statusHtml = '<span class="status-badge" style="background-color: #3b82f6; color: white;">Đang tải (' + (rec.progress || 0) + '%)</span>';
        } else {
            statusHtml = '<span class="status-badge">' + (rec.status || 'N/A') + '</span>';
        }

        var urlsHtml = formatUrlsHtml(rec.urls || '');

        row.innerHTML =
            '<td>' + (rec.time || 'N/A') + '</td>' +
            '<td style="word-break: break-all; max-width: 450px;">' + urlsHtml + '</td>' +
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

// ==================== PENDING FILES MANAGEMENT ====================
function loadPendingBadge() {
    fetch('/api/pending/list')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            var badge = document.getElementById('pendingBadge');
            if (badge) {
                var count = (data && data.count) || 0;
                if (count > 0) {
                    badge.textContent = count;
                    badge.style.display = 'inline-block';
                } else {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(function () {});
}

function loadPendingList() {
    var tbody = document.getElementById('pendingListBody');
    if (tbody && (!tbody.children.length || tbody.children[0].innerText.indexOf('Đang') !== -1)) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 25px; color: var(--text-muted);">Đang tải danh sách file tạm...</td></tr>';
    }

    fetch('/api/pending/list')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            renderPendingList(data);
        })
        .catch(function (err) {
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #ef4444; padding: 25px;">Lỗi khi tải danh sách: ' + (err.message || err) + '</td></tr>';
            }
        });
}

function renderPendingList(data) {
    var tbody = document.getElementById('pendingListBody');
    var countDisplay = document.getElementById('pendingCountDisplay');
    var wasteDisplay = document.getElementById('pendingWasteDisplay');
    var badge = document.getElementById('pendingBadge');

    var count = (data && data.count) || 0;
    var totalHuman = (data && data.total_size_human) || '0 B';
    var items = (data && data.items) || [];

    if (countDisplay) countDisplay.textContent = count;
    if (wasteDisplay) wasteDisplay.textContent = totalHuman;

    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    }

    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 30px; color: var(--text-muted); font-size: 0.95rem;">🎉 Tuyệt vời! Không có file tạm hoặc download dở dang nào trên hệ thống.</td></tr>';
        return;
    }

    tbody.innerHTML = '';
    items.forEach(function (item) {
        var tr = document.createElement('tr');

        // Engine badge
        var engColors = {
            'fshare': '#dc2626',
            'terabox': '#2563eb',
            'mediafire': '#0284c7',
            'mega': '#ea580c',
            'fichier': '#7c3aed',
            'pixeldrain': '#059669'
        };
        var engColor = engColors[item.engine] || '#64748b';
        var engineBadge = '<span class="status-badge" style="background-color: ' + engColor + '; color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 4px;">' +
            (item.engine_display || item.engine || 'Unknown') + '</span>';

        // URL / Name display
        var nameSafe = (item.name || item.folder_key || 'N/A').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        var nameHtml = '<div style="font-weight: 600; color: var(--text-color); margin-bottom: 4px; word-break: break-all;">' + nameSafe + '</div>';
        if (item.url) {
            var urlSafe = item.url.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            nameHtml += '<div style="font-size: 11px; color: var(--text-muted); word-break: break-all;">' +
                '<a href="' + encodeURI(item.url) + '" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: underline;">' + urlSafe + '</a>' +
                '</div>';
        } else {
            nameHtml += '<div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">Hash: ' + (item.folder_key || item.path) + '</div>';
        }

        // Status badge
        var statusBadge = '';
        if (item.is_active) {
            statusBadge = '<span class="status-badge" style="background-color: #3b82f6; color: white;">⚡ Đang tải (Active)</span>';
        } else if (item.status === 'incomplete') {
            statusBadge = '<span class="status-badge" style="background-color: #f59e0b; color: #1e293b; font-weight: 600;">⚠️ Tải dở dang (.part)</span>';
        } else if (item.status === 'completed_unuploaded') {
            statusBadge = '<span class="status-badge" style="background-color: #8b5cf6; color: white;">📦 Chưa upload</span>';
        } else {
            statusBadge = '<span class="status-badge" style="background-color: #64748b; color: white;">' + (item.status_display || item.status) + '</span>';
        }

        // Action button
        var actionBtn = '';
        if (item.is_active) {
            actionBtn = '<span style="font-size: 11px; color: var(--text-muted);">Đang chạy</span>';
        } else {
            actionBtn = '<button class="btn-secondary btn-delete-pending" style="padding: 4px 8px; border: 1px solid #ef4444; color: #ef4444; border-radius: 4px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px; cursor: pointer;" title="Xóa thư mục tạm này">' +
                '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>' +
                '</svg> Xóa</button>';
        }

        tr.innerHTML =
            '<td>' + engineBadge + '</td>' +
            '<td style="max-width: 450px;">' + nameHtml + '</td>' +
            '<td style="font-weight: 600; color: #f59e0b;">' + (item.size_human || '0 B') + '</td>' +
            '<td>' + statusBadge + '</td>' +
            '<td style="font-size: 12px; color: var(--text-muted);">' + (item.modified_at || 'N/A') + '</td>' +
            '<td style="text-align: center;">' + actionBtn + '</td>';

        var btn = tr.querySelector('.btn-delete-pending');
        if (btn) {
            btn.addEventListener('click', function () {
                deletePendingItem(item.path, item.name || item.folder_key);
            });
        }

        tbody.appendChild(tr);
    });
}

function deletePendingItem(path, displayName) {
    if (!confirm('Bạn có chắc muốn xóa file tạm này?\n\n' + (displayName || path))) {
        return;
    }

    fetch('/api/pending/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path })
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                loadPendingList();
            } else {
                alert('Lỗi: ' + (data.error || 'Không thể xóa'));
            }
        })
        .catch(function (err) {
            alert('Lỗi kết nối: ' + err.message);
        });
}

function clearAllPending() {
    if (!confirm('Bạn có chắc muốn XÓA TẤT CẢ các file tạm / download dở dang trên hệ thống không?\n\nThao tác này sẽ dọn sạch các thư mục /tmp/*_dl và giải phóng dung lượng ổ cứng!')) {
        return;
    }

    var tbody = document.getElementById('pendingListBody');
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 25px; color: var(--text-muted);">Đang dọn sạch tất cả file tạm...</td></tr>';
    }

    fetch('/api/pending/clear_all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.success) {
                alert('Đã dọn dẹp thành công!\n- Số mục đã xóa: ' + (data.deleted_count || 0) + '\n- Dung lượng giải phóng: ' + (data.freed_human || '0 B'));
                loadPendingList();
            } else {
                alert('Lỗi: ' + (data.error || 'Không thể dọn dẹp'));
                loadPendingList();
            }
        })
        .catch(function (err) {
            alert('Lỗi kết nối: ' + err.message);
            loadPendingList();
        });
}

document.addEventListener('DOMContentLoaded', function () {
    var refreshPendingBtn = document.getElementById('refreshPendingBtn');
    if (refreshPendingBtn) {
        refreshPendingBtn.addEventListener('click', function () {
            loadPendingList();
        });
    }

    var clearAllPendingBtn = document.getElementById('clearAllPendingBtn');
    if (clearAllPendingBtn) {
        clearAllPendingBtn.addEventListener('click', function () {
            clearAllPending();
        });
    }
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

    // Initialize config status badges and terabox cookie details
    checkConfigStatus();
    tbLoadCookie();
});


// ==================== TERABOX TAB ====================
(function () {
    return; // Obsolete, replaced by unified transfer queue
    // DOM elements
    var tbCookieInput = document.getElementById('teraboxCookie');
    var tbSaveCookieBtn = document.getElementById('teraboxSaveCookieBtn');
    var tbCookieStatus = document.getElementById('teraboxCookieStatus');
    var tbAccountStatus = document.getElementById('teraboxAccountStatus');
    var tbUrlInput = document.getElementById('teraboxUrl');
    var tbDestInput = document.getElementById('teraboxDest');
    var tbCheckBtn = document.getElementById('teraboxCheckBtn');
    var tbStartBtn = document.getElementById('teraboxStartBtn');
    var tbStopBtn = document.getElementById('teraboxStopBtn');
    var tbResetBtn = document.getElementById('teraboxResetBtn');
    var tbClearTempBtn = document.getElementById('teraboxClearTempBtn');
    var tbFileInfo = document.getElementById('teraboxFileInfo');
    var tbFileName = document.getElementById('teraboxFileName');
    var tbFileSize = document.getElementById('teraboxFileSize');
    var tbStatusSection = document.getElementById('teraboxStatusSection');
    var tbStatusText = document.getElementById('teraboxStatusText');
    var tbPhaseText = document.getElementById('teraboxPhaseText');
    var tbProgressBar = document.getElementById('teraboxProgressBar');
    var tbProgressPercent = document.getElementById('teraboxProgressPercent');
    var tbProgressDetail = document.getElementById('teraboxProgressDetail');
    var tbConsole = document.getElementById('teraboxConsole');

    // Guard: if elements don't exist (page without terabox tab), bail
    if (!tbCookieInput || !tbUrlInput) return;

    var tbPollingInterval = null;
    var tbLastLogCount = 0;
    var tbRenderedLogKey = '';

    // Restore from localStorage
    var savedTbLink = localStorage.getItem('tb_link');
    var savedTbDest = localStorage.getItem('tb_dest');
    if (savedTbLink) tbUrlInput.value = savedTbLink;
    if (savedTbDest) tbDestInput.value = savedTbDest;

    // ---- Cookie Management ----
    function tbLoadCookie() {
        fetch('/api/terabox/cookie')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.has_cookie) {
                    if (tbCookieStatus) {
                        tbCookieStatus.innerHTML = '✅ Cookie đã lưu (<code>' + data.masked + '</code>)';
                        tbCookieStatus.style.color = '#22c55e';
                    }
                    if (tbAccountStatus) {
                        tbAccountStatus.innerHTML = '✅ Cookie Terabox ndus đã được lưu. Sẵn sàng tải file.';
                        tbAccountStatus.style.color = '#22c55e';
                        tbAccountStatus.style.borderColor = 'rgba(34,197,94,.35)';
                        tbAccountStatus.style.background = 'rgba(34,197,94,.1)';
                    }
                } else {
                    if (tbCookieStatus) {
                        tbCookieStatus.innerHTML = '⚠️ Chưa có cookie. Vui lòng nhập và lưu.';
                        tbCookieStatus.style.color = '#f59e0b';
                    }
                    if (tbAccountStatus) {
                        tbAccountStatus.innerHTML = '⚠️ Chưa cấu hình Cookie Terabox ndus. Vui lòng cấu hình ở tab <strong>Cấu hình</strong>.';
                        tbAccountStatus.style.color = '#f59e0b';
                        tbAccountStatus.style.borderColor = 'rgba(245,158,11,.35)';
                        tbAccountStatus.style.background = 'rgba(245,158,11,.1)';
                    }
                }
            })
            .catch(function () {
                if (tbCookieStatus) {
                    tbCookieStatus.textContent = '❌ Không thể kiểm tra cookie.';
                    tbCookieStatus.style.color = '#ef4444';
                }
                if (tbAccountStatus) {
                    tbAccountStatus.textContent = '❌ Không thể kiểm tra cookie. Vui lòng kiểm tra lại cấu hình.';
                    tbAccountStatus.style.color = '#ef4444';
                    tbAccountStatus.style.borderColor = 'rgba(239,68,68,.35)';
                    tbAccountStatus.style.background = 'rgba(239,68,68,.1)';
                }
            });
    }

    function tbSaveCookie() {
        var val = tbCookieInput.value.trim();
        if (!val) {
            alert('Vui lòng nhập cookie ndus!');
            return;
        }
        tbSaveCookieBtn.disabled = true;
        tbSaveCookieBtn.textContent = '⏳ Đang lưu...';

        fetch('/api/terabox/cookie', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cookie: val })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    tbCookieInput.value = '';
                    tbLoadCookie();
                } else {
                    alert('Lỗi: ' + (data.error || 'Không rõ'));
                }
            })
            .catch(function (e) { alert('Lỗi kết nối: ' + e); })
            .finally(function () {
                tbSaveCookieBtn.disabled = false;
                tbSaveCookieBtn.textContent = '💾 Lưu';
            });
    }

    // ---- Check File Info ----
    function tbCheckInfo() {
        var rawUrl = tbUrlInput.value.trim();
        if (!rawUrl) {
            alert('Vui lòng nhập link Terabox!');
            return;
        }
        var lines = rawUrl.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
        var url = lines[0] || '';

        var isTerabox = !/terabox|1024tera|nephobox|4funbox|mirrobox|momerybox|tibibox|tibabox|freeterabox|terasharelink|teraboxlink|teraboxshare|dubox|momotera|miyauplat|funletu|ytbterabox/i.test(url);
        if (isTerabox) {
            alert('Dòng đầu tiên không phải link Terabox. Cần link dạng: https://www.terabox.app/s/...');
            return;
        }

        tbCheckBtn.disabled = true;
        tbCheckBtn.textContent = '⏳ Đang kiểm tra...';
        tbFileInfo.style.display = 'none';

        fetch('/api/terabox/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    tbFileName.textContent = (lines.length > 1 ? '[Link 1] ' : '') + data.file_name;
                    var detail = data.file_size_human || '';
                    if (data.download_url_ready === false) {
                        detail += ' · đã lấy metadata, link tải sẽ thử lại khi bắt đầu';
                    }
                    if (data.missing_fields && data.missing_fields.length > 0) {
                        detail += ' · thiếu: ' + data.missing_fields.join(', ');
                    }
                    tbFileSize.textContent = detail;
                    tbFileInfo.style.display = 'block';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không lấy được thông tin file'));
                }
            })
            .catch(function (e) { alert('Lỗi kết nối: ' + e); })
            .finally(function () {
                tbCheckBtn.disabled = false;
                tbCheckBtn.textContent = '🔍 Kiểm tra link';
            });
    }

    // ---- Start Pipeline ----
    function tbStart() {
        var url = tbUrlInput.value.trim();
        var dest = tbDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link Terabox!'); return; }
        var lines = url.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
        if (lines.length === 0) { alert('Vui lòng nhập link Terabox!'); return; }
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (!/terabox|1024tera|nephobox|4funbox|mirrobox|momerybox|tibibox|tibabox|freeterabox|terasharelink|teraboxlink|teraboxshare|dubox|momotera|miyauplat|funletu|ytbterabox/i.test(line)) {
                alert('Dòng ' + (i + 1) + ' không phải link Terabox hợp lệ!');
                return;
            }
        }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        // Save to localStorage
        localStorage.setItem('tb_link', url);
        localStorage.setItem('tb_dest', dest);

        // Convert Google Drive URL if needed
        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        tbStartBtn.disabled = true;
        tbStartBtn.textContent = '⏳ Đang khởi tạo...';

        fetch('/api/terabox/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, destination: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) {
                    // Show progress section
                    tbStatusSection.style.display = 'block';
                    tbConsole.textContent = 'Đang khởi tạo pipeline...\n';
                    tbLastLogCount = 0;

                    // Start polling
                    tbStartPolling();
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể bắt đầu'));
                    tbStartBtn.disabled = false;
                    tbStartBtn.textContent = '🚀 Bắt đầu tải';
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
                tbStartBtn.disabled = false;
                tbStartBtn.textContent = '🚀 Bắt đầu tải';
            });
    }

    // ---- Polling ----
    function tbStartPolling() {
        if (tbPollingInterval) clearInterval(tbPollingInterval);
        tbPollingInterval = setInterval(tbPollStatus, 2000);
        tbPollStatus(); // immediate first call
    }

    function tbStopPolling() {
        if (tbPollingInterval) {
            clearInterval(tbPollingInterval);
            tbPollingInterval = null;
        }
    }

    function tbRenderLogs(logs, replace) {
        if (!logs || logs.length === 0) {
            if (replace) {
                tbConsole.textContent = 'Đang chờ console...';
                tbLastLogCount = 0;
                tbRenderedLogKey = '';
            }
            return;
        }

        var start = replace ? 0 : tbLastLogCount;
        var newLogs = logs.slice(start);
        if (replace) {
            tbConsole.innerHTML = '';
        } else if (newLogs.length === 0) {
            var lastLog = logs[logs.length - 1];
            var currentKey = logs.length + '|' + (lastLog.time || '') + '|' + (lastLog.msg || '');
            if (currentKey !== tbRenderedLogKey && logs.length <= tbLastLogCount) {
                newLogs = logs;
                tbConsole.innerHTML = '';
            }
        }

        if (newLogs.length === 0) return;

        var html = '';
        for (var i = newLogs.length - 1; i >= 0; i--) {
            var log = newLogs[i];
            var color = '#a5b4fc'; // default
            if (log.level === 'ERROR') color = '#ef4444';
            else if (log.level === 'WARNING') color = '#f59e0b';
            else if (log.level === 'INFO') color = '#38bdf8';
            else if (log.level === 'DEBUG') color = '#64748b';

            var safeMsg = String(log.msg || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            html += '<span style="color:' + color + '">[' + log.time + '] ' + safeMsg + '</span>\n';
        }

        if (replace) {
            tbConsole.innerHTML = html;
        } else {
            tbConsole.innerHTML = html + tbConsole.innerHTML;
        }
        tbLastLogCount = logs.length;
        var last = logs[logs.length - 1];
        tbRenderedLogKey = logs.length + '|' + (last.time || '') + '|' + (last.msg || '');
        tbConsole.scrollTop = 0;
    }

    function tbUpdateStatusUI(data, replaceLogs) {
                // Update progress bar
                var pct = data.progress || 0;
                tbProgressBar.style.width = pct + '%';
                tbProgressPercent.textContent = pct + '%';

                // Color based on phase: download=blue, upload=green
                if (pct <= 50) {
                    tbProgressBar.style.background = 'linear-gradient(90deg, #3b82f6, #60a5fa)';
                } else {
                    tbProgressBar.style.background = 'linear-gradient(90deg, #22c55e, #4ade80)';
                }

                // Update status text
                tbStatusText.textContent = data.message || 'Đang xử lý...';
                var progressDetail = '';
                if (data.total_items && data.total_items > 0) {
                    progressDetail += '[' + (data.current_index || 0) + '/' + data.total_items + '] ';
                }
                if (data.file_name) progressDetail += data.file_name;
                if (data.file_size_human) {
                    progressDetail += (progressDetail ? ' · ' : '') + data.file_size_human;
                }
                tbProgressDetail.textContent = progressDetail;

                // Phase indicator
                if (data.phase === 'info' || data.status === 'fetching_info') {
                    tbPhaseText.textContent = '🔎 Đang lấy thông tin Terabox';
                } else if (data.phase === 'download' || data.status === 'downloading') {
                    tbPhaseText.textContent = '📥 Đang tải từ Terabox';
                } else if (data.phase === 'upload' || data.status === 'uploading') {
                    tbPhaseText.textContent = '📤 Đang đẩy lên Google Drive';
                }

                tbRenderLogs(data.logs || [], replaceLogs);

                // Terminal states
                if (data.status === 'done') {
                    tbStopPolling();
                    tbStatusText.textContent = '✅ ' + (data.message || 'Hoàn tất!');
                    tbStatusText.style.color = '#22c55e';
                    tbPhaseText.textContent = '🎉 Xong!';
                    tbStopBtn.style.display = 'none';
                    tbStartBtn.disabled = false;
                    tbStartBtn.textContent = '🚀 Bắt đầu tải';
                } else if (data.status === 'error') {
                    tbStopPolling();
                    tbStatusText.textContent = '❌ ' + (data.message || 'Lỗi!');
                    tbStatusText.style.color = '#ef4444';
                    tbPhaseText.textContent = '⚠️ Thất bại';
                    tbStopBtn.style.display = 'none';
                    tbStartBtn.disabled = false;
                    tbStartBtn.textContent = '▶️ Resume tải';
                } else if (data.status === 'stopped') {
                    tbStopPolling();
                    tbStatusText.textContent = '⏹ ' + (data.message || 'Đã dừng.');
                    tbStatusText.style.color = '#f59e0b';
                    tbPhaseText.textContent = '⏸ Đã tạm dừng, có thể resume';
                    tbStopBtn.style.display = 'none';
                    tbStartBtn.disabled = false;
                    tbStartBtn.textContent = '▶️ Resume tải';
                } else if (data.status === 'paused') {
                    tbStopPolling();
                    tbStatusText.textContent = '⏸ ' + (data.message || 'Đang tạm dừng, có thể resume.');
                    tbStatusText.style.color = '#f59e0b';
                    tbPhaseText.textContent = '⏸ Chờ resume';
                    tbStopBtn.style.display = 'none';
                    tbStartBtn.disabled = false;
                    tbStartBtn.textContent = '▶️ Resume tải';
                } else if (data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading') {
                    tbStartBtn.disabled = true;
                    tbStartBtn.textContent = '⏳ Đang chạy...';
                    tbStatusSection.style.display = 'block';
                    tbStatusText.style.color = '#3b82f6';
                    tbStopBtn.style.display = 'block';
                }
    }

    function tbPollStatus() {
        fetch('/api/terabox/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                tbUpdateStatusUI(data, false);
            })
            .catch(function () {
                // Silently ignore polling errors
            });
    }

    function tbRestoreStatus() {
        fetch('/api/terabox/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var hasLogs = data.logs && data.logs.length > 0;
                var active = data.status === 'fetching_info' || data.status === 'downloading' || data.status === 'uploading';
                var terminal = data.status === 'done' || data.status === 'error' || data.status === 'stopped' || data.status === 'paused';
                if (!hasLogs && !active && !terminal) return;

                tbStatusSection.style.display = 'block';
                tbUpdateStatusUI(data, true);

                if (active) {
                    tbStartPolling();
                }
            })
            .catch(function () { });
    }

    // ---- Stop ----
    function tbStop() {
        fetch('/api/terabox/stop', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function () {
                tbStopPolling();
                tbStatusText.textContent = '⏹ Đã dừng bởi người dùng.';
                tbStartBtn.disabled = false;
                tbStartBtn.textContent = '🚀 Bắt đầu tải';
            })
            .catch(function (e) { alert('Lỗi: ' + e); });
    }

    function tbReset(deleteFiles) {
        var confirmMsg = deleteFiles
            ? 'Xóa toàn bộ file tạm Terabox (.part) và trạng thái hiện tại? Sau đó sẽ tải lại từ đầu.'
            : 'Xóa trạng thái/log Terabox đang hiển thị? File .part để resume sẽ được giữ lại.';
        if (!confirm(confirmMsg)) return;

        fetch('/api/terabox/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: !!deleteFiles })
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    if (!r.ok) throw new Error(data.error || 'Reset thất bại');
                    return data;
                });
            })
            .then(function () {
                tbStopPolling();
                tbStatusSection.style.display = 'none';
                tbStatusText.textContent = 'Đang xử lý...';
                tbPhaseText.textContent = '';
                tbProgressBar.style.width = '0%';
                tbProgressPercent.textContent = '0%';
                tbProgressDetail.textContent = '';
                tbConsole.textContent = 'Đang chờ...';
                tbLastLogCount = 0;
                tbRenderedLogKey = '';
                tbStartBtn.disabled = false;
                tbStartBtn.textContent = '🚀 Bắt đầu tải';
                tbStopBtn.style.display = 'none';
                alert(deleteFiles ? 'Đã xóa trạng thái và file tạm.' : 'Đã xóa trạng thái.');
            })
            .catch(function (e) {
                alert('Lỗi: ' + e.message);
            });
    }

    function tbQueue() {
        var url = tbUrlInput.value.trim();
        var dest = tbDestInput.value.trim();

        if (!url) { alert('Vui lòng nhập link Terabox!'); return; }
        var lines = url.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
        if (lines.length === 0) { alert('Vui lòng nhập link Terabox!'); return; }
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (!/terabox|1024tera|nephobox|4funbox|mirrobox|momerybox|tibibox|tibabox|freeterabox|terasharelink|teraboxlink|teraboxshare|dubox|momotera|miyauplat|funletu|ytbterabox/i.test(line)) {
                alert('Dòng ' + (i + 1) + ' không phải link Terabox hợp lệ!');
                return;
            }
        }
        if (!dest) { alert('Vui lòng nhập đường dẫn đích Google Drive!'); return; }

        if (dest.indexOf('drive.google.com') > -1) {
            var converted = convertSingleUrl(dest);
            if (converted) dest = converted;
        }

        var queueBtn = document.getElementById('teraboxQueueBtn');
        if (queueBtn) {
            queueBtn.disabled = true;
            queueBtn.textContent = '⏳ Đang thêm...';
        }

        fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, output_dir: dest })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.message) {
                    alert(data.message);
                    tbUrlInput.value = '';
                } else {
                    alert('Lỗi: ' + (data.error || 'Không thể thêm vào hàng đợi'));
                }
            })
            .catch(function (e) {
                alert('Lỗi kết nối: ' + e);
            })
            .finally(function () {
                if (queueBtn) {
                    queueBtn.disabled = false;
                    queueBtn.textContent = '⏳ Thêm hàng đợi';
                }
            });
    }

    // ---- Event Listeners ----
    tbSaveCookieBtn.addEventListener('click', tbSaveCookie);
    tbCheckBtn.addEventListener('click', tbCheckInfo);
    tbStartBtn.addEventListener('click', tbStart);
    tbStopBtn.addEventListener('click', tbStop);
    var tbQueueBtn = document.getElementById('teraboxQueueBtn');
    if (tbQueueBtn) tbQueueBtn.addEventListener('click', tbQueue);
    if (tbResetBtn) tbResetBtn.addEventListener('click', function () { tbReset(false); });
    if (tbClearTempBtn) tbClearTempBtn.addEventListener('click', function () { tbReset(true); });

    // Load cookie status on page load
    tbLoadCookie();
    tbRestoreStatus();
})();

// ==================== CLOUD UNPACK MODULE ====================
(function () {
    const githubRepo = document.getElementById('githubRepo');
    const githubPat = document.getElementById('githubPat');
    const saveGithubConfigBtn = document.getElementById('saveGithubConfigBtn');
    const githubConfigStatus = document.getElementById('githubConfigStatus');

    const unpackSource = document.getElementById('unpack_source');
    const unpackMode = document.getElementById('unpack_mode');
    const unpackPassword = document.getElementById('unpack_password');
    const btnUnpackStart = document.getElementById('btnUnpackStart');
    const btnUnpackReset = document.getElementById('btnUnpackReset');
    const unpackStatusSection = document.getElementById('unpackStatusSection');
    const unpackStatusText = document.getElementById('unpackStatusText');
    const unpackSourceText = document.getElementById('unpackSourceText');
    const unpackGithubLink = document.getElementById('unpackGithubLink');
    const unpackTimeline = document.getElementById('unpackTimeline');
    const githubWarning = document.getElementById('githubWarning');
    const linkToConfig = document.getElementById('linkToConfig');

    let unpackPollTimer = null;
    let isConfigComplete = false;

    // Load GitHub Config
    window.loadGithubConfig = async function () {
        try {
            const r = await fetch('/api/github/config');
            const data = await r.json();
            if (githubRepo) githubRepo.value = data.github_repo || '';
            if (githubPat) githubPat.value = ''; // Don't show PAT
            if (githubPat && data.has_pat) {
                githubPat.placeholder = 'Đã lưu: ' + data.pat_masked;
            }
            
            isConfigComplete = data.complete;
            if (githubWarning) {
                githubWarning.style.display = data.complete ? 'none' : 'block';
            }
        } catch (e) {
            console.error('Lỗi tải config GitHub:', e);
        }
    };

    // Save GitHub Config
    if (saveGithubConfigBtn) {
        saveGithubConfigBtn.addEventListener('click', async () => {
            const repo = githubRepo.value.trim();
            const pat = githubPat.value.trim();

            if (!repo) {
                showConfigStatus('Vui lòng điền Repository', 'danger');
                return;
            }

            saveGithubConfigBtn.disabled = true;
            try {
                const r = await fetch('/api/github/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        github_repo: repo,
                        github_pat: pat || '__KEEP__'
                    })
                });
                const data = await r.json();
                if (data.success) {
                    showConfigStatus('Cấu hình GitHub lưu thành công!', 'success');
                    loadGithubConfig();
                } else {
                    showConfigStatus('Lỗi: ' + data.error, 'danger');
                }
            } catch (e) {
                showConfigStatus('Lỗi kết nối: ' + e, 'danger');
            } finally {
                saveGithubConfigBtn.disabled = false;
            }
        });
    }

    function showConfigStatus(msg, type) {
        if (!githubConfigStatus) return;
        githubConfigStatus.textContent = msg;
        githubConfigStatus.className = 'config-status ' + type;
        setTimeout(() => { githubConfigStatus.className = 'config-status'; }, 4000);
    }

    // Link warning to Config tab
    if (linkToConfig) {
        linkToConfig.addEventListener('click', (e) => {
            e.preventDefault();
            // Unlock/show config tab if hidden
            const tabBtnConfig = document.getElementById('tabBtnConfig');
            if (tabBtnConfig) {
                tabBtnConfig.style.display = 'inline-flex';
                tabBtnConfig.click();
            }
        });
    }

    // Start Unpack
    if (btnUnpackStart) {
        btnUnpackStart.addEventListener('click', async () => {
            if (!isConfigComplete) {
                alert('Vui lòng cấu hình GitHub Actions trong tab Cấu hình trước khi chạy!');
                return;
            }

            let source = unpackSource.value.trim();
            if (!source) {
                alert('Vui lòng nhập đường dẫn nguồn Google Drive!');
                return;
            }

            // Convert to Rclone syntax if dynamic link is pasted
            if (source.indexOf('drive.google.com') > -1) {
                const converted = convertSingleUrl(source);
                if (converted) {
                    source = converted;
                    unpackSource.value = source;
                }
            }

            const mode = unpackMode.value;
            const password = unpackPassword.value.trim();

            btnUnpackStart.disabled = true;
            btnUnpackStart.querySelector('.btn-text').textContent = 'Đang khởi chạy...';

            try {
                const r = await fetch('/api/cloud-unpack/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        remote_path: source,
                        mode: mode,
                        password: password
                    })
                });
                const data = await r.json();
                if (data.success) {
                    alert(data.message);
                    unpackPassword.value = '';
                    checkUnpackStatus();
                } else {
                    alert('Lỗi: ' + data.error);
                }
            } catch (e) {
                alert('Lỗi kết nối: ' + e);
            } finally {
                btnUnpackStart.disabled = false;
                btnUnpackStart.querySelector('.btn-text').textContent = '🚀 Bắt đầu Giải Nén Cloud';
            }
        });
    }

    // Reset tracking
    if (btnUnpackReset) {
        btnUnpackReset.addEventListener('click', async () => {
            if (confirm('Bạn muốn ngừng theo dõi tiến trình này? (Không ảnh hưởng đến tiến trình đang chạy trên GitHub)')) {
                try {
                    await fetch('/api/cloud-unpack/reset', { method: 'POST' });
                    checkUnpackStatus();
                } catch (e) {
                    console.error(e);
                }
            }
        });
    }

    // Check unpack status & steps
    window.checkUnpackStatus = async function () {
        if (unpackPollTimer) clearTimeout(unpackPollTimer);

        try {
            const r = await fetch('/api/cloud-unpack/status');
            const data = await r.json();

            if (!data.status || data.status === 'idle') {
                if (unpackStatusSection) unpackStatusSection.style.display = 'none';
                if (btnUnpackReset) btnUnpackReset.style.display = 'none';
                return;
            }

            // Show status section
            if (unpackStatusSection) unpackStatusSection.style.display = 'block';
            if (btnUnpackReset) btnUnpackReset.style.display = 'inline-block';
            if (unpackSourceText) unpackSourceText.textContent = data.remote_path || '...';

            // GitHub link
            if (unpackGithubLink && data.html_url) {
                unpackGithubLink.href = data.html_url;
                unpackGithubLink.style.display = 'flex';
            } else if (unpackGithubLink) {
                unpackGithubLink.style.display = 'none';
            }

            // Status label & animation classes
            let statusLabel = 'Đang chạy...';
            if (data.status === 'queued') statusLabel = '⏳ Đang chờ máy ảo (Queued)...';
            else if (data.status === 'initializing') statusLabel = '⚡ Đang khởi động...';
            else if (data.status === 'in_progress') statusLabel = '🌀 Đang thực hiện (In Progress)...';
            else if (data.status === 'completed') {
                if (data.conclusion === 'success') statusLabel = '✅ Hoàn thành thành công (Success)!';
                else statusLabel = '❌ Thất bại (Failed hoặc Cancelled)!';
            }

            if (unpackStatusText) unpackStatusText.textContent = statusLabel;

            // Generate timeline steps
            if (unpackTimeline) {
                if (data.steps && data.steps.length > 0) {
                    unpackTimeline.innerHTML = '';
                    data.steps.forEach(step => {
                        const stepDiv = document.createElement('div');
                        stepDiv.className = 'timeline-step ' + (step.status || 'queued');
                        if (step.status === 'completed' && step.conclusion === 'failure') {
                            stepDiv.className = 'timeline-step failed';
                        }
                        
                        const titleSpan = document.createElement('div');
                        titleSpan.style.fontWeight = '500';
                        titleSpan.textContent = step.name;
                        stepDiv.appendChild(titleSpan);

                        const descDiv = document.createElement('div');
                        descDiv.className = 'step-details';
                        let desc = 'Đang chờ...';
                        if (step.status === 'in_progress') desc = '⚡ Đang xử lý...';
                        else if (step.status === 'completed') {
                            desc = step.conclusion === 'success' ? '✅ Đã hoàn thành' : '❌ Lỗi xảy ra';
                        }
                        descDiv.textContent = desc;
                        stepDiv.appendChild(descDiv);

                        unpackTimeline.appendChild(stepDiv);
                    });
                } else {
                    unpackTimeline.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem;">⏳ Đang khởi tạo các bước chạy...</div>';
                }
            }

            // Auto poll if still active
            if (data.status !== 'completed') {
                unpackPollTimer = setTimeout(checkUnpackStatus, 4000);
            }
        } catch (e) {
            console.error('Lỗi check unpack status:', e);
            unpackPollTimer = setTimeout(checkUnpackStatus, 6000);
        }
    };

    // Auto-check on page load
    setTimeout(() => {
        checkUnpackStatus();
    }, 1000);
})();
