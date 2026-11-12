// node tests/raster.test.mjs
import assert from 'node:assert/strict'
import { createLayer, strokeLine, stamp, floodFill, clearLayer, isEmpty, diffBox, cropPatch, applyPatch,
  cloneLayer, resizeNearest, hexToRgb, rgbToHex, hsvToRgb, rgbToHsv, sampleComposite } from '../src/lib/raster.js'

const W = 200, H = 120
const RED = [255, 120, 20]

// 1. 画线后只出现选中色(a=255)和透明两种像素
{
  const img = createLayer(W, H)
  let box = strokeLine(img, 10, 10, 150, 90, 9, RED)
  box = strokeLine(img, 150, 90, 30, 100, 5, RED, 'paint', false, box)
  const seen = new Set()
  for (let i = 0; i < img.data.length; i += 4) {
    seen.add(img.data[i + 3] === 0 ? 'T' : img.data.subarray(i, i + 4).join(','))
  }
  assert.deepEqual([...seen].sort(), ['255,120,20,255', 'T'].sort())
  assert.ok(box && box[0] >= 0 && box[2] < W)
  for (let t = 0; t <= 1; t += 0.01) {
    const x = Math.floor(10 + 140 * t), y = Math.floor(10 + 80 * t)
    assert.equal(img.data[(y * W + x) * 4 + 3], 255)
  }
  console.log('ok 画线仅两种像素')
}

// 2. 1 像素笔刷恰好一个像素；边界裁剪不越界
{
  const img = createLayer(W, H)
  stamp(img, 5, 5, 1, RED)
  let n = 0
  for (let i = 3; i < img.data.length; i += 4) if (img.data[i]) n++
  assert.equal(n, 1)
  stamp(img, -3, -3, 20, RED)
  stamp(img, W + 2, H + 2, 20, RED)
  assert.equal(img.data.length, W * H * 4)
  console.log('ok 印章与边界')
}

// 3. 填充：不越界(被闭合轮廓挡住)，只改连通区域
{
  const img = createLayer(W, H)
  const G = [0, 255, 0]
  strokeLine(img, 50, 30, 120, 30, 3, G); strokeLine(img, 120, 30, 120, 80, 3, G)
  strokeLine(img, 120, 80, 50, 80, 3, G); strokeLine(img, 50, 80, 50, 30, 3, G)
  const before = cloneLayer(img)
  const box = floodFill(img, 80, 55, [0, 0, 255])
  assert.ok(box)
  assert.ok(box[0] >= 50 && box[2] <= 120 && box[1] >= 30 && box[3] <= 80, 'bbox 在框内 ' + box)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4
      const inside = x > 51 && x < 119 && y > 31 && y < 79
      if (inside) assert.deepEqual([...img.data.subarray(i, i + 4)], [0, 0, 255, 255], `inside ${x},${y}`)
      if (x < 49 || x > 121 || y < 29 || y > 81) assert.equal(img.data[i + 3], 0, `outside ${x},${y}`)
      if (before.data[i + 3] === 255) assert.deepEqual([...img.data.subarray(i, i + 4)], [0, 255, 0, 255])
    }
  }
  floodFill(img, 5, 5, [255, 0, 0])
  assert.equal(img.data[(55 * W + 80) * 4 + 2], 255)
  assert.equal(img.data[(55 * W + 80) * 4], 0)
  assert.equal(floodFill(img, 5, 5, [255, 0, 0]), null, '同色再填无变化')
  console.log('ok 填充不越界')
}

// 4. 橡皮清除、柔边
{
  const img = createLayer(W, H)
  strokeLine(img, 20, 20, 100, 20, 11, RED)
  strokeLine(img, 20, 20, 100, 20, 11, RED, 'erase')
  assert.ok(isEmpty(img))
  strokeLine(img, 20, 20, 100, 20, 11, RED)
  assert.ok(!isEmpty(img))
  clearLayer(img)
  assert.ok(isEmpty(img))
  strokeLine(img, 20, 60, 100, 60, 15, RED, 'paint', true)
  let soft = 0
  for (let i = 0; i < img.data.length; i += 4) {
    if (img.data[i + 3] > 0) {
      assert.deepEqual([...img.data.subarray(i, i + 3)], RED)
      if (img.data[i + 3] < 255) soft++
    }
  }
  assert.ok(soft > 0)
  console.log('ok 橡皮/清除/柔边')
}

// 5. 补丁撤销、diff、缩放、颜色转换、吸管
{
  const img = createLayer(W, H)
  const before = cloneLayer(img)
  strokeLine(img, 30, 30, 90, 70, 7, RED)
  const box = diffBox(before, img)
  const pb = cropPatch(before, box), pa = cropPatch(img, box)
  applyPatch(img, pb)
  assert.ok(isEmpty(img))
  applyPatch(img, pa)
  assert.equal(diffBox(img, cloneLayer(img)), null)
  const big = resizeNearest(img, W * 2, H * 2)
  assert.equal(big.width, W * 2)
  const set = new Set()
  for (let i = 0; i < big.data.length; i += 4) set.add(big.data[i + 3] === 0 ? 'T' : big.data.subarray(i, i + 4).join())
  assert.equal(set.size, 2)
  assert.equal(rgbToHex(...hexToRgb('#ff7814')), '#ff7814')
  const hsv = rgbToHsv(255, 120, 20)
  assert.deepEqual(hsvToRgb(hsv[0], hsv[1], hsv[2]), [255, 120, 20])
  const base = { width: W, height: H, data: new Uint8ClampedArray(W * H * 4).fill(100) }
  assert.deepEqual(sampleComposite(base, img, 0, 0), [100, 100, 100])
  assert.deepEqual(sampleComposite(base, img, 30, 30), RED)
  console.log('ok 补丁/缩放/颜色/吸管')
}
console.log('raster 测试全部通过')
