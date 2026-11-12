# AInVFX Fluid Studio · 多关键帧流体特效

[English](README.md) | **简体中文**

用画笔画出烟、蒸汽、火、爆炸、水、尘、雾、云的**形状**，软件把色块变成真实流体特效，并自动补出关键帧之间的运动。视频生成**全程离线**，使用本机显卡（LTX-2.5 + AInVFX Fluid IC-LoRA，经固定版本的 ComfyUI 后端）。

> **本仓库只提供项目框架，不包含、也不再分发任何模型权重。** 模型请从下方官方页面自行下载，并在对应页面同意其许可。

## 运行要求
- Windows 10/11 64 位；NVIDIA 显卡，按 **16GB 显存**设计与测试（≤12GB 未测试）；建议 64GB 内存；驱动 580+。
- 约 35GB 磁盘空间（模型约 32GB + 引擎约 4GB）。
- 需要 Git Bash 运行安装脚本；只有想重新构建网页界面时才需要 Node.js 18+。

## 安装
1. **构建引擎**（Python 3.12 嵌入版 + 固定版本 ComfyUI + 节点包；需联网，必要时设 `HTTPS_PROXY`）：
   ```bash
   bash scripts/build_engine.sh
   ```
2. **FFmpeg**：从 <https://www.gyan.dev/ffmpeg/builds/> 或 <https://github.com/BtbN/FFmpeg-Builds> 下载 Windows 版，把 `ffmpeg.exe`、`ffprobe.exe`（共享版还需 DLL）放进 `tools/ffmpeg/`。
3. **下载模型**到 `models/` 对应子目录（文件名不要改）。启动后右上角“自检”会检查文件是否齐全、大小是否正确；SHA-256 见 `models.manifest.json`。
4. 双击 `start.bat`（仅本机）或 `start_lan.bat`（平板手写笔，局域网 + 口令保护）。

## 模型下载
| 文件 | 放到 | 大小 | 来源 | 许可 / 门禁 |
|---|---|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models/` | 21.5GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5/blob/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors) | LTX-2.x 社区许可 · **需同意条款** |
| `gemma4-12b-with-proj-ltx-2.5-Q4_K_M.gguf` | `models/text_encoders/` | 8.4GB | [elix3r/gemma4-12b-with-proj-ltx-2.5-GGUF](https://huggingface.co/elix3r/gemma4-12b-with-proj-ltx-2.5-GGUF/blob/main/gemma4-12b-with-proj-ltx-2.5-Q4_K_M.gguf) | 以仓库页面为准（Gemma 4 / LTX 条款）· **需同意条款** |
| `ltx-2.5-video-vae-bf16.safetensors` | `models/vae/` | 1.5GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-video-vae-bf16.safetensors) | LTX-2.x 社区许可 · **需同意条款** |
| `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae/` | 0.36GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-audio-vae-bf16.safetensors) | LTX-2.x 社区许可 · **需同意条款** |
| `ainvfx-fluid.safetensors`（IC-LoRA） | `models/loras/` | 0.65GB | [AInVFX/ainvfx-fluid](https://huggingface.co/AInVFX/ainvfx-fluid/blob/main/ltx-2.5/ainvfx-fluid.safetensors) | LTX-2.x 社区许可（衍生模型）；训练数据 CC BY 4.0 |

带“需同意条款”的仓库须先登录 Hugging Face 并在仓库页面点同意。国内网络可把 `huggingface.co` 换成 `hf-mirror.com`。

## 使用（简版）
选底图模式 → 选时长（1–5 秒）和关键帧方案 → 每个关键帧纯色平涂（橙+黄=火/爆炸，深灰=浓烟，浅灰=烟，白=蒸汽/云，浅蓝+白=水）→ 填提示词表单 → **生成**。完整说明见 [`docs/README-原始说明.txt`](docs/README-原始说明.txt)。

“中文转英文”是可选功能，走你在界面里配置的外接大模型接口（OpenAI / Anthropic 兼容），密钥只保存在本机 `.env`，不会提交到仓库。视频生成本身不联网、无遥测。

## 示例项目
`examples/示例_坦克爆炸_3a7628/` 是现成的演示项目（坦克爆炸：首尾关键帧 + 参考图）。把整个文件夹复制到 `projects/` 里，刷新软件即可打开。示例图片版权归 cache-miss-hue，以 CC BY 4.0 发布。

## 开发
```bash
cd app/web && npm install && npm run build && npm test       # 网页界面
engine/python/python.exe -s tests/unit_backend_test.py        # 不占显卡的后端测试
```

## 许可
- **本项目自身代码**：Apache-2.0（[LICENSE](LICENSE)）；`app/engine_nodes/` 因在 ComfyUI 进程内运行，采用 GPL-3.0。
- **模型不在本许可范围内。** LTX-2.5 与 AInVFX Fluid LoRA 适用 **LTX-2.x 社区许可**：个人及年收入 **< 1000 万美元**的主体可免费使用；年收入 ≥ 1000 万美元的主体在测试评估之外的商用需与 Lightricks 另签付费协议，并须遵守可接受使用政策。基于 Gemma 的文本编码器另有其条款。使用或再分发前请阅读各模型页面。
- 第三方组件见 [NOTICE](NOTICE) 与 [`licenses/`](licenses/)。
- 本说明不构成法律意见，请以官方页面的最新条款为准。
