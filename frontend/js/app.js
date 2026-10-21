// ==================== STYLE PRESET CHIPS ====================
const STYLE_PRESET_CHIPS = [
    { id: 'cinema4k', label: '🎥 Điện ảnh 4K', suffix: 'cinematic lighting, 4K movie frame, photorealistic, shallow depth of field' },
    { id: 'anime', label: '🌸 Anime Ghibli', suffix: 'Studio Ghibli anime style, vibrant colors, detailed hand-drawn animation' },
    { id: 'real8k', label: '📸 Chân thực 8K', suffix: 'ultra-realistic 8K photography, natural texture, sharp focus, DSLR' },
    { id: 'smoothpan', label: '🎞️ Chuyển động mượt', suffix: 'smooth camera pan, fluid natural motion, cinematic slow motion' },
    { id: 'cyberpunk', label: '✨ Cyberpunk Neon', suffix: 'cyberpunk neon aesthetic, volumetric fog, dramatic rim lighting' },
    { id: 'golden', label: '🌅 Nắng Hoàng hôn', suffix: 'golden hour sunlight, warm cinematic glow, soft atmospheric shadows' }
];

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
    activeStyleChips: new Set(),

    // Gallery State
    galleryTypeFilter: 'all',
    galleryItems: [],
    selectedGalleryIds: new Set(),
    activePlayerItem: null,

    // Sound & Notification
    soundNotifyEnabled: localStorage.getItem('muse_sound_notify') !== '0',
    _prevGlobalRunning: 0,

    // Accounts & Proxies
    accounts: [],
    proxies: [],
    addAccountMode: 'single',
    settings: {}
};

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', async () => {
    updateSoundNotifyUI();
    renderStyleChips();
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

function updateSoundNotifyUI() {
    const btn = document.getElementById('btn-sound-notify');
    const icon = document.getElementById('icon-sound-notify');
    const label = document.getElementById('label-sound-notify');
    if (!btn || !icon || !label) return;
    if (state.soundNotifyEnabled) {
        btn.className = 'px-2.5 py-1.5 rounded-lg bg-amber-500/15 border border-amber-500/30 text-xs font-semibold text-amber-300 flex items-center gap-1.5 transition';
        icon.className = 'fa-solid fa-bell text-amber-400';
        label.textContent = 'Âm báo: Bật';
    } else {
        btn.className = 'px-2.5 py-1.5 rounded-lg bg-museInput border border-museBorder text-xs font-semibold text-gray-400 flex items-center gap-1.5 transition';
        icon.className = 'fa-regular fa-bell-slash text-gray-500';
        label.textContent = 'Âm báo: Tắt';
    }
}

function toggleSoundNotify() {
    state.soundNotifyEnabled = !state.soundNotifyEnabled;
    localStorage.setItem('muse_sound_notify', state.soundNotifyEnabled ? '1' : '0');
    updateSoundNotifyUI();
    if (state.soundNotifyEnabled) {
        playCompletionChime();
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().catch(() => {});
        }
        showToast('Đã bật chuông báo khi hoàn thành hàng đợi!', 'success');
    } else {
        showToast('Đã tắt chuông báo hoàn thành', 'info');
    }
}

function playCompletionChime() {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        const notes = [523.25, 659.25, 783.99, 1046.5]; // C5 - E5 - G5 - C6
        notes.forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, ctx.currentTime + i * 0.11);
            gain.gain.setValueAtTime(0.14, ctx.currentTime + i * 0.11);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.11 + 0.35);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(ctx.currentTime + i * 0.11);
            osc.stop(ctx.currentTime + i * 0.11 + 0.36);
        });
    } catch (e) {}
}

function triggerQueueCompletionAlert(completedTotal) {
    showToast(`🎉 Toàn bộ hàng đợi tác vụ đã hoàn thành! (Tổng xong: ${completedTotal})`, 'success');
    if (!state.soundNotifyEnabled) return;
    playCompletionChime();
    try {
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Muse Studio — Hoàn tất hàng đợi!', {
                body: `Toàn bộ tác vụ đang chạy đã hoàn thành (${completedTotal} media).`
            });
        }
    } catch (e) {}
}

function renderStyleChips() {
    const container = document.getElementById('style-chips-container');
    if (!container) return;
    container.innerHTML = STYLE_PRESET_CHIPS.map(chip => {
        const active = state.activeStyleChips.has(chip.id);
        const cls = active
            ? 'bg-indigo-600 text-white border-indigo-400 shadow-sm'
            : 'bg-museInput hover:bg-gray-800 text-gray-300 border-museBorder';
        return `<button type="button" onclick="toggleStyleChip('${chip.id}')" title="Nối hậu tố: ${escapeHtml(chip.suffix)}" class="px-2 py-1 rounded-lg border text-[11px] font-medium transition ${cls}">${chip.label}</button>`;
    }).join('');
}

function toggleStyleChip(chipId) {
    if (state.activeStyleChips.has(chipId)) {
        state.activeStyleChips.delete(chipId);
    } else {
        state.activeStyleChips.add(chipId);
    }
    renderStyleChips();
}

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

// ==================== LICENSE KEY MANAGEMENT (GATEKEEPER) ====================
function updateLicenseUI(lic) {
    if (!lic) return;
    const btn = document.getElementById('btn-header-license');
    const icon = document.getElementById('icon-header-license');
    const lbl = document.getElementById('label-header-license');
    const hwidInput = document.getElementById('lic-modal-hwid');
    const statusBox = document.getElementById('lic-modal-status-box');
    const statusTitle = document.getElementById('lic-modal-status-title');
    const statusMsg = document.getElementById('lic-modal-status-msg');
    const closeBtn = document.getElementById('lic-modal-close-btn');
    const cancelBtn = document.getElementById('lic-modal-cancel-btn');
    const deactBtn = document.getElementById('lic-modal-deactivate-btn');

    if (hwidInput && lic.hwid) {
        hwidInput.value = lic.hwid;
    }

    if (lic.is_valid) {
        const isExpiringSoon = (lic.days_remaining || 0) <= 3;
        if (btn && icon && lbl) {
            if (isExpiringSoon) {
                btn.className = 'px-2.5 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-xs font-semibold text-amber-300 flex items-center gap-1.5 transition';
                icon.className = 'fa-solid fa-triangle-exclamation text-amber-400';
            } else {
                btn.className = 'px-2.5 py-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold text-emerald-300 flex items-center gap-1.5 transition';
                icon.className = 'fa-solid fa-key text-emerald-400';
            }
            const daysText = lic.days_remaining > 3650 ? 'Vĩnh viễn' : `Còn ${lic.days_remaining} ngày (${lic.expires_at})`;
            lbl.textContent = `Bản quyền: ${lic.customer || 'Active'} · ${daysText}`;
        }

        if (statusBox && statusTitle && statusMsg) {
            statusBox.className = 'p-3.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 text-emerald-200 space-y-1';
            statusTitle.innerHTML = `✅ Bản quyền đang hoạt động (${escapeHtml(lic.customer || 'Khách hàng')})`;
            statusMsg.innerHTML = `Thiết bị: <b class="font-mono">${escapeHtml(lic.hwid)}</b> · Ngày hết hạn: <b>${escapeHtml(lic.expires_at)}</b> (Còn <b>${lic.days_remaining}</b> ngày sử dụng).`;
        }
        if (closeBtn) closeBtn.classList.remove('hidden');
        if (cancelBtn) cancelBtn.classList.remove('hidden');
        if (deactBtn) deactBtn.classList.remove('hidden');
    } else {
        if (btn && icon && lbl) {
            btn.className = 'px-2.5 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-xs font-bold text-rose-300 flex items-center gap-1.5 transition animate-pulse';
            icon.className = 'fa-solid fa-lock text-rose-400';
            lbl.textContent = lic.status_code === 'expired' ? 'Bản quyền: ĐÃ HẾT HẠN' : 'Chưa kích hoạt Key';
        }
        if (statusBox && statusTitle && statusMsg) {
            statusBox.className = 'p-3.5 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-200 space-y-1';
            statusTitle.textContent = lic.status_code === 'expired'
                ? '⚠️ License Key đã hết hạn sử dụng!'
                : '🔒 Yêu cầu Kích hoạt License Key Bản quyền';
            statusMsg.textContent = lic.message || 'Vui lòng gửi Mã Thiết Bị (HWID) bên dưới cho Admin để được cấp License Key.';
        }
        if (closeBtn) closeBtn.classList.add('hidden');
        if (cancelBtn) cancelBtn.classList.add('hidden');
        if (deactBtn) deactBtn.classList.add('hidden');

        // Tự động bật màn hình khóa Bản quyền nếu chưa mở
        const modal = document.getElementById('modal-license-gate');
        if (modal && modal.classList.contains('hidden')) {
            modal.classList.remove('hidden');
        }
    }
}

async function openLicenseModal(manualOpen = false) {
    try {
        const res = await fetch('/api/license/status');
        const data = await res.json();
        if (data && data.license) {
            state.license = data.license;
            updateLicenseUI(data.license);
        }
    } catch (e) {}
    const modal = document.getElementById('modal-license-gate');
    if (modal) modal.classList.remove('hidden');
}

function closeLicenseModal() {
    if (state.license && !state.license.is_valid) {
        showToast('Vui lòng nhập License Key hợp lệ để mở khóa ứng dụng!', 'warning');
        return;
    }
    const modal = document.getElementById('modal-license-gate');
    if (modal) modal.classList.add('hidden');
}

function copyMachineHwid() {
    const hwidEl = document.getElementById('lic-modal-hwid');
    const hwid = hwidEl ? hwidEl.value.trim() : (state.license?.hwid || '');
    if (!hwid) return;
    navigator.clipboard.writeText(hwid);
    showToast(`Đã sao chép Mã Máy (HWID): ${hwid}`, 'success');
}

async function submitActivateLicense() {
    const keyInput = document.getElementById('lic-modal-key-input');
    const license_key = keyInput ? keyInput.value.trim() : '';
    if (!license_key) {
        showToast('Vui lòng dán mã MUSEKEY-... vào ô nhập!', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/license/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ license_key })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.detail || 'License Key không hợp lệ!', 'error');
            return;
        }
        state.license = data.license;
        updateLicenseUI(data.license);
        if (keyInput) keyInput.value = '';
        showToast(data.message || 'Kích hoạt bản quyền thành công!', 'success');
        closeLicenseModal();
        await refreshStudioState();
    } catch (err) {
        showToast('Lỗi kết nối khi kích hoạt bản quyền', 'error');
    }
}

async function deactivateCurrentLicense() {
    if (!confirm('Bạn có chắc muốn gỡ License Key hiện tại khỏi máy này?')) return;
    const res = await fetch('/api/license/deactivate', { method: 'POST' });
    const data = await res.json();
    if (data && data.license) {
        state.license = data.license;
        updateLicenseUI(data.license);
    }
    showToast('Đã gỡ License Key hiện tại', 'info');
}

// ==================== OTA AUTO-UPDATER (CẬP NHẬT 1 CHẠM) ====================
function renderChangelogItems(items) {
    const ul = document.getElementById('upd-changelog-list');
    if (!ul) return;
    if (!items || items.length === 0) {
        ul.innerHTML = `<li class="text-gray-500 italic">Không có ghi chú chi tiết.</li>`;
        return;
    }
    ul.innerHTML = items.map(line => `<li>${escapeHtml(line)}</li>`).join('');
}

async function openUpdaterModal() {
    try {
        const res = await fetch('/api/updater/info');
        const data = await res.json();
        if (data && data.info) {
            const info = data.info;
            state.versionInfo = info;
            const localVerEl = document.getElementById('upd-local-ver');
            const localDateEl = document.getElementById('upd-local-date');
            const srcInput = document.getElementById('upd-source-url-input');
            if (localVerEl) localVerEl.textContent = `v${info.version || '1.2.0'}`;
            if (localDateEl) localDateEl.textContent = info.released_at || '-';
            if (srcInput && !srcInput.value && info.update_manifest_url) {
                srcInput.value = info.update_manifest_url;
            }
            renderChangelogItems(info.changelog || []);
        }
    } catch (e) {}

    const modal = document.getElementById('modal-app-updater');
    if (modal) modal.classList.remove('hidden');

    const srcVal = document.getElementById('upd-source-url-input')?.value?.trim();
    if (srcVal) {
        await checkAppUpdateNow();
    }
}

function closeUpdaterModal() {
    const modal = document.getElementById('modal-app-updater');
    if (modal) modal.classList.add('hidden');
}

async function checkAppUpdateNow() {
    const srcInput = document.getElementById('upd-source-url-input');
    const statusBox = document.getElementById('upd-status-box');
    const remoteVerEl = document.getElementById('upd-remote-ver');
    const remoteDateEl = document.getElementById('upd-remote-date');
    const hdrBtn = document.getElementById('btn-header-updater');
    const hdrLbl = document.getElementById('label-header-updater');

    const source_url = srcInput ? srcInput.value.trim() : '';
    if (statusBox) {
        statusBox.className = 'p-3 rounded-xl bg-museInput border border-sky-500/30 text-sky-200 leading-relaxed';
        statusBox.textContent = '⏳ Đang kết nối máy chủ kiểm tra phiên bản mới nhất...';
    }

    try {
        const res = await fetch('/api/updater/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_url })
        });
        const data = await res.json();

        if (!data.ok) {
            if (statusBox) {
                statusBox.className = 'p-3 rounded-xl bg-amber-500/10 border border-amber-500/40 text-amber-200 leading-relaxed';
                statusBox.textContent = data.message || 'Không thể kiểm tra bản cập nhật.';
            }
            return;
        }

        if (remoteVerEl) remoteVerEl.textContent = `v${data.remote_version}`;
        if (remoteDateEl) remoteDateEl.textContent = data.remote_released_at || 'Mới nhất';
        if (data.remote_changelog && data.remote_changelog.length > 0) {
            renderChangelogItems(data.remote_changelog);
        }

        if (data.has_update) {
            if (statusBox) {
                statusBox.className = 'p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/40 text-emerald-200 font-semibold leading-relaxed';
                statusBox.textContent = data.message;
            }
            if (hdrBtn && hdrLbl) {
                hdrBtn.className = 'px-2.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-500/50 text-xs font-bold text-emerald-300 flex items-center gap-1.5 transition animate-pulse';
                hdrLbl.textContent = `✨ Có bản mới v${data.remote_version}!`;
            }
            showToast(`Đã phát hiện phiên bản mới v${data.remote_version}!`, 'success');
        } else {
            if (statusBox) {
                statusBox.className = 'p-3 rounded-xl bg-museInput border border-emerald-500/30 text-emerald-300 leading-relaxed';
                statusBox.textContent = data.message;
            }
            showToast(`Bạn đang ở phiên bản mới nhất (v${data.local_version})`, 'info');
        }
    } catch (err) {
        if (statusBox) {
            statusBox.className = 'p-3 rounded-xl bg-rose-500/10 border border-rose-500/40 text-rose-200 leading-relaxed';
            statusBox.textContent = 'Lỗi kết nối khi kiểm tra phiên bản mới.';
        }
    }
}

async function applyAppUpdateNow() {
    const srcInput = document.getElementById('upd-source-url-input');
    const statusBox = document.getElementById('upd-status-box');
    const applyBtn = document.getElementById('btn-upd-apply');
    const source_url = srcInput ? srcInput.value.trim() : '';

    if (!confirm('Tải và cập nhật lên phiên bản mới ngay bây giờ?\n(Toàn bộ License Key, Tài khoản, Cookie, Proxy và Video của bạn được bảo toàn 100%).')) {
        return;
    }

    if (applyBtn) applyBtn.disabled = true;
    if (statusBox) {
        statusBox.className = 'p-3 rounded-xl bg-sky-500/15 border border-sky-500/40 text-sky-200 font-semibold leading-relaxed';
        statusBox.textContent = '🚀 Đang tải gói cập nhật và nâng cấp ứng dụng... Vui lòng chờ 2–3 giây!';
    }

    try {
        const res = await fetch('/api/updater/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_url })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            if (statusBox) {
                statusBox.className = 'p-3 rounded-xl bg-rose-500/15 border border-rose-500/40 text-rose-200 leading-relaxed';
                statusBox.textContent = data.detail || data.message || 'Cập nhật thất bại!';
            }
            showToast(data.detail || data.message || 'Cập nhật thất bại', 'error');
            if (applyBtn) applyBtn.disabled = false;
            return;
        }

        if (statusBox) {
            statusBox.className = 'p-3 rounded-xl bg-emerald-500/20 border border-emerald-500/50 text-emerald-200 font-bold leading-relaxed';
            statusBox.textContent = data.message || 'Cập nhật thành công! Đang tự động khởi động lại ứng dụng...';
        }
        showToast('Cập nhật thành công! Đang khởi động lại Muse Studio...', 'success');
        setTimeout(() => {
            window.location.reload();
        }, 3200);
    } catch (err) {
        showToast('Đang khởi động lại phiên bản mới...', 'info');
        setTimeout(() => {
            window.location.reload();
        }, 3200);
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
        if (data.license) {
            state.license = data.license;
            updateLicenseUI(data.license);
        }
        if (data.version_info && data.version_info.version) {
            state.versionInfo = data.version_info;
            const hdrLbl = document.getElementById('label-header-updater');
            if (hdrLbl && !hdrLbl.textContent.includes('Có bản mới')) {
                hdrLbl.textContent = `v${data.version_info.version} · Cập nhật`;
            }
        }

        // Cập nhật 2 Badge góc phải Header + Kiểm tra hoàn tất hàng đợi
        const curRunning = data.global_counts?.running ?? 0;
        const curCompleted = data.global_counts?.completed ?? 0;
        const pc = data.project_counts || {};
        if (state._prevGlobalRunning > 0 && curRunning === 0 && (pc.pending ?? 0) === 0) {
            triggerQueueCompletionAlert(curCompleted);
        }
        state._prevGlobalRunning = curRunning;

        document.getElementById('badge-global-running').textContent = curRunning;
        document.getElementById('badge-global-completed').textContent = curCompleted;

        // Cập nhật số lượng trên bộ lọc Studio
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
        const emptyHtml = `
            <tr>
                <td colspan="7" class="py-16 text-center text-gray-500">
                    <i class="fa-solid fa-wand-magic-sparkles text-2xl text-indigo-400/40 mb-2 block"></i>
                    Chưa có tác vụ nào trong danh sách. Hãy nhập Prompt ở cột bên phải để bắt đầu!
                </td>
            </tr>
        `;
        if (state._lastTasksHtml !== emptyHtml) {
            tbody.innerHTML = emptyHtml;
            state._lastTasksHtml = emptyHtml;
        }
        return;
    }

    const newHtml = state.tasks.map(t => {
        const isSelected = state.selectedTaskIds.has(t.id);
        const typeBadge = getTaskTypeBadge(t.task_type, t.aspect_ratio, t.ref_images);
        const statusCell = getTaskStatusCell(t);
        const accLabel = t.account_name || t.account_email || '<span class="text-gray-500">Chưa gán</span>';
        const hasOutput = t.status === 'completed' && t.output_file_path;

        const refCount = (t.ref_images || []).length;
        const refTag = refCount > 0
            ? `<span class="ml-1.5 px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 text-[10px]" title="Đính kèm ${refCount} ảnh tham chiếu (${t.ref_mode})"><i class="fa-solid fa-paperclip mr-0.5"></i>${refCount} ảnh</span>`
            : '';

        const chainIdx = parseInt(t.chain_index || 0, 10);
        let chainTag = '';
        if (chainIdx === 999) {
            chainTag = `<span class="ml-1.5 px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[10px] font-bold" title="Video dài đã ghép hoàn chỉnh bằng FFmpeg"><i class="fa-solid fa-film mr-0.5"></i>Video Dài</span>`;
        } else if (chainIdx > 0) {
            chainTag = `<span class="ml-1.5 px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[10px]" title="Phân cảnh nối tiếp #${chainIdx} (Tự lấy frame cuối từ cảnh trước)"><i class="fa-solid fa-link mr-0.5"></i>Cảnh #${chainIdx}</span>`;
        }
        const charLockTag = (t.character_lock_text && t.character_lock_text.trim())
            ? `<span class="ml-1 px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 text-[10px]" title="Khóa đồng bộ nhân vật: ${escapeHtml(t.character_lock_text)}"><i class="fa-solid fa-user-lock mr-0.5"></i>Khóa NV</span>`
            : '';

        return `
            <tr data-task-id="${t.id}" class="studio-row transition ${isSelected ? 'selected' : ''}">
                <td class="py-2.5 px-3 text-center">
                    <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleSelectTask(${t.id}, this.checked)" class="rounded border-gray-600 bg-museInput text-indigo-600 focus:ring-0 cursor-pointer" />
                </td>
                <td class="py-2.5 px-2 text-center font-mono font-bold text-gray-400">${t.stt}</td>
                <td class="py-2.5 px-3 max-w-xs">
                    <div class="flex items-center flex-wrap gap-y-0.5">
                        <span class="font-bold text-white">${escapeHtml(t.task_name)}</span>
                        ${refTag}
                        ${chainTag}
                        ${charLockTag}
                    </div>
                    <p class="text-gray-400 truncate mt-0.5 cursor-pointer hover:text-indigo-300" onclick="openEditPromptModal(${t.id})" title="Bấm để sửa Prompt: ${escapeHtml(t.prompt_text)}">${escapeHtml(t.prompt_text)}</p>
                </td>
                <td class="py-2.5 px-2 text-center">${typeBadge}</td>
                <td class="py-2.5 px-2 text-gray-300 truncate max-w-[120px]">${accLabel}</td>
                <td class="py-2.5 px-3">${statusCell}</td>
                <td class="py-2.5 px-3 text-right">
                    <div class="flex items-center justify-end gap-1">
                        ${(hasOutput && t.task_type === 'image') ? `
                        <button onclick="studioAnimateToVideo(${t.id})" title="Tạo Video chuyển động từ bức ảnh này (Ảnh → Video)" class="w-7 h-7 rounded-lg bg-violet-500/20 hover:bg-violet-500/40 text-violet-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-clapperboard text-[11px]"></i>
                        </button>
                        ` : ''}
                        <button onclick="openTaskMedia(${t.id})" ${hasOutput ? '' : 'disabled'} title="Phát Media (Play)" class="w-7 h-7 rounded-lg ${hasOutput ? 'bg-indigo-500/20 hover:bg-indigo-500/40 text-indigo-300' : 'bg-gray-800/50 text-gray-600 cursor-not-allowed'} flex items-center justify-center transition">
                            <i class="fa-solid fa-play text-[11px]"></i>
                        </button>
                        <button onclick="openTaskFolder(${t.id})" title="Mở thư mục chứa file" class="w-7 h-7 rounded-lg bg-museCard hover:bg-gray-700 text-amber-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-folder-open text-[11px]"></i>
                        </button>
                        <button onclick="openEditPromptModal(${t.id})" title="Sửa Prompt tác vụ" class="w-7 h-7 rounded-lg bg-museCard hover:bg-indigo-500/25 text-sky-300 flex items-center justify-center transition">
                            <i class="fa-solid fa-pen-to-square text-[11px]"></i>
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

    if (state._lastTasksHtml === newHtml) {
        return;
    }
    state._lastTasksHtml = newHtml;
    tbody.innerHTML = newHtml;
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

async function onPromptFileSelected(event) {
    const file = event.target && event.target.files ? event.target.files[0] : null;
    if (!file) return;
    try {
        const text = await file.text();
        const lines = text
            .split(/\r?\n/)
            .map(ln => ln.trim())
            .filter(ln => ln && !ln.startsWith('#'));
        if (lines.length === 0) {
            showToast('File không có dòng Prompt nào hợp lệ', 'warning');
            return;
        }
        const ta = document.getElementById('studio-prompt-textarea');
        ta.value = (ta.value.trim() ? ta.value.trim() + '\n' : '') + lines.join('\n');
        onPromptTextareaInput();
        showToast(`Đã nạp ${lines.length} dòng Prompt từ file ${file.name}!`, 'success');
    } catch (err) {
        showToast('Không thể đọc file Prompt', 'error');
    } finally {
        event.target.value = '';
    }
}

function openEditPromptModal(taskId) {
    const t = state.tasks.find(x => x.id === taskId);
    if (!t) return;
    document.getElementById('edit-prompt-task-id').value = t.id;
    document.getElementById('edit-prompt-modal-title').textContent = `Sửa Prompt: ${t.task_name}`;
    document.getElementById('edit-prompt-type').value = t.task_type || 'video';
    document.getElementById('edit-prompt-ratio').value = t.aspect_ratio || '16:9';
    document.getElementById('edit-prompt-textarea').value = t.prompt_text || '';
    document.getElementById('modal-edit-prompt').classList.remove('hidden');
}

function closeEditPromptModal() {
    document.getElementById('modal-edit-prompt').classList.add('hidden');
}

async function submitEditPrompt(autoStart) {
    const taskId = parseInt(document.getElementById('edit-prompt-task-id').value || '0', 10);
    const prompt_text = document.getElementById('edit-prompt-textarea').value.trim();
    const task_type = document.getElementById('edit-prompt-type').value;
    const aspect_ratio = document.getElementById('edit-prompt-ratio').value;
    if (!taskId || !prompt_text) {
        showToast('Nội dung Prompt không được để trống', 'warning');
        return;
    }
    const res = await fetch(`/api/tasks/${taskId}/prompt`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_text, task_type, aspect_ratio, auto_start: autoStart })
    });
    if (res.ok) {
        closeEditPromptModal();
        showToast(autoStart ? 'Đã cập nhật Prompt và chạy lại tác vụ!' : 'Đã lưu thay đổi Prompt!', 'success');
        await refreshStudioState();
    } else {
        showToast('Lỗi khi cập nhật Prompt', 'error');
    }
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
    let prompts = getPromptLinesFromTextarea();
    if (prompts.length === 0) {
        showToast('Vui lòng nhập ít nhất 1 dòng Prompt!', 'warning');
        return;
    }

    const charLockEl = document.getElementById('studio-char-lock-input');
    const chainToggleEl = document.getElementById('studio-chain-mode-toggle');
    const characterLockText = charLockEl ? charLockEl.value.trim() : '';
    const chainMode = !!(chainToggleEl && chainToggleEl.checked);

    if (chainMode && prompts.length < 2) {
        showToast('Chế độ Chuỗi Video Dài cần ít nhất 2 dòng Prompt (hoặc bấm "Tự chia chuỗi Clip 10s" để chia tự động)!', 'warning');
        return;
    }

    // Nối hậu tố từ các Thẻ Phong cách nhanh (Style Chips) đang bật
    const activeSuffixes = STYLE_PRESET_CHIPS
        .filter(c => state.activeStyleChips.has(c.id))
        .map(c => c.suffix);
    if (activeSuffixes.length > 0) {
        const suffixStr = activeSuffixes.join(', ');
        prompts = prompts.map(p => `${p}, ${suffixStr}`);
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
            auto_start: autoStart,
            character_lock_text: characterLockText,
            chain_mode: chainMode
        })
    });
    const data = await res.json();
    if (!res.ok) {
        showToast(data.detail || 'Lỗi khi tạo tác vụ', 'error');
        return;
    }

    clearPromptTextarea();
    const chainMsg = data.chain_group_id
        ? ` (Chuỗi Video Dài ${data.created_count * 10}s - Tự trích frame cuối & ghép FFmpeg)`
        : '';
    showToast(
        autoStart
            ? `Đã tạo và bắt đầu chạy ${data.created_count} tác vụ${chainMsg}!`
            : `Đã thêm ${data.created_count} tác vụ vào danh sách chờ${chainMsg}.`,
        'success'
    );
    await refreshStudioState();
}

function onChainModeToggleChange() {
    const chainToggleEl = document.getElementById('studio-chain-mode-toggle');
    if (chainToggleEl && chainToggleEl.checked) {
        if (state.newTaskType === 'image') {
            setTaskType('video');
        }
        if (state.refImages.length > 0 && state.newRefMode !== 'shared') {
            setRefMode('shared');
            showToast('Đã tự động chuyển Ảnh tham chiếu sang "Dùng chung" để giữ 100% nhân vật đồng bộ qua mọi clip!', 'info');
        }
    }
}

function autoSplitScriptIntoChainClips() {
    const ta = document.getElementById('studio-prompt-textarea');
    const sel = document.getElementById('chain-target-duration-select');
    const chainToggle = document.getElementById('studio-chain-mode-toggle');
    if (!ta) return;

    const clipCount = parseInt((sel && sel.value) || '6', 10);
    const rawLines = getPromptLinesFromTextarea();
    if (rawLines.length === 0) {
        showToast('Hãy nhập ý tưởng hoặc kịch bản tổng thể vào ô Prompt trước khi bấm Tự chia chuỗi Clip 10s!', 'warning');
        ta.focus();
        return;
    }

    // Tự động bật công tắc Chuỗi Video Dài & Dùng chung ảnh nhân vật
    if (chainToggle && !chainToggle.checked) {
        chainToggle.checked = true;
        onChainModeToggleChange();
    }

    const baseIdea = rawLines.join(' — ');
    const stageTemplates = [
        { phase: 'Mở đầu (Establishing & Action Start)', cam: 'Wide tracking shot, nhân vật bắt đầu di chuyển vào bối cảnh, kết thúc cảnh đúng lúc đang bước đi/chuyển động' },
        { phase: 'Triển khai hành động (Continuous Motion)', cam: 'Medium follow shot nối tiếp từ vị trí cuối cảnh trước, máy quay pan mượt theo chuyển động đang diễn ra' },
        { phase: 'Tương tác bối cảnh (Dynamic Progression)', cam: 'Dynamic side-angle tracking shot, nhân vật tiếp tục hành động liền mạch, cắt cảnh đúng lúc đang xoay người/di chuyển' },
        { phase: 'Cao trào chuyển động (Climax Action)', cam: 'Close-to-medium cinematic dolly shot, biểu cảm và chuyển động nhân vật liên tục, ánh sáng đồng nhất' },
        { phase: 'Mở rộng không gian (Environment Sweep)', cam: 'Smooth crane/gimbal movement theo bước chân nhân vật, giữ nguyên trang phục và ánh sáng, cắt giữa chuyển động' },
        { phase: 'Kết chuỗi (Resolution & Final Motion)', cam: 'Cinematic slow pull-back shot nối tiếp mượt mà từ khung hình trước, hoàn tất chuỗi hành động tự nhiên' }
    ];

    const generatedLines = [];
    for (let i = 1; i <= clipCount; i++) {
        const startSec = (i - 1) * 10;
        const endSec = i * 10;
        const tpl = stageTemplates[(i - 1) % stageTemplates.length];
        generatedLines.push(
            `[Cảnh ${i}/${clipCount} - ${startSec}s-${endSec}s | ${tpl.phase}] ${baseIdea} — (${tpl.cam}, chỉ sinh âm thanh môi trường ambient tự nhiên, không nhạc nền/VO rời rạc)`
        );
    }

    ta.value = generatedLines.join('\n');
    onPromptTextareaInput();
    showToast(`Đã tự chia thành ${clipCount} phân cảnh 10s liền mạch (Tổng ~${clipCount * 10} giây) và bật chế độ Chuỗi Video Dài!`, 'success');
}

// ==================== CHUYỂN TIẾP 1 CHẠM: ẢNH -> VIDEO ====================
function animateImageItemToVideo(item) {
    if (!item || !item.output_file_path) return;
    const fpath = item.output_file_path;
    const parts = fpath.replace(/\\/g, '/').split('/');
    const fname = parts[parts.length - 1] || 'image.png';
    const stem = fname.replace(/\.[^/.]+$/, '');

    closeMediaPlayerModal();
    switchTab('studio');
    setTaskType('img2vid');
    setAspectRatio(item.aspect_ratio || '16:9');
    setRefMode('shared');

    state.refImages = [{ path: fpath, name: fname, stem: stem }];
    renderRefImagesChips();

    const ta = document.getElementById('studio-prompt-textarea');
    if (ta) {
        if (!ta.value.trim()) {
            ta.value = item.prompt_text || 'Animate this scene with smooth cinematic camera motion and natural movement';
        }
        onPromptTextareaInput();
        ta.focus();
    }
    showToast(`Đã nạp ảnh "${fname}" vào chế độ Ảnh → Video!`, 'success');
}

function studioAnimateToVideo(taskId) {
    const item = state.tasks.find(t => t.id === taskId);
    if (!item) return;
    animateImageItemToVideo(item);
}

function galleryAnimateToVideo(taskId) {
    const item = state.galleryItems.find(x => x.id === taskId);
    if (!item) return;
    animateImageItemToVideo(item);
}

function playerAnimateToVideo() {
    if (!state.activePlayerItem) return;
    animateImageItemToVideo(state.activePlayerItem);
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

function updateGallerySelectedBadge() {
    const el = document.getElementById('gallery-selected-badge');
    if (el) {
        el.textContent = `${state.selectedGalleryIds.size} đã chọn`;
    }
}

function toggleGallerySelect(taskId, ev) {
    if (ev) ev.stopPropagation();
    if (state.selectedGalleryIds.has(taskId)) {
        state.selectedGalleryIds.delete(taskId);
    } else {
        state.selectedGalleryIds.add(taskId);
    }
    updateGallerySelectedBadge();
    renderGalleryGrid();
}

function toggleSelectAllGallery() {
    const allIds = state.galleryItems.map(x => x.id);
    if (allIds.length > 0 && allIds.every(id => state.selectedGalleryIds.has(id))) {
        state.selectedGalleryIds.clear();
    } else {
        allIds.forEach(id => state.selectedGalleryIds.add(id));
    }
    updateGallerySelectedBadge();
    renderGalleryGrid();
}

async function batchStitchGallerySelected() {
    const ids = Array.from(state.selectedGalleryIds);
    if (ids.length < 2) {
        showToast('Hãy tích chọn ít nhất 2 video clip trong Thư viện theo thứ tự muốn ghép!', 'warning');
        return;
    }
    showToast(`Đang ghép nối ${ids.length} clip thành 1 Video dài bằng FFmpeg...`, 'info');
    try {
        const res = await fetch('/api/gallery/stitch-videos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: ids })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast(`Đã ghép thành công ${data.clips_count} clip thành Video dài (~${data.estimated_duration_sec}s - ${data.file_size_mb} MB)!`, 'success');
            await loadGallery();
            await refreshStudioState(true);
            if (data.task_id) {
                openGalleryMedia(data.task_id);
            }
        } else {
            showToast(data.detail || 'Không thể ghép video', 'error');
        }
    } catch (e) {
        showToast('Lỗi khi ghép video bằng FFmpeg', 'error');
    }
}

async function batchExportGallerySelected() {
    const ids = Array.from(state.selectedGalleryIds);
    if (ids.length === 0) {
        showToast('Hãy tích chọn ít nhất 1 media trong Thư viện để xuất ra thư mục!', 'warning');
        return;
    }
    showToast('Đang mở hộp thoại chọn thư mục đích trên Windows...', 'info');
    try {
        const res = await fetch('/api/gallery/batch-export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: ids })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast(`Đã copy ${data.copied_count} file sang: ${data.target_folder}`, 'success');
        } else if (!data.cancelled) {
            showToast(data.detail || data.message || 'Không thể copy file', 'warning');
        }
    } catch (e) {
        showToast('Lỗi khi xuất file hàng loạt', 'error');
    }
}

async function batchDeleteGallerySelected() {
    const ids = Array.from(state.selectedGalleryIds);
    if (ids.length === 0) {
        showToast('Hãy tích chọn ít nhất 1 media trong Thư viện để xóa!', 'warning');
        return;
    }
    if (!confirm(`Bạn có chắc muốn xóa ${ids.length} media đã chọn và xóa luôn file gốc trên ổ đĩa?`)) return;
    try {
        const res = await fetch('/api/gallery/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: ids, delete_disk_file: true })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            state.selectedGalleryIds.clear();
            updateGallerySelectedBadge();
            showToast(`Đã xóa ${data.deleted} media khỏi Thư viện và ổ đĩa!`, 'info');
            await loadGallery();
            await refreshStudioState(true);
        }
    } catch (e) {
        showToast('Lỗi khi xóa hàng loạt', 'error');
    }
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

    const validIds = new Set(state.galleryItems.map(x => x.id));
    for (const id of Array.from(state.selectedGalleryIds)) {
        if (!validIds.has(id)) state.selectedGalleryIds.delete(id);
    }
    updateGallerySelectedBadge();

    document.getElementById('gallery-total-count').textContent = `${state.galleryItems.length} media`;
    renderGalleryGrid();
}

function renderGalleryGrid() {
    const grid = document.getElementById('gallery-grid-container');
    if (!grid) return;

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
        const isSelected = state.selectedGalleryIds.has(item.id);
        const previewHtml = isImg
            ? `<img src="${streamUrl}" class="w-full h-44 object-cover group-hover:scale-105 transition duration-300" loading="lazy" />`
            : `<video src="${streamUrl}" muted loop onmouseover="this.play()" onmouseout="this.pause()" class="w-full h-44 object-cover"></video>`;

        const durTag = item.duration_sec > 0 ? ` · ⏱ ${item.duration_sec}s` : '';

        return `
            <div onclick="openGalleryItemModal(${item.id})" class="group cursor-pointer bg-museCard border ${isSelected ? 'border-indigo-500 ring-2 ring-indigo-500/40' : 'border-museBorder hover:border-indigo-500/60'} rounded-xl overflow-hidden shadow-lg flex flex-col transition">
                <div class="relative bg-black h-44 overflow-hidden">
                    ${previewHtml}
                    <span class="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-black/70 text-[10px] font-bold text-white uppercase">
                        ${isImg ? 'Ảnh (IMG)' : 'Video (VIDEO)'} · ${escapeHtml(item.aspect_ratio)}${durTag}
                    </span>
                    <div onclick="toggleGallerySelect(${item.id}, event)" class="absolute top-2 right-2 w-6 h-6 rounded-md bg-black/70 hover:bg-black flex items-center justify-center border border-white/20">
                        <input type="checkbox" ${isSelected ? 'checked' : ''} class="rounded accent-indigo-500 pointer-events-none" />
                    </div>
                    <span class="absolute bottom-2 right-2 px-2 py-0.5 rounded-md bg-black/70 text-[10px] font-mono text-emerald-300">
                        ${item.file_size_mb || 0} MB
                    </span>
                    ${isImg ? `
                    <button onclick="event.stopPropagation(); galleryAnimateToVideo(${item.id})" title="Biến bức ảnh này thành Video chuyển động (Ảnh → Video)" class="absolute bottom-2 left-2 px-2 py-0.5 rounded-md bg-violet-600/90 hover:bg-violet-500 text-[10px] font-bold text-white flex items-center gap-1 shadow transition">
                        <i class="fa-solid fa-clapperboard"></i>
                        <span>Tạo Video</span>
                    </button>
                    ` : ''}
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
                        <div class="grid grid-cols-3 gap-1.5">
                            <button onclick="event.stopPropagation(); galleryQuickOpenFile(${item.id})" class="py-1 px-2 rounded-md bg-museInput hover:bg-gray-800 border border-museBorder text-[11px] font-semibold text-gray-200 flex items-center justify-center gap-1 transition">
                                <i class="fa-solid fa-up-right-from-square text-sky-400 text-[10px]"></i>
                                <span>Mở file</span>
                            </button>
                            <button onclick="event.stopPropagation(); galleryQuickOpenFolder(${item.id})" class="py-1 px-2 rounded-md bg-museInput hover:bg-gray-800 border border-museBorder text-[11px] font-semibold text-gray-200 flex items-center justify-center gap-1 transition">
                                <i class="fa-solid fa-folder-open text-amber-400 text-[10px]"></i>
                                <span>Thư mục</span>
                            </button>
                            <button onclick="event.stopPropagation(); galleryQuickDelete(${item.id})" title="Xóa Media & File trên ổ đĩa" class="py-1 px-2 rounded-md bg-rose-500/15 hover:bg-rose-500/30 border border-rose-500/30 text-[11px] font-semibold text-rose-300 flex items-center justify-center gap-1 transition">
                                <i class="fa-solid fa-trash-can text-[10px]"></i>
                                <span>Xóa</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function galleryQuickDelete(taskId) {
    if (!confirm('Xóa media này khỏi Thư viện và xóa luôn file gốc trên ổ cứng?')) return;
    try {
        const res = await fetch(`/api/gallery/${taskId}/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_disk_file: true })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast('Đã xóa media và file trên ổ đĩa!', 'info');
            await loadGallery();
            await refreshStudioState(true);
        } else {
            showToast(data.detail || 'Không thể xóa media', 'error');
        }
    } catch (e) {
        showToast('Lỗi khi xóa media', 'error');
    }
}

async function playerDeleteMedia() {
    if (!state.activePlayerItem?.id) return;
    if (!confirm('Xóa media này khỏi Thư viện và xóa luôn file gốc trên ổ cứng?')) return;
    const taskId = state.activePlayerItem.id;
    closeMediaPlayerModal();
    try {
        const res = await fetch(`/api/gallery/${taskId}/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_disk_file: true })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast('Đã xóa media và file trên ổ đĩa!', 'info');
            await loadGallery();
            await refreshStudioState(true);
        } else {
            showToast(data.detail || 'Không thể xóa media', 'error');
        }
    } catch (e) {
        showToast('Lỗi khi xóa media', 'error');
    }
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

    const animateBtn = document.getElementById('btn-player-animate-video');
    if (animateBtn) {
        if (item.task_type === 'image' && item.output_file_path) {
            animateBtn.classList.remove('hidden');
        } else {
            animateBtn.classList.add('hidden');
        }
    }

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
function formatProxyOptionLabel(p) {
    const hostPort = (p.host && p.port) ? `${p.host}:${p.port}` : (p.raw_string || `Proxy #${p.id}`);
    const proto = (p.protocol || 'http').toUpperCase();
    const country = p.country_code ? ` · ${p.country_code}` : '';
    const st = p.status === 'Live' ? ` · Live${country}` : (p.status === 'Dead' ? ' · Dead' : '');
    const assigned = p.account_email ? ` (${p.account_email.split('@')[0]})` : '';
    return `${hostPort} [${proto}${st}]${assigned}`;
}

function populateAddAccountProxySelects() {
    const proxies = state.proxies || [];
    const optionsHtml = `<option value="0">— Không dùng proxy —</option>` + proxies.map(p =>
        `<option value="${p.id}">${escapeHtml(formatProxyOptionLabel(p))}</option>`
    ).join('');

    const singleSel = document.getElementById('new-acc-proxy-select');
    if (singleSel) {
        const curVal = singleSel.value || '0';
        singleSel.innerHTML = optionsHtml;
        if (proxies.some(p => String(p.id) === String(curVal))) {
            singleSel.value = curVal;
        }
    }
    const bulkSel = document.getElementById('new-acc-bulk-proxy-select');
    if (bulkSel) {
        const curBulkVal = bulkSel.value || '0';
        bulkSel.innerHTML = optionsHtml;
        if (proxies.some(p => String(p.id) === String(curBulkVal))) {
            bulkSel.value = curBulkVal;
        }
    }
}

async function changeAccountProxy(accId, proxyIdVal) {
    const parsedId = parseInt(proxyIdVal || '0', 10);
    await updateAccountField(accId, { proxy_id: parsedId });
    if (parsedId > 0) {
        const pObj = (state.proxies || []).find(x => x.id === parsedId);
        const pLabel = pObj ? `${pObj.host}:${pObj.port}` : `#${parsedId}`;
        showToast(`Đã gán Proxy ${pLabel} cho tài khoản #${accId}`, 'success');
    } else {
        showToast(`Đã chuyển tài khoản #${accId} sang Không dùng proxy`, 'info');
    }
    await loadAccounts(true);
}

async function loadAccounts(isBackground = false) {
    try {
        const res = await fetch('/api/accounts');
        const data = await res.json();
        state.accounts = data.accounts || [];
        if (Array.isArray(data.proxies)) {
            state.proxies = data.proxies;
            populateAddAccountProxySelects();
        }

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

        const proxiesList = state.proxies || [];

        tbody.innerHTML = state.accounts.map(acc => {
            const cookieBadge = acc.cookie_status === 'Cookie tốt'
                ? `<span class="px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold inline-flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>Cookie tốt</span>`
                : acc.cookie_status === 'Hết hạn'
                    ? `<span class="px-2.5 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30 text-[11px] font-semibold">Hết hạn</span>`
                    : `<span class="px-2.5 py-0.5 rounded-full bg-gray-700/60 text-gray-300 text-[11px]">Chưa có</span>`;

            const curProxyId = acc.proxy_id ? parseInt(acc.proxy_id, 10) : 0;
            const proxySelectOptions = `<option value="0" ${curProxyId === 0 ? 'selected' : ''}>— Không dùng proxy —</option>` +
                proxiesList.map(p => {
                    const isSel = curProxyId === p.id ? 'selected' : '';
                    const hostPort = (p.host && p.port) ? `${p.host}:${p.port}` : (p.raw_string || `Proxy #${p.id}`);
                    const proto = (p.protocol || 'http').toUpperCase();
                    const st = p.status === 'Live' ? ' · Live' : (p.status === 'Dead' ? ' · Dead' : '');
                    return `<option value="${p.id}" ${isSel}>${escapeHtml(`${hostPort} (${proto}${st})`)}</option>`;
                }).join('');

            const proxyDropdownHtml = `
                <select
                    onchange="changeAccountProxy(${acc.id}, this.value)"
                    class="bg-museInput border ${curProxyId > 0 ? 'border-amber-500/40 text-amber-200' : 'border-museBorder text-gray-300'} hover:border-indigo-500/50 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-emerald-400 max-w-[215px] w-full truncate cursor-pointer transition"
                >
                    ${proxySelectOptions}
                </select>
            `;

            return `
                <tr class="studio-row">
                    <td class="py-3 px-3 text-center">
                        <input type="checkbox" ${acc.is_enabled ? 'checked' : ''} onchange="updateAccountField(${acc.id}, {is_enabled: this.checked ? 1 : 0})" class="rounded accent-indigo-500 cursor-pointer" />
                    </td>
                    <td class="py-3 px-3">
                        <div class="font-bold text-white">${escapeHtml(acc.display_name || '')}</div>
                        <div class="text-gray-400 text-[11px] font-mono">${escapeHtml(acc.email)}</div>
                    </td>
                    <td class="py-3 px-2 text-center">
                        <input type="number" min="0" max="20" title="Nhập 0 nếu không muốn tài khoản này chạy tạo Ảnh" value="${acc.image_threads ?? 5}" onchange="updateAccountField(${acc.id}, {image_threads: Math.max(0, parseInt(this.value || '0', 10))})" class="w-14 bg-museInput border border-museBorder rounded-md py-1 text-center text-white" />
                    </td>
                    <td class="py-3 px-2 text-center">
                        <input type="number" min="0" max="20" title="Nhập 0 nếu tài khoản này không tạo được Video (hệ thống sẽ tự động đẩy toàn bộ Video sang tài khoản khác)" value="${acc.video_threads ?? 5}" onchange="updateAccountField(${acc.id}, {video_threads: Math.max(0, parseInt(this.value || '0', 10))})" class="w-14 bg-museInput border border-museBorder rounded-md py-1 text-center text-white" />
                    </td>
                    <td class="py-3 px-3">
                        ${proxyDropdownHtml}
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
                            <button onclick="clearAccountVideoMemory(${acc.id})" title="Xóa bộ nhớ chặn tạo Video theo vùng (Region-Block Memory) trên tài khoản này" class="px-2 py-1 rounded-lg bg-violet-500/15 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-[11px] font-semibold transition">
                                Fix Video
                            </button>
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

async function clearAccountVideoMemory(accId) {
    showToast('Đang xóa bộ nhớ Region-Block Video trên Muse.ai...', 'info');
    try {
        const res = await fetch(`/api/accounts/${accId}/clear-memory`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.ok) {
            showToast(data.message || 'Đã xóa bộ nhớ chặn tạo Video thành công!', 'success');
        } else {
            showToast(data.message || data.detail || 'Không thể xóa bộ nhớ tài khoản', 'warning');
        }
    } catch (e) {
        showToast('Lỗi kết nối khi xóa bộ nhớ tài khoản', 'error');
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

async function openAddAccountModal() {
    try {
        const res = await fetch('/api/proxies');
        const data = await res.json();
        if (data && Array.isArray(data.proxies)) {
            state.proxies = data.proxies;
        }
    } catch (e) {}
    populateAddAccountProxySelects();
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
    const profWrap = document.getElementById('add-acc-profile-wrap');

    if (mode === 'single') {
        singleBtn.className = 'py-2 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 transition';
        bulkBtn.className = 'py-2 rounded-lg text-gray-400 hover:text-white transition';
        singleForm.classList.remove('hidden');
        bulkForm.classList.add('hidden');
        if (profWrap) profWrap.classList.remove('hidden');
    } else {
        bulkBtn.className = 'py-2 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 transition';
        singleBtn.className = 'py-2 rounded-lg text-gray-400 hover:text-white transition';
        bulkForm.classList.remove('hidden');
        singleForm.classList.add('hidden');
        if (profWrap) profWrap.classList.add('hidden');
    }
}

async function submitAddAccount() {
    const image_threads = parseInt(document.getElementById('new-acc-img-threads').value || '5', 10);
    const video_threads = parseInt(document.getElementById('new-acc-vid-threads').value || '5', 10);

    let payload = { image_threads, video_threads };
    if (state.addAccountMode === 'bulk') {
        payload.bulk_text = document.getElementById('new-acc-bulk-text').value;
        const bulkProxyId = parseInt(document.getElementById('new-acc-bulk-proxy-select')?.value || '0', 10);
        if (bulkProxyId > 0) {
            payload.proxy_id = bulkProxyId;
        }
    } else {
        payload.display_name = document.getElementById('new-acc-name').value;
        payload.email = document.getElementById('new-acc-email').value;
        payload.password = document.getElementById('new-acc-pass').value;
        const singleProxyId = parseInt(document.getElementById('new-acc-proxy-select')?.value || '0', 10);
        if (singleProxyId > 0) {
            payload.proxy_id = singleProxyId;
        }
        const customProf = document.getElementById('new-acc-profile-path')?.value;
        if (customProf && customProf.trim()) {
            payload.custom_profile_path = customProf.trim();
        }
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
    if (document.getElementById('new-acc-profile-path')) {
        document.getElementById('new-acc-profile-path').value = '';
    }
    if (document.getElementById('new-acc-proxy-select')) {
        document.getElementById('new-acc-proxy-select').value = '0';
    }
    if (document.getElementById('new-acc-bulk-proxy-select')) {
        document.getElementById('new-acc-bulk-proxy-select').value = '0';
    }
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
    populateAddAccountProxySelects();
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
        const countryTag = p.country_code ? ` · ${escapeHtml(p.country_code)}` : '';
        const statusBadge = p.status === 'Live'
            ? `<span class="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold">Live${countryTag}</span>`
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
    const retryEl = document.getElementById('set-auto-retry');
    if (retryEl) retryEl.value = s.auto_retry_count || '1';
    const sleepEl = document.getElementById('set-idle-sleep');
    if (sleepEl) sleepEl.value = s.browser_idle_sleep_sec || '180';
    document.getElementById('set-auto-approve').checked = s.auto_approve === '1';
    document.getElementById('set-offscreen-mode').checked = s.offscreen_mode === '1';
    const groupEl = document.getElementById('set-group-by-project');
    if (groupEl) groupEl.checked = s.group_output_by_project === '1';

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
        auto_retry_count: document.getElementById('set-auto-retry')?.value || '1',
        browser_idle_sleep_sec: document.getElementById('set-idle-sleep')?.value || '180',
        auto_approve: document.getElementById('set-auto-approve').checked ? '1' : '0',
        offscreen_mode: document.getElementById('set-offscreen-mode').checked ? '1' : '0',
        group_output_by_project: document.getElementById('set-group-by-project')?.checked ? '1' : '0',
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
