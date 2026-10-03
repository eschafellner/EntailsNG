(() => {
    const progress = document.getElementById('backup-progress');
    if (!progress) return;
    async function poll() {
        let finished = false;
        try {
            const response = await fetch(progress.dataset.url, { cache: 'no-store', referrerPolicy: 'no-referrer' });
            if (response.ok) {
                const data = await response.json();
                document.getElementById('backup-state').textContent = data.label;
                document.getElementById('backup-stage').textContent = data.stage;
                const error = document.getElementById('backup-error');
                error.hidden = !data.error;
                error.textContent = data.error;
                finished = ['completed', 'failed', 'recovery_required'].includes(data.state);
                if (data.state === 'completed' && data.restore_url) {
                    const link = document.getElementById('backup-restore-link');
                    link.href = data.restore_url;
                    link.hidden = false;
                }
            }
        } catch (_) { /* Keep polling across transient network interruptions. */ }
        if (!finished) window.setTimeout(poll, 2000);
    }
    poll();
})();
