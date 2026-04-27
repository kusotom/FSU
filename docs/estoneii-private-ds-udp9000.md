# eStoneII SiteUnit DS UDP/9000 私有协议解析

本文记录维谛/AMS eStoneII `SiteUnit` 在进入 B 接口 SOAP 通讯前，向 DS/SC 地址发送的私有 UDP/9000 前置报文。

当前结论基于设备 `192.168.100.100` 指向平台 `192.168.100.123:9000` 后的实测抓包，以及固件 `SiteUnit` 字符串分析。

## 协议层次

设备里同时存在两层协议：

- B 接口业务层：`http+soap+xml`，路径为 `http://<SC>:<port>/services/SCService`，业务命令包括 `LOGIN`、`LOGIN_ACK`、`GET_DATA`、`SEND_ALARM` 等。
- DS 私有前置层：UDP/9000，帧头以 `6d7e` 开头。固件字符串包括 `LogToDS`、`LoginToDSC`、`GetServiceAddr`、`LogToDS return`，说明该层用于注册或获取服务地址，成功后设备才进入 SOAP `LOGIN`。

因此，抓到的 `6d7e...` 包不是 SOAP 正文，而是 SOAP 之前的私有握手。

## 已解析帧头

帧头固定 24 字节：

| 偏移 | 长度 | 示例 | 说明 |
|---:|---:|---|---|
| `0x00` | 2 | `6d 7e` | magic，ASCII 为 `m~` |
| `0x02` | 1 | `f6` | 序号，设备重发时递增 |
| `0x03` | 1 | `00` | 保留 |
| `0x04` | 2 | `11 00` | 小端命令号，当前实测为 `0x0011` |
| `0x06` | 14 | `46 ff 00 00 00 00 c1 62 00 2d 00 00 00 00` | 固定/会话字段，当前抓包稳定 |
| `0x14` | 2 | `dd 00` | 小端 body 长度，等于总长减 24 |
| `0x16` | 2 | `04 3b` | 小端校验和 |
| `0x18` | N | body | 私有业务体 |

校验和算法：

```text
checksum = sum(packet[2:22] + packet[24:]) & 0xffff
```

也就是跳过 magic 和校验字段本身，对序号、命令、固定字段、body 长度以及 body 求 16 位低位累加。

## 已解析 body

以 245 字节抓包为例，body 长 221 字节：

| body 偏移 | 长度 | 说明 |
|---:|---:|---|
| `0x00` | 32 | `token_a`，32 字节十六进制风格字符串 |
| `0x20` | 1 | `00` 分隔 |
| `0x21` | 32 | `token_b`，32 字节十六进制风格字符串 |
| `0x41` | 32 | ASCII `0` 填充 |
| `0x61` | 4 | 小端 Unix 时间戳 |
| `0x65` | 1 | 地址数量，当前为 `4` |
| `0x66` | 变长 | 地址列表 |

地址列表当前解析规则：

- 第 1 项：`type, reserved, length, value`
- 后续项：`type, length, value`

已知 type：

| type | 说明 | 示例 |
|---:|---|---|
| `0x00` | 主 UDP 服务地址 | `udp://192.168.100.100:6002` |
| `0x01` | 备用 UDP 服务地址 | `udp://192.168.100.100:6002` |
| `0xff` | fallback UDP 地址 | `udp://192.168.100.100:6002` |
| `0x14` | FTP 地址 | `ftp://root:hello@192.168.100.100` |

设备刚启动时可能先上报 `[dhcp]:6002` 形态，随后变为实际地址 `192.168.100.100:6002`。

## 实测样例

245 字节样例：

```text
magic=6d7e
seq=246
cmd=17
body_length=221
checksum=0x3b04 valid=true
token_a=c43c8b4f49cf47e19c3019534f189225
token_b=bf75a09e781b4ceba4b14705f7db6abd
time=2026-04-26T22:34:18Z
addr[0]=primary_udp udp://192.168.100.100:6002
addr[1]=secondary_udp udp://192.168.100.100:6002
addr[2]=fallback_udp udp://192.168.100.100:6002
addr[3]=ftp ftp://root:hello@192.168.100.100
```

## 回包实验状态

已验证无效或未推进到 SOAP 的模式：

- 不回包：设备持续重发私有握手。
- 原包 echo：设备仍持续重发。
- 只回 22 字节 prefix：长度/校验不完整，设备不接受。
- 合法 24 字节空 ACK，cmd=17：设备仍持续重发。
- 合法 24 字节空 ACK，cmd=18：设备仍持续重发。
- 合法 `status-u32-ack`，body 为 `01 00 00 00`：设备仍重发 `cmd=17`。
- 合法 `service-list-ack`，body 为 `status + URL`：设备仍重发 `cmd=17`。
- 合法 `ds-address-table-ack`，body 为 `u16le(table_len) + type/len/url...`：校验和通过，设备不再报 `fail checksum`，但仍未进入平台 HTTP 捕获；后续反汇编确认这里少了开头的返回码字节。

结论：设备需要“带有效 body 的成功/服务地址响应”，仅有合法帧头不够。

固件反汇编里 `GetServiceAddr` 一段更像是在解析“服务地址表”：

- body 第 1 字节是返回码，代码分支会检查 `0/1/2`；实测分支含义为 `0=Success`、`1=Fail`、`2=UnRegister`。
- 返回码后 2 字节是地址表长度，小端读取。
- 后面循环读取 `type, length, value`。
- `value` 预期为 `udp://ip:port`，解析时会跳过前 6 个字符，再按 `:` 拆分 IP 和端口。
- type `0,5,6,7,8,9` 分别置位，成功条件疑似要求掩码达到 `0x3f`。
- 因此当前候选应答为 `ds-address-table-ack --ds-table-status-byte 0 --ds-service-types 0,5,6,7,8,9 --ds-url udp://192.168.100.123:9000`。

为了快速验证字段差异，脚本已支持这些变体参数：

- `--reply-command-mode same|increment|zero`
- `--reply-seq-delta <n>`
- `--reply-header3 0xNN`
- `--ds-table-status-byte 0xNN`
- `--ds-table-length-endian little|big|none`
- `--ds-table-include-count`

2026-04-27 重启联调进一步确认：

- `XML.log` 在 `12:03:03` 生成了新的 `[Send CMD:LOGIN]`，但平台 HTTP `80/8000` 没收到连接。
- 同时监听 `UDP/9000` 和 `UDP/7000` 后，发现后续业务/状态通道不走 HTTP，而是继续走私有 UDP。
- `UDP/7000` 收到固定 30 字节包，命令号 `0x8011`，body 长 6，形态为 `00 + unix_time_le + 00`，校验按 `cmd=17` 同一算法成立。
- `UDP/9000` 同时收到 24 字节 `cmd=0x001f`，无 body；其校验与 `cmd=17` 算法不同，当前观察为普通求和再排除一段 `c1 62 00 2d` 后匹配。
- 对 `cmd=0x8011` 和 `cmd=0x001f` 做原包 echo 后，设备仍持续发送，说明短心跳还需要专用 ACK 格式。

设备日志里出现过：

```text
[Run] LoginToDSC Result[1]
[LoginToDSC]Login to Dsc timeout(3600 seconds),recreate socket!
```

这说明私有 DS 层存在被设备认为成功的路径，但成功后还需要继续接住后续 SOAP/数据服务连接，否则最终仍会超时重建 socket。

解析和实验工具：

```powershell
python backend\scripts\ds_udp9000_responder.py --decode-file backend\logs\ds-udp9000\<capture>.bin

python backend\scripts\ds_udp9000_responder.py --port 9000 --reply-mode none --verbose
python backend\scripts\ds_udp9000_responder.py --port 9000 --reply-mode status-u32-ack --reply-status 1 --verbose
python backend\scripts\ds_udp9000_responder.py --port 9000 --reply-mode service-list-ack --sc-url http://192.168.100.123:8000/services/SCService --verbose
python backend\scripts\estoneii_sc_lab.py --duration 90 --udp-ports 9000,7000 --http-ports 80,8000 --reply-mode ds-address-table-ack --ds-table-status-byte 0 --ds-url udp://192.168.100.123:9000 --ds-service-types 0,5,6,7,8,9
python backend\scripts\estoneii_sc_lab.py --duration 120 --udp-ports 9000,7000 --http-ports 80,8000 --reply-mode ds-session-ack --reply-status 0
```

这些模式会自动生成 `6d7e` 帧头、body 长度和校验和。

## 与 SOAP B 接口的关系

固件内已确认以下业务字符串：

- `http://%s:%d/services/SCService`
- `LOGIN`
- `LOGIN_ACK`
- `RightLevel`
- `DataSCIP`
- `SCIP`
- `GET_DATA`
- `SEND_ALARM`

平台侧应在 DS 私有握手成功后，准备接收 HTTP SOAP：

```text
POST /services/SCService
Content-Type: text/xml; charset=utf-8 或 application/soap+xml
```

`LOGIN_ACK` 至少应返回：

```xml
<Response>
  <PK_Type>
    <Name>LOGIN_ACK</Name>
    <Code>102</Code>
  </PK_Type>
  <Info>
    <RightLevel>2</RightLevel>
    <SCIP>192.168.100.123</SCIP>
  </Info>
</Response>
```

当前阻塞点在 UDP/9000 私有回包 body 格式，解析器已能稳定解请求包并生成校验正确的候选回包。

实测 `XML.log` 已经看到设备生成了 `LOGIN`：

```text
[Send CMD:LOGIN]
FsuId=51051243812345
FsuCode=51051243812345
FsuIP=192.168.100.100
VpnMode=0 LoginIP=192.168.100.123
```

因此后续联调需要同时启动两类服务：

- UDP/9000 DS 私有响应器，用于通过 `LoginToDSC/LogToDS`。
- HTTP SOAP `SCService`，用于接收设备发出的 `LOGIN` 并返回 `LOGIN_ACK`。

## 2026-04-27 DS 注册与心跳确认

反汇编 `SiteUnit` 后确认，外层帧除了 `cmd` 外，还使用包头 offset `6` 作为业务分发码：

- `0x46`：设备发出的 `GetServiceAddr/LogToDS` 请求。
- `0x47`：平台返回的 `GetServiceAddr` 应答。
- `0xd2`：设备发出的心跳请求。
- `0xd3`：平台返回的心跳应答。

`GetServiceAddr` 应答 body 结构为：

```text
u8     status        # 0=Success, 1=Fail, 2=UnRegister
u16le  entry_count   # 不是字节长度
repeat entry_count:
  u8   service_type
  u8   url_length
  bytes url           # 例如 udp://192.168.100.123:9000
```

成功掩码要求返回 `0,5,6,7,8,9` 六类服务地址。实测有效 ACK：

```text
cmd=0x8011
header[6]=0x47
body=00 06 00 + entries(type/len/url...)
```

设备日志确认：

```text
[GetServiceAddr] LogToDS return [0]: Success
[StationName= ...]Register OK!
```

心跳 ACK 结构：

```text
cmd=0x8011
header[6]=0xd3
body=<request_body[1:5]>   # 4 字节 Unix 时间戳，小端
```

### 全量通信状态上报 ACK

注册成功后约 3 分钟，设备会触发 `SendAllCommState`。抓包显示该阶段发出 51 字节私有帧：

```text
cmd=0x8010
header[6]=0x2b
body_length=27
```

如果平台不回包，设备每约 10 秒重发一次，30 秒后日志出现 `SendAllCommState Failed!`。

反汇编 `SiteUnit` 后确认，这类高位命令帧需要短 ACK。有效 ACK 为复制请求头并改写：

```text
cmd=0x001f
header[6]=0x2b
body_length=0
checksum=重新计算
```

实测 `2026-04-27 14:52:03`，平台对 `0x8010/0x2b` 连续 3 个包回 `24` 字节短 ACK 后，设备日志变为 `SendAllCommState Success!`。

脚本入口：

```powershell
python backend\scripts\estoneii_sc_lab.py --duration 300 --udp-ports 9000,7000 --http-ports 80,8000 --reply-mode estoneii-ds-ack --ds-table-status-byte 0 --ds-url udp://192.168.100.123:9000 --ds-service-types 0,5,6,7,8,9
```

这个模式已经能让设备进入 `Register OK`，并在监听期间持续响应 DS/RDS 心跳。监听停止后设备会在下一轮心跳超时后重新 `LogToDS`，这是预期行为。

## 落地接入守护进程

`estoneii_sc_lab.py` 仍用于实验和抓包。正式接入入口使用：

```powershell
python backend\scripts\estoneii_ds_gateway.py --ds-url udp://192.168.100.123:9000 --udp-ports 9000,7000
```

默认行为：

- 长期监听 `UDP/9000,7000`。
- 复用 `estoneii-ds-ack`，处理 GetServiceAddr、DS/RDS 心跳、`SendAllCommState`。
- 将事件追加写入 `backend/logs/estoneii-ds-gateway/events.jsonl`。
- 使用 `--capture-packets` 可同时保存每个包的 `.bin/.json` 明细，便于继续逆向业务帧。
- 使用 `--duration-seconds 600` 可做限时验收；默认 `0` 为常驻运行。

事件流当前至少包含：

```text
ds_get_service_addr
ds_heartbeat
ds_short_ack
send_all_comm_state
```

下一步落地点是把该 JSONL 事件流或守护进程内的事件处理器接入平台数据库，并继续解析实时数据、历史数据、告警、控制等业务帧。
