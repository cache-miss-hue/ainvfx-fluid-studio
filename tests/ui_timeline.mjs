// 浏览器验收（不占 GPU，引擎可以不启动：FX_NO_ENGINE=1）：时间轴预览/落笔建帧/快捷键/源视频起始帧/
// 生成前补保存（描述框里写英文）/空关键帧提醒/删除项目。
// 用法：node tests/ui_timeline.mjs <端口> <截图目录>   （需要 FX_TEST_INPUT 目录下的 ainvfx_demo_video.mp4）
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PORT = process.argv[2] || "7911";
const OUT = process.argv[3] || ".";
const APP = `http://127.0.0.1:${PORT}/`;
const INP = process.env.FX_TEST_INPUT || "./tests/input/";
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log("[tl]", ok ? "PASS" : "FAIL", name, typeof detail === "string" ? detail : JSON.stringify(detail)); };
fs.mkdirSync(OUT, { recursive: true });
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9342", `--user-data-dir=${path.join(OUT, "profile")}`,
  "--window-size=1920,1080", "--no-first-run", "--no-proxy-server", "about:blank"], { stdio: "ignore" });
let ws, mid = 0; const pending = new Map(); const events = [];
const send = (method, params = {}) => { const id = ++mid; ws.send(JSON.stringify({ id, method, params })); return new Promise((res) => pending.set(id, res)); };
async function ev(expr) { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; }
const shot = async (n) => fs.writeFileSync(path.join(OUT, n + ".png"), Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
async function clickText(text, sel = "button") { const ok = await ev(`(()=>{const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(e=>e.textContent.trim().includes(${JSON.stringify(text)})&&!e.disabled);if(!b)return false;b.click();return true})()`); if (!ok) throw new Error("找不到：" + text); await sleep(400); }
const mouse = (type, x, y, buttons = 1, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons, clickCount: 1, ...extra });
const key = (k, code, mods = 0, vk = 0) => send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, modifiers: mods, windowsVirtualKeyCode: vk }).then(() => send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, modifiers: mods, windowsVirtualKeyCode: vk }));
const proj = async (pid) => (await fetch(APP + `api/projects/${pid}`)).json();
const st = () => ev(`(()=>{const a=document.querySelector('#app').__vue_app__;return null})()`);
const playhead = () => ev(`parseInt(document.querySelector('.pos b').textContent)`);
const canvasSrc = () => ev(`document.querySelector('img.layer.base').getAttribute('src')`);
const info = () => ev(`document.querySelector('.info.top-l').textContent`);
async function box(sel) { return ev(`(()=>{const r=document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`); }
async function draw(points) { const b = await box("canvas.layer.strokes"); const P = points.map(([u, v]) => [b.x + u * b.w, b.y + v * b.h]);
  await mouse("mouseMoved", ...P[0], 0); await mouse("mousePressed", ...P[0]); for (const p of P.slice(1)) { await mouse("mouseMoved", ...p); await sleep(15); } await mouse("mouseReleased", ...P.at(-1), 0); await sleep(300); }
const tool = (re) => ev(`(()=>{const b=[...document.querySelectorAll('button.tool')].find(e=>${re}.test(e.title+e.textContent));b.click();return !!b})()`);
async function idxs(pid) { return (await proj(pid)).resolved_keyframes.map((k) => k.index); }
async function settle(ms = 1400) { await sleep(ms); }

let pid = null;
try {
  const page = (await (await fetch("http://127.0.0.1:9342/json").catch(async () => { await sleep(1500); return fetch("http://127.0.0.1:9342/json"); })).json()).find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result || {}); pending.delete(d.id); } else if (d.method) events.push(d); };
  await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: APP }); await sleep(2500);
  await clickText("新建"); await sleep(400);
  await ev(`(()=>{const i=document.querySelector('.mask input[type=text]');i.value='时间轴验收';i.dispatchEvent(new Event('input'))})()`);
  await clickText("确定", ".mask button"); await sleep(1500);
  pid = await ev(`(async()=>(await (await fetch('api/projects')).json()).find(p=>p.name==='时间轴验收')?.id)()`);
  const doc = await send("DOM.getDocument", { depth: -1 });
  const fi = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: "input[type=file]" });
  await send("DOM.setFileInputFiles", { nodeId: fi.nodeId, files: [INP + "ainvfx_demo_video.mp4"] }); await sleep(4000);
  await clickText("3 秒"); await settle();
  check("上传视频后出现“源视频”总览条", await ev(`!!document.querySelector('.ovrow .win')`));
  await sleep(2500);
  const film = await ev(`[...document.querySelectorAll('.lane .film img')].map(i=>i.complete&&i.naturalWidth>0)`);
  check("时间轴上铺了参考画面缩略图", film.length === 12 && film.filter(Boolean).length >= 10, film.join());

  // ---------- 拖动标尺：画布实时显示该帧，松手吸附 ----------
  const tb = await box(".trackbox");
  const fx = (f) => tb.x + (tb.w * f) / 72;
  await mouse("mouseMoved", fx(30), tb.y + 10, 0); await mouse("mousePressed", fx(30), tb.y + 10);
  for (let f = 31; f <= 44; f++) { await mouse("mouseMoved", fx(f), tb.y + 10); await sleep(25); }
  await sleep(400);
  const midSrc = await canvasSrc(), midInfo = await info(), midHead = await playhead();
  check("拖动中画布显示该帧的参考画面", /\/clip\/\d+\/4[2-5]\b/.test(midSrc), midSrc);
  check("拖动中左上角显示“预览 · 第 N 帧”", midInfo.includes("预览") && midInfo.includes(`第 ${midHead} 帧`), midInfo);
  check("拖动中出现松手落点提示", await ev(`!!document.querySelector('.ghost')`) || midHead % 8 === 1);
  await mouse("mouseReleased", fx(44), tb.y + 10, 0); await sleep(600);
  const ph = await playhead();
  check("松手后播放头吸附到 8k+1 网格", ph % 8 === 1, ph);
  check("不在关键帧上：画布提示“还不是关键帧”", (await ev(`document.querySelector('.emptytip.pv')?.textContent||''`)).includes("还不是关键帧"));
  await shot("T1_preview");

  // ---------- 在预览帧上直接画 = 建关键帧 ----------
  await tool("/橡皮/"); await draw([[0.3, 0.3], [0.4, 0.4]]); await settle(900);
  check("橡皮在预览帧上不建关键帧", !(await idxs(pid)).includes(ph), (await idxs(pid)).join());
  await tool("/画笔/");
  await draw([[0.45, 0.5], [0.5, 0.55], [0.55, 0.5]]); await settle();
  let k = (await proj(pid));
  const created = k.resolved_keyframes.find((x) => x.index === ph);
  check("在预览帧上落笔：在播放头处新建了关键帧", !!created, k.resolved_keyframes.map((x) => x.index).join());
  let saved = false;
  for (let i = 0; i < 20 && created; i++) { if ((await fetch(APP + `api/projects/${pid}/strokes/${created.id}`)).status === 200) { saved = true; break; } await sleep(250); }
  check("新关键帧的笔触已保存", saved);
  check("画布上换成了真实底图", (await canvasSrc()).includes(`/base/${ph}`), await canvasSrc());
  await key("z", "KeyZ", 2, 90); await settle();
  check("撤销这一笔：落笔时新建的关键帧一起撤掉", !(await idxs(pid)).includes(ph), (await idxs(pid)).join());

  // ---------- 快捷键 ----------
  await key("Home", "Home", 0, 36); await sleep(200);
  check("Home 回到第 0 帧（首帧关键帧）", (await playhead()) === 0 && (await info()).includes("首帧"));
  await key("ArrowRight", "ArrowRight", 0, 39); await sleep(150); const a1 = await playhead();
  await key("ArrowRight", "ArrowRight", 0, 39); await sleep(150); const a2 = await playhead();
  check("→ 按网格跳（吸附开）", a1 === 1 && a2 === 9, `${a1},${a2}`);
  await key("ArrowRight", "ArrowRight", 8, 39); await sleep(150);
  check("Shift+→ 逐帧", (await playhead()) === 10, await playhead());
  await key("k", "KeyK", 0, 75); await settle();
  check("K 在播放头处加关键帧（吸附到 9）", (await idxs(pid)).includes(9) && (await playhead()) === 9, (await idxs(pid)).join());
  await key("End", "End", 0, 35); await sleep(150);
  await key("ArrowLeft", "ArrowLeft", 2, 37); await sleep(150);
  check("Ctrl+← 跳到上一个关键帧", (await playhead()) === 9, await playhead());

  // ---------- 双击时间轴加帧；拖动关键帧时预览 ----------
  const lane = await box(".lane");
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: fx(50), y: lane.y + lane.h - 4, button: "left", buttons: 1, clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: fx(50), y: lane.y + lane.h - 4, button: "left", buttons: 0, clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: fx(50), y: lane.y + lane.h - 4, button: "left", buttons: 1, clickCount: 2 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: fx(50), y: lane.y + lane.h - 4, button: "left", buttons: 0, clickCount: 2 });
  await settle();
  check("双击时间轴加关键帧（吸附到 49）", (await idxs(pid)).includes(49), (await idxs(pid)).join());
  const dpos = await ev(`(()=>{const e=[...document.querySelectorAll('.kf')].find(e=>e.textContent.trim()==='49');const r=e.querySelector('.dia').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await mouse("mouseMoved", dpos.x, dpos.y, 0); await mouse("mousePressed", dpos.x, dpos.y);
  for (let i = 1; i <= 8; i++) { await mouse("mouseMoved", dpos.x + i * 32, dpos.y); await sleep(30); }
  await sleep(300);
  const dragInfo = await info(), dragSrc = await canvasSrc();
  check("拖动关键帧时画布预览新位置的画面", dragInfo.includes("拖动中") && dragSrc.includes("/clip/"), dragInfo + " | " + dragSrc);
  await mouse("mouseReleased", dpos.x + 256, dpos.y, 0); await settle();
  const moved = await idxs(pid);
  check("松手后关键帧移到新位置", !moved.includes(49) && moved.some((x) => x > 49 && x % 8 === 1), moved.join());

  // ---------- 源视频总览条：拖选框改起始帧 ----------
  const s0 = (await proj(pid)).project.reference.start25;
  const win = await box(".ovrow .win");
  await mouse("mouseMoved", win.x + win.w / 2, win.y + win.h / 2, 0); await mouse("mousePressed", win.x + win.w / 2, win.y + win.h / 2);
  for (let i = 1; i <= 6; i++) { await mouse("mouseMoved", win.x + win.w / 2 + i * 15, win.y + win.h / 2); await sleep(40); }
  check("拖动选框时显示起始帧小图", await ev(`!!document.querySelector('.ovrow .tip img')`));
  await mouse("mouseReleased", win.x + win.w / 2 + 90, win.y + win.h / 2, 0); await settle(1800);
  const s1 = (await proj(pid)).project.reference.start25;
  check("松手后起始帧写进项目", s1 > s0, `${s0} → ${s1}`);
  await sleep(1500);
  check("时间轴缩略图换成新起始帧的画面", (await ev(`document.querySelector('.lane .film img').getAttribute('src')`)).includes(`/clip/${s1}/`));
  await shot("T2_overview");

  // ---------- 超出时长的关键帧提示 ----------
  await key("End", "End", 0, 35); await sleep(100);
  await clickText("1 秒"); await settle();
  check("缩短时长后提示有关键帧不参与生成", (await ev(`document.querySelector('.warnbtn')?.textContent||''`)).includes("不参与生成"));
  await clickText("3 秒"); await settle();

  // ---------- 生成前补保存：描述框里直接写英文 ----------
  await key("Home", "Home", 0, 36); await sleep(200);
  await tool("/画笔/"); await draw([[0.45, 0.5], [0.55, 0.5]]); await settle();   // 首帧画上，其余关键帧留空
  await ev(`(()=>{const t=[...document.querySelectorAll('textarea')].find(e=>e.placeholder.includes('橙红色火球'));t.value='giant green flames swirl upward';t.dispatchEvent(new Event('input'))})()`);
  await clickText("▶ 生成");
  await sleep(1500);
  const dlg = await ev(`document.querySelector('.mask .box')?.textContent||''`);
  check("有空关键帧时生成前提醒，并可按项目关闭", dlg.includes("没画") && dlg.includes("不再提醒"), dlg.slice(0, 120));
  await ev(`document.querySelector('.mask .chk input').click()`);
  await clickText("照样生成", ".mask button"); await sleep(1500);
  const pj = (await proj(pid)).project;
  check("提交生成时磁盘上的提示词已包含描述（不会用旧提示词生成）", pj.prompt.final.includes("giant green flames"), pj.prompt.final);
  check("勾选“不再提醒”记进项目", pj.skip_empty_warning === true);
  const job = await ev(`(async()=>{const s=await (await fetch('api/status')).json();return s.queue.find(j=>j.project===${JSON.stringify(pid)})})()`);
  check("生成任务已提交", !!job, job);
  if (job) {
    await clickText("取消生成"); await sleep(1500);
    const j2 = await (await fetch(APP + `api/jobs/${job.id}`)).json();
    check("等引擎时取消：任务马上结束为已取消", j2.state === "cancelled", j2.state);
  }
  await shot("T3_generate");

  const errs = events.filter((e) => e.method === "Runtime.exceptionThrown" || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"));
  check("无前端异常", errs.length === 0, errs.map((e) => JSON.stringify(e.params).slice(0, 300)).join(" | "));

  // ---------- 删除项目（界面） ----------
  await clickText("打开"); await sleep(800);
  await ev(`(()=>{const it=[...document.querySelectorAll('.item')].find(e=>e.textContent.includes('时间轴验收'));it.querySelector('button.danger').click()})()`); await sleep(500);
  await clickText("删除", ".mask .btns button"); await sleep(2000);
  const still = await ev(`(async()=>(await (await fetch('api/projects')).json()).some(p=>p.id===${JSON.stringify(pid)}))()`);
  check("在项目列表里删除项目（移到回收站）", !still);
  if (!still) pid = null;
} catch (e) { console.error("UI TIMELINE ERROR", e); try { await shot("99_error"); } catch {} }
finally {
  if (pid) await fetch(APP + `api/projects/${pid}`, { method: "DELETE" }).catch(() => {});
  chrome.kill();
  fs.writeFileSync(path.join(OUT, "ui_timeline_results.json"), JSON.stringify(results, null, 1));
  console.log("[tl]", `共 ${results.length} 项，失败 ${results.filter((r) => !r.ok).length}`);
}
