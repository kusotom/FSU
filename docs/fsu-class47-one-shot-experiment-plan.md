# FSU classByte=0x47 注册返回 one-shot 受控实验方案

## 1. 实验目标

本实验目标不是接管平台，不是长期自动回包，也不是启用线上 ACK。

目标仅限于：

- 只验证 FSU 是否接受一次 classByte=0x47 注册返回候选。
- 观察 FSU 是否从重复 209/245 注册/配置阶段进入 Register OK 候选状态。
- 观察是否出现新的 RDS_REALDATA / BUSINESS_DATA_ACTIVE 相关帧。
- 不写业务主表。
- 不修改真实 FSU 配置。

## 2. 当前离线依据

离线协议图谱 v1.4：

- `backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-2026-05-01.md`
- `backend/logs/fsu_raw_packets/final-offline-protocol-map-v1.4-2026-05-01.json`

D2FF ACK 已完整复现：

- pairedBySeq = exactMatches = checksumMatches
- success = true

0x47 当前最优候选：

- typeBytes = `110047ff`
- seq = mirror 0x46 request seqLE
- header[8..19] = copy 0x46 request context
- payloadLength = 171
- totalLength = 195
- ackRequiredFlag = false
- checksum = normal LE

0x47 payload：

- resultCode = 0
- serviceCount = 6
- requiredMask = 0x3f
- channelType 0/5/6/7/8/9

## 3. 实验前置条件

1. 当前 Git 工作区必须干净。
2. 当前 raw log 正常增长。
3. 当前设备 online。
4. UDP_DSC 9000 正常监听。
5. UDP_RDS 7000 正常监听。
6. 当前仍能观察到 209/245 注册/配置重复帧。
7. 当前仍能观察到 RDS30 / D2FF ACK 配对。
8. 最新 0x46 请求帧可被提取。
9. 已备份实验前 raw log 文件。
10. 已记录实验前 raw log size。
11. 已记录实验前最新 seqLE。
12. 已记录实验前 frameClass 分布。
13. 已明确人工批准实验窗口。
14. 实验期间无人修改平台配置。
15. 实验期间不得运行其他 ACK / 发包脚本。

## 4. 明确禁止事项

- 禁止循环发送。
- 禁止自动响应所有 0x46。
- 禁止修改 `service.py`。
- 禁止把候选逻辑接入 fsu-gateway。
- 禁止写业务主表。
- 禁止自动 ACK。
- 禁止修改真实 FSU。
- 禁止刷固件。
- 禁止在未确认 raw log 起点时实验。
- 禁止在设备异常或 raw log 不增长时实验。

## 5. 实验候选包原则

候选包必须：

- 基于最新一条真实 0x46 请求。
- 回显该请求 seqLE。
- 复制该请求 header[8..19]。
- 使用 typeBytes = `110047ff`。
- 使用 payloadLength = 171。
- 使用 resultCode = 0。
- 包含 channelType 0/5/6/7/8/9。
- requiredMask = 0x3f。
- checksum 使用普通 FSU checksum LE。
- 只允许一次性发送。
- 不允许循环发送。

本文档不提供发包脚本，不提供可执行发包命令。

## 6. 实验步骤草案

以下步骤仅作为未来如获人工批准后的草案。本文档不执行任何实验。

1. 停止所有非必要测试脚本。
2. 确认 fsu-gateway 只读接收正常。
3. 记录 raw log 当前大小。
4. 记录最新 frameClass 分布。
5. 提取最新 0x46 请求帧。
6. 离线生成 110047ff 候选帧。
7. 人工复核候选：
   - seq
   - header[8..19]
   - payloadLength
   - checksum
   - payload requiredMask
8. 若人工批准，则未来可由单独受控脚本只发送一次。
9. 发送后不再补发。
10. 观察 30 秒到 120 秒。
11. 生成实验后观察报告。
12. 若出现异常，立即停止。

第 8 步必须由未来独立任务执行。本文档不执行。

## 7. 观测指标

实验前后比较：

- raw log 是否继续增长。
- 209/245 是否停止或减少。
- RDS30 是否继续。
- D2FF ACK 是否继续。
- 是否出现新 frameClass。
- 是否出现非 24/30/209/245 长度。
- 是否出现 RDS_REALDATA 候选。
- 是否出现 classByte 非 0x46/0xd2。
- 是否出现 Register OK 相关日志。
- 是否出现错误/重连/超时。
- 设备 online 状态是否变化。
- `/health` 是否正常。
- API raw-packets 是否正常。

## 8. 成功判定

成功候选条件：

- 设备保持 online。
- raw log 正常增长。
- 209/245 重复明显减少或停止。
- 出现新的 RDS_REALDATA / 业务数据候选帧。
- 未出现异常重连/错误/离线。
- D2FF ACK 机制仍正常。
- 观察窗口内没有异常告警。

成功条件只是候选成功，不是完整业务解析完成。

## 9. 失败 / 停止条件

任一条件出现必须停止：

- 设备 offline。
- raw log 停止增长。
- 209/245 重试频率异常升高。
- 出现大量 UNKNOWN。
- 出现异常长度帧。
- fsu-gateway 报错。
- `/health` 异常。
- 设备 Web 或平台状态异常。
- 出现重复发送风险。
- 任何人工判断异常。

## 10. 回滚方式

由于本方案不修改真实 FSU、不修改 `service.py`、不写业务主表、不改变网关逻辑，回滚主要是：

- 停止实验脚本。
- 保留 raw log。
- 恢复只读观察。
- 不再发送任何候选包。
- 如单独开过实验分支，则回到 v1.4 Git 提交。
- 如设备状态异常，先断开实验脚本，不做进一步写操作。

## 11. 风险说明

- `110047ff` 未经线上验证。
- FSU 可能忽略该包。
- FSU 可能进入未知状态。
- FSU 可能要求额外时间同步/配置同步。
- URI 填写策略可能不对。
- RDS_REALDATA 不一定立即出现。
- 实验只能证明候选行为，不能证明协议完整。
- 不允许长期自动化。

## 12. 是否进入下一阶段的准入标准

只有满足以下条件，未来才允许另起任务写 one-shot 发包脚本：

1. 本方案文档已人工审阅。
2. raw log 只读观察稳定。
3. Git 工作区干净。
4. 实验窗口明确。
5. 发包脚本必须独立，不能接入 `service.py`。
6. 发包脚本必须默认 dry-run。
7. 发包脚本必须需要显式 `--execute` 才能发送。
8. 发包脚本必须限制只发送一次。
9. 发包脚本必须写入实验日志。
10. 发包脚本必须拒绝循环模式。

## 13. 当前结论

当前只建议生成实验方案，不建议立即实验。

当前最安全下一步是人工审阅方案。

本文档不包含发包脚本，也不执行任何网络动作。
