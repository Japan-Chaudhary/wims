/**
 * main.js
 * -------
 * Shared JavaScript for the WIMS application.
 *
 * Features:
 *   - Sidebar toggle for mobile
 *   - Password visibility toggle
 *   - Auto-dismiss flash alerts
 */

document.addEventListener('DOMContentLoaded', function () {

    // =================================================================
    //  SIDEBAR TOGGLE (mobile)
    // =================================================================
    const sidebar       = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarClose  = document.getElementById('sidebarClose');
    const sidebarOverlay= document.getElementById('sidebarOverlay');

    function openSidebar() {
        if (sidebar) sidebar.classList.add('show');
        if (sidebarOverlay) sidebarOverlay.classList.add('show');
        document.body.style.overflow = 'hidden';  // prevent scroll
    }

    function closeSidebar() {
        if (sidebar) sidebar.classList.remove('show');
        if (sidebarOverlay) sidebarOverlay.classList.remove('show');
        document.body.style.overflow = '';
    }

    if (sidebarToggle)  sidebarToggle.addEventListener('click', openSidebar);
    if (sidebarClose)   sidebarClose.addEventListener('click', closeSidebar);
    if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);


    // =================================================================
    //  PASSWORD VISIBILITY TOGGLE
    // =================================================================
    document.querySelectorAll('.toggle-password').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const targetId = this.getAttribute('data-target');
            const input = document.getElementById(targetId);
            const icon  = this.querySelector('i');

            if (input && icon) {
                if (input.type === 'password') {
                    input.type = 'text';
                    icon.classList.replace('bi-eye', 'bi-eye-slash');
                } else {
                    input.type = 'password';
                    icon.classList.replace('bi-eye-slash', 'bi-eye');
                }
            }
        });
    });


    // =================================================================
    //  AUTO-DISMISS FLASH ALERTS (after 5 seconds)
    // =================================================================
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            // Use Bootstrap's dismiss API
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

});
