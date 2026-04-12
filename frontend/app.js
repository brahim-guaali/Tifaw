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

        // Faces
        fileFaces: [],
        facesLoading: false,
        labelInput: {},

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

        async mergePersonPrompt() {
            if (!this.activePerson) return;
            const otherName = prompt(`Merge "${this.activePerson}" with which person?\nType the exact name (e.g. "Person 42"):`);
            if (!otherName || otherName.trim() === this.activePerson) return;
            try {
                // Rename the other person's faces to this person's name
                const r = await fetch(`/api/people/${encodeURIComponent(otherName.trim())}/rename`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ label: this.activePerson }),
                });
                const data = await r.json();
                this.showToast(`Merged ${otherName.trim()} into ${this.activePerson} (${data.faces_updated} photos merged)`);
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

        // Storage bar colors
        catColor(name) {
            const m = { Images:'bg-blue-400', Documents:'bg-emerald-400', Personal:'bg-pink-400', Screenshots:'bg-gray-400', Work:'bg-indigo-400', Code:'bg-violet-400', Media:'bg-orange-400', Education:'bg-amber-400', Legal:'bg-red-400', Finance:'bg-green-400' };
            return m[name] || 'bg-gray-300';
        },
    };
}
