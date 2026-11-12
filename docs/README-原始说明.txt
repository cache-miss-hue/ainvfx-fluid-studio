【说明】这是软件在“完整离线包”形态下的原始中文说明。开源仓库不含模型和 Python 引擎，安装步骤请以仓库根目录 README.zh-CN.md 为准；下文关于“完整包已自带模型/无需安装 Python”的描述不适用于源码仓库。

AInVFX Fluid Studio · 多关键帧流体特效（离线版）
================================================

用画笔画出流体的形状，软件会把色块变成真实的烟、蒸汽、火、爆炸、水、尘、雾、云，
并自动补出关键帧之间的运动。视频生成全程离线，不需要安装 Python 或 ComfyUI。

【运行要求】
  Windows 10/11 64 位；NVIDIA 显卡，按 16GB 显存设计与测试（12GB 及以下未测试、不保证）；
  建议 64GB 内存；显卡驱动 580 或更新；完整包约 33GB，另需空间存放成片。

【启动】
  双击 start.bat → 浏览器自动打开界面。关闭黑色窗口即退出软件（后台引擎会一并关闭）。
  想用平板手写笔画：双击 start_lan.bat，在平板浏览器打开窗口里显示的“局域网访问地址”
  （打不开就试窗口里列出的其他地址；Windows 防火墙询问时请允许“专用网络”）。
  局域网模式需要访问口令：窗口里显示的地址已经带上口令，平板打开一次后浏览器会记住一年；
  也可以在平板打开的页面上手动输入口令。电脑本机不需要口令，电脑界面顶栏“平板访问”里随时能看到
  地址和口令。口令保存在 runtime\lan_token.txt，想换口令就删掉它再启动。
  双击 start.bat 启动时只允许本机访问，同一网络里的其他设备连不上。
  第一次生成要把约 30GB 模型读进内存，会多等 1–2 分钟；之后每段约 2 分钟（5 秒、1024×576）。

【使用步骤】
  1. 右侧①：选底图模式。0 黑底素材（可叠加到你的视频）；1 原图直接画；2 色块化后画。
     模式 1/2 需拖入参考图片或视频。
  2. 底部时间轴：选时长（1–5 秒）和关键帧方案（只首帧 / 首尾 / 每秒一帧）。
     用视频参考时，时间轴上方有一条“源视频”：拖动橙色框选择从视频哪里开始（= 起始帧）；
     也可以在右侧播放器里找到画面后点“用播放器当前画面作起始帧”。
     拖动下方标尺，画布会实时显示那一帧的画面；松手后自动停在模型最适合的帧号（吸附）。
     停在不是关键帧的位置时，直接在画布上画，就会在这一帧新建关键帧；
     也可以双击时间轴、按 K 或点“+ 加帧”。拖动菱形可以移动关键帧（拖动时画布显示新位置的画面）。
     快捷键：←/→ 跳到上/下一个吸附位置，Shift+←/→ 逐帧，Ctrl+←/→ 跳关键帧，Home/End 到首/尾帧。
  3. 中间画布：每个关键帧画该时刻特效的形状。纯色平涂，不要渐变：
     橙 + 黄 = 火/爆炸；深灰 = 浓烟；浅灰 = 烟；白 = 蒸汽/云；浅蓝 + 白 = 水。
     用到的关键帧没画 = 那一刻没有特效（生成前会提醒；有意留空可以勾选“本项目不再提醒”）。
     换参考图或底图模式不会丢已画的笔触。
  4. 右侧②：填提示词表单。可以写中文，点“转英文”（调用你在「翻译设置」里配置的翻译接口，结果可见可改）。
  5. 点“▶ 生成”。完成后可播放、下载 MP4；黑底素材可预览叠加效果并导出合成版。
  想换效果就改 seed。显存不足时软件会自动降低解码分块，仍不足请减小输出尺寸。
  想用显卡做别的事又不想关软件：点顶栏的“释放显存”（下次生成会重新加载模型）。
  引擎出错或意外退出时软件会自动重启它；仍不行就点顶栏的“重启引擎”。

【中文转英文（可选）】
  提示词可以写中文，翻译走外接大模型接口，不占本机显存。
  配置方法（推荐）：点顶栏的「翻译设置」按钮（或提示词面板里的「翻译接口…」），在弹出的设置页里填：
    接口地址（Base URL）  例如 https://api.deepseek.com（带不带 /v1 都行）
    API Key（密钥）       你的密钥；本机 Ollama / LM Studio 可不填
    模型名                例如 deepseek-chat；可点「拉取模型」从接口获取模型列表，搜索后点选
  填好点「保存」即写入软件目录的 .env，立即生效、不用重启。设置页里还有「发送测试」可以先试译一句，
  以及接口格式、深度推理、超时、随机性、最大输出长度、代理等高级选项。密钥在界面上只打码显示，不会明文回传。
  也可以直接用记事本编辑 .env（首次启动会自动从 .env.example 生成），对应这几行：
    FX_TRANSLATE_BASE_URL=https://api.deepseek.com      接口地址（带不带 /v1 都行）
    FX_TRANSLATE_API_KEY=你的密钥
    FX_TRANSLATE_MODEL=模型名
  兼容 OpenAI Chat Completions（DeepSeek、通义、Kimi、大多数中转站）、OpenAI Responses、
  Anthropic Messages 三种格式，默认自动识别；也可用本机的 Ollama / LM Studio。其余选项见 .env.example。
  不配置也能用：直接写英文提示词，或只用内置术语表替换特效词汇（界面会提示）。
  只有点“转英文”时才会联网；把软件转给别人时，打包脚本不会带上你的 .env（不会泄露密钥）。

【模型下载】（完整包已自带；精简包需要自己下载，放进 models\ 对应子目录，文件名不要改）
  文件                                                         放到                      大小     下载地址
  ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors  models\diffusion_models\  21.5GB
      https://huggingface.co/Lightricks/LTX-2.5/resolve/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors
  gemma4-12b-with-proj-ltx-2.5-Q4_K_M.gguf                     models\text_encoders\     8.4GB
      https://huggingface.co/elix3r/gemma4-12b-with-proj-ltx-2.5-GGUF/resolve/main/gemma4-12b-with-proj-ltx-2.5-Q4_K_M.gguf
  ltx-2.5-video-vae-bf16.safetensors                           models\vae\               1.5GB
      https://huggingface.co/Lightricks/LTX-2.5/resolve/main/vae/ltx-2.5-video-vae-bf16.safetensors
  ltx-2.5-audio-vae-bf16.safetensors                           models\vae\               0.36GB
      https://huggingface.co/Lightricks/LTX-2.5/resolve/main/vae/ltx-2.5-audio-vae-bf16.safetensors
  ainvfx-fluid.safetensors                                     models\loras\             0.65GB
      https://huggingface.co/AInVFX/ainvfx-fluid/resolve/main/ltx-2.5/ainvfx-fluid.safetensors
  注意：Lightricks/LTX-2.5 和 elix3r/gemma4-12b-with-proj-ltx-2.5-GGUF 两个仓库需要先登录
  Hugging Face、在仓库页面点同意许可后才能下载。国内网络可把 huggingface.co 换成镜像 hf-mirror.com。
  放好后启动软件，右上角“自检”会逐个检查文件是否齐全、大小是否正确。

【文件】
  projects\  每个项目一个文件夹（可整个复制分享）
  output\    生成的 MP4 与对应参数 JSON
  runtime\logs\  出错时的日志（engine.log 是引擎本次的日志，engine.prev.log 是上一次的）
  runtime\trash\ 在界面里删除的项目和结果先放这里，30 天后自动清除，期间可以手动拷回来
  runtime\cache\ 预览图缓存，14 天没用到的启动时自动清理，可以随时整个删掉

【开发者】
  界面源码在 app\web\src，软件实际加载的是构建好的 app\web\dist：改了源码要在 app\web 下
  运行 npm run build（npm test 跑前端单元测试）。不占显卡的后端测试：
  engine\python\python.exe -s tests\unit_backend_test.py

【许可】见 licenses\ 目录。LTX-2 模型：年收入 ≥1000 万美元的公司在测试评估之外的商用需与 Lightricks 另签协议。
