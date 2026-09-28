# SemShell：从 Agent 的决策边界到统一执行模型

## 1. LLM Agent 的最小模型

### 1.1 Agent 作为决策与协调角色

本文从强化学习与控制系统中的观测—行动关系出发，将 **Agent 定义为根据可见信息作出决策、选择行动或协调工作的角色**。其基本关系是：

```text
observation → Agent → action
```

这一角色不限定实现方式：它可以由 LLM 参与实现，也可以采用其他决策机制；工具、记忆服务、显式循环、独立进程和特定框架都不是定义的前提。本文关注 LLM Agent，但始终区分角色与工程对象。框架中的 `Agent` class 是实现这一角色的一种容器，具体封装哪些组件取决于软件设计，不能直接将它与 Agent 角色、LLM 或 Runtime 等同。

### 1.2 LLM 作为可分离的推理组件

LLM 是实现 Agent 决策功能的一种计算组件，其接口可以抽象为：

```text
Context → LLM Inference → Output
```

模型根据当前上下文生成回答、判断、计划或行动请求。推理具有明确的输入与输出边界，因此可以在逻辑上与上下文管理、环境交互和执行管理分离。它既可以通过远程 API 或本地推理服务提供，也可以嵌入应用或由分布式设施承载；逻辑上的可分离性不要求物理隔离。

单次推理不以模型知道“自己属于一个 Agent”为前提。上下文可以说明它正在承担的角色，但不会因此赋予模型 Agent 的生命周期。本文将一次模型调用视为离散的推理过程，其中可以生成多步计划；任务如何跨调用延续、何时再次调用模型，以及已提交的行动如何继续执行，都由模型之外的机制维护。

### 1.3 短期上下文作为工作记忆

**Short-term Context 是当前推理中模型能够直接使用的动态信息集合**，包括环境观测、近期历史、先前模型输出、指令、工作记录、工具描述和检索材料，也可以包含图像等多模态信息。本文将其称为短期记忆或工作记忆。“短期”指信息参与本次推理的方式，与原始材料在外部保存了多久无关。

跨调用的认知连续性依赖相关信息被再次提供。出现在前一次调用中的内容，不保证后一次调用仍然可见。上下文管理通过保留原文、提取片段或生成摘要，使后续推理能够接续目标、证据与未完成事项；不同组织方式也会保留不同程度的细节。

上下文包含对环境观测的选择性表示，以及指令、历史输出等推理材料，**不等于完整环境状态、完整事件日志或运行事实本身**。例如，测试已经结束，而完成通知尚未进入上下文时，“测试运行中”只是较早的观测。任务是否仍在运行，需要依据执行系统的状态与记录确认。

### 1.4 参数记忆与外部存储

本文用**参数化长期记忆**指模型参数中编码的知识与能力，例如语言模式、领域知识和代码生成能力。这个术语用于区分模型通过训练形成的能力与工程系统保存的记录，并不保证其中的知识正确或能被精确回忆。在参数固定的推理过程中，加入新上下文不会直接更新模型参数；训练和微调属于另一条更新路径。

数据库、向量存储、文件、对话归档和用户资料，统一视为外部状态或外部存储。工程系统可以把用于跨会话复用的记录称为“长期记忆”，但它们仍不是 LLM 的参数记忆。相关内容只有被读取并提供给模型后，才成为当前推理可直接使用的信息。

| 信息形态 | 信息载体 | 参与本次推理的方式 |
| --- | --- | --- |
| 短期上下文／工作记忆 | 本次调用提供给模型的输入 | 作为当前可见的信息参与推理 |
| 参数化长期记忆 | 模型参数 | 通过已训练的参数参与输入处理与输出生成 |
| 外部存储 | 文件、数据库、向量存储等 | 相关内容经读取与组织后进入上下文 |

同一份内容可以同时存在于外部存储和当前上下文中。例如，一条几个月前保存的项目约定，在磁盘上是持久记录，被提供给模型后又成为当前上下文。裁剪上下文不会因此删除外部记录，保存完整日志也不意味着模型已经看过全部内容。

### 1.5 Agent Host：角色的工程实现

本文将**实现 Agent 角色的宿主程序称为 Agent Host**。对于 LLM Agent，它负责上下文管理、LLM 调用、输出解释与环境交互：接收信息、组织输入、决定何时调用模型，再将输出保留为后续推理材料或交给环境处理。Agent 表达决策与协调角色，Agent Host 则将这一角色落实为软件行为。

Agent Host 可以是一个进程、服务、框架对象或事件处理器，也可以由分布式组件共同实现。这里的 Host 表示角色的宿主实现，不意味着它拥有运行时管理权限，也不等同于 SemShell 的 Host 管理侧。

在记录能够完整放入模型输入的最简实现中，上下文管理只需维护一份追加日志。用户输入和环境反馈写入日志后，管理器按模型输入格式组织这些记录并调用 LLM；模型输出的指令、显式分析或工作记录等内容，以副本形式保留到日志中，工具调用请求则交给 Environment。此时，当前日志就构成工作上下文，无须额外的检索、摘要或复杂调度。

复杂一些的实现可以加入调用条件：信息到达后先被保存，条件满足时才调用 LLM。例如，模型可以提前提出“等待两项测试都完成后再分析”，由 Host 转换为可检查的规则；条件也可以由 Environment 提供或检查，并在满足时通知 Host。已明确的条件可以由普通程序检查，无须为每条反馈重新进行模型推理。

这里的上下文管理器因此兼有信息管理与调用控制两类职责，属于 Agent Host 的一部分。它决定模型何时获得哪些信息；环境中的执行组件则负责请求如何被接受、运行和结束。即使这些职责由同一段程序实现，也需要明确各自维护的状态。

### 1.6 Environment：相对当前 Agent 的外部状态与机制

从当前 Agent 的局部视角看，**Environment 是决策角色之外、它能够观察或作用的外部状态与机制**。工具、shell、文件系统、网络、用户、服务、runtime、其他 Agent 和外部存储，都可以属于 Environment。这个边界按交互与职责划分，同一个应用可以同时实现 Agent Host 和部分环境能力。

工具和 Subagent 在本章中被视为环境中的不同软件角色：工具处理操作，Subagent 实现另一个决策角色。它们与远程服务、用户一样，都可以通过 action 与 observation 和当前 Agent 交互；共同的交互关系不意味着相同的权限、能力或生命周期。

Environment 内部仍可分为多个组件与管理层次。例如，外部存储保存记录，runtime 维护任务与资源，另一个 Agent 处理特定问题。它们在当前 Agent 的交互视角下同属环境，各自仍可独立实现。

### 1.7 Action 与 Observation

**Action 是 Agent 面向 Environment 发出的行为请求**，包括回复用户、读取文件、运行程序或委派任务等。Agent Host 解释模型输出并交付请求，环境组件再决定是否接受以及如何处理。请求可以引起环境状态变化，但提出请求不等于执行成功。

行动交付与上下文更新是两条逻辑通道：

```text
行动通道：模型输出 → Host 解释与交付 → Environment 处理
记忆通道：输入、输出与观测 → 保存／选择／组织 → 后续 Context
```

同一份输出可以进入两条通道，但行动并不以写入上下文为生效条件。将“准备运行测试”写进日志，不代表测试已经启动；请求提出、执行启动和测试完成，是三个不同的事实。反过来，请求已经执行而结果交付中断时，缺少返回内容也不能证明行动没有发生。

**Observation 是 Environment 向当前 Agent 提供的可见反馈**，例如用户的新要求、工具结果或任务状态变化。它只揭示环境的一部分，Agent Host 还可以进一步选择、过滤或加工，再将其用于后续上下文。例如，完整测试日志保存在环境中，模型只收到失败用例与关键报错。摘要应保留当前判断需要的请求归属、执行状态和待确认事项，不能把“已提交”压缩成“已完成”。

两条通道可以共用数据与设施。写入任务笔记在执行层是文件写入行动，在后续使用中又参与记忆管理；写入是否成功、内容是否进入后续上下文，仍需分别判断。

### 1.8 最小交互模型

将上述关系合在一起，可以得到最小 LLM Agent 交互模型：

**Figure 1 — Minimal LLM-Agent Interaction Model**

```mermaid
flowchart TB
    E["Environment<br/>外部状态与机制"]
    C["Short-term Context<br/>当前模型可见的工作记忆"]
    M["LLM<br/>可分离的推理组件"]

    E -->|"observation · Host 选择与组织"| C
    C -->|"context · Host 按需调用"| M
    M -.->|"output · Host 保留到后续上下文"| C
    M -->|"action · Host 解释与交付"| E
```

Agent 角色对应根据可见信息形成行动的整体决策关系。LLM 提供推理能力，Context 提供本次可见的动态信息，Environment 提供观测并接受行动请求。Agent Host 实现箭头所示的信息组织、调用与交付；图中按职责展示关系，不规定组件的部署位置。

虚线表示模型输出可以被保留到后续上下文，是否保留以及保留哪些内容由 Host 决定。指向 Environment 的行动路径同样经过 Host 处理，不表示模型直接执行请求。这些路径可以随时间重复发生，下一次调用由什么触发，则取决于具体实现。

### 1.9 Loop 的含义：随时间重复的交互

这里的 loop 描述一种可以重复发生的交互时序：

```text
Context_t → LLM → action → Environment → observation → Context_{t+1}
```

这条路径不要求每次推理都产生工具请求，也不要求每条观测都立即触发推理。模型输出还可以直接参与后续上下文更新。**Loop 是交互随时间重复形成的结构，不是 Agent 定义中必须拥有的额外组件。**

Agent Host 可以用显式的 `while` 循环实现，也可以由事件驱动：

```mermaid
flowchart TD
    E["收到 Observation / Event"] --> S["保存或更新相关信息"]
    S --> Q{"是否满足调用条件？"}
    Q -->|"否"| R["结束本次事件处理"]
    Q -->|"是"| I["组织 Context 并调用 LLM"]
    I --> O["处理输出并按需交付 action"]
    O --> R
```

下一次事件到来后，Host 再处理信息；一次模型调用也可以使用此前积累的多条观测。调用是按需激活推理的方式，结束后不必立即开始下一轮。因此，系统可以表现出循环交互，而不要求 Agent 显式拥有一个循环。

**决策连续性与执行连续性**也由此分开：前者依靠多次推理之间的信息衔接，后者依靠执行系统维护任务与资源。模型暂时没有新调用时，测试程序仍可继续运行；等待结果、跟踪进度和传播取消，都可以按既定规则处理。同步与异步接口均可保持这种职责划分。

模型调用结束不代表外部任务结束。任务所有者退出、取消或执行设施失效后，工作能否继续，由具体生命周期规则决定；跨越多次推理运行，也不自动意味着能跨服务重启恢复。

这些区分为后文提供了共同的术语基础。第二章将进一步讨论工程系统如何组合这些职责、Agent Host 为什么会扩展到执行管理，以及哪些运行状态应由独立的管理主体维护。

## 2. 从决策角色到执行管理问题

### 2.1 Agent Host 为什么会扩展到执行管理

第一章区分了决策角色、模型推理与环境执行。Agent Host 将决策角色落实为软件行为：组织上下文、调用模型、解释输出并交付行动请求。但一个可以持续完成工作的系统，还需要处理请求发出之后的事情。

例如，Agent 请求运行测试后，系统需要知道测试是否已经启动、由谁负责、何时结束以及结果交给谁。多个任务同时运行时，还需要处理等待、失败、重试与取消。涉及资源访问时，又需要确定请求所依据的权限。这些需求伴随工作复杂度增加而出现，并不因采用 LLM 就消失。

把相关机制放在 Agent Host 周围，是一种直接的工程组织方式：这里已经拥有任务入口、调用接口和结果接收路径。随着功能增加，最初支持模型决策的宿主程序，也就可能承担执行跟踪、子任务管理、权限处理和资源清理等运行时职责。一个 harness 因而往往同时包含 Agent Host 及其配套的执行设施。

需要讨论的是这些职责之间的关系。模型调用、上下文更新、外部任务执行与资源管理，可以在同一个应用中实现，但它们各自维护什么状态、依赖谁持续运行，需要有明确的边界。

### 2.2 从认知连续性到执行连续性

上下文管理维持的是多次推理之间的信息衔接：当前目标是什么，已有何种证据，还有哪些问题需要判断。执行管理则需要确认请求是否获准、任务是否仍在运行、谁可以停止它，以及什么条件下可以报告完成。

这些信息可能同时出现在上下文中，但实际状态不能由上下文中的表述决定。Agent 看到“测试运行中”，只是获得了一条观测；测试是否已经结束、结果是否已保存，仍需要执行系统给出依据。

耦合也不只发生在模型记忆中。即使任务状态由普通代码维护，如果只能通过某个 Agent Host 访问，或者必须由它不断发出跟进动作才能推进，执行过程仍可能依附于该宿主。判断边界时，需要区分三种关系：

- 信息关系：状态与结果进入上下文，支持模型判断。
- 调用关系：Agent Host 请求外部组件完成工作。
- 管理关系：系统维护这次工作的身份、权限、所有权与生命周期。

前两种关系并不自动决定第三种关系。Agent 发起工作，可以成为该次执行的所有者；但这种所有权仍需要由系统表达和落实，不能只依靠它记住“这是我的子任务”。同样，一个组件被 Agent 使用，也不意味着该组件只能作为 Agent 的内部设施存在。

### 2.3 现实参照：Harness 已经承担了哪些职责

现有 harness 已经提供了模型之外的执行机制。以本文此前核对的 DeepSeek Harness 提交 `ddefc45` 为例，其模型适配器、工具、会话与默认驱动通过 Cordis 插件组合，驱动逻辑本身也可以替换。Agent Host 因而可以由多个组件共同实现。[架构说明](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/architecture.md)

在信息侧，Session 保存事件日志，模型消息历史从日志中派生；输入接口还区分内容入队与是否唤醒驱动。这说明记录一条信息、把它提供给模型和触发一次推理，可以分别处理。[Session 与消息投影](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/subsystems/session.md)、[输入与唤醒实现](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/core/agent-loop/src/agent.ts#L128-L146)

在执行侧，工具管线负责请求检查与执行，后台 Job 维护工作状态并提供等待、停止等操作，可继续交互的子会话则有相应的生命周期管理。执行管理已有明确的软件主体，不能将它概括为“让 LLM 在上下文中记住所有任务”。[工具执行管线](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/tool-execution-pipeline.md)、[后台 Job](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/subsystems/jobs.md)、[子会话管理](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/docs/subsystems/subagent.md)

这个实例把问题推进了一步：模型之外已有多种管理机制，它们分别服务于会话、工具、后台工作与委派。当这些活动需要协作时，彼此的身份、权限、等待和取消规则如何衔接？哪些差异来自工作本身，哪些差异来自各自的接口与组织方式？这里关注的是执行契约如何组合，而不是由模块数量或命名判断设计优劣。

### 2.4 多种执行活动组合时，需要回答什么

考虑一个简单场景：协调程序同时启动测试程序和一个 LLM 分析程序，等两者完成后生成报告。模型可以参与任务安排或结果解释，但两项工作的执行仍需要回答一组共同问题：

| 管理问题 | 场景中需要明确的含义 |
| --- | --- |
| 身份 | 如何区分两次运行，并将输出归到正确的任务？ |
| 权限 | 每项工作以谁的授权运行，可以访问哪些资源？ |
| 所有权 | 谁负责这两项工作，协调程序结束后由谁清理？ |
| 等待 | 等待的是某次调用返回、某条消息，还是整项工作结束？ |
| 取消 | 取消协调程序是否传播到两项工作，怎样确认处理完成？ |
| 结果 | 部分失败时如何报告，何时才能认为这次协作已经结束？ |

这些问题同样存在于普通程序之间的协作。LLM 为其中一些步骤提供了新的决策能力，但没有消除身份、资源与生命周期之间的关系。

如果每类活动采用各自的管理接口，协调程序就需要理解并衔接这些规则。这种分工可以适合各自的需求；当组合变多时，也需要检查是否出现重复管理、含义不一致或无人负责的边界。即使组件已经插件化、异步化，跨组件的执行关系仍需单独定义。

### 2.5 核心问题：哪些职责应独立于 Agent Host？

回到 Figure 1，执行管理属于 Environment 中的机制。Agent Host 可以观察运行状态、提出请求并承担协调策略，但这些行为是否要求它同时成为执行设施的管理中心？当它暂时不调用模型，或者改由另一种程序承担协调角色时，已有工作应如何继续被识别、授权、等待和结束？

独立构造首先要求明确状态归属与接口，不要求每个组件独立部署。任务之间仍可以有所有权与父子关系；具体工作能否跨越所有者退出而继续，则由生命周期规则决定。异步执行是这种划分可能支持的行为之一，同步调用也需要同样清楚的职责边界。

由此，问题可以收敛为：**当不同程序都需要身份、权限、所有权、等待、取消与结果时，哪些语义可以由共同的执行层提供，哪些应保留在各程序自己的决策与交互逻辑中？**

第三章将从这一问题出发，讨论如何保留 Agent 的决策与协调角色，并为独立运行的程序建立共同的执行边界。

## 3. 将决策与执行管理分离

### 3.1 保留 Agent 的决策与协调角色

第二章提出的问题，是不同运行活动的管理规则如何衔接。要回答它，可以保留第一章的决策关系：

```text
observation → decision → action
```

Agent Host 仍负责组织上下文、调用 LLM、解释输出与交付请求，也仍可采用 ReAct、规划或其他推理策略。需要进一步划分的是这些请求由谁接纳、如何获得运行身份，以及后续执行由谁管理。

从 Figure 1 的局部视角看，这些管理机制属于 Environment。Agent Host 通过接口使用它们；同样的接口也可以提供给确定性程序、协调器和面向人的交互程序。Agent Host 可以调用协调程序，也可以被协调程序调用，决策角色不必固定在整个执行结构的顶层。

### 3.2 为认知状态与运行状态确定各自的管理主体

短期上下文提供当前推理需要的信息，执行层维护运行中的事实与关系。两者通过观测和请求联系，但各自有明确的状态归属：

| 认知侧的信息 | 执行侧的记录 |
| --- | --- |
| 当前目标、相关历史与工作材料 | 已获准的运行实例及其状态 |
| 某项工作正在进行的观测 | 该次执行的身份、所有者与生命周期 |
| 当前可用能力与权限的说明 | 系统维护的有效权限与检查规则 |
| 用于解释结果的摘要 | 已提交的完成状态与结果 |

这种划分允许同一事实以不同形式出现。测试结束后，执行层可以保存完整结果，Agent Host 再选择失败信息放入上下文。模型暂时没有收到通知，不会使测试重新变成运行状态；上下文被裁剪，也不会撤销已经授予的权限或已经作出的终态决定。

程序仍可保留自己的内部状态。例如，协调器记住当前计划与结果解释方式，Agent Host 保存上下文组织策略。共同执行层只接管跨程序管理所需的状态，无须接管全部应用数据，也无需理解模型的推理内容。

### 3.3 从共同问题得到执行契约

回到第二章的场景：一个协调程序启动测试程序和 LLM 分析程序，等待两者结束后生成报告。两项工作的内部机制不同，但协调者都需要识别它们、等待结果，并在必要时请求取消。

共同执行契约可以为这些关系提供一致的含义：

| 契约要素 | 共同执行层需要明确的内容 |
| --- | --- |
| 身份与准入 | 区分软件定义与一次运行；请求获准后建立可引用的运行身份 |
| 输入与通信 | 输入和消息交给哪个实例，接收方如何识别来源 |
| 权限 | 请求依据什么授权，哪些操作允许执行 |
| 所有权 | 谁负责该次运行，哪些工作属于其管理范围 |
| 等待 | 等待哪些运行实例，以及什么状态满足等待条件 |
| 取消与结束 | 请求如何改变生命周期，何时报告终态，如何处理迟到结果 |

共同契约让协调程序依据运行身份与结果处理工作，不必因为其中一个程序使用 LLM，就另写一套等待或取消协议。程序的结果内容仍可不同：测试程序输出测试报告，分析程序输出语义判断，协调器负责解释和组合它们。

这里尤其需要区分所有权与等待。所有权决定生命周期责任，等待表达同步条件；创建了一个子任务，不等于当前程序已经开始等待它。取消请求被接受，也不等于底层工作已经完成清理。将这些阶段分别表达，才能让调用者知道自己实际获得了什么保证。

这份契约也需要规定完成、失败与取消同时发生时如何决定最终结果。即使接口名称统一，如果各类工作对“完成”和“取消”的含义不同，协调者仍要承担额外的适配。因此，统一执行语义要求共同的行为约定，而不只是相似的方法名称。

### 3.4 用 Event / Action 表达交互边界

一种实现上述契约的方式，是由 runtime 提供 Event，程序处理事件后返回 Action：

```text
Event → 程序处理 → Action
```

Event 表达输入、消息或运行状态变化；Action 表达程序提出的操作请求，例如创建运行实例、等待、发送、调用资源、取消或结束。runtime 检查请求并推进执行，再用事件提供后续信息。Tool calling 可以被纳入这一更一般的交互模型。

以前述协作为例，正常路径可以表达为：

```text
协调程序                         Runtime
   │                                │
   ├─ 请求创建测试与分析实例 ────────→│
   │←──────── 返回获准实例的身份 ────┤
   ├─ 请求等待这两个实例 ──────────→│
   │                                │ 维护运行、等待与结果
   │←──────── 两者均结束及各自结果 ──┤
   ├─ 解释结果、生成报告              │
   └─ 请求结束并提交报告 ──────────→│
```

创建请求可能被拒绝，工作可能失败或被取消，这些分支也应有可识别的反馈。上图只说明职责与先后关系；具体事件名称、错误规则及取消语义由执行协议确定。等待时如果目标已经结束，runtime 也应依据已保存的结果处理，而不能要求调用者恰好赶上完成通知。

一次事件处理不必对应一次模型调用。普通逻辑可以处理创建确认、结果收集等确定步骤，需要语义判断时再拼装上下文并调用 LLM。runtime 事件因而可以支持模型可见的 observation，但二者并不要求一一对应。

Event / Action 边界使工作可以在提交后独立推进。当前 Agent 暂时没有新的推理时，runtime 仍可维护运行关系并处理结果；下一次推理由 Agent Host 根据收到的信息和调用条件决定。

### 3.5 权限属于执行契约

不同决策方式共用执行层，也需要共用权限模型。一次请求至少要能确定执行主体、授权依据、目标资源与操作，系统再根据策略判断是否允许。策略可以采用白名单、权限分级或显式授权集合，具体表达方式由实现选择。

这里需要区分用户或服务的授权身份、当前运行实例，以及请求中提出的权限需求。同一个用户可以启动多个具有不同权限的实例；程序请求某项权限，并不意味着它已被授予。将工作委派给另一个程序时，也需要说明授予哪些权限、由谁检查以及是否允许继续委派。

以协作场景为例，测试程序可能需要运行测试的能力，分析程序可能只需读取指定材料。两者可以使用同一授权机制，却获得不同的权限。它们是否使用 LLM，不应自动决定权限大小。

Agent Host 可以向模型说明可用能力与当前权限，以帮助它规划行动；实际请求仍由执行层依据有效权限处理。这样，权限的描述、申请、授予和检查各有位置，模型输出可以提出操作，但不会自行改变授权事实。

### 3.6 将协调策略与执行机制放在合适的位置

共同执行层根据规则完成准入、身份维护、通信、等待、取消和结果交付。协调程序决定如何分解工作、如何解释结果以及下一步采用什么方案。两者都可能作出程序化的决定，区别在于管理什么关系。

例如，协调器可以决定某项工作失败后重试两次；执行层负责为新的执行建立身份、检查权限并报告结果。如果失败意味着原先的方法不再适用，协调器可以调用 Agent 重新判断。收集两个终态结果可以按规则完成，判断它们是否相互矛盾则可能需要语义推理。

这些职责都可以位于当前 Agent 的 Environment 中。环境既包含执行机制，也可以包含其他承担决策的程序。因此，将工作移出当前 Agent 的激活环，并不要求把所有协调逻辑放进 Kernel。

这也保留了第一章的最小模型：Agent 继续根据可见信息作出决策，能够独立推进的管理过程由相应组件承担。独立性体现为明确的接口和状态归属，同步调用、异步调用以及同一进程内的组合都可以遵守这一划分。

### 3.7 Process-like 模型及其适用范围

当一次运行需要独立的身份、权限、生命周期与结果时，Process-like 模型就成为承载共同契约的一个候选。它区分软件定义与运行实例，并将运行之间的所有权、通信和同步关系交给 runtime 管理。

逻辑 Process 可以调用 LLM，也可以执行确定性计算或协调其他程序。runtime 依据共同契约管理这些运行实例，程序内部采用什么决策方式则由其实现决定。逻辑身份也可以与具体执行后端分开，不必等同于 Linux PID、线程或模型会话标识。

共同的执行类型允许不同实例具有不同权限和所有者。Agent Host 发起的工作仍可成为其子任务，只是这条关系由 runtime 显式记录并落实；角色平等不意味着权限相同，也不取消任务层级。

这一抽象适用于需要独立管理的运行实例。程序内部的辅助函数可以继续是普通函数，简单资源访问可以通过受控接口或资源 bridge 完成。是否建立独立执行实例，取决于是否需要单独管理其运行身份、权限与生命周期，无须把每一次操作都变成 Process。

采用共同契约也有成本：不同工作类型需要明确映射到统一状态与交互规则，持续交互的程序与一次性计算还需要保留各自的行为。抽象是否合适，要看它能否减少跨程序协作时的特殊处理，同时准确表达这些差异；不能仅凭命名统一就推断性能或易用性更好。

### 3.8 引出 SemShell 的参考设计

至此，可以将本文的设计问题具体化：让 Agent Host、普通程序、协调器和面向人的程序作为统一的逻辑执行实例，通过 Event / Action 交互，并由共同 runtime 管理身份、权限、所有权与生命周期，这样的结构能否形成一致的执行模型？

在这一模型中，Operator 是程序承担的决策与协调角色。LLM-backed program、规则程序或面向人的程序可以采用不同方式生成请求，只要遵守共同契约，下游程序就无需随决策方式一起改变管理模型。这种可替换性指接口与执行结构的可替换，不保证不同实现作出相同判断。

SemShell 在后续章节作为这一问题的 executable reference design 出场。具体的软件定义、运行请求、Process、权限规则与执行案例，将用于检验本章提出的职责划分和共同契约。

## 4. SemShell：从软件定义到一次受管理的执行

第三章提出了共同执行契约，本章用 SemShell 的参考实现说明它如何运作。讨论沿着一份软件进入系统的过程展开：实现行为、注册定义、请求运行，再与其他程序组合。已有的 Echo / Coordinator 演示提供完整执行案例，一个简短的文本转换程序则展示新增软件需要填写哪些部分。

### 4.1 当前已经搭建了什么

SemShell 当前提供的是一个可运行的参考执行框架。软件实现具体行为，Catalog 保存软件定义，Kernel 维护运行身份、权限准入、消息、所有权、等待、取消与结果；受信任的 Host 启动代码负责把这些组件装配起来。应用侧主要由演示程序组成，用来检查第三章提出的边界是否能够落实为代码。

这里先区分四个对象：

| 对象 | 表达什么 | 在 Echo 示例中的含义 |
| --- | --- | --- |
| `ProcessProgram` | 程序处理事件并返回行动的行为契约 | `EchoProgram` 实现收到输入后返回结果的行为 |
| `ProcessImage` | 带版本的软件定义，包含实例工厂与能力声明 | `demo.echo@1` 指向一份可以构造 Echo 程序的定义 |
| `ProcessSpec` | 本次运行请求，包含软件选择、输入与请求权限 | 请求执行 `demo.echo`，输入为 `"alpha"` |
| Process | 准入后的一次运行，拥有 PID、状态、权限与结果 | 某次 Echo 执行，与其他 Echo 执行各有身份 |

因此，同一份 Image 可以产生多个 Process。输入不同、所有者不同或请求权限不同，都是运行请求之间的差异，无须为每次执行重新定义软件。`ProcessImage` 中的 Image 指逻辑软件定义，当前实现并不要求它是容器镜像。[软件定义与请求](./semshell/software/image.py)

这些 Process 在当前 Python 实现中共享解释器，由异步运行机制推进；逻辑 PID 不等同于操作系统 PID。Kernel 管理的是共同执行语义，生产环境中的进程隔离、容器执行与持久化属于另外的实现工作。后文涉及权限时，也只把当前实现作为受控接口的授权证据，不将其解释为对任意 Python 代码的安全隔离。[运行状态与结果](./semshell/kernel/process.py)、[安全边界](./docs/security-model.md)

### 4.2 新增软件：实现程序行为

最小程序可以只处理启动事件。现有 `EchoProgram` 收到 `Started` 后读取 `context.input`，返回 `Exit(context.input)`，把原输入作为本次执行的结果。它不自行分配 PID，也不直接修改运行状态；`Exit` 交给 Kernel 后，才由 Kernel 决定并发布终态。[Echo 实现](./semshell/examples/architecture_demo.py)

程序遵循 `handle(context, event) -> ProcessAction` 契约：一次激活处理一个 Event，返回一个 Action。Kernel 不会同时再次激活同一个 Process。多步程序可以把当前阶段保存在实例的私有状态中，待下一个事件到来后继续；这些私有状态与 Kernel 维护的运行记录各有用途。另一个接口 `stop(reason)` 用于有时间边界的尽力取消清理，程序可以在其中释放自己管理的资源。[程序接口](./semshell/software/program.py)、[激活语义](./docs/semantics.md#activation)

例如，新增一个把文本转换为大写的程序，可以写成：

```python
from semshell.kernel import (
    Exit, Fail, ProcessAction, ProcessContext, ProcessEvent, Started,
)


class UppercaseProgram:
    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if not isinstance(event, Started):
            return Fail("unsupported event")
        if not isinstance(context.input, str):
            return Fail("input must be a string")
        return Exit(context.input.upper())

    async def stop(self, reason: str) -> None:
        pass
```

这段程序明确检查输入，并用 `Fail` 表达失败。若处理函数抛出异常，Kernel 也会将其转换为结构化的失败结果。这里没有需要清理的外部资源，所以 `stop` 为空。实现满足协议即可，无须继承专用的 Agent 或 Tool 基类。

`ProcessContext` 是 Kernel 为当前激活提供的运行信息，包括 PID、所有者、Principal、有效 Authority 与输入。它不同于第一章的 LLM Context：前者描述本次执行，后者是模型本次推理可见的材料。使用 LLM 的程序可以从运行信息与事件中选择内容组织模型输入，但这种组织方式仍属于程序行为。

### 4.3 注册与发现：让系统知道这份软件

有了行为实现，还需要把它登记为可选择的软件。接着上一节的代码，受信任的装配代码可以创建 Catalog 并注册一个 Image：

```python
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import CapabilitySpec, ProcessImage, ProcessSpec

catalog = ProcessCatalog()
catalog.register(
    ProcessImage(
        image_id="article.uppercase",
        version="1",
        factory=UppercaseProgram,
        capabilities=(
            CapabilitySpec("text.uppercase", "Convert text to uppercase"),
        ),
    )
)

exact_request = ProcessSpec(image="article.uppercase@1", input="hello")
capability_request = ProcessSpec(capability="text.uppercase", input="hello")
```

这里的 factory 在准入时构造程序实例；注册只保存定义，不会执行文本转换。两个 `ProcessSpec` 展示不同选择方式：前者指定精确软件版本，后者要求 Catalog 解析提供 `text.uppercase` 能力的软件。当前 Catalog 中只有一个提供者，所以两者选择同一 Image；它们仍是两个独立的运行请求。

Capability 描述软件对外提供的语义接口，可以带有说明、输入输出 schema 等元数据。多个 Image 可以提供同一能力，此时调用方需要指定精确的 `provider`，或直接使用 Image 引用；Catalog 会拒绝含糊选择，不会自行推断“最好”的实现。各版本独立注册，重复的精确引用会被拒绝，新版本的注册也不会改变已经运行的 Process。[Catalog 实现](./semshell/software/catalog.py)

运行中的程序通过返回 `DiscoverImages()` 请求发现软件，再接收 `ImagesDiscovered` 事件。事件中的描述信息不包含实例工厂，因而不会把 Host 构造程序的 callable 交给调用者。发现也不代表获准执行：程序可以先看见能力，再提出请求，实际准入仍需检查权限。

对 LLM 程序而言，发现后还有一步工作：选择哪些描述、以什么形式放进模型上下文。Catalog 提供元数据，程序负责组织输入，Kernel 负责执行请求的准入。这三个环节不能仅凭“模型看到了一个工具名称”合并为一次操作。[Image 描述信息](./semshell/software/image.py)、[LLMShell 的上下文组织](./semshell/shells/llm.py)

### 4.4 准入与启动：从请求形成运行实例

运行请求有两个入口。受信任的 Host 启动代码可以创建根 Process；运行中的程序则返回 `Spawn`，请求创建由自己拥有的子 Process。前者负责建立执行环境的入口，后者在已有运行身份与权限范围内组合工作。

下面的代码与 4.2、4.3 的代码按顺序放在同一个 Python 文件中，可以从项目环境运行。它通过 `HostAdmin` 启动根实例，打印 `HELLO`，最后关闭 Kernel：

```python
import asyncio

from semshell.host.admin import HostAdmin
from semshell.kernel import ProcessKernel
from semshell.security import Authority, Principal


async def main() -> None:
    admin = HostAdmin(ProcessKernel(catalog))
    await admin.start()
    try:
        pid = await admin.spawn(
            exact_request,
            principal=Principal.parse("human:article"),
            authority_ceiling=Authority.empty(),
        )
        result = await admin.wait(pid)
        print(result.result)
    finally:
        await admin.stop()


asyncio.run(main())
```

`HostAdmin` 是受信任的生命周期管理接口，没有 SemShell PID，也不能作为 Process 消息的发送者。普通程序不通过这个接口创建工作，而是返回 Action，让 Kernel 从当前激活中确定请求来源。[HostAdmin](./semshell/host/admin.py)

一次成功创建的主要路径如下：

```mermaid
flowchart LR
    S["ProcessSpec<br/>软件选择、输入、请求权限"] --> R["Catalog 解析 ProcessImage"]
    R --> A["准入检查<br/>执行 ACL、请求与 Authority"]
    A --> F["工厂构造程序实例"]
    F --> P["分配 PID<br/>建立运行与所有权记录"]
    P --> E["投递 Started"]
```

准入失败不会分配 PID，也不会发布一个可运行的 Process。批量 `Spawn` 会在分配 PID、发布记录前完成整批请求的准备与检查。`Started` 则表示程序可以开始处理本次输入，后续能否成功仍由程序行为与运行结果决定。[准入语义](./docs/semantics.md#spawn-and-authority)

权限检查需要区分三个概念。Principal 标识授权主体，例如上面的 `human:article`；Image 的执行 ACL 限制哪些主体可以运行这份软件；Authority 则是本次 Process 持有的操作权限。Capability 的“提供文本转换能力”属于软件描述，`Permission(capability, scope)` 的“允许对指定范围执行操作”属于授权，两者用途不同。

当前默认策略使用精确的 Permission 集合。子进程请求的 Authority 必须在父进程有效权限内，同时满足系统与 Image 的上限，以及 Image 的最低权限要求。请求权限默认是空集合，不会因为创建了子进程就自动复制父进程的全部权限。如果请求不能被完整授予，准入会被拒绝，不会静默缩减权限后继续运行。[默认权限策略](./semshell/security/policy.py)

例如，令 `P = Permission("workspace.read_text", "demo.workspace")`。在执行 ACL、系统与 Image 限制均允许的前提下：

| 父进程的有效权限 | 子进程请求 | 准入结果 |
| --- | --- | --- |
| 包含 `P` | `{P}` | 可以授予该权限并创建子进程 |
| 空集合 | `{P}` | 拒绝，父进程没有可委派的权限 |

这里的 scope 是精确标识，不隐含路径层级或通配符。把另一个 scope 写进请求，也不会自动得到对它的访问权。上面的文本转换程序不需要资源权限，因而可以在空 Authority 下运行；读取资源的程序则需要相应授权。权限检查发生在执行边界，不依赖模型是否遵循提示词中的权限说明。[权限测试](./tests/test_authority_policy.py)

### 4.5 组合软件：创建、等待与完成

有了运行实例，下一步是让程序组合其他程序。现有 `CoordinatorProgram` 接收一组输入，为每项输入创建 Echo，等待它们结束，再汇总结果。其 `handle` 实现如下；这里省略了所在模块的导入和 `stop` 接口：

```python
async def handle(
    self, context: ProcessContext, event: ProcessEvent
) -> ProcessAction:
    if isinstance(event, Started):
        if not isinstance(context.input, (list, tuple)):
            raise TypeError("coordinator input must be a list or tuple")
        return Spawn(
            tuple(
                ProcessSpec(capability="demo.echo", input=value)
                for value in context.input
            )
        )
    if isinstance(event, Spawned):
        return Wait(event.pids)
    if isinstance(event, ChildrenCompleted):
        return Exit(tuple(result.result for result in event.results))
    raise RuntimeError(
        f"unsupported Coordinator event: {type(event).__name__}"
    )
```

这个程序决定拆分方式与结果组合方式。Kernel 接受创建请求后分配子进程身份，通过 `Spawned` 返回 PID；协调器随后显式返回 `Wait`。当目标都已进入终态，Kernel 提供 `ChildrenCompleted`，协调器才解释结果并提交自己的 `Exit`。[完整演示实现](./semshell/examples/architecture_demo.py)

```text
Coordinator                         Kernel
    │                                  │
    ├─ Spawn(Echo alpha, Echo beta) ───→│ 准入并创建子进程
    │←──────── Spawned(pids) ───────────┤
    ├─ Wait(pids) ─────────────────────→│ 维护等待关系
    │                                  │ 两个 Echo 分别结束
    │←──── ChildrenCompleted(results) ──┤
    └─ Exit(("alpha", "beta")) ────────→│ 提交协调器的终态结果
```

创建与等待因此是两个动作。所有 guest 创建的子进程都附属于一个 owner，但 owner 可以在创建之后继续处理其他逻辑，再决定等待哪些子进程。当前 `Wait` 只能等待直接拥有的子进程，且必须等显式集合中的所有目标结束；若目标在 `Wait` 前已经结束，Kernel 使用保留的结果满足等待，不要求程序恰好赶上完成通知。返回结果按 PID 排序。[所有权与等待](./docs/semantics.md#ownership-and-waiting)

在本章下一节的主演示中，Operator 创建 Coordinator，Coordinator 再创建两个 Echo。一次新 Kernel 中的结果可整理为：

| PID | 软件 | owner PID | 终态 | 结果的 JSON 表示 |
| --- | --- | --- | --- | --- |
| 1 | 所选 Operator | 无 | `EXITED` | `["alpha", "beta"]` |
| 2 | `demo.coordinator@1` | 1 | `EXITED` | `["alpha", "beta"]` |
| 3 | `demo.echo@1` | 2 | `EXITED` | `"alpha"` |
| 4 | `demo.echo@1` | 2 | `EXITED` | `"beta"` |

这组 PID 属于本次演示；一般程序应使用 `Spawned` 返回的身份，不应预设具体数字。表中展示的是软件选择、所有权与结果可以共同被观察，并不表示 Kernel 理解了“回声工具”或“协调器”这些角色。

正常路径之外，还需要明确失败由谁处理。`ChildrenCompleted` 中包含各子进程的状态、结果和错误，并不保证它们全部成功。上述简化协调器只提取 `result`，没有实现通用失败处理；实际程序应检查状态，再决定返回部分结果、重试或失败。重试可以创建新的运行实例，其策略属于协调程序。

生命周期责任则由 Kernel 落实。父进程仍有活动子进程时，正常 `Exit` 会被拒绝；异常失败与取消会进入清理流程，子进程先于 owner 完成清理。每个已准入 Process 只发布一个终态结果，迟到完成不能覆盖既定终态。等待表达同步条件，所有权决定清理范围，这两种关系在同一棵执行树中仍需分别理解。[取消与完成语义](./docs/semantics.md#cancellation-and-completion)、[生命周期测试](./tests/test_kernel_lifecycle.py)

第二、三章使用的“测试程序 + LLM 分析程序”仍是概念场景；这里的 Echo 组合提供了可执行的最小证据。它验证创建、等待与结果组合的契约，尚不替具体应用完成测试报告解释或业务失败处理。

### 4.6 同一契约下的 LLM 程序与 Operator

普通文本程序直接计算结果，LLM 程序则可以在处理事件时组织上下文、调用模型 backend，再将模型输出解析成 Action。两者交给 Kernel 的边界相同，差异位于程序内部。

当前 `LLMShell` 收到 `Started` 后先请求发现软件；收到 `ImagesDiscovered` 后，把任务、Image 引用和能力名称组织为模型输入，再调用 `SemanticBackend`。backend 返回文本，由 `action_from_data` 解析为结构化行动，随后交给 Kernel 处理。模型 SDK 的对象不进入 Kernel 的执行契约。[LLMShell](./semshell/shells/llm.py)、[行动解析](./semshell/shells/codec.py)

在这个最小实现中，收到 `Spawned` 后返回 `Wait`、收到子任务结果后结束等步骤由普通逻辑完成，并不再次调用模型。这与第三章的区分一致：事件处理提供推进执行的机会，模型只在程序选择的步骤参与判断。更复杂的 Agent Host 可以在同一接口内实现自己的上下文管理与调用策略。

仓库用三种 Operator 运行同一个任务。在完成 [README 中的环境安装](./README.md#setup) 后，从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm
```

三次输出中的关键结果如下，完整 JSON 还包含运行树与权限决策记录：

| Operator | 根 Image | Process 数量 | 最终 `result` |
| --- | --- | --- | --- |
| Human | `demo.human-shell@1` | 4 | `["alpha", "beta"]` |
| Rule | `demo.rule-shell@1` | 4 | `["alpha", "beta"]` |
| LLM | `demo.llm-shell@1` | 4 | `["alpha", "beta"]` |

三个 Operator 都通过发现、创建、等待和完成的共同契约，驱动同一组 Coordinator 与 Echo 软件。替换根 Image 后，下游所有权结构、程序与终态值保持一致，Kernel 不增加 Human、Rule 或 LLM 专用的运行分支。[可替换性与角色边界测试](./tests/test_operator_demo.py)

这份证据的范围也需要准确理解。human 路径接收预置的 `OperatorTask`，没有在这三条命令中实现交互终端；llm 路径使用离线的 scripted backend，预先给定行动输出。它们验证不同决策实现可以接入同一执行契约，不比较真人、规则和真实模型的判断质量，也不保证任意替换程序都会产生相同结果。

Host CLI 在这里负责装配与展示。任务进入根 Process 后，由 Operator 返回结构化行动；Coordinator 随后也会决定自己的子任务。决策可以分布在普通程序中，不要求所有行动都经过一个位于顶层的 LLM。

### 4.7 接入资源：程序之外的另一条扩展路径

软件组合解决了独立运行实例之间的协作。读取材料等操作还需要访问运行环境中的资源。SemShell 为这类访问提供被动的 ResourceBridge：程序提出资源请求，由 Kernel 检查当前执行身份与权限，再调用受信任 Host 提供的实现。

`WorkspaceReaderProgram` 展示了这条路径。它从启动输入中取得 binding ID 与相对路径，返回 `InvokeResource(binding_id, "read_text", {"path": path})`；收到 `ResourceCompleted` 后提交读取结果，收到 `ResourceRejected` 后用 `Exit({"error": ...})` 提交业务错误。Kernel 拒绝请求或已准入的 bridge 执行失败，均可产生 `ResourceRejected`。这个示例处理该事件后仍正常结束为 `EXITED`；程序也可以选择 `Fail`，将操作错误转为整个 Process 的失败。读取程序有自己的 PID 与生命周期，bridge 则是被调用的 Host 资源接口。[读取程序与装配](./semshell/examples/resource_demo.py)

资源必须先由 Host 装配。Host 在 Kernel 启动前建立 `ResourceRegistry`，把 binding ID、操作到 Permission 的映射以及 bridge 实例绑定起来。例如，`demo.workspace` 的 `read_text` 操作要求 `Permission("workspace.read_text", "demo.workspace")`。guest 不能凭一个名字自行注册或替换该绑定。[资源注册](./semshell/resources/registry.py)

调用时，Kernel 从当前 Process 记录中取得 PID、Principal 与有效 Authority，分配调用 ID，检查资源、操作、权限和容量，并把 JSON-like 输入冻结为不可变数据。缺少权限的请求在进入 bridge 前就会被拒绝；只有获准后，bridge 才负责操作本身的参数校验与访问。调用结果通过后续事件回到程序，程序无须取得 Host 实现对象。[资源调用语义](./docs/semantics.md#host-resource-invocation)

扩展演示可以验证允许、拒绝与取消边界：

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario extended
```

其中，资源访问与生命周期结果包含以下证据：

| 输出字段 | 值 | 所说明的边界 |
| --- | --- | --- |
| `resource.success.result`、`resource.success.bridge_invocations` | `"hello"`、`1` | 获准的读取调用 bridge 并返回内容 |
| `resource.denied.bridge_invocations` | `0` | 缺少权限时没有调用 bridge |
| `cancellation.owner_state`、`cancellation.child_state` | 均为 `CANCELLED` | 取消覆盖 owner 与附属子进程 |
| `cancellation.child_result_publications` | `1` | 子进程只发布一个终态结果 |
| `cancellation.late_outcome_suppressed` | `true` | 迟到的资源结果不能重新激活已取消的 Process |

取消持有资源调用的 Process，不等于底层操作已经物理停止。当前契约先确定执行侧的取消与结果交付规则；即使 bridge 迟到返回，也不能改变终态。演示使用内存 bridge 和受控时序验证这些性质，没有访问本地项目文件，也不能据此推断已经实现了文件系统隔离。[扩展演示](./semshell/examples/extended_demo.py)、[资源测试](./tests/test_kernel_resources.py)

更完整的委派演示把程序组合与资源授权放在同一个场景中：

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario delegation
```

Host 通过绑定的 ConsoleBridge 向 UserShell 提交对话。UserShell 创建空 Authority 的 `llm1`，后者启动两个文本工具，并请求读取受限报告。直接读取和自行创建更高权限子进程的尝试都会被拒绝。随后，`llm1` 向 UserShell 发送委派请求，UserShell 检查请求并使用自己已有的权限创建 `llm2`：

```text
UserShell                         [报告读取权限]
├── llm1                          [空 Authority]
│   ├── 文本工具：词数             [空 Authority]
│   └── 文本工具：字符数           [空 Authority]
└── llm2                          [报告读取权限]
```

`llm2` 与 `llm1` 协作，但由 UserShell 拥有。UserShell 等待 `llm2` 后把结果作为消息交给 `llm1`；`llm1` 没有直接等待兄弟进程，也没有因此获得报告读取权限。Kernel 为消息提供真实的来源 PID，应用程序负责请求关联与应答解释。协作关系、所有权与授权因而可以分别表达。

这里的批准来自固定白名单策略，模型输出来自 scripted backend；演示中的越权尝试也是预先安排的验证步骤。UserShell 的批准不能制造自己没有的权限，Kernel 仍会独立执行准入检查。该示例验证的是授权范围内的委派与结果转交，并非通用交互审批系统。[委派场景与验证](./docs/delegation-demo.md)、[委派测试](./tests/test_delegation_demo.py)

由此可以区分两种扩展方式：需要独立身份、权限与生命周期的工作实现为 ProcessProgram；需要供程序访问的 Host 资源则通过受控 bridge 接入。同一个应用可以同时使用两者，无须把每次资源操作都包装成新 Process。

### 4.8 已验证的边界与后续软件开发

回到新增软件的问题，本章的文本转换程序只需要实现行为、声明 Image 与能力、加入 Catalog 装配，再由调用方提交 `ProcessSpec`。使用现有 Event / Action 契约时，不需要为它向 Kernel 增加新的软件角色分支。相应的输入、结果、失败与组合行为仍应由软件自己的验证覆盖；共同运行机制不会替应用证明业务正确性。

目前的示例也标出了后续开发的具体空间。CLI 仍是演示入口，没有通用安装或运行命令；`required_capabilities` 和 schema 等声明没有形成自动依赖装配与通用输入输出校验机制。新增软件需要明确装配，程序也仍需检查业务输入。当前 `LLMShell` 仅把 Image 引用和能力名称提供给模型，软件说明、参数 schema 与失败反馈如何进入更完整的决策流程，还需要在程序侧继续实现。

参考实现已经提供可检查的运行证据：不同 Operator 可以驱动共同的软件组合，Kernel 维护身份、等待、所有权与唯一终态，资源请求在 Host 调用前接受权限检查。这些性质由具体演示和测试支撑，不构成性能提升、真实模型能力或生产可靠性的结论。操作系统隔离、持久化恢复与生产执行后端仍属于独立的实现范围。[参考实现与生产边界](./docs/reference-and-production.md)

对于前三章讨论的 Agent Host，这一划分意味着它可以继续管理上下文、调用模型并决定如何协调工作，同时作为普通程序使用共同执行契约。程序决定要做什么、如何解释结果；运行框架维护哪次执行已获准、由谁拥有、何时结束以及留下什么结果。两者通过事件与行动衔接，使认知过程的延续与执行过程的管理各有明确的软件主体。
