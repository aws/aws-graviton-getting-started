# Linux Kernel on Graviton

This document captures Linux kernel configuration changes and tuning recommendations relevant to running workloads on AWS Graviton based instances.

## Kernel preemption model change in Linux 7.0

Starting with Linux kernel 7.0, the default preemption model changed from `PREEMPT_NONE` to `PREEMPT_LAZY` on architectures that support it.  This can cause throughput regressions for applications that rely on userspace spinlocks, as the scheduler may preempt a thread holding a lock causing all other threads to busy-wait, as reported for PostgreSQL 17 on the [LKML community](https://lore.kernel.org/all/20260403191942.21410-1-dipiets@amazon.it/T/#m8baeeaf48aa7ae5342c8c2db8f4e1c27e03c1368).

### Mitigations

1. Use the [rseq time slice extension](https://lkml.kernel.org/r/20251215155615.870031952@linutronix.de) to let userspace request a short scheduling extension while inside a critical section.  Applications need to be updated to use this interface.
2. Use a Linux distribution that defaults to `PREEMPT_NONE` on kernel 7.0+.
3. If building a custom kernel, set `CONFIG_PREEMPT_NONE=y` to restore the previous behavior.
