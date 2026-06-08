---
name: catalyst_calendar
display_name: 催化日历
description: 梳理未来事件、潜在影响、兑现窗口和失效条件，形成事件驱动观察清单。
category: framework
required-tools: get_financial_services_capabilities, search_comprehensive_intel, search_stock_news, get_realtime_quote, analyze_trend
aliases: [催化日历, 事件日历, catalyst]
default-priority: 130
---
# 催化日历

1. 使用 `search_comprehensive_intel` 和 `search_stock_news` 收集带日期或时间窗口的财报、政策、产品、订单、解禁和监管事件。
2. 每个事件记录：预计时间、方向、可信度、影响路径、已反映程度和失效条件。
3. 使用 `get_realtime_quote` 与 `analyze_trend` 判断临近事件时的价格位置和风险收益。
4. 过去事件只能用于复盘，不得混入未来催化列表；日期不确定时明确标记“待确认”。
5. 不得编造上游付费日历数据。需要外部服务时先调用 `get_financial_services_capabilities`。
