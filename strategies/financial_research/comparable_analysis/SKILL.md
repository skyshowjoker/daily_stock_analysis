---
name: comparable_analysis
display_name: 可比公司分析
description: 在现有公开数据边界内比较估值、成长、质量和市场表现，并明确数据缺口。
category: framework
required-tools: get_financial_services_capabilities, get_stock_info, get_realtime_quote, search_comprehensive_intel
aliases: [可比公司, 竞品分析, comps]
default-priority: 135
---
# 可比公司分析

1. 明确用户指定或公开信息支持的可比公司集合，不得凭空扩充。
2. 对每家公司分别调用 `get_stock_info` 与 `get_realtime_quote`，比较 PE、PB、市值、增长、ROE、现金流和价格表现。
3. 使用 `search_comprehensive_intel` 解释估值差异背后的业务、行业和事件原因。
4. 输出可比性限制：市场、会计口径、业务结构、币种和数据日期。
5. 当前工具无法完成完整 DCF、交易数据库或付费一致预期比较；需要这些能力时调用 `get_financial_services_capabilities` 并明确降级。
