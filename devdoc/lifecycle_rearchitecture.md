# SemShell 生命周期整理与分阶段重构计划

日期：2026-09-08。状态：第一、第二阶段已实现并通过验收；原第三阶段由 design edition
migration 取代，当前行为仍保持有效。

## 1. 结论与范围

采纳“决定结果、执行清理、等待结果、回收记录、关闭运行时”职责分离的方向，
分三个阶段推进：先修复局部竞争，再统一内部生命周期，最后迁移公开契约。
第一、第二阶段已经完成并作为 design edition 的正确性基础保留。原第三阶段不再作为
当前实施路线；替代计划见
[`design_edition_migration_stages.md`](design_edition_migration_stages.md)。

本文面向 Python 参考内核。现行行为以 `docs/semantics.md` 为准，生产边界沿用
`docs/reference-and-production.md`：本仓库提供可执行的语义证明，实际执行与隔离交给
独立的 Linux／OCI runtime。保留 Process、Event、Action、Authority 和公开结果类型。

实施与验收状态见文末记录。内部优化不自动授权改变公开行为；实现中发现
无法兼容的地方，应归入第三阶段并说明具体影响。

## 2. 问题依据

以下依据当前源码结构判断；竞争场景仍须通过确定性回归用例确认，不能把代码检查
写成测试已通过或已完成运行复现。

| 当前路径 | 问题或已有基础 | 对应行动 |
| --- | --- | --- |
| `ProcessKernel.stop()` | 保存根 PID，逐个等待后重新查表；整个流程属于外部调用任务 | 共享 shutdown task，跨 await 保留 PCB 引用 |
| `_activate()` | 持有执行槽期间等待 Action 和异常清理 | 第二阶段将清理移出 activation |
| `cancel()` / `_fail_abnormally()` | 取消已有独立 cleanup task，异常清理仍由 runner 执行 | 统一 Kernel 持有的 finalizer |
| `_finish()` 及其调用者 | 竞争依靠各路径的状态判断，缺少独立决定记录 | 引入不可变 TerminalDecision |
| `_subtree_pids()` / `_cancellation_postorder()` | 使用递归遍历 | 改用显式栈，同时检查公开 tree 路径 |
| `ControlGateway.close_session()` | 依据 await 前的 was_replied 决定是否补记审计 | reply 与终态 audit 共用一次性提交点 |
| `wait()` | 已解析一次 PID 并 shield completion | 保留现有能力，验证与 reap 交错 |
| `reap()` | 已检查终态、ownership 子节点和活动 wait | 前两阶段保留资格条件 |

这些修改服务于结果唯一、清理不被观察者取消、停机不遗漏目标等不变量。
完整 finalizer 恢复、自动回收和持久化会明显扩大参考实现，不纳入近期范围。

## 3. 第一阶段：局部竞争修复

### 3.1 共享 shutdown 与稳定目标引用

Kernel 持有唯一 `_shutdown_task`。首次 stop 在受控且不含 await 的提交步骤中关闭
admission、进入 STOPPING、保存目标 PCB 引用并登记任务；其他 stop 调用等待同一任务的
shield 视图。取消任一等待者不得取消已提交的 shutdown。

目标集合包括 detached 根及当时的 attached 子进程，按根优先顺序清理。保留全部目标
是为了覆盖已运行的 activation 在停机期间执行 Detach 的情况，不改变 Detach 资格。
清理辅助路径使用已解析的 PCB／completion，避免等待后重新
依赖 PID 表项；只对已知终结的对象跳过清理，不把任意 ProcessNotFound 解释为成功。
第一阶段保留现行子树取消、FAILING 拒绝和清理顺序。

所有目标按现行契约完成，剩余任务已完成或按现行机制登记为 draining 后，才进入
STOPPED。不能在 finally 中无条件设置 STOPPED。内部失败向 stop 调用者报错并保留
STOPPING，本阶段不承诺自动恢复。STOPPING 拒绝 start，正常 STOPPED 后保留 restart，
新一轮使用新的 shutdown task，PID 不复用。

### 3.2 迭代遍历

将子树收集、取消后序遍历以及公开 tree 路径中的递归改成显式栈。保留成员范围、
排序和子先于父的清理顺序，不在这一步改变 TREE 遇到 FAILING 的处理规则。

### 3.3 reply 与 audit 一次性提交

以受控 `commit_reply` 合并检查、保存 reply、追加唯一终态 audit 和唤醒 future。
提交内不 await，可能失败的数据准备在提交前完成。succeed、reject、interrupt、close
以及 admission 后的 busy rejection 均走同一入口，删除 was_replied 推断和重复记账。

Gateway 绑定受控审计入口，Session 不调用 Kernel。保留 Request 与 Process 两条时间线：
关闭观察不回滚已开始的 mutation。保留现行晚到审计类型，每个真实晚到结果最多记一次。
本阶段不新增 EXECUTING 状态、不改变排队 mutation 的 interruption 契约，也不新增
独立 operation_outcome 审计流。审计唯一性仅限当前内存生命周期。

完成条件：停止调用者取消、stop/reap 交错、并发 stop 和 close/reply 竞争均有确定性用例；
旧契约断言保持成立，正常 restart 和深树遍历通过。

## 4. 第二阶段：统一内部生命周期

第一阶段验收后推进。保持公开 ProcessState、ProcessResult、wait/reap 资格及现行
TREE 拒绝行为；内部竞争统一使用 decision，公开 CANCELLING／FAILING 继续表示清理中。

### 4.1 唯一决定与结果发布

| 内部记录 | 职责 |
| --- | --- |
| `decision: TerminalDecision \| None` | 不可变终态决定，保存 EXITED／FAILED／CANCELLED、原因、时间和已冻结的结果数据 |
| `completion: Future[ProcessResult]` | 继续作为唯一结果发布点，观察者使用 shield |
| `finalizer_task: Task \| None` | Kernel 持有并监督的唯一清理执行者 |
| `runner: Task \| None` | 当前 activation，不拥有整个 Process 生命周期 |

Exit、显式 Fail、Program 异常、非法 Action 和 Cancel 使用统一的同步提交入口。
先完成校验和可失败的数据冻结，再提交 decision；入口内不 await、不调用 Program、
Policy、bridge 或扩展代码。结果冻结失败转换为结构化 FAILED。

无 decision 时按现行资格接受请求；已有 decision 时，晚到 Action 或异常不得覆盖胜者。
重复 cancel 的返回或拒绝仍按现行契约，例如 FAILING 时仍拒绝，不能统一改成等待原结果。

decision 提交后不再调度普通 activation。完成必要清理后才发布 ProcessResult 并进入
公开终态；没有清理工作的正常退出可以同步发布。有活动 attached 子进程时，继续拒绝
Exit／显式 Fail／SELF cancel。

### 4.2 Kernel 持有 finalizer

异常提交失败后退出 runner，由 Kernel 推进清理。取消和异常共用清理机制，但保留
hook 差异：显式取消调用有超时限制的 `Program.stop(reason)`；异常路径执行 Kernel
清理，不额外调用已抛异常 Program 的 stop。

activation 持有执行槽运行 handle，释放槽后接收 Action／提交终态。runner 标记保持到
Action 接收结束，避免重入；接收前重查 decision，丢弃取消后的返回值。仍在实际执行的
不合作 handler 不得提前释放其占用配额。

finalizer 负责取消 runner／待执行资源、抑制晚到事件、执行必要 hook、等待 attached
child completion，再发布结果。owner 只等待 child，child 不等待 owner。清理不占
activation semaphore，hook 最多调用一次；hook 超时或抛错只追加诊断，不改终态胜者。

当前实现保留 TREE 的串行后序清理：新 finalizer 记录前一已选节点的稳定引用，
先等该节点，再清理自身。依赖只沿既定后序向前，不引入 child 等待 owner。
单次 TREE 的清理时间上界随成员数量增长。

Cancel Action 的完成通知由 Kernel 持有。调用者仍可继续运行时，登记显式 completion
依赖并进入 WAITING；已有 decision 时不登记依赖、不投递完成通知。这包括自我取消和
经授权取消包含自身的祖先 TREE，必须避免 runner 与 finalizer 双向等待。

复用现有 draining 管理不合作 runner／bridge，资源实际结束前不归还配额，晚到结果
不改变终态。旧任务按原 PCB／invocation identity 结算，不干扰 restart 后的新进程。

### 4.3 内部故障边界

Kernel 必须收集 finalizer 异常。finalizer 意外退出时，监督路径应使 shutdown 明确失败，
保留 STOPPING，不得无限等待失去执行者的 completion，也不得伪造子树完成。
普通 wait 不因此获得新的公开恢复协议；故障诊断应能识别未完成的 PCB。

本阶段不实现 finalizer 接管、阶段日志或再次 stop 自动恢复。若必须引入公开清理失败
结果或改变 wait 行为，移入第三阶段决策，不能用 FAILED 覆盖已提交的 CANCELLED 决定。

完成条件：所有终止路径只有一个 decision 和一个结果发布点；清理独立于请求者及执行槽；
竞争、self-cancel、异常清理和超时用例通过，旧公开契约保持成立。

## 5. Superseded third-stage design

本节保留 2026-09-08 的历史设计背景。它没有实现，也不再是当前 TODO。当前代码继续
遵循 `docs/semantics.md`，后续不兼容修改按 design edition staged migration 同步规范、
实现和测试。

### 5.1 Cancel 统一为 ownership 级联

公开取消不再让调用者选择 SELF 或 TREE。`cancel(pid)` 固定取消目标及其全部 attached
后代；需要独立存活的 child 必须在取消提交前完成 Detach。Process 只拥有并直接管理
自己的 child，Kernel 沿直接 ownership 边迭代收集完整后代并负责清理，不要求 Process
查询或编排整棵树。

取消范围在一个不含 await 的提交步骤中完成校验、收集稳定引用并封闭。该步骤与 Spawn、
Detach 的同步提交顺序决定范围：Detach 先提交则 child 已成为独立根；取消先提交则该
child 已进入范围，后续 Spawn 和 Detach 拒绝。detached 根仍由 Kernel shutdown 管理。

范围中已有 FAILED、FAILING、CANCELLED 或其他终态决定的成员保留原决定，其余成员提交
CANCELLED；某个成员已失败不能使整次级联取消拒绝。Kernel 仍按 child 先于 owner 的
方向确认完成，ProcessResult 各自保存实际胜者。现有 `CancelMode.SELF/TREE` 进入兼容性
迁移：先标记弃用并把两者归一为级联语义，再在下一次明确破坏性版本移除参数和枚举。

### 5.2 Pause 是正交的调度状态

pause 不加入 ProcessState 主状态机，而是在 PCB 上增加独立调度状态：

```python
class SchedulingState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
```

Process 同时保留 `READY/RUNNING/WAITING/terminal` 生命周期状态和 `ACTIVE/PAUSED` 调度
状态。pause 只禁止创建新的 activation，不回退、不重算底层状态，也不取消当前工作。

- READY 或 WAITING 时 pause 立即提交。
- RUNNING 时立即把调度状态改为 PAUSED；当前 `handle()` 和返回的 Action 正常完成提交，
  但不启动下一次 activation。Exit 或 Fail 仍可直接进入终态。
- mailbox 在暂停期间继续按现行规则接收 Event。普通消息保持 FIFO；Resource 和 child
  completion 保留既有 continuation 优先级，pause 不重新定义事件顺序。
- Resource、child 和等待目标继续推进，底层 WAITING 可以因 completion 变为 READY，
  scheduler 因 PAUSED 不执行它。
- resume 只恢复 ACTIVE；若底层状态已经是 READY，立即调用 scheduler，否则继续等待。
- cancel 和 shutdown 可以直接终止暂停中的 Process。

参考内核第一版允许暂停期间继续接收普通 IPC 和 console input，沿用当前无界 mailbox；
文档明确这是内存参考实现限制。生产 runtime 必须定义队列容量和背压。第一版 pause
只作用于指定 Process，不隐式传播给 child，不暂停正在执行的 Resource，也不提供回滚。

Control 增加类型化 `PauseProcess`／`ResumeProcess`，分别要求
`control.process.pause`／`control.process.resume` Authority。第一版只提供 Host Control
入口，不新增 guest 暂停其他 Process 的 Action。边界式 pause 对所有 Process 可用，
不要求 image 声明能力。长时间不返回的 `handle()` 无法被立即冻结；需要
快速响应的程序应拆分为短 activation。协作式 token、显式 checkpoint 和 durable resume
属于后续能力，不纳入第三阶段。

### 5.3 Interrupt 是 Control 请求的观察状态

interrupt 只作用于 ControlRequest，不修改 ProcessResult，不隐式转换为 pause 或 cancel。
Shell Ctrl+C、session close、客户端 deadline、排队超时和上层取消 token 复用同一提交
入口，并记录结构化 source 和 reason。Kernel Process scheduler 不自动产生 interrupt。

一个 Request 同时保留执行状态和观察状态：

```python
class RequestExecutionState(StrEnum):
    ADMITTED = "ADMITTED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"

class RequestObservationState(StrEnum):
    OPEN = "OPEN"
    REPLIED = "REPLIED"
    INTERRUPTED = "INTERRUPTED"
```

`QUEUED -> EXECUTING` 是 mutation 的不可回退边界。Gateway 取得 mutation slot 后，
在同一个不含 await 的受控步骤中检查 observation、提交 EXECUTING，然后立即调用 Kernel：

- interrupt 先赢：execution 进入 SKIPPED，提交唯一 INTERRUPTED reply，不调用 Kernel。
- EXECUTING 先赢：interrupt 只把 observation 改为 INTERRUPTED，Kernel 操作继续。
- 后台操作完成后，execution 进入 SUCCEEDED 或 REJECTED；若 observation 已 INTERRUPTED，
  只追加一条 LATE_SUCCEEDED 或 LATE_REJECTED，不产生第二个 reply。

只读观察被 interrupt 后可以取消其 handler；已 shield 的 Process completion 和目标 Process
不受影响。`WaitProcess.timeout` 仍是操作自身的 timeout rejection，不是 interrupt；Process
运行期限使用独立 cancel/deadline 机制。Control 客户端 deadline 和 mutation queue timeout
才进入 INTERRUPTED，其中 queue timeout 必须发生在 EXECUTING 之前。

reply 与终态 audit 继续通过唯一 `commit_reply` 提交。实际执行结果使用独立
operation outcome 记录，使 `EXECUTING + INTERRUPTED` 之后仍能表达真实结果。Session
close 同步关闭 admission，中断所有 OPEN observation，跳过尚未执行的 queued mutation，
取消无副作用的观察 handler，并保留已 EXECUTING 的 mutation task。

### 5.4 尚待决定的项目

以下内容尚未收敛，不能与前三项一起默认实施：

| 项目 | 待决策内容 |
| --- | --- |
| 公开过渡状态 | 是否调整 CANCELLING／FAILING 的可见性、含义和快照字段 |
| wait/reap 扩展 | 是否改变活动 wait 对 reap 的限制或新增观察能力 |
| Control close task | 多个 close 是否共享 Gateway 持有的任务，以及关闭完成的准确边界 |

finalizer 自动恢复、自动 reaper、结果持久化、生产 supervisor 和容器执行器继续暂缓。
批量 spawn 的额外事务重构也不并入本阶段；保留已有 metadata 失败不消耗 PID 的回归
保护，新增问题单独提供证据后处理。

### 5.5 第三阶段实施顺序

1. 先更新规范和公开类型，写明兼容期以及每个竞争的线性化点。
2. 将 cancel 归一为 ownership 级联，并实现与 Spawn／Detach 的原子范围封闭。
3. 增加正交 SchedulingState、PauseProcess 和 ResumeProcess。
4. 拆分 RequestExecutionState 与 RequestObservationState，落实 queued interrupt 边界。
5. 增加 operation outcome 审计并迁移 Control close。
6. 完成定向竞争测试后，运行全套 pytest、Ruff 和 strict mypy。

## 6. 修改落点与验收

| 阶段 | 主要落点 | 交付边界 |
| --- | --- | --- |
| 第一阶段 | `semshell/kernel/kernel.py`、`semshell/control/session.py`、`semshell/control/gateway.py` | 共享 stop、稳定引用、迭代遍历、唯一 reply/audit |
| 第二阶段 | `semshell/kernel/_runtime.py`、`semshell/kernel/kernel.py` | TerminalDecision、统一 finalizer、completion 依赖和故障监督 |
| 第三阶段 | Kernel Process/operation 类型、Control request/session/gateway、公开规范 | 级联 cancel、正交 pause、双维 interrupt；其他候选逐项决策 |

用 Event／Future 栅栏固定竞争顺序，避免依靠长 sleep 或反复运行碰概率。

| 阶段 | 场景 | 必须成立 |
| --- | --- | --- |
| 一 | 取消 stop 等待者、并发 stop | 已提交 shutdown 继续，同轮共享任务 |
| 一 | stop 与 reap 交错 | 已解析的终结对象不因移除 PID 索引导致 shutdown 失败 |
| 一 | 已登记 wait 与 reap 交错 | 新查询失败，已有观察保持有效；reap 资格不变 |
| 一 | STOPPING/start、正常 restart | STOPPING 拒绝 start；新轮 stop 正常工作，PID 不复用 |
| 一 | 深树超过递归阈值 | 合理提高 max_processes 后，tree/cancel/shutdown 不递归溢出 |
| 一 | close 与 reply／interrupt、busy rejection | 每个已回复请求只有一条终态审计，真实晚到结果最多一条 late 审计 |
| 二 | Exit／异常／Cancel 竞争 | 合法请求按提交顺序决定胜者，仅一个 decision 和 result |
| 二 | self-cancel、父子同时取消、后代取消祖先 TREE | 无 self-await 或双向依赖，终止调用者不接收完成通知 |
| 二 | 取消 waiter／cancel caller | 已提交清理继续，观察取消不改变进程结果 |
| 二 | max_running=1、hook 抛错或超时 | 清理不占执行槽，hook 最多一次，晚到 Action 不复活进程 |
| 二 | finalizer 内部故障 | shutdown 明确报错并保持 STOPPING，不伪造结果，不隐式重试 hook |
| 二 | TREE 含 FAILING、Exit 有活动子节点 | 前两阶段仍满足现行拒绝规则 |
| 三 | cancel 与 Spawn／Detach 竞争 | 原子提交顺序决定范围；级联不因已有失败成员整体拒绝 |
| 三 | CancelMode 兼容期 | SELF 和 TREE 都执行 ownership 级联，并发出稳定弃用提示；后续版本移除 |
| 三 | READY／WAITING pause/resume | pause 不改底层状态；resume 后 READY 恢复调度，WAITING 继续等待 |
| 三 | RUNNING 时 pause | 当前 Action 正常提交，后续 activation 被抑制；Exit/Fail 可直接终结 |
| 三 | 暂停期间的事件 | 普通消息保持 FIFO，continuation 保持既有优先级，恢复后无丢失或重复 |
| 三 | PAUSED 与 cancel/shutdown | 暂停不能阻止终态决定、清理或 Kernel 停机 |
| 三 | queued mutation interrupt | interrupt 先赢则 SKIPPED 且不调用 Kernel；EXECUTING 先赢则操作继续 |
| 三 | 执行后的 interrupt | 只有一个 INTERRUPTED reply，实际结果最多一条 late operation outcome |
| 三 | interrupt 来源与 timeout | source/reason 冻结；WaitProcess.timeout、client deadline、queue timeout 不混用 |
| 三 | Session close | queued mutation 跳过、只读观察取消、已执行 mutation 继续且可审计 |

每阶段先运行受影响的定向用例。近期第一、第二阶段完成后运行一次全套 pytest、Ruff、
strict mypy；只有新改动、新失败或未解决疑点才扩大或重复验证。第三阶段若实施，按其
独立变更重新验收。旧断言仅在明确采纳契约变化后迁移，并记录原因。

## 7. Linux／POSIX 对照与资料

Linux 对照用于解释边界，不决定 Python 内部实现。SemShell Process 跨多次 handle
存活，是逻辑任务；activation、Linux PID 和 pthread 不与它一一对应。

| 参照 | 本方案采用的启发与差异 |
| --- | --- |
| `pthread_cancel` / `pthread_join` | 接受取消与确认结束分开；不复制 pthread 可禁用取消的语义 |
| `_exit` / `exit_group` | 一个 runner 结束不代表整个逻辑 Process 清理完成 |
| `waitid(WNOWAIT)` | 可重复观察与回收分开；Python 记录不是 Linux zombie |
| Linux 父子关系 | Linux 通常重新收养孤儿；SemShell attached 的成功等待和异常清理是自身契约 |
| `pthread_detach` | 不等于 SemShell Detach；后者解除 owner，仍可 Host wait/reap，仍受 shutdown 管理 |
| `pidfd_open` | 稳定引用避免跨 await 依赖 PID 查表；无需引入文件描述符或持久化身份系统 |
| cgroup v2 | 请求终止与观察范围结束分开；生产容器子层级与逻辑 Process 子树需分别管理 |

Python 无法强停吞取消或阻塞事件循环的代码，超时以事件循环可继续运行为前提。
逻辑终态不保证 Host 副作用停止；更强的执行边界由生产 runtime 提供。

以下参考资料沿用原提案；本次实现期间未重新联网核验，也未做 Linux 实机测试：

- [_exit(2)](https://man7.org/linux/man-pages/man2/_exit.2.html)
- [wait(2)](https://man7.org/linux/man-pages/man2/wait.2.html)
- [pthread_cancel(3)](https://man7.org/linux/man-pages/man3/pthread_cancel.3.html)
- [pthread_detach(3)](https://man7.org/linux/man-pages/man3/pthread_detach.3.html)
- [pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
- [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)

## 8. 实施记录

2026-09-08：第一、第二阶段已实现。Kernel 使用共享 shutdown、稳定目标引用、
迭代遍历、TerminalDecision 和统一 finalizer；Control 将审计准备与一次性回复提交
连接起来，移除了 was_replied 快照推断。未改变 TREE 的 FAILING 拒绝规则、reap 资格
或排队 mutation 的 interruption 行为。原第三阶段设计没有实现，现已由 focused design
edition migration 取代；自动恢复仍不在范围内。

验收证据：全套 pytest 149 项通过，Ruff 通过，strict mypy 检查 54 个源文件通过。
新增用例覆盖并发 stop、停机调用者取消后独立完成、wait/reap 与 stop/reap 交错、
停机期间 Detach、1,100 层子树、单执行槽上的异常及取消清理、授权后代取消祖先、
晚到 Action、结果冻结失败，以及 finalizer
抛错／被取消／遗漏 completion。Control 用例覆盖 close 与成功回复交错、晚到 mutation
和审计准备失败。`git diff --check` 通过。
