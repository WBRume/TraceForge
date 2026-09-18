"""资产文档子域：解析、存储、版本化与修复。

对外模块划分（调用方直接 import 叶子模块，不在此处做 re-export）：
- payload          文档解析统一入口（parse_document_payload / can_inline_review）
- markdown_blocks  markdown / 纯文本 → blocks
- storage          任务资产目录与原文件落盘
- repository       版本查询
- versioning       版本创建与激活工作流
- repair           DOCX 版本内容修复
- serializer       ORM → API DTO
- docx/            DOCX 解析/构建私有子系统
"""
