# AromaNexus

[![CI](https://github.com/rastagan-git/AromaNexus/actions/workflows/ci.yml/badge.svg)](https://github.com/rastagan-git/AromaNexus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

[English](README.md) · **简体中文**

一套重视数据来源追踪的化学—感官数据整理工具：把化合物工作簿扩充为可核查、可继续分析的数据表。

AromaNexus 将化学身份、气相色谱保留指数、气味描述、阈值，以及可选的嗅觉受体实验结果串联起来。它会保留原始表格，规范化不同来源的结果，并记录每项扩充数据来自哪里。输出可作为后续统计分析、化学信息学与边界清晰的机器学习实验输入。

```text
XLSX / CSV / TSV
      │
      ▼
验证标识符 ──► 带缓存的数据源适配器 ──► 规范字段 + 来源记录
                                                │
                                                ▼
                                      新的、便于分析的数据表
```

## 这次升级带来了什么

原有四套工作簿脚本仍然保留，同时新增了统一 CLI：

- 严格验证 CAS，并明确标记名称匹配歧义；
- 默认记录状态、来源 URL、获取时间、缓存、版本、许可链接和诊断信息；
- 使用保守的访问间隔、有限重试与持久缓存；
- 原子写入、定期生成恢复检查点，默认不覆盖已有文件；
- 在原有 NIST、MFFI、ChemicalBook 流程之外，增加 PubChem、Pyrfume 与 M2OR 扩充。

## 安装

需要 Python 3.11 或更高版本。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

### macOS 或 Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

安装后先确认版本并查看所有数据源的访问模式：

```bash
aromanexus --version
aromanexus sources
```

## 快速开始

CLI 支持 `.xlsx`、`.csv` 和 `.tsv`。列名均可修改；下面使用默认列名。

```bash
# 规范化身份、理化性质、同义词、CAS 标识符与带来源的气味文本
aromanexus pubchem compounds.xlsx --identifier-column "CAS Number"

# 在名称查询前跳过当前数据集中的结构标签
aromanexus pubchem compounds.xlsx --identifier-column "Name" --skip-pattern '^C\d+$'

# 在 NIST 中寻找最接近实验计算值的保留指数
aromanexus nist-ri data.xlsx \
  --cas-column "CAS Number" \
  --calculated-ri-column "Calculated RI"

# 通过 NIST WebBook 将化合物名称解析为 CAS
aromanexus resolve-cas names.xlsx --name-column "Name"

# 查询选定的 Pyrfume 集合；缺少 CID 时会通过 PubChem 解析
aromanexus pyrfume compounds.xlsx --archives aromadb,superscent

# 可选的分子—嗅觉受体实验依据
aromanexus m2or compounds.xlsx --cas-column "CAS Number"

# 需要交互浏览器的兼容数据源
aromanexus mffi compounds.xlsx --cas-column "CAS Number"

# 设有许可门槛的旧版数据源；命令会要求明确确认
aromanexus chemicalbook-legacy compounds.xlsx --cas-column "CAS Number"
```

在 PowerShell 中，请把多行命令写成一行，或将 Bash 的 `\` 续行符换成 PowerShell 的反引号。

## 命令一览

| 命令 | 默认输入列 | 用途 | 默认输出后缀 |
| --- | --- | --- | --- |
| `aromanexus sources` | 无 | 列出数据源、用途和访问方式；`providers` 是别名。 | 无 |
| `aromanexus nist-ri INPUT` | `CAS Number`、`Calculated RI` | 在原流程指定的 NIST 非极性柱、自定义升温 RI 表中匹配最接近值。 | `_nist_result` |
| `aromanexus resolve-cas INPUT` | `Name` | 通过 NIST 将无歧义的化合物名称解析为 CAS Registry Number。 | `_with_cas` |
| `aromanexus pubchem INPUT` | `CAS Number` | 添加 CID、名称、结构标识符、选定性质、同义词、CAS 标识符和带来源的气味注释。 | `_pubchem` |
| `aromanexus pyrfume INPUT` | `PubChem CID`；若需解析 CID，则用 `CAS Number` | 匹配白名单内的固定版本档案：`aromadb`、`flavornet`、`superscent`；默认 `aromadb,superscent`。 | `_pyrfume` |
| `aromanexus m2or INPUT` | `CAS Number` | 汇总分子—受体配对、响应配对、物种、人类响应受体和研究 DOI。 | `_m2or` |
| `aromanexus mffi INPUT` | `CAS Number` | 通过可见 Chrome 获取中英文名、感官特征和水中阈值；确认不需要交互时才使用 `--headless`。 | `_mffi_result` |
| `aromanexus chemicalbook-legacy INPUT` | `CAS Number` | 保留原有气味、阈值和香型交互流程；在确认有书面许可前禁用。 | `_cb_result` |

使用 `aromanexus COMMAND --help` 查看列名及数据源专用选项。全局参数必须写在子命令之前：

```bash
aromanexus --cache-dir .cache/aromanexus --timeout 30 pubchem compounds.xlsx
```

### 输出、检查点与覆盖保护

所有表格命令默认在输入文件旁生成新文件，保留原有行序和列，再添加数据源字段。例如，PubChem 会将 `compounds.xlsx` 输出为 `compounds_pubchem.xlsx`。

默认来源记录包括数据源状态、来源 URL、获取时间、是否命中缓存、固定版本、许可 URL 与诊断信息。PubChem 会单独报告 CAS 解析状态；仅当输入 CAS 得到确认，或只剩一个校验有效的候选时，才填入 `Resolved CAS`。多个或缺失候选会保持未解析。只有在确实需要旧版形状时才使用 `--no-provenance`。

```bash
# 明确指定输出位置
aromanexus pubchem compounds.xlsx --output results/compounds_enriched.xlsx

# 每处理 10 行保存一次恢复检查点；设为 0 可关闭
aromanexus pubchem compounds.xlsx --checkpoint-every 10

# 明确覆盖一个已存在的目标文件
aromanexus pubchem compounds.xlsx --output compounds_pubchem.xlsx --force
```

检查点形如 `compounds_pubchem.partial.xlsx`：运行期间定期刷新，中断后保留，最终文件写入成功后删除。若目标文件已存在，命令会停止，除非显式传入 `--force`。建议输出到新文件，不要直接覆盖输入。

成功的 HTTP 响应与下载快照默认缓存到 `~/.cache/aromanexus`。如需更改位置，可设置 `AROMANEXUS_CACHE_DIR`，或在子命令之前传入 `--cache-dir`；更名前的缓存环境变量仍可兼容使用。

## 数据来源、访问方式与权利边界

访问规则与数据条款可能变化。正式抓取、发表或再分发前，请重新检查下列官方页面。本仓库不会替第三方数据授予使用权。

| 数据源 | 本工具使用的数据 | 访问与缓存方式 | 权利与科学边界 |
| --- | --- | --- | --- |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) + [PUG-View](https://pubchem.ncbi.nlm.nih.gov/docs/pug-view) | 化合物身份、选定性质、同义词/CAS 标识符，以及带贡献者来源的气味注释 | 调用 NCBI 在线 API 并持久缓存响应。未缓存请求间隔为 0.25 秒，即每秒 4 次，低于 PubChem 的每秒 5 次上限；瞬时失败只进行有限重试。 | PubChem 汇集不同贡献者记录。输出保留注释来源名、来源 URL 和许可 URL；请同时检查 [NCBI 政策](https://www.ncbi.nlm.nih.gov/home/about/policies/)及各贡献者条款。 |
| [NIST Chemistry WebBook，SRD 69](https://webbook.nist.gov/chemistry/) | 保留指数查询、名称解析 CAS | HTML 持久缓存；未缓存请求之间至少间隔 5 秒，遵守公开的 [robots.txt](https://webbook.nist.gov/robots.txt)。 | 适用 [NIST Standard Reference Data 权利规定](https://www.nist.gov/srd/public-law)。应按需获取并引用，不要把该服务当作可自由再分发的批量数据集。 |
| [Pyrfume Public Data Archive](https://github.com/pyrfume/pyrfume-data) | 以 PubChem CID 为键、固定版本的 `aromadb`、`flavornet` 与 `superscent` 文件 | 仅允许显式列出的档案；从固定提交下载选定文件并在本地缓存。 | 权利以**每个 manifest 和上游集合**为准。仓库代码的许可证不会自动覆盖每一份数据；输出会保留 manifest 的来源、备注与许可说明。 |
| [M2OR](https://github.com/chemosim-lab/M2OR) | 分子—嗅觉受体配对、响应标签、物种、受体和 DOI | 可选的固定版本 CSV 快照，约 43 MB；首次使用时下载并缓存，本仓库不捆绑该文件。 | 上游快照采用 Apache-2.0。这些是生物测定结果，不代表人的感知质量、安全性、疗效或临床结局。 |
| [MFFI](https://mffi.sjtu.edu.cn/database/search) | 中英文名、感官特征和水中阈值 | 通过 Selenium/Chrome 交互访问，并使用保守的逐行间隔。目前未发现公开且有文档的 API 或速率政策。 | 目前未发现明确的再利用许可证。网页可访问或 robots 允许访问，并不等于获得再发布许可；请保守使用并引用来源。 |
| [ChemicalBook](https://www.chemicalbook.com/) | 旧版气味描述、嗅觉阈值和香型兼容流程 | **默认禁用，并设有许可门槛。**当前 [robots.txt](https://www.chemicalbook.com/robots.txt) 排除了搜索及属性页面路径。连接器保持可见和手动，不会破解或绕过 CAPTCHA。 | 只有在书面许可明确覆盖所需自动访问与再利用时才能运行。`--i-have-permission` 是操作者自己的声明，不代表本项目提供了许可。 |

## Codex 项目 Skill

仓库内置了项目级 Skill：`.agents/skills/curate-aroma-data/`。在 Codex 中可直接调用：

```text
$curate-aroma-data
```

该 Skill 会检查工作簿、选择满足需求的最小数据源组合、预览访问及输出影响、执行一个聚焦命令，并核对行数、结构、状态和来源记录。它只是本软件包之上的流程编排指南，不是另一套爬虫，也不会自动赋予数据使用权。

也可以直接运行其中只读的工作簿检查工具：

```bash
python .agents/skills/curate-aroma-data/scripts/inspect_workbook.py compounds.xlsx
```

## 旧版兼容入口

更名前的 `flavor-data` 命令与 `flavor_data_crawler` Python 命名空间继续作为兼容别名。新集成建议使用 `aromanexus`，现有自动化无需立刻重写。

原有脚本与 Windows 启动器仍然保留，继续支持固定的工作簿布局：

| 启动器 | 脚本 | 预期工作簿 | 必需列 | 输出 |
| --- | --- | --- | --- | --- |
| `start1.bat` | `nist_excel_tool.py` | `data.xlsx` | `CAS Number`、`Calculated RI` | `data_result.xlsx` |
| `start2.bat` | `name_to_cas.py` | `name.xlsx` | `Name` | `name_with_cas.xlsx` |
| `start3.bat` | `mffi_spider.py` | `max.xlsx` | `CAS Number` | `max_mffi_result.xlsx` |
| `start4.bat` | `cb_spider.py` | `Odor.xlsx` | `CAS Number` | `Odor_cb_result.xlsx` |

`.bat` 会依次寻找 `.venv`、`myenv`、`venv`，最后才使用系统 `python`。兼容脚本会刻意生成不含来源列的旧版结果，并覆盖固定名称的结果文件；新任务建议使用 CLI，以获得明确路径与覆盖保护。MFFI 和 ChemicalBook 需要本机可用的 Chrome，ChemicalBook 仍会要求输入许可确认短语。

## 开发与测试

安装开发依赖后，运行离线测试和代码检查：

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

CI 会在 Ubuntu 与 Windows 上使用 Python 3.11 和 3.13 执行上述检查。测试通过固定样例或注入客户端运行，不依赖实时网站，也不依赖 Codex 运行环境。

## 负责任地使用

- 针对你的具体用途核对数据源条款、robots 规则、引用要求和再分发权利。
- 保持保守请求频率，优先使用缓存。
- 不得绕过 CAPTCHA、身份验证、付费墙或其他访问控制。
- 将 `not_found`、`invalid_input`、`http_error`、`network_error`、`parse_error`、`missing_data`、`data_error`、`partial`、`blocked` 和 `skipped` 视为不同结果。
- 在统计、化学信息学或机器学习工作中使用前，核对来源记录与生物学适用范围。

## 许可证

AromaNexus 的源代码与原创文档采用 [MIT License](LICENSE) 授权。

该许可证不会授予任何第三方数据集、网站内容、数据源响应或生成数据集的使用权。
通过 PubChem、NIST、Pyrfume、M2OR、MFFI、ChemicalBook 或其他来源取得的
数据，仍分别受各来源适用的条款、许可证及使用限制约束。
