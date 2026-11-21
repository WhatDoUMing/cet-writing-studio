# CET Writing Studio · 四六级作文批改

Python + PyQt6 独立桌面应用，支持学生练习与教师复核。项目版本 1.0.0，来源信息见 [SOURCE.md](SOURCE.md)。本项目仅交付源码，不含 EXE。

## 安装与启动

已在 Windows、Python 3.13.5、PyQt6 环境验证。使用独立虚拟环境：

```powershell
# 在 Git 检出目录打开 PowerShell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

默认学生练习、CET-4、浅色主题、文本输入。无需登录。在设置中选择 AI 服务商并填写新项目 API Key；图片 OCR 作为可选入口，在线识别可使用独立 OCR Key，也可沿用本项目同服务商的评分 Key。模型名称可在设置中修改；自定义 API 地址可写入本项目 `config/settings.json` 的 `ai.providers.<provider>.api_base`。

本地 OCR 为可选项：安装 `requirements-local-ocr.txt`，在设置中切换本地模式并填写自己的模型目录。模型权重未随项目复制或上传。

模型名称使用可编辑下拉框：填写或已有 API Key 后点击“获取模型列表”，选择模型再保存设置，也可继续手动填写。评分和在线 OCR 分别提供查询按钮；获取期间可继续编辑，切换服务商、修改 Key 或离开设置会使旧查询结果失效，失败保留原填写值。

OpenAI / DeepSeek 和自定义兼容地址查询当前服务的 `/models`；智谱官方地址读取[官方公开模型目录](https://docs.bigmodel.cn/cn/guide/start/model-overview)，列表来源会显示在界面中，公开目录不代表账户调用权限。评分请选择文字对话模型，OCR 请选择支持图片输入的模型；智谱 OCR 目录仅提供适用的 GLM-OCR。自定义地址沿用本项目 API 配置，不向公共文档发送 Key。

## 使用

1. 首页选择 CET-4 或 CET-6；填写题目，可指定最低词数。
2. 默认直接输入或粘贴文本；需要处理图片时选择可选 OCR 入口。可为当前任务选择本级别参考范文。
3. 文本确认页编辑原文、检查拼写，并核对本地词数及题目长度要求。
4. 确认原文并评分。学生报告自动保存，展示 AI 练习分与文字诊断、纠错改写。
5. 顶部切到教师批改，可从历史打开学生练习报告复核；填审核教师，接受 AI 分或修改整数最终分和评语。修改建议时需填写原因。
6. 反馈默认仅保存在当前作文。教师完成复核并明确确认后，反馈才加入该考试级别的长期规则。

切换考试、模式或任务会使旧异步结果失效。草稿按模式和考试保留在当前进程中；关闭程序前未评分的手动草稿没有持久化恢复功能。已评分报告与记录来源保存在 SQLite。

键盘导航：Ctrl+1 首页、Ctrl+2 新作文、Ctrl+3 文本确认、Ctrl+H 历史、Ctrl+, 设置。Tab / Shift+Tab 移动焦点，原生控件响应 Enter 和方向键。导航与模式／考试切换即时完成。

完成考试与题目设置并继续后，左侧“文本确认”和 Ctrl+3 才会启用；新作文重新锁定此入口。未完成时导航显示为灰色。可操作按钮在悬停时轻微变色，纯展示卡片保持静止。

## 评分与数据

评分依据：[中国大学生在线：英语四六级考试题型和分值比例](https://dxs.moe.gov.cn/zx/a/kskt_yy/210601/1693612.shtml)。采用整体印象评分，0—15 整数；13—15 / 10—12 / 7—9 / 4—6 / 1—3 对应 14 / 11 / 8 / 5 / 2 分档，0 分单独处理。CET-4 和 CET-6 分别记录标准版本，长度问题纳入整体评价，不采用固定扣分公式。

AI 报告字段为 `score`、`dimension_feedback`（`content`、`language`、`structure`）、`overall_comment` 及四个诊断数组。程序计算 `score_band` 和 `word_count`。缺失字段、错误类型、布尔值、小数和越界分触发一次修正重试；再次失败时报告错误，不将结果显示为有效成绩。

词数规则：英文或数字单元计词，缩写、单词内撇号及连字符连接的复合词计一个词；标点与换行分隔。弯引号、常用 Unicode 连字符先规范化。中文和纯标点不增加词数。题目显式范围或最低要求优先，教师手动最低词数可覆盖默认要求。

每条记录保存创建模式、审核状态、AI 分、教师分、原始 AI 报告、实际提交文本、服务商／模型、提示词及评分标准版本。学生趋势读取学生来源记录的 AI 分；教师趋势读取已确认教师分；趋势按考试级别隔离。历史可以组合筛选考试、创建模式与审核状态，保留搜索、题目分组和分页。

独立位置：

| 数据 | 位置或标识 |
| --- | --- |
| 数据库 | `data/cet_writing.db` |
| 用户设置 | `config/settings.json` |
| 日志 | `logs/CETWritingStudio/app.log`，logger 为 `CETWritingStudio` |
| 规则镜像 | `data/CETWritingStudio/CET-4-rules.md` / `CET-6-rules.md` |
| Windows 凭据 | 服务名 `CETWritingStudio`，账户名使用 CET 专属前缀 |
| 加密回退 | 本项目 `config/CETWritingStudio/secrets.dpapi`；外部密钥目录 `%LOCALAPPDATA%/CETWritingStudio` |

数据库、密钥、日志、学生图像、用户设置及模型权重均不进入 Git。全新项目不读取原项目设置或凭据。

## 测试与界面截图

```powershell
New-Item -ItemType Directory -Path work -Force | Out-Null
python -m pytest tests --basetemp work/pytest -q
python tools/capture_ui.py --output work/screenshots
```

所有网络回归使用测试替身，测试会阻止意外真实 HTTP 请求。截图工具使用临时数据库和合成作文，不访问 AI 服务商。已覆盖主要页面、学生报告、教师复核、浅／深色主题，以及 960×640、1280×820、1600×1000 窗口布局。

真实 AI／在线 OCR 联调：当前新项目尚未配置 API Key，未进行真实调用。测试替身验证不代表真实模型质量或服务可用性。可选本地 OCR 的权重推理同样未验证，线程隔离已通过替身测试。

## 评测工具

```powershell
python -m evaluation.cli --input samples.jsonl --csv work/evaluation.csv --summary work/summary.json
```

JSONL 每行包含 `sample_id`、`essay_type`（CET-4 / CET-6）、`max_score`（15）、`question`、`student_text`、`teacher_score`（0—15 整数），可附 `teacher_score_2`。评测记录每次异常、分差、重复波动和按考试级别统计的误差；AI 对象报告使用与桌面端相同的严格字段校验。

## GitHub

目标：[WhatDoUMing/cet-writing-studio](https://github.com/WhatDoUMing/cet-writing-studio)，origin 为 `git@github.com:WhatDoUMing/cet-writing-studio.git`。本地按功能提交。获授权的更改推到独立分支，创建面向 `main` 的草稿 PR 并安排独立审核；不直接推送 `main`。远端操作使用授权账户已有的 GitHub 凭据。

### 可选的本地主题与开屏

本仓库只包含应用源码和可复现的合成测试，不附带奶家人图片、开屏音视频、私有预览入口或运行数据。不设置素材目录也能启动：缺少主题字体或插图时使用系统字体并保留文字提示，没有完整开屏素材时直接进入主页。普通启动是静音的。在线评分或在线 OCR 需在应用设置里填写自己的 API Key；测试使用合成稿与假服务，不需要密钥。

如果已经拥有这套素材，可将其保留在 Git 检出目录之外。将环境变量设为素材包所在目录，不用把文件复制进仓库：

```powershell
$env:CET_LOCAL_ASSETS_DIR = '填写你的本地素材目录'
python main.py --with-startup-audio
```

- 素材目录保留已有布局：`startup-assets/startup-v4.json` 与其引用的图片和帧、`ui-meme-assets/ui-meme-assets.json` 与六个用途的配图、`companions` 中的三张角色 PNG、`fonts` 中的 `ui-regular.ttf` 与 `ui-bold.ttf`。图像和字体仅由本机读取，不会自动下载。
- 若使用同一 3.4 秒开屏，在素材根目录保留原 `startup_audio_contract.json`，并把对应的 `hd-laugh-first-055-3400/laugh-fade-a.wav` 保留在 `startup-assets` 之下。程序核对清单、PCM 格式和 SHA-256；文件缺失或校验失败则静音。清单的 SHA-256 是文件完整性校验，不是内容许可证明。
- 声音仅在交互式 Windows 窗口明确加 `--with-startup-audio` 且本人点击 Start 后，由完整首帧触发；`--silent`、离屏和减少动态不启用音频。已有本机预览入口与个人数据不需要改动。
