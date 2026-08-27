/**
 * admin_sponsor.js - Dynamische Anzeige von bedingten Feldern im Sponsor-Admin
 * Blendet veranstaltung / aktiv_bis je nach gewähltem aktiv_modus ein/aus.
 */
document.addEventListener('DOMContentLoaded', function () {
    const aktivModusSelect = document.getElementById('id_aktiv_modus');
    if (!aktivModusSelect) return;

    const rowVeranstaltung = document.querySelector('.form-row.field-veranstaltung');
    const rowAktivBis = document.querySelector('.form-row.field-aktiv_bis');

    function updateVisibility() {
        const val = aktivModusSelect.value;

        if (rowVeranstaltung) {
            if (val === 'veranstaltung') {
                rowVeranstaltung.style.display = '';
            } else {
                rowVeranstaltung.style.display = 'none';
            }
        }

        if (rowAktivBis) {
            if (val === 'datum') {
                rowAktivBis.style.display = '';
            } else {
                rowAktivBis.style.display = 'none';
            }
        }
    }

    aktivModusSelect.addEventListener('change', updateVisibility);
    updateVisibility();
});
