# 引用内存数字前的检查表（含本团队历史声明复核）

这份文档不引入新测量，只把 `memtruth` 的三路对拍结论翻译成「怎么写、怎么读内存数字」。
所有支持数据在 `benchmark/calibration.json` 与 `benchmark/raw/`（66 次隔离运行）。

## 1 · 三种口径，回答三个不同问题

| 口径 | 怎么来 | 回答的问题 | 什么时候会骗你 |
|---|---|---|---|
| traced bytes | `tracemalloc.get_traced_memory()` | 我的代码向 Python 分配器**请求**了多少字节 | 零页未写入时高估（≥33x–≥64x）；C 扩展/`mmap` 时低估（0.50x–0.52x） |
| RSS 峰值 | `/proc/self/status` 的 `VmHWM` − 基线 `VmRSS` | 内核为这个进程**驻留**了多少物理页 | 零页共享时接近 0；页缓存/共享库把别的成本算进来 |
| 开 tracing 的 RSS 峰值 | 同上，但先 `tracemalloc.start()` | 我的**测试台**实际占了多少内存 | 把 trace 元数据算进被测代码（本机最多 ×2.77） |

**没有一种口径是「进程内存」本身。** 结论必须写清口径、基线、以及是否开着 profiler。

## 2 · 四条硬规则

1. **写数字必须带口径**：「峰值 4.7 MB (traced)」而不是「内存 4.7 MB」。
2. **做 A/B 对比时，两种模式都要测**：只在 `tracemalloc` 下对比，会把 ×2.38–×2.77 的自成本算进被测实现，且不同负载的放大倍数不同。
3. **分母小于 1 MiB 不给倍数**：4 KiB 的 RSS 差分除 64 MiB，得到的 16392x 是噪声放大器。`memtruth` 在 1 MiB 以下只报下界（`rss-below-noise-floor` / `below-noise-floor`）。
4. **峰值与留存分开报**：本机同一句 `del` + `gc.collect()`，留存从 3.7%（`churn_free`）到 100%（`small_objects`）都有；「RSS 不归还」不是通用事实。

## 3 · 本团队历史内存声明的口径复核

只做口径标注，**不重跑、不改写**那些仓库的结论（它们的代码与原始样本仍各自可复现）：

| 仓库 | 当时的测量 | 口径 | 复核意见 |
|---|---|---|---|
| `linluozi/peakgate` | 每次调用自建 `tracemalloc` 高水位，`findall→finditer` 4.71 MB→2.23 kB | traced | 作为「分配请求峰值」成立；**不能**读成 RSS。本仓 `regex_findall` 的 traced/RSS=0.90x 只说明该负载下 traced 略低于驻留峰值；同一负载的 profiler 自成本是 ×2.77，所以「开着 tracing 的 RSS」不能由该数字推出 |
| `linluozi/slotfit` / `slotcert` / `slotforge` / `slotsgate` | 每实例 live heap（tracemalloc） | traced | 被测对象是纯 pymalloc 小对象，落在本仓 7/11 的 agree 带（0.88x–1.00x），因此**近似可当驻留内存**；`slotsgate` 已自行修正 `__weakref__` 的 8 B/实例代价，与本仓结论一致 |
| `linluozi/speedgap` / `benchreconcile` / `diffcert` / `deoptscope` | 时间、声明对账、样本去重、特化计数 | 非内存 | 不涉及本检查表 |

## 4 · 一条命令自查

```bash
python3 benchmark/bench.py --repeat 3            # 得到你自己的 calibration.json
python3 -m memtruth gate benchmark/calibration.json --strict
```

`gate` 在「开 tracing 让峰值 RSS 超过关闭时 ×1.25」或「判定不是 agree」时返回 1。
本仓自己的 11 条负载里有 6 条在默认门槛下不合格——这不是缺陷，而是「多数内存测试台确实被 profiler 影响了」的证据。
