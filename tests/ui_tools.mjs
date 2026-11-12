// 浏览器验收（不占 GPU）：时间轴关键帧、画笔工具像素、视频起始帧。用法：node ui_tools.mjs <端口> <截图目录>
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const PORT = process.argv[2] || "7911";
const OUT = process.argv[3] || ".";
const APP = `http://127.0.0.1:${PORT}/`;
const INP = process.env.FX_TEST_INPUT || "./tests/input/";   // 需要 ainvfx_tank_demo.png 与 ainvfx_demo_video.mp4
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log("[ui]", ok ? "PASS" : "FAIL", name, detail); };
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9341",
  `--user-data-dir=${path.join(OUT, "profile")}`, "--window-size=1920,1080", "--no-first-run", "--no-proxy-server", "about:blank"], { stdio: "ignore" });
let ws, mid = 0; const pending = new Map(); const events = [];
const send = (method, params = {}) => { const id = ++mid; ws.send(JSON.stringify({ id, method, params })); return new Promise((res) => pending.set(id, res)); };
async function ev(expr) { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300)); return r.result.value; }
const shot = async (n) => fs.writeFileSync(path.join(OUT, n + ".png"), Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
async function clickText(text, sel = "button") { const ok = await ev(`(()=>{const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(e=>e.textContent.trim().includes(${JSON.stringify(text)})&&!e.disabled);if(!b)return false;b.click();return true})()`); if (!ok) throw new Error("找不到：" + text); await sleep(500); }
const mouse = (type, x, y, buttons = 1) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons, clickCount: 1 });
async function clickAt(x, y) { await mouse("mouseMoved", x, y, 0); await mouse("mousePressed", x, y); await mouse("mouseReleased", x, y, 0); await sleep(400); }
async function canvasBox() { return ev(`(()=>{const c=document.querySelector('canvas.layer.strokes').getBoundingClientRect();return {x:c.x,y:c.y,w:c.width,h:c.height}})()`); }
async function draw(points) { const b = await canvasBox(); const P = points.map(([u, v]) => [b.x + u * b.w, b.y + v * b.h]);
  await mouse("mouseMoved", ...P[0], 0); await mouse("mousePressed", ...P[0]); for (const p of P.slice(1)) { await mouse("mouseMoved", ...p); await sleep(10); } await mouse("mouseReleased", ...P.at(-1), 0); }
const ring = (cx, cy, r, n = 40) => Array.from({ length: n + 1 }, (_, i) => [cx + r * Math.cos(i / n * 6.2832), cy + r * 1.78 * Math.sin(i / n * 6.2832)]);
const tool = (re) => ev(`(()=>{const b=[...document.querySelectorAll('button.tool')].find(e=>${re}.test(e.title+e.textContent));b.click();return !!b})()`);
const setColor = (hex) => ev(`(()=>{const i=[...document.querySelectorAll('input')].find(e=>/^#[0-9a-fA-F]{6}$/.test(e.value));i.value='${hex}';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'));return i.value})()`);
const proj = async (pid) => (await fetch(APP + `api/projects/${pid}`)).json();
async function waitSaved(pid, kid) { for (let i = 0; i < 60; i++) { const r = await fetch(APP + `api/projects/${pid}/strokes/${kid}`); if (r.status === 200) return Buffer.from(await r.arrayBuffer()); await sleep(250); } return null; }

try {
  const page = (await (await fetch("http://127.0.0.1:9341/json").catch(async () => { await sleep(1500); return fetch("http://127.0.0.1:9341/json"); })).json()).find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result || {}); pending.delete(d.id); } else if (d.method) events.push(d); };
  await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: APP }); await sleep(2500);
  await clickText("新建"); await sleep(400);
  await ev(`(()=>{const i=document.querySelector('.mask input[type=text]');i.value='工具验收';i.dispatchEvent(new Event('input'))})()`);
  await clickText("确定", ".mask button"); await sleep(1500);
  const pid = await ev(`(async()=>(await (await fetch('api/projects')).json()).find(p=>p.name==='工具验收')?.id)()`);
  await clickText("3 秒"); await sleep(800);

  // ---------- A 时间轴 ----------
  const idx = async () => (await proj(pid)).resolved_keyframes.map((k) => k.index).join(",");
  await clickText("每秒一帧"); await sleep(1500); check("方案：每秒一帧", (await idx()) === "0,25,49,72", await idx());
  await clickText("只首帧"); await sleep(1500); check("方案：只首帧", (await idx()) === "0", await idx());
  await clickText("首尾"); await sleep(1500); check("方案：首尾", (await idx()) === "0,72", await idx());
  const track = await ev(`(()=>{const r=document.querySelector('.trackbox').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);
  const fx = (f) => track.x + track.w * f / 72;   // 近似（两端有内边距时会有 1–2 帧误差，下面只检查吸附规则）
  await clickAt(fx(30), track.y + 10); await clickText("+ 加帧"); await sleep(1500);
  let kfs = (await proj(pid)).resolved_keyframes; const added = kfs.find((k) => k.index !== 0 && k.index !== 72);
  check("加帧（吸附开）落在 8k+1 网格", added && added.index % 8 === 1, JSON.stringify(kfs.map((k) => k.index)));
  await ev(`(()=>{const c=[...document.querySelectorAll('label')].find(l=>l.textContent.includes('吸附'))?.querySelector('input');c.click()})()`); await sleep(1200);
  await clickAt(fx(44), track.y + 10); await clickText("+ 加帧"); await sleep(1500);
  kfs = (await proj(pid)).resolved_keyframes;
  const off = kfs.filter((k) => ![0, 72, added?.index].includes(k.index));
  check("关闭吸附后可放在任意帧", off.length === 1 && off[0].index % 8 !== 1, JSON.stringify(kfs.map((k) => k.index)));
  // 拖动刚加的帧
  const dpos = await ev(`(()=>{const d=[...document.querySelectorAll('.trackbox [class*=dia]')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}});return d})()`);
  const before = kfs.map((k) => k.index).join(",");
  const tgt = dpos[2];
  await mouse("mouseMoved", tgt.x, tgt.y, 0); await mouse("mousePressed", tgt.x, tgt.y);
  for (let i = 1; i <= 10; i++) { await mouse("mouseMoved", tgt.x + i * 12, tgt.y); await sleep(20); }
  await mouse("mouseReleased", tgt.x + 120, tgt.y, 0); await sleep(1500);
  const afterDrag = (await proj(pid)).resolved_keyframes.map((k) => k.index).join(",");
  check("拖动关键帧改变帧号", afterDrag !== before, `${before} → ${afterDrag}`);
  await clickText("删除此帧"); await sleep(600);
  if (await ev(`!!document.querySelector('.mask')`)) await clickText("确定", ".mask button");
  await sleep(1500);
  const afterDel = (await proj(pid)).resolved_keyframes.length;
  check("删除选中的关键帧", afterDel === kfs.length - 1, `${kfs.length} → ${afterDel}`);
  await clickText("首尾"); await sleep(600);
  if (await ev(`!!document.querySelector('.mask')`)) await clickText("确定", ".mask button");
  await sleep(1200);
  await shot("A_timeline");

  // ---------- B 画笔工具 ----------
  const d0 = (await ev(`(()=>{const d=[...document.querySelectorAll('.trackbox [class*=dia]')];const r=d[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`));
  await clickAt(d0.x, d0.y);
  await tool("/画笔/"); await setColor("#ff7814"); await ev(`(()=>{const i=[...document.querySelectorAll('input[type=number]')].find(e=>e.max==='200');i.value=10;i.dispatchEvent(new Event('input'))})()`);
  await draw(ring(0.5, 0.5, 0.08)); await sleep(300);
  await tool("/填充/"); await setColor("#ffd73c"); { const b = await canvasBox(); await clickAt(b.x + 0.5 * b.w, b.y + 0.5 * b.h); }
  await tool("/橡皮/"); await draw([[0.40, 0.75], [0.60, 0.75]]); await draw([[0.5, 0.2], [0.5, 0.32]]);
  const png = await waitSaved(pid, "k_first");
  check("填充/橡皮后笔触已保存", !!png);
  if (png) {
    fs.writeFileSync(path.join(OUT, "B_strokes.png"), png);
    const stat = await ev(`(async()=>{const b=await (await fetch('api/projects/${pid}/strokes/k_first',{cache:'no-store'})).blob();
      const bm=await createImageBitmap(b,{premultiplyAlpha:'none',colorSpaceConversion:'none'});const c=new OffscreenCanvas(bm.width,bm.height);const x=c.getContext('2d');x.drawImage(bm,0,0);
      const d=x.getImageData(0,0,bm.width,bm.height).data;const set=new Map();for(let i=0;i<d.length;i+=4){const k=d[i+3]===0?'transparent':d[i].toString(16).padStart(2,'0')+d[i+1].toString(16).padStart(2,'0')+d[i+2].toString(16).padStart(2,'0')+':'+d[i+3];set.set(k,(set.get(k)||0)+1)}
      const W=bm.width,H=bm.height,px=(u,v)=>{const i=(Math.round(v*H)*W+Math.round(u*W))*4;return [d[i],d[i+1],d[i+2],d[i+3]]};
      return {colors:[...set.entries()],center:px(0.5,0.5),erased:px(0.5,0.25)}})()`);
    const keys = stat.colors.map(([k]) => k);
    check("保存的笔触只有选中色与透明（硬边、无混色）", keys.every((k) => ["transparent", "ff7814:255", "ffd73c:255"].includes(k)), JSON.stringify(stat.colors));
    check("油漆桶把圈内填成黄色", stat.center.join() === "255,215,60,255", stat.center.join());
    check("橡皮擦除处为透明", stat.erased[3] === 0, stat.erased.join());
  }
  // 吸管：从底图（黑底=空项目无参考）上取色 → 上传参考图后在天空处取色
  const doc = await send("DOM.getDocument", { depth: -1 });
  const fi = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: "input[type=file]" });
  await send("DOM.setFileInputFiles", { nodeId: fi.nodeId, files: [INP + "ainvfx_tank_demo.png"] }); await sleep(3500);
  await tool("/吸管/"); { const b = await canvasBox(); await clickAt(b.x + 0.85 * b.w, b.y + 0.08 * b.h); }
  const hex = await ev(`[...document.querySelectorAll('input')].find(e=>/^#[0-9a-fA-F]{6}$/.test(e.value)).value`);
  const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  check("吸管从底图取到天空蓝色", rgb[2] > rgb[0] + 40, hex);
  await shot("B_tools");

  // ---------- C 视频起始帧 ----------
  await send("DOM.setFileInputFiles", { nodeId: (await send("DOM.querySelector", { nodeId: (await send("DOM.getDocument", { depth: -1 })).root.nodeId, selector: "input[type=file]" })).nodeId, files: [INP + "ainvfx_demo_video.mp4"] });
  await sleep(4000);
  await clickText("2 秒"); await sleep(1000);
  const baseHash = async () => crypto.createHash("md5").update(Buffer.from(await (await fetch(APP + `api/projects/${pid}/base/0?t=${Date.now()}`)).arrayBuffer())).digest("hex");
  const h0 = await baseHash(); const s0 = (await proj(pid)).project.reference.start25;
  for (let i = 0; i < 10; i++) { await ev(`document.querySelector('button[title="前进一帧"]').click()`); await sleep(300); }
  await sleep(2000);
  const s1 = (await proj(pid)).project.reference.start25; const h1 = await baseHash();
  check("视频起始帧步进写入项目", s1 === s0 + 10, `${s0} → ${s1}`);
  check("起始帧改变后底图随之改变", h0 !== h1);
  await shot("C_video");
  const errs = events.filter((e) => e.method === "Runtime.exceptionThrown" || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"));
  check("无前端异常", errs.length === 0, errs.map((e) => JSON.stringify(e.params).slice(0, 200)).join(" | "));
  fs.writeFileSync(path.join(OUT, "ui_tools_results.json"), JSON.stringify({ pid, results }, null, 1));
  await fetch(APP + `api/projects/${pid}`, { method: "DELETE" });   // 测试项目移进回收站，不留在项目列表里
} catch (e) { console.error("UI TOOLS ERROR", e); try { await shot("99_error"); } catch {} }
finally { chrome.kill(); console.log("[ui]", `共 ${results.length} 项，失败 ${results.filter((r) => !r.ok).length}`); }
