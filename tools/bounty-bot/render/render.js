#!/usr/bin/env node
// 悬赏机器人渲染器：payload.json -> HTML -> 无头 Chrome 截图 PNG
// 用法: node render.js <payload.json> <out.png>
//
// 设计纪律：
//   * 高度自适应：先 --dump-dom 量出 data-full-height，再按该高度截图；
//   * 中间 HTML 写到 out/ 之外（系统临时目录），且任何退出路径都删掉——
//     早期版本把中间文件留在 out/ 且截图失败时不清理，会持续堆积；
//   * 静态资源（base.css / fonts / png）按 __ASSETS__ 内联或替换；
//   * 退出码：0 成功 / 2 用法或输入错 / 3 Chrome 失败（stderr 带原因）。
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const CHROME = process.env.BOUNTY_CHROME
  || '/root/.cache/puppeteer/chrome/linux-131.0.6778.204/chrome-linux64/chrome';

const [payloadPath, outPath] = process.argv.slice(2);
if (!payloadPath || !outPath) { console.error('usage: render.js <payload> <out>'); process.exit(2); }

let data;
try {
  data = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));
} catch (e) {
  console.error('payload 读取失败: ' + e.message); process.exit(2);
}
const kind = data.kind || 'help';

const ROOT = __dirname;
const tplMap = {
  help: 'help.html',
  bounty: 'bounty.html',
  contribution: 'contribution.html',
  rank: 'rank.html',
};
const tpl = tplMap[kind] || tplMap.help;
let html;
try {
  html = fs.readFileSync(path.join(ROOT, tpl), 'utf8');
} catch (e) {
  console.error('模板读取失败: ' + e.message); process.exit(2);
}

// 数据注入：内联 payload + 静态资源目录
// 关键：base.css 必须内联，否则其 __ASSETS__ 占位符不会被替换
const baseCssPath = path.join(ROOT, 'base.css');
if (fs.existsSync(baseCssPath)) {
  html = html.replace(/<link rel="stylesheet" href="base\.css">/,
                      '<style>' + fs.readFileSync(baseCssPath, 'utf8') + '</style>');
}
const assetsDir = path.join(ROOT, '..', 'assets').replace(/\\/g, '/');
const injected = html
  .replace('/*__DATA__*/', 'window.__DATA__ = ' + JSON.stringify(data) + ';')
  .replace(/__ASSETS__/g, assetsDir);
if (injected.indexOf('window.__DATA__') < 0) {
  console.error('模板缺少 /*__DATA__*/ 注入点: ' + tpl); process.exit(2);
}

// 中间 HTML 落系统临时目录（不污染 out/），并在 finally 里清理
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bounty-render-'));
const tmpHtml = path.join(tmpDir, 'page.html');
fs.writeFileSync(tmpHtml, injected);

function chrome(args, opts) {
  try {
    return execFileSync(CHROME, args, opts);
  } catch (e) {
    const tail = (e.stderr ? e.stderr.toString() : '') || e.message;
    console.error('Chrome 调用失败: ' + tail.slice(-400));
    process.exit(3);
  }
}

try {
  const w = parseInt(process.env.BOUNTY_W || '1080', 10);
  // 高度由页面自适应：先量出实际高度再截
  const probe = chrome([
    '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
    '--window-size=' + w + ',100',
    '--run-all-compositor-stages-before-draw',
    '--virtual-time-budget=4000',
    '--dump-dom', 'file://' + tmpHtml,
  ], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });

  const m = probe.match(/data-full-height="(\d+)"/);
  const h = m ? Math.min(Math.max(parseInt(m[1], 10), 400), 4000) : 1600;

  chrome([
    '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
    '--window-size=' + w + ',' + h,
    '--screenshot=' + outPath,
    '--default-background-color=00000000',
    '--run-all-compositor-stages-before-draw',
    '--virtual-time-budget=5000',
    'file://' + tmpHtml,
  ], { stdio: ['ignore', 'pipe', 'pipe'] });

  if (!fs.existsSync(outPath) || fs.statSync(outPath).size === 0) {
    console.error('截图产物缺失或为空: ' + outPath); process.exit(3);
  }
  console.log('rendered ' + outPath + ' ' + w + 'x' + h);
} finally {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) { /* 忽略 */ }
}
