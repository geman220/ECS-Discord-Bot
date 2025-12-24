document.addEventListener('DOMContentLoaded', function() {
    // Auto-refresh stats every 30 seconds
    let autoRefresh = setInterval(refreshStats, 30000);

    // Manual refresh button
    const refreshButton = document.getElementById('refresh-stats');
    if (refreshButton) {
        refreshButton.addEventListener('click', function() {
            refreshStats();
            this.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Refreshing...';
            setTimeout(() => {
                this.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh';
            }, 1000);
        });
    }

    // Cache test button
    const testButton = document.getElementById('test-cache');
    if (testButton) {
        testButton.addEventListener('click', function() {
            testCache();
        });
    }

    function refreshStats() {
        const refreshUrl = document.getElementById('refresh-stats')?.dataset.refreshUrl;
        if (!refreshUrl) return;

        fetch(refreshUrl)
            .then(response => response.json())
            .then(data => {
                if (!data.error) {
                    // Update the display with new stats
                    location.reload(); // Simple reload for now
                }
            })
            .catch(error => console.error('Error refreshing stats:', error));
    }

    function testCache() {
        const button = document.getElementById('test-cache');
        const result = document.getElementById('test-result');
        const testUrl = button?.dataset.testUrl;

        if (!button || !testUrl) return;

        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';
        button.disabled = true;

        fetch(testUrl)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    result.innerHTML = '<div class="alert alert-success"><i class="fas fa-check"></i> ' + data.message + '</div>';
                } else {
                    result.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> ' + data.message + '</div>';
                }
            })
            .catch(error => {
                result.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> Cache test failed: ' + error + '</div>';
            })
            .finally(() => {
                button.innerHTML = '<i class="fas fa-vial"></i> Test Cache Connection';
                button.disabled = false;
            });
    }
});
