(async () => {
  const source = document.querySelector('#editable-contract-terms');
  if (!source || document.documentElement.dataset.paginated) return;
  await document.fonts.ready;
  const anchor = document.querySelector('#contract-signature-page');
  const title = source.dataset.title;
  let body;
  let count = 0;
  const newPage = () => {
    if (++count > 100) throw new Error('Too many contract pages');
    const page = document.createElement('section');
    page.className = 'page dynamic terms-page';
    page.innerHTML = '<div class="running-head"><span>عقد إقامة</span><span>الشروط والأحكام العامة</span></div><h1></h1><div class="terms-body"></div><span class="footer"></span>';
    page.querySelector('h1').textContent = title;
    anchor.before(page);
    body = page.querySelector('.terms-body');
    body.style.height = `${Math.max(100, page.querySelector('.footer').getBoundingClientRect().top - body.getBoundingClientRect().top - 24)}px`;
  };
  const fits = () => body.scrollHeight <= body.clientHeight + 1;
  // Split a long block with DOM Ranges: preserve inline emphasis and every character.
  const split = (node, offset) => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    let text = walker.nextNode();
    while (text && offset > text.length) { offset -= text.length; text = walker.nextNode(); }
    const left = document.createRange(), right = document.createRange();
    left.selectNodeContents(node); right.selectNodeContents(node);
    if (text) { left.setEnd(text, offset); right.setStart(text, offset); }
    const a = node.cloneNode(false), b = node.cloneNode(false);
    a.append(left.cloneContents()); b.append(right.cloneContents());
    return [a, b];
  };
  const blocks = [];
  for (const child of source.content.children) {
    if (child.matches('ol,ul')) {
      [...child.children].forEach((li, index) => {
        const list = child.cloneNode(false);
        if (child.tagName === 'OL') list.start = index + 1;
        list.append(li.cloneNode(true)); blocks.push(list);
      });
    } else blocks.push(child.cloneNode(true));
  }
  newPage();
  for (let i = 0; i < blocks.length; i++) {
    let block = blocks[i];
    if (block.matches('h2,h3') && blocks[i + 1] && body.children.length) {
      const probe = document.createElement('div');
      probe.append(block.cloneNode(true), blocks[i + 1].cloneNode(true));
      body.append(probe); const ok = fits(); probe.remove();
      if (!ok) newPage();
    }
    body.append(block);
    if (fits()) continue;
    block.remove();
    if (body.children.length && !(body.children.length === 1 && body.firstElementChild.matches('h2,h3'))) newPage();
    body.append(block);
    while (!fits()) {
      block.remove();
      const text = block.textContent;
      let low = 1, high = text.length - 1, best = 0;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        const [probe] = split(block, middle); body.append(probe);
        const ok = fits(); probe.remove();
        if (ok) { best = middle; low = middle + 1; } else high = middle - 1;
      }
      if (!best) throw new Error('Contract block cannot fit a page');
      const space = text.lastIndexOf(' ', best);
      if (space > best / 2) best = space + 1;
      const [first, rest] = split(block, best);
      body.append(first); newPage(); block = rest; body.append(block);
    }
  }
  const pages = [...document.querySelectorAll('.page')];
  pages.forEach((page, index) => { page.querySelector('.footer').textContent = `${index + 1} / ${pages.length}`; });
  document.documentElement.dataset.paginated = 'true';
})();
