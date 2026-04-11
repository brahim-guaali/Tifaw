function app() {
    return {
        view: 'dashboard',
        status: {
            ollama_connected: false,
            model_available: false,
            total_files: 0,
            indexed_files: 0,
            pending_files: 0,
            pending_renames: 0,
            queue_size: 0,
            watched_folders: [],
        },
        recentFiles: [],
        searchQuery: '',
        searchResults: [],
        activeFolder: null,
        folderGroups: null,
        chatMessages: [],
        chatInput: '',
        chatLoading: false,
        renameProposals: [],
        selectedFile: null,

        async init() {
            await this.refreshStatus();
            await this.loadRecentFiles();
            // Poll status every 5 seconds
            setInterval(() => this.refreshStatus(), 5000);
        },

        async refreshStatus() {
            try {
                const resp = await fetch('/api/status');
                this.status = await resp.json();
            } catch (e) {
                console.error('Status fetch failed:', e);
            }
        },

        async loadRecentFiles() {
            try {
                const resp = await fetch('/api/files?limit=20');
                const data = await resp.json();
                this.recentFiles = data.files || [];
            } catch (e) {
                console.error('Files fetch failed:', e);
            }
        },

        async performSearch() {
            if (!this.searchQuery.trim()) {
                this.searchResults = [];
                return;
            }
            try {
                const resp = await fetch(`/api/search?q=${encodeURIComponent(this.searchQuery)}`);
                const data = await resp.json();
                this.searchResults = data.results || [];
            } catch (e) {
                console.error('Search failed:', e);
                this.searchResults = [];
            }
        },

        async openFolder(folder) {
            this.activeFolder = folder;
            this.view = 'folders';
            try {
                const resp = await fetch(`/api/files?watch_folder=${encodeURIComponent(folder)}&grouped=true`);
                const data = await resp.json();
                this.folderGroups = data.categories || {};
            } catch (e) {
                console.error('Folder load failed:', e);
                this.folderGroups = {};
            }
        },

        async sendChat() {
            const msg = this.chatInput.trim();
            if (!msg || this.chatLoading) return;

            this.chatMessages.push({
                role: 'user',
                content: msg,
                timestamp: new Date().toISOString(),
            });
            this.chatInput = '';
            this.chatLoading = true;

            this.$nextTick(() => {
                const el = document.getElementById('chatMessages');
                if (el) el.scrollTop = el.scrollHeight;
            });

            try {
                const resp = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg }),
                });

                if (resp.ok) {
                    const data = await resp.json();
                    this.chatMessages.push({
                        role: 'assistant',
                        content: data.response || 'No response',
                        timestamp: new Date().toISOString(),
                    });
                } else {
                    this.chatMessages.push({
                        role: 'assistant',
                        content: 'Sorry, something went wrong. Make sure Ollama is running.',
                        timestamp: new Date().toISOString(),
                    });
                }
            } catch (e) {
                this.chatMessages.push({
                    role: 'assistant',
                    content: 'Connection error. Is the server running?',
                    timestamp: new Date().toISOString(),
                });
            }

            this.chatLoading = false;
            this.$nextTick(() => {
                const el = document.getElementById('chatMessages');
                if (el) el.scrollTop = el.scrollHeight;
            });
        },

        async loadRenames() {
            try {
                const resp = await fetch('/api/renames/pending');
                const data = await resp.json();
                this.renameProposals = data.proposals || [];
            } catch (e) {
                console.error('Renames fetch failed:', e);
            }
        },

        async approveRename(fileId) {
            try {
                await fetch(`/api/renames/${fileId}/approve`, { method: 'POST' });
                this.renameProposals = this.renameProposals.filter(p => p.file_id !== fileId);
                this.refreshStatus();
            } catch (e) {
                console.error('Approve failed:', e);
            }
        },

        async dismissRename(fileId) {
            try {
                await fetch(`/api/renames/${fileId}/dismiss`, { method: 'POST' });
                this.renameProposals = this.renameProposals.filter(p => p.file_id !== fileId);
                this.refreshStatus();
            } catch (e) {
                console.error('Dismiss failed:', e);
            }
        },

        async approveAllRenames() {
            for (const p of [...this.renameProposals]) {
                await this.approveRename(p.file_id);
            }
        },

        async reindexFile(fileId) {
            if (!fileId) return;
            try {
                await fetch(`/api/files/${fileId}/reindex`, { method: 'POST' });
                this.selectedFile = null;
            } catch (e) {
                console.error('Reindex failed:', e);
            }
        },

        getFileIcon(ext) {
            const icons = {
                '.pdf': '📄',
                '.png': '🖼️',
                '.jpg': '🖼️',
                '.jpeg': '🖼️',
                '.gif': '🖼️',
                '.webp': '🖼️',
                '.svg': '🎨',
                '.py': '🐍',
                '.js': '📜',
                '.ts': '📜',
                '.html': '🌐',
                '.css': '🎨',
                '.json': '📋',
                '.md': '📝',
                '.txt': '📝',
                '.csv': '📊',
                '.xlsx': '📊',
                '.docx': '📄',
                '.zip': '📦',
                '.go': '🔷',
                '.rs': '🦀',
                '.java': '☕',
            };
            return icons[ext] || '📎';
        },

        renderMarkdown(text) {
            if (!text) return '';
            try {
                return marked.parse(text);
            } catch {
                return text;
            }
        },
    };
}
