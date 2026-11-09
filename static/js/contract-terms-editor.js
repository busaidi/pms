(() => {
  const field = document.querySelector('[data-terms-editor]');
  if (!field || !window.Quill) return;
  const editor = document.createElement('div');
  editor.id = 'terms-rich-editor';
  field.after(editor);
  const quill = new Quill(editor, {
    theme: 'snow',
    formats: ['header', 'bold', 'italic', 'underline', 'strike', 'list', 'blockquote'],
    modules: { toolbar: [
      [{header: [2, 3, false]}], ['bold', 'italic', 'underline', 'strike'],
      [{list: 'ordered'}, {list: 'bullet'}], ['blockquote', 'clean'],
    ] },
  });
  quill.clipboard.dangerouslyPasteHTML(field.value);
  quill.root.setAttribute('dir', 'rtl');
  quill.root.setAttribute('aria-label', 'الشروط والأحكام');
  field.hidden = true;
  field.required = false;
  // Keep the form field synchronized, including before a standard form submit.
  const sync = () => { field.value = quill.getSemanticHTML(); };
  quill.on('text-change', sync);
  field.form.addEventListener('submit', sync);
})();
