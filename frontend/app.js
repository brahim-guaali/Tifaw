function app() {
    return {
        view: 'overview',
        darkMode: false,
        sidebarOpen: false,

        // Overview
        overview: null,
        overviewLoading: true,

        // Photos
        photos: [],
        photosTotal: 0,
        photosFilters: { people: [], categories: [] },
        photosActivePerson: null,
        photosActiveCategory: null,
        photosLoading: false,
        photosOffset: 0,

        // People
        people: { named: [], unnamed: [] },
        peopleLoading: false,
        activePerson: null,
        personPhotos: [],

        // Documents
        documentGroups: [],
        documentsLoading: false,
        activeDocGroup: null,
        activeDocFiles: [],

        // Search
        searchQuery: '',
        searchResults: [],

        // Chat
        chatMessages: [],
        chatInput: '',
        chatLoading: false,

        // Renames
        renameProposals: [],

        // Projects
        projects: [],
        projectsLoading: false,

        // Config
        configData: {},
        configSaving: false,
        reindexingAll: false,

        // Faces
        fileFaces: [],
        facesLoading: false,
        labelInput: {},

        // Merge picker
        mergePickerOpen: false,
        mergePickerList: [],

        // File detail
        selectedFile: null,

        // Folder picker
        folderPicker: { open: false, path: '', dirs: [], parent: null, target: null, index: null },

        // Toast
        toast: { show: false, message: '', type: 'success' },

        // Status (polled)
        status: { ollama_connected: false, total_files: 0, indexed_files: 0, pending_files: 0, pending_renames: 0, queue_size: 0, watched_folders: [] },

        async init() {
            this.initTheme();
            this.loadOverview();
            this.refreshStatus();
            setInterval(() => this.refreshStatus(), 5000);
        },

        // ─── Theme ────────────────────────────────────────
        initTheme() {
            const stored = localStorage.getItem('theme');
            this.darkMode = stored === 'dark';
            this.applyTheme();
        },
        applyTheme() {
            if (this.darkMode) document.documentElement.classList.add('dark');
            else document.documentElement.classList.remove('dark');
        },
        toggleDarkMode() {
            this.darkMode = !this.darkMode;
            localStorage.setItem('theme', this.darkMode ? 'dark' : 'light');
            this.applyTheme();
        },

        // ─── Navigation ───────────────────────────────────
        navigate(v) {
            this.view = v;
            this.sidebarOpen = false;
            if (v === 'overview') this.loadOverview();
            if (v === 'photos') this.loadPhotos(true);
            if (v === 'people') this.loadPeople();
            if (v === 'documents') this.loadDocuments();
            if (v === 'projects') this.loadProjects();
            if (v === 'renames') this.loadRenames();
            if (v === 'settings') this.loadConfig();
        },

        // ─── Toast ────────────────────────────────────────
        showToast(message, type = 'success') {
            this.toast = { show: true, message, type };
            setTimeout(() => this.toast.show = false, 3000);
        },

        // ─── Status ───────────────────────────────────────
        async refreshStatus() {
            try {
                const r = await fetch('/api/status');
                this.status = await r.json();
            } catch (e) { }
        },

        // ─── Overview ─────────────────────────────────────
        async loadOverview() {
            this.overviewLoading = true;
            try {
                const r = await fetch('/api/overview');
                this.overview = await r.json();
                this.$nextTick(() => {
                    if (this.overview.photo_locations?.length) this.initMap(this.overview.photo_locations);
                    if (this.overview.calendar_heatmap) this.renderHeatmap(this.overview.calendar_heatmap);
                });
            } catch (e) {
                console.error('Overview failed:', e);
            }
            this.overviewLoading = false;
        },

        // Count-up animation helper
        countUp(el, target, duration = 1800) {
            if (!el || !target) return;
            let start = 0;
            const step = (ts) => {
                if (!start) start = ts;
                const p = Math.min((ts - start) / duration, 1);
                const eased = 1 - Math.pow(1 - p, 3);
                el.textContent = Math.floor(eased * target).toLocaleString();
                if (p < 1) requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        },

        formatSize(bytes) {
            if (!bytes) return '0 B';
            if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
            if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
            if (bytes >= 1024) return (bytes / 1024).toFixed(0) + ' KB';
            return bytes + ' B';
        },

        maxTimelineCount() {
            if (!this.overview?.timeline) return 1;
            return Math.max(...this.overview.timeline.map(t => t.count), 1);
        },

        // ─── Photos ───────────────────────────────────────
        async loadPhotos(reset = false) {
            if (reset) { this.photos = []; this.photosOffset = 0; }
            this.photosLoading = true;
            try {
                let url = `/api/photos?limit=60&offset=${this.photosOffset}`;
                if (this.photosActivePerson) url += `&person=${encodeURIComponent(this.photosActivePerson)}`;
                if (this.photosActiveCategory) url += `&category=${encodeURIComponent(this.photosActiveCategory)}`;
                const r = await fetch(url);
                const data = await r.json();
                if (reset) this.photos = data.photos;
                else this.photos = [...this.photos, ...data.photos];
                this.photosTotal = data.total;
                if (data.filters?.people) this.photosFilters.people = data.filters.people;
                if (data.filters?.categories) this.photosFilters.categories = data.filters.categories;
                this.photosOffset += data.photos.length;
            } catch (e) { console.error('Photos failed:', e); }
            this.photosLoading = false;
        },

        filterPhotosByPerson(name) {
            this.photosActivePerson = this.photosActivePerson === name ? null : name;
            this.loadPhotos(true);
        },

        filterPhotosByCategory(cat) {
            this.photosActiveCategory = this.photosActiveCategory === cat ? null : cat;
            this.loadPhotos(true);
        },

        onPhotosScroll(e) {
            const el = e.target;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 300 && !this.photosLoading && this.photos.length < this.photosTotal) {
                this.loadPhotos();
            }
        },

        // ─── People ───────────────────────────────────────
        async loadPeople() {
            this.peopleLoading = true;
            try {
                const r = await fetch('/api/people');
                const data = await r.json();
                this.people = data;
                this.activePerson = null;
                this.personPhotos = [];
            } catch (e) { console.error('People failed:', e); }
            this.peopleLoading = false;
        },

        async showPersonPhotos(name) {
            this.activePerson = name;
            try {
                const r = await fetch(`/api/people/${encodeURIComponent(name)}/photos`);
                const data = await r.json();
                this.personPhotos = data.photos || [];
            } catch (e) { console.error('Person photos failed:', e); }
        },

        async renamePersonPrompt() {
            if (!this.activePerson) return;
            const newName = prompt(`Rename "${this.activePerson}" to:`, this.activePerson);
            if (!newName || newName.trim() === this.activePerson) return;
            try {
                const r = await fetch(`/api/people/${encodeURIComponent(this.activePerson)}/rename`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ label: newName.trim() }),
                });
                const data = await r.json();
                this.showToast(`Renamed to ${newName.trim()} (${data.faces_updated} photos updated)`);
                this.activePerson = newName.trim();
                this.loadPeople();
            } catch (e) { this.showToast('Rename failed', 'error'); }
        },

        openMergePicker() {
            if (!this.activePerson) return;
            const all = [...(this.people.named || []), ...(this.people.unnamed || [])];
            this.mergePickerList = all.filter(p => p.name !== this.activePerson);
            this.mergePickerOpen = true;
        },
        async mergePerson(otherName) {
            if (!otherName || otherName === this.activePerson) return;
            this.mergePickerOpen = false;
            try {
                const r = await fetch(`/api/people/${encodeURIComponent(otherName)}/rename`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ label: this.activePerson }),
                });
                const data = await r.json();
                this.showToast(`Merged ${otherName} into ${this.activePerson} (${data.faces_updated} photos merged)`);
                await this.showPersonPhotos(this.activePerson);
                this.loadPeople();
            } catch (e) { this.showToast('Merge failed', 'error'); }
        },

        goToPerson(name) {
            this.view = 'photos';
            this.photosActivePerson = name;
            this.loadPhotos(true);
            this.sidebarOpen = false;
        },

        // ─── Documents ────────────────────────────────────
        async loadDocuments() {
            this.documentsLoading = true;
            this.activeDocGroup = null;
            this.activeDocFiles = [];
            try {
                const r = await fetch('/api/documents');
                const data = await r.json();
                this.documentGroups = data.groups || [];
            } catch (e) { console.error('Documents failed:', e); }
            this.documentsLoading = false;
        },

        async openDocGroup(name) {
            this.activeDocGroup = name;
            try {
                const r = await fetch(`/api/documents/${encodeURIComponent(name)}`);
                const data = await r.json();
                this.activeDocFiles = data.files || [];
            } catch (e) { console.error('Doc group failed:', e); }
        },

        // ─── Search ───────────────────────────────────────
        async performSearch() {
            if (!this.searchQuery.trim()) { this.searchResults = []; return; }
            try {
                const r = await fetch(`/api/search?q=${encodeURIComponent(this.searchQuery)}`);
                const data = await r.json();
                this.searchResults = data.results || [];
            } catch (e) { this.searchResults = []; }
        },

        // ─── Chat ─────────────────────────────────────────
        async sendChat() {
            const msg = this.chatInput.trim();
            if (!msg || this.chatLoading) return;
            this.chatMessages.push({ role: 'user', content: msg, timestamp: new Date().toISOString() });
            this.chatInput = '';
            this.chatLoading = true;
            this.$nextTick(() => { const el = document.getElementById('chatMessages'); if (el) el.scrollTop = el.scrollHeight; });
            try {
                const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) });
                const data = r.ok ? await r.json() : null;
                this.chatMessages.push({ role: 'assistant', content: data?.response || 'Something went wrong.', timestamp: new Date().toISOString() });
            } catch (e) {
                this.chatMessages.push({ role: 'assistant', content: 'Connection error.', timestamp: new Date().toISOString() });
            }
            this.chatLoading = false;
            this.$nextTick(() => { const el = document.getElementById('chatMessages'); if (el) el.scrollTop = el.scrollHeight; });
        },

        // ─── Renames ──────────────────────────────────────
        async loadRenames() {
            try {
                const r = await fetch('/api/renames/pending');
                const data = await r.json();
                this.renameProposals = data.proposals || [];
            } catch (e) { }
        },
        async approveRename(id) {
            await fetch(`/api/renames/${id}/approve`, { method: 'POST' });
            this.renameProposals = this.renameProposals.filter(p => p.file_id !== id);
            this.refreshStatus();
            this.showToast('File renamed');
        },
        async dismissRename(id) {
            await fetch(`/api/renames/${id}/dismiss`, { method: 'POST' });
            this.renameProposals = this.renameProposals.filter(p => p.file_id !== id);
        },
        async approveAllRenames() {
            for (const p of [...this.renameProposals]) await this.approveRename(p.file_id);
        },

        // ─── Projects ─────────────────────────────────────
        async loadProjects() {
            try {
                const r = await fetch('/api/projects');
                this.projects = (await r.json()).projects || [];
            } catch (e) { }
        },
        async scanProjects() {
            this.projectsLoading = true;
            try {
                const data = await (await fetch('/api/projects/scan', { method: 'POST' })).json();
                await this.loadProjects();
                this.showToast(`Found ${data.scanned} projects`);
            } catch (e) { this.showToast('Scan failed', 'error'); }
            this.projectsLoading = false;
        },

        // ─── Config ───────────────────────────────────────
        async loadConfig() {
            try { this.configData = await (await fetch('/api/config')).json(); } catch (e) { }
        },
        async saveConfig() {
            this.configSaving = true;
            try {
                const body = { watch_folders: this.configData.watch_folders, project_directories: this.configData.project_directories, rename_enabled: this.configData.rename?.enabled, rename_auto_approve: this.configData.rename?.auto_approve, cleanup_threshold_days: this.configData.cleanup?.threshold_days, max_file_size_mb: this.configData.indexing?.max_file_size_mb };
                const r = await fetch('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                if (r.ok) { this.showToast('Settings saved'); this.refreshStatus(); }
                else this.showToast('Save failed', 'error');
            } catch (e) { this.showToast('Save failed', 'error'); }
            this.configSaving = false;
        },

        // ─── Folder Picker ────────────────────────────────
        async openFolderPicker(target, index = null) {
            this.folderPicker.target = target;
            this.folderPicker.index = index;
            const list = this.configData[target] || [];
            await this.browseTo(index !== null && list[index] ? list[index] : '~');
            this.folderPicker.open = true;
        },
        async browseTo(path) {
            try {
                const data = await (await fetch(`/api/browse?path=${encodeURIComponent(path)}`)).json();
                this.folderPicker.path = data.path;
                this.folderPicker.dirs = data.dirs || [];
                this.folderPicker.parent = data.parent;
            } catch (e) { }
        },
        selectFolder() {
            const { target, index, path } = this.folderPicker;
            if (!this.configData[target]) this.configData[target] = [];
            if (index !== null) this.configData[target][index] = path;
            else this.configData[target].push(path);
            this.folderPicker.open = false;
        },

        // ─── Faces ────────────────────────────────────────
        async detectFaces(id) {
            if (!id) return;
            this.facesLoading = true;
            try {
                const data = await (await fetch(`/api/files/${id}/detect-faces`, { method: 'POST' })).json();
                this.fileFaces = data.faces || [];
                this.showToast(this.fileFaces.length > 0 ? `Found ${this.fileFaces.length} face(s)` : 'No faces detected', this.fileFaces.length > 0 ? 'success' : 'error');
            } catch (e) { this.showToast('Face detection failed', 'error'); }
            this.facesLoading = false;
        },
        async loadFaces(id) {
            if (!id) return;
            try { this.fileFaces = (await (await fetch(`/api/files/${id}/faces`)).json()).faces || []; } catch (e) { this.fileFaces = []; }
        },
        async labelFace(faceId) {
            const label = (this.labelInput[faceId] || '').trim();
            if (!label) return;
            try {
                const data = await (await fetch(`/api/faces/${faceId}/label`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ label }) })).json();
                const face = this.fileFaces.find(f => f.id === faceId);
                const old = face?.label;
                this.fileFaces.forEach(f => { if (f.label === old) f.label = label; });
                delete this.labelInput[faceId];
                this.showToast(data.faces_updated > 1 ? `Labeled ${data.faces_updated} photos as ${label}` : `Labeled as ${label}`);
            } catch (e) { }
        },
        isPlaceholderLabel(l) { return l && l.startsWith('Person '); },

        // ─── File Actions ─────────────────────────────────
        async revealFile(id) {
            if (!id) return;
            await fetch(`/api/files/${id}/reveal`, { method: 'POST' });
            this.showToast('Opened in Finder');
        },
        async deleteFile(id, fromDisk = false) {
            if (!id || !confirm(fromDisk ? 'Move this file to Trash?' : 'Remove from Tifaw?')) return;
            try {
                const r = await fetch(`/api/files/${id}?from_disk=${fromDisk}`, { method: 'DELETE' });
                if (r.ok) {
                    this.selectedFile = null;
                    this.photos = this.photos.filter(f => f.id !== id);
                    this.searchResults = this.searchResults.filter(f => f.id !== id);
                    this.refreshStatus();
                    this.showToast(fromDisk ? 'Moved to Trash' : 'Removed from Tifaw');
                }
            } catch (e) { this.showToast('Delete failed', 'error'); }
        },
        async reindexFile(id) {
            if (!id) return;
            await fetch(`/api/files/${id}/reindex`, { method: 'POST' });
            this.selectedFile = null;
            this.showToast('Queued for re-indexing');
        },
        async reindexAll() {
            if (!confirm('Re-index all files? This will re-analyze every file.')) return;
            this.reindexingAll = true;
            try {
                const r = await fetch('/api/reindex-all', { method: 'POST' });
                const data = await r.json();
                this.showToast(`Queued ${data.queued} files for re-indexing`);
                this.refreshStatus();
            } catch (e) { this.showToast('Re-index failed', 'error'); }
            this.reindexingAll = false;
        },

        // ─── Helpers ──────────────────────────────────────
        isImage(ext) { return ['.png','.jpg','.jpeg','.gif','.webp','.svg','.bmp'].includes(ext); },
        isVideo(ext) { return ['.mp4','.mov','.webm','.avi','.mkv'].includes(ext); },
        isPreviewable(ext) { return this.isImage(ext) || this.isVideo(ext); },

        getFileIcon(ext) {
            const m = { '.pdf':'\u{1F4C4}','.png':'\u{1F5BC}\uFE0F','.jpg':'\u{1F5BC}\uFE0F','.jpeg':'\u{1F5BC}\uFE0F','.gif':'\u{1F5BC}\uFE0F','.webp':'\u{1F5BC}\uFE0F','.svg':'\u{1F3A8}','.py':'\u{1F40D}','.js':'\u{1F4DC}','.ts':'\u{1F4DC}','.html':'\u{1F310}','.css':'\u{1F3A8}','.json':'\u{1F4CB}','.md':'\u{1F4DD}','.txt':'\u{1F4DD}','.csv':'\u{1F4CA}','.xlsx':'\u{1F4CA}','.docx':'\u{1F4C4}','.zip':'\u{1F4E6}','.go':'\u{1F537}','.rs':'\u{1F980}','.java':'\u2615' };
            return m[ext] || '\u{1F4CE}';
        },

        renderMarkdown(text) {
            if (!text) return '';
            try { return marked.parse(text); } catch { return text; }
        },

        renderChatContent(text) {
            if (!text) return '';
            try {
                // Parse markdown first
                let html = marked.parse(text);
                // The LLM may output photo grid HTML directly — it passes through marked
                return html;
            } catch { return text; }
        },

        // Donut chart gradient from categories
        donutGradient(categories, total) {
            if (!categories || !total) return '';
            let angle = 0;
            const stops = [];
            const colors = {
                Images: '#60a5fa', Documents: '#34d399', Personal: '#f472b6',
                Screenshots: '#9ca3af', Work: '#818cf8', Code: '#a78bfa',
                Media: '#fb923c', Education: '#fbbf24', Legal: '#f87171',
                Finance: '#4ade80', Invoices: '#2dd4bf', Receipts: '#a3e635',
                Medical: '#e879f9', Archives: '#94a3b8', Other: '#cbd5e1',
            };
            for (const cat of categories) {
                const pct = (cat.count / total) * 360;
                const color = colors[cat.name] || '#cbd5e1';
                stops.push(`${color} ${angle}deg ${angle + pct}deg`);
                angle += pct;
            }
            return `background: conic-gradient(${stops.join(', ')})`;
        },

        // Photo map (Leaflet)
        _map: null,
        initMap(locations) {
            if (!locations || !locations.length) return;
            if (typeof L === 'undefined') return;
            this.$nextTick(() => {
                const el = document.getElementById('photo-map');
                if (!el) return;
                if (this._map) { this._map.remove(); this._map = null; }
                const map = L.map(el, { scrollWheelZoom: false });
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; OpenStreetMap',
                    maxZoom: 18,
                }).addTo(map);
                const bounds = [];
                for (const loc of locations) {
                    if (loc.lat && loc.lng) {
                        const ll = [loc.lat, loc.lng];
                        bounds.push(ll);
                        L.circleMarker(ll, {
                            radius: 5, fillColor: '#3b82f6', color: '#fff',
                            weight: 1.5, fillOpacity: 0.85
                        }).addTo(map).bindPopup(`<div style="text-align:center"><img src="/api/files/${loc.id}/preview" style="width:160px;height:120px;object-fit:cover;border-radius:6px" loading="lazy"><div style="font-size:11px;margin-top:4px;color:#666">${loc.filename}</div></div>`, {minWidth: 170});
                    }
                }
                if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
                this._map = map;
            });
        },

        // Calendar heatmap
        renderHeatmap(data) {
            if (!data) return;
            this.$nextTick(() => {
                const el = this.$refs.heatmap;
                if (!el) return;
                const today = new Date();
                const oneYearAgo = new Date(today);
                oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
                // Start from the Sunday of the week of oneYearAgo
                const start = new Date(oneYearAgo);
                start.setDate(start.getDate() - start.getDay());

                const maxCount = Math.max(1, ...Object.values(data));
                const weeks = [];
                const d = new Date(start);
                let week = [];
                while (d <= today) {
                    const key = d.toISOString().slice(0, 10);
                    const count = data[key] || 0;
                    let level = 0;
                    if (count > 0) level = Math.min(3, Math.ceil((count / maxCount) * 3));
                    week.push({ date: key, count, level });
                    if (week.length === 7) { weeks.push(week); week = []; }
                    d.setDate(d.getDate() + 1);
                }
                if (week.length) weeks.push(week);

                let html = '<div class="flex gap-[3px]">';
                for (const w of weeks) {
                    html += '<div class="flex flex-col gap-[3px]">';
                    for (const cell of w) {
                        const cls = ['heatmap-0','heatmap-1','heatmap-2','heatmap-3'][cell.level];
                        html += `<div class="w-2.5 h-2.5 rounded-sm ${cls}" title="${cell.date}: ${cell.count} files"></div>`;
                    }
                    html += '</div>';
                }
                html += '</div>';
                el.innerHTML = html;
            });
        },

        // Storage bar colors
        catColor(name) {
            const m = { Images:'bg-blue-400', Documents:'bg-emerald-400', Personal:'bg-pink-400', Screenshots:'bg-gray-400', Work:'bg-indigo-400', Code:'bg-violet-400', Media:'bg-orange-400', Education:'bg-amber-400', Legal:'bg-red-400', Finance:'bg-green-400' };
            return m[name] || 'bg-gray-300';
        },
    };
}
