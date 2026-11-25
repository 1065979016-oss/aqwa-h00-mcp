# 原生 AQWA 求解（可选）

这是专用于同一 H00 基准的原生求解入口，不是通用 AQWA 工程导入器，也不运行 Workbench 网格生成或重建 LINE 数据库。

## 1. 配置本机路径

Windows PowerShell 示例，路径是占位符，换成你自己的实际路径。若 MCP 客户端不继承当前环境，把对应变量设置在该客户端的服务器配置中。

```powershell
$env:AQWA_MCP_EXE = '<your-Aqwa.exe-absolute-path>'
$env:AQWA_MCP_INPUTS = '<your-private-H00-bundle-absolute-directory>'
# 可选，使用自己的现有工作区；不设置则输出到仓库 .aqwa-runs/
$env:AQWA_MCP_RUNS = '<your-results-directory>'
python -B mcp_server.py
```

最后一个命令在等 MCP 客户端发送消息，并不是直接求解。实际连接时由 MCP 客户端启动它。需要本地许可可用，并使用可信的求解器路径和私有输入。

## 2. 自备匹配的 H00 输入

将有权使用的输入复制到 `AQWA_MCP_INPUTS`，按下表命名（不改二进制内容或换行）。版本使用固定 H00 指纹，不能换成任意工程；可在 [aqwa_profile.py](aqwa_profile.py) 查验。边界 LINE 输入在运行前对比非频率卡片与宽频输入是否一致。

| 目录中的文件 | 对应原生文件 |
| --- | --- |
| `wide.dat`, `wide.lis`, `wide.hyd`, `wide.res` | 同一 19 点宽频 AQWA-LINE 的输入、日志、HYD 和 RES |
| `edge.dat` | 配套边界频点 AQWA-LINE 输入 |
| `base.dat` | H00 三缆、8 m/s 平均风工作点的原生 AQWA-FER 模板 |
| `equilibrium.eqp`, `equilibrium.lis` | 同一工作点的平衡文件与原生 AQWA-LIBRIUM 日志 |

这些文件不随公开版发布。没有匹配的输入时，使用离线演示即可，不要用改指纹或篡改日志的方法强行运行。

## 3. 通过 MCP 运行

1. 调用 `preview_h00_full_sea_batch`，传入 `{"cases": [...工况...]}`。可用 [examples/sea_states.json](examples/sea_states.json) 的海况规格，若实际做研究需替换为有依据的海况。源码会校验输入参数、原生数据文件及频带。
2. 调用 `start_h00_full_sea_batch`，传入同一 `cases`，另将预检返回的 `preview_sha256` 填入 `expected_preview_sha256`。
3. 以返回的 `batch_id` 查询 `get_h00_full_sea_batch`。同一批次内一次启动一组；不同批次请勿并发占用同一个许可席位。只在能确认上一个任务已结束时重新提交。
4. 之后调用 `read_h00_full_sea_batch`。按返回路径打开 HTML 和 JSON。若部分工况未通过频带预检，批次会显示部分完成，不把它当作求解失败，也不生成该组响应。两个已接受的演示海况需完成网格频率和积分频带对照，不自动外推。
