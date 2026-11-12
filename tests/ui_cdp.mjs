// 真实浏览器验收：用 Chrome（无头、临时配置目录）通过 DevTools 协议操作界面。
// 用法：node ui_cdp.mjs <应用端口> <截图目录>
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PORT = process.argv[2] || "7911";
const OUT = process.argv[3] || ".";
const APP = `http://127.0.0.1:${PORT}/`;
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PROFILE = path.join(OUT, "chrome-profile");
const REF = (process.env.FX_TEST_INPUT||"./tests/input/")+"ainvfx_tank_demo.png";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log("[ui]", ...a);
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); log(ok ? "PASS" : "FAIL", name, detail); };

const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9339", `--user-data-dir=${PROFILE}`,
  "--window-size=1920,1080", "--no-first-run", "--no-default-browser-check", "--no-proxy-server", "about:blank"], { stdio: "ignore" });

async function getJSON(u) { for (let i = 0; i < 50; i++) { try { return await (await fetch(u)).json(); } catch { await sleep(200); } } throw new Error("cdp"); }
const api = async (p, opt) => { const r = await fetch(APP + p.replace(/^\//, ""), opt); return r; };

let ws, mid = 0; const pending = new Map(); const events = [];
function send(method, params = {}) {
  const id = ++mid; ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error("eval: " + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result.value;
}
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(path.join(OUT, name + ".png"), Buffer.from(r.data, "base64"));
}
async function clickText(text, sel = "button") {
  const ok = await ev(`(()=>{const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(e=>e.textContent.trim().includes(${JSON.stringify(text)})&&!e.disabled);if(!b)return false;b.click();return true})()`);
  if (!ok) throw new Error("找不到可点的：" + text);
  await sleep(400);
}
async function waitFor(expr, ms = 15000) { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return true; await sleep(250); } return false; }
async function mouse(type, x, y, buttons = 1) {
  await send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons, clickCount: 1 });
}
async function drawOnCanvas(points) {
  const box = await ev(`(()=>{const c=document.querySelector('canvas.layer.strokes').getBoundingClientRect();return {x:c.x,y:c.y,w:c.width,h:c.height}})()`);
  const P = points.map(([u, v]) => [box.x + u * box.w, box.y + v * box.h]);
  await mouse("mouseMoved", P[0][0], P[0][1], 0);
  await mouse("mousePressed", P[0][0], P[0][1]);
  for (const [x, y] of P.slice(1)) { await mouse("mouseMoved", x, y); await sleep(15); }
  await mouse("mouseReleased", P[P.length - 1][0], P[P.length - 1][1], 0);
}
const circle = (cx, cy, r, n = 24) => Array.from({ length: n + 1 }, (_, i) => [cx + r * Math.cos(i / n * 6.283), cy + r * 1.7 * Math.sin(i / n * 6.283)]);

try {
  const tabs = await getJSON("http://127.0.0.1:9339/json");
  const page = tabs.find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id).res(d.result || {}); pending.delete(d.id); } else if (d.method) events.push(d); };
  await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: APP });
  await sleep(2500);
  check("页面加载", await waitFor(`document.body.innerText.includes('生成')`));
  await shot("01_start");

  // 新建项目
  await clickText("新建");
  await waitFor(`!!document.querySelector('.mask input[type=text]')`);
  await ev(`(()=>{const i=document.querySelector('.mask input[type=text]');i.value='浏览器验收 测试';i.dispatchEvent(new Event('input'))})()`);
  await clickText("确定", ".mask button");
  check("新建项目", await waitFor(`!!document.querySelector('canvas.layer.strokes')`));
  await sleep(800);
  const pid = await ev(`(async()=>{const l=await (await fetch('api/projects')).json();return l.find(p=>p.name==='浏览器验收 测试')?.id})()`);
  check("项目已存盘", !!pid, pid);

  // 时长 2 秒（生成快一些）、首尾方案
  await clickText("2 秒"); await clickText("首尾");
  // 上传参考图
  const doc = await send("DOM.getDocument", { depth: -1 });
  const q = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: "input[type=file]" });
  await send("DOM.setFileInputFiles", { nodeId: q.nodeId, files: [REF] });
  check("参考图上传", await waitFor(`(async()=>{const p=await (await fetch('api/projects/${pid}')).json();return !!p.project.reference})()`, 20000));
  await sleep(2500);
  await shot("02_reference");

  // 画首帧
  await clickText("火焰·橙", ".sw, button").catch(async () => { await ev(`document.querySelector('.sw')?.click()`); });
  await ev(`(()=>{const b=[...document.querySelectorAll('button.tool')].find(e=>/画笔/.test(e.title||e.textContent));b&&b.click()})()`);
  await drawOnCanvas(circle(0.3, 0.35, 0.04));
  await drawOnCanvas([[0.25, 0.35], [0.35, 0.35], [0.3, 0.3], [0.3, 0.42]]);
  await sleep(1800);
  let r = await api(`api/projects/${pid}/strokes/k_first`);
  check("首帧笔触自动保存", r.status === 200, "HTTP " + r.status);
  if (r.status === 200) {
    const buf = Buffer.from(await r.arrayBuffer());
    fs.writeFileSync(path.join(OUT, "strokes_first.png"), buf);
  }
  // 选尾帧并画
  const dia = await ev(`(()=>{const d=[...document.querySelectorAll('.trackbox [class*=dia]')];const r=d[d.length-1].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await mouse("mouseMoved", dia.x, dia.y, 0); await mouse("mousePressed", dia.x, dia.y); await mouse("mouseReleased", dia.x, dia.y, 0);
  await sleep(800);
  await ev(`document.querySelectorAll('.sw')[2]?.click()`);
  await drawOnCanvas(circle(0.3, 0.3, 0.08));
  await sleep(1800);
  let tWait = 0;
  for (; tWait < 15000; tWait += 250) { r = await api(`api/projects/${pid}/strokes/k_tail`); if (r.status === 200) break; await sleep(250); }
  check("尾帧笔触自动保存", r.status === 200, `HTTP ${r.status}，笔画结束后约 ${(1800 + tWait) / 1000}s 落盘`);
  if (process.env.QUICK) { await shot("03q"); throw new Error("QUICK 模式结束"); }
  await shot("03_drawn_tail");

  // 改底图模式 → 笔触保留
  const before = Buffer.from(await (await api(`api/projects/${pid}/strokes/k_first`)).arrayBuffer());
  await ev(`(()=>{const r=[...document.querySelectorAll('input[type=radio]')].find(e=>e.value==='2');r.click()})()`);
  await sleep(3000);
  const after = Buffer.from(await (await api(`api/projects/${pid}/strokes/k_first`)).arrayBuffer());
  check("改底图模式后笔触不变（无需刷新）", before.equals(after));
  const pj = await (await api(`api/projects/${pid}`)).json();
  check("底图模式已保存为 2", pj.project.base_mode === 2, String(pj.project.base_mode));
  await shot("04_mode2");

  // 撤销/重做
  await clickText("撤销"); await sleep(1500);
  await clickText("重做"); await sleep(1500);
  const afterRedo = Buffer.from(await (await api(`api/projects/${pid}/strokes/k_tail`)).arrayBuffer());
  check("撤销后重做恢复尾帧", afterRedo.length > 100);

  // 提示词：写中文 → 点生成 → 应先翻译并停下
  await ev(`(()=>{const t=document.querySelector('textarea');t.value='雪地上一辆白色坦克，晴朗的蓝天';t.dispatchEvent(new Event('input'))})()`);
  await sleep(1200);
  await clickText("生成", "button.gen");
  const stopped = await waitFor(`document.body.innerText.includes('已转成英文')`, 120000);
  check("含中文时先翻译并停下等确认", stopped);
  const sceneEn = await ev(`document.querySelectorAll('textarea')[1].value`);
  check("英文框已填入翻译", /tank/i.test(sceneEn), sceneEn);
  await shot("05_translated");
  const finalTxt = await ev(`[...document.querySelectorAll('textarea')].at(-1).value`);
  check("最终英文稿以 ainvfxfluid 开头", finalTxt.startsWith("ainvfxfluid"), finalTxt);

  // 真正生成
  await clickText("生成", "button.gen");
  const t0 = Date.now();
  let sawProgress = false;
  const done = await (async () => {
    while (Date.now() - t0 < 900000) {
      const txt = await ev(`document.body.innerText`);
      if (/采样|解码/.test(txt)) sawProgress = true;
      if (await ev(`!!document.querySelector('video')`)) return true;
      if (/出错|失败/.test(txt) && !/没画/.test(txt)) { log(txt.slice(0, 500)); return false; }
      await sleep(1000);
    }
    return false;
  })();
  check("界面显示进度（采样/解码）", sawProgress);
  check("生成完成并切到结果播放器", done, `${Math.round((Date.now() - t0) / 1000)}s`);
  await sleep(2000);
  await shot("06_result");
  const res = await (await api(`api/projects/${pid}/results`)).json();
  check("结果文件已存档", res.length === 1, JSON.stringify(res[0]?.file));

  // 重新载入页面，项目与笔触保留
  await send("Page.reload"); await sleep(3000);
  await ev(`(async()=>{})()`);
  const reloaded = await (await api(`api/projects/${pid}`)).json();
  check("重新载入后项目设置保留", reloaded.project.seconds === 2 && reloaded.project.base_mode === 2 && reloaded.strokes.length === 2,
    JSON.stringify({ s: reloaded.project.seconds, m: reloaded.project.base_mode, strokes: reloaded.strokes }));
  await shot("07_reloaded");
  const cons = events.filter((e) => e.method === "Runtime.exceptionThrown" || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"));
  check("无前端异常/控制台错误", cons.length === 0, cons.map((e) => JSON.stringify(e.params).slice(0, 200)).join(" | "));
  fs.writeFileSync(path.join(OUT, "ui_results.json"), JSON.stringify({ pid, results }, null, 1));
} catch (e) {
  console.error("UI TEST ERROR", e);
  try { await shot("99_error"); } catch {}
} finally {
  chrome.kill();
  const f = results.filter((r) => !r.ok);
  log(`共 ${results.length} 项，失败 ${f.length}`);
}
