# Linux Kernel on Graviton

This document captures Linux kernel configuration changes and tuning recommendations relevant to running workloads on AWS Graviton based instances.

## Kernel preemption model change in Linux 7.0

Starting with Linux kernel 7.0, the default preemption model changed from `PREEMPT_NONE` to `PREEMPT_LAZY` on architectures that support it.  This can cause throughput regressions for applications that rely on userspace spinlocks, as the scheduler may preempt a thread holding a lock causing all other threads to busy-wait, as reported for PostgreSQL 17 on the [LKML community](https://lore.kernel.org/all/20260403191942.21410-1-dipiets@amazon.it/T/#m8baeeaf48aa7ae5342c8c2db8f4e1c27e03c1368).

The regression can be amplified by minor page faults.  When a thread holding a spinlock accesses memory that has not yet been physically mapped (e.g. first-touch on a large `shared_buffers` region), the kernel handles a minor fault.  Under `PREEMPT_LAZY`, the faulting thread can be preempted while the kernel is still handling the fault and scheduled out.  The lock is not released until the faulting thread is scheduled back in and completes the fault, so every other thread waiting for that lock keeps spinning on-cpu for the entire duration.

### Mitigations

1. Use the [rseq time slice extension](https://lkml.kernel.org/r/20251215155615.870031952@linutronix.de) to let userspace request a short scheduling extension while inside a critical section.  Applications need to be updated to use this interface.
2. Use a Linux distribution that defaults to `PREEMPT_NONE` on kernel 7.0+.  Note: the kernel maintainers might remove PREEMPT_NONE in a future release.
3. If building a custom kernel, set `CONFIG_PREEMPT_NONE=y` to restore the previous behavior.
4. For PostgreSQL, enabling huge pages (`huge_pages = on` in `postgresql.conf` with pre-allocated `vm.nr_hugepages`) can mitigate the issue by reducing the number of minor faults by orders of magnitude.


## Metal instance IO optimizations

1. If on Graviton2 and newer metal instances, try disabling the System MMU (Memory Management Unit) to speed up IO handling:
  ```bash
  %> cd ~/aws-gravition-getting-started/perfrunbook/utilities
  # Configure the SMMU to be off on metal, which is the default on x86.
  # Leave the SMMU on if you require the additional security protections it offers.
  # Virtualized instances do not expose an SMMU to instances.
  %> sudo ./configure_graviton_metal_iommu.sh off
  %> sudo shutdown now -r
  ```

