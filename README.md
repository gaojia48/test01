# Linux Ops Agent

Linux Ops Agent 是一个面向 Linux 运维场景的诊断与文本解读工具。项目会自动读取 `.env` 或环境变量中的 `DEEPSEEK_API_KEY`；如果存在 API Key，默认启用 DeepSeek 云端增强，否则使用内置的本地运维模型完成意图识别、skill 推荐、日志/命令输出解读。

## 三层能力

1. 自然语言 skill 层
   - 用户输入自然语言问题，系统通过关键词或 DeepSeek 选择已登记的 skill。
   - skill 只会执行 `skills/*.yaml` 中声明的脚本。
   - 新增 `auto_inspect` 自动巡检 skill，用于一次性采集系统、磁盘、进程、网络、服务、日志和登录线索。

2. 本地运维模型层
   - 内置规则化语义模型，识别磁盘、日志、权限、端口、网络、OOM、Nginx upstream、SSH 爆破等运维信号。
   - 能从大段描述中抽取症状、对象、证据、风险级别和建议 skill。
   - 没有配置 API Key 时不调用 DeepSeek。

3. DeepSeek 可选增强层
   - 默认会读取 `.env` 或环境变量中的 `DEEPSEEK_API_KEY`；如果存在 API Key，系统会自动启用 DeepSeek。
   - 如果没有 API Key，系统自动使用本地运维模型。
   - 可以使用 `--no-llm` 强制禁用 DeepSeek，也可以使用 `--cloud-llm` 强制尝试云端增强。
   - 大模型不能返回任意 Shell 命令让系统执行。

4. 运维文本解读层
   - 支持分析大量日志、命令输出、报错信息、配置片段、事故聊天记录。
   - 默认根据 API Key 自动选择 DeepSeek 或本地运维模型生成中文诊断报告。
   - 需要强制本地分析时可以加 `--no-llm`。

## 内置 Skills

- `auto_inspect`：自动巡检系统关键状态。
- `disk_check`：检查磁盘空间、inode、日志目录占用和大文件。
- `log_analyze`：分析系统日志、SSH 登录失败和高频错误。
- `process_check`：检查 CPU、内存、负载和高占用进程。
- `network_check`：检查网络地址、路由、监听端口和连通性。
- `health_report`：生成综合巡检报告。

## 安装

```bash
cd linux-ops-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`：

```text
DEEPSEEK_API_KEY=你的key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

没有 API Key 也可以完整运行，系统默认使用本地运维模型。

## 使用

进入交互模式：

```bash
./ops
```

自然语言执行 skill：

```bash
python main.py "检查磁盘空间问题"
python main.py "分析最近 SSH 登录失败"
python main.py "做一次自动巡检和系统体检"
```

直接执行指定 skill：

```bash
python main.py --skill auto_inspect
python main.py --skill disk_check
python main.py --report daily
```

查看 skills：

```bash
python main.py --list-skills
```

## 文本、日志和命令输出解读

分析日志文件：

```bash
python main.py --analyze-file nginx-error.log --analysis-type log
```

分析一段报错：

```bash
python main.py --analyze-text "bind() to 0.0.0.0:80 failed (98: Address already in use)" --analysis-type error
```

从管道读取命令输出：

```bash
journalctl -u nginx --since "1 hour ago" --no-pager | python main.py --analyze-stdin --analysis-type log
```

禁用 DeepSeek，只使用本地规则：

```bash
python main.py --analyze-file app.log --analysis-type log --no-llm
```

强制启用 DeepSeek 云端增强：

```bash
python main.py --analyze-file app.log --analysis-type log --cloud-llm
```

分析报告会保存到 `reports/` 目录。

## 静态 HTML 报告中心

项目支持生成不需要端口的静态 UI：

```bash
python main.py --export-html
```

生成文件：

```text
reports/index.html
```

每次文本分析或 skill 报告生成后，系统也会自动更新这个文件。可以通过 MobaXterm 左侧文件栏下载或打开 `reports/index.html`，在本机浏览器中查看报告中心。

报告中心包含：

- 最新报告高亮
- 历史报告列表
- 搜索框
- 严重程度标签
- 分析引擎标签
- 演示日志样例
- 常用命令

这种方式不需要 Web 服务、不需要安全组、不需要 SSH 隧道。

## 测试

```bash
python -m unittest discover -s tests
```

如果安装了 `pytest`：

```bash
pytest
```

在 Linux 或安装了 bash 的环境中，还可以直接验证脚本：

```bash
bash scripts/auto_inspect.sh
bash scripts/disk_check.sh
bash scripts/log_analyze.sh
```

## 安全设计

- 只执行 `skills/*.yaml` 中登记的脚本。
- 脚本必须位于 `scripts/` 目录。
- 默认拒绝高风险 skill。
- 每次脚本执行都有超时限制。
- 不执行大模型动态生成的任意 Shell 命令。
- 文本分析只做诊断和建议，不直接修改系统。
