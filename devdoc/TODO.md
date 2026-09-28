# SemShell 当前待办

更新：2026-09-23。当前实现是可执行的架构参考设计；行为以
[公开语义](../docs/semantics.md)为准。旧版本路线和勾选状态保留在
[历史 TODO](TODO-history.md)，不再用旧 API 的完成记录描述当前能力。

## 已有实现与证据

| 内容 | 证据 |
| --- | --- |
| Human、Rule、脚本 LLM 三种 Operator 执行同一任务 | `tests/test_operator_demo.py`、`tests/test_demo_cli.py`；[主命令](../README.md#60-second-architecture-proof) |
| Kernel 不按 Operator 角色分支，guest 通过 Event/Action 工作 | `tests/test_operator_demo.py`、`tests/test_guest_abi_architecture.py` |
| IPC 来源认证、权限拒绝先于 Host 调用、级联取消和迟到结果抑制 | `tests/test_demo_cli.py`、`tests/test_kernel_resources.py`、`tests/test_kernel_lifecycle.py` |
| HostAdmin、Console 和 Process IPC 身份边界 | `tests/test_host_admin.py`；[安全模型](../docs/security-model.md) |
| UserShell 在自身权限内创建受限 worker，LLM 权限不提升 | `tests/test_delegation_demo.py`；[委派场景](../docs/delegation-demo.md) |
| 镜像、能力及资源描述的嵌套元数据不可变；权限报告支持混合 scope | `tests/test_catalog.py`、`tests/test_resource_values.py`、`tests/test_demo_cli.py` |

当前验证结果统一记录在[验收记录](../docs/design-edition-validation.md)。

## 演示与设计版收尾

- [ ] 补一个新注册的第四种同契约 Operator 场景：只改 Program/image 和
  bootstrap/catalog 组装，复用现有 Kernel、worker/coordinator；提供运行入口和测试。
  已有三种 Operator 的等价性测试不等同于该扩展场景。
- [ ] 补简短架构对照表，说明 Agent/Tool 专用 Kernel 分支的耦合点与当前证据的对应关系；
  不宣称未经测量的性能或智能水平提升。
- [ ] 记录独立读者的身份、日期、对四个架构问题的回答及未解决疑点，完成 Stage 6 sign-off。
  [验收记录](../docs/design-edition-validation.md#reader-review-and-freeze-status)列出了问题；
  自动化测试和本次文档检查不能替代该签署。
- [ ] 发布前确认历史恢复引用：当前本地没有 `complete-reference` 分支或
  `complete-reference-20260915` 标签，已有提交
  `73c133d7a55bfec349708a276b8f91fb3011844a` 可恢复。核对远端或改用提交引用，
  不把本地缺少引用写成远端也不存在。

## 文章与发布

- [ ] 按最新代码和演示更新[文章计划](article_writing_plan.md)的证据映射，
  纳入委派案例，确认中文稿与原英文文章计划的交付关系。
- [ ] 核对并补齐生态比较所需的一手来源；未核验的比较不得作为实现结论。
- [ ] 完成文章正文和无上下文读者检查，确定最终发布语言与稿件。
- [ ] 准备独立发布仓库和明确选择的发布文件；本次整理不表示已经发布。

`SemShell_zh.md` 是正在编辑的中文稿。`SemShell_zh copy.md` 是已跟踪的早期稿，
保留作历史对照；不自动合并、删除或将其当成当前文章。

## 工程改进候选

以下尚未配置，但不属于当前架构证明的完成门槛；按后续交付需求选择：

- [ ] 将 README 中的 pytest、Ruff、mypy 和离线演示接入 CI，覆盖声明支持的 Python 环境。
- [ ] 如需 `pip install` 和直接 `semshell` 命令，再增加包元数据与 console entry point；
  当前受支持的运行方式是仓库根目录下的 `python -m semshell.cli.main`。
- [ ] 如需长期重现固定工具环境，补依赖约束或锁定文件；现有 requirements 只声明版本下限。

## 不属于本仓库的遗漏

生产 transport、持久化、容器执行器、真实文件系统/网络/secret 注入、流式订阅、
supervisor、多 worker、认证与遥测属于独立 Linux/OCI runtime，见
[参考实现与生产边界](../docs/reference-and-production.md)。已移除的 Control REPL、
Detach、Wait ANY、reap、运行时 unregister、部分授权与取消模式不需要恢复。
