# memtruth

`tracemalloc` 报的是「Python 分配器被请求了多少字节」，`/proc` 里的 RSS 报的是「内核真正驻留了多少页」。这两个数在真实代码里可以差出两个数量级，而多数内存结论只引用前者。`memtruth` 把三件事放进同一次隔离测量：traced 峰值、**关闭 profiling** 时的 RSS 峰值、**开启 profiling** 时的 RSS 峰值，并对每条分配路径判定「谁偏了、偏多少」。

Upstream: none

本仓库是原创测量工具，不含上游补丁，也没有修改任何第三方库。任务书里的 G1–G5（上游测试绿 / 差分一致 / 中位加速 / 大规模不退化 / RSS 不退化）**不适用**：这里没有「优化后更快」的声明。替代物是第 2 节的可复现实测、第 3 节的 33 个测试与第 4 节的 CI 闸门。

## 1 · 它回答什么问题

- 我引用的 `tracemalloc` 峰值，能当成进程内存成本吗？（11 条路径里 7 条能；2 条低估到 0.50x/0.51x；2 条 RSS 低于噪声地板而 traced 报了 32–64 MiB）
- 打开 `tracemalloc` 本身会让进程多占多少？（本机实测最多 **+76.6 MiB，峰值 RSS ×2.77**）
- 我把对象全释放了，RSS 会还回来吗？（取决于负载：3.7% 到 100% 都实测到了）
- 我的内存测试台本身可信吗？（`memtruth gate` 直接对测试台判不合格：本仓 11 条负载里 6 条在 ×1.25 门槛下不合格，2 条因 RSS 低于噪声地板不参与比值）

## 2 · 实测（本机真实输出，`benchmark/calibration.json`）

11 条分配路径 × 3 次独立子进程 × 2 种模式（traced / control），共 **66 次运行**，每次全新解释器。表内为 3 次中位数；p25/p75 与逐次样本见 `benchmark/raw/`（66 个 JSON）。

| workload | traced 峰值 | RSS 峰值(关闭 tracing) | RSS 峰值(开启 tracing) | traced/RSS | 判定 | 释放后 RSS 留存 |
|---|---:|---:|---:|---:|---|---:|
| `small_objects` 200k 两键 dict | 42.8 MiB | 44.6 MiB | 106.3 MiB | 0.96x | agree | 100% |
| `bytes_1k` 200k × 1 KiB | 203.2 MiB | 206.0 MiB | 225.2 MiB | 0.99x | agree | 100% |
| `churn_free` 分配后全部释放 | 42.8 MiB | 44.6 MiB | 106.2 MiB | 0.96x | agree | **3.7%** |
| `json_roundtrip` 8 MiB 文档 | 33.7 MiB | 35.8 MiB | 75.8 MiB | 0.94x | agree | 58% |
| `regex_findall` 1 MiB → 786k 对象 | 38.7 MiB | 43.2 MiB | 119.8 MiB | 0.90x | agree | 98% |
| `stdlib_compile` 5 个 stdlib 包真实源码 | 4.9 MiB | 5.5 MiB | 8.1 MiB | 0.89x | agree | 94% |
| `numpy_touched` 64 MiB 全页写入 | 64.0 MiB | 64.0 MiB | 64.0 MiB | 1.00x | agree | 100% |
| `mmap_pages` 32 MiB 匿名映射 | 32.0 MiB | 63.9 MiB | 63.9 MiB | 0.50x | under-report | 50% |
| `sqlite_rows` 20k 行内存表 | 1.9 MiB | 3.6 MiB | 7.6 MiB | 0.51x | under-report | 100% |
| `numpy_zeros` 64 MiB 未写入 | 64.0 MiB | 0.0 MiB | 0.0 MiB | **≥64x** | rss-below-noise-floor | 100% |
| `zlib_zeros` 压缩 32 MiB 零字节 | 32.6 MiB | 0.4 MiB | 0.4 MiB | **≥33x** | rss-below-noise-floor | 100% |

三条可引用、也可被推翻的结论：

1. **traced 峰值 ≠ 驻留内存，偏差双向。** 未写入的零页（`numpy.zeros`、`bytes(n)`）只映射共享零页，RSS 几乎不涨，tracemalloc 却按请求字节全额记账：RSS 少于 **1 MiB 噪声地板**，traced 报 32.6–64.0 MiB，因此只报下界 **≥33x / ≥64x**（不把 4 KiB 的分母除成 16392x）。反方向：`sqlite3` 页缓存走 C `malloc`、`mmap` 映射不是分配器对象，traced 只看到 **0.50x–0.51x**。纯 pymalloc 留存负载（`small_objects`、`bytes_1k`）两者只差 1%–4%。
2. **开 profiling 本身有成本，且不被它自己记账。** `regex_findall` 上 tracing 把峰值 RSS 从 43.2 MiB 抬到 119.8 MiB（**+76.6 MiB，×2.77**）；`small_objects`/`churn_free` +61.6 MiB（×2.38），`json_roundtrip` +40.0 MiB（×2.12），`sqlite_rows` +4.0 MiB（×2.10），真实源码 `stdlib_compile` +2.6 MiB（×1.49）。trace 元数据用原始分配器，不在 traced 数字里。任何「开着 tracemalloc 测 RSS」的对比都会把这笔算到被测代码头上。
3. **释放后 RSS 是否归还没有统一答案。** 同样 `del` + `gc.collect()`：`churn_free` 只留 3.7%（三次运行 3.7/3.7/3.7），`json_roundtrip` 58%–59%，`regex_findall` 98%，`small_objects` 100%。「RSS 只涨不落」是负载性质，不是解释器常量；工具报 `retained_fraction`，不替你下结论。

## 3 · 可证伪对照与测试

**写页对照（机制验证，不是相关性）**：`numpy_zeros` 与 `numpy_touched` 同库、同大小、同 `np.zeros` 调用，唯一差别是后者 `arr.fill(1.0)` 写了每一页。traced 峰值两次都是 **64.0 MiB（差 <0.01%）**，RSS 峰值从 **0.0 MiB 变成 64.0 MiB**，判定从「RSS 低于噪声地板（≥64x）」翻到 agree(1.00x)。这条对照被 `test_write_pattern_flips_verdict` 机器化：改回不写，结论必然回来。

- `PYTHONPATH=. python3 -m unittest discover -s tests -v` → **33 tests OK**（1.4 s）。覆盖：/proc 解析与畸形行、判定边界（1.49/1.50、0.70/0.71）、1 MiB 噪声地板与下界、instrument 成本双条件告警、p25/p50/p75、CLI 的 raw/聚合落盘、脚本审计、traced 字节跨进程确定性、写页翻转判定、gate 的三条拒绝路径、注册表不误 import numpy。
- 确定性：`small_objects` 在 scale=0.002 下连续两次独立子进程的 `traced_peak` **逐字节相等**（`test_traced_bytes_are_deterministic`）。
- 所有负载无随机数、无网络、无 sleep；`stdlib_compile` 读本机 CPython 自带真实源码（每 3 个 `.py` 取 1 个）。
- 本机只有 CPython 3.12.3（`/usr/bin/python3.12`），**无 3.10/3.11，无法交叉**；本文不声称跨版本结论。

## 4 · CI 闸门：先证明测试台不歪

```bash
python3 -m memtruth gate benchmark/calibration.json                 # 默认 x1.25
python3 -m memtruth gate benchmark/calibration.json --strict        # 还要求每个判定 agree
```

本仓实测（真实输出）：

```
FAIL churn_free       profiler inflates peak RSS x2.38 > x1.25
FAIL json_roundtrip   profiler inflates peak RSS x2.12 > x1.25
FAIL regex_findall    profiler inflates peak RSS x2.77 > x1.25
FAIL small_objects    profiler inflates peak RSS x2.38 > x1.25
FAIL sqlite_rows      profiler inflates peak RSS x2.10 > x1.25
FAIL stdlib_compile   profiler inflates peak RSS x1.49 > x1.25
6 workload(s) failed the memory-instrument gate   (exit=1)
```

**本仓自己的 11 条负载里有 6 条在 x1.25 下不合格，另有 2 条因 RSS 低于噪声地板不参与该比值**——这是结论，不是 bug：只要进程里有大量小对象，开 tracemalloc 测 RSS 就会把 trace 元数据算进去。闸门的用途是让 CI 在引用内存数字前先发现这件事；RSS 低于 1 MiB 的负载不参与该比值（分母是噪声）；traced 与 RSS 都低于 1 MiB 时判 `below-noise-floor`，不给任何比值。

## 5 · 复现（三条命令）

```bash
python3 -m pip install -e .
python3 benchmark/bench.py --repeat 3          # 写 benchmark/calibration.json + 66 个 raw 样本
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

单条路径：`python3 -m memtruth run sqlite_rows --repeat 3`；审计自己的脚本：`python3 -m memtruth audit myscript.py`。

## 6 · 环境

- CPU：AMD EPYC 7K62（4 vCPU）；内存 3.7 GiB（`free -m`）；Linux，`/proc` 可读。
- Python **3.12.3**；numpy **1.26.4**（仅两条 numpy 负载需要；缺失时跳过并记进 `skipped`）。
- 种子：不适用——所有负载确定性构造，没有 `random`。
- 原始样本 `benchmark/raw/<workload>-<mode>-<i>.json` 共 66 个；聚合 `benchmark/calibration.json`。

## 7 · 边界（不夸大的部分）

- RSS 是驻留物理页，受内核零页共享、THP、cgroup 记账影响；绝对值不跨机可比，**比值与判定**才是结论。
- `numpy_zeros` 的「≥64x」不是「numpy 不占内存」，而是「未写入的零页不驻留」；写满后就是 1.00x（已在表里）。
- 只测 Linux `/proc`；macOS/Windows 需要各自的 RSS 来源，未实现。
- 不替代 `memray`/`pympler`：它们做分配归因，本工具做**仪器一致性判定**。

## 本轮创新

**B 档。** 台账里 `peakgate`（单次调用 tracemalloc 高水位）、`slotsgate`/`slotfit`（每实例 heap）、`speedgap`（合成 vs 真实计时）都**信任 tracemalloc 读数**；本仓第一次把它当被测对象做三路对拍：traced 峰值 / 关闭 tracing 的 RSS 峰值 / 开启 tracing 的 RSS 峰值，按分配路径给出双向偏差与 **profiler 自身成本**（最多 ×2.77）。结论当场可证伪：`np.zeros` 改成写满，over-report 消失（≥64x → 1.00x）；不启动 tracemalloc，×2.77 的自成本消失。它还给出一个可执行判据（`gate`），并诚实地让本仓自己的 6/11 条负载不合格。这同时约束了本团队此前的内存声明——那些是 traced 字节，不是驻留内存。

## License

MIT，原创；见 `LICENSE`。
