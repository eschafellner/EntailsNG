// Uploads images that are pasted or chosen in the info page editor to the server.
// TinyMCE resolves the handler by name (see images_upload_handler in info/admin.py).
(function () {
  'use strict';
  const fallback = 'Das Bild konnte nicht hochgeladen werden. Bitte Anmeldung und Verbindung prüfen.';

  window.infoUploadImage = async function (blobInfo) {
    const editor = window.tinymce && window.tinymce.activeEditor;
    const url = editor && editor.options.get('images_upload_url');
    const token = document.querySelector('[name="csrfmiddlewaretoken"]');
    if (!url || !token) throw { message: fallback, remove: true };
    const body = new FormData();
    body.append('file', blobInfo.blob(), blobInfo.filename());
    body.append('csrfmiddlewaretoken', token.value);
    let data = {};
    let response;
    try {
      response = await fetch(url, { method: 'POST', body, credentials: 'same-origin', headers: { Accept: 'application/json' } });
      data = await response.json();
    } catch (_) {
      throw { message: fallback, remove: true };
    }
    if (!response.ok || response.redirected || typeof data.location !== 'string') {
      throw { message: data.error || fallback, remove: true };
    }
    return data.location;
  };
})();
