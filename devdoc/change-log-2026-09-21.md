# 2026-09-21 修改记录

本次整理覆盖基线提交 `851b871` 之后的文章修改、权限委派案例、运行说明与测试。主要成果是将文章第二、三章的论证重新衔接，并用一个可离线运行的案例展示权限、所有权和任务协作之间的区别。

## 1. 中文文章

修改文件：[SemShell_zh.md](../SemShell_zh.md)。第一章保持原样，集中调整后续章节。

### 第二章：恢复为问题章

- 从 Agent Host 为什么会扩展到执行管理切入，区分认知连续性与执行连续性。
- 区分信息关系、调用关系与管理关系，说明“发起工作”不等于“由模型维护运行事实”。
- 将 DeepSeek Harness 的详细架构分析压缩为一节现实参照，保留已有机制及其来源，移除提前展开的 SemShell 对照。
- 用“协调程序同时启动测试程序与 LLM 分析程序”的概念场景，提出身份、权限、所有权、等待、取消和结果问题，再引向第三章。

### 第三章：从管理问题推导共同执行契约

- 明确认知侧信息与执行侧记录各自的管理主体。
- 将第二章的问题展开为共同执行契约，区分创建与等待、取消请求与清理完成等阶段。
- 用 Event / Action 交互流程展示职责分工，并说明一次事件处理不必对应一次模型调用。
- 展开权限申请、授予与检查，以及协调策略与执行机制的边界。
- 明确 Process-like 模型针对需要独立管理的运行实例，不要求每个函数或资源操作都成为 Process。

### 第四章：建立代码导向的大纲

按“现有框架 → 程序实现 → 注册发现 → 准入启动 → 组合执行 → LLM / Operator → 资源接入 → 当前范围”组织，列出代码依据、拟用片段与证据。当前仍是大纲，尚未展开完整正文；本次新增的权限委派案例已具备后续写入正文的实现基础。

## 2. 新增权限委派案例

实现：[delegation_demo.py](../semshell/examples/delegation_demo.py)。

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario delegation
```

完整路径：

1. Host 创建普通 UserShell Process，通过绑定的 ConsoleBridge 输入对话。
2. UserShell 创建空 Authority 的 llm1；llm1 调用脚本模型生成委派申请，并启动两个文本工具，分别统计词数与字符数。
3. llm1 演示直接读取受限资源、直接创建高权限子实例均被拒绝，再通过 IPC 向 UserShell 申请委派。
4. UserShell 检查请求来源、格式、请求 ID 与资源白名单，在自身已有权限范围内创建 llm2。
5. llm2 读取获批的项目报告，再演示访问另一资源被拒绝，调用脚本模型生成分析结果并退出。
6. UserShell 等待 llm2 后把结果发送给 llm1；llm1 校验回复来源、等待自己的工具子实例、汇总结果并退出。

```text
UserShell                         [项目报告读取权限]
├── llm1                          [空 Authority]
│   ├── 词数统计工具               [空 Authority]
│   └── 字符数统计工具             [空 Authority]
└── llm2                          [项目报告读取权限]
```

llm2 在任务协作上服务于 llm1，在运行时由 UserShell 拥有。llm1 的权限没有提升，也没有通过 Wait 等待自己的兄弟实例。UserShell 的批准仍需经过 Kernel 准入，不能制造自身不具备的权限。

本次未修改 Kernel、Action / Event ABI 或权限继承规则。新增程序通过现有接口接入；CLI 增加 `delegation` 场景，README 增加入口。

## 3. 证据与实现范围

成功运行的 CLI 输出已检查：

| 项目 | 结果 |
| --- | --- |
| 委派结果 | `completed` |
| 运行实例 | 5 个，拒绝的创建没有发布额外实例 |
| 资源拒绝 | 2 次：llm1 读取报告、llm2 访问其他资源 |
| 创建拒绝 | 1 次：llm1 试图创建更高权限子实例 |
| 实际 bridge 调用 | 报告资源 1 次，其他资源 0 次 |
| 模型调用 | llm1 2 次，llm2 1 次 |
| 并发证据 | 权限申请处理与 llm2 启动时，两个工具均已开始且尚未结束 |

实现范围：

- 使用 `ScriptedSemanticBackend` 和内存资源，无需 API Key、网络或外部文件访问。模型输出与越权探测步骤预先设定，用于验证协议和执行机制。
- 审批使用固定白名单及可配置的批准／拒绝选择，不是交互式人工审批界面。
- 并发通过 Host 注入的事件门控稳定复现，证明 asyncio 下的运行时段重叠，不作为 CPU 并行或性能测试。
- Kernel 审计与应用 trace 分别输出；前者证明准入和资源处理，后者记录应用流程。
- 示例每个 UserShell 处理一次对话。报告采集时 UserShell 仍为 `WAITING`，随后 Host 关闭 Kernel；它不代表已实现通用多轮对话前端。
- 本次测试未新增取消竞争、资源耗尽或服务故障场景的覆盖；相关 Kernel 行为仍由已有测试验证。

完整使用说明：[delegation-demo.md](../docs/delegation-demo.md)。

## 4. 验证结果

本次代码完成后已执行以下检查，全部通过。整理本记录时没有进一步修改运行代码。

| 检查 | 结果 |
| --- | --- |
| 完整 pytest 测试集 | 113 passed |
| Ruff | All checks passed |
| 严格 mypy，排除可选 OpenAI adapter | 43 个源文件通过 |
| delegation CLI | 成功完成，证据字段符合上表 |
| Git diff 空白检查 | 通过 |

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --exclude semshell/llm/openai.py --cache-dir .venv/.cache/mypy semshell
```

新增 [test_delegation_demo.py](../tests/test_delegation_demo.py) 共 6 个测试用例，覆盖成功委派及三条越权探测、拒绝申请、超出白名单、UserShell 权限不足、无关 IPC 发送者和 CLI 输出。现有 [guest ABI 架构检查](../tests/test_guest_abi_architecture.py) 同时纳入新示例文件。

## 5. 文件清单与后续工作

| 文件 | 修改内容 |
| --- | --- |
| `SemShell_zh.md` | 第二、三章重构，第四章大纲 |
| `semshell/examples/delegation_demo.py` | 新增对话、委派、并发与拒绝案例 |
| `semshell/cli/main.py` | 新增 demo 场景入口 |
| `tests/test_delegation_demo.py` | 新增行为与 CLI 验证 |
| `tests/test_guest_abi_architecture.py` | 扩展架构检查范围 |
| `docs/delegation-demo.md` | 场景、证据、拒绝分支和扩展说明 |
| `README.md` | 增加运行入口与说明链接 |
| `devdoc/change-log-2026-09-21.md` | 本次修改与验证记录 |

下一步优先将权限委派案例接入第四章正文：保留 Echo 作为最小程序示例，再用委派场景解释身份、授权与所有权。真实模型接入、人工审批前端和更多生命周期竞争场景留待明确需求后扩展，不列为本次已完成能力。
