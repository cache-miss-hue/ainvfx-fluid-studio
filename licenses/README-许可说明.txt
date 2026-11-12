AInVFX Fluid Studio · 组件与模型许可说明 / Components & model licenses

本仓库不包含任何模型权重，也不包含第三方二进制。本目录保存第三方组件的许可证原文，
这些组件由 scripts/build_engine.sh 在你本机按固定版本下载，各自遵守其许可证：

  ComfyUI（固定 7a2833204）            GPL-3.0                    ComfyUI-LICENSE-GPL3.txt
  ComfyUI-LTXVideo（220e1d4）          LTX-2 Community License    ComfyUI-LTXVideo-LICENSE.txt
  ComfyUI-GGUF（molbal 分支 b601643）  Apache-2.0                 ComfyUI-GGUF-LICENSE.txt
  Python 3.12 embeddable               PSF License                Python-LICENSE.txt
  PyTorch / NumPy / Pillow / PyAV / Transformers / FastAPI 等    见 py-*-LICENSE.txt
  FFmpeg（需自行下载，GPL/LGPL 取决于构建）                       FFmpeg-LICENSE.txt

模型（不在本仓库内，由用户从官方页面下载，见 models.manifest.json 与根目录 README）：
  LTX-2.5 transformer / 视频 VAE / 音频 VAE —— LTX-2.x Community License Agreement（Lightricks）
  gemma4-12b-with-proj-ltx-2.5（GGUF）     —— 以其仓库页面声明为准
  ainvfx-fluid IC-LoRA                      —— LTX-2.x Community License（LTX-2.5 的衍生模型）

LTX-2.x 社区许可要点（摘自 https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x ，以原文为准）：
  年收入 >= 1000 万美元的主体（含关联公司合并计算），除非仅用于非商业目的，须向 Lightricks
  购买商业许可；分发 LTX-2.x 或其衍生品（含 LoRA）须附带完整协议并告知使用限制（Attachment A）。
  Key terms: entities with annual revenue >= US$10M (affiliates aggregated) need a paid Commercial Use
  Agreement for any use other than non-commercial purposes; redistributing LTX-2.x or derivatives
  (incl. LoRAs) requires a copy of the agreement and notice of the use restrictions (Attachment A).

本项目自身代码许可见仓库根目录 LICENSE 与 NOTICE。
视频生成不联网、无遥测。中文转英文是可选功能：只有在 .env 配置了翻译接口并点击“转英文”时，
才会把要翻译的文字发送到你配置的接口；密钥只保存在本机 .env，已被 .gitignore 排除。
