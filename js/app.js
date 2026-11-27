let paintings = [];
let filteredPaintings = [];
let selectedIndex = null;
const descriptionsByPrefix = {}; // Descriptions currently shown in the detail pane / viewer

const PAINTINGS_DIR = 'paintings/';
const LIBRARY_URL = 'api/paintings.php';

function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function baseName(path) {
    return String(path || '').split(/[\\/]/).pop();
}

// Stable key of a painting (library id; file name for entries without id)
function paintingKey(painting) {
    return painting.id || baseName(painting.file_path || painting.original_filename);
}

// file_path is relative to paintings/; legacy absolute paths fall back to the file name
function imageUrl(painting) {
    let path = String(painting.file_path || painting.original_filename || '').replace(/\\/g, '/');
    if (/^([a-z]:|\/)/i.test(path)) path = path.split('/').pop();
    if (!path) return '';
    const version = painting.file_size ? `?v=${painting.file_size}` : '';
    return PAINTINGS_DIR + path.split('/').map(encodeURIComponent).join('/') + version;
}

// ===================== Account (own SQLite DB on the NAS) =====================
let account = { user: null, seen: new Set(), favorites: new Set() };

async function api(url, body) {
    const options = body === undefined
        ? { cache: 'no-store' }
        : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Cuadros': '1' }, body: JSON.stringify(body) };
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
    return data;
}

// ===================== Theme (light/dark) =====================
function applyTheme(theme) {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('theme', theme);
    const toggle = document.getElementById('themeToggle');
    toggle.setAttribute('aria-pressed', theme === 'dark');
    toggle.title = theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
}

function toggleTheme() {
    const theme = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
    applyTheme(theme);
    // Logged-in users keep their choice on every device
    if (account.user) api('api/account.php', { action: 'set_theme', theme }).catch(() => {});
}

applyTheme(document.documentElement.classList.contains('dark') ? 'dark' : 'light');

function setAccount(data) {
    if (data.user && data.user.theme) applyTheme(data.user.theme);
    account = { user: data.user, seen: new Set(data.seen || []), favorites: new Set(data.favorites || []) };
    document.body.classList.toggle('logged-in', !!account.user);
    document.body.classList.toggle('is-admin', !!(account.user && account.user.is_admin));
    document.body.classList.toggle('can-upload', !!(account.user && account.user.can_upload));
    renderAccountArea();
}

async function fetchAccount() {
    try {
        setAccount(await api('api/account.php'));
    } catch (error) {
        console.warn('No se pudo cargar la cuenta', error);
        setAccount({ user: null });
    }
}

function renderAccountArea() {
    const area = document.getElementById('accountArea');
    if (!account.user) {
        area.innerHTML = `<button class="account-btn" onclick="openAuth('login')">👤 Entrar</button>`;
        return;
    }
    area.innerHTML = `
        <div class="account-menu">
            <button class="account-btn" onclick="toggleAccountMenu(event)">👤 ${esc(account.user.username)} ▾</button>
            <div class="account-dropdown" id="accountDropdown">
                <div class="account-info">❤️ ${account.favorites.size} favoritos · 👁️ ${account.seen.size} vistos${account.user.is_admin ? '<br>🛠️ Superusuario' : ''}</div>
                ${account.user.is_admin ? '<button onclick="openUsers()">👥 Usuarios</button><button onclick="openAiSettings()">🤖 IA de procesado</button>' : ''}
                <button onclick="openAuth('change')">🔑 Cambiar contraseña</button>
                <button onclick="logout()">🚪 Cerrar sesión</button>
            </div>
        </div>
    `;
}

function toggleAccountMenu(event) {
    event.stopPropagation();
    document.getElementById('accountDropdown').classList.toggle('open');
}

document.addEventListener('click', () => {
    const dropdown = document.getElementById('accountDropdown');
    if (dropdown) dropdown.classList.remove('open');
});

// Re-render everything that depends on the account (marks, filters, list, open panels)
function refreshAccountUI() {
    applyFilters();
    if (selectedIndex === null) {
        const savedKey = localStorage.getItem('selectedPaintingPath');
        const index = paintings.findIndex(p => paintingKey(p) === savedKey || baseName(p.file_path) === baseName(savedKey));
        if (index !== -1 && !isMobileLayout()) {
            selectedIndex = index;
            renderList();
        }
    }
    if (selectedIndex !== null) renderDetail(paintings[selectedIndex]);
    if (viewerIndex !== null) {
        const panel = document.getElementById('viewerPanel');
        const scroll = panel.scrollTop;
        panel.innerHTML = viewerPanelHtml(paintings[viewerIndex]);
        panel.scrollTop = scroll;
    }
}

// Before accounts existed, "seen" was stored in this browser keyed by file path: import it once
async function importLegacySeen() {
    const legacy = JSON.parse(localStorage.getItem('seenLivePaintings') || '{}');
    const ids = Object.entries(legacy)
        .filter(([, value]) => value)
        .map(([path]) => paintings.find(p => baseName(p.file_path) === baseName(path)))
        .filter(Boolean)
        .map(p => p.id)
        .filter(id => id && !account.seen.has(id));
    if (ids.length) {
        await api('api/marks.php', { type: 'seen', ids, value: true });
        ids.forEach(id => account.seen.add(id));
        showToast(`👁️ ${ids.length} cuadro${ids.length !== 1 ? 's' : ''} visto${ids.length !== 1 ? 's' : ''} importado${ids.length !== 1 ? 's' : ''} de este navegador`);
    }
    localStorage.removeItem('seenLivePaintings');
}

let authMode = 'login';

function openAuth(mode) {
    authMode = mode;
    const titles = { login: '👤 Iniciar sesión', register: '✨ Crear cuenta', change: '🔑 Cambiar contraseña' };
    const submits = { login: 'Entrar', register: 'Crear cuenta', change: 'Guardar' };
    document.getElementById('authTitle').textContent = titles[mode];
    document.getElementById('authSubmit').textContent = submits[mode];
    document.getElementById('authError').textContent = '';
    const show = (id, visible) => { document.getElementById(id).style.display = visible ? '' : 'none'; };
    show('authUsername', mode !== 'change');
    show('authCurrentPassword', mode === 'change');
    show('authPassword2', mode !== 'login');
    const password = document.getElementById('authPassword');
    password.placeholder = mode === 'change' ? 'Nueva contraseña' : 'Contraseña';
    password.autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    document.getElementById('authSwitch').innerHTML = {
        login: '¿No tienes cuenta? <a onclick="openAuth(\'register\')">Regístrate</a>',
        register: '¿Ya tienes cuenta? <a onclick="openAuth(\'login\')">Inicia sesión</a>',
        change: ''
    }[mode];
    ['authCurrentPassword', 'authPassword', 'authPassword2'].forEach(id => { document.getElementById(id).value = ''; });
    document.getElementById('authModal').classList.add('open');
    document.getElementById(mode === 'change' ? 'authCurrentPassword' : 'authUsername').focus();
}

function closeAuth() {
    document.getElementById('authModal').classList.remove('open');
}

document.getElementById('authModal').addEventListener('click', (e) => {
    if (e.target.id === 'authModal') closeAuth();
});

document.getElementById('authForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('authUsername').value.trim();
    const password = document.getElementById('authPassword').value;
    const errorEl = document.getElementById('authError');
    if (authMode !== 'login' && password !== document.getElementById('authPassword2').value) {
        errorEl.textContent = 'Las contraseñas no coinciden';
        return;
    }
    const submit = document.getElementById('authSubmit');
    submit.disabled = true;
    errorEl.textContent = '';
    try {
        if (authMode === 'change') {
            await api('api/account.php', {
                action: 'change_password',
                current_password: document.getElementById('authCurrentPassword').value,
                password
            });
            closeAuth();
            showToast('🔑 Contraseña actualizada');
            return;
        }
        setAccount(await api('api/account.php', { action: authMode, username, password }));
        closeAuth();
        try {
            await importLegacySeen();
        } catch (error) {
            console.warn('No se pudieron importar los vistos', error);
        }
        renderAccountArea();
        await fetchCollections();
        refreshAccountUI();
        showToast(authMode === 'register' ? `✨ ¡Bienvenido/a, ${account.user.username}!` : `👋 Hola, ${account.user.username}`);
    } catch (error) {
        errorEl.textContent = error.message;
    } finally {
        submit.disabled = false;
    }
});

async function logout() {
    try {
        setAccount(await api('api/account.php', { action: 'logout' }));
    } catch (error) {
        showToast('⚠ ' + error.message);
        return;
    }
    closeUpload();
    myCollections = [];
    if (activeCollection && activeCollection.mine) await setActiveCollection('', { quiet: true, apply: false });
    renderCollectionBar();
    refreshAccountUI();
    showToast('Sesión cerrada');
}

// ===================== Marks: seen / favorite =====================
function getSeenLiveStatus(key) {
    return account.seen.has(key);
}

function isFavorite(key) {
    return account.favorites.has(key);
}

function markButtonsHtml(painting, prefix) {
    const key = paintingKey(painting);
    const seen = getSeenLiveStatus(key);
    const fav = isFavorite(key);
    return `
        <div class="mark-actions">
            <button class="icon-btn seen auth-only${seen ? ' on' : ''}" data-mark="seen" data-key="${esc(key)}" data-tip="¡Esta la he visto!" aria-label="Marcar como visto en vivo" aria-pressed="${seen}" onclick="toggleMark('seen', this.dataset.key)"><span>👁️</span></button>
            <button class="icon-btn fav auth-only${fav ? ' on' : ''}" data-mark="favorite" data-key="${esc(key)}" data-tip="${fav ? 'Quitar de favoritos' : 'Añadir a favoritos'}" aria-label="Favorito" aria-pressed="${fav}" onclick="toggleMark('favorite', this.dataset.key)"><span>❤️</span></button>
            <button class="icon-btn coll auth-only${customCollections().some(c => c.painting_ids.includes(key)) ? ' on' : ''}" data-key="${esc(key)}" data-tip="Añadir a colección" aria-label="Añadir a colección" onclick="openCollectionMenu(this)"><span>📁</span></button>
            <button class="icon-btn share on" data-key="${esc(key)}" data-tip="Copiar enlace" aria-label="Compartir" onclick="sharePainting(this.dataset.key, '${prefix}')"><span>🔗</span></button>
            <button class="icon-btn edit admin-only on" data-key="${esc(key)}" data-tip="Editar" aria-label="Editar cuadro" onclick="openEdit(this.dataset.key)"><span>✏️</span></button>
        </div>
    `;
}

function syncMarkButtons(type, key) {
    const on = type === 'seen' ? getSeenLiveStatus(key) : isFavorite(key);
    document.querySelectorAll(`.icon-btn[data-mark="${type}"]`).forEach(btn => {
        if (btn.dataset.key !== key) return;
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-pressed', on);
        if (type === 'favorite') btn.dataset.tip = on ? 'Quitar de favoritos' : 'Añadir a favoritos';
    });
}

async function toggleMark(type, key) {
    if (!account.user) {
        openAuth('login');
        return;
    }
    const set = type === 'seen' ? account.seen : account.favorites;
    const value = !set.has(key);
    const apply = (on) => {
        if (on) set.add(key); else set.delete(key);
        syncMarkButtons(type, key);
        if (type === 'favorite') syncFavoritesCollection(key, on);
        renderList();
        renderAccountArea();
    };
    apply(value); // optimistic
    if (matchMedia('(hover: none)').matches) {
        showToast(type === 'seen'
            ? (value ? '👁️ Marcado como visto' : 'Desmarcado como visto')
            : (value ? '❤️ Añadido a favoritos' : 'Quitado de favoritos'));
    }
    try {
        await api('api/marks.php', { type, id: key, value });
    } catch (error) {
        apply(!value);
        showToast('⚠ No se pudo guardar: ' + error.message);
    }
}

// ===================== Share =====================
function shareUrl(key, descIndex) {
    const url = new URL(location.pathname, location.origin);
    url.searchParams.set('cuadro', key);
    if (descIndex > 0) url.searchParams.set('desc', descIndex);
    return url.toString();
}

async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (error) { /* fall back below */ }
    }
    // http:// (not a secure context) has no Clipboard API
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
    textarea.remove();
    return ok;
}

async function sharePainting(key, prefix) {
    const selector = document.getElementById(prefix + 'DescSelector');
    const url = shareUrl(key, selector ? parseInt(selector.value) || 0 : 0);
    if (await copyText(url)) {
        showToast('🔗 Enlace copiado al portapapeles');
    } else {
        window.prompt('Copia el enlace:', url);
    }
}

// Open the painting (and description) requested by a shared link: ?cuadro=<id>&desc=<n>
function openFromUrl() {
    const params = new URLSearchParams(location.search);
    const key = params.get('cuadro');
    if (!key) return false;
    history.replaceState(null, '', location.pathname);
    const index = paintings.findIndex(p => paintingKey(p) === key);
    if (index === -1) {
        showToast('⚠ No se encontró el cuadro del enlace');
        return false;
    }
    selectPainting(index, { openViewer: isMobileLayout() });
    const desc = parseInt(params.get('desc')) || 0;
    if (desc > 0) {
        ['detail', 'viewer'].forEach(prefix => {
            const selector = document.getElementById(prefix + 'DescSelector');
            if (selector && selector.options[desc]) {
                selector.value = String(desc);
                changeDescription(prefix);
            }
        });
    }
    return true;
}

let toastTimer = null;
function showToast(text) {
    const toast = document.getElementById('toast');
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

let filters = {
    search: '',
    yearFrom: null,
    yearTo: null,
    orientation: 'all',
    confirmed: 'all',
    seenLive: 'all',
    favorite: 'all',
    period: 'all',
    theme: 'all',
    review: 'all',
    confidenceMin: 0,
    confidenceMax: 100,
    sortBy: 'updated-desc'
};

let collapseTimer = null;

// Auto-collapse filters panel after a delay
function autoCollapseFilters() {
    if (collapseTimer) {
        clearTimeout(collapseTimer);
    }
    collapseTimer = setTimeout(() => {
        const filtersPanel = document.getElementById('advancedFilters');
        const btn = document.querySelector('.collapse-btn');
        if (filtersPanel && !filtersPanel.classList.contains('collapsed')) {
            filtersPanel.classList.add('collapsed');
            btn.classList.add('collapsed');
        }
    }, 200);
}

// Load filters from localStorage
function loadFiltersFromStorage() {
    const saved = localStorage.getItem('paintingFilters');
    if (saved) {
        try {
            const savedFilters = JSON.parse(saved);
            filters = { ...filters, ...savedFilters };
            
            // Restore UI elements
            document.getElementById('searchInput').value = filters.search || '';
            document.getElementById('yearFrom').value = filters.yearFrom || '';
            document.getElementById('yearTo').value = filters.yearTo || '';
            document.getElementById('sortBy').value = filters.sortBy || 'none';
            
            // Restore orientation buttons
            document.querySelectorAll('.orientation-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.orientation === filters.orientation);
            });
            
            // Restore confirmed buttons
            document.querySelectorAll('[data-confirmed]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.confirmed === filters.confirmed);
            });
            
            // Restore seen live buttons
            document.querySelectorAll('[data-seen-live]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.seenLive === filters.seenLive);
            });
            
            // Restore favorite buttons
            document.querySelectorAll('[data-favorite]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.favorite === filters.favorite);
            });
            
            document.querySelectorAll('[data-review]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.review === (filters.review || 'all'));
            });
            
            // Restore period/theme selects (options exist already: fetchLibrary fills them)
            ['period', 'theme'].forEach(kind => {
                const select = document.getElementById(kind + 'Filter');
                if (!select.querySelector(`option[value="${CSS.escape(filters[kind] || 'all')}"]`)) filters[kind] = 'all';
                select.value = filters[kind] || 'all';
            });
            
            // Restore confidence slider
            if (filters.confidenceMin !== undefined && filters.confidenceMax !== undefined) {
                document.getElementById('confidenceMin').value = filters.confidenceMin;
                document.getElementById('confidenceMax').value = filters.confidenceMax;
                updateConfidenceSlider();
            }
        } catch (e) {
            console.warn('Could not load saved filters:', e);
        }
    }
}

// Save filters to localStorage
function saveFiltersToStorage() {
    localStorage.setItem('paintingFilters', JSON.stringify(filters));
}

// Save selected painting to localStorage
function saveSelectedPainting(index) {
    if (index !== null && paintings[index]) {
        localStorage.setItem('selectedPaintingPath', paintingKey(paintings[index]));
    } else {
        localStorage.removeItem('selectedPaintingPath');
    }
}

// Load and restore selected painting (desktop only: on mobile the list is the home screen)
function loadSelectedPainting() {
    const savedKey = localStorage.getItem('selectedPaintingPath');
    if (savedKey && !isMobileLayout()) {
        const index = paintings.findIndex(p => paintingKey(p) === savedKey || baseName(p.file_path) === baseName(savedKey));
        if (index !== -1) {
            selectPainting(index);
        }
    }
}

function isMobileLayout() {
    return window.innerWidth <= 768;
}

async function fetchLibrary() {
    const response = await fetch(LIBRARY_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error('No se pudo cargar la biblioteca');
    const data = await response.json();
    paintings = data.paintings || [];
    populateTagFilters();
    updateTotalCount();
}

// Load library
async function loadLibrary() {
    try {
        await Promise.all([fetchLibrary(), fetchAccount()]);
        await fetchCollections();
        const sharedCollection = new URLSearchParams(location.search).get('coleccion');
        await setActiveCollection(sharedCollection || localStorage.getItem('activeCollection') || '', { quiet: true, apply: false });
        if (sharedCollection && !new URLSearchParams(location.search).get('cuadro')) history.replaceState(null, '', location.pathname);
        
        // Load saved filters and apply them
        loadFiltersFromStorage();
        filteredPaintings = [...paintings];
        applyFilters();
        
        // A shared link wins over the last selected painting
        if (!openFromUrl()) loadSelectedPainting();
    } catch (error) {
        document.getElementById('paintingList').innerHTML = 
            `<li class="error">Error al cargar: ${esc(error.message)}</li>`;
    }
}

// Reload the library (e.g. after an upload) keeping the current selection and viewer
async function refreshLibrary() {
    const selectedKey = selectedIndex !== null && paintings[selectedIndex] ? paintingKey(paintings[selectedIndex]) : null;
    const viewerKey = viewerIndex !== null && paintings[viewerIndex] ? paintingKey(paintings[viewerIndex]) : null;
    await fetchLibrary();
    applyFilters();
    if (selectedKey) {
        const index = paintings.findIndex(p => paintingKey(p) === selectedKey);
        if (index !== -1) {
            selectedIndex = index;
            renderList();
        }
    }
    if (viewerKey) {
        viewerIndex = paintings.findIndex(p => paintingKey(p) === viewerKey);
        if (viewerIndex === -1) viewerIndex = null;
    }
}

// Render painting list
function renderList() {
    const listEl = document.getElementById('paintingList');
    
    if (filteredPaintings.length === 0) {
        listEl.innerHTML = '<li class="empty-state" style="padding: 30px; text-align: center;">No se encontraron resultados</li>';
        return;
    }

    listEl.innerHTML = filteredPaintings.map((painting, index) => {
        // Check if painting has any descriptions
        const hasDescription = painting.descriptions && 
                               Object.values(painting.descriptions).some(arr => arr && arr.length > 0);
        const noDescClass = hasDescription ? '' : ' no-description';
        
        // Check if painting has been seen live
        const seenLiveClass = getSeenLiveStatus(paintingKey(painting)) ? ' seen-live' : '';
        
        // Get the painting's index in the original paintings array
        const paintingIndex = paintings.indexOf(painting);
        
        return `
            <li class="painting-item ${paintingIndex === selectedIndex ? 'active' : ''}${noDescClass}${seenLiveClass}${painting.status === 'pending' ? ' pending' : ''}" 
                onclick="selectPainting(${paintingIndex}, { openViewer: isMobileLayout() })">
                <div class="painting-item-title">${painting.status === 'pending' ? '<span title="Pendiente de revisión">⏳ </span>' : ''}${esc(painting.title || 'Sin título')}${isFavorite(paintingKey(painting)) ? '<span class="fav-mark" title="Favorito">❤️</span>' : ''}</div>
                <div class="painting-item-artist">${esc(painting.artist || 'Artista desconocido')}</div>
                <div class="painting-item-year">${esc(painting.year || 'Año desconocido')}</div>
            </li>
        `;
    }).join('');
}

// Select and display painting
function selectPainting(index, { openViewer: showViewer = false } = {}) {
    selectedIndex = index;
    renderList();
    renderDetail(paintings[index]);
    saveSelectedPainting(index);
    document.getElementById('detailView').scrollTop = 0;
    autoCollapseFilters();
    if (showViewer) openViewer(index);
}

const EMPTY_DETAIL_HTML = `
    <button class="close-button" id="closeButton" onclick="closeDetail()">&times;</button>
    <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <h2>Selecciona una pintura</h2>
        <p>Elige una obra de la lista para ver sus detalles</p>
    </div>
`;

// Close detail view and show empty state
function closeDetail() {
    const detailView = document.getElementById('detailView');
    detailView.classList.remove('has-content');
    detailView.scrollTop = 0;
    selectedIndex = null;
    saveSelectedPainting(null); // Clear from localStorage
    renderList();
    detailView.innerHTML = EMPTY_DETAIL_HTML;
}

// Descriptions of a painting (handles the old single-object and very old plain-text formats)
function getDescriptions(painting) {
    const toEntry = (desc, idx) => ({
        text: desc.description || '',
        date: desc.generated_at ? new Date(desc.generated_at).toLocaleString('es-ES') : 'Fecha desconocida',
        style: desc.description_style || 'Estilo no especificado',
        creator: desc.comment_creator || 'Creador no especificado',
        maxLength: desc.max_length || 'No especificada',
        index: idx
    });
    if (painting.descriptions) {
        const lang = Object.keys(painting.descriptions)[0];
        if (!lang) return [];
        const value = painting.descriptions[lang];
        return (Array.isArray(value) ? value : [value]).map(toEntry);
    }
    if (painting.description) return [toEntry({ description: painting.description }, 0)];
    return [];
}

function descriptionMetaHtml(desc) {
    return `<strong>ℹ️ Información:</strong> Generada el ${esc(desc.date)} • Creador: ${esc(desc.creator)} • Estilo: ${esc(desc.style)} • Longitud máxima: ${esc(desc.maxLength)}`;
}

// Header, badges, technical info and descriptions. `prefix` keeps element ids unique
// because the same painting can be shown in the detail pane and in the viewer at once.
function renderPaintingInfo(painting, prefix, compact) {
    const descriptions = getDescriptions(painting);
    descriptionsByPrefix[prefix] = descriptions;

    const confidence = painting.confidence_score || 0;
    let confidenceBadge = 'badge-confidence';
    let confidenceText = 'Alta';
    if (confidence < 0.5) {
        confidenceBadge += ' low';
        confidenceText = 'Baja';
    } else if (confidence < 0.8) {
        confidenceBadge += ' medium';
        confidenceText = 'Media';
    }

    const hasLocation = painting.location && painting.location !== 'Unknown' && painting.location !== 'Desconocido';
    const searchUrl = 'https://www.google.com/search?q=' + encodeURIComponent('"' + (painting.original_title || '') + '" "' + (painting.artist || '') + '"');
    const mapsUrl = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(painting.location || '');

    const technicalInfo = `
        <div class="info-section">
            <h3>🔍 Información Técnica</h3>
            <div class="info-grid">
                ${painting.file_width && painting.file_height ? `
                    <div class="info-item">
                        <div class="info-label">Dimensiones</div>
                        <div class="info-value">${esc(painting.file_width)} × ${esc(painting.file_height)} px</div>
                    </div>
                ` : ''}
                ${painting.file_size ? `
                    <div class="info-item">
                        <div class="info-label">Tamaño de archivo</div>
                        <div class="info-value">${(painting.file_size / 1024 / 1024).toFixed(2)} MB</div>
                    </div>
                ` : ''}
                ${painting.added_to_library ? `
                    <div class="info-item">
                        <div class="info-label">Agregado</div>
                        <div class="info-value">${new Date(painting.added_to_library).toLocaleDateString('es-ES')}</div>
                    </div>
                ` : ''}
                ${painting.updated_on_library ? `
                    <div class="info-item">
                        <div class="info-label">Actualizado</div>
                        <div class="info-value">${new Date(painting.updated_on_library).toLocaleDateString('es-ES')}</div>
                    </div>
                ` : ''}
            </div>
        </div>
    `;

    const descriptionSection = descriptions.length > 0 ? `
        <div class="description-section">
            <h3>📋 Descripción</h3>
            ${descriptions.length > 1 ? `
                <div class="description-selector">
                    <label for="${prefix}DescSelector">🔍 Selecciona una versión de la descripción (${descriptions.length} disponibles):</label>
                    <select id="${prefix}DescSelector" onchange="changeDescription('${prefix}')">
                        ${descriptions.map((desc, idx) => `
                            <option value="${idx}">
                                Versión ${idx + 1}: ${esc(desc.creator)}, Estilo: ${esc(desc.style)}, Longitud: ${esc(desc.maxLength)} (${esc(desc.date)})
                            </option>
                        `).join('')}
                    </select>
                </div>
            ` : ''}
            <div class="description-history" id="${prefix}DescriptionMeta">${descriptionMetaHtml(descriptions[0])}</div>
            <div id="${prefix}DescriptionText" class="description-text">${esc(descriptions[0].text)}</div>
        </div>
    ` : '';

    // Tags: format (always), then period(s), then theme(s)
    const FORMAT_LABELS = { landscape: 'horizontal', portrait: 'vertical', square: 'cuadrado' };
    const tagChips = [
        painting.orientation && FORMAT_LABELS[painting.orientation]
            ? `<span class="tag-chip tag-format" title="Formato">${FORMAT_LABELS[painting.orientation]}</span>` : '',
        ...(painting.periods || []).map(t => `<span class="tag-chip tag-period" title="Época">${esc(t)}</span>`),
        ...(painting.themes || []).map(t => `<span class="tag-chip tag-theme" title="Temática">${esc(t)}</span>`)
    ].join('');

    const pendingBanner = painting.status === 'pending' ? `
        <div class="pending-banner" data-key="${esc(paintingKey(painting))}">
            <span>⏳ <strong>Pendiente de revisión.</strong> La IA todavía no ha identificado este cuadro (o no pudo).
            Solo lo ven quienes pueden subir cuadros.</span>
            <button type="button" class="btn-small" onclick="reprocessPainting(this.closest('.pending-banner').dataset.key)">🔄 Reintentar con IA</button>
            <span class="pending-status"></span>
        </div>
    ` : '';

    return `
        ${pendingBanner}
        <div class="painting-header">
            ${painting.original_title && painting.original_title !== painting.title ? 
                `<div class="painting-original-title">Título original: <a href="${esc(searchUrl)}" target="_blank" rel="noopener noreferrer" class="search-link">${esc(painting.original_title)}</a></div>` : ''}
            <h2 class="painting-title">${esc(painting.title || 'Sin título')}</h2>
            <div class="painting-meta-row">
                <div class="painting-meta">
                    <span><strong>🎨 Artista:</strong> ${esc(painting.artist || 'Desconocido')}</span>
                    <span><strong>📆 Año:</strong> ${esc(painting.year || 'Desconocido')}</span>
                    ${hasLocation ? `<span><strong>🗺️ Ubicación:</strong> <a href="${esc(mapsUrl)}" target="_blank" rel="noopener noreferrer" class="search-link">${esc(painting.location)}</a></span>` : ''}
                </div>
                ${markButtonsHtml(painting, prefix)}
            </div>
        </div>
        ${descriptionSection}
        ${technicalInfo}
        ${tagChips ? `<div class="painting-tags">${tagChips}</div>` : ''}
        <div class="painting-badges">
            <span class="badge ${confidenceBadge}">Confianza: ${(confidence * 100).toFixed(0)}% (${confidenceText})</span>
            ${painting.info_data_source ? `<span class="badge badge-source">${esc(painting.info_data_source)}</span>` : ''}
            ${painting.confirmed ? `<span class="badge badge-confirmed">✔️ Confirmado</span>` : ''}
        </div>
    `;
}

// Render painting detail
function renderDetail(painting) {
    const detailView = document.getElementById('detailView');
    detailView.classList.add('has-content');
    const url = imageUrl(painting);
    const index = paintings.indexOf(painting);

    detailView.innerHTML = `
        <div class="detail-split">
            <div class="detail-stage">
                ${url ? `
                    <img src="${esc(url)}" alt="${esc(painting.title)}" draggable="false">
                    <div class="viewer-lens"></div>
                    <span class="detail-stage-hint">🔍 Pasa el ratón para ampliar ×2 · rueda para ajustar</span>
                ` : '<div class="empty-state">Sin imagen</div>'}
            </div>
            <aside class="detail-info">
                <button class="close-button" onclick="closeDetail()" aria-label="Cerrar">&times;</button>
                ${renderPaintingInfo(painting, 'detail', true)}
                ${url ? `<p style="margin-top: 20px;"><a href="${esc(url)}" target="_blank" rel="noopener" class="search-link">↗ Abrir imagen original</a></p>` : ''}
            </aside>
        </div>
    `;
    if (url) attachDetailLens(detailView.querySelector('.detail-stage'), url);
}

// Magnifying lens on the detail image (desktop): ×2 by default, wheel adjusts it
function attachDetailLens(stage, url) {
    const img = stage.querySelector('img');
    const lens = stage.querySelector('.viewer-lens');
    lens.style.backgroundImage = `url("${url}")`;
    const hide = () => {
        lens.style.display = 'none';
        stage.classList.remove('zooming');
    };
    const update = (e) => {
        const rect = img.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        if (!img.naturalWidth || x < 0 || y < 0 || x > rect.width || y > rect.height) {
            hide();
            return false;
        }
        lens.style.display = 'block';
        stage.classList.add('zooming');
        const size = lens.offsetWidth;
        const stageRect = stage.getBoundingClientRect();
        lens.style.left = (e.clientX - stageRect.left - size / 2) + 'px';
        lens.style.top = (e.clientY - stageRect.top - size / 2) + 'px';
        lens.style.backgroundSize = `${rect.width * lensFactor}px ${rect.height * lensFactor}px`;
        lens.style.backgroundPosition = `${size / 2 - x * lensFactor}px ${size / 2 - y * lensFactor}px`;
        return true;
    };
    stage.addEventListener('mousemove', update);
    stage.addEventListener('mouseleave', hide);
    stage.addEventListener('wheel', (e) => {
        if (!update(e)) return;
        e.preventDefault();
        lensFactor = Math.min(6, Math.max(1.5, lensFactor * (e.deltaY < 0 ? 1.25 : 0.8)));
        update(e);
        const hint = stage.querySelector('.detail-stage-hint');
        if (hint) hint.textContent = `Zoom ×${lensFactor.toFixed(1)}`;
    }, { passive: false });
}

// Desktop: previous/next painting in the detail pane (arrow keys)
function detailStep(direction) {
    if (selectedIndex === null) return;
    const current = paintings[selectedIndex];
    const list = filteredPaintings.includes(current) ? filteredPaintings : paintings;
    if (list.length < 2) return;
    const next = list[(list.indexOf(current) + direction + list.length) % list.length];
    selectPainting(paintings.indexOf(next));
    const item = document.querySelector('.painting-item.active');
    if (item) item.scrollIntoView({ block: 'nearest' });
}

// Change displayed description
function changeDescription(prefix) {
    const selector = document.getElementById(prefix + 'DescSelector');
    const textEl = document.getElementById(prefix + 'DescriptionText');
    const metaEl = document.getElementById(prefix + 'DescriptionMeta');
    const descriptions = descriptionsByPrefix[prefix] || [];
    
    if (!selector || !textEl || !metaEl || descriptions.length === 0) return;
    
    const desc = descriptions[parseInt(selector.value)];
    textEl.textContent = desc.text;
    metaEl.innerHTML = descriptionMetaHtml(desc);
}

// Apply all filters
function applyFilters() {
    filteredPaintings = paintings.filter(painting => {
        // Text search
        if (filters.search) {
            const query = filters.search.toLowerCase();
            const title = (painting.title || '').toLowerCase();
            const artist = (painting.artist || '').toLowerCase();
            const year = (painting.year || '').toString();
            const originalTitle = (painting.original_title || '').toLowerCase();
            const location = (painting.location || '').toLowerCase();
            const tags = [...(painting.periods || []), ...(painting.themes || [])].join(' ').toLowerCase();
            
            if (!title.includes(query) && !artist.includes(query) && 
                !year.includes(query) && !originalTitle.includes(query) && 
                !location.includes(query) && !tags.includes(query)) {
                return false;
            }
        }
        
        // Year range filter
        if (filters.yearFrom || filters.yearTo) {
            const paintingYear = parseInt(painting.year);
            if (isNaN(paintingYear)) return false;
            
            if (filters.yearFrom && paintingYear < filters.yearFrom) return false;
            if (filters.yearTo && paintingYear > filters.yearTo) return false;
        }
        
        // Active collection
        if (activeCollection && !activeCollection.painting_ids.has(painting.id)) return false;
        
        // Review status (only users who can upload ever receive pending paintings)
        if (account.user && account.user.can_upload && filters.review && filters.review !== 'all') {
            if ((painting.status === 'pending') !== (filters.review === 'pending')) return false;
        }
        
        // Period / theme filters
        if (filters.period && filters.period !== 'all' && !(painting.periods || []).includes(filters.period)) return false;
        if (filters.theme && filters.theme !== 'all' && !(painting.themes || []).includes(filters.theme)) return false;
        
        // Orientation filter
        if (filters.orientation !== 'all') {
            if (painting.orientation !== filters.orientation) return false;
        }
        
        // Confirmed status filter
        if (filters.confirmed !== 'all') {
            const isConfirmed = painting.confirmed === true;
            const filterConfirmed = filters.confirmed === 'true';
            if (isConfirmed !== filterConfirmed) return false;
        }
        
        // Seen live / favorite filters (only meaningful when logged in)
        if (account.user && filters.seenLive !== 'all') {
            const isSeenLive = getSeenLiveStatus(paintingKey(painting));
            const filterSeenLive = filters.seenLive === 'true';
            if (isSeenLive !== filterSeenLive) return false;
        }
        
        if (account.user && filters.favorite !== 'all') {
            if (isFavorite(paintingKey(painting)) !== (filters.favorite === 'true')) return false;
        }
        
        // Confidence filter
        const confidence = (painting.confidence_score || 0) * 100;
        if (confidence < filters.confidenceMin || confidence > filters.confidenceMax) {
            return false;
        }
        
        return true;
    });
    
    // Apply sorting
    applySorting();
    
    // Save filters to localStorage
    saveFiltersToStorage();
    
    // Auto-collapse after filter change
    autoCollapseFilters();
    
    selectedIndex = null;
    renderList();
}

// Apply sorting to filtered paintings
function applySorting() {
    if (filters.sortBy === 'none') return;
    
    filteredPaintings.sort((a, b) => {
        switch (filters.sortBy) {
            case 'date-asc':
                return parseInt(a.year || '9999') - parseInt(b.year || '9999');
            case 'date-desc':
                return parseInt(b.year || '0') - parseInt(a.year || '0');
            case 'title-asc':
                return (a.title || '').localeCompare(b.title || '');
            case 'title-desc':
                return (b.title || '').localeCompare(a.title || '');
            case 'artist-asc':
                return (a.artist || '').localeCompare(b.artist || '');
            case 'artist-desc':
                return (b.artist || '').localeCompare(a.artist || '');
            case 'desc-yes': {
                const aHasDesc = a.descriptions && Object.values(a.descriptions).some(arr => arr.length > 0 && arr[0].description);
                const bHasDesc = b.descriptions && Object.values(b.descriptions).some(arr => arr.length > 0 && arr[0].description);
                return (bHasDesc ? 1 : 0) - (aHasDesc ? 1 : 0);
            }
            case 'desc-no': {
                const aHasDesc = a.descriptions && Object.values(a.descriptions).some(arr => arr.length > 0 && arr[0].description);
                const bHasDesc = b.descriptions && Object.values(b.descriptions).some(arr => arr.length > 0 && arr[0].description);
                return (aHasDesc ? 1 : 0) - (bHasDesc ? 1 : 0);
            }
            case 'added-asc': {
                const aAdded = a.added_to_library ? new Date(a.added_to_library).getTime() : 0;
                const bAdded = b.added_to_library ? new Date(b.added_to_library).getTime() : 0;
                return aAdded - bAdded;
            }
            case 'added-desc': {
                const aAdded = a.added_to_library ? new Date(a.added_to_library).getTime() : 0;
                const bAdded = b.added_to_library ? new Date(b.added_to_library).getTime() : 0;
                return bAdded - aAdded;
            }
            case 'updated-asc': {
                const aUpdated = a.updated_on_library ? new Date(a.updated_on_library).getTime() : 0;
                const bUpdated = b.updated_on_library ? new Date(b.updated_on_library).getTime() : 0;
                return aUpdated - bUpdated;
            }
            case 'updated-desc': {
                const aUpdated = a.updated_on_library ? new Date(a.updated_on_library).getTime() : 0;
                const bUpdated = b.updated_on_library ? new Date(b.updated_on_library).getTime() : 0;
                return bUpdated - aUpdated;
            }
            default:
                return 0;
        }
    });
}

// Reset all filters
function resetFilters() {
    filters = {
        search: '',
        yearFrom: null,
        yearTo: null,
        orientation: 'all',
        confirmed: 'all',
        seenLive: 'all',
        favorite: 'all',
        period: 'all',
        theme: 'all',
        review: 'all',
        confidenceMin: 0,
        confidenceMax: 100,
        sortBy: 'updated-desc'
    };
    
    document.getElementById('searchInput').value = '';
    document.getElementById('yearFrom').value = '';
    document.getElementById('yearTo').value = '';
    document.getElementById('sortBy').value = 'updated-desc';
    
    document.querySelectorAll('.orientation-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.orientation === 'all');
    });
    
    document.querySelectorAll('[data-confirmed]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.confirmed === 'all');
    });
    
    document.querySelectorAll('[data-seen-live]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.seenLive === 'all');
    });
    
    document.querySelectorAll('[data-favorite]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.favorite === 'all');
    });
    
    document.querySelectorAll('[data-review]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.review === 'all');
    });
    
    document.getElementById('periodFilter').value = 'all';
    document.getElementById('themeFilter').value = 'all';
    
    document.getElementById('confidenceMin').value = 0;
    document.getElementById('confidenceMax').value = 100;
    updateConfidenceSlider();
    
    filters.confidenceMin = 0;
    filters.confidenceMax = 100;
    document.getElementById('confidenceMin').value = 0;
    document.getElementById('confidenceMax').value = 100;
    updateConfidenceSlider();
    
    applyFilters();
    
    // Auto-collapse after reset
    autoCollapseFilters();
}

// Search functionality
document.getElementById('searchInput').addEventListener('input', (e) => {
    filters.search = e.target.value.toLowerCase();
    applyFilters();
});

// Year range filters
document.getElementById('yearFrom').addEventListener('input', (e) => {
    filters.yearFrom = e.target.value ? parseInt(e.target.value) : null;
    applyFilters();
});

document.getElementById('yearTo').addEventListener('input', (e) => {
    filters.yearTo = e.target.value ? parseInt(e.target.value) : null;
    applyFilters();
});

// Options = tags actually used in the collection, with their counts
function populateTagFilters() {
    [['period', 'periods'], ['theme', 'themes']].forEach(([kind, key]) => {
        const counts = new Map();
        paintings.forEach(p => (p[key] || []).forEach(tag => counts.set(tag, (counts.get(tag) || 0) + 1)));
        const select = document.getElementById(kind + 'Filter');
        const current = select.value || 'all';
        select.innerHTML = '<option value="all">Todas</option>' + [...counts.entries()]
            .sort((a, b) => a[0].localeCompare(b[0], 'es'))
            .map(([tag, count]) => `<option value="${esc(tag)}">${esc(tag)} (${count})</option>`).join('');
        select.value = counts.has(current) ? current : 'all';
    });
}

document.querySelectorAll('[data-review]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('[data-review]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filters.review = btn.dataset.review;
        applyFilters();
    });
});

['period', 'theme'].forEach(kind => {
    document.getElementById(kind + 'Filter').addEventListener('change', (e) => {
        filters[kind] = e.target.value;
        applyFilters();
    });
});

// Sort dropdown
document.getElementById('sortBy').addEventListener('change', (e) => {
    filters.sortBy = e.target.value;
    applyFilters();
});

// Orientation button filters
document.querySelectorAll('[data-orientation]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('[data-orientation]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filters.orientation = btn.dataset.orientation;
        applyFilters();
    });
});

// Confirmed status button filters
document.querySelectorAll('[data-confirmed]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('[data-confirmed]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filters.confirmed = btn.dataset.confirmed;
        applyFilters();
    });
});

// Seen live button filters
document.querySelectorAll('[data-seen-live]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('[data-seen-live]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filters.seenLive = btn.dataset.seenLive;
        applyFilters();
    });
});

// Favorite button filters
document.querySelectorAll('[data-favorite]').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('[data-favorite]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filters.favorite = btn.dataset.favorite;
        applyFilters();
    });
});

// Confidence range slider
const confidenceMin = document.getElementById('confidenceMin');
const confidenceMax = document.getElementById('confidenceMax');

function updateConfidenceSlider() {
    const min = parseInt(confidenceMin.value);
    const max = parseInt(confidenceMax.value);
    
    // Prevent sliders from crossing
    if (min > max) {
        confidenceMin.value = max;
        filters.confidenceMin = max;
    } else {
        filters.confidenceMin = min;
    }
    
    if (max < min) {
        confidenceMax.value = min;
        filters.confidenceMax = min;
    } else {
        filters.confidenceMax = max;
    }
    
    // Update display values
    document.getElementById('confidenceMinValue').textContent = filters.confidenceMin + '%';
    document.getElementById('confidenceMaxValue').textContent = filters.confidenceMax + '%';
    
    // Update track visual
    const track = document.getElementById('sliderTrack');
    const percentMin = filters.confidenceMin;
    const percentMax = filters.confidenceMax;
    track.style.left = percentMin + '%';
    track.style.width = (percentMax - percentMin) + '%';
}

confidenceMin.addEventListener('input', () => {
    updateConfidenceSlider();
    applyFilters();
});

confidenceMax.addEventListener('input', () => {
    updateConfidenceSlider();
    applyFilters();
});

// Initialize slider
updateConfidenceSlider();

// Toggle filters visibility
function toggleFilters() {
    const filters = document.getElementById('advancedFilters');
    const btn = document.querySelector('.collapse-btn');
    
    filters.classList.toggle('collapsed');
    btn.classList.toggle('collapsed');
}

// ===================== Viewer =====================
const viewerEl = document.getElementById('viewer');
const stageEl = document.getElementById('viewerStage');
const viewerImg = document.getElementById('viewerImage');
const lensEl = document.getElementById('viewerLens');
const hintEl = document.getElementById('viewerHint');
const MAX_TOUCH_ZOOM = 6;
let viewerIndex = null;
let lensFactor = 2;
const zoom = { scale: 1, x: 0, y: 0 };
let hintTimer = null;

// After a reload the browser may restore our "viewer" history entry while the viewer is closed
if (history.state && history.state.viewer) history.replaceState(null, '');

function showHint(text) {
    hintEl.textContent = text;
    hintEl.classList.add('show');
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => hintEl.classList.remove('show'), 2500);
}

function openViewer(index) {
    if (index === null || index < 0 || !paintings[index]) return;
    showInViewer(index);
    if (viewerEl.classList.contains('open')) return;
    viewerEl.classList.add('open');
    viewerEl.setAttribute('aria-hidden', 'false');
    document.body.classList.add('viewer-open');
    // "Back" (browser/phone) closes the viewer and returns to the list
    if (!(history.state && history.state.viewer)) history.pushState({ viewer: true }, '');
    const finePointer = matchMedia('(hover: hover) and (pointer: fine)').matches;
    showHint(finePointer ? 'Pasa el ratón por el cuadro para ampliarlo ×2 · rueda para ajustar' : 'Pellizca o toca dos veces para hacer zoom');
}

function showInViewer(index, { afterSwipe = false } = {}) {
    viewerIndex = index;
    const painting = paintings[index];
    const url = imageUrl(painting);
    resetZoom(false);
    hideLens();
    viewerImg.src = url;
    viewerImg.alt = painting.title || '';
    if (afterSwipe) {
        // The peek covers the stage until the new image is ready: no flash of the old one
        viewerImg.decode().catch(() => {}).finally(() => preparePeeks());
    } else {
        preparePeeks();
    }
    lensEl.style.backgroundImage = url ? `url("${url}")` : '';
    const panel = document.getElementById('viewerPanel');
    panel.innerHTML = viewerPanelHtml(painting);
    panel.scrollTop = 0;
}

function viewerPanelHtml(painting) {
    const url = imageUrl(painting);
    return renderPaintingInfo(painting, 'viewer', true)
        + (url ? `<p style="margin-top: 20px;"><a href="${esc(url)}" target="_blank" rel="noopener" class="search-link">↗ Abrir imagen original</a></p>` : '');
}

function hideViewer() {
    viewerEl.classList.remove('open');
    viewerEl.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('viewer-open');
    hideLens();
    resetZoom(false);
    viewerPanelEl.style.transition = '';
    viewerPanelEl.style.opacity = '';
    viewerIndex = null;
}

function closeViewer() {
    if (history.state && history.state.viewer) {
        history.back(); // popstate hides it
    } else {
        hideViewer();
    }
}

window.addEventListener('popstate', () => {
    if (viewerEl.classList.contains('open') && !(history.state && history.state.viewer)) hideViewer();
});

// Previous/next painting following the order of the (filtered) list
function neighborIndex(direction) {
    if (viewerIndex === null) return null;
    const current = paintings[viewerIndex];
    const list = filteredPaintings.includes(current) ? filteredPaintings : paintings;
    if (list.length < 2) return null;
    const pos = list.indexOf(current);
    return paintings.indexOf(list[(pos + direction + list.length) % list.length]);
}

function viewerStep(direction, options = {}) {
    const next = neighborIndex(direction);
    if (next === null) return;
    if (!isMobileLayout()) selectPainting(next);
    showInViewer(next, options);
}

// ---- Swipe preview (touch): the neighbour painting follows the finger ----
const peekEls = { '-1': document.getElementById('viewerPeekPrev'), '1': document.getElementById('viewerPeekNext') };
const isTouchDevice = () => navigator.maxTouchPoints > 0 || 'ontouchstart' in window;

function preparePeeks() {
    [-1, 1].forEach(direction => {
        const el = peekEls[direction];
        el.classList.remove('swipe-anim');
        el.style.visibility = 'hidden';
        el.style.transform = '';
        const index = isTouchDevice() ? neighborIndex(direction) : null;
        el.dataset.index = index === null ? '' : index;
        if (index === null) return;
        const painting = paintings[index];
        const img = el.querySelector('img');
        const url = imageUrl(painting);
        if (img.getAttribute('src') !== url) img.src = url; // preloads the neighbour
        el.querySelector('.viewer-peek-caption').textContent =
            `${direction > 0 ? 'Siguiente' : 'Anterior'} ▸ ${painting.title || 'Sin título'}`;
    });
}

const SWIPE_COMMIT_RATIO = 0.25; // fraction of the width that completes a swipe
const SWIPE_MIN_PANEL_OPACITY = 0.15;
const viewerPanelEl = document.getElementById('viewerPanel');

// Info panel fades out as the swipe gets closer to completing (driven by the finger)
function setPanelFade(progress) {
    viewerPanelEl.style.transition = 'none';
    viewerPanelEl.style.opacity = String(1 - (1 - SWIPE_MIN_PANEL_OPACITY) * Math.min(1, Math.max(0, progress)));
}

function animatePanelOpacity(from, to, ms) {
    viewerPanelEl.style.transition = 'none';
    viewerPanelEl.style.opacity = String(from);
    void viewerPanelEl.offsetWidth; // apply the start value before transitioning
    viewerPanelEl.style.transition = `opacity ${ms}ms ease-out`;
    viewerPanelEl.style.opacity = String(to);
}

function setSwipeOffset(dx) {
    hintEl.classList.remove('show');
    const width = stageEl.clientWidth;
    const direction = dx < 0 ? 1 : -1;
    const peek = peekEls[direction];
    const other = peekEls[-direction];
    other.style.visibility = 'hidden';
    if (peek.dataset.index === '') {
        viewerImg.style.transform = `translateX(${dx / 3}px)`; // nothing to show: resist
        peek.style.visibility = 'hidden';
        setPanelFade(0);
        return;
    }
    viewerImg.style.transform = `translateX(${dx}px)`;
    peek.style.visibility = 'visible';
    peek.style.transform = `translateX(${direction * width + dx}px)`;
    setPanelFade(Math.abs(dx) / (width * SWIPE_COMMIT_RATIO));
}

function finishSwipe(dx, commit) {
    const width = stageEl.clientWidth;
    const direction = dx < 0 ? 1 : -1;
    const peek = peekEls[direction];
    commit = commit && peek.dataset.index !== '';
    viewerImg.classList.add('swipe-anim');
    peek.classList.add('swipe-anim');
    if (commit) {
        viewerImg.style.transform = `translateX(${-direction * width}px)`;
        peek.style.transform = 'translateX(0)';
        setPanelFade(1);
    } else {
        viewerImg.style.transform = '';
        peek.style.transform = `translateX(${direction * width}px)`;
        animatePanelOpacity(parseFloat(viewerPanelEl.style.opacity || '1'), 1, 200);
    }
    setTimeout(() => {
        viewerImg.classList.remove('swipe-anim');
        if (commit) {
            viewerStep(direction, { afterSwipe: true });
            animatePanelOpacity(0, 1, 180); // new info: quick fade in
        } else {
            peek.classList.remove('swipe-anim');
            peek.style.visibility = 'hidden';
        }
    }, 260);
}

document.addEventListener('keydown', (e) => {
    if (!collectionMenu.hidden && e.key === 'Escape') {
        closeCollectionMenu();
        return;
    }
    if (collectionModal.classList.contains('open')) {
        if (e.key === 'Escape') closeCollectionModal();
        return;
    }
    if (document.getElementById('authModal').classList.contains('open')) {
        if (e.key === 'Escape') closeAuth();
        return;
    }
    if (editModal.classList.contains('open')) {
        if (e.key === 'Escape') closeEdit();
        return;
    }
    if (usersModal.classList.contains('open')) {
        if (e.key === 'Escape') closeUsers();
        return;
    }
    if (aiModal.classList.contains('open')) {
        if (e.key === 'Escape') closeAiSettings();
        return;
    }
    if (uploadModal.classList.contains('open')) {
        if (e.key === 'Escape') closeUpload();
        return;
    }
    if (!viewerEl.classList.contains('open')) {
        if (isMapOpen()) {
            if (e.key === 'Escape') closeMap();
            return;
        }
        const typing = e.target.closest && e.target.closest('input, textarea, select, [contenteditable]');
        if (!typing && !isMobileLayout() && selectedIndex !== null) {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); detailStep(-1); }
            else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); detailStep(1); }
            else if (e.key === 'Escape') closeDetail();
        }
        return;
    }
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowLeft') viewerStep(-1);
    else if (e.key === 'ArrowRight') viewerStep(1);
});

// ---- Desktop: magnifying lens (×2 by default) following the mouse ----
function hideLens() {
    lensEl.style.display = 'none';
    stageEl.classList.remove('zooming');
}

function updateLens(e) {
    const rect = viewerImg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    if (zoom.scale !== 1 || !viewerImg.naturalWidth || x < 0 || y < 0 || x > rect.width || y > rect.height) {
        hideLens();
        return false;
    }
    lensEl.style.display = 'block';
    stageEl.classList.add('zooming');
    const size = lensEl.offsetWidth;
    const stageRect = stageEl.getBoundingClientRect();
    lensEl.style.left = (e.clientX - stageRect.left - size / 2) + 'px';
    lensEl.style.top = (e.clientY - stageRect.top - size / 2) + 'px';
    lensEl.style.backgroundSize = `${rect.width * lensFactor}px ${rect.height * lensFactor}px`;
    lensEl.style.backgroundPosition = `${size / 2 - x * lensFactor}px ${size / 2 - y * lensFactor}px`;
    return true;
}

stageEl.addEventListener('pointerleave', (e) => {
    if (e.pointerType === 'mouse') hideLens();
});

stageEl.addEventListener('wheel', (e) => {
    if (!updateLens(e)) return;
    e.preventDefault();
    lensFactor = Math.min(6, Math.max(1.5, lensFactor * (e.deltaY < 0 ? 1.25 : 0.8)));
    updateLens(e);
    showHint(`Zoom ×${lensFactor.toFixed(1)}`);
}, { passive: false });

// ---- Touch: pinch, pan, double tap and swipe ----
const pointers = new Map();
let gesture = null;
let lastTap = { time: 0, x: 0, y: 0 };

function applyZoom(animate) {
    viewerImg.classList.toggle('animating', !!animate);
    viewerImg.style.transform = zoom.scale === 1 && !zoom.x && !zoom.y
        ? ''
        : `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})`;
}

function resetZoom(animate) {
    zoom.scale = 1;
    zoom.x = 0;
    zoom.y = 0;
    applyZoom(animate);
}

function clampZoom() {
    const maxX = Math.max(0, (viewerImg.offsetWidth * zoom.scale - stageEl.clientWidth) / 2);
    const maxY = Math.max(0, (viewerImg.offsetHeight * zoom.scale - stageEl.clientHeight) / 2);
    zoom.x = Math.min(maxX, Math.max(-maxX, zoom.x));
    zoom.y = Math.min(maxY, Math.max(-maxY, zoom.y));
}

// Zoom keeping the image point under (clientX, clientY) fixed
function zoomAt(clientX, clientY, newScale, animate) {
    newScale = Math.min(MAX_TOUCH_ZOOM, Math.max(1, newScale));
    const stageRect = stageEl.getBoundingClientRect();
    const cx = stageRect.left + viewerImg.offsetLeft + viewerImg.offsetWidth / 2;
    const cy = stageRect.top + viewerImg.offsetTop + viewerImg.offsetHeight / 2;
    const qx = (clientX - cx - zoom.x) / zoom.scale;
    const qy = (clientY - cy - zoom.y) / zoom.scale;
    zoom.x = clientX - cx - newScale * qx;
    zoom.y = clientY - cy - newScale * qy;
    zoom.scale = newScale;
    clampZoom();
    applyZoom(animate);
}

function pinchInfo() {
    const [a, b] = [...pointers.values()];
    return { dist: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

stageEl.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' || e.target.closest('button')) return;
    try { stageEl.setPointerCapture(e.pointerId); } catch (err) { /* pointer already gone */ }
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) {
        gesture = { startX: e.clientX, startY: e.clientY, startTime: Date.now(), moved: false, multi: false };
    } else if (gesture) {
        gesture.moved = true;
        gesture.multi = true;
    }
});

stageEl.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'mouse') {
        updateLens(e);
        return;
    }
    if (!pointers.has(e.pointerId)) return;
    const prev = pointers.get(e.pointerId);
    if (pointers.size === 2) {
        const before = pinchInfo();
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const after = pinchInfo();
        if (!before.dist) return;
        zoom.x += after.x - before.x;
        zoom.y += after.y - before.y;
        zoomAt(after.x, after.y, zoom.scale * after.dist / before.dist, false);
    } else if (pointers.size === 1) {
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const dx = gesture ? e.clientX - gesture.startX : 0;
        const dy = gesture ? e.clientY - gesture.startY : 0;
        if (gesture && Math.hypot(dx, dy) > 10) {
            gesture.moved = true;
            if (!gesture.swipe && zoom.scale === 1 && !gesture.multi) {
                gesture.swipe = Math.abs(dx) > Math.abs(dy) ? 'horizontal' : 'vertical';
            }
        }
        if (gesture && gesture.swipe === 'horizontal') {
            setSwipeOffset(dx);
        } else if (zoom.scale > 1) {
            zoom.x += e.clientX - prev.x;
            zoom.y += e.clientY - prev.y;
            clampZoom();
            applyZoom(false);
        }
    }
});

function endPointer(e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size > 0) return;
    const g = gesture;
    gesture = null;
    const dx = g ? e.clientX - g.startX : 0;
    const elapsed = g ? Date.now() - g.startTime : 0;
    if (g && g.swipe === 'horizontal') {
        // Complete when dragged past a quarter of the width, or on a quick flick
        const commit = e.type !== 'pointercancel'
            && (Math.abs(dx) > stageEl.clientWidth * SWIPE_COMMIT_RATIO || (Math.abs(dx) > 50 && elapsed < 300));
        finishSwipe(dx, commit);
        return;
    }
    if (zoom.scale < 1.05) resetZoom(true);
    if (!g || e.type === 'pointercancel') return;

    if (!g.moved && elapsed < 300) {
        const now = Date.now();
        if (now - lastTap.time < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 40) {
            if (zoom.scale > 1) resetZoom(true);
            else zoomAt(e.clientX, e.clientY, 2.5, true);
            lastTap.time = 0;
        } else {
            lastTap = { time: now, x: e.clientX, y: e.clientY };
        }
    }
}

stageEl.addEventListener('pointerup', endPointer);
stageEl.addEventListener('pointercancel', endPointer);
window.addEventListener('resize', () => {
    if (viewerEl.classList.contains('open')) resetZoom(false);
});

// ===================== Upload =====================
const uploadModal = document.getElementById('uploadModal');
const uploadList = document.getElementById('uploadList');
const fileInput = document.getElementById('fileInput');
const dropzone = document.getElementById('dropzone');
const IMAGE_NAME_RE = /\.(jpe?g|png|webp|gif|bmp|tiff?)$/i;
let activeUploads = 0;

const canUpload = () => !!(account.user && account.user.can_upload);

function openUpload() {
    if (!canUpload()) return;
    uploadModal.classList.add('open');
}

function closeUpload() {
    uploadModal.classList.remove('open');
    resetDragState();
}

uploadModal.addEventListener('click', (e) => {
    if (e.target === uploadModal) closeUpload();
});
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fileInput.click();
    }
});
fileInput.addEventListener('change', () => {
    handleFiles(fileInput.files);
    fileInput.value = '';
});

// Drag & drop: ONLY while the "+" upload panel is open. Otherwise dropping a file does nothing
// (we still cancel the event so the browser does not navigate away to the dropped image).
let dragDepth = 0;
const draggingFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
const acceptingDrops = () => canUpload() && uploadModal.classList.contains('open');

function resetDragState() {
    dragDepth = 0;
    document.body.classList.remove('dragging-files');
}

document.addEventListener('dragenter', (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    if (!acceptingDrops()) return;
    dragDepth++;
    document.body.classList.add('dragging-files');
});
document.addEventListener('dragover', (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = acceptingDrops() ? 'copy' : 'none';
});
document.addEventListener('dragleave', (e) => {
    if (!draggingFiles(e) || !acceptingDrops()) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) document.body.classList.remove('dragging-files');
});
document.addEventListener('drop', (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    const accept = acceptingDrops();
    resetDragState();
    if (accept) handleFiles(e.dataTransfer.files);
});

function updateUploadBadge() {
    const badge = document.getElementById('uploadBadge');
    badge.textContent = activeUploads;
    badge.classList.toggle('show', activeUploads > 0);
}

function handleFiles(fileList) {
    const files = [...fileList].filter(f => f.type.startsWith('image/') || IMAGE_NAME_RE.test(f.name));
    if (!canUpload()) return;
    openUpload();
    files.forEach(file => startUpload(file, createUploadItem(file)));
}

function createUploadItem(file) {
    const li = document.createElement('li');
    li.className = 'upload-item';
    li.innerHTML = `
        <img alt="">
        <div style="min-width: 0;">
            <div class="upload-name"></div>
            <div class="upload-status">En cola…</div>
            <div class="upload-progress"><div></div></div>
        </div>
        <div class="upload-actions"></div>
    `;
    const thumb = li.querySelector('img');
    thumb.src = URL.createObjectURL(file);
    thumb.onload = () => URL.revokeObjectURL(thumb.src);
    li.querySelector('.upload-name').textContent = file.name;
    li.querySelector('.upload-name').title = file.name;
    uploadList.prepend(li);

    const statusEl = li.querySelector('.upload-status');
    const barEl = li.querySelector('.upload-progress > div');
    return {
        setStatus(text) {
            statusEl.textContent = text;
            statusEl.title = text;
        },
        setProgress(percent) {
            barEl.style.width = percent + '%';
        },
        fail(message, log) {
            li.classList.add('error');
            this.setStatus('⚠ ' + message);
            this.setProgress(100);
            if (log) {
                const details = document.createElement('details');
                details.innerHTML = '<summary>Ver registro</summary><pre></pre>';
                details.querySelector('pre').textContent = log;
                li.appendChild(details);
            }
        },
        done(result) {
            li.classList.add('done');
            this.setProgress(100);
            this.setStatus(`✓ ${result.title || 'Sin título'} — ${result.artist || 'Artista desconocido'}${result.year && result.year !== 'Unknown' ? ` (${result.year})` : ''}`);
            const button = document.createElement('button');
            button.className = 'upload-view-btn';
            button.textContent = 'Ver';
            button.onclick = () => {
                const index = paintings.findIndex(p => (result.id && p.id === result.id) || baseName(p.file_path) === baseName(result.file_path));
                if (index === -1) return;
                closeUpload();
                if (isMobileLayout()) openViewer(index); else selectPainting(index);
            };
            li.querySelector('.upload-actions').appendChild(button);
        }
    };
}

function startUpload(file, item) {
    activeUploads++;
    updateUploadBadge();
    const finish = () => {
        activeUploads--;
        updateUploadBadge();
    };

    const form = new FormData();
    form.append('image', file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', 'api/upload.php');
    xhr.setRequestHeader('X-Cuadros', '1');
    xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const ratio = e.loaded / e.total;
        item.setProgress(ratio * 40);
        item.setStatus(`Subiendo… ${Math.round(ratio * 100)}%`);
    };
    xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* non-JSON error page */ }
        if (xhr.status !== 202) {
            item.fail(data.error || `Error ${xhr.status} al subir`);
            finish();
            return;
        }
        item.setProgress(45);
        item.setStatus('Identificando el cuadro con IA…');
        pollJob(data.job, item, finish);
    };
    xhr.onerror = () => {
        item.fail('Error de red al subir');
        finish();
    };
    xhr.send(form);
}

async function pollJob(jobId, item, finish, attempt = 0) {
    let data;
    try {
        const response = await fetch(`api/job.php?id=${encodeURIComponent(jobId)}`, { cache: 'no-store' });
        data = await response.json();
        if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
    } catch (error) {
        if (attempt < 300) {
            setTimeout(() => pollJob(jobId, item, finish, attempt + 1), 3000);
        } else {
            item.fail('No se pudo consultar el estado: ' + error.message);
            finish();
        }
        return;
    }

    if (data.state === 'processing') {
        item.setProgress(Math.min(95, 45 + attempt * 2));
        if (data.last_line) item.setStatus(data.last_line);
        setTimeout(() => pollJob(jobId, item, finish, attempt + 1), 2000);
        return;
    }

    if (data.state === 'done' && data.result) {
        try {
            await refreshLibrary();
        } catch (error) {
            console.warn('No se pudo recargar la biblioteca', error);
        }
        item.done(data.result);
    } else {
        item.fail(data.daily_limit_reached
            ? 'Límite diario de la API alcanzado. La imagen queda guardada y se procesará en la próxima ejecución.'
            : 'No se pudo identificar el cuadro. La imagen queda guardada en paintings/.', data.log);
    }
    finish();
}

window.addEventListener('beforeunload', (e) => {
    if (activeUploads > 0) e.preventDefault();
});

// ===================== Map =====================
const LEAFLET_VERSION = '1.9.4';
const MARKERCLUSTER_VERSION = '1.5.3';
const mapViewEl = document.getElementById('mapView');
let leafletPromise = null;
let map = null;
let mapLayer = null;

function loadAsset(tag, url) {
    return new Promise((resolve, reject) => {
        const el = document.createElement(tag);
        if (tag === 'link') {
            el.rel = 'stylesheet';
            el.href = url;
        } else {
            el.src = url;
        }
        el.onload = resolve;
        el.onerror = () => reject(new Error('No se pudo cargar la librería del mapa'));
        document.head.appendChild(el);
    });
}

// Leaflet + markercluster (nearby museums are grouped until you zoom in), loaded on first use
function loadLeaflet() {
    if (!leafletPromise) {
        const cluster = `https://unpkg.com/leaflet.markercluster@${MARKERCLUSTER_VERSION}/dist/`;
        leafletPromise = Promise.all([
            loadAsset('link', `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css`),
            loadAsset('link', cluster + 'MarkerCluster.css'),
            loadAsset('script', `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`)
                .then(() => loadAsset('script', cluster + 'leaflet.markercluster.js'))
        ]).catch(error => {
            leafletPromise = null;
            throw error;
        });
    }
    return leafletPromise;
}

function markerIcon(count) {
    return L.divIcon({
        className: '',
        html: `<div class="map-marker"><span>${count}</span></div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

function isMapOpen() {
    return mapViewEl.classList.contains('open');
}

async function openMap() {
    if (!isMapOpen()) {
        mapViewEl.classList.add('open');
        document.body.classList.add('viewer-open');
        if (!(history.state && history.state.map)) history.pushState({ map: true }, '');
    }
    try {
        await loadLeaflet();
    } catch (error) {
        document.getElementById('mapCanvas').innerHTML = `<div class="error">${esc(error.message)}</div>`;
        return;
    }
    if (!map) {
        map = L.map('mapCanvas', { worldCopyJump: true }).setView([40, -20], 3);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
        }).addTo(map);
    }
    map.invalidateSize();
    renderMap();
}

function hideMap() {
    mapViewEl.classList.remove('open');
    if (!viewerEl.classList.contains('open')) document.body.classList.remove('viewer-open');
    if (map) map.closePopup();
}

function closeMap() {
    if (history.state && history.state.map) {
        history.back(); // popstate hides it
    } else {
        hideMap();
    }
}

window.addEventListener('popstate', () => {
    const state = history.state || {};
    if (isMapOpen() && !state.map && !state.viewer) hideMap();
    // Back from the viewer to the map keeps the page scroll locked
    if (isMapOpen() && state.map) document.body.classList.add('viewer-open');
});

// Paintings shown on the map = the ones currently in the (filtered) list
function renderMap() {
    const source = filteredPaintings;
    const groups = new Map();
    const missing = [];
    source.forEach(painting => {
        const geo = painting.geo;
        if (geo && geo.status === 'ok' && geo.lat !== null && geo.lon !== null) {
            // Same museum written differently ("London"/"Londres") lands on the same coordinates
            const key = `${geo.lat.toFixed(4)},${geo.lon.toFixed(4)}`;
            if (!groups.has(key)) groups.set(key, { lat: geo.lat, lon: geo.lon, place: geo.place, names: new Set(), paintings: [] });
            const group = groups.get(key);
            group.names.add(painting.location);
            group.paintings.push(painting);
        } else {
            missing.push(painting);
        }
    });

    if (mapLayer) mapLayer.remove();
    mapLayer = L.markerClusterGroup({
        showCoverageOnHover: false,
        maxClusterRadius: 40,
        // Cluster bubble shows the number of paintings, not of museums
        iconCreateFunction: (cluster) => L.divIcon({
            className: '',
            html: `<div class="map-cluster">${cluster.getAllChildMarkers().reduce((sum, m) => sum + m.options.count, 0)}</div>`,
            iconSize: [42, 42]
        })
    }).addTo(map);
    const bounds = [];
    groups.forEach(group => {
        const icon = markerIcon(group.paintings.length);
        const title = [...group.names][0];
        const place = (group.place || '').split(',').slice(0, 3).join(',');
        L.marker([group.lat, group.lon], { icon, title, riseOnHover: true, count: group.paintings.length })
            .bindPopup(`
                <div class="map-popup-title">${esc(title)}</div>
                <div class="map-popup-place">${esc(place)}</div>
                <div class="map-popup-list">
                    ${group.paintings.map(p => {
                        const key = paintingKey(p);
                        return `
                            <button class="map-popup-item${getSeenLiveStatus(key) ? ' seen-live' : ''}" onclick="openFromMap(${paintings.indexOf(p)})">
                                <img src="${esc(imageUrl(p))}" alt="" loading="lazy">
                                <span><strong>${esc(p.title || 'Sin título')}</strong>${isFavorite(key) ? ' ❤️' : ''}
                                <small>${esc(p.artist || 'Artista desconocido')}${p.year ? ` · ${esc(p.year)}` : ''}</small></span>
                            </button>
                        `;
                    }).join('')}
                </div>
            `, { maxWidth: 320, minWidth: 240 })
            .addTo(mapLayer);
        bounds.push([group.lat, group.lon]);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });

    const placed = source.length - missing.length;
    const filtered = source.length !== paintings.length;
    document.getElementById('mapSubtitle').textContent =
        `${placed} cuadro${placed !== 1 ? 's' : ''} en ${groups.size} lugar${groups.size !== 1 ? 'es' : ''}`
        + (filtered ? ` · filtros activos (${source.length} de ${paintings.length})` : '');

    const reason = (p) => {
        if (!p.location || (p.geo && p.geo.status === 'not_a_place')) return 'sin ubicación';
        if (!p.geo) return 'pendiente de localizar';
        return `«${p.location}» no encontrada`;
    };
    document.getElementById('mapFooter').innerHTML = missing.length === 0
        ? '✅ Todos los cuadros tienen ubicación en el mapa'
        : `<details>
                <summary>📍 ${missing.length} cuadro${missing.length !== 1 ? 's' : ''} sin ubicación en el mapa</summary>
                <ul>
                    ${missing.map(p => `
                        <li><a onclick="openFromMap(${paintings.indexOf(p)})">${esc(p.title || 'Sin título')}</a>
                            — ${esc(p.artist || 'Artista desconocido')} <span class="map-footer-reason">(${esc(reason(p))})</span></li>
                    `).join('')}
                </ul>
           </details>`;
}

function openFromMap(index) {
    if (map) map.closePopup();
    if (isMobileLayout()) {
        openViewer(index);
    } else {
        closeMap();
        selectPainting(index);
    }
}

// ===================== Edit paintings (admin) =====================
const editModal = document.getElementById('editModal');
let editingKey = null;
let aiOptions = null;
let aiJobRunning = false;

function editingPainting() {
    return paintings.find(p => paintingKey(p) === editingKey);
}

async function openEdit(key) {
    editingKey = key;
    const painting = editingPainting();
    if (!painting) return;
    document.getElementById('editTitle').textContent = `✏️ ${painting.title || 'Editar cuadro'}`;
    document.getElementById('editFieldTitle').value = painting.title || '';
    document.getElementById('editFieldOriginalTitle').value = painting.original_title || '';
    document.getElementById('editFieldArtist').value = painting.artist || '';
    document.getElementById('editFieldYear').value = painting.year || '';
    document.getElementById('editFieldLocation').value = painting.location || '';
    document.getElementById('editFieldConfirmed').checked = !!painting.confirmed;
    document.getElementById('editFieldPending').checked = painting.status === 'pending';
    editTags = { periods: [...(painting.periods || [])], themes: [...(painting.themes || [])] };
    editBaseline = editFieldValues();
    versionEdits = new Map();
    versionDeletes = new Set();
    document.getElementById('editDescText').value = '';
    renderEditTags();
    resetReplaceImage();
    renderEditVersions();
    showEditTab(editVersions.length ? 'versions' : 'own');
    showEditPane('general');
    resetDeleteConfirm();
    document.getElementById('editError').textContent = '';
    if (!aiJobRunning) setAiStatus('');
    updateEditDirty();
    editModal.classList.add('open');

    if (!aiOptions) {
        try {
            aiOptions = await api('api/painting.php');
        } catch (error) {
            aiOptions = { providers: [], default_style: '' };
        }
    }
    renderEditTags();
    const select = document.getElementById('editAiProvider');
    select.innerHTML = aiOptions.providers.map(p => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')
        || '<option value="">No hay IAs configuradas</option>';
    const style = document.getElementById('editAiStyle');
    style.placeholder = `Estilo (por defecto: ${aiOptions.default_style || 'el de la configuración'})`;
    document.getElementById('editAiLength').placeholder = `Longitud máxima en caracteres (por defecto: ${aiOptions.default_max_length || 1000})`;
    document.getElementById('editAiSubmit').disabled = aiJobRunning || aiOptions.providers.length === 0;
}

// Main tabs. The card has a fixed size, so switching tabs never makes it jump
function showEditPane(name) {
    document.querySelectorAll('#editModal .edit-main-tab').forEach(tab => {
        const active = tab.dataset.pane === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active);
    });
    document.querySelectorAll('#editModal .edit-pane').forEach(pane => {
        pane.hidden = pane.dataset.pane !== name;
    });
    document.querySelector('#editModal .edit-body').scrollTop = 0;
}

// ---- Pending changes: everything is applied together with the single «Guardar» button ----
let editBaseline = null;          // field values when the editor was opened (or last saved)
let versionEdits = new Map();     // description_id -> edited text
let versionDeletes = new Set();   // description_ids marked to be deleted

function editFieldValues() {
    const value = (id) => document.getElementById(id).value;
    return {
        title: value('editFieldTitle'),
        original_title: value('editFieldOriginalTitle'),
        artist: value('editFieldArtist'),
        year: value('editFieldYear'),
        location: value('editFieldLocation'),
        periods: [...editTags.periods],
        themes: [...editTags.themes],
        confirmed: document.getElementById('editFieldConfirmed').checked,
        pending: document.getElementById('editFieldPending').checked
    };
}

function editDirtyState() {
    if (!editBaseline) return { general: false, image: false, description: false, advanced: false };
    const now = editFieldValues();
    const same = (key) => JSON.stringify(Array.isArray(now[key]) ? [...now[key]].sort() : now[key])
        === JSON.stringify(Array.isArray(editBaseline[key]) ? [...editBaseline[key]].sort() : editBaseline[key]);
    return {
        general: !['title', 'original_title', 'artist', 'year', 'location', 'periods', 'themes'].every(same),
        image: editImageFile.files.length > 0,
        description: versionEdits.size > 0 || versionDeletes.size > 0 || document.getElementById('editDescText').value.trim() !== '',
        advanced: !['confirmed', 'pending'].every(same)
    };
}

const EDIT_PANE_NAMES = { general: 'General', image: 'Imagen', description: 'Descripción', advanced: 'Avanzado' };

function updateEditDirty() {
    const dirty = editDirtyState();
    const panes = Object.keys(dirty).filter(name => dirty[name]);
    document.querySelectorAll('#editModal .edit-main-tab').forEach(tab => {
        tab.classList.toggle('dirty', !!dirty[tab.dataset.pane]);
    });
    document.getElementById('editPendingSummary').textContent = panes.length
        ? `Sin guardar: ${panes.map(name => EDIT_PANE_NAMES[name]).join(', ')}`
        : 'No hay cambios';
    document.getElementById('editSubmit').disabled = panes.length === 0;
    return panes.length > 0;
}

editModal.addEventListener('input', updateEditDirty);
editModal.addEventListener('change', updateEditDirty);

function closeEdit(force = false) {
    if (force !== true && editModal.classList.contains('open') && updateEditDirty()
        && !confirm('Hay cambios sin guardar. ¿Cerrar y descartarlos?')) {
        return;
    }
    editModal.classList.remove('open');
    editBaseline = null;
}

editModal.addEventListener('click', (e) => {
    if (e.target === editModal) closeEdit();
});

async function afterPaintingChange(message) {
    try {
        await refreshLibrary();
    } catch (error) {
        console.warn('No se pudo recargar la biblioteca', error);
    }
    refreshAccountUI();
    if (isMapOpen()) renderMap();
    showToast(message);
}

async function uploadReplacementImage(key, file) {
    const form = new FormData();
    form.append('id', key);
    form.append('image', file, file.name);
    const response = await fetch('api/replace_image.php', { method: 'POST', headers: { 'X-Cuadros': '1' }, body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
    return data;
}

// Applies the pending changes of every tab: image, data/tags/state, description versions and the new description
document.getElementById('editForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const dirty = editDirtyState();
    if (!Object.values(dirty).some(Boolean)) return;
    const submit = document.getElementById('editSubmit');
    const errorEl = document.getElementById('editError');
    const key = editingKey;
    const fields = editFieldValues();
    if (!fields.title.trim()) {
        showEditPane('general');
        errorEl.textContent = 'El título no puede quedar vacío';
        document.getElementById('editFieldTitle').focus();
        return;
    }
    const locationChanged = fields.location.trim() !== (editingPainting().location || '');
    const step = (text) => { submit.textContent = text; };
    let saved = false;
    let imageReplaced = false;
    submit.disabled = true;
    errorEl.textContent = '';
    try {
        if (dirty.image) {
            step('Subiendo la imagen…');
            await uploadReplacementImage(key, editImageFile.files[0]);
            imageReplaced = saved = true;
            resetReplaceImage();
        }
        if (dirty.general || dirty.advanced) {
            step(dirty.general && locationChanged ? 'Guardando y ubicando en el mapa…' : 'Guardando datos…');
            await api('api/painting.php', { action: 'update', id: key, fields });
            editBaseline = fields;
            saved = true;
        }
        if (dirty.description) {
            step('Guardando la descripción…');
            for (const id of [...versionDeletes]) {
                await api('api/painting.php', { action: 'delete_description', id: key, description_id: id });
                versionDeletes.delete(id);
                versionEdits.delete(id);
                saved = true;
            }
            for (const [id, text] of [...versionEdits]) {
                await api('api/painting.php', { action: 'update_description', id: key, description_id: id, text });
                versionEdits.delete(id);
                saved = true;
            }
            const newText = document.getElementById('editDescText');
            if (newText.value.trim()) {
                await api('api/painting.php', { action: 'add_description', id: key, text: newText.value });
                newText.value = '';
                saved = true;
            }
        }
        closeEdit(true);
        await afterPaintingChange('💾 Cambios guardados');
        if (imageReplaced && viewerIndex !== null && paintingKey(paintings[viewerIndex]) === key) showInViewer(viewerIndex);
        const painting = paintings.find(p => paintingKey(p) === key);
        if (dirty.general && locationChanged && painting && painting.location && (!painting.geo || painting.geo.status !== 'ok')) {
            showToast('💾 Guardado, pero la nueva ubicación no se encontró en el mapa');
        }
    } catch (error) {
        errorEl.textContent = '⚠ ' + error.message + (saved ? ' (lo anterior sí se guardó)' : '');
        if (saved) {
            // Part of it was applied: reload so the editor shows the real state; what failed stays pending
            try { await refreshLibrary(); } catch (ignored) { /* keep the error visible */ }
            if (editingKey === key) {
                renderEditVersions();
                if (imageReplaced) { resetReplaceImage(); renderEditTags(); }
            }
        }
    } finally {
        submit.textContent = '💾 Guardar';
        updateEditDirty();
    }
});

function setAiStatus(text, isError = false, log = null) {
    const el = document.getElementById('editAiStatus');
    el.classList.toggle('error', isError);
    el.textContent = text;
    if (log) {
        const pre = document.createElement('pre');
        pre.textContent = log;
        el.appendChild(pre);
    }
}

// Asking an AI is an action (a background job), not a pending change: it adds the version as soon as it finishes
async function requestAiDescription() {
    const submit = document.getElementById('editAiSubmit');
    const paintingKeyForJob = editingKey;
    submit.disabled = true;
    aiJobRunning = true;
    setAiStatus('⏳ Pidiendo la descripción…');
    try {
        const { job } = await api('api/painting.php', {
            action: 'request_description',
            id: paintingKeyForJob,
            provider: document.getElementById('editAiProvider').value,
            style: document.getElementById('editAiStyle').value,
            max_length: Number(document.getElementById('editAiLength').value) || null
        });
        for (;;) {
            await new Promise(r => setTimeout(r, 2000));
            const data = await api(`api/job.php?id=${encodeURIComponent(job)}`);
            if (data.state === 'processing') {
                if (data.last_line) setAiStatus('⏳ ' + data.last_line);
                continue;
            }
            if (data.state === 'done') {
                setAiStatus('✅ Descripción nueva añadida (ahora es la versión más reciente)');
                await afterPaintingChange('🤖 Descripción nueva añadida');
                if (editingKey === paintingKeyForJob && editModal.classList.contains('open')) {
                    renderEditVersions();
                    showEditTab('versions');
                }
            } else {
                setAiStatus('⚠ No se pudo generar la descripción', true, data.log);
            }
            break;
        }
    } catch (error) {
        setAiStatus('⚠ ' + error.message, true);
    } finally {
        aiJobRunning = false;
        submit.disabled = !(aiOptions && aiOptions.providers.length);
    }
}

// ===================== Users dashboard (superadmin) =====================
const usersModal = document.getElementById('usersModal');
let usersPage = 1;
let usersSearchTimer = null;
let usersRequest = 0;

function formatDate(iso, withTime = false) {
    if (!iso) return '<span class="muted">—</span>';
    const date = new Date(iso);
    if (isNaN(date)) return '<span class="muted">—</span>';
    return esc(withTime
        ? date.toLocaleString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
        : date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }));
}

function openUsers() {
    usersPage = 1;
    document.getElementById('usersSearch').value = '';
    usersModal.classList.add('open');
    loadUsers();
}

function closeUsers() {
    usersModal.classList.remove('open');
}

usersModal.addEventListener('click', (e) => {
    if (e.target === usersModal) closeUsers();
});

document.getElementById('usersSearch').addEventListener('input', () => {
    clearTimeout(usersSearchTimer);
    usersSearchTimer = setTimeout(() => {
        usersPage = 1;
        loadUsers();
    }, 250);
});

function changeUsersPage(delta) {
    usersPage += delta;
    loadUsers();
}

async function loadUsers() {
    const request = ++usersRequest; // ignore late responses of older searches
    const query = document.getElementById('usersSearch').value.trim();
    const body = document.getElementById('usersBody');
    body.style.opacity = '0.5';
    let data;
    try {
        data = await api(`api/admin.php?page=${usersPage}&q=${encodeURIComponent(query)}`);
    } catch (error) {
        if (request === usersRequest) {
            body.style.opacity = '';
            body.innerHTML = `<tr><td colspan="6" class="error">${esc(error.message)}</td></tr>`;
        }
        return;
    }
    if (request !== usersRequest) return;
    body.style.opacity = '';
    usersPage = data.page;

    document.getElementById('usersStats').innerHTML = `
        <div class="users-stat"><strong>${data.stats.total}</strong><span>Usuarios</span></div>
        <div class="users-stat"><strong>${data.stats.uploaders}</strong><span>Superusuarios</span></div>
        <div class="users-stat"><strong>${data.stats.new_30_days}</strong><span>Nuevos (30 días)</span></div>
    `;

    body.innerHTML = data.users.length === 0
        ? `<tr><td colspan="6" class="muted" style="text-align: center; padding: 24px;">${query ? 'Ningún usuario coincide con la búsqueda' : 'No hay usuarios'}</td></tr>`
        : data.users.map(u => `
            <tr>
                <td><strong>${esc(u.username)}</strong>${u.is_owner ? '<span class="users-badge">propietario</span>' : ''}${u.username === account.user.username ? ' <span class="muted">(tú)</span>' : ''}</td>
                <td class="hide-mobile">${formatDate(u.created_at)}</td>
                <td class="hide-mobile">${formatDate(u.last_login_at, true)}</td>
                <td class="num">${u.seen_count}</td>
                <td class="num">${u.favorites_count}</td>
                <td class="num">
                    <label class="switch" title="${u.is_owner ? 'El propietario siempre es superusuario' : (u.username === account.user.username ? 'No puedes quitarte tus propios permisos' : 'Superusuario: subir y editar cuadros, gestionar usuarios y la IA')}">
                        <input type="checkbox" ${u.is_superadmin ? 'checked' : ''} ${u.is_owner || u.username === account.user.username ? 'disabled' : ''}
                               aria-label="${esc(u.username)} es superusuario"
                               data-user-id="${u.id}" data-username="${esc(u.username)}" onchange="setUploadPermission(this)">
                        <span></span>
                    </label>
                </td>
            </tr>
        `).join('');

    const shown = data.users.length;
    const from = shown ? (data.page - 1) * data.per_page + 1 : 0;
    document.getElementById('usersPageInfo').textContent =
        `${from}–${from + shown - (shown ? 1 : 0)} de ${data.matching} · página ${data.page} de ${data.pages}`;
    document.getElementById('usersPrev').disabled = data.page <= 1;
    document.getElementById('usersNext').disabled = data.page >= data.pages;
}

async function setUploadPermission(checkbox) {
    const value = checkbox.checked;
    checkbox.disabled = true;
    try {
        await api('api/admin.php', { action: 'set_upload', user_id: Number(checkbox.dataset.userId), value });
        showToast(value
            ? `🛠️ ${checkbox.dataset.username} ahora es superusuario`
            : `${checkbox.dataset.username} ya no es superusuario`);
        loadUsers(); // refresh the counters
    } catch (error) {
        checkbox.checked = !value;
        checkbox.disabled = false;
        showToast('⚠ ' + error.message);
    }
}

// ---- Description versions (edit / delete) and painting deletion ----
let editVersions = [];

// Fill the version dropdown; keepId keeps the same version selected. Pending edits/deletions are kept
function renderEditVersions(keepId = null) {
    const painting = editingPainting();
    if (!painting) return;
    const previous = currentEditVersion();
    editVersions = [];
    Object.entries(painting.descriptions || {}).forEach(([lang, list]) => {
        (Array.isArray(list) ? list : [list]).forEach(d => editVersions.push({ ...d, language: d.language || lang }));
    });
    const ids = new Set(editVersions.map(d => d.description_id));
    [...versionEdits.keys()].forEach(id => { if (!ids.has(id)) versionEdits.delete(id); });
    [...versionDeletes].forEach(id => { if (!ids.has(id)) versionDeletes.delete(id); });
    const hasVersions = editVersions.length > 0;
    document.getElementById('editVersionSelect').style.display = hasVersions ? '' : 'none';
    document.getElementById('editVersionBox').style.display = hasVersions ? '' : 'none';
    document.getElementById('editVersionsEmpty').style.display = hasVersions ? 'none' : '';
    if (!hasVersions) return;

    document.getElementById('editVersionSelect').innerHTML = editVersions.map((d, i) => `<option value="${i}"></option>`).join('');
    refreshVersionOptions();
    const wanted = keepId || (previous && previous.description_id);
    const keep = editVersions.findIndex(d => d.description_id === wanted);
    document.getElementById('editVersionSelect').value = String(keep === -1 ? 0 : keep);
    showEditVersion();
}

function refreshVersionOptions() {
    const options = document.getElementById('editVersionSelect').options;
    editVersions.forEach((d, i) => {
        if (!options[i]) return;
        const mark = versionDeletes.has(d.description_id) ? ' · 🗑️ se borrará' : versionEdits.has(d.description_id) ? ' · ✏️ editada' : '';
        options[i].textContent = `Versión ${i + 1}${i === 0 ? ' (por defecto)' : ''} · ${d.comment_creator || 'desconocido'} · `
            + `${d.generated_at ? new Date(d.generated_at).toLocaleDateString('es-ES') : 'sin fecha'}${mark}`;
    });
}

function currentEditVersion() {
    return editVersions[Number(document.getElementById('editVersionSelect').value)];
}

function showEditVersion() {
    const d = currentEditVersion();
    if (!d) return;
    const index = editVersions.indexOf(d);
    const deleting = versionDeletes.has(d.description_id);
    document.getElementById('editVersionHead').innerHTML =
        `<strong>Versión ${index + 1}</strong>${index === 0 ? '<span class="edit-version-default">se muestra por defecto</span>' : ''}<br>`
        + `${esc(d.comment_creator || 'Creador desconocido')} · ${d.generated_at ? esc(new Date(d.generated_at).toLocaleString('es-ES')) : 'fecha desconocida'}`
        + (d.description_style ? ` · estilo: ${esc(d.description_style)}` : '');
    const textarea = document.getElementById('editVersionText');
    textarea.value = versionEdits.has(d.description_id) ? versionEdits.get(d.description_id) : (d.description || '');
    textarea.scrollTop = 0;
    textarea.disabled = deleting;
    textarea.classList.toggle('to-delete', deleting);
    document.getElementById('editVersionDelete').textContent = deleting ? '↩️ No borrar' : '🗑️ Borrar versión';
    document.getElementById('editVersionNote').textContent = deleting
        ? 'Se borrará al pulsar «Guardar».'
        : versionEdits.has(d.description_id) ? 'Editada: se guardará al pulsar «Guardar».' : '';
}

document.getElementById('editVersionText').addEventListener('input', (e) => {
    const d = currentEditVersion();
    if (!d) return;
    if (e.target.value === (d.description || '')) versionEdits.delete(d.description_id);
    else versionEdits.set(d.description_id, e.target.value);
    document.getElementById('editVersionNote').textContent = versionEdits.has(d.description_id) ? 'Editada: se guardará al pulsar «Guardar».' : '';
    refreshVersionOptions();
});

function toggleDeleteVersion() {
    const d = currentEditVersion();
    if (!d) return;
    if (versionDeletes.has(d.description_id)) versionDeletes.delete(d.description_id);
    else versionDeletes.add(d.description_id);
    showEditVersion();
    refreshVersionOptions();
    updateEditDirty();
}

// Deleting requires typing the painting title exactly (surrounding spaces ignored)
function resetDeleteConfirm() {
    const painting = editingPainting();
    document.getElementById('editDeleteExpected').textContent = painting ? (painting.title || 'Sin título') : '';
    document.getElementById('editDeleteConfirm').value = '';
    updateDeleteButton();
}

function updateDeleteButton() {
    const painting = editingPainting();
    const typed = document.getElementById('editDeleteConfirm').value.trim();
    document.getElementById('editDeleteButton').disabled = !painting || typed !== (painting.title || 'Sin título').trim();
}

async function deletePainting() {
    const painting = editingPainting();
    if (!painting) return;
    updateDeleteButton();
    const button = document.getElementById('editDeleteButton');
    if (button.disabled) return;
    button.disabled = true;
    try {
        await api('api/painting.php', { action: 'delete_painting', id: editingKey });
    } catch (error) {
        showToast('⚠ ' + error.message);
        button.disabled = false;
        return;
    }
    const index = paintings.indexOf(painting);
    closeEdit(true);
    if (viewerIndex === index) closeViewer();
    if (selectedIndex === index) closeDetail();
    await afterPaintingChange(`🗑️ «${painting.title || 'Sin título'}» eliminado de la colección`);
}

// ---- Editor: tags ----
let editTags = { periods: [], themes: [] };
const FORMAT_NAMES = { landscape: 'horizontal', portrait: 'vertical', square: 'cuadrado' };

function renderEditTags() {
    const painting = editingPainting();
    const box = document.getElementById('editTags');
    if (!painting) return;
    const vocabulary = aiOptions && aiOptions.vocabulary;
    if (!vocabulary) {
        box.innerHTML = '<div class="edit-status">Cargando tags…</div>';
        return;
    }
    const chips = (kind, list) => list.map(tag =>
        `<button type="button" class="edit-chip ${kind}" data-kind="${kind}" data-tag="${esc(tag)}" onclick="toggleEditTag(this)">${esc(tag)}</button>`
    ).join('');
    box.innerHTML = `
        <div class="edit-field"><span>Formato</span>
            <div class="edit-chips"><span class="tag-chip tag-format">${FORMAT_NAMES[painting.orientation] || '—'}</span>
            <span class="edit-status">se calcula a partir de la imagen</span></div>
        </div>
        <div class="edit-field"><span>Época (1 o 2)</span><div class="edit-chips">${chips('periods', vocabulary.periods)}</div></div>
        <div class="edit-field"><span>Temática (1 o más)</span><div class="edit-chips">${chips('themes', vocabulary.themes)}</div></div>
        <div class="edit-status edit-tags-hint" id="editTagsHint"></div>
        <div class="edit-chips">
            <button type="button" class="btn-small" id="editTagsSuggest" onclick="suggestTags()">🏷️ Sugerir tags con IA</button>
            <span class="edit-status" id="editTagsSuggestStatus"></span>
        </div>
    `;
    updateEditTagChips();
}

// Ask the processing AI for period/theme only (image + title/artist/year); result is a suggestion to review
async function suggestTags() {
    const key = editingKey;
    const button = document.getElementById('editTagsSuggest');
    const status = document.getElementById('editTagsSuggestStatus');
    const setStatus = (text) => { if (editingKey === key) status.textContent = text; };
    button.disabled = true;
    setStatus('⏳ Preguntando a la IA…');
    try {
        const { job } = await api('api/painting.php', { action: 'suggest_tags', id: key });
        for (;;) {
            await new Promise(r => setTimeout(r, 2000));
            const data = await api(`api/job.php?id=${encodeURIComponent(job)}`);
            if (data.state === 'processing') continue;
            if (editingKey !== key) return; // the editor moved to another painting meanwhile
            if (data.state === 'done' && data.result) {
                const vocabulary = aiOptions.vocabulary;
                const periods = (data.result.periods || []).slice(0, vocabulary.max_periods);
                const themes = (data.result.themes || []).slice(0, vocabulary.max_tags - 1 - periods.length);
                editTags = { periods, themes };
                updateEditTagChips();
                setStatus(`✨ Sugerencia de ${data.result.provider || 'la IA'}: revísala y pulsa «Guardar»`);
            } else {
                setStatus(/429|quota|cuota/i.test(data.log || '')
                    ? '⚠ La IA ha agotado su cuota diaria. Prueba con otra en «🤖 IA de procesado».'
                    : '⚠ La IA no devolvió tags válidos.');
            }
            break;
        }
    } catch (error) {
        setStatus('⚠ ' + error.message);
    } finally {
        if (editingKey === key) button.disabled = false;
    }
}

function toggleEditTag(button) {
    const list = editTags[button.dataset.kind];
    const tag = button.dataset.tag;
    const index = list.indexOf(tag);
    if (index === -1) list.push(tag); else list.splice(index, 1);
    updateEditTagChips();
}

function updateEditTagChips() {
    const vocabulary = aiOptions && aiOptions.vocabulary;
    if (!vocabulary) return;
    const maxTopical = vocabulary.max_tags - 1; // the format tag is always there
    const total = editTags.periods.length + editTags.themes.length;
    document.querySelectorAll('#editTags .edit-chip').forEach(chip => {
        const selected = editTags[chip.dataset.kind].includes(chip.dataset.tag);
        chip.classList.toggle('selected', selected);
        chip.disabled = !selected && (total >= maxTopical
            || (chip.dataset.kind === 'periods' && editTags.periods.length >= vocabulary.max_periods));
    });
    const missing = [];
    if (!editTags.periods.length) missing.push('una época');
    if (!editTags.themes.length) missing.push('una temática');
    const hint = document.getElementById('editTagsHint');
    hint.classList.toggle('warn', missing.length > 0);
    hint.textContent = `${total + 1} de ${vocabulary.max_tags} tags (incluido el formato)`
        + (missing.length ? ` · ⚠ falta al menos ${missing.join(' y ')}` : '');
    updateEditDirty();
}

// ---- Editor: replace the image (no AI involved) ----
const editImageFile = document.getElementById('editImageFile');

function resetReplaceImage() {
    const painting = editingPainting();
    editImageFile.value = '';
    document.getElementById('editImagePreview').innerHTML = '';
    document.getElementById('editImageStatus').textContent = '';
    document.getElementById('editImageCurrent').textContent = painting
        ? `Actual: ${painting.file_width || '?'} × ${painting.file_height || '?'} px`
            + (painting.file_size ? ` · ${(painting.file_size / 1024 / 1024).toFixed(2)} MB` : '')
            + '. Se sustituye solo el archivo: título, descripciones y tags no cambian y no se consulta a ninguna IA.'
        : '';
    if (editBaseline) updateEditDirty();
}

// Drop zone: click/keyboard opens the picker; dropping is handled here (the page-wide handlers only
// accept drops while the "+" upload panel is open, so stop the events from reaching them)
const editImageDrop = document.getElementById('editImageDrop');
editImageDrop.addEventListener('click', () => editImageFile.click());
editImageDrop.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        editImageFile.click();
    }
});
['dragenter', 'dragover'].forEach(type => editImageDrop.addEventListener(type, (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
    editImageDrop.classList.add('over');
}));
editImageDrop.addEventListener('dragleave', (e) => {
    if (!editImageDrop.contains(e.relatedTarget)) editImageDrop.classList.remove('over');
});
editImageDrop.addEventListener('drop', (e) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    editImageDrop.classList.remove('over');
    const file = [...e.dataTransfer.files].find(f => f.type.startsWith('image/') || IMAGE_NAME_RE.test(f.name));
    const status = document.getElementById('editImageStatus');
    if (!file) {
        status.classList.add('error');
        status.textContent = '⚠ Eso no parece una imagen';
        return;
    }
    status.classList.remove('error');
    const transfer = new DataTransfer();
    transfer.items.add(file);
    editImageFile.files = transfer.files;
    editImageFile.dispatchEvent(new Event('change'));
});

editImageFile.addEventListener('change', () => {
    const file = editImageFile.files[0];
    const preview = document.getElementById('editImagePreview');
    document.getElementById('editImageStatus').textContent = '';
    updateEditDirty();
    if (!file) {
        preview.innerHTML = '';
        return;
    }
    const url = URL.createObjectURL(file);
    preview.innerHTML = `<img alt=""><span>${esc(file.name)}<br><span class="edit-status">${(file.size / 1024 / 1024).toFixed(2)} MB</span>`
        + `<br><span class="edit-status">Se sustituirá al pulsar «Guardar».</span></span>`
        + `<button type="button" class="btn-small" onclick="resetReplaceImage()">✕ Descartar</button>`;
    const img = preview.querySelector('img');
    img.onload = () => {
        const painting = editingPainting();
        const smaller = painting && painting.file_width && img.naturalWidth * img.naturalHeight < painting.file_width * painting.file_height;
        preview.querySelector('.edit-status').textContent =
            `${img.naturalWidth} × ${img.naturalHeight} px · ${(file.size / 1024 / 1024).toFixed(2)} MB`
            + (smaller ? ' · ⚠ tiene menos resolución que la actual' : '');
        URL.revokeObjectURL(url);
    };
    img.src = url;
});

function showEditTab(name) {
    document.querySelectorAll('#editModal .edit-tab').forEach(tab => {
        const active = tab.dataset.tab === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active);
    });
    document.querySelectorAll('#editModal .edit-tab-panel').forEach(panel => {
        panel.hidden = panel.dataset.panel !== name;
    });
}

// ---- Pending review: run the AI identification again ----
async function reprocessPainting(key) {
    const banners = () => [...document.querySelectorAll('.pending-banner')].filter(b => b.dataset.key === key);
    const setStatus = (text, busy) => banners().forEach(b => {
        b.querySelector('.pending-status').textContent = text;
        b.querySelector('button').disabled = busy;
    });
    setStatus('⏳ Pidiendo a la IA que identifique el cuadro…', true);
    try {
        const { job } = await api('api/reprocess.php', { id: key });
        for (;;) {
            await new Promise(r => setTimeout(r, 2500));
            const data = await api(`api/job.php?id=${encodeURIComponent(job)}`);
            if (data.state === 'processing') {
                if (data.last_line) setStatus('⏳ ' + data.last_line, true);
                continue;
            }
            if (data.state === 'done') {
                await afterPaintingChange('🤖 Cuadro identificado: ' + (data.result.title || ''));
            } else {
                const quota = /429|quota|cuota/i.test(data.log || '');
                setStatus(quota
                    ? '⚠ La IA ha agotado su cuota diaria. Vuelve a intentarlo más tarde (normalmente al día siguiente).'
                    : '⚠ La IA no pudo identificarlo. Puedes completar los datos a mano desde ✏️.', false);
            }
            break;
        }
    } catch (error) {
        setStatus('⚠ ' + error.message, false);
    }
}

// ===================== AI used for processing (superadmin) =====================
const aiModal = document.getElementById('aiModal');
let aiSettings = null;

async function openAiSettings() {
    aiModal.classList.add('open');
    document.getElementById('aiError').textContent = '';
    document.getElementById('aiOllamaInfo').textContent = '⏳ Consultando los modelos de Ollama…';
    document.getElementById('aiSubmit').disabled = true;
    try {
        aiSettings = await api('api/settings.php');
    } catch (error) {
        document.getElementById('aiError').textContent = error.message;
        return;
    }
    document.getElementById('aiGeminiModel').innerHTML = aiSettings.gemini_models
        .map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
    document.getElementById('aiGeminiModel').value = aiSettings.gemini_model;
    document.getElementById('aiStyle').value = aiSettings.description_style || '';
    document.getElementById('aiMaxLength').value = aiSettings.description_max_length || 1000;

    const ollamaSelect = document.getElementById('aiOllamaModel');
    ollamaSelect.innerHTML = aiSettings.ollama_models.map(m => `
        <option value="${esc(m.name)}">${esc(m.name)}${m.size ? ` · ${esc(m.size)}` : ''}${m.vision ? ' · 👁️ ve imágenes' : ''}${m.cloud ? ' · ☁️ nube' : ''}</option>
    `).join('');
    if (aiSettings.ollama_models.some(m => m.name === aiSettings.ollama_model)) ollamaSelect.value = aiSettings.ollama_model;

    const ollamaRadio = aiModal.querySelector('input[value="ollama"]');
    ollamaRadio.disabled = !aiSettings.ollama_reachable || aiSettings.ollama_models.length === 0;
    aiModal.querySelector(`input[value="${aiSettings.provider}"]`).checked = true;
    updateAiForm();
    document.getElementById('aiSubmit').disabled = false;
}

function closeAiSettings() {
    aiModal.classList.remove('open');
}

function updateAiForm() {
    const provider = (aiModal.querySelector('input[name="aiProvider"]:checked') || {}).value;
    document.getElementById('aiGeminiModel').disabled = provider !== 'gemini';
    document.getElementById('aiOllamaModel').disabled = provider !== 'ollama';
    const info = document.getElementById('aiOllamaInfo');
    if (!aiSettings) return;
    if (!aiSettings.ollama_reachable) {
        info.textContent = `⚠ No se puede conectar con Ollama (${aiSettings.ollama_host}).`;
        return;
    }
    const model = aiSettings.ollama_models.find(m => m.name === document.getElementById('aiOllamaModel').value);
    info.textContent = provider === 'ollama' && model && !model.vision
        ? '⚠ Este modelo no ve imágenes: solo podrá identificar el cuadro por el nombre del archivo.'
        : `${aiSettings.ollama_models.length} modelos disponibles en ${aiSettings.ollama_host}`;
}

aiModal.querySelectorAll('input[name="aiProvider"]').forEach(r => r.addEventListener('change', updateAiForm));
document.getElementById('aiOllamaModel').addEventListener('change', updateAiForm);
aiModal.addEventListener('click', (e) => {
    if (e.target === aiModal) closeAiSettings();
});

document.getElementById('aiForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const provider = (aiModal.querySelector('input[name="aiProvider"]:checked') || {}).value;
    const submit = document.getElementById('aiSubmit');
    submit.disabled = true;
    document.getElementById('aiError').textContent = '';
    try {
        await api('api/settings.php', {
            provider,
            gemini_model: document.getElementById('aiGeminiModel').value,
            ollama_model: document.getElementById('aiOllamaModel').value,
            description_style: document.getElementById('aiStyle').value,
            description_max_length: Number(document.getElementById('aiMaxLength').value)
        });
        aiOptions = null; // the edit form re-reads the provider labels
        closeAiSettings();
        showToast(provider === 'ollama'
            ? `🖥️ Procesando con Ollama (${document.getElementById('aiOllamaModel').value})`
            : `☁️ Procesando con Gemini (${document.getElementById('aiGeminiModel').value})`);
    } catch (error) {
        document.getElementById('aiError').textContent = error.message;
    } finally {
        submit.disabled = false;
    }
});

// ===================== Collections =====================
var myCollections = [];      // [{id, name, owner, mine, painting_ids: []}]
var activeCollection = null; // {id, name, owner, mine, painting_ids: Set}
const collectionModal = document.getElementById('collectionModal');
const collectionMenu = document.getElementById('collectionMenu');
let collectionModalMode = 'create';
let collectionPendingKey = null; // painting to add right after creating a collection from the 📁 menu

function customCollections() {
    return myCollections.filter(c => c.kind !== 'favorites');
}

function collectionIcon(collection) {
    if (collection.kind === 'favorites') return '❤️';
    return collection.mine ? '📁' : '🔗';
}

// Keep the built-in ❤️ Favoritos collection in sync with the heart buttons
function syncFavoritesCollection(key, on) {
    const favorites = myCollections.find(c => c.kind === 'favorites');
    if (favorites) {
        favorites.painting_ids = on
            ? [...new Set([...favorites.painting_ids, key])]
            : favorites.painting_ids.filter(id => id !== key);
    }
    if (activeCollection && activeCollection.mine && activeCollection.kind === 'favorites') {
        if (on) activeCollection.painting_ids.add(key); else activeCollection.painting_ids.delete(key);
        applyFilters();
    }
    renderCollectionBar();
}

function updateTotalCount() {
    const el = document.getElementById('totalCount');
    if (activeCollection) {
        const n = paintings.filter(p => activeCollection.painting_ids.has(p.id)).length;
        el.textContent = `${collectionIcon(activeCollection)} ${activeCollection.name} · ${n} obra${n !== 1 ? 's' : ''}`
            + (activeCollection.mine || activeCollection.kind === 'favorites' ? '' : ` · de ${activeCollection.owner}`);
    } else {
        el.textContent = `${paintings.length} obra${paintings.length !== 1 ? 's' : ''} en la galería`;
    }
}

async function fetchCollections() {
    if (!account.user) {
        myCollections = [];
    } else {
        try {
            myCollections = (await api('api/collections.php')).collections;
        } catch (error) {
            console.warn('No se pudieron cargar las colecciones', error);
            myCollections = [];
        }
    }
    if (activeCollection && activeCollection.mine) {
        const fresh = myCollections.find(c => c.id === activeCollection.id);
        activeCollection = fresh ? { ...fresh, painting_ids: new Set(fresh.painting_ids) } : null;
    }
    renderCollectionBar();
}

function renderCollectionBar() {
    const select = document.getElementById('collectionSelect');
    const options = [`<option value="">🖼️ Todas las obras</option>`]
        .concat(myCollections.map(c => `<option value="${esc(c.id)}">${collectionIcon(c)} ${esc(c.name)} (${c.painting_ids.length})</option>`));
    if (activeCollection && !activeCollection.mine) {
        options.push(`<option value="${esc(activeCollection.id)}">${collectionIcon(activeCollection)} ${esc(activeCollection.name)}</option>`);
    }
    select.innerHTML = options.join('');
    select.value = activeCollection ? activeCollection.id : '';
    select.hidden = options.length === 1;
    document.getElementById('collectionManage').hidden = !(activeCollection && activeCollection.mine);
    updateTotalCount();
}

async function setActiveCollection(id, { quiet = false, apply = true } = {}) {
    let next = null;
    if (id) {
        const mine = myCollections.find(c => c.id === id);
        if (mine) {
            next = mine;
        } else {
            try {
                next = await api(`api/collections.php?id=${encodeURIComponent(id)}`);
            } catch (error) {
                if (!quiet) showToast('⚠ ' + error.message);
            }
        }
    }
    activeCollection = next ? { ...next, painting_ids: new Set(next.painting_ids) } : null;
    if (activeCollection) localStorage.setItem('activeCollection', activeCollection.id);
    else localStorage.removeItem('activeCollection');
    renderCollectionBar();
    if (apply) applyFilters();
}

// ---- Create / rename / share / delete ----
function createCollection(addKey = null) {
    if (!account.user) {
        openAuth('login');
        showToast('Inicia sesión para crear colecciones');
        return;
    }
    collectionPendingKey = addKey;
    openCollectionModal('create');
}

function openCollectionModal(mode) {
    collectionModalMode = mode;
    const manage = mode === 'manage';
    const builtIn = manage && activeCollection.kind === 'favorites';
    document.getElementById('collectionModalTitle').textContent = manage ? `${collectionIcon(activeCollection)} ${activeCollection.name}` : '📁 Nueva colección';
    document.getElementById('collectionForm').hidden = builtIn;
    document.getElementById('collectionDelete').hidden = builtIn;
    document.getElementById('collectionSubmit').textContent = manage ? 'Renombrar' : 'Crear colección';
    document.getElementById('collectionName').value = manage ? activeCollection.name : '';
    document.getElementById('collectionError').textContent = '';
    document.getElementById('collectionManageExtra').hidden = !manage;
    const del = document.getElementById('collectionDelete');
    del.dataset.armed = '';
    del.textContent = '🗑️ Borrar colección';
    collectionModal.classList.add('open');
    if (!builtIn) document.getElementById('collectionName').focus();
}

function closeCollectionModal() {
    collectionModal.classList.remove('open');
    collectionPendingKey = null;
}

collectionModal.addEventListener('click', (e) => {
    if (e.target === collectionModal) closeCollectionModal();
});

document.getElementById('collectionForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const submit = document.getElementById('collectionSubmit');
    const name = document.getElementById('collectionName').value;
    submit.disabled = true;
    document.getElementById('collectionError').textContent = '';
    try {
        if (collectionModalMode === 'manage') {
            await api('api/collections.php', { action: 'rename', id: activeCollection.id, name });
            await fetchCollections();
            showToast('✏️ Colección renombrada');
        } else {
            const created = await api('api/collections.php', { action: 'create', name });
            if (collectionPendingKey) {
                await api('api/collections.php', { action: 'toggle', id: created.id, painting_id: collectionPendingKey, value: true });
            }
            await fetchCollections();
            showToast(collectionPendingKey
                ? `📁 Añadido a la nueva colección «${created.name}»`
                : `📁 Colección «${created.name}» creada: añade cuadros con el botón 📁 de cada cuadro`);
            if (collectionPendingKey) refreshMarkViews();
            else await setActiveCollection(created.id);
        }
        closeCollectionModal();
    } catch (error) {
        document.getElementById('collectionError').textContent = error.message;
    } finally {
        submit.disabled = false;
    }
});

async function copyCollectionLink() {
    const url = `${location.origin}${location.pathname}?coleccion=${encodeURIComponent(activeCollection.id)}`;
    if (await copyText(url)) showToast('🔗 Enlace de la colección copiado');
    else window.prompt('Copia el enlace:', url);
}

// Two clicks to delete (no pop-up)
async function deleteCollection() {
    const button = document.getElementById('collectionDelete');
    if (!button.dataset.armed) {
        button.dataset.armed = '1';
        button.textContent = '⚠️ Pulsa otra vez para borrarla (los cuadros no se borran)';
        return;
    }
    button.disabled = true;
    try {
        const name = activeCollection.name;
        await api('api/collections.php', { action: 'delete', id: activeCollection.id });
        closeCollectionModal();
        await fetchCollections();
        await setActiveCollection('');
        refreshMarkViews();
        showToast(`🗑️ Colección «${name}» borrada`);
    } catch (error) {
        document.getElementById('collectionError').textContent = error.message;
    } finally {
        button.disabled = false;
    }
}

// ---- 📁 menu: add/remove the painting to/from my collections ----
let collectionMenuKey = null;

function openCollectionMenu(button) {
    if (!account.user) {
        openAuth('login');
        return;
    }
    if (!collectionMenu.hidden && collectionMenuKey === button.dataset.key) {
        closeCollectionMenu();
        return;
    }
    collectionMenuKey = button.dataset.key;
    renderCollectionMenu();
    collectionMenu.hidden = false;
    const rect = button.getBoundingClientRect();
    const width = collectionMenu.offsetWidth;
    const height = collectionMenu.offsetHeight;
    const left = Math.min(Math.max(8, rect.left), innerWidth - width - 8);
    const top = rect.bottom + 6 + height > innerHeight ? rect.top - height - 6 : rect.bottom + 6;
    collectionMenu.style.left = left + 'px';
    collectionMenu.style.top = Math.max(8, top) + 'px';
}

function renderCollectionMenu() {
    const key = collectionMenuKey;
    collectionMenu.innerHTML = `
        <div class="collection-menu-title">Añadir a colección</div>
        ${customCollections().map(c => `
            <label><input type="checkbox" data-id="${esc(c.id)}" ${c.painting_ids.includes(key) ? 'checked' : ''} onchange="toggleInCollection(this)"> ${esc(c.name)}</label>
        `).join('') || '<div class="collection-menu-title" style="text-transform: none; font-weight: 400;">Todavía no tienes colecciones</div>'}
        <button type="button" class="collection-menu-new" onclick="closeCollectionMenu(); createCollection('${esc(key)}')">+ Nueva colección…</button>
    `;
}

function closeCollectionMenu() {
    collectionMenu.hidden = true;
    collectionMenuKey = null;
}

document.addEventListener('click', (e) => {
    if (!collectionMenu.hidden && !collectionMenu.contains(e.target) && !e.target.closest('.icon-btn.coll')) closeCollectionMenu();
});
window.addEventListener('resize', closeCollectionMenu);
document.addEventListener('scroll', closeCollectionMenu, true);

async function toggleInCollection(checkbox) {
    const key = collectionMenuKey;
    const collection = myCollections.find(c => c.id === checkbox.dataset.id);
    const value = checkbox.checked;
    checkbox.disabled = true;
    try {
        await api('api/collections.php', { action: 'toggle', id: collection.id, painting_id: key, value });
        collection.painting_ids = value
            ? [...new Set([...collection.painting_ids, key])]
            : collection.painting_ids.filter(id => id !== key);
        if (activeCollection && activeCollection.id === collection.id) {
            if (value) activeCollection.painting_ids.add(key); else activeCollection.painting_ids.delete(key);
            applyFilters();
        }
        renderCollectionBar();
        refreshMarkViews();
        showToast(value ? `📁 Añadido a «${collection.name}»` : `Quitado de «${collection.name}»`);
    } catch (error) {
        checkbox.checked = !value;
        showToast('⚠ ' + error.message);
    } finally {
        checkbox.disabled = false;
    }
}

// Update the 📁 buttons (filled when the painting is in any of my collections)
function refreshMarkViews() {
    document.querySelectorAll('.icon-btn.coll').forEach(btn => {
        btn.classList.toggle('on', customCollections().some(c => c.painting_ids.includes(btn.dataset.key)));
    });
}

// Initialize
loadLibrary();
