// ==================== GLOBAL STATE ====================
const state = {
    currentTab: 'studio',
    projects: [],
    activeProjectId: null,
    studioFilter: 'all',
    studioSearch: '',
    tasks: [],
    selectedTaskIds: new Set(),

    // New Task Form State
    newTaskType: 'video',      // 'video' | 'image' | 'img2vid'
    newAspectRatio: '16:9',    // '16:9' | '9:16' | '1:1' | '4:3' | '3:4'
    newRefMode: 'pair',        // 'pair' | 'shared' | 'by_name'
    refImages: [],             // [{path, name, stem}]

    // Gallery State
    galleryTypeFilter: 'all',
    galleryItems: [],
    activePlayerItem: null,

    // Accounts & Proxies
    accounts: [],
    proxies: [],
    addAccountMode: 'single',
    settings: {}
};

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', async () => {
    await refreshStudioState();
    await loadSettingsIntoForm();

    // Polling mỗi 1.5s để cập nhật thanh progress bar %, đồng hồ đếm giây và badge trạng thái
    setInterval(async () => {
        await refreshStudioState(true);
        if (state.currentTab === 'accounts') {
            await loadAccounts(true);
        }
    }, 1500);
});

// ==================== TOAST NOTIFICATION ====================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    const colorMap = {
        info: 'border-indigo-500/50 bg-museCard text-indigo-200',
        success: 'border-emerald-500/50 bg-museCard text-emerald-200',
        error: 'border-rose-500/50 bg-museCard text-rose-200',
        warning: 'border-amber-500/50 bg-museCard text-amber-200'
    };
    const iconMap = {
        info: 'fa-circle-info text-indigo-400',
        success: 'fa-circle-check text-emerald-400',
        error: 'fa-triangle-exclamation text-rose-400',
        warning: 'fa-circle-exclamation text-amber-400'
    };

    el.className = `px-4 py-3 rounded-xl border shadow-xl flex items-center gap-2.5 text-xs font-medium transition-all duration-300 ${colorMap[type] || colorMap.info}`;
    el.innerHTML = `<i class="fa-solid ${iconMap[type] || iconMap.info} text-sm"></i><span>${escapeHtml(message)}</span>`;
    container.appendChild(el);

    setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 300);
    }, 3500);
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatSeconds(sec) {
    const s = Math.max(0, parseInt(sec || 0, 10));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    if (m > 0) {
        return `${m}p${rem < 10 ? '0' : ''}${rem}s`;
    }
    return `${rem}s`;
}

// ==================== TAB NAVIGATION ====================
async function switchTab(tabName) {
    state.currentTab = tabName;
    const tabs = ['studio', 'gallery', 'accounts', 'proxies', 'settings'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-btn-${t}`);
        const view = document.getElementById(`tab-view-${t}`);
        if (t === tabName) {
            btn.classList.add('active');
            view.classList.remove('hidden');
        } else {
            btn.classList.remove('active');
            view.classList.add('hidden');
        }
    });

    if (tabName === 'studio') {
        await refreshStudioState();
    } else if (tabName === 'gallery') {
        await loadGallery();
    } else if (tabName === 'accounts') {
        await loadAccounts();
    } else if (tabName === 'proxies') {
        await loadProxies();
    } else if (tabName === 'settings') {
        await loadSettingsIntoForm();
    }
}

// ==================== TAB 1: STUDIO ====================
async function refreshStudioState(isBackground = false) {
    try {
        const params = new URLSearchParams({
            status_filter: state.studioFilter,
            search: state.studioSearch || ''
        });
        if (state.activeProjectId) {
            params.set('project_id', state.activeProjectId);
        }

        const res = await fetch(`/api/state?${params.toString()}`);
        const data = await res.json();

        state.projects = data.projects || [];
        state.activeProjectId = data.active_project_id;
        state.tasks = data.tasks || [];
        state.settings = data.settings || {};

        // Cập nhật 2 Badge góc phải Header
        document.getElementById('badge-global-running').textContent = data.global_counts?.running ?? 0;
        document.getElementById('badge-global-completed').textContent = data.global_counts?.completed ?? 0;

        // Cập nhật số lượng trên bộ lọc Studio
        const pc = data.project_counts || {};
        document.getElementById('count-filter-all').textContent = pc.all ?? 0;
        document.getElementById('count-filter-pending').textContent = pc.pending ?? 0;
        document.getElementById('count-filter-running').textContent = pc.running ?? 0;
        document.getElementById('count-filter-completed').textContent = pc.completed ?? 0;
        document.getElementById('count-filter-failed').textContent = pc.failed ?? 0;

        renderProjectSelectors();
        renderStudioTasksTable();
    } catch (err) {
        if (!isBackground) {
            console.error(err);
        }
    }
}

function renderProjectSelectors() {
    const studioSelect = document.getElementById('studio-project-select');
    const galSelect = document.getElementById('gallery-project-filter');

    const currentGalVal = galSelect ? galSelect.value : '0';

    if (studioSelect) {
        studioSelect.innerHTML = state.projects
            .map(p => `<option value="${p.id}" ${p.id === state.activeProjectId ? 'selected' : ''}>${escapeHtml(p.name)}</option>`)
            .join('');
    }

    if (galSelect) {
        galSelect.innerHTML = `<option value="0">Tất cả dự án</option>` +
            state.projects.map(p => `<option value="${p.id}" ${String(p.id) === String(currentGalVal) ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('');
    }
}

function onProjectChange() {
    const sel = document.getElementById('studio-project-select');
    state.activeProjectId = parseInt(sel.value, 10);
    state.selectedTaskIds.clear();
    refreshStudioState();
}

async function createNewProjectPrompt() {
    const name = prompt('Nhập tên dự án mới:');
    if (!name || !name.trim()) return;
    const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() })
    });
    const data = await res.json();
    if (!res.ok) {
        showToast(data.detail || 'Không thể tạo dự án', 'error');
        return;
    }
    state.activeProjectId = data.project.id;
    showToast(`Đã tạo dự án "${data.project.name}"`, 'success');
    await refreshStudioState();
}

async function renameCurrentProjectPrompt() {
    const currentProj = state.projects.find(p => p.id === state.activeProjectId);
    if (!currentProj) return;
    const newName = prompt('Đổi tên dự án:', currentProj.name);
    if (!newName || !newName.trim() || newName.trim() === currentProj.name) return;

    const res = await fetch(`/api/projects/${state.activeProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() })
    });
    if (!res.ok) {
        const err = await res.json();
        showToast(err.detail || 'Đổi tên thất bại', 'error');
        return;
    }
    showToast('Đã cập nhật tên dự án', 'success');
    await refreshStudioState();
}

async function deleteCurrentProjectPrompt() {
    const currentProj = state.projects.find(p => p.id === state.activeProjectId);
    if (!currentProj) return;
    if (!confirm(`Bạn có chắc chắn muốn xóa dự án "${currentProj.name}" và toàn bộ tác vụ bên trong?`)) return;

    const res = await fetch(`/api/projects/${state.activeProjectId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.ok) {
        state.activeProjectId = data.next_project_id;
        state.selectedTaskIds.clear();
        showToast('Đã xóa dự án', 'info');
        await refreshStudioState();
    }
}

function setStudioFilter(filterVal) {
    state.studioFilter = filterVal;
    ['all', 'pending', 'running', 'completed', 'failed'].forEach(f => {
        const btn = document.getElementById(`filter-btn-${f}`);
        if (f === filterVal) {
            btn.className = 'px-2.5 py-1 rounded-md bg-museAccent text-white transition';
        } else {
            btn.className = 'px-2.5 py-1 rounded-md text-gray-400 hover:text-white transition';
        }
    });
    refreshStudioState();
}

function onStudioSearchInput() {
    state.studioSearch = document.getElementById('studio-search-input').value;
    refreshStudioState();
}

function renderStudioTasksTable() {
    const tbody = document.getElementById('studio-tasks-tbody');
    if (!tbody) return;

    // Dọn các ID đã chọn nhưng không còn tồn tại
    const currentIds = new Set(state.tasks.map(t => t.id));
    for (const id of Array.from(state.selectedTaskIds)) {
        if (!currentIds.has(id)) state.selectedTaskIds.delete(id);
    }
    document.getElementById('selected-tasks-counter').textContent = `Đã chọn: ${state.selectedTaskIds.size}`;

    if (state.tasks.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="py-16 text-center text-gray-500">
                    <i class="fa-solid fa-wand-magic-sparkles text-2xl text-indigo-400/40 mb-2 block"></i>
                    Chưa có tác vụ nào trong danh sách. Hãy nhập Prompt ở cột bên phải để bắt đầu!
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = state.tasks.map(t => {
        const isSelected = state.selectedTaskIds.has(t.id);
        const typeBadge = getTaskTypeBadge(t.task_type, t.aspect_ratio, t.ref_images);
        const statusCell = getTaskStatusCell(t);
        const accLabel = t.account_name || t.account_email || '<span class="text-gray-500">Chưa gán</span>';
        const hasOutput = t.status === 'completed' && t.output_file_path;

        const refCount = (t.ref_images || []).length;
        const refTag = refCount > 0
            ? `<span class="ml-1.5 px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 text-[10px]" title="Đính kèm ${refCount} ảnh tham chiếu (${t.ref_mode})"><i class="fa-solid fa-paperclip mr-0.5"></i>${refCount} ảnh</span>`
            : '';

        return `
            <tr class="studio-row transition ${isSelected ? 'selected' : ''}">
                <td class="py-2.5 px-3 text-center">
                    <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleSelectTask(${t.id}, this.checked)" class="rounded border-gray-600 bg-museInput text-indigo-600 focus:ring-0 cursor-pointer" />
                </td>
                <td class="py-2.5 px-2 text-center font-mono font-bold text-gray-400">${t.stt}</td>
                <td class="py-2.5 px-3 max-w-xs">
                    <div class="flex items-center">
                        <span class="font-bold text-white">${escapeHtml(t.task_name)}</span>
                        ${refTag}
                    </div>
                    <p class="text-gray-400 truncate mt-0.5" title="${escapeHtml(t.prompt_text)}">${escapeHtml(t.prompt_text)}</p>
                </td>
                <td class="py-2.5 px-2 text-center">${typeBadge}</td>
                <td class="py-2.5 px-2 text-gray-300 truncate max-w-[120px]">${accLabel}</td>
                <td class="py-2.5 px-3">${statusCell}</td>
                <td class="py-2.5 px-3 text-right">
                    <div class="flex items-center justify-end gap-1">
                        <button onclick="openTaskMedia(${t.id})" ${hasOutput ? '' : 'disabled'} title="Phát Media (Play)" class="w-7 h-7 rounded-lg ${hasOutput ? 'bg-indigo-500/20 hover:bg-indigo-500/40 text-indigo-300' : 'bg-gray-800/50 text-gray-600 cursor-not-allowed'} flex items-center justify-center transition">
                            <i class="fa-solid fa-play text-[11px]"></i>
                        </button>
                        <button onclick="openTaskFolder(${t.id})" title="Mở thư mục chứa file" class="w-7 h-7 rounded-lg bg-museCard hover:bg-gray-700 text-amber-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-folder-open text-[11px]"></i>
                        </button>
                        <button onclick="retrySingleTask(${t.id})" title="Chạy lại tác vụ này (Retry)" class="w-7 h-7 rounded-lg bg-museCard hover:bg-emerald-500/25 text-emerald-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-rotate-right text-[11px]"></i>
                        </button>
                        <button onclick="deleteSingleTask(${t.id})" title="Xóa tác vụ" class="w-7 h-7 rounded-lg bg-museCard hover:bg-rose-500/25 text-rose-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-trash text-[11px]"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function getTaskTypeBadge(taskType, ratio, refImages) {
    const t = (taskType || 'video').toLowerCase();
    let label = 'Video';
    let cls = 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30';
    if (t === 'image') {
        label = 'Ảnh';
        cls = 'bg-sky-500/15 text-sky-300 border-sky-500/30';
    } else if (t === 'img2vid' || (refImages && refImages.length > 0)) {
        label = 'Ảnh→Vid';
        cls = 'bg-violet-500/15 text-violet-300 border-violet-500/30';
    }
    return `
        <div class="inline-flex flex-col items-center">
            <span class="px-2 py-0.5 rounded-md border text-[10px] font-semibold ${cls}">${label}</span>
            <span class="text-[10px] text-gray-500 mt-0.5">${escapeHtml(ratio || '16:9')}</span>
        </div>
    `;
}

function getTaskStatusCell(t) {
    const pct = Math.min(100, Math.max(0, parseInt(t.progress_percent || 0, 10)));
    if (t.status === 'running') {
        const timerStr = formatSeconds(t.elapsed_seconds || 0);
        return `
            <div class="space-y-1">
                <div class="flex items-center justify-between text-[11px]">
                    <span class="text-indigo-300 font-semibold truncate max-w-[130px]">${escapeHtml(t.status_message || 'Đang chạy...')}</span>
                    <span class="font-mono text-indigo-200">${pct}% · ${timerStr}</span>
                </div>
                <div class="w-full h-1.5 bg-museInput rounded-full overflow-hidden border border-museBorder">
                    <div class="h-full bg-gradient-to-r from-indigo-500 to-violet-500 progress-running transition-all duration-300" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    } else if (t.status === 'completed') {
        const sizeLabel = t.file_size_mb ? `${t.file_size_mb} MB` : '100%';
        return `
            <div class="space-y-1">
                <div class="flex items-center justify-between text-[11px]">
                    <span class="text-emerald-400 font-semibold"><i class="fa-solid fa-check mr-1"></i>Hoàn thành</span>
                    <span class="font-mono text-gray-400">${sizeLabel}</span>
                </div>
                <div class="w-full h-1.5 bg-museInput rounded-full overflow-hidden">
                    <div class="h-full bg-emerald-500" style="width: 100%"></div>
                </div>
            </div>
        `;
    } else if (t.status === 'failed') {
        return `
            <div class="text-[11px] text-rose-400 font-medium leading-snug" title="${escapeHtml(t.status_message)}">
                <i class="fa-solid fa-circle-xmark mr-1"></i>${escapeHtml(t.status_message || 'Lỗi')}
            </div>
        `;
    } else {
        return `
            <div class="text-[11px] text-gray-400 flex items-center gap-1.5">
                <i class="fa-regular fa-clock text-gray-500"></i>
                <span class="truncate">${escapeHtml(t.status_message || 'Chờ chạy')}</span>
            </div>
        `;
    }
}

// ==================== SELECTION & BATCH ACTIONS ====================
function toggleSelectTask(taskId, checked) {
    if (checked) {
        state.selectedTaskIds.add(taskId);
    } else {
        state.selectedTaskIds.delete(taskId);
    }
    renderStudioTasksTable();
}

function toggleSelectAllTasks(forceState) {
    const allSelected = state.tasks.length > 0 && state.tasks.every(t => state.selectedTaskIds.has(t.id));
    const target = typeof forceState === 'boolean' ? forceState : !allSelected;
    if (target) {
        state.tasks.forEach(t => state.selectedTaskIds.add(t.id));
    } else {
        state.selectedTaskIds.clear();
    }
    const hdr = document.getElementById('header-checkbox-all');
    if (hdr) hdr.checked = target;
    renderStudioTasksTable();
}

function openQuickSelectModal() {
    document.getElementById('modal-quick-select').classList.remove('hidden');
}

function closeQuickSelectModal() {
    document.getElementById('modal-quick-select').classList.add('hidden');
}

function quickSelectByStatus(status) {
    state.selectedTaskIds.clear();
    if (status !== 'none') {
        state.tasks.filter(t => t.status === status).forEach(t => state.selectedTaskIds.add(t.id));
    }
    closeQuickSelectModal();
    renderStudioTasksTable();
}

function quickSelectByRange() {
    const fromStt = parseInt(document.getElementById('qs-from-stt').value || '1', 10);
    const toStt = parseInt(document.getElementById('qs-to-stt').value || '10', 10);
    state.selectedTaskIds.clear();
    state.tasks.forEach(t => {
        if (t.stt >= fromStt && t.stt <= toStt) {
            state.selectedTaskIds.add(t.id);
        }
    });
    closeQuickSelectModal();
    renderStudioTasksTable();
}

async function reindexProjectTasks() {
    if (!state.activeProjectId) return;
    await fetch('/api/tasks/reindex', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: state.activeProjectId })
    });
    showToast('Đã đánh lại số thứ tự (STT)', 'success');
    await refreshStudioState();
}

async function startSelectedOrAllTasks() {
    const ids = Array.from(state.selectedTaskIds);
    const payload = ids.length > 0
        ? { task_ids: ids }
        : { project_id: state.activeProjectId };
    await fetch('/api/tasks/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    showToast(ids.length > 0 ? `Bắt đầu chạy ${ids.length} tác vụ đã chọn` : 'Bắt đầu chạy hàng đợi dự án', 'success');
    await refreshStudioState();
}

async function retryFailedTasks() {
    const ids = Array.from(state.selectedTaskIds);
    const payload = ids.length > 0
        ? { task_ids: ids }
        : { project_id: state.activeProjectId };
    await fetch('/api/tasks/retry-failed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    showToast('Đã kích hoạt chạy lại các tác vụ lỗi', 'info');
    await refreshStudioState();
}

async function stopSelectedOrAllTasks() {
    const ids = Array.from(state.selectedTaskIds);
    const payload = ids.length > 0
        ? { task_ids: ids }
        : { project_id: state.activeProjectId };
    await fetch('/api/tasks/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    showToast('Đã gửi lệnh dừng tác vụ', 'warning');
    await refreshStudioState();
}

async function deleteSelectedTasks() {
    const ids = Array.from(state.selectedTaskIds);
    if (ids.length === 0) {
        showToast('Hãy tích chọn ít nhất 1 tác vụ để xóa', 'warning');
        return;
    }
    if (!confirm(`Xóa ${ids.length} tác vụ đã chọn?`)) return;
    await fetch('/api/tasks/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_ids: ids })
    });
    state.selectedTaskIds.clear();
    showToast(`Đã xóa ${ids.length} tác vụ`, 'info');
    await refreshStudioState();
}

async function retrySingleTask(taskId) {
    await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST' });
    showToast(`Đã đưa tác vụ #${taskId} vào hàng đợi chạy`, 'info');
    await refreshStudioState();
}

async function deleteSingleTask(taskId) {
    await fetch('/api/tasks/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_ids: [taskId] })
    });
    state.selectedTaskIds.delete(taskId);
    await refreshStudioState();
}

function openTaskMedia(taskId) {
    const t = state.tasks.find(x => x.id === taskId);
    if (!t || !t.output_file_path) return;
    openMediaPlayerModal(t);
}

async function openTaskFolder(taskId) {
    const t = state.tasks.find(x => x.id === taskId);
    const targetPath = (t && t.output_file_path) ? t.output_file_path : (state.settings.output_dir || 'output');
    try {
        const res = await fetch('/api/system/open-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetPath })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast('Đã mở thư mục chứa file trên Windows Explorer', 'info');
        } else {
            showToast(data.detail || 'Không thể mở thư mục', 'error');
        }
    } catch (err) {
        showToast('Lỗi khi gọi mở thư mục', 'error');
    }
}

// ==================== RIGHT COLUMN: NEW TASK CREATOR ====================
function setTaskType(type) {
    state.newTaskType = type;
    ['video', 'image', 'img2vid'].forEach(t => {
        const btn = document.getElementById(`type-btn-${t}`);
        if (t === type) {
            btn.className = 'py-2 rounded-lg text-xs font-semibold bg-museAccent text-white shadow transition flex items-center justify-center gap-1.5';
        } else {
            btn.className = 'py-2 rounded-lg text-xs font-semibold text-gray-400 hover:text-white transition flex items-center justify-center gap-1.5';
        }
    });
}

function setAspectRatio(ratio) {
    state.newAspectRatio = ratio;
    ['16:9', '9:16', '1:1', '4:3', '3:4'].forEach(r => {
        const btn = document.getElementById(`ratio-btn-${r}`);
        if (r === ratio) {
            btn.className = 'py-2 rounded-lg text-xs font-semibold bg-museAccent text-white border border-indigo-400/50 transition';
        } else {
            btn.className = 'py-2 rounded-lg text-xs font-semibold bg-museInput text-gray-400 hover:text-white border border-museBorder transition';
        }
    });
}

function setRefMode(mode) {
    state.newRefMode = mode;
    ['pair', 'shared', 'by_name'].forEach(m => {
        const btn = document.getElementById(`refmode-btn-${m}`);
        if (m === mode) {
            btn.className = 'py-1.5 rounded-md bg-museAccent text-white transition';
        } else {
            btn.className = 'py-1.5 rounded-md text-gray-400 hover:text-white transition';
        }
    });

    const helper = document.getElementById('ref-mode-helper-text');
    if (mode === 'pair') {
        helper.innerHTML = 'Prompt dòng thứ <i>i</i> tự động đính kèm file ảnh thứ <i>i</i> trong danh sách.';
    } else if (mode === 'shared') {
        helper.innerHTML = 'Toàn bộ các prompt đều đính kèm chung file ảnh đã chọn.';
    } else {
        helper.innerHTML = 'Quét tên file ảnh (không tính đuôi mở rộng). Nếu trong câu prompt xuất hiện tên file nào (VD: <code>anh_so_1</code>), tự động đính kèm tất cả file ảnh khớp.';
    }
}

function getPromptLinesFromTextarea() {
    const raw = document.getElementById('studio-prompt-textarea').value || '';
    return raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
}

function onPromptTextareaInput() {
    const lines = getPromptLinesFromTextarea();
    const count = lines.length;
    document.getElementById('prompt-line-counter-badge').textContent = `${count} Prompt`;
    document.getElementById('btn-create-and-run-label').textContent = `Tạo & chạy (${count})`;
}

function clearPromptTextarea() {
    document.getElementById('studio-prompt-textarea').value = '';
    onPromptTextareaInput();
}

function selectRefImagesDialog() {
    const input = document.getElementById('browser-ref-images-input');
    if (input) {
        input.value = '';
        input.click();
    }
}

function selectRefFolderDialog() {
    const input = document.getElementById('browser-ref-folder-input');
    if (input) {
        input.value = '';
        input.click();
    }
}

function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

async function onBrowserRefImagesSelected(event, isFolder = false) {
    const rawFiles = Array.from((event.target && event.target.files) || []);
    if (rawFiles.length === 0) return;

    const validExts = ['.png', '.jpg', '.jpeg', '.webp'];
    const imgFiles = rawFiles
        .filter(f => {
            const lower = (f.name || '').toLowerCase();
            return validExts.some(ext => lower.endsWith(ext));
        })
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));

    if (imgFiles.length === 0) {
        showToast('Không tìm thấy file ảnh hợp lệ (.png, .jpg, .jpeg, .webp)', 'warning');
        return;
    }

    showToast(`Đang nạp ${imgFiles.length} ảnh tham chiếu...`, 'info');
    try {
        const payloadFiles = [];
        for (const f of imgFiles) {
            const b64 = await readFileAsBase64(f);
            payloadFiles.push({ name: f.name, data_b64: b64 });
        }

        const res = await fetch('/api/dialog/upload-ref-images', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ files: payloadFiles, replace: isFolder })
        });
        const data = await res.json();
        if (data.ok && data.images && data.images.length > 0) {
            if (isFolder) {
                state.refImages = data.images;
            } else {
                const existingPaths = new Set(state.refImages.map(x => x.path));
                data.images.forEach(img => {
                    if (!existingPaths.has(img.path)) {
                        state.refImages.push(img);
                    }
                });
            }
            renderRefImagesChips();
            showToast(`Đã nạp thành công ${data.images.length} ảnh tham chiếu!`, 'success');
        }
    } catch (err) {
        showToast(`Lỗi khi nạp ảnh tham chiếu: ${err.message}`, 'error');
    }
}

function clearRefImages() {
    state.refImages = [];
    renderRefImagesChips();
}

function removeSingleRefImage(index) {
    state.refImages.splice(index, 1);
    renderRefImagesChips();
}

function renderRefImagesChips() {
    const countEl = document.getElementById('ref-images-count-label');
    const chipsEl = document.getElementById('ref-images-chips');

    if (state.refImages.length === 0) {
        countEl.textContent = 'Chưa chọn ảnh tham chiếu';
        chipsEl.innerHTML = '';
        return;
    }

    countEl.textContent = `Đã chọn: ${state.refImages.length} ảnh`;
    chipsEl.innerHTML = state.refImages.map((img, idx) => `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-museInput border border-museBorder text-[11px] text-gray-200">
            <i class="fa-regular fa-image text-indigo-400"></i>
            <span class="truncate max-w-[120px]" title="${escapeHtml(img.path)}">${escapeHtml(img.name)}</span>
            <button onclick="removeSingleRefImage(${idx})" class="text-gray-500 hover:text-rose-400 ml-0.5">&times;</button>
        </span>
    `).join('');
}

async function openMatcherPreviewModal() {
    const prompts = getPromptLinesFromTextarea();
    if (prompts.length === 0) {
        showToast('Hãy nhập ít nhất 1 dòng Prompt để xem trước kết quả ghép ảnh', 'warning');
        return;
    }
    const res = await fetch('/api/matcher/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompts,
            image_paths: state.refImages.map(x => x.path),
            ref_mode: state.newRefMode
        })
    });
    const data = await res.json();
    const body = document.getElementById('matcher-preview-body');
    body.innerHTML = (data.preview || []).map(item => {
        const imgsHtml = item.matched_images.length > 0
            ? item.matched_images.map(m => `<span class="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono text-[11px]">${escapeHtml(m.name)}</span>`).join(' ')
            : `<span class="text-gray-500 italic">Không đính kèm ảnh</span>`;
        return `
            <div class="p-3 rounded-xl bg-museCard border border-museBorder space-y-1.5">
                <div class="font-semibold text-white">Prompt #${item.index}: <span class="font-normal text-gray-300">${escapeHtml(item.prompt)}</span></div>
                <div class="flex flex-wrap items-center gap-1.5">
                    <span class="text-gray-400 text-[11px]">Ảnh khớp:</span>
                    ${imgsHtml}
                </div>
            </div>
        `;
    }).join('');
    document.getElementById('modal-matcher-preview').classList.remove('hidden');
}

function closeMatcherPreviewModal() {
    document.getElementById('modal-matcher-preview').classList.add('hidden');
}

async function submitCreateTasks(autoStart) {
    const prompts = getPromptLinesFromTextarea();
    if (prompts.length === 0) {
        showToast('Vui lòng nhập ít nhất 1 dòng Prompt!', 'warning');
        return;
    }

    const res = await fetch('/api/tasks/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: state.activeProjectId,
            prompts,
            task_type: state.newTaskType,
            aspect_ratio: state.newAspectRatio,
            ref_mode: state.newRefMode,
            image_paths: state.refImages.map(x => x.path),
            auto_start: autoStart
        })
    });
    const data = await res.json();
    if (!res.ok) {
        showToast(data.detail || 'Lỗi khi tạo tác vụ', 'error');
        return;
    }

    clearPromptTextarea();
    showToast(
        autoStart
            ? `Đã tạo và bắt đầu chạy ${data.created_count} tác vụ!`
            : `Đã thêm ${data.created_count} tác vụ vào danh sách chờ.`,
        'success'
    );
    await refreshStudioState();
}

// ==================== TAB 2: THƯ VIỆN (MEDIA GALLERY) ====================
function setGalleryTypeFilter(type) {
    state.galleryTypeFilter = type;
    ['all', 'video', 'image'].forEach(t => {
        const btn = document.getElementById(`gal-type-${t}`);
        if (t === type) {
            btn.className = 'px-3 py-1 rounded-md bg-museAccent text-white transition';
        } else {
            btn.className = 'px-3 py-1 rounded-md text-gray-400 hover:text-white transition';
        }
    });
    loadGallery();
}

async function loadGallery() {
    const projId = document.getElementById('gallery-project-filter')?.value || '0';
    const params = new URLSearchParams({
        media_type: state.galleryTypeFilter,
        project_id: projId
    });
    const res = await fetch(`/api/gallery?${params.toString()}`);
    const data = await res.json();
    state.galleryItems = data.items || [];

    document.getElementById('gallery-total-count').textContent = `${state.galleryItems.length} media`;
    const grid = document.getElementById('gallery-grid-container');

    if (state.galleryItems.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full py-20 text-center text-gray-500">
                <i class="fa-solid fa-photo-film text-3xl text-violet-400/40 mb-3 block"></i>
                Chưa có file media nào hoàn thành trong bộ lọc này.
            </div>
        `;
        return;
    }

    grid.innerHTML = state.galleryItems.map(item => {
        const streamUrl = `/api/media/stream?path=${encodeURIComponent(item.output_file_path || '')}`;
        const isImg = item.task_type === 'image';
        const previewHtml = isImg
            ? `<img src="${streamUrl}" class="w-full h-44 object-cover group-hover:scale-105 transition duration-300" loading="lazy" />`
            : `<video src="${streamUrl}" muted loop onmouseover="this.play()" onmouseout="this.pause()" class="w-full h-44 object-cover"></video>`;

        return `
            <div onclick="openGalleryItemModal(${item.id})" class="group cursor-pointer bg-museCard border border-museBorder hover:border-indigo-500/60 rounded-xl overflow-hidden shadow-lg flex flex-col transition">
                <div class="relative bg-black h-44 overflow-hidden">
                    ${previewHtml}
                    <span class="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-black/70 text-[10px] font-bold text-white uppercase">
                        ${isImg ? 'Ảnh (IMG)' : 'Video (VIDEO)'} · ${escapeHtml(item.aspect_ratio)}
                    </span>
                    <span class="absolute bottom-2 right-2 px-2 py-0.5 rounded-md bg-black/70 text-[10px] font-mono text-emerald-300">
                        ${item.file_size_mb || 0} MB
                    </span>
                </div>
                <div class="p-3 flex-1 flex flex-col justify-between space-y-2">
                    <div>
                        <div class="text-xs font-bold text-white truncate">${escapeHtml(item.task_name)}</div>
                        <p class="text-[11px] text-gray-400 line-clamp-2 mt-0.5">${escapeHtml(item.prompt_text)}</p>
                    </div>
                    <div class="space-y-1.5 pt-1 border-t border-museBorder/60">
                        <div class="flex items-center justify-between text-[10px] text-gray-500">
                            <span>${escapeHtml(item.project_name || '')}</span>
                            <span>${escapeHtml(item.completed_at || '')}</span>
                        </div>
                        <div class="grid grid-cols-2 gap-1.5">
                            <button onclick="event.stopPropagation(); galleryQuickOpenFile(${item.id})" class="py-1 px-2 rounded-md bg-museInput hover:bg-gray-800 border border-museBorder text-[11px] font-semibold text-gray-200 flex items-center justify-center gap-1 transition">
                                <i class="fa-solid fa-up-right-from-square text-sky-400 text-[10px]"></i>
                                <span>Mở file</span>
                            </button>
                            <button onclick="event.stopPropagation(); galleryQuickOpenFolder(${item.id})" class="py-1 px-2 rounded-md bg-museInput hover:bg-gray-800 border border-museBorder text-[11px] font-semibold text-gray-200 flex items-center justify-center gap-1 transition">
                                <i class="fa-solid fa-folder-open text-amber-400 text-[10px]"></i>
                                <span>Thư mục</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function galleryQuickOpenFile(taskId) {
    const item = state.galleryItems.find(x => x.id === taskId);
    if (!item?.output_file_path) return;
    await openSystemFileByPath(item.output_file_path);
}

async function galleryQuickOpenFolder(taskId) {
    const item = state.galleryItems.find(x => x.id === taskId);
    if (!item?.output_file_path) return;
    await openSystemFolderByPath(item.output_file_path);
}

async function openSystemFileByPath(filePath) {
    try {
        const res = await fetch('/api/system/open-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast('Đã mở file trên Windows!', 'info');
        } else {
            showToast(data.detail || 'Không thể mở file', 'error');
        }
    } catch (err) {
        showToast('Lỗi kết nối khi mở file', 'error');
    }
}

async function openSystemFolderByPath(targetPath) {
    try {
        const res = await fetch('/api/system/open-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetPath })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast('Đã mở thư mục trên Windows Explorer!', 'info');
        } else {
            showToast(data.detail || 'Không thể mở thư mục', 'error');
        }
    } catch (err) {
        showToast('Lỗi kết nối khi mở thư mục', 'error');
    }
}

function openGalleryItemModal(taskId) {
    const item = state.galleryItems.find(x => x.id === taskId);
    if (!item) return;
    openMediaPlayerModal(item);
}

function openMediaPlayerModal(item) {
    state.activePlayerItem = item;
    document.getElementById('player-modal-title').textContent = item.task_name || 'Media Player';
    document.getElementById('player-meta-project').textContent = item.project_name || 'Mặc định';
    document.getElementById('player-meta-size').textContent = `${item.file_size_mb || 0} MB`;
    document.getElementById('player-meta-ratio').textContent = item.aspect_ratio || '16:9';
    document.getElementById('player-meta-date').textContent = item.completed_at || item.created_at || '-';
    document.getElementById('player-meta-prompt').textContent = item.prompt_text || '';

    const videoEl = document.getElementById('player-modal-video');
    const imgEl = document.getElementById('player-modal-image');
    const streamUrl = `/api/media/stream?path=${encodeURIComponent(item.output_file_path || '')}`;

    if (item.task_type === 'image') {
        videoEl.pause();
        videoEl.classList.add('hidden');
        imgEl.src = streamUrl;
        imgEl.classList.remove('hidden');
    } else {
        imgEl.classList.add('hidden');
        videoEl.src = streamUrl;
        videoEl.classList.remove('hidden');
        videoEl.play().catch(() => {});
    }

    document.getElementById('modal-media-player').classList.remove('hidden');
}

function closeMediaPlayerModal() {
    const videoEl = document.getElementById('player-modal-video');
    videoEl.pause();
    videoEl.src = '';
    document.getElementById('modal-media-player').classList.add('hidden');
}

async function playerOpenFile() {
    if (!state.activePlayerItem?.output_file_path) return;
    await openSystemFileByPath(state.activePlayerItem.output_file_path);
}

async function playerOpenFolder() {
    if (!state.activePlayerItem?.output_file_path) return;
    await openSystemFolderByPath(state.activePlayerItem.output_file_path);
}

function playerCopyPrompt() {
    if (!state.activePlayerItem?.prompt_text) return;
    navigator.clipboard.writeText(state.activePlayerItem.prompt_text);
    showToast('Đã sao chép Prompt vào Clipboard!', 'success');
}

function playerReusePrompt() {
    if (!state.activePlayerItem?.prompt_text) return;
    const item = state.activePlayerItem;
    closeMediaPlayerModal();
    switchTab('studio');
    setTaskType(item.task_type || 'video');
    setAspectRatio(item.aspect_ratio || '16:9');
    const ta = document.getElementById('studio-prompt-textarea');
    ta.value = (ta.value ? ta.value + '\n' : '') + item.prompt_text;
    onPromptTextareaInput();
    showToast('Đã đưa Prompt sang khung tạo tác vụ Studio', 'info');
}

async function openOutputRootFolder() {
    const path = state.settings.output_dir || 'output';
    await openSystemFolderByPath(path);
}

// ==================== TAB 3: TÀI KHOẢN ====================
async function loadAccounts(isBackground = false) {
    try {
        const res = await fetch('/api/accounts');
        const data = await res.json();
        state.accounts = data.accounts || [];

        if (!isBackground && data.thread_config) {
            document.getElementById('acc-max-concurrent').value = data.thread_config.max_concurrent_accounts;
            document.getElementById('acc-global-max-threads').value = data.thread_config.global_max_threads;
            document.getElementById('acc-schedule-mode').value = data.thread_config.schedule_mode;
        }

        const tbody = document.getElementById('accounts-tbody');
        if (state.accounts.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="py-16 text-center text-gray-500">
                        Chưa có tài khoản Muse nào. Nhấn <b>+ Thêm tài khoản</b> để thêm mới hoặc nhập hàng loạt <code>email|pass|proxy</code>.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = state.accounts.map(acc => {
            const cookieBadge = acc.cookie_status === 'Cookie tốt'
                ? `<span class="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold">Cookie tốt</span>`
                : acc.cookie_status === 'Hết hạn'
                    ? `<span class="px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30 text-[11px] font-semibold">Hết hạn</span>`
                    : `<span class="px-2 py-0.5 rounded-full bg-gray-700/60 text-gray-300 text-[11px]">Chưa có</span>`;

            const proxyText = acc.proxy_host
                ? `<span class="font-mono text-amber-300">${escapeHtml(acc.proxy_host)}:${acc.proxy_port}</span>`
                : `<span class="text-gray-500">Trực tiếp (Direct)</span>`;

            return `
                <tr class="studio-row">
                    <td class="py-3 px-3 text-center">
                        <input type="checkbox" ${acc.is_enabled ? 'checked' : ''} onchange="updateAccountField(${acc.id}, {is_enabled: this.checked ? 1 : 0})" class="rounded accent-indigo-500 cursor-pointer" />
                    </td>
                    <td class="py-3 px-3">
                        <div class="font-bold text-white">${escapeHtml(acc.display_name || '')}</div>
                        <div class="text-gray-400 text-[11px] font-mono">${escapeHtml(acc.email)}</div>
                    </td>
                    <td class="py-3 px-3">${proxyText}</td>
                    <td class="py-3 px-2 text-center">
                        <input type="number" min="1" max="20" value="${acc.image_threads || 5}" onchange="updateAccountField(${acc.id}, {image_threads: parseInt(this.value, 10)})" class="w-14 bg-museInput border border-museBorder rounded-md py-1 text-center text-white" />
                    </td>
                    <td class="py-3 px-2 text-center">
                        <input type="number" min="1" max="20" value="${acc.video_threads || 5}" onchange="updateAccountField(${acc.id}, {video_threads: parseInt(this.value, 10)})" class="w-14 bg-museInput border border-museBorder rounded-md py-1 text-center text-white" />
                    </td>
                    <td class="py-3 px-3 text-center">
                        <span class="text-sky-300 font-medium">${escapeHtml(acc.quota_status || 'Chưa kiểm tra')}</span>
                    </td>
                    <td class="py-3 px-3 text-center">
                        <div>${cookieBadge}</div>
                        ${acc.cookie_updated_at ? `<div class="text-[10px] text-gray-500 mt-0.5">${escapeHtml(acc.cookie_updated_at)}</div>` : ''}
                    </td>
                    <td class="py-3 px-3 text-center font-mono">
                        <span class="text-indigo-400 font-bold">${acc.running_tasks || 0}</span> /
                        <span class="text-emerald-400 font-bold">${acc.completed_tasks || 0}</span> /
                        <span class="text-rose-400 font-bold">${acc.failed_tasks || 0}</span>
                    </td>
                    <td class="py-3 px-3 text-right">
                        <div class="flex items-center justify-end gap-1.5">
                            <button onclick="checkSingleAccountQuota(${acc.id})" class="px-2.5 py-1 rounded-lg bg-museCard hover:bg-gray-700 border border-museBorder text-sky-300 text-[11px] font-semibold transition">
                                Hạn mức
                            </button>
                            <button onclick="checkSingleAccountCookie(${acc.id})" class="px-2.5 py-1 rounded-lg bg-museCard hover:bg-gray-700 border border-museBorder text-amber-300 text-[11px] font-semibold transition">
                                Cookie
                            </button>
                            <button onclick="loginAccountInteractive(${acc.id})" class="px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] font-bold flex items-center gap-1 transition">
                                <i class="fa-brands fa-chrome"></i>
                                <span>Login</span>
                            </button>
                            <button onclick="deleteAccount(${acc.id})" class="px-2 py-1 rounded-lg bg-rose-500/15 hover:bg-rose-500/30 text-rose-300 text-[11px] transition">
                                Xóa
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error(e);
    }
}

async function saveAccountThreadConfig() {
    const max_concurrent_accounts = parseInt(document.getElementById('acc-max-concurrent').value || '20', 10);
    const global_max_threads = parseInt(document.getElementById('acc-global-max-threads').value || '25', 10);
    const schedule_mode = document.getElementById('acc-schedule-mode').value;

    await fetch('/api/accounts/thread-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_concurrent_accounts, global_max_threads, schedule_mode })
    });
    showToast('Đã lưu cấu hình luồng đa tài khoản', 'success');
}

function openAddAccountModal() {
    document.getElementById('modal-add-account').classList.remove('hidden');
}

function closeAddAccountModal() {
    document.getElementById('modal-add-account').classList.add('hidden');
}

function switchAddAccountMode(mode) {
    state.addAccountMode = mode;
    const singleBtn = document.getElementById('add-acc-mode-single');
    const bulkBtn = document.getElementById('add-acc-mode-bulk');
    const singleForm = document.getElementById('add-acc-single-form');
    const bulkForm = document.getElementById('add-acc-bulk-form');

    if (mode === 'single') {
        singleBtn.className = 'py-1.5 rounded-md bg-museAccent text-white';
        bulkBtn.className = 'py-1.5 rounded-md text-gray-400 hover:text-white';
        singleForm.classList.remove('hidden');
        bulkForm.classList.add('hidden');
    } else {
        bulkBtn.className = 'py-1.5 rounded-md bg-museAccent text-white';
        singleBtn.className = 'py-1.5 rounded-md text-gray-400 hover:text-white';
        bulkForm.classList.remove('hidden');
        singleForm.classList.add('hidden');
    }
}

async function submitAddAccount() {
    const image_threads = parseInt(document.getElementById('new-acc-img-threads').value || '5', 10);
    const video_threads = parseInt(document.getElementById('new-acc-vid-threads').value || '5', 10);

    let payload = { image_threads, video_threads };
    if (state.addAccountMode === 'bulk') {
        payload.bulk_text = document.getElementById('new-acc-bulk-text').value;
    } else {
        payload.display_name = document.getElementById('new-acc-name').value;
        payload.email = document.getElementById('new-acc-email').value;
        payload.password = document.getElementById('new-acc-pass').value;
    }

    const res = await fetch('/api/accounts/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) {
        showToast(data.detail || 'Thêm tài khoản thất bại', 'error');
        return;
    }

    document.getElementById('new-acc-name').value = '';
    document.getElementById('new-acc-email').value = '';
    document.getElementById('new-acc-pass').value = '';
    document.getElementById('new-acc-bulk-text').value = '';
    closeAddAccountModal();
    showToast(`Đã thêm ${data.added_count} tài khoản`, 'success');
    await loadAccounts();
}

async function updateAccountField(accId, fields) {
    await fetch(`/api/accounts/${accId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
    });
}

async function deleteAccount(accId) {
    if (!confirm('Xóa tài khoản này?')) return;
    await fetch(`/api/accounts/${accId}`, { method: 'DELETE' });
    showToast('Đã xóa tài khoản', 'info');
    await loadAccounts();
}

async function loginAccountInteractive(accId) {
    showToast('Đang mở trình duyệt Chrome... Hãy nhập OTP 6 số từ Gmail và tích Remember this device. Cửa sổ sẽ tự lưu Cookie và đóng khi vào khung Composer!', 'info');
    const res = await fetch(`/api/accounts/${accId}/login`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        showToast(data.message || 'Đăng nhập và lưu Cookie thành công!', 'success');
    } else {
        showToast(data.message || 'Chưa hoàn tất đăng nhập', 'warning');
    }
    await loadAccounts();
}

async function checkSingleAccountCookie(accId) {
    const res = await fetch(`/api/accounts/${accId}/check-cookie`, { method: 'POST' });
    const data = await res.json();
    showToast(`Trạng thái Cookie: ${data.cookie_status}`, data.cookie_status === 'Cookie tốt' ? 'success' : 'warning');
    await loadAccounts();
}

async function checkSingleAccountQuota(accId) {
    const res = await fetch(`/api/accounts/${accId}/check-quota`, { method: 'POST' });
    const data = await res.json();
    showToast(`Hạn mức: ${data.quota_status}`, 'info');
    await loadAccounts();
}

async function batchCheckCookies() {
    showToast('Đang kiểm tra trạng thái Cookie toàn bộ tài khoản...', 'info');
    await fetch('/api/accounts/batch-check-cookies', { method: 'POST' });
    await loadAccounts();
    showToast('Đã cập nhật trạng thái Cookie', 'success');
}

async function batchCheckQuota() {
    showToast('Đang kiểm tra hạn mức toàn bộ tài khoản...', 'info');
    await fetch('/api/accounts/batch-check-quota', { method: 'POST' });
    await loadAccounts();
    showToast('Đã cập nhật hạn mức tài khoản', 'success');
}

// ==================== TAB 4: PROXY ====================
async function loadProxies() {
    const res = await fetch('/api/proxies');
    const data = await res.json();
    state.proxies = data.proxies || [];
    document.getElementById('proxy-total-badge').textContent = `${state.proxies.length} Proxy`;

    const tbody = document.getElementById('proxies-tbody');
    if (state.proxies.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="py-16 text-center text-gray-500">
                    Danh sách Proxy trống. Hãy nạp Proxy ở khung bên phải.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = state.proxies.map(p => {
        const statusBadge = p.status === 'Live'
            ? `<span class="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold">Live</span>`
            : p.status === 'Dead'
                ? `<span class="px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30 text-[11px] font-semibold">Dead</span>`
                : `<span class="px-2 py-0.5 rounded-full bg-gray-700/60 text-gray-300 text-[11px]">Chưa kiểm tra</span>`;

        const latencyHtml = p.latency_ms ? `<span class="font-mono text-emerald-300">${p.latency_ms} ms</span>` : '-';
        const assignedAcc = p.account_email || p.account_name || '<span class="text-gray-500">Chưa gán</span>';

        return `
            <tr class="studio-row">
                <td class="py-2.5 px-3 text-center font-mono text-gray-400">#${p.id}</td>
                <td class="py-2.5 px-3 font-mono text-white">${escapeHtml(p.raw_string)}</td>
                <td class="py-2.5 px-3 text-center uppercase text-indigo-300 font-semibold">${escapeHtml(p.protocol)}</td>
                <td class="py-2.5 px-3 text-center">${statusBadge}</td>
                <td class="py-2.5 px-3 text-center">${latencyHtml}</td>
                <td class="py-2.5 px-3 text-gray-300">${assignedAcc}</td>
                <td class="py-2.5 px-3 text-right">
                    <div class="flex items-center justify-end gap-1">
                        <button onclick="checkSingleProxy(${p.id})" class="px-2 py-1 rounded bg-museCard hover:bg-gray-700 text-emerald-300 text-[11px]">Test</button>
                        <button onclick="deleteSingleProxy(${p.id})" class="px-2 py-1 rounded bg-rose-500/15 hover:bg-rose-500/30 text-rose-300 text-[11px]">Xóa</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function submitBulkProxies() {
    const raw_lines = document.getElementById('proxy-bulk-textarea').value;
    const protocol = document.getElementById('proxy-default-protocol').value;
    if (!raw_lines || !raw_lines.trim()) {
        showToast('Vui lòng nhập danh sách Proxy', 'warning');
        return;
    }
    const res = await fetch('/api/proxies/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_lines, protocol })
    });
    const data = await res.json();
    if (data.ok) {
        document.getElementById('proxy-bulk-textarea').value = '';
        showToast(`Đã nạp thành công ${data.added} Proxy`, 'success');
        await loadProxies();
    }
}

async function checkAllProxies() {
    showToast('Đang kiểm tra kết nối toàn bộ Proxy...', 'info');
    await fetch('/api/proxies/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    });
    await loadProxies();
    showToast('Đã kiểm tra xong danh sách Proxy', 'success');
}

async function checkSingleProxy(proxyId) {
    await fetch('/api/proxies/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy_ids: [proxyId] })
    });
    await loadProxies();
}

async function autoAssignProxies() {
    const res = await fetch('/api/proxies/auto-assign', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        showToast(`Đã tự động gán Proxy cho ${data.assigned} tài khoản`, 'success');
        await loadProxies();
    } else {
        showToast(data.message || 'Không thể gán Proxy', 'warning');
    }
}

async function deleteSingleProxy(proxyId) {
    await fetch(`/api/proxies/${proxyId}`, { method: 'DELETE' });
    await loadProxies();
}

async function clearDeadProxies() {
    const res = await fetch('/api/proxies/clear-dead', { method: 'POST' });
    const data = await res.json();
    showToast(`Đã dọn dẹp ${data.deleted} Proxy Dead`, 'info');
    await loadProxies();
}

// ==================== TAB 5: CÀI ĐẶT ====================
async function loadSettingsIntoForm() {
    const res = await fetch('/api/settings');
    const data = await res.json();
    const s = data.settings || {};
    state.settings = s;

    document.getElementById('set-output-dir').value = s.output_dir || '';
    document.getElementById('set-image-timeout').value = s.image_timeout_sec || '300';
    document.getElementById('set-video-timeout').value = s.video_timeout_sec || '600';
    document.getElementById('set-auto-approve').checked = s.auto_approve === '1';
    document.getElementById('set-offscreen-mode').checked = s.offscreen_mode === '1';

    document.getElementById('set-tpl-t2i').value = s.tpl_text_to_image || '';
    document.getElementById('set-tpl-i2i').value = s.tpl_image_to_image || '';
    document.getElementById('set-tpl-t2v').value = s.tpl_text_to_video || '';
    document.getElementById('set-tpl-i2v').value = s.tpl_image_to_video || '';
}

async function browseOutputFolder() {
    const res = await fetch('/api/dialog/select-folder?purpose=output', { method: 'POST' });
    const data = await res.json();
    if (data.ok && data.folder) {
        document.getElementById('set-output-dir').value = data.folder;
    }
}

async function saveAllSettings() {
    const payload = {
        output_dir: document.getElementById('set-output-dir').value.trim(),
        image_timeout_sec: document.getElementById('set-image-timeout').value,
        video_timeout_sec: document.getElementById('set-video-timeout').value,
        auto_approve: document.getElementById('set-auto-approve').checked ? '1' : '0',
        offscreen_mode: document.getElementById('set-offscreen-mode').checked ? '1' : '0',
        tpl_text_to_image: document.getElementById('set-tpl-t2i').value,
        tpl_image_to_image: document.getElementById('set-tpl-i2i').value,
        tpl_text_to_video: document.getElementById('set-tpl-t2v').value,
        tpl_image_to_video: document.getElementById('set-tpl-i2v').value
    };

    const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
        state.settings = data.settings;
        showToast('Đã lưu toàn bộ cài đặt hệ thống và mẫu Prompt Wrapper!', 'success');
    }
}

async function resetPromptTemplates() {
    const res = await fetch('/api/settings/reset-templates', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        await loadSettingsIntoForm();
        showToast('Đã khôi phục 4 mẫu Prompt Wrapper về mặc định', 'info');
    }
}
