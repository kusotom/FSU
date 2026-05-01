# FSU Readonly Observation Scheduler

## Purpose

定时执行 FSU 只读观测巡检，持续整理 raw packet 日志、日报、新帧检测、当前 DSC/RDS 状态机判断和注释报告。

## Safety Boundary

- 不发送 UDP。
- 不新增 ACK。
- 不运行 `send-one-shot-ack.js`。
- 不修改 `fsu-gateway` 回包逻辑。
- 不写业务主表。
- 只读 `backend/logs/fsu_raw_packets/*.jsonl`。
- 只生成巡检和分析报告。

## Install

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\install-fsu-readonly-observation-task.ps1
```

默认创建 Windows 任务计划程序任务：

- 任务名：`FSU Readonly Observation`
- 频率：每 30 分钟一次
- 执行入口：`backend\scripts\run-fsu-readonly-observation.cmd`

## Manual Run

```powershell
schtasks /Run /TN "FSU Readonly Observation"
```

也可以直接手动运行一次脚本：

```powershell
node backend\scripts\run-fsu-readonly-observation.js
```

## Query Task

```powershell
schtasks /Query /TN "FSU Readonly Observation" /V /FO LIST
```

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\uninstall-fsu-readonly-observation-task.ps1
```

等价命令：

```powershell
schtasks /Delete /TN "FSU Readonly Observation" /F
```

## Outputs

- `backend/logs/fsu_raw_packets/readonly-observation-run-*.md`
- `backend/logs/fsu_raw_packets/readonly-observation-run-*.json`
- `backend/logs/fsu_raw_packets/readonly-observation-scheduler.log`
- `backend/logs/fsu_raw_packets/daily-observation-*.md`
- `backend/logs/fsu_raw_packets/daily-observation-*.json`
- `backend/logs/fsu_raw_packets/new-frame-types-*.md`
- `backend/logs/fsu_raw_packets/new-frame-types-*.json`
- `backend/logs/fsu_raw_packets/current-dsc-rds-state-*.md`
- `backend/logs/fsu_raw_packets/current-dsc-rds-state-*.json`
- `backend/logs/fsu_raw_packets/dsc-rds-annotation-v0.2-*.md`
- `backend/logs/fsu_raw_packets/dsc-rds-annotation-v0.2-*.json`

如果发现真实设备新帧，还会额外生成：

- `backend/logs/fsu_raw_packets/new-frame-observation-*.md`
- `backend/logs/fsu_raw_packets/new-frame-observation-*.json`

## Troubleshooting

- `node` 不在 PATH：安装 Node.js，或在任务入口中改为 Node 的绝对路径。
- PowerShell 执行策略限制：使用 `-ExecutionPolicy Bypass` 运行安装/卸载脚本。
- `schtasks` 权限不足：使用管理员 PowerShell，或在任务计划程序中手动创建任务。
- 后端未运行：巡检报告会记录 `healthOk=false`，但不会启动或修改网关逻辑。
- UDP `9000/7000` 未监听：巡检报告会记录对应监听状态为 `false`。
- raw log 未增长：巡检报告会记录 `rawLogGrowing=false`，需要检查后端 FSU gateway 运行状态和设备网络。
- 中文路径问题：`.cmd` 入口使用 `chcp 65001` 并切换到固定项目根目录。

## Notes

管理员 API `/api/v1/fsu-debug/raw-packets` 需要 token。自动巡检脚本不会硬编码管理员密码；如需检查受保护 API，可在任务环境中提供 `FSU_DEBUG_BEARER_TOKEN`。未提供时，巡检报告会标记 `fsuDebugApiChecked=skipped`。
