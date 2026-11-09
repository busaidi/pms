import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright';

const script = await readFile(new URL('../static/js/contract-pagination.js', import.meta.url),'utf8');
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const clause = 'نص كامل يجب الحفاظ عليه مع التنسيق والوضوح. ';
  for (const content of [
    '<h3>عنوان</h3><p>شروط قصيرة <strong>مهمة</strong>.</p>',
    '<h3>عنوان فقرة طويلة</h3><p>' + (clause + '<strong>نص بارز</strong>').repeat(600) + '</p><ol><li>أولًا</li><li>ثانيًا</li></ol>',
    Array.from({length:60},(_,i)=>`<h3>المادة ${i}</h3><p>${clause.repeat(6)}</p>`).join(''),
  ]) {
    await page.setContent(`<html dir="rtl"><style>
      .page{width:794px;height:1123px;padding:90px 65px 80px;box-sizing:border-box;position:relative;}
      .footer{position:absolute;bottom:32px;left:65px;right:65px;}
      .running-head{position:absolute;top:32px;}.terms-body{display:flow-root;}
      p,li{font:18px/1.4 Arial;} h3{font:20px Arial;} h1{font:24px Arial;}
      </style><template id="editable-contract-terms" data-title="شروط اختبار">${content}</template>
      <section class="page" id="contract-signature-page"><span class="footer"></span></section></html>`);
    await page.evaluate(script);
    const result = await page.evaluate(()=>{
      const norm = value=>value.replace(/\s+/g,'');
      const bodies=[...document.querySelectorAll('.terms-body')];
      return {
        expected:norm(document.querySelector('template').content.textContent),
        actual:norm(bodies.map(e=>e.textContent).join('')),
        overflow:bodies.some(e=>e.scrollHeight>e.clientHeight+1),
        orphan:bodies.some(e=>e.children.length===1 && e.firstElementChild.matches('h2,h3')),
        bold:document.querySelectorAll('.terms-body strong').length,
        pages:document.querySelectorAll('.page').length,
      };
    });
    assert.equal(result.actual,result.expected);
    assert.equal(result.overflow,false);
    assert.equal(result.orphan,false);
    if(content.includes('<strong>'))assert(result.bold>0);
    console.log(`Pagination passed: ${result.pages} pages, complete text and formatting.`);
  }
} finally {await browser.close();}
