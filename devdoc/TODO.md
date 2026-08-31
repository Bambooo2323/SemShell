# SemShell TODO

本文档将 [`llm_cli_os_design_draft.md`](./llm_cli_os_design_draft.md) 转换为可执行的实现路线。
第一阶段的目标不是构建完整 OS 或通用 Agent 框架，而是验证以下命题：

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

- [x] Create the `semshell/` Python package and a single `requirements.txt` for the repository prototype.
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

- [ ] Complete interactive CLI commands: `images`, `ps`, `tree`, `spawn`, `send`, `wait`, `cancel`, `inspect`, and `reap`.
- [ ] JSON Lines, socket, and other remote adapters with request correlation and backpressure.
- [ ] Approval, memory, Python runner, test runner, file editor, network, and LLM worker guest software.
- [ ] A richer repair-project demonstration with allow, deny, and cancellation paths.
- [ ] append-only event journal 和 replay。
- [ ] Process checkpoint / resume。
- [ ] subprocess/container executor。
- [ ] Add a locked-down single-container runtime profile for coarse Host containment.
- [ ] Define explicit workspace and network bridge configuration for container runs.
- [ ] Add isolated Process execution profiles only after the shared executor contract is stable.
- [ ] signal、streaming stdout/stderr 和 backpressure。
- [ ] resource budget 与 accounting。
- [ ] supervisor software 和 restart policy。
- [ ] remote catalog / package manager。
- [ ] multi-worker transport 和 lease-based process ownership。
- [ ] OpenTelemetry adapter 和可视化 inspector。
- [ ] 兼容 MCP、OpenAI Responses 或其他 Agent SDK 的 user-space adapter。
- [ ] Add a transport-neutral, read-only virtual namespace over images, capabilities, processes, and sessions.
- [ ] Prototype an optional Linux/libfuse3 adapter after the in-memory namespace contract is stable.
- [ ] Consider writable request transaction nodes only after CLI/JSON semantics prove their behavior.

### Long-lived streams and frontend subscriptions

Implement this only after the 0.1 Process, Control, cancellation, authority, and
end-to-end operator contracts are stable.

- [ ] Define a provider-neutral stream protocol with `StreamId`, open, chunk, close, failure, and cancellation events.
- [ ] Define producer ownership and the relationship between Process termination and stream termination.
- [ ] Add bounded buffering, backpressure, chunk ordering, and slow-consumer policy.
- [ ] Distinguish a stream's zero-or-more events from the exactly-one terminal `ControlReply` of its subscription request.
- [ ] Define subscribe, unsubscribe, disconnect, reconnect cursor, and late-subscriber behavior.
- [ ] Add an output journal only if replay or reconnect requires it; do not make durability implicit.
- [ ] Implement transport-neutral fake stream tests before selecting a frontend transport.
- [ ] Add optional SSE and/or WebSocket Control adapters for frontend consumers.
- [ ] Bridge OpenAI Responses streaming events into the provider-neutral stream protocol without exposing OpenAI SDK types to the Kernel.
- [ ] Reuse the same stream contract for LLM output, subprocess stdout/stderr, logs, file reads, and other incremental producers.

Completion criteria: a slow or disconnected frontend cannot cause unbounded
mailbox/task growth, each stream reaches one stable terminal state, and enabling
OpenAI streaming requires no model-specific branch in the Kernel.

## 推荐实施顺序

严格按以下关键路径推进：

```text
Semantics
  -> Public Types
  -> Deterministic Kernel
  -> Cancellation
  -> Catalog
  -> Authority
  -> Operators
  -> User-space Programs
  -> End-to-end Demo
  -> Documentation / 0.1.0
```

不要先实现真实 LLM 接口。fake LLMShell 足以验证 Kernel contract；真实模型接入只有在 HumanShell 和 RuleShell 已证明同一接口可替换后才有意义。
