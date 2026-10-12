# 数据库迁移

[项目首页](../../README.md) · [全部文档](../../README.md#文档导航) · [后端启动](../README.md)

Alembic 从后端配置读取数据库连接；先按[后端指南](../README.md#首次启动)创建数据库和配置 `.env`。以下命令在 `backend/` 目录与项目虚拟环境中执行。

## 升级数据库

```powershell
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

已有数据库先备份，迁移成功后再启动新版本应用。不要用删除数据库或直接修改版本标记代替迁移。

## 新增迁移

修改模型后生成草案：

```powershell
python -m alembic revision --autogenerate -m "describe the schema change"
```

人工检查生成的 upgrade / downgrade、数据兼容性与 `down_revision`；自动生成不代表数据迁移已经正确。新增模型需确认已由 [`env.py`](env.py) 导入并注册到 metadata。在独立测试数据库上验证迁移后再提交。
