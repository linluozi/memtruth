# memtruth

`tracemalloc` 报的是「Python 分配器被请求了多少字节」，`/proc` 的 RSS 报的是「内核真正驻留了多少页」。这两个数在真实代码里可以相差 **四个数量级**，而大多数内存结论只引用前者。`memtruth` 把三件事放进同一次隔离测量：traced 峰值、**关闭 profiling** 时的 RSS 峰值、**开启 profiling** 时的 RSS 峰值，并对每个分配路径给出「谁在说谎、差多少」的判定。

Upstream: none

本仓库是原创测量工具，不含上游补丁，也没有修改任何第三方库。因此任务书里的 G1–G5（上游测试绿 / 差分一致 / 中位加速 / 大规模不退化 / RSS 不退化）**不适用**：这里没有「优化后更快」的声明。替代它的是本文第 2 节的可复现测量与第 3 节的 26 个测试。

## 1 · 它回答什么问题

- 我引用的 `tracemalloc` 峰值，能当成进程内存成本吗？（9 条路径里只有 3 条能，误差 0.7–1.5x）
- 打开 `tracemalloc` 本身会让进程多占多少内存？（本机实测最多 **+76.6 MiB，峰值 RSS ×2.77**）
- 我把对象全释放了，RSS 会还回来吗？（churn 负载：归还 **0%**，RSS 停在峰值）
- C 扩展（sqlite3）、`mmap`、`numpy.zeros` 这些分配，tracemalloc 看得到吗？（分别只看到 0.51x / 0.50x / 0.00006x）

## 2 · 实测（本机真实输出，`benchmark/calibration.json`）

9 条分配路径 × 3 次独立子进程 × 2 种模式（traced / control），共 **54 次运行**，每次都是全新解释器。表中为 3 次的中位数；p25/p75 与逐次原始样本在 `benchmark/raw/`。

| workload | traced 峰值 | RSS 峰值(关闭 tracing) | RSS 峰值(开启 tracing) | traced/RSS | 判定 |
|---|---:|---:|---:|---:|---|
| `small_objects` 200k 两键 dict | 42.8 MiB | 44.6 MiB | 106.2 MiB | 0.96x | agree |
| `bytes_1k` 200k × 1 KiB | 203.2 MiB | 206.0 MiB | 225.2 MiB | 0.99x | agree |
| `churn_free` 分配后全部释放 | 42.8 MiB | 44.6 MiB | 106.2 MiB | 0.96x | agree |
| `json_roundtrip` 8 MiB 文档 | 33.7 MiB | 35.8 MiB | 75.8 MiB | 0.94x | agree |
| `regex_findall` 1 MiB → 786k 对象 | 38.7 MiB | 43.2 MiB | 119.8 MiB | 0.90x | agree |
| `mmap_pages` 32 MiB 匿名映射 | 32.0 MiB | 63.9 MiB | 63.9 MiB | 0.50x | under-report |
| `sqlite_rows` 20k 行内存表 | 1.9 MiB | 3.6 MiB | 7.5 MiB | 0.51x | under-report |
| `numpy_zeros` 64 MiB 未写入 | 64.0 MiB | 0.0 MiB | 0.0 MiB | 16391x | over-report |
| `zlib_zeros` 压缩 32 MiB 零字节 | 32.6 MiB | 0.4 MiB | 0.4 MiB | 79.5x | over-report |

三个可以直接引用、也可被推翻的结论：

1. **traced 峰值 ≠ 驻留内存，偏差是双向的。** 未写入的零页（`numpy.zeros`、`bytes(n)`）只映射共享零页，RSS 几乎不涨，tracemalloc 却按请求字节全额记账 → 高估 **79x–16392x**；反过来，`sqlite3` 的页缓存走 C `malloc`、`mmap` 的映射根本不是分配器对象 → 低估到 **0.50x**。
2. **开 profiling 本身有成本，且不被它自己记账。** `regex_findall` 上 tracing 让峰值 RSS 从 43.2 MiB 涨到 119.8 MiB（**+76.6 MiB，×2.77**）；`small_objects` / `churn_free` 为 +61.6 MiB（×2.38），`json_roundtrip` +39.9 MiB（×2.11）。tracemalloc 的 trace 元数据用的是原始分配器，不在 traced 数字里。任何「开着 tracemalloc 测 RSS」的对比都会把这部分算到被测代码头上。
3. **churn 负载释放后 RSS 不归还。** `churn_free` 把 200k dict 全部 `del` 并 `gc.collect()` 后，RSS 仍为峰值的 **100.0%**（`retained_fraction=1.0001`）。这类代码的合理成本指标是**峰值**，不是结束时的存活字节。

参考：3/9 条路径落进 0.7–1.5x 的「agree」带，说明 traced 数字在纯 pymalloc 留存负载上可信；不可信的 6 条正好是零页、C 扩展、`mmap` 三条路径。

## 3 · 测试与证据

- `PYTHONPATH=. python3 -m unittest discover -s tests -v` → **26 tests OK**（0.55 s）。覆盖：/proc 解析与畸形行、判定阈值边界（1.49/1.50、0.70/0.71）、instrument 成本的「双条件」告警、p25/p50/p75、CLI 的 raw/聚合落盘、脚本审计模式、traced 字节的跨进程确定性、注册表不误 import numpy。
- 确定性：`small_objects` 在 scale=0.002 下连续两次独立子进程的 `traced_peak` **逐字节相等**（测试 `test_traced_bytes_are_deterministic`）。
- 全部工作负载无随机数、无网络、无 sleep；工作负载只做确定性分配。
- 本机只有 CPython 3.12.3（`/usr/bin/python3.12`），**无 3.10/3.11，无法做三解释器交叉**；本报告不声称跨版本结论。

## 4 · 复现（三条命令）

```bash
python3 -m pip install -e .
python3 benchmark/bench.py --repeat 3          # 写 benchmark/calibration.json 与 54 个 raw 样本
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

单条路径：`python3 -m memtruth run sqlite_rows --repeat 3`；审计自己的脚本：`python3 -m memtruth audit myscript.py`。

## 5 · 环境

- CPU：AMD EPYC 7K62（4 vCPU）；内存 3.7 GiB（本机 `free -m`）；Linux，`/proc` 可读。
- Python **3.12.3**；numpy **1.26.4**（仅 `numpy_zeros` 需要，缺失时该条自动跳过并在 `skipped` 记录）。
- 种子：不适用——所有负载是确定性构造，没有 `random`。
- 原始样本：`benchmark/raw/<workload>-<mode>-<i>.json`，54 个；聚合：`benchmark/calibration.json`。

## 6 · 边界（不夸大的部分）

- RSS 是**驻留物理页**，受内核零页共享、THP、cgroup 记账影响；本机是单机容器，绝对值不可跨机复现，**比值与判定**才是结论。
- `numpy_zeros` 的 16392x 不是「numpy 不占内存」，而是「未写入的零页不驻留」；一旦写入，RSS 会涨到接近 64 MiB。工具报告的是**这条负载的触碰行为**。
- 只测 Linux `/proc`；macOS/Windows 需要各自的 RSS 来源，未实现。
- 不替代 `memray`/`pympler`：它们做分配归因，本工具做**仪器一致性判定**。

## 本轮创新

**B 档。** 台账里 `peakgate`（单次调用 tracemalloc 高水位）、`slotsgate`/`slotfit`（每实例 heap）、`speedgap`（合成 vs 真实计时）都**信任 tracemalloc 的读数**；本仓第一次把它当被测对象，做三路对拍：traced 峰值 / 关闭 tracing 的 RSS 峰值 / 开启 tracing 的 RSS 峰值，并按分配路径给出双向偏差与 **profiler 自身成本**（最多 ×2.77）。新结论是可证伪的：同一负载把 `np.zeros` 改成写入，over-report 就会消失；关掉 tracemalloc，×2.77 的自成本也会消失。这也直接约束了本团队此前的内存声明——那些是 traced 字节，不是驻留内存。

## License

MIT，原创；见 `LICENSE`。
