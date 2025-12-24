$(document).ready(function() {
    if ($.fn.DataTable.isDataTable('#pollsTable')) {
        $('#pollsTable').DataTable().destroy();
    }

    $('#pollsTable').DataTable({
        "order": [[ 3, "desc" ]], // Order by created date, newest first
        "pageLength": 25,
        "responsive": true,
        "columnDefs": [
            { "orderable": false, "targets": [5] } // Disable sorting on actions column
        ]
    });
});
