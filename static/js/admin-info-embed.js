// Progressive enhancement: the form remains usable without JavaScript.
document.addEventListener('DOMContentLoaded', () => {
  const pageType = document.getElementById('id_page_type');
  if (!pageType) return;
  const embedFields = document.querySelector('.info-embed-fields');
  const update = () => {
    const isEmbed = pageType.value === 'EMBED';
    if (embedFields) embedFields.hidden = !isEmbed;
    const label = document.querySelector('.field-content label');
    if (label) label.classList.toggle('required', !isEmbed);
  };
  pageType.addEventListener('change', update);
  update();
});
