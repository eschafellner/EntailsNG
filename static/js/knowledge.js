(function () {
  'use strict';
  const form = document.getElementById('knowledge-editor-form');
  if (!form) return;
  const texts = JSON.parse(document.getElementById('knowledge-js-texts').textContent);
  const status = document.getElementById('knowledge-upload-status');
  let uploads = 0;

  function editor() { return window.tinymce && window.tinymce.get('id_content'); }
  function insert(url, name, image) {
    const current = editor();
    if (!current) { status.textContent = texts.editor_wait; return; }
    const node = document.createElement(image ? 'img' : 'a');
    if (image) { node.src = url; node.alt = name; }
    else { node.setAttribute('href', url); node.textContent = name; }
    current.insertContent(node.outerHTML);
    current.focus();
  }

  function attachmentItem(data) {
    const list = document.getElementById('knowledge-attachment-list');
    if (!list) return;
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = data.location.replace('?inline=1', '');
    link.textContent = data.name;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn knowledge-insert-attachment';
    button.dataset.url = data.location; button.dataset.name = data.name;
    button.dataset.image = data.is_image ? '1' : '0';
    button.textContent = data.is_image ? texts.insert_image : texts.insert_link;
    item.append(link, document.createTextNode(' '), button); list.append(item);
  }

  async function upload(file) {
    if (!form.dataset.uploadUrl) { status.textContent = texts.save_first; throw new Error(texts.save_first); }
    if (!file || file.size > 10 * 1024 * 1024) { status.textContent = texts.file_size; throw new Error(texts.file_size); }
    uploads += 1;
    form.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = true; });
    status.textContent = texts.uploading;
    let feedback = texts.upload_failed;
    try {
      const body = new FormData(); body.append('file', file, file.name || 'image.png');
      body.append('csrfmiddlewaretoken', form.querySelector('[name="csrfmiddlewaretoken"]').value);
      const response = await fetch(form.dataset.uploadUrl, { method: 'POST', body, credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (response.redirected) throw new Error(texts.upload_failed);
      const data = await response.json();
      if (!response.ok) { feedback = data.error || texts.upload_failed; throw new Error(feedback); }
      if (!data.location || !data.location.startsWith('/knowledge/attachments/')) throw new Error(texts.upload_failed);
      attachmentItem(data); status.textContent = texts.uploaded;
      return data;
    } catch (_) {
      status.textContent = feedback;
      throw new Error(feedback);
    } finally {
      uploads -= 1;
      if (!uploads) form.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = false; });
    }
  }

  window.knowledgeUploadImage = async function (blobInfo) {
    const file = new File([blobInfo.blob()], blobInfo.filename(), { type: blobInfo.blob().type });
    const data = await upload(file);
    if (!data.is_image) throw new Error(texts.upload_failed);
    return data.location;
  };

  document.getElementById('knowledge-insert-link').addEventListener('click', function () {
    const select = document.getElementById('knowledge-link');
    if (select.value) insert(select.value, select.selectedOptions[0].textContent, false);
  });
  document.getElementById('knowledge-attachment-list')?.addEventListener('click', function (event) {
    const button = event.target.closest('.knowledge-insert-attachment');
    if (button) insert(button.dataset.url, button.dataset.name, button.dataset.image === '1');
  });
  document.getElementById('knowledge-upload-form')?.addEventListener('submit', async function (event) {
    event.preventDefault();
    const button = this.querySelector('button'); button.disabled = true;
    try { await upload(this.querySelector('[type="file"]').files[0]); this.reset(); }
    catch (_) { /* The upload status contains the error. */ }
    finally { button.disabled = false; }
  });
  form.addEventListener('submit', function (event) {
    if (uploads) { event.preventDefault(); status.textContent = texts.uploading; }
  });
})();
