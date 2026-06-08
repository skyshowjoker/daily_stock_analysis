---
name: earnings_analysis
display_name: 盈利与财报分析
description: 将财报、盈利质量、市场预期和价格反应组合成可验证的盈利分析。
category: framework
required-tools: get_financial_services_capabilities, get_stock_info, search_comprehensive_intel, get_realtime_quote, analyze_trend
aliases: [财报分析, 盈利分析, earnings]
default-priority: 120
---
# 盈利与财报分析

先调用 `get_financial_services_capabilities` 确认真实可用的数据边界。不得假设存在卖方一致预期、逐项财务模型或付费数据。

1. 使用 `get_stock_info` 检查收入、利润、现金流、ROE、估值和覆盖状态。
2. 使用 `search_comprehensive_intel` 查找最新财报、业绩预告、管理层表述和市场预期变化。
3. 区分收入增长、利润率变化、一次性损益和现金流质量。
4. 使用 `get_realtime_quote` 与 `analyze_trend` 判断业绩信息是否已被价格反映。
5. 输出超预期/符合预期/低于预期判断、关键驱动、风险和下一观察节点；缺少一致预期时明确写明。
