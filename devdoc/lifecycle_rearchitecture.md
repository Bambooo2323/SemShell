# SemShell 生命周期整理与分阶段重构计划

日期：2026-09-07。状态：实施范围已归纳，代码尚未按本计划改造。

## 1. 结论与范围

采纳“决定结果、执行清理、等待结果、回收记录、关闭运行时”职责分离的方向，
分三个阶段推进：先修复局部竞争，再统一内部生命周期，最后单独评估公开契约变化。
近期实施范围为第一、第二阶段；第三阶段是待决策项，不是前两阶段的完成条件。

本文面向 Python 参考内核。现行行为以 `docs/semantics.md` 为准，生产边界沿用
`docs/reference-and-production.md`：本仓库提供可执行的语义证明，实际执行与隔离交给
独立的 Linux／OCI runtime。保留 Process、Event、Action、Authority 和公开结果类型。

本次只整理计划，不代表实现或验收完成。内部优化不自动授权改变公开行为；实现中发现
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
admission、进入 STOPPING、保存根 PCB 引用并登记任务；其他 stop 调用等待同一任务的
shield 视图。取消任一等待者不得取消已提交的 shutdown。

根集合包括 detached 根。清理辅助路径使用已解析的 PCB／completion，避免等待后重新
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

## 5. 第三阶段：单独评估契约变化

以下是设计候选，不随前两阶段实施。每项须说明现行行为、目标行为、调用方影响、
错误语义和验收用例，再同步规范与实现；没有必要证据时可以保持现状。

| 候选变化 | 待决策内容 |
| --- | --- |
| TREE 遇到 FAILING | 是否从整体拒绝改为保留失败成员、继续取消其他成员；何时替换 `_cancel_tree_after_failures` |
| 一次封闭子树 | 父异常或 shutdown 是否立即对整个范围提交决定；与 Spawn／Detach 的先后顺序及清理并发上界 |
| 公开过渡状态 | 是否调整 CANCELLING／FAILING 的可见性、含义和快照字段；第二阶段不删除这些状态 |
| wait/reap 扩展 | 是否改变活动 wait 对 reap 的限制或新增观察能力；内部稳定引用不要求改变资格条件 |
| queued interruption | 取得 mutation 配额前中断是否阻止 Kernel 调用；取得配额后如何同步提交 EXECUTING 边界 |
| Control 关闭与审计扩展 | 是否需要共享 close task、独立 operation_outcome，以及相应记录保留规则 |

TREE 如采用逐成员决定，应在无 await 的步骤中校验并收集稳定引用，保留已有胜者，
封闭后禁止新建 attached／detached 后代及 ownership 变更。Detach 先提交则脱离范围，
TREE 先提交则拒绝 Detach；detached 根仍由 shutdown 管理。兄弟可并发清理，若串行则
须按节点数给出总时间上界，不能把单 hook 超时视为整棵树的时间上界。

queued interruption 如变更，应明确排队与执行的分界：取得配额、检查未中断、同步
标记执行开始并调用 Kernel；此后中断只结束观察，operation task 由 Gateway 持有。

finalizer 自动恢复、自动 reaper、结果持久化、生产 supervisor 和容器执行器暂缓，
不作为第三阶段默认交付。批量 spawn 的额外事务重构也不并入本计划；保留已有 metadata
失败不消耗 PID 的回归保护，新增问题单独提供证据后处理。

## 6. 修改落点与验收

| 阶段 | 主要落点 | 交付边界 |
| --- | --- | --- |
| 第一阶段 | `semshell/kernel/kernel.py`、`semshell/control/session.py`、`semshell/control/gateway.py` | 共享 stop、稳定引用、迭代遍历、唯一 reply/audit |
| 第二阶段 | `semshell/kernel/_runtime.py`、`semshell/kernel/kernel.py` | TerminalDecision、统一 finalizer、completion 依赖和故障监督 |
| 第三阶段 | 受影响实现、`docs/semantics.md`、`devdoc/control_protocol_semantics.md` 等契约文件 | 逐项迁移公开行为；按需更新资源契约与代码导览 |

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
| 三 | TREE 范围与 Spawn／Detach 竞争 | 仅在新契约采纳后验证原子封闭和逐成员保留胜者 |
| 三 | 排队／执行后 interrupt | 仅在新契约采纳后验证前者不调用 Kernel、后者不回滚 |

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

原提案列出以下资料；本次为文档归纳，未重新联网核验，也未做 Linux 实机测试：

- [_exit(2)](https://man7.org/linux/man-pages/man2/_exit.2.html)
- [wait(2)](https://man7.org/linux/man-pages/man2/wait.2.html)
- [pthread_cancel(3)](https://man7.org/linux/man-pages/man3/pthread_cancel.3.html)
- [pthread_detach(3)](https://man7.org/linux/man-pages/man3/pthread_detach.3.html)
- [pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
- [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
