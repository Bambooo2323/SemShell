# 开发文档索引

当前公开契约位于 [docs/semantics.md](../docs/semantics.md)，项目入口是
[README](../README.md)。本目录保存工作清单、文章计划和历史决策，不能用历史方案替代当前契约。

## 当前工作

| 文档 | 用途 |
| --- | --- |
| [TODO.md](TODO.md) | 当前已完成证据、真实待办及工程改进候选 |
| [设计版验收](../docs/design-edition-validation.md) | 按日期记录验证结果、恢复入口与尚未完成的读者验收 |
| [迁移阶段](design_edition_migration_stages.md) | 已完成迁移的记录和 Stage 6 剩余验收门槛 |
| [文章计划](article_writing_plan.md) | 写作目标、素材和证据映射；仍需与当前中文稿对齐 |
| [2026-09-21 修改记录](change-log-2026-09-21.md) | 委派场景和当日文章修改的证据，不代表之后稿件状态 |
| [当前中文稿](../SemShell_zh.md) | 正在编辑的文章 |
| [早期中文稿](../SemShell_zh%20copy.md) | 已跟踪的历史草稿，保留对照 |

## 历史设计

| 文档 | 历史范围 |
| --- | --- |
| [旧 TODO](TODO-history.md) | 整理前的完整路线和状态；含已移除 API |
| [最初设计](llm_cli_os_design_draft.md)、[旧语义](semantics.md) | 原始完整参考实现的概念与契约 |
| [v0.1](version_0_1_scope.md)、[v0.2](version_0_2_resource_bridge_plan.md)、[v0.3](version_0_3_interactive_control_cli_plan.md) | 早期版本范围与实现计划 |
| [Control 协议](control_protocol_semantics.md)、[Libfuse 方案](libfuse_inspired_design_plan.md) | 已移除的 Control 和外部接口设计 |
| [资源桥](resource_bridge_semantics.md)、[Host 边界](host_boundary_and_sandbox.md)、[Docker 计划](docker_sandbox_plan.md) | 历史资源与隔离探索；当前仅保留内存资源证明 |
| [生命周期重构](lifecycle_rearchitecture.md)、[设计版简化](design_edition_simplification_plan.md) | 迁移理由与旧验收步骤 |

历史文档中提到的 `complete-reference` 分支与 `complete-reference-20260915` 标签
未出现在 2026-09-23 的本地检出中。已核实完整提交
`73c133d7a55bfec349708a276b8f91fb3011844a` 存在；恢复和查看方式见
[验收记录](../docs/design-edition-validation.md#retained-and-removed-scope)。
