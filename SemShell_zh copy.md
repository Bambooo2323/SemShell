
## 1.介绍


1.1 Current Loop-Agent Paradigm

P1 — 当前范式定义
介绍本文使用的描述性术语 Loop Agent：许多当前 Agent 系统可以抽象为“LLM + 外部维护的短期上下文 + 环境交互”的迭代结构。LLM 本身每次调用仍是离散推理，任务连续性主要依赖外部保存并重新提供的 context。

P2 — Context 的作用
Short-term Context / Working Memory 保存与下一轮推理相关的信息，例如用户输入、历史输出、工具结果、环境观测和 scratchpad。它不是环境真实状态本身，而是 LLM 可见状态的一个选择性投影。

Figure 1 — Loop-Agent Interaction Model
图中表达：

        Environment
      ↙             ↖
observation       action
    ↓               ↑
Short-term Context ↔ LLM
        iterative loop

图片索引：

![Figure 1. Loop-Agent Interaction Model](./figures/01-loop-agent.png)

P3 — Loop 的真正位置
强调 loop 的核心不是“LLM 与工具不断互调”，而是：

Context_t
   ↓ read
  LLM
   ↓ write/update
Context_{t+1}

也就是 LLM 与短期上下文之间持续发生的 read/write update。环境交互则通过 observation 和 action 接入这个内部循环。

1.2 Action and Memory Are Different Channels

P4 — Action 不等于 Memory 写入
LLM 生成的 action 可以直接作用于 Environment；是否同时将该 command 记录到 context，是独立的日志/记忆策略。

因此应区分：

Action channel
→ changes external state

Memory channel
→ changes future model-visible state

即使工程实现中通常会记录 tool call、command 和 result，这并不是逻辑上的硬性要求。

P5 — Observation 同样是选择性的
Environment 中发生的状态变化也不必全部进入 context。runtime 可以过滤、摘要、裁剪或只保留与后续推理有关的信息。因此：

context ≠ complete event log
context ≠ system state

它更接近短期工作记忆，或者形成当前后验判断所依赖的近期证据。

1.3 Why This Architecture Works

P6 — 这种结构为什么自然
Loop Agent 很轻量，因为它不要求 LLM 自己保持持久状态，也不要求工具理解 Agent。LLM 只需读取 context、输出 action；环境执行后返回 observation。

这一模式尤其适合 shell、API、browser、code execution 等离散交互环境。

P7 — 不把 loop 本身当作问题
明确说明本文并不认为 iterative loop 是架构缺陷。observe → infer → act → observe 本身是合理甚至不可避免的闭环决策结构。

问题将在下一节出现：随着 Agent 能力扩张，越来越多原本属于 execution runtime 的状态和职责开始被依附到这条 context loop 上。

1.4 Transition to the Architectural Problem

P8 — 从认知连续性扩展到执行连续性
最初 context 主要用于维持：

task history
recent observations
reasoning-relevant state

但复杂 Agent 系统逐渐还需要处理：

running tasks
tool lifecycle
subagents
permissions
cancellation
resource ownership
results

这里开始出现一个核心问题：

哪些状态真正属于 LLM 的短期认知上下文，哪些状态应该由独立的 execution runtime 管理？
## 2. From Decision Role to Runtime Role
2.1 Agent as a Decision / Coordination Role

P1 — 回归 Agent 的基础定义
将 Agent 重新放回 RL / control loop 的抽象中：Agent 根据 observation 形成 decision，并输出 action。这里的 Agent 是一个 decision / coordination role，而不是某个具体框架里的对象、类或模块集合。

核心关系：

Environment ── observation ──→ Agent
Environment ←──── action ───── Agent

P2 — LLM 只是 Agent 的一种实现机制
在 LLM Agent 中，决策机制由模型推理完成，但 Agent 并不等于 LLM 本体。LLM 需要依赖外部维护的短期上下文，才能在多轮交互中保持连续性。

2.2 The LLM Loop as the Decision Mechanism

P3 — Loop 的内部结构
LLM Agent 的核心 loop 可以表示为：

Short-term Context ↔ LLM

其中 context 是 LLM 唯一能够直接访问的动态短期记忆；模型参数则构成其长期、参数化记忆。

P4 — Context 的作用范围
Context 保存当前推理所需的信息，例如近期 observation、用户输入、模型先前输出以及必要的任务历史。它并不是完整系统状态，而是对外界状态的选择性、短期表示。

P5 — ReAct / loop 本身没有问题
这种 iterative context–LLM loop 是自然且有效的。observe → infer → act → observe 本身不是本文批评对象；相反，它是 LLM Agent 最基本、最合理的决策结构。

2.3 Everything Else Belongs to the Environment

P6 — Environment 的范围
从单个 Agent 的局部视角看，除 decision loop 以外的部分都属于 Environment，包括：

tools
shell
filesystem
network
users
databases
external storage
runtime
other agents / subagents

Agent 不需要知道这些机制内部如何实现。

P7 — Tool 只是 action–observation 的一种实现
Agent 只产生 action。Environment 接收 action、发生状态变化，并返回 observation。所谓 tool calling 只是这种交互的一种工程编码方式。

因此 Agent 层不需要区分 tool 到底是函数、RPC、shell command、容器还是其他程序。

P8 — Subagent 同样属于 Environment
对于当前 Agent，所谓 subagent 只是 Environment 中可能被某个 action 激活、随后产生 observation 的外部行为。它是否由另一个 LLM、线程、进程或远程服务实现，不属于 Agent 局部抽象的问题。

2.4 Role Expansion in Modern Agent Systems

P9 — 从决策 loop 到执行管理
随着 Agent 系统复杂化，原本只负责 decision 的 Agent 开始承担越来越多与执行相关的职责，例如：

task tracking
subtask scheduling
retry
permission handling
cancellation
lifecycle management
result aggregation

这些职责不再只是“如何决定下一步行动”，而开始涉及整个执行系统如何运行。

P10 — Operational state 渗入 context loop
为了维持这些职责，越来越多 execution state 被重新编码进 Agent 的短期 context 或绑定在 Agent loop 周围。

例如：

which task is running
which subtask has completed
what failed
what should be retried
what permissions remain

于是 context 不再仅仅承担认知连续性，也开始间接承担执行连续性。

2.5 The Architectural Question

P11 — 问题不是 Agent loop，而是角色膨胀
本文并不认为 Agent loop 应该被消除，也不认为现有架构“错误”。

真正的问题是：

Agent 是否应该同时承担 decision role 和 execution runtime role？

P12 — 引出后文
如果将 decision / coordination 与 execution management 分离，那么 Agent 可以继续保持简单的：

observation → decision → action

而 identity、lifecycle、authority、cancellation、execution state 等可以由独立 runtime 管理。

这一节只提出问题，不提前宣称 process-centric 模型“更正确”。后文再讨论一种更规则、更显式的 runtime abstraction 是否更适合承载这些职责。

## 3.Separating Decision from Execution 
3.1 Preserve the Agent as a Decision / Coordination Role

P1 — 保留 Agent 的核心职责
Agent 继续保持最基础的闭环角色：

observation → decision → action

其内部可以使用 ReAct、planner、graph、规则系统或其他 reasoning strategy。

P2 — 不改变 reasoning 范式
这一架构并不试图替代 ReAct，也不规定 LLM 应如何推理。需要被重新划分的是 execution management，而不是 decision logic。

3.2 Separate Cognitive State from Operational State

P3 — 区分两类状态
短期 context 继续承担 LLM 的认知状态，而运行时状态由独立 execution layer 保存。

Cognitive state
- observations
- task-relevant history
- reasoning context

Operational state
- running executions
- lifecycle
- permissions
- cancellation
- completion / results

P4 — Operational state 不应依赖 LLM 记忆维持
LLM 可以观察、推理和使用这些状态，但不应依赖 prompt/context 成为其唯一事实来源。

3.3 Introduce a Uniform Execution Substrate

P5 — 执行层需要统一的管理对象
不同软件执行单元内部行为可以完全不同，例如：

LLM-backed program
deterministic program
coordinator
shell
operator

但它们都可能需要相似的运行时语义：

identity
lifecycle
input / output
authority
cancellation
result

P6 — 统一管理不等于同质化
统一的是 execution semantics，而不是软件功能、智能程度或实现方式。

3.4 Event / Action as the Execution Boundary

P7 — 显式化 decision 与 runtime 的交界面
执行单元通过：

Event → decision logic → Action

与 runtime 交互。

Event 表示 runtime 提供的输入或状态变化，Action 表示程序希望外部系统执行的下一步操作。

P8 — Action 是通用执行请求，不只是 tool call
Action 可以进一步表示：

spawn
wait
send
invoke
cancel
exit
fail

因此 tool calling 只是更一般 action 模型的一种具体形式。

3.5 Runtime as Part of the Environment

P9 — Agent 的局部抽象不需要改变
从 Agent 视角看，runtime 本身仍属于 Environment。

Agent
  ↓ action
Environment / Runtime
  ↓ execution
External state
  ↑ observation
Agent

Agent 不需要知道 action 最终通过函数、进程、容器、RPC 或其他机制完成。

P10 — Runtime 负责机制，而不是决策
runtime 只负责：

admit
execute
track
authorize
cancel
report

它不决定“现在应该做什么”，因此不与 Agent 的 decision role 竞争。

3.6 Why Use a Process-like Runtime Model

P11 — Process 是一个自然候选抽象
传统系统中的 Process 已经提供了一套成熟的独立执行实体语言，包括 identity、lifecycle、权限边界和 completion。

这里借用的是这些结构性质，而不是复制 POSIX 或重新实现操作系统。

P12 — Process-centric 不是唯一答案
这一模型不宣称“更正确”或天然性能更好。

它的优势主要是：

regularity
explicit state
clear lifecycle
clear authority boundaries
structural legibility

即更规则、更显式、更容易解释。

3.7 Transition to SemShell

P13 — 提出具体实验问题
到这里自然引出：

如果将 LLM-backed software、普通程序、coordinator 和 operator 都放入同一个 process-like runtime，并让它们共享统一 execution semantics，会发生什么？

SemShell 在下一章作为这一问题的 executable reference design 出场。
















##
这样前三章的整体推进现在很清楚：

Chapter 1
Loop Agent 的基本结构

Chapter 2
Agent 从 decision role 向 runtime role 膨胀

Chapter 3
将 decision 与 execution 重新分离

Chapter 4
SemShell：一个 process-centric executable experiment

第三章的作用就是完成“问题 → 设计空间”的过渡，不需要在这一章证明 SemShell 本身。