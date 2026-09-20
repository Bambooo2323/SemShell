# SemShell TODO

本文档将 [`llm_cli_os_design_draft.md`](./llm_cli_os_design_draft.md) 转换为可执行的实现路线。
本仓库的最终目标是完成技术架构证明和可复现演示，不是构建完整 OS、生产 runtime
或通用 Agent 框架。需要验证的命题是：

1. LLM-backed program、Tool、Coordinator、Memory 和普通程序在 Kernel 中都是平等的 Process。
2. HumanShell、RuleShell 和 LLMShell 可以通过同一套结构化接口操作 Kernel。
3. Process 的创建、等待、取消、退出和 authority 变化都具有显式、可检查、可测试的结构。

## 0. 第一版边界

### 必须实现

- 单 Python 进程、`asyncio` 驱动的 Kernel。
- `ProcessImage -> ProcessSpec -> Process` 的创建模型。
- PID、PPID、Process Table 和确定性的生命周期状态机。
- 结构化 Action、Event、Message 和 ProcessResult。
- capability-based image discovery。
- 动态 register / unregister image。
- Principal、Authority 和子进程 authority 削减。
- spawn、send、receive、wait、cancel、exit、reap、inspect。
- HumanShell、RuleShell、LLMShell 使用相同的 Kernel 接口。
- 一个用 HumanShell、RuleShell 和 fake LLMShell 展示同一进程树的最小示例。

### 明确不做

- CPU 抢占式调度、虚拟内存、真实文件系统或网络栈。
- 多机或多 worker 调度。
- crash 后的持久化恢复。
- exactly-once 消息或分布式事务。
- 通用 Prompt、RAG、Workflow 或 Multi-Agent 框架。
- 为 benchmark 进行性能优化。
- Kernel 内置 ReAct、Planner、Tool、Agent、LLM 等语义角色。

## 1. 在编码前闭合核心语义

- [x] 编写 `docs/semantics.md`，定义 ProcessImage、ProcessSpec、Process、Principal、Authority、Capability、Action、Event 和 Message。
- [x] 决定 PID 的范围和生命周期：Kernel 内单调整数；重启后不保证延续。
- [x] 定义完整状态机及合法迁移，至少包括：
  - `CREATED -> READY -> RUNNING`
  - `RUNNING -> READY | WAITING | EXITED | FAILED`
  - `READY | RUNNING | WAITING -> CANCELLING -> CANCELLED`
  - terminal state `-> REAPED`
- [x] 明确一次 process activation 的规则：每次只处理一个 Event，并且必须返回一个 Action 或 Action batch。
- [x] 明确 `Continue`、`Yield` 和 `Wait` 的区别，禁止以“READY 但没有可处理 Event”的方式隐式继续。
- [x] 将 ownership edge 与 wait edge 分开定义：PPID 表示生命周期所有权，wait set 表示同步依赖。
- [x] 定义 attached、detached 两种最小子进程所有权模式。
- [x] 定义 `wait_all`、`wait_any` 和空 wait set 的行为。
- [x] 定义 cancel 与 exit 同时发生时的唯一终态和迟到事件处理规则。
- [x] 定义消息投递基线：第一版仅保证 Kernel 存活期间的 in-memory、at-most-once delivery。
- [x] 定义 ProcessResult 的结构化错误字段，避免只保存异常字符串。

完成条件：仅阅读 `docs/semantics.md` 就能实现一个兼容 Kernel；所有合法和非法状态迁移均可列成测试表。

## 2. 建立包骨架和公共类型

- [x] Create the `semshell/` Python package with default offline requirements;
  keep provider dependencies in explicitly named optional requirement files.
- [x] Support Python 3.11+ and validate with pytest, Ruff, and strict mypy commands.
- [x] 建立以下初始模块：

```text
semshell/
├── kernel/
│   ├── actions.py
│   ├── events.py
│   ├── process.py
│   ├── kernel.py
│   └── errors.py
├── software/
│   ├── image.py
│   ├── catalog.py
│   └── program.py
├── security/
│   ├── principal.py
│   ├── authority.py
│   └── policy.py
├── shells/
│   ├── human.py
│   ├── rule.py
│   └── llm.py
├── cli/
│   └── main.py
└── examples/
```

- [x] 所有 Kernel 核心类型使用明确的 dataclass / enum / protocol，并保持与模型 SDK 无关。
- [x] Keep the initial Kernel types model-agnostic without imposing an import blacklist.

Completion criteria: public types are importable from the repository, an empty Kernel can start and stop, and tests plus static checks pass inside `.venv`.

## 3. Implement the minimal Process Kernel

- [x] Implement the Process Table and monotonic PID allocation.
- [x] Instantiate ProcessImage factories from ProcessSpec requests.
- [x] Implement `spawn()`, including attached parent ownership.
- [x] Process one event at a time without re-entering the same process.
- [x] Implement a single authoritative mailbox and passive-process wake-up.
- [x] Implement structured Actions:
  - `Send`
  - `Spawn`
  - `Wait`
  - `Yield`
  - `Exit`
  - `Fail`
- [x] Implement structured system Events:
  - `Started`
  - `MessageReceived`
  - `ChildrenCompleted`
  - `Spawned`
  - `OperationCompleted`
  - `OperationRejected`
- [x] Implement `wait(pid)` with an external timeout that does not cancel the process.
- [x] Implement immutable snapshots through `inspect(pid)`, `list_processes()`, and `tree(pid)`.
- [x] Explicitly `reap()` completed processes without reusing their PIDs.
- [x] Prevent terminal processes from being scheduled or receiving ordinary messages.
- [x] Keep each IPC message in one authoritative mailbox location.

Completion criteria: deterministic programs can perform multi-level spawn, send, wait, and exit flows without an LLM dependency.

## 3.1 Add a model API boundary

- [x] Define provider-neutral `LLMRequest`, `LLMResponse`, `TokenUsage`, and `LLMBackend` types.
- [x] Add an async OpenAI Responses API backend outside the Kernel.
- [x] Support injected clients so tests require neither an API key nor network access.
- [x] Normalize `output_text`, response identity, status, and token usage.

## 4. 显式取消和生命周期所有权

- [x] 实现 `cancel(pid, mode=...)`，第一版支持：
  - `self`：仅取消目标；
  - `tree`：取消目标及 attached descendants。
- [x] 增加 `CANCELLING` 状态，避免把请求取消与完成清理混为一体。
- [x] 为 Program 提供有截止时间的 stop/cancel hook。
- [x] 定义并测试父进程先退出、子进程先退出和同时退出的行为。
- [x] detached child 不随 parent tree cancellation 传播。
- [x] 父进程等待的子进程被取消时，必须收到结构化 ChildResult。
- [x] `wait_any` 唤醒一次后清除对应 wait edge，但不隐式取消其他子进程。
- [x] 如需 first-winner 行为，由 user-space Coordinator 显式发起其余分支的 cancel。
- [x] 忽略或审计取消后的迟到普通消息，不重新激活 terminal process。

完成条件：任意进程树在任何 activation 点被取消后都能在限定时间内进入稳定终态，且没有悬挂 waiter 或后台 task。

## 4.1 Freeze a transport-neutral control protocol

Detailed plan: [`libfuse_inspired_design_plan.md`](./libfuse_inspired_design_plan.md).

- [x] Define session-local request IDs, session identity, immutable caller context, and request handles.
- [x] Define Kernel-owned operation payloads and a single external reply envelope; exclude operations that require a Process caller PID.
- [x] Guarantee exactly one terminal reply per admitted request.
- [x] Distinguish request interruption, client disconnect, and explicit process cancellation at the protocol state layer.
- [x] Ensure an interrupted `wait` never cancels its target and an interrupted admitted `spawn` never rolls back implicitly.
- [x] Bind every session to a Principal and maximum delegated Authority.
- [x] Specify bounded in-flight requests, session close, late completion, and audit behavior.
- [x] Keep transport errors and Linux `errno` outside Kernel error types.

Completion criteria: the protocol can be implemented by CLI, JSON Lines, an in-memory test adapter, or a future FUSE adapter without changing Process semantics.

## 5. Capability Catalog 和动态软件管理

- [x] 定义 `ProcessImage` 元数据：image ID、version、factory、provided/required capabilities、schema、trust metadata。
- [x] 定义 `CapabilitySpec`：名称、描述、输入输出 schema、副作用、预估成本和所需 authority。
- [x] 支持同一 capability 的多个 provider。
- [x] 定义确定性的 resolve policy；第一版默认拒绝含糊解析，调用方可指定 provider。
- [x] 实现运行时 register、unregister、list 和 resolve。
- [x] 禁止卸载仍有 Process 使用的 image，或明确采用引用计数/延迟卸载。
- [x] image upgrade 注册为新版本，不原地改变已运行 Process 的代码定义。
- [x] 将 install/download/compile 保留为未来 user-space package manager 行为，Kernel 只暴露 load/register 接口。

完成条件：Kernel 启动后可以增加和移除软件定义；新 spawn 使用新版本，已运行 Process 不受影响。

## 6. Principal、Authority 和 Spawn Policy

- [x] 实现稳定 Principal ID，例如 `human:alice`、`service:ci`、`system`。
- [x] Authority 使用结构化 capability + scope 表示，不使用自由文本权限判断。
- [x] 实现 authority subset/intersection 操作。
- [x] ProcessSpec 中的 `requested_authority` 明确为 request。
- [x] spawn 时计算：

```text
effective authority =
    image declaration
    ∩ parent authority
    ∩ system policy
    ∩ approved escalation
```

- [x] 普通 child 默认只能继承或削减 parent authority。
- [x] 将 authority escalation 表达为显式 pending request/event，不在 `spawn()` 内隐藏交互式审批。
- [x] 区分 image execute ACL 与 process effective authority。
- [x] 所有 authority 决策产生可审计事件，记录 requester、requested、granted/denied 和 policy reason。
- [x] 用表驱动测试覆盖无权限、部分授权、削减、拒绝和审批后授权。

完成条件：任何 Process 都无法通过自行构造 ProcessSpec 获得父进程没有的 authority；每次授权结果可解释。

## 7. Minimal Operator proof

- [x] Remove the incomplete generic external-input path; define only a console binding to an admitted HumanShell Process.
- [x] Keep ControlGateway as a Host administration and test boundary, not a normal Operator path.
- [x] Define one shared Operator task envelope and use the existing Process Event/Action ABI.
- [x] Implement HumanShell, RuleShell, and LLMShell as ordinary ProcessPrograms.
- [x] Define a model-neutral `SemanticBackend` protocol and an offline scripted implementation.
- [x] Allow Operators to discover factory-free Catalog metadata through a shared Process Action/Event pair.
- [x] Ensure every Operator can only submit ordinary Process Actions; no Shell may call Kernel or Host tools directly.
- [x] Add one shared contract suite for all three Operator implementations.

Completion criterion: one task can be driven by HumanShell, RuleShell, and fake LLMShell without a role-specific Kernel branch.

## 8. Minimal guest software

- [x] Implement one deterministic `echo`-like worker ProcessImage.
- [x] Implement one coordinator ProcessImage using explicit spawn, wait, and aggregate Actions.
- [x] Register both through the Catalog without adding software-specific Kernel code.

Completion criterion: removing either software package requires no Kernel change, and adding it requires only image registration.

## 9. Architecture demonstration

- [x] Add `semshell demo --operator human|rule|llm` as the only required CLI workflow.
- [x] Run the same deterministic fan-out/fan-in task for all three Operators.
- [x] Print the final Process tree, terminal values, and relevant authority decisions.
- [x] Use the scripted backend by default; the demonstration must require no network or API key.
- [x] Keep the Host CLI as a bootstrap/console adapter; semantic work begins in the Operator Process.

Completion criterion: a new reader can compare three short runs and observe that only the Operator implementation changes.

## 10. Remaining 0.1 tests

- [x] Add HumanShell, RuleShell, and LLMShell shared contract tests.
- [x] Add a Kernel role-neutrality architecture test.
- [x] Add a parameterized end-to-end demonstration test for all three Operators.
- [x] Assert equivalent Process topology and results where task semantics require equivalence.
- [x] Run the full offline suite repeatedly without leaked asyncio tasks.

Completion criterion: no test calls a real model or external service, and the architecture proof is deterministic.

## 11. Documentation and first release

- [x] Distill the design draft into a short `docs/design.md` centered on the three architecture claims.
- [x] Make `docs/semantics.md` the authoritative behavioral specification.
- [x] Add a concise security model describing the semantic VM, Host bridges, lack of code containment, and non-goals.
- [x] Add a 60-second README path for the three Operator demonstrations.
- [x] Perform a context-free reader test against the architecture claims.

Completion criterion: release `0.1.0` only when code and documentation make the three claims observable without a large feature tour.

## 12. 0.1.0 之后

以下内容仅在第一版语义和演示稳定后进入规划：

### Recommended next proof: generic Host resource bridge

- [x] Close startup-fixed ResourceBinding identity and Kernel-lifetime ownership semantics.
- [x] Define InvokeResource and ResourceCompleted/ResourceRejected with Kernel-allocated invocation IDs.
- [x] Define Kernel-authenticated ResourceInvocation context with no caller-supplied PID, Principal, or Authority.
- [x] Define an immutable binding-ID Authority scope and trusted operation-to-Permission mapping.
- [x] Define one outstanding invocation per Process and completion/cancellation linearization.
- [x] Define bounded input/result behavior and metadata-only audit records.
- [x] Implement Host-only descriptors, a startup registry, and a passive HostResourceBridge protocol.
- [x] Implement an in-memory `read_text` bridge and shared conformance tests.
- [x] Integrate generic resource Actions/Events without filesystem-specific Kernel branches.
- [x] Implement a matching local `read_text` bridge over trusted temporary roots only.
- [x] Add one workspace-reader ProcessImage and allowed/denied/lexical-escape proof.
- [x] Update public semantics and security documentation without claiming code containment.

Completion criterion: one unchanged guest ProcessImage works against fake and
local bridges, missing Authority prevents Host invocation, lexical escape is
rejected in a trusted temporary tree, and cancellation cannot reactivate the caller.

### Version 0.3: persistent local Control CLI

- [x] Define the 0.3 boundary: a persistent local administration REPL, not an Operator Process or remote transport.
- [x] Keep external `send` unavailable; Process IPC requires a running source Process and Human input requires a bound ConsoleBridge.
- [x] Freeze sequential request handling, RequestId allocation, strict rendering, and orderly shutdown semantics.
- [x] Add the observational `ListProcesses` operation to the transport-neutral Control protocol.
- [x] Add strict parsing for `images`, `ps`, `tree`, `spawn`, `wait`, `cancel`, `inspect`, and `reap`.
- [x] Add deterministic JSON-compatible encoding for public Control reply values.
- [x] Implement `semshell control` as one persistent Kernel/Gateway/Session lifecycle.
- [x] Prove `spawn -> ps/inspect -> wait -> reap`, rejection recovery, interruption, shutdown, routing, and Control audit correlation with scripted input.
- [x] Update public documentation while preserving the Control/Console/Operator distinction.

Completion criterion: one local CLI session operates one live runtime entirely
through ControlGateway after bootstrap, every admitted command has one terminal
reply and audit record, and the CLI cannot forge Process IPC provenance.

## 13. Design edition scope decision

This repository is now an executable reference design rather than the
production runtime implementation.

- [x] Distinguish the Python reference state machine from a Linux/OCI runtime.
- [x] Document which semantics stay owned by SemShell and which mechanisms are
  delegated to Linux and a container runtime.
- [x] Remove production runtime features from this repository's implementation
  roadmap.
- [x] Adopt a focused design edition after preserving the complete reference.
- [x] Define the file-level reduction, API migration, validation, and rollback
  rules in [`design_edition_simplification_plan.md`](design_edition_simplification_plan.md)
  and [`design_edition_migration_stages.md`](design_edition_migration_stages.md).
- [x] Preserve the reviewed Stage 3 tree at branch `complete-reference` and tag
  `complete-reference-20260915` before physical removal.

Until a migration stage changes behavior, current code and `docs/semantics.md`
remain authoritative. Do not add production transports, persistence, executors,
streams, supervisors, or deployment systems here.

## 14. Design edition staged migration

生命周期重构第一、第二阶段的正确性修复已经完成并保留。原第三阶段中的 pause/resume
和扩展 Control interrupt 不再属于本仓库完成条件。当前公开行为保持有效，直到下面对应
阶段同时迁移规范、实现、消费者和测试：

- [x] Stage 0 — preserve the complete baseline and adopt the scope decision.
- [x] Stage 1 — add HostAdmin, explicit report projection, and the extended
  offline demonstration.
- [x] Stage 2 — decouple guest Actions from Control operation types.
- [x] Stage 3 — reduce ownership, cancellation, Wait, Message, ProcessSpec,
  Catalog, and Policy semantics.
  - [x] 3A — attached-only ownership and cascading cancellation.
  - [x] 3B — explicit Wait ALL and simplified messaging.
  - [x] 3C — reduced ProcessSpec, Catalog, and Policy.
- [x] Stage 4 — remove the active Control REPL/package and local filesystem proof.
  - [x] Preserve the complete-reference branch and tag.
  - [x] Remove active Control, Control-only operations, CLI, and tests.
  - [x] Remove LocalWorkspaceBridge and retain portable in-memory validation.
  - [x] Migrate current documentation and mark removed designs historical.
  - [x] Run pytest, Ruff, mypy, and all four demos in a Python environment.
- [x] Stage 5 — isolate the optional OpenAI adapter and default dependency path.
  - [x] Remove the eager package export and move OpenAI to
    `requirements-openai.txt`.
  - [x] Validate the default environment without the OpenAI SDK: 106 passed,
    1 optional test skipped, four demos passed, Ruff passed, strict mypy passed
    for 42 source files.
  - [x] Validate the optional environment: adapter fake-client test passed,
    complete suite 107 passed, strict mypy passed for 43 source files.
- [ ] Stage 6 — publish current documentation, validate, reader-test, and freeze.
  - [x] Reconcile current documentation, historical banners, and article evidence.
  - [x] Validate both dependency paths, four demos, Ruff, and strict mypy.
  - [x] Record source size, direct dependencies, tests, and removed capabilities.
  - [ ] Record independent reader review and final sign-off.
  - Evidence: [design-edition validation](../docs/design-edition-validation.md).

Each stage uses the gates and rollback points in
[`design_edition_migration_stages.md`](design_edition_migration_stages.md). A
stage is not complete merely because obsolete tests or files were removed.

## 15. Final Agent architecture demonstration

Stage 6 review note (2026-09-15): primary and extended demonstrations pass.
The checklist below includes broader article/demo goals, so earlier unchecked
items are not blanket claims that the implementations are absent. Current
evidence and remaining gaps (independent reader review and a separate newly
registered fourth Operator scenario) are tracked in
[the validation record](../docs/design-edition-validation.md).

第 9 节已经完成最小 Operator 等价性证明；本节将其整理成最终对外演示。目标是让读者
直接看到 Process-centric Agent 结构的优势，而不是展示一个功能繁多
的 CLI 或操作系统。这里的“优势”必须由仓库代码、运行输出和测试支持，不使用无法验证的
性能、智能水平或生产可靠性主张。

### 15.1 要证明的架构性质

- [ ] 同一个任务由 HumanShell、RuleShell 和 fake LLMShell 执行时，Kernel、Action/Event
  ABI、普通软件和资源边界保持不变，只替换 Operator ProcessImage。
- [ ] LLM、工具型程序、Coordinator 和普通程序在 Kernel 中都是 Process；Kernel 不导入、
  识别或分支处理 Agent、Tool、Planner、Memory、Human 或 LLM 角色。
- [ ] Agent 的拆分、组合和替换通过 ProcessImage、Capability、Spawn、Wait 和 Message
  表达；增加一个同契约 Operator 不修改 Kernel。
- [ ] authority、ownership、等待关系、取消和失败结果都能从结构化快照及审计中
  观察，而不是藏在 Prompt 或框架内部状态中。
- [ ] HostAdmin、Console 输入、Resource bridge 和 Process IPC 的身份边界清晰，Host
  facade 不能伪造 Process 来源。

### 15.2 演示场景

- [ ] 保留现有 `demo --operator human|rule|llm` 作为 60 秒主路径，并确保三种 Operator
  对同一确定性 fan-out/fan-in 任务产生等价拓扑和结果。
- [ ] 输出紧凑的结构化证据：Operator image、Process tree、每个节点的角色无关状态、
  最终结果、关键 authority decision 和 Resource audit；避免输出内部 PCB 或 Python 对象。
- [ ] 增加一个替换性场景：注册新的同契约 Operator image，只改 bootstrap/catalog 组装，
  不改 Kernel 和 worker/coordinator。
- [ ] 增加一个受控生命周期场景：展示 attached 后代级联取消、资源取消和迟到结果抑制。
- [ ] 增加一个边界拒绝场景：缺少 Authority 时 Resource 在 Host 调用前被拒绝，并证明
  HostAdmin 无法伪造 Process IPC source PID。
- [ ] 每个场景提供固定输入、预期关键输出和对应测试；默认使用 scripted backend，
  不需要网络、API key、Docker 或人工时序操作。

### 15.3 演示交付物

- [ ] 在 README 提供一条 60 秒主命令和一条 5 分钟扩展演示路径。
- [ ] 提供一份面向架构读者的说明，按“输入 → Operator 决策 → 普通 Process 协作 →
  Kernel 可观察证据”解释完整流程。
- [ ] 给出简短对照表，说明传统按 Agent/Tool 写 Kernel 分支的耦合点，以及本实现由哪些
  可执行证据证明角色中立；只比较结构，不宣称未经测量的性能收益。
- [ ] 保留机器可读输出，确保演示可由测试复现；可视化只作为同一结果的展示层。
- [ ] 完成一次无上下文读者检查：读者应能从文档和输出回答“谁做了决策、Kernel 是否
  识别 Agent、权限在哪里执行、替换 Operator 需要修改什么”。

完成条件：新读者在不阅读 Kernel 实现的情况下，可以通过命令、输出和短文档验证上述
架构性质；演示没有引入生产 transport、持久化、容器执行器或新的角色专用 Kernel 分支。

## 16. Separate production-runtime boundary

The following are intentionally not TODO items for this repository:

- production JSON Lines, socket, HTTP, or frontend transports;
- persistent journal, replay, checkpoint, and resume;
- subprocess/container executors and Linux signal/cgroup integration;
- production workspace, network, secret, model, and device injection;
- streaming stdout/stderr, subscriptions, and backpressure;
- supervisors, restart policy, resource accounting, and multi-worker leases;
- durable state, authentication, audit storage, and telemetry;
- remote Catalog/package management and deployment orchestration;
- optional FUSE views or other operating-system adapters.

这些能力若需要落地，应进入独立的 Linux／OCI application repository。wire schema、
container identity、crash recovery ordering、runtime exit precedence、execution-profile
compiler 和生产资源注入规范也由该仓库按实际实现需求推进，不再作为本仓库完成条件。

## 17. Article and documentation handoff

The writing brief is maintained in
[`article_writing_plan.md`](article_writing_plan.md).

- [x] Freeze the executable reference scope and its non-claims.
- [x] Select the article thesis, audience, outline, terminology, and evidence
  map.
- [x] Separate repository-backed claims from comparisons requiring external
  primary sources.
- [ ] 在架构演示冻结后更新文章 evidence map，引用最终命令、输出和测试。
- [ ] Collect primary sources for ecosystem, Codex, OCI, and adjacent-runtime comparisons.
- [ ] Draft the English article section by section, centered on the verified
  Agent architecture rather than an operating-system feature inventory.
- [ ] Run context-free reader tests against the complete article.
- [ ] Prepare the separate publication repository and copy only intentional
  release artifacts.

文章资料整理可以并行开始；最终实现证据以设计版 Stage 6 和第 15 节演示冻结后的结果为准。
