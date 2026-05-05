# B Interface Release Summary

日期：`2026-05-06`

适用范围：铁塔 B 接口阶段性发布说明，可直接复用为 GitHub Release 草稿或项目周报。

## 摘要

本轮完成了 FSU 北向铁塔 B 接口的阶段性闭环，从 SOAP/WSDL 兼容、真实 FSU 入站观测、状态与告警落库，扩展到 FSUService 手动出站、实时/历史数据、信号映射、出站审计，以及升级/重启控制命令的安全阻断框架。

当前实现重点是：
- 可兼容真实 FSU 的 SOAP 1.1 `rpc/encoded` `invoke(xmlData)` 交互
- 可观察、可审计、可缓存、可查询
- 对控制类命令默认阻断，避免真实设备副作用

## 已完成能力

### 1. SOAP/WSDL 兼容
- `SCService` / `FSUService` SOAP 1.1 `rpc/encoded` 兼容
- `invoke(xmlData) -> invokeReturn` 主操作
- 动态 WSDL 返回
- 与原始附件级 `SCService.wsdl` / `FSUService.wsdl` 对齐

### 2. 入站业务兼容
- `LOGIN`
- `SEND_ALARM`
- `GET_DATA`
- `TIME_CHECK`
- `GET_FSUINFO`
- `GET_LOGININFO`
- `SET_LOGININFO`
- `SET_FSUREBOOT`

### 3. 数据能力
- FSU 登录状态缓存
- 当前告警 / 历史告警入库
- 实时点位入库
- 历史点位 `GET_HISDATA_ACK` 入库

### 4. 映射与缓存
- `init_list.ini`
- `SignalIdMap.ini`
- `SignalIdMap-2G.ini`
- `MonitorUnits XML`
- `GET_FSUINFO_ACK` / `GET_LOGININFO_ACK` 结构化缓存

### 5. 出站能力
- 手动 `FSUService` 客户端
- `GET_DATA`
- `GET_HISDATA`
- `TIME_CHECK`
- `GET_FSUINFO`
- `GET_LOGININFO`
- 统一出站审计与错误分类

### 6. 控制命令安全框架
- `SET_FSUREBOOT`
- `AUTO_UPGRADE`
- `SET_AUTOUPGRADE`
- `SET_FSUUPGRADE`
- `SET_UPGRADE`

当前全部只支持：
- 识别
- 解析
- 审计
- 阻断
- 授权 dry-run

不支持真实执行。

## 安全结论

- 默认禁止真实重启
- 默认禁止真实升级
- 默认禁止真实设备控制
- 不自动外呼真实 FSU
- 不修改 UDP DSC/RDS 主监听逻辑
- 不新增真实 UDP ACK
- 控制命令 `executed` 恒为 `false`

## 验收基线

核心回归命令：

```powershell
python -m compileall backend\app
.\.venv\Scripts\python.exe -m unittest tests.test_b_interface_soap -v
```

当前测试基线：
- `78/78 OK`

## 主要文档

- `docs/b-interface-soap-integration.md`
- `docs/b-interface-live-test.md`
- `docs/b-interface-p0-acceptance.md`
- `docs/b-interface-p1-acceptance.md`
- `docs/b-interface-p2-signal-mapping.md`
- `docs/b-interface-p2-fsuinfo-logininfo.md`
- `docs/b-interface-p2-outbound-audit.md`
- `docs/b-interface-p2-hisdata.md`
- `docs/b-interface-p2-005-auto-upgrade-reboot.md`
- `docs/b-interface-p2-005-acceptance.md`

## 仍未完成

- 原厂全量 WSDL/报文完全对齐
- 真实升级执行链路
- 真实重启执行链路
- 升级包下载、校验、回滚
- 更完整的 FSUService 真机联调

## 下一步建议

建议进入 `P2-006`：
- 基于真实样本继续补全厂商差异字段
- 如确有需要，再单独设计“受控执行层”，不要直接在当前阻断框架上放开真实控制
