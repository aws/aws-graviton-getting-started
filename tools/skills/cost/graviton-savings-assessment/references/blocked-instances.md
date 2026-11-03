# Blocked Instance Families — No Graviton Migration Path

This document lists instance families and workload categories that cannot be migrated to Graviton (ARM64) processors. These are assigned to **Wave 4 (Blocked/Deferred)** in migration plans with **$0 estimated savings**.

---

## GPU and Accelerator Families

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `p` (p3, p4d, p5, p6) | GPU compute (NVIDIA V100/A100/H100/B200) | No Graviton GPU instance in this family. P6e-GB200 is ARM64, but on NVIDIA Grace CPUs, not Graviton, and is not a like-for-like cost migration. | Optimize with newer GPU generations (p4d → p5) for better price-performance. Consider SageMaker managed training. |
| `g` (g4dn, g5, g6) | Graphics-intensive / ML inference | The only Graviton GPU instance is g5g (Graviton2 with NVIDIA T4G GPUs). The skill treats g5g as already-Graviton; it is not offered as a target for other g families, whose GPUs differ. | Evaluate g5g for Android game streaming or ML inference that fits a T4G GPU; use AWS Inferentia (inf2) for ML inference where the model is compatible. |
| `dl` (dl1, dl2q) | Deep learning training | Specialized Gaudi/Qualcomm accelerators, no ARM64 variant. | Evaluate Trainium (trn1) for training workloads with supported frameworks. |
| `trn` (trn1, trn1n, trn2) | AWS Trainium ML training | Already a custom AWS chip; not x86 or ARM64 migration target. | Already cost-optimized for training. No action needed. |
| `inf` (inf1, inf2) | AWS Inferentia ML inference | Already a custom AWS chip; not x86 or ARM64 migration target. | Already cost-optimized for inference. No action needed. |

---

## Specialized Compute Families

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `vt` (vt1) | Video transcoding (Xilinx) | FPGA-based transcoding hardware, no Graviton equivalent. | Use AWS Elemental MediaConvert for managed transcoding. |
| `f` (f1) | FPGA instances | Custom FPGA hardware, no ARM64 FPGA instances available. | Re-evaluate if FPGA logic can be ported to software on Graviton for non-latency-critical paths. |

---

## Dense Storage Families

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `d` (d2, d3, d3en) | Dense HDD storage | HDD-based storage instances, no Graviton equivalent with local HDD. | Evaluate i4g (Graviton NVMe SSD) if SSD is acceptable, or use S3/EBS for storage-heavy workloads. |
| `h` (h1) | High-throughput HDD | 16 TB HDD per instance, no Graviton equivalent. | Migrate to d3en for better density, or offload to S3 for sequential workloads. |

---

## High Memory Families

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `z` (z1d) | High-frequency compute + memory | Sustained all-core turbo frequency, no Graviton equivalent. | Evaluate r7g for memory-intensive workloads where single-thread frequency is not critical. |
| `u` (u-6tb1, u-24tb1) | High memory (6–24 TB RAM) | Extreme memory capacity for SAP HANA / in-memory databases, no Graviton equivalent at this scale. | No direct alternative. Continue on x86 high-memory instances. |

> **Note:** hyphenated `u-*` type names (e.g. `u-6tb1.112xlarge`) do not match the
> classifier's type pattern. Their spend is still counted in the total; they are
> listed in the HTML report's Not Eligible table as "Unrecognised instance type"
> and in `summary.data_quality.unclassified_types` in the assessment JSON.

---

## Mac Instances

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `mac` (mac1, mac2, mac2-m1ultra) | Apple macOS (Intel/Apple Silicon) | Dedicated Apple hardware for macOS builds. Not applicable to Graviton migration. | mac2 (M1) and mac2-m1ultra already use Apple ARM silicon. No AWS Graviton path exists or is needed. |

---

## Windows-Only Workloads

| Category | Blocking Reason | Alternative Path |
|----------|-----------------|------------------|
| .NET Framework (not .NET Core/.NET 5+) | .NET Framework runs only on Windows, which has limited Graviton support and higher licensing costs. | Port to .NET 6+ which supports Linux ARM64 natively, then migrate to Graviton. |
| Windows-specific services (Active Directory, IIS, MSMQ) | Tightly coupled to Windows OS; no Linux ARM64 equivalent. | Evaluate AWS Managed AD, ALB, or Amazon MQ as managed replacements where feasible. |
| Windows desktop applications | Require Windows GUI stack, no ARM64 Windows on EC2. | Keep on x86 Windows instances. Consider Amazon WorkSpaces for end-user desktops. |

---

## Commercial Database Engines

The skill routes RDS rows on these engines to Wave 4 with $0 savings, whatever
the instance class, because RDS offers them no Graviton instance classes.

| Category | Blocking Reason | Alternative Path |
|----------|-----------------|------------------|
| SQL Server (all editions) | AWS does not offer Graviton-based RDS for SQL Server. | Migrate to PostgreSQL or Aurora PostgreSQL for Graviton compatibility. Use AWS SCT (Schema Conversion Tool) and DMS for migration. Alternatively, optimize with newer x86 generations (r5 → r6i). |
| Oracle, Db2 | No Graviton instance classes for these engines on RDS. | Migrate to PostgreSQL or Aurora PostgreSQL with AWS SCT and DMS where feasible, or optimize within x86 generations. |

---

## Legacy Families

| Family | Description | Blocking Reason | Alternative Path |
|--------|-------------|-----------------|------------------|
| `cc` / `cc1` / `cc2` | Cluster compute (legacy) | Deprecated instance families, no Graviton equivalent. | Migrate to c7g (Graviton3 compute-optimized) or hpc7g for HPC workloads. |
| `cg1` | Cluster GPU (legacy) | Deprecated GPU cluster instances. | Migrate to p5 or g6 for GPU workloads. |
| `cr` / `cr1` | High-memory cluster (legacy) | Deprecated memory-optimized cluster instances. | Migrate to r7g (Graviton3 memory-optimized). |

---

## Summary

| Category | Families | Count | Recommended Action |
|----------|----------|-------|--------------------|
| GPU / Accelerator | p, g, dl, trn, inf | 5 | Optimize within family or use AWS custom chips |
| Specialized Compute | vt, f | 2 | Evaluate managed services or software alternatives |
| Dense Storage | d, h | 2 | Consider NVMe SSD (i4g) or S3 offload |
| High Memory | z, u | 2 | Continue on x86; no Graviton path at scale |
| Mac | mac | 1 | Already ARM (Apple Silicon) where applicable |
| Legacy | cc, cc1, cc2, cg1, cr, cr1 | 6 | Migrate to current-gen Graviton equivalents |
| Windows-only | — | — | Port to .NET 6+ / Linux or keep on x86 |
| Commercial engines (SQL Server, Oracle, Db2) | — | — | Migrate to PostgreSQL/Aurora or stay on x86 |

**Total blocked families in classifier:** p, dl, trn, inf, g, vt, f, d, h, z, u, mac, cc, cc1, cc2, cg1, cr, cr1
