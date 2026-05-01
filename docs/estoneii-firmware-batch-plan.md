# eStoneII 固件批量接入改造方案

日期：2026-04-05

## 目标

针对同型号 eStoneII 动环设备，做一版“最小改动”的定制升级包，使设备批量刷机后默认接入自有平台，而不是继续接入铁塔侧默认北向。

这版方案的目标不是去改协议实现，也不是强行取消认证，而是：

- 保留现有 `L2TP/PPP` 接入架构
- 保留现有 PPP 认证流程
- 批量固化自有 `LNS`
- 批量固化自有 `tt_proxy` 上送目标
- 让后续设备刷包后直接接入自有平台

## 现状结论

已确认的北向链路：

- `gprs_monitor -> L2TP/PPP -> tt_proxy -> UDP/10378`

已确认的关键配置文件：

- `modem/gprs_monitor/gprs_monitor.default.ini`
- `modem/gprs_monitor/options.l2tpd.client.tieta`
- `modem/gprs_monitor/tt_proxy.ini`
- `disaster.ini`

已确认的升级链：

- `update.sh`
- `update_main.sh`
- `update_gprs_monitor.sh`
- `update.tar.gz`

其中 `update_main.sh` 会把 `update.tar.gz` 解到 `/tmp/remote_update`，再整体覆盖：

- `/modem/*`
- `/home/*`
- `/etc/*`
- `/lib/*`
- `/data2/*`

这意味着，批量改造的主落点应优先放在 `update.tar.gz` 里的配置模板，而不是先改二进制。

## 为什么不先改二进制

当前不建议首轮就修改下列二进制：

- `modem/gprs_monitor/gprs_monitor`
- `modem/gprs_monitor/tt_proxy`
- `modem/gprs_monitor/ttb.so`

原因：

- 风险高，容易引入启动失败或协议回归
- 回滚成本高
- 现阶段业务目标只需要“改接入面”，配置足够实现
- 真实批量上线时，更需要可复用、可回滚的配置固化方案

## 建议修改的文件

### 1. `modem/gprs_monitor/gprs_monitor.default.ini`

建议改这些字段：

- `[l2tp_tunnel0] name`
- `[l2tp_tunnel0] password`
- `[l2tp_tunnel0] server_ip`
- `[l2tp_tunnel0] subnet`
- `[l2tp_tunnel0] l2tp_lns`
- `[l2tp_tunnel0] l2tp_subnet`
- `[l2tp_tunnel0] l2tp_lns_bak1`
- `[l2tp_tunnel0] l2tp_bak1_subnet`
- `[l2tp_tunnel0] l2tp_lns_bak2`
- `[l2tp_tunnel0] l2tp_bak2_subnet`
- `[l2tp_tunnel0] l2tp_lns_bak3`
- `[l2tp_tunnel0] l2tp_bak3_subnet`

作用：

- 固化主 L2TP 接入点
- 固化备 L2TP 接入点
- 固化 PPP 账号密码

### 2. `modem/gprs_monitor/options.l2tpd.client.tieta`

建议改这些字段：

- `name`
- `password`

建议保留：

- `noauth`
- `noccp`
- `mtu`
- `mru`

说明：

- `noauth` 是本地 `pppd` 不要求对端认证，不等于取消客户端提交账号密码
- 当前批量方案仍建议保留 PPP 认证，只是把凭据和 LNS 接入面改成自有体系

### 3. `modem/gprs_monitor/tt_proxy.ini`

建议改这些字段：

- `[servers] server`

示例：

```ini
[servers]
server=192.168.100.123:10378,192.168.100.124:10378
```

作用：

- 固化 `tt_proxy` 的主上送目标
- 让业务数据直接进入自有 `UDP/10378` 接收端

### 4. `disaster.ini`

建议改这些字段：

- `disaster_recovery_server_ip`
- `disaster_recovery_subnet`
- `disaster_recovery_l2tp_lns`
- `disaster_recovery_l2tp_subnet`
- `disaster_recovery_l2tp_lns_bak1`
- `disaster_recovery_l2tp_bak1_subnet`
- `disaster_recovery_name`
- `disaster_recovery_password`

说明：

- `update_gprs_monitor.sh` 会根据省份码，从 `disaster.ini` 读取灾备字段并写入实际 `gprs_monitor.ini`
- 如果只改主模板、不改 `disaster.ini`，后续设备切灾备时仍可能回到原铁塔侧配置

## 不建议首轮改动的内容

这些内容首轮建议保持不动：

- `monitor_type`
- `start_gprs`
- `start_l2tp.sh`
- `gprs_monitor`
- `tt_proxy`
- `ttb.so`
- Web CGI 程序

理由：

- 这些部分属于运行逻辑或协议实现层
- 当前没有必要为了批量上线去承担额外回归风险

## 升级包改造方法

建议生成一个新的输出目录，不直接覆盖原始包。

已提供改包脚本：

- [patch_estoneii_update.py](/C:/Users/Administrator/Desktop/fsu-platform/backend/scripts/patch_estoneii_update.py)

### 脚本能力

- 复制原始升级包目录到新目录
- 修改外层 `modem/gprs_monitor/*` 配置文件
- 解包并重打 `update.tar.gz`
- 修改包内：
  - `modem/gprs_monitor/gprs_monitor.default.ini`
  - `modem/gprs_monitor/options.l2tpd.client.tieta`
  - `modem/gprs_monitor/tt_proxy.ini`
  - `disaster.ini`
- 自动重算 `tar.md5`

### 示例命令

```powershell
python backend/scripts/patch_estoneii_update.py `
  --input-dir "C:\Users\Administrator\Desktop\单站远程升级工具20221012D\单站远程升级工具20221012D\Update\eStoneII" `
  --output-dir "C:\Users\Administrator\Desktop\eStoneII-custom" `
  --server-ip "192.168.100.123" `
  --server-subnet "192.168.100.0/24" `
  --l2tp-lns "192.168.100.123" `
  --l2tp-subnet "10.45.0.0/16" `
  --l2tp-lns-bak1 "192.168.100.124" `
  --l2tp-bak1-subnet "10.46.0.0/16" `
  --ppp-name "ttcw2015" `
  --ppp-password "ttcw@2015" `
  --ttproxy-server "192.168.100.123:10378,192.168.100.124:10378"
```

如果只想改特定省份段，可以补：

```powershell
--disaster-sections "51,52"
```

## 建议上线顺序

### 第一步：单机验证

- 用定制包刷 1 台设备
- 验证能否正常升级、重启、拨号
- 验证是否向自有 `LNS` 发起 `L2TP`
- 验证是否向自有 `UDP/10378` 发业务包

### 第二步：小批量验证

- 选 3 到 5 台同型号设备
- 验证不同运营商、不同站点环境下是否一致
- 验证主备 LNS 切换
- 验证掉线重连和断电恢复

### 第三步：固化量产包

- 固化版本号和出厂配置
- 留一份“回铁塔原配置”的回滚包
- 形成正式交付流程

## 回滚建议

批量改造必须同步保留：

- 原始升级包
- 定制升级包
- 回滚升级包

最小回滚策略：

- 只回滚这 4 个配置文件
- 不碰二进制

这样风险最低，也最适合批量运维。

## 当前工程建议

当前最合理的固件路线是：

1. 先用配置模板改包跑通 1 台
2. 抓到真实 `tt_proxy -> UDP/10378` 首包
3. 再决定是否有必要继续改 `tt_proxy` 或 `ttb.so`

在没有抓到真实 `10378` 首包之前，不建议继续深入二进制补丁路线。
