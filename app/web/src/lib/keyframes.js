// 关键帧换算（纯函数）：与后端 projects.resolved_keyframes 同一规则。
// 两边都用 tests/fixtures/keyframes_cases.json 校验（app/web/tests/keyframes.test.mjs、tests/unit_backend_test.py）。

/** 吸附到最近的网格点；距离相同取较小的帧号。 */
export function snapTo(idx, grid) {
  let best = grid[0]
  for (const g of grid) if (Math.abs(g - idx) < Math.abs(best - idx) || (Math.abs(g - idx) === Math.abs(best - idx) && g < best)) best = g
  return best
}

/** 项目里的关键帧 → 实际帧号（尾帧跟随时长；开启吸附时落到网格；超出时长的隐藏；同一帧只留一个，尾帧优先）。 */
export function resolveKeyframes(p, tl) {
  if (!p || !tl || tl.seconds !== Number(p.seconds)) return []
  const out = []
  for (const kf of p.keyframes) {
    let idx = kf.tail ? tl.last : Number(kf.index)
    if (idx > tl.last || idx < 0) continue
    if (p.snap !== false) idx = snapTo(idx, tl.grid)
    out.push({ id: kf.id, index: idx, tail: !!kf.tail })
  }
  out.sort((a, b) => a.index - b.index || (a.tail ? -1 : 1) - (b.tail ? -1 : 1))
  const seen = new Set(), uniq = []
  for (const k of out) { if (!seen.has(k.index)) { seen.add(k.index); uniq.push(k) } }
  return uniq
}

/** 网格上相对 f 的下一个（dir=1）/上一个（dir=-1）位置；没有就停在两端。 */
export function stepOnGrid(f, dir, grid) {
  if (dir > 0) { for (const g of grid) if (g > f) return g; return grid[grid.length - 1] }
  for (let i = grid.length - 1; i >= 0; i--) if (grid[i] < f) return grid[i]
  return grid[0]
}
