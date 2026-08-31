# LLM-Operated CLI OS：面向 LLM 的进程化执行环境设计草案

## 1. 项目定位

本项目尝试构建一个基于 Python 的简易 CLI-like Operating Environment，用于演示一种 **Process-Centric、LLM-Operated** 的 Agent 系统架构。

传统 CLI 操作系统中，人承担目标理解、程序选择、命令组织和交互式决策；在这里，这部分职责可以由 LLM 接管。

但这里并不是简单地“用 LLM 替换 Shell”。

更准确地说：

> 过去由人在 CLI 中承担的部分交互式控制工作，现在可以交给一个由 LLM 驱动的 Shell Process。

Kernel 本身仍然负责确定性的执行机制，包括进程创建、进程关系、IPC、生命周期、资源与权限管理。

---

## 2. 核心类比

```text
传统 CLI                         LLM CLI OS

人理解目标                      LLM 理解目标
人选择程序                      LLM 选择 software capability
人输入命令和参数                LLM 产生结构化 Action
Shell 创建进程                  Kernel 创建进程
程序调用其他程序                Process spawn / send
人观察输出后决定下一步          LLM 接收事件后决定下一步
Ctrl+C                          用户或父进程发起 cancel
OS 管理进程关系和资源           Kernel 管理进程关系和资源
```

因此，“人变成 LLM”主要发生在 **Operator / Shell 层**，而不是 Kernel 层。

---

## 3. 整体结构

```text
Human / External Principal
          │
          │ goal / approval / authority
          ▼
Operator Process
(HumanShell / LLMShell / ScriptShell / RuleShell)
          │
          │ Structured Action
          ▼
Process Kernel
          │
          │ spawn / send / wait / cancel / exit
          ▼
Process Images / Running Processes
  ├── LLM-backed Program
  ├── Tool Program
  ├── Memory Program
  ├── Coordinator Program
  ├── Approval Program
  └── Ordinary Python Program
          │
          ▼
Host OS
Python asyncio / subprocess / filesystem / network
```

系统运行在现有操作系统之上，不重新实现真实 OS 的 CPU 调度、虚拟内存、文件系统或网络栈。

它更像一个 **Agent-oriented user-space process runtime / control plane**。

---

## 4. 最重要的设计原则：LLM 不是 Kernel

LLM 不拥有特殊系统地位。

LLM 可以承担 Shell / Operator 角色，但 LLM-backed program 本身仍然只是普通软件。

```text
LLM can act as Shell
but
LLMProgram is still only an executable image
```

一个 LLM Shell Process 可以：

- 创建 Tool Process；
- 创建普通 Python Process；
- 创建另一个 LLM Process；
- 创建 Coordinator Process；
- 创建另一个 Shell Process。

Shell 也不一定由 LLM 驱动。

```text
HumanShell
ScriptShell
RuleShell
LLMShell
```

它们都通过同一个 Kernel 接口工作。

这意味着系统不再把 LLM、Tool、Memory、Coordinator 建模为不同等级的对象。

---

## 5. Flattened Architecture

传统 LLM-centric Agent 架构通常类似：

```text
LLM
├── tools
├── memory
├── skills
├── subagents
└── loop
```

其中 LLM 是应用中心，其他能力被视为 LLM 的附属物。

本项目希望改成：

```text
Kernel
├── Process
├── Process
├── Process
└── Process
```

某些 Process 使用 LLM。

某些 Process 提供确定性 Tool capability。

某些 Process 持有 Memory。

某些 Process 暂时承担 Coordinator 或 Operator 角色。

Kernel 不需要知道这些语义角色。

理想情况下，Kernel 核心代码中甚至不需要出现：

```text
Agent
Tool
LLM
Memory
Coordinator
```

Kernel 只认识：

```text
Process
ProcessImage
Capability
Message
Action
Lifecycle State
Authority
```

核心不变量可以表述为：

> The kernel recognizes processes, capabilities, messages, authorities, and lifecycle states—not agents, tools, or LLMs.

---

## 6. ProcessImage：逻辑可执行文件

`ProcessImage` 可以理解为系统中的逻辑 executable image，类似 `.exe`、ELF executable 或 container image，但在 Python 原型中不要求真的生成二进制文件。

```text
ProcessImage
    +
ProcessSpec
    ↓
Kernel.spawn()
    ↓
Process
```

### 6.1 ProcessImage

ProcessImage 是静态的软件定义。

它可以包含：

```text
image_id
version
entrypoint / factory
provided capabilities
required capabilities
input schema
output schema
description
trust metadata
image ACL
```

例如：

```text
web-search@1
```

表示一种可运行的软件定义。

---

## 7. ProcessSpec：一次具体启动配置

同一个 executable image 可以通过不同启动参数形成不同 Process。

```text
ProcessSpec
├── args
├── env
├── cwd
├── requested authority
├── resource limits
├── parent
└── metadata
```

例如：

```text
web-search@1
   ├── PID 41(query="MCP")
   ├── PID 42(query="Agent Runtime")
   └── PID 43(query="Claude Code")
```

因此：

> ProcessImage 是程序定义；Process 是一次具体运行实例。

---

## 8. Process：系统中的一等执行对象

Process 是 Kernel 真正管理的运行时实体。

一个 Process 可以具有：

```text
pid
ppid
image_id
args
env
state
mailbox
authority
children
result
started_at
```

系统中的 LLM Worker、Tool、Shell、Coordinator、Memory 都只是不同的 Process。

例如：

```text
PID 10  HumanShell
PID 20  LLMShell
PID 21  CodeReviewer
PID 22  TestRunner
PID 23  MemoryService
```

从 Kernel 的执行模型看，它们没有本质区别。

---

## 9. User、Principal 与 Process

这里必须区分：

```text
Principal
Process
Authority
```

### 9.1 Principal

Principal 回答：

> Who owns or authorizes this execution?

例如：

```text
human:alice
service:ci
system
```

Principal 是身份与授权来源，不是执行实体。

---

### 9.2 Process

Process 回答：

> What is currently executing?

例如：

```text
PID 10 HumanShell
PID 11 LLMShell
PID 12 Python
PID 13 Search
```

---

### 9.3 Authority

Authority 回答：

> What may this process do?

例如：

```text
fs.read:/repo
fs.write:/repo/src
network:github.com
spawn:python
```

三者关系：

```text
Principal
    │
    │ delegates
    ▼
Process
    │
    │ carries
    ▼
Authority
```

Kernel 在实际执行时主要处理：

```text
Process + Authority
```

而不是直接处理 Human。

---

## 10. Human 与 LLM 的执行路径应保持一致

Human 不是一种特殊 Kernel execution entity。

人对系统的一切操作，最终也应通过某个 Process 进入 Kernel。

```text
Human
  ↓
HumanShell Process
  ↓
Kernel
```

LLM 同样：

```text
LLM backend
  ↓
LLMShell Process
  ↓
Kernel
```

脚本同样：

```text
Script
  ↓
ScriptShell Process
  ↓
Kernel
```

因此：

```text
                Kernel
                   ▲
          same process interface
                   │
       ┌───────────┼───────────┐
       │           │           │
 HumanShell     LLMShell    ScriptShell
       ▲           ▲
       │           │
     Human        LLM
```

可以同时存在：

```text
Alice
 ├── PID 10 HumanShell
 └── PID 20 LLMShell
```

两者可以协作。

例如：

```text
LLMShell
   ↓ request approval
HumanShell
   ↓ approve / deny
Kernel
```

因此更准确的表述是：

> The LLM is not the user. It is a process that may temporarily exercise the operator role under delegated authority.

---

## 11. Operator 是角色，不是系统对象类型

Operator 可以是：

```text
HumanShell
LLMShell
RuleShell
ScriptShell
RemoteShell
```

Operator 负责：

- 理解目标；
- 查询可用 software capability；
- 选择程序；
- 构造输入；
- 请求创建进程；
- 接收事件；
- 决定继续、等待、重试、派生、取消或结束。

但 Operator 不是 Kernel 特权对象。

它仍然只是一个 Process。

因此：

```text
Operator != Principal
Operator != Kernel
Operator == Role played by a Process
```

---

## 12. Kernel 应保持最小化

Kernel 只负责机制，不负责智能策略。

建议核心接口保持接近：

```text
spawn(...)
send(...)
recv(...)
wait(...)
cancel(...)
exit(...)
reap(...)
inspect(...)
```

Kernel 内部主要维护：

```text
Process Table
Authority Table
Event Queue
```

Kernel 不应该理解：

- planning；
- reasoning；
- RAG；
- memory retrieval；
- multi-agent；
- ReAct；
- reflection；
- tool routing。

这些都属于 user-space software 或 operator policy。

---

## 13. CLI 与 Syscall 必须分离

系统可以提供一层人和 LLM 都容易理解的 CLI：

```text
images
ps
tree
spawn <capability> <input>
send <pid> <message>
wait <pid>
cancel <pid>
inspect <pid>
reap <pid>
```

但 CLI 不是 Kernel 的核心协议。

它应该被转换成结构化 Action / Syscall：

```text
Spawn(...)
Send(...)
Wait(...)
Cancel(...)
Exit(...)
Fail(...)
```

于是同一个操作可以有三种入口：

```text
Human CLI input
LLM structured output
Program-generated Action
          │
          ▼
      same Kernel
```

CLI 只是 Kernel 的一种用户界面。

---

## 14. Event-Driven，而不是固定 Agent Loop

系统不应该把：

```text
while not done:
    llm()
    tool()
```

作为最高层 execution model。

更合理的是：

```text
event arrives
    ↓
runtime wakes process
    ↓
process handles event
    ↓
maybe invoke LLM
    ↓
maybe invoke tool
    ↓
emit event / syscall
    ↓
yield
```

例如：

```text
USER_GOAL
   ↓
wake LLMShell
   ↓
LLM decides Action
   ↓
Kernel executes
   ↓
LLMShell yields

PROCESS_EXIT
   ↓
wake LLMShell
   ↓
LLM decides next Action
```

因此 ReAct、Plan-and-Execute、FSM 或固定 workflow 都可以作为某个 Process 内部的策略实现，但不是 Kernel 的固定执行模型。

---

## 15. Capability Catalog：类似 PATH，但更语义化

传统 CLI 中，人通过：

```text
git
python
curl
rg
```

找到程序。

这里可以通过 capability 找到软件：

```text
reason
web_search
edit_file
review_code
remember
coordinate
```

Catalog 可以理解为比 PATH 更结构化的软件目录。

例如：

```text
CapabilitySpec
├── name
├── description
├── input_schema
├── output_schema
├── side_effects
├── estimated_cost
└── required_authority
```

同一个 capability 可以有多个 provider：

```text
search.web
├── provider-a@1
├── provider-b@2
├── local-index@1
└── human-search@1
```

于是 Shell 可以表达：

```text
spawn capability=search.web
```

而不是直接绑定某个 Python 类、URL 或 SDK。

---

## 16. 软件目录不应在 Kernel 启动后固化

系统启动后，可运行软件必须允许动态变化。

```text
OS running

install
remove
upgrade
download
compile
register
```

因此 `Catalog` 应是动态的，而不是 Kernel 初始化时写死的 registry。

结构可以是：

```text
Software Store
      │
install / remove / update
      ▼
Catalog
      │
resolve capability / image
      ▼
Kernel.spawn(...)
```

Package Manager 本身也可以是普通 user-space Process。

Kernel 只需要知道：

```text
resolve
load
spawn
```

而不需要理解“安装软件”这一高层策略。

---

## 17. 权限模型：Image Requirement 与 Process Authority 分离

不能把权限简单固定在 executable 上，也不能让 `spawn()` 调用者随意创造权限。

需要区分：

```text
Image requirements
Process authority
Parent authority
System policy
User approval
```

### 17.1 Image Requirements

Image 可以声明：

```text
required:
    network.http

optional:
    memory.cache
```

这表示：

> 该软件可能需要这些能力。

但这不意味着它自动获得这些权限。

---

### 17.2 Process Authority

真正运行中的 Process 拥有的是 effective authority。

例如：

```text
PID 42

authority:
    network.http: github.com
    fs.read: /workspace/**
```

---

### 17.3 权限继承与削减

子进程默认只能继承或削减父进程已有 authority。

形式上：

```text
ChildAuthority ⊆ ParentAuthority
```

除非经过更高权限主体显式授权。

例如：

```text
Parent
{A, B, C}

spawn child
      ↓

Child
{A, B}
```

普通进程不能凭空创造：

```text
root
new network access
production secret
admin capability
```

---

### 17.4 Spawn 中的权限参数应是 request，而不是 grant

更合理的语义是：

```text
spawn(
    image,
    args,
    requested_authority=...
)
```

Kernel 最终根据：

```text
Image Declaration
      ∩
Parent Authority
      ∩
System Policy
      ∩
Optional User Approval
```

决定实际 Process Authority。

因此：

> requested authority is a request, not a grant.

---

## 18. Image ACL 与 Process Capability 是两回事

Image 本身可以有 ACL，例如：

```text
who can read it
who can modify it
who can execute it
who can upgrade it
```

这类似 Unix executable file permissions。

但进程启动以后能访问什么资源，是另一套机制。

因此：

```text
Image ACL
→ 谁能操作 / 执行这个软件

Process Authority
→ 这次运行能操作哪些资源
```

两者不能混淆。

---

## 19. Structured IPC，而不是默认聊天消息

IPC 不应该默认使用：

```json
{"role": "user", "content": "..."}
```

更通用的结构可以是：

```text
Message
├── source_pid
├── target_pid
├── kind
├── payload
└── correlation_id
```

消息类型例如：

```text
REQUEST
RESULT
EVENT
ERROR
CANCEL
SIGNAL
```

Payload 可以是任意结构化 schema。

因此：

```text
LLM ↔ LLM
```

可以传自然语言；

但：

```text
Tool → Coordinator
```

可以直接传：

```json
{
  "files_changed": 3,
  "tests_passed": true
}
```

Conversation 只是 IPC payload 的一种形式，而不是系统骨架。

---

## 20. Prompt、Context 与 Skill 的重新解释

在这套架构中：

```text
system prompt
→ 软件配置 / 行为说明

tool schema
→ CLI 参数规范 / callable interface

skill
→ man page / script package / operating manual

context
→ 当前 process / shell session 的工作上下文

conversation history
→ interaction history，不等于 process state

model
→ 某种 semantic execution engine

ProcessImage
→ 真正的软件定义
```

因此：

- 同一个 model backend 可以运行多个不同 ProcessImage；
- 同一个 ProcessImage 也可以切换不同 model backend。

---

## 21. 输出、事件与退出状态

Tool 与 LLM-backed Process 应统一采用进程结果语义。

例如：

```text
ProcessResult
├── pid
├── state
├── result
└── error
```

可类比：

```text
EXITED
→ exit code 0

FAILED
→ non-zero exit

CANCELLED
→ signal / cancellation

result
→ stdout-like structured output

error
→ stderr-like structured diagnostic

events
→ streaming output
```

但系统应保持 structured data first，而不是退化成只能传文本的 Unix pipe。

---

## 22. 一个最小演示流程

用户输入：

```text
检查这个项目为什么测试失败，能安全修的话修掉。
```

执行树可能是：

```text
PID 1  LLMShell
 ├── PID 2  inspect_project
 │    └── EXIT 0
 ├── PID 3  run_tests
 │    └── EXIT 1
 ├── PID 4  diagnosis_llm
 │    └── EXIT 0
 ├── PID 5  edit_file
 │    └── WAITING_APPROVAL
 ├── PID 6  approval
 │    └── EXIT ALLOW
 └── PID 7  run_tests
      └── EXIT 0
```

这个演示不需要额外引入：

```text
planner agent
executor agent
review agent
tool node
graph edge
```

进程树本身就能表达执行结构。

---

## 23. 项目的核心论点

可以收敛为三句话：

> 现代 Agent 框架通常把 LLM 当成应用中心，把工具、Memory 和 Sub-agent 当成 LLM 的附属物。

> 本项目把 LLM、Tool、Memory、Coordinator 和普通程序都定义为平等的可执行软件，并在运行时实例化为 Process。

> 它像一个简易 CLI operating environment：只是过去坐在终端前逐步选择和运行程序的人，现在可以由 LLM-backed Shell Process 替代。

更精确的英文版本：

> A tiny CLI-like operating environment where LLM-backed programs, tools, coordinators, memory services, and ordinary programs are equal executables, while an LLM-backed process may temporarily act as the primary operator.

以及：

> The LLM is not the kernel, and it is not the user. It is an executable process that may exercise the operator role under delegated authority.

---

## 24. 关键设计不变量

建议仓库第一版始终坚持以下 invariants：

1. **Kernel 不认识 Agent、Tool、LLM、Memory、Coordinator。**
2. **所有运行实体统一为 Process。**
3. **ProcessImage 与 Process 必须分离。**
4. **Operator 是角色，不是 Kernel 特权类型。**
5. **Human 与 LLM 的执行路径最终都通过 Process 进入 Kernel。**
6. **Principal 负责身份与授权，Process 负责执行。**
7. **Authority 属于具体 Process execution，而不是自动固化在 Image 上。**
8. **Child Process 默认只能继承或削减 Parent Authority。**
9. **Software Catalog 可以动态 install / remove / update。**
10. **CLI 只是结构化 syscall 的一种入口。**
11. **IPC 以结构化 Message 为主，而不是默认 Conversation。**
12. **Loop、Graph、ReAct 等只是 Process 内部策略，不属于 Kernel execution model。**

---

## 25. 推荐的仓库关键词

```text
flattened architecture
process-centric runtime
software/process separation
explicit execution structure
capability-based program discovery
structured IPC
LLM-operated CLI
model-agnostic kernel
event-driven execution
delegated authority
dynamic software catalog
```

---

## 26. 文章 / 小论文方向

可以考虑以下标题：

### 方向一

**From Agent Loops to Processes: A Tiny LLM-Operated CLI Environment**

### 方向二

**LLMs Are Programs, Not Kernels: A Process-Centric Runtime for Agentic Software**

### 方向三

**Flattening the Agent Stack: LLMs, Tools, and Coordinators as Equal Processes**

其中第二个最直接体现核心设计立场。

---

## 27. 后续最小实现范围

第一版 Python 原型不需要追求完整 OS 功能。

建议只实现：

```text
ProcessImage
ProcessSpec
Process
ProcessKernel
CapabilityCatalog
Authority
Message
EventQueue
HumanShell
LLMShell
```

以及少量示例软件：

```text
llm-worker
python-runner
memory-service
approval-service
test-runner
file-editor
```

重点验证的不是“能不能做复杂 Agent”，而是以下三件事：

1. **Operator 可替换**  
   同一个 Kernel 能运行 HumanShell、RuleShell、LLMShell。

2. **执行实体拍平**  
   LLM、Tool、Coordinator、Memory 在 Kernel 视角下都是 Process。

3. **权限与生命周期显式化**  
   spawn、wait、cancel、exit、authority inheritance、approval 可以被完整观察和审计。

如果这三点成立，项目就已经足以支撑一篇有明确论点的技术文章，并为后续小论文提供实验基础。
