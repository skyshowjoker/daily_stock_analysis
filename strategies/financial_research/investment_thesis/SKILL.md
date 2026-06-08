---
name: investment_thesis
display_name: 投资逻辑研究
description: 构建包含主张、证据、催化、风险和证伪条件的股票投资逻辑。
category: framework
required-tools: get_financial_services_capabilities, get_stock_info, search_comprehensive_intel, analyze_trend, get_realtime_quote
aliases: [投资逻辑, 投资论点, thesis]
default-priority: 125
---
# 投资逻辑研究

目标是形成可证伪的投资逻辑，而不是只输出看多或看空结论。

1. 用 `get_stock_info` 建立业务质量、增长、估值和资本效率基线。
2. 用 `search_comprehensive_intel` 提取行业趋势、竞争位置、关键事件和风险。
3. 用 `analyze_trend` 与 `get_realtime_quote` 检查市场是否确认该逻辑，以及当前价格是否透支预期。
4. 明确列出：核心主张、支持证据、反方证据、催化剂、证伪条件、观察指标和时间窗口。
5. 若需要付费研究、专家访谈或专有数据，先调用 `get_financial_services_capabilities`，并把缺口标为未验证。
