// 关键帧换算：前端实现必须与后端给出同样的结果（期望值由 tests/fixtures/make_keyframes_cases.py 用后端生成）。
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { resolveKeyframes, snapTo, stepOnGrid } from '../src/lib/keyframes.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(fs.readFileSync(path.join(here, '../../../tests/fixtures/keyframes_cases.json'), 'utf8'))
let fail = 0
const check = (name, ok, detail = '') => { if (!ok) fail++; console.log(ok ? 'PASS' : 'FAIL', name, ok ? '' : detail) }

for (const c of cases) {
  const got = resolveKeyframes(c.project, c.timeline)
  check('与后端一致：' + c.name, JSON.stringify(got) === JSON.stringify(c.expected), JSON.stringify({ got, want: c.expected }))
}
const grid = [0, 1, 9, 17, 25, 33, 41, 48]
check('吸附：等距取小', snapTo(5, grid) === 1)
check('网格步进：向后', stepOnGrid(25, 1, grid) === 33 && stepOnGrid(30, 1, grid) === 33 && stepOnGrid(48, 1, grid) === 48)
check('网格步进：向前', stepOnGrid(25, -1, grid) === 17 && stepOnGrid(30, -1, grid) === 25 && stepOnGrid(0, -1, grid) === 0)
console.log(fail ? `失败 ${fail} 项` : '全部通过')
process.exit(fail ? 1 : 0)
