# Anthropic Financial Services Integration

本项目以适配方式接入 `anthropics/financial-services` 的研究理念，不直接复制其 Claude 插件运行时。

上游参考仓库：[anthropics/financial-services](https://github.com/anthropics/financial-services)（Apache-2.0）。本次集成使用本项目原生实现与工具契约，没有复制或打包上游付费连接器。

## 已接入

- `SKILL.md` 研究工作流：盈利与财报分析、投资逻辑研究、催化日历、可比公司分析。
- DSA 原生 Agent 工具：行情、日线、基本面、资金流、技术分析、新闻情报、组合与回测。
- `get_financial_services_capabilities`：在执行研究前返回真实能力边界，防止模型假设付费数据或插件可用。

能力目录中的 `available` 表示工具已注册；工具实际调用仍可能因缺少 API Key、网络或数据源失败而降级，Agent 必须保留这些运行时错误。

## 未直接接入

- 上游付费金融数据 MCP：需要各数据厂商订阅、凭据与独立 MCP runtime。
- Spreadsheet / document / presentation 插件：当前服务端 Agent 未暴露 Office 产物工具。
- 上游 Managed Agents：本项目继续使用现有 decision / technical / intel / risk / portfolio Agent。

## 兼容原则

- 研究工作流只能调用本项目工具注册表中真实存在的工具。
- 缺少付费数据、一致预期、专有交易库或 Office 插件时必须明确降级，不得编造。
- 外部连接器后续应通过独立适配器接入，保留当前数据源 fallback、超时和错误边界。

## 回滚

删除 `strategies/financial_research/`，并回退 `integration_tools.py`、`financial_services_integration.py` 与 Agent factory 注册即可；不会影响现有分析、数据源或 LLM 配置。
