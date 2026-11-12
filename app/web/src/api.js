// 后端接口封装。所有错误统一抛出带中文信息的 Error，不暴露堆栈。

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function parseError(res) {
  let msg = ''
  try {
    const j = await res.json()
    if (typeof j.detail === 'string') msg = j.detail
    else if (Array.isArray(j.detail)) msg = '请求参数不正确'
  } catch (_) { /* 非 JSON */ }
  if (!msg) {
    if (res.status === 404) msg = '找不到对应的内容'
    else if (res.status >= 500) msg = '后端出错了，请稍后重试'
    else msg = `请求失败（${res.status}）`
  }
  return new ApiError(msg, res.status)
}

export async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} }
  if (body instanceof Blob || body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(url, init)
  } catch (_) {
    throw new ApiError('无法连接到后端，请确认软件仍在运行', 0)
  }
  if (!res.ok) throw await parseError(res)
  if (opts.raw) return res
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  return ct.includes('json') ? res.json() : res
}

const enc = encodeURIComponent
export const api = {
  status: () => request('GET', '/api/status'),
  selfcheck: () => request('GET', '/api/selfcheck'),
  meta: () => request('GET', '/api/meta'),
  timeline: (seconds, scheme) =>
    request('GET', `/api/timeline?seconds=${seconds}` + (scheme != null ? `&scheme=${scheme}` : '')),
  listProjects: () => request('GET', '/api/projects'),
  createProject: (name) => request('POST', '/api/projects', { name }),
  getProject: (pid) => request('GET', `/api/projects/${enc(pid)}`),
  putProject: (pid, project) => request('PUT', `/api/projects/${enc(pid)}`, project),
  duplicate: (pid, name) => request('POST', `/api/projects/${enc(pid)}/duplicate`, { name }),
  getStrokes: (pid, kid) => request('GET', `/api/projects/${enc(pid)}/strokes/${enc(kid)}`, undefined, { raw: true }),
  putStrokes: (pid, kid, blob) => request('PUT', `/api/projects/${enc(pid)}/strokes/${enc(kid)}`, blob),
  delStrokes: (pid, kid) => request('DELETE', `/api/projects/${enc(pid)}/strokes/${enc(kid)}`),
  uploadReference: (pid, file) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    return request('POST', `/api/projects/${enc(pid)}/reference`, fd)
  },
  uploadFrameRef: (pid, slot, file) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    return request('POST', `/api/projects/${enc(pid)}/frame_ref/${slot}`, fd)
  },
  deleteFrameRef: (pid, slot) => request('DELETE', `/api/projects/${enc(pid)}/frame_ref/${slot}`),
  frameRefUrl: (pid, slot, rev) => `/api/projects/${enc(pid)}/frame_ref/${slot}/file?t=${rev}`,
  deleteReference: (pid) => request('DELETE', `/api/projects/${enc(pid)}/reference`),
  baseUrl: (pid, index, rev) => `/api/projects/${enc(pid)}/base/${index}?t=${rev}`,
  refFileUrl: (pid, rev) => `/api/projects/${enc(pid)}/reference/file?t=${rev}`,
  refFrameUrl: (pid, n, rev, w = 640) => `/api/projects/${enc(pid)}/reference/frame/${n}?w=${w}&t=${rev}`,
  clipUrl: (pid, start, i, rev) => `/api/projects/${enc(pid)}/clip/${start}/${i}?t=${rev}`,
  deleteProject: (pid) => request('DELETE', `/api/projects/${enc(pid)}`),
  deleteResult: (file) => request('DELETE', `/api/results?file=${enc(file)}`),
  engineRestart: () => request('POST', '/api/engine/restart'),
  engineFree: () => request('POST', '/api/engine/free'),
  lan: () => request('GET', '/api/lan'),
  compose: (form, base_mode) => request('POST', '/api/prompt/compose', { form, base_mode }),
  translate: (text) => request('POST', '/api/prompt/translate', { text }),
  getTranslateConfig: () => request('GET', '/api/translate/config'),
  putTranslateConfig: (config) => request('PUT', '/api/translate/config', config),
  testTranslate: (text, config) => request('POST', '/api/translate/test', { text, config }),
  listTranslateModels: (config) => request('POST', '/api/translate/models', { config }),
  getGlossary: () => request('GET', '/api/glossary'),
  putGlossary: (user) => request('PUT', '/api/glossary', { user }),
  generate: (pid) => request('POST', `/api/projects/${enc(pid)}/generate`),
  getJob: (jid) => request('GET', `/api/jobs/${enc(jid)}`),
  cancelJob: (jid) => request('POST', `/api/jobs/${enc(jid)}/cancel`),
  results: (pid) => request('GET', `/api/projects/${enc(pid)}/results`),
  overlay: (file, blend) => request('POST', '/api/results/overlay', { file, blend }),
  mediaUrl: (file) => '/media/' + file.split('/').map(enc).join('/'),
}
