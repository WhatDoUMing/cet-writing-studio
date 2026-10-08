# 在线模型名称选择

日期：2026-10-08。

设置页的评分模型和在线 OCR 模型均使用可编辑下拉框。选择服务商后点击“获取模型列表”，可从列表选择、输入关键字补全，或保留手动输入；点击“保存设置”后应用。

## 查询来源

- OpenAI、DeepSeek 和自定义兼容 API 地址：读取当前服务的 `/models`，使用当前输入的 Key 或本项目已保存的 Key。
- 智谱默认官方地址：读取官方公开模型目录。评分候选限定文本/视觉对话模型；智谱 OCR 返回 GLM-OCR 条目。界面明确标明公开目录，目录不代表账户调用权限。
- 查询公开文档时不发送 API Key。自定义服务地址使用其自身模型列表，不回退为智谱公共目录。
- 本地 OCR 模型仍使用名称或本地路径配置。

## 操作与异常

查询在线程中进行，可继续编辑模型名称；结果到达后保留编辑中的原值，当前模型在下拉中保持选中。查询失败、Key 缺失、权限错误、接口不支持、空列表或格式异常均显示明确提示，保留原值并允许重试。

切换服务商、修改 Key、切换 OCR 模式、保存/重新加载配置或离开设置页会使旧查询失效；过期结果不覆盖新状态。缓存仅保留在当前进程，不将 Key 或模型查询结果写入普通设置文件。

## 验证

- 正式测试目录整体回归：**212 passed in 62.55s**，无失败或跳过。
- 网络替身覆盖接口/地址/鉴权、返回值去重、格式错误、HTTP 错误、超时、Key 不回显、异步过期、查询期间编辑、模型选择保存及 OCR Key 回退。
- 智谱公开目录已真实获取：本次 23 个评分候选模型、1 个 GLM-OCR 条目；设置页的实际后台查询与浅/深色下拉截图也已验证。
- 当前新项目 GLM/OpenAI/DeepSeek 均未配置 API Key；OpenAI、DeepSeek 和自定义服务的真实账户模型列表查询未验证。网络替身通过不代表真实账户可用性；没有调用真实作文评分或在线 OCR。
- 未执行 EXE/PyInstaller。

截图与日志保存在用户指定 outputs/model-picker，并镜像到当前聊天 outputs/model-picker。

接口依据：[OpenAI 模型列表](https://developers.openai.com/api/reference/resources/models/methods/list)、[DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models/)、[智谱公开模型目录](https://docs.bigmodel.cn/cn/guide/start/model-overview)。
