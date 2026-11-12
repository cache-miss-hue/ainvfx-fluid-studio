// 纯函数光栅工具：在 {width,height,data:Uint8ClampedArray(RGBA)} 上直接写像素。
// 不使用 Canvas 2D 的 arc/lineTo，避免抗锯齿混色。绘制函数返回被改动的包围盒 [x0,y0,x1,y1]（含），或 null。

export function createLayer(width, height) {
  return { width, height, data: new Uint8ClampedArray(width * height * 4) }
}

export function cloneLayer(img) {
  return { width: img.width, height: img.height, data: new Uint8ClampedArray(img.data) }
}

export function hexToRgb(hex) {
  let h = String(hex || '').trim().replace(/^#/, '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}

export function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')
}

export function hsvToRgb(h, s, v) {
  h = ((h % 360) + 360) % 360
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0, g = 0, b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)]
}

export function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
  let h = 0
  if (d) {
    if (mx === r) h = 60 * (((g - b) / d) % 6)
    else if (mx === g) h = 60 * ((b - r) / d + 2)
    else h = 60 * ((r - g) / d + 4)
  }
  if (h < 0) h += 360
  return [h, mx === 0 ? 0 : d / mx, mx]
}

export function unionBox(box, x0, y0, x1, y1) {
  if (!box) return [x0, y0, x1, y1]
  if (x0 < box[0]) box[0] = x0
  if (y0 < box[1]) box[1] = y0
  if (x1 > box[2]) box[2] = x1
  if (y1 > box[3]) box[3] = y1
  return box
}

/**
 * 圆形印章（整数像素）。cx,cy 为像素格坐标（整数），size 为直径（像素数）。
 * mode: 'paint' | 'erase'；rgb: [r,g,b]；soft: 柔边（边缘 alpha 渐变，RGB 仍为精确选中色）。
 */
export function stamp(img, cx, cy, size, rgb, mode = 'paint', soft = false, box = null) {
  const W = img.width, H = img.height, data = img.data
  const r = Math.max(0.5, size / 2)
  const ccx = cx + 0.5, ccy = cy + 0.5
  const x0 = Math.max(0, Math.floor(ccx - r)), x1 = Math.min(W - 1, Math.ceil(ccx + r))
  const y0 = Math.max(0, Math.floor(ccy - r)), y1 = Math.min(H - 1, Math.ceil(ccy + r))
  const r2 = r * r
  let touched = false
  for (let y = y0; y <= y1; y++) {
    const dy = y + 0.5 - ccy
    for (let x = x0; x <= x1; x++) {
      const dx = x + 0.5 - ccx
      const d2 = dx * dx + dy * dy
      if (d2 > r2) continue
      const i = (y * W + x) * 4
      if (!soft) {
        if (mode === 'erase') { data[i] = 0; data[i + 1] = 0; data[i + 2] = 0; data[i + 3] = 0 }
        else { data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; data[i + 3] = 255 }
      } else {
        // 内 50% 半径实心，向外线性衰减
        const t = Math.sqrt(d2) / r
        const f = t <= 0.5 ? 1 : Math.max(0, (1 - t) / 0.5)
        if (mode === 'erase') {
          const na = Math.round(data[i + 3] * (1 - f))
          data[i + 3] = na
          if (na === 0) { data[i] = 0; data[i + 1] = 0; data[i + 2] = 0 }
        } else {
          const a = Math.round(255 * f)
          if (a >= data[i + 3]) { data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; data[i + 3] = a }
        }
      }
      touched = true
    }
  }
  if (!touched) return box
  return unionBox(box, x0, y0, x1, y1)
}

/** 沿线段按 ≤半径/2 的步长插值盖章。 */
export function strokeLine(img, x0, y0, x1, y1, size, rgb, mode = 'paint', soft = false, box = null) {
  const step = Math.max(0.5, size / 4)
  const dx = x1 - x0, dy = y1 - y0
  const len = Math.hypot(dx, dy)
  const n = Math.max(1, Math.ceil(len / step))
  for (let k = 0; k <= n; k++) {
    const t = k / n
    box = stamp(img, Math.floor(x0 + dx * t), Math.floor(y0 + dy * t), size, rgb, mode, soft, box)
  }
  return box
}

function sameRGBA(d, i, r, g, b, a) {
  if (d[i + 3] === 0 && a === 0) return true
  return d[i] === r && d[i + 1] === g && d[i + 2] === b && d[i + 3] === a
}

/** 油漆桶：RGBA 完全相等（全透明视为相等）的 4 邻域连通区域，扫描线填充。 */
export function floodFill(img, sx, sy, rgb) {
  const W = img.width, H = img.height, data = img.data
  if (sx < 0 || sy < 0 || sx >= W || sy >= H) return null
  const si = (sy * W + sx) * 4
  const tr = data[si], tg = data[si + 1], tb = data[si + 2], ta = data[si + 3]
  const fr = rgb[0], fg = rgb[1], fb = rgb[2], fa = 255
  if (ta === 255 && tr === fr && tg === fg && tb === fb) return null
  const visited = new Uint8Array(W * H)
  const stack = [sx, sy]
  let box = null
  const match = (x, y) => !visited[y * W + x] && sameRGBA(data, (y * W + x) * 4, tr, tg, tb, ta)
  while (stack.length) {
    const y = stack.pop()
    const x = stack.pop()
    if (!match(x, y)) continue
    let xl = x
    while (xl > 0 && match(xl - 1, y)) xl--
    let xr = x
    while (xr < W - 1 && match(xr + 1, y)) xr++
    for (let k = xl; k <= xr; k++) {
      visited[y * W + k] = 1
      const i = (y * W + k) * 4
      data[i] = fr; data[i + 1] = fg; data[i + 2] = fb; data[i + 3] = fa
    }
    box = unionBox(box, xl, y, xr, y)
    for (const ny of [y - 1, y + 1]) {
      if (ny < 0 || ny >= H) continue
      let inRun = false
      for (let k = xl; k <= xr; k++) {
        const m = match(k, ny)
        if (m && !inRun) { stack.push(k, ny); inRun = true } else if (!m) inRun = false
      }
    }
  }
  return box
}

export function isEmpty(img) {
  const d = img.data
  for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return false
  return true
}

export function clearLayer(img) {
  const had = !isEmpty(img)
  img.data.fill(0)
  return had ? [0, 0, img.width - 1, img.height - 1] : null
}

/** 两图逐字节比较，返回差异包围盒（无差异返回 null）。 */
export function diffBox(a, b) {
  const W = a.width, H = a.height
  const da = a.data, db = b.data
  let y0 = -1, y1 = -1, x0 = W, x1 = -1
  for (let y = 0; y < H; y++) {
    const row = y * W * 4
    let rx0 = -1, rx1 = -1
    for (let x = 0; x < W; x++) {
      const i = row + x * 4
      if (da[i] !== db[i] || da[i + 1] !== db[i + 1] || da[i + 2] !== db[i + 2] || da[i + 3] !== db[i + 3]) {
        if (rx0 < 0) rx0 = x
        rx1 = x
      }
    }
    if (rx0 >= 0) {
      if (y0 < 0) y0 = y
      y1 = y
      if (rx0 < x0) x0 = rx0
      if (rx1 > x1) x1 = rx1
    }
  }
  return y0 < 0 ? null : [x0, y0, x1, y1]
}

export function cropPatch(img, box) {
  const x0 = box[0], y0 = box[1]
  const w = box[2] - x0 + 1, h = box[3] - y0 + 1
  const out = new Uint8ClampedArray(w * h * 4)
  for (let y = 0; y < h; y++) {
    const s = ((y0 + y) * img.width + x0) * 4
    out.set(img.data.subarray(s, s + w * 4), y * w * 4)
  }
  return { x: x0, y: y0, w, h, data: out }
}

export function applyPatch(img, patch) {
  for (let y = 0; y < patch.h; y++) {
    const d = ((patch.y + y) * img.width + patch.x) * 4
    img.data.set(patch.data.subarray(y * patch.w * 4, (y + 1) * patch.w * 4), d)
  }
}

/** 最近邻缩放。 */
export function resizeNearest(img, nw, nh) {
  const out = createLayer(nw, nh)
  for (let y = 0; y < nh; y++) {
    const sy = Math.min(img.height - 1, Math.floor(((y + 0.5) * img.height) / nh))
    for (let x = 0; x < nw; x++) {
      const sx = Math.min(img.width - 1, Math.floor(((x + 0.5) * img.width) / nw))
      const s = (sy * img.width + sx) * 4, d = (y * nw + x) * 4
      out.data[d] = img.data[s]; out.data[d + 1] = img.data[s + 1]
      out.data[d + 2] = img.data[s + 2]; out.data[d + 3] = img.data[s + 3]
    }
  }
  return out
}

/** 吸管：取“底图 + 笔触”的合成色。base 可为 null（按黑底）。返回 [r,g,b] 或 null。 */
export function sampleComposite(base, strokes, x, y) {
  x = Math.floor(x); y = Math.floor(y)
  if (x < 0 || y < 0 || x >= strokes.width || y >= strokes.height) return null
  let br = 0, bg = 0, bb = 0
  if (base && x < base.width && y < base.height) {
    const j = (y * base.width + x) * 4
    br = base.data[j]; bg = base.data[j + 1]; bb = base.data[j + 2]
  }
  const i = (y * strokes.width + x) * 4
  const a = strokes.data[i + 3] / 255
  return [
    Math.round(strokes.data[i] * a + br * (1 - a)),
    Math.round(strokes.data[i + 1] * a + bg * (1 - a)),
    Math.round(strokes.data[i + 2] * a + bb * (1 - a)),
  ]
}
