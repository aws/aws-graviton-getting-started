# Migration Waves Reference

This document describes the 4-wave phased migration plan used by the Graviton Savings Assessment skill. Each wave groups instances by migration complexity and service type, enabling teams to capture savings incrementally with appropriate effort at each stage.

---

## Wave 1: Managed Services

**Scope:** All non-Graviton instances running on AWS managed services — RDS, ElastiCache, and OpenSearch — except RDS on SQL Server, Oracle or Db2, which go to Wave 4. These services support in-place instance class changes with minimal application impact.

**Timeline:** Week 1–2

**Effort Level:** Low

**Required Migration Actions:**
1. Modify the instance class from x86 to Graviton equivalent (e.g., `db.r5` → `db.r6g`)
2. Apply the change using a blue/green deployment or maintenance window
3. Verify application connectivity and performance after switchover
4. Update IaC templates (Terraform, CloudFormation) to reflect the new instance class

**Example Instance Types:**

| Current | Graviton Target | Service |
|---------|----------------|---------|
| db.r5.xlarge | db.r6g.xlarge | RDS |
| cache.m5.large | cache.m6g.large | ElastiCache |
| db.m5.2xlarge | db.m6g.2xlarge | RDS |

**Why Wave 1 is first:** Managed services require no OS-level changes, no AMI rebuilds, and no application recompilation. The migration is a configuration change with built-in rollback via blue/green deployment. This delivers quick wins with minimal risk.

---

## Wave 2: Containers (EKS/ECS/Fargate)

**Scope:** EC2 instances running containerized workloads on EKS or ECS.

**Not auto-detected.** EKS/ECS nodes bill as ordinary EC2 instance hours and cannot be told apart from other instances in Cost Explorer data without resource tags; Fargate bills as vCPU/GB-hours and is outside this assessment's instance-hours scope entirely. Any container nodes in the fleet are therefore counted in Wave 3, where the effort estimate assumes an AMI swap rather than the multi-arch image rebuild described below — size that work separately using your own knowledge of which instances are cluster nodes.

**Timeline:** Week 2–3

**Effort Level:** Medium

**Required Migration Actions:**
1. Build multi-architecture (amd64 + arm64) container images using Docker buildx
2. Push multi-arch manifests to ECR or your container registry
3. Update Karpenter NodePool or Auto Scaling Group configurations to include Graviton instance types (e.g., `m6g`, `c6g` families)
4. Deploy updated task definitions or pod specs that support arm64 scheduling
5. Validate workload performance on Graviton nodes
6. Gradually shift traffic from x86 to arm64 nodes

**Example Instance Types:**

| Current | Graviton Target | Context |
|---------|----------------|---------|
| m5.xlarge | m6g.xlarge | EKS worker node |
| c5.2xlarge | c6g.2xlarge | ECS container instance |
| m5.4xlarge | m6g.4xlarge | EKS node group |

**Why Wave 2 is second:** Container workloads are already abstracted from the underlying hardware. Multi-arch builds are a one-time setup, and Kubernetes/ECS schedulers handle placement automatically. The main effort is building arm64 images and validating compatibility — more work than the AMI swap Wave 3 costs those instances at, which is why identifying your container nodes yourself matters.

---

## Wave 3: EC2 Instances

**Scope:** All remaining EC2 instances that have a Graviton upgrade path but are not running containerized workloads. This includes standalone application servers, batch processing nodes, and general-purpose compute.

**Timeline:** Week 3–6

**Effort Level:** Medium

**Required Migration Actions:**
1. Rebuild or obtain arm64-compatible AMIs for your application stack
2. Update launch templates or launch configurations to specify Graviton instance types
3. Recompile any native binaries or install arm64 package variants
4. Update Auto Scaling Groups with new launch template versions
5. Perform load testing and application validation on Graviton instances
6. Execute a rolling deployment or blue/green cutover
7. Update monitoring and alerting thresholds if performance characteristics change

**Example Instance Types:**

| Current | Graviton Target | Use Case |
|---------|----------------|----------|
| m5.xlarge | m6g.xlarge | General-purpose application server |
| c5.4xlarge | c6g.4xlarge | Compute-intensive batch processing |
| r5.2xlarge | r6g.2xlarge | Memory-optimized analytics |

**Why Wave 3 takes longer:** EC2 migrations require AMI rebuilds, potential recompilation of native code, and more extensive testing. Each application may have unique dependencies that need arm64 validation.

---

## Wave 4: Blocked/Deferred

**Scope:** Instances with no Graviton path. This includes GPU/accelerator families (p, g, dl, trn, inf), Windows instances, RDS on SQL Server, Oracle or Db2, instance types the classifier does not recognise, and any instance family without an arm64 variant.

**Timeline:** Deferred

**Effort Level:** N/A

**Required Migration Actions:**
- No migration action available at this time
- Monitor AWS announcements for future Graviton support in these families
- Consider alternative optimization strategies (rightsizing, Spot, Reserved Instances)
- For Windows workloads, evaluate if the application can be ported to Linux

**Example Instance Types:**

| Instance Type | Blocking Reason |
|---------------|----------------|
| p4d.24xlarge | GPU instance — no Graviton equivalent |
| g5.xlarge | GPU instance — no Graviton equivalent |
| m5.xlarge (Windows) | Windows OS — requires Linux migration first |
| db.r5.xlarge (SQL Server) | Commercial engine — no Graviton instance classes on RDS |

**Why Wave 4 is deferred:** These instances either rely on hardware (GPU/accelerators) that has no arm64 variant, or run operating systems and software (Windows, commercial database engines) that are not supported on Graviton processors. They are assigned zero estimated savings in the assessment.

---

## Wave Summary Table

| Wave | Scope | Timeline | Effort | Savings Included |
|------|-------|----------|--------|-----------------|
| Wave 1 | Managed Services (RDS, ElastiCache, OpenSearch) | Week 1–2 | Low | Yes |
| Wave 2 | Containers (EKS/ECS) — not auto-detected, counted in Wave 3 | Week 2–3 | Medium | (in Wave 3) |
| Wave 3 | EC2 Instances (including any container nodes) | Week 3–6 | Medium | Yes |
| Wave 4 | Blocked/Deferred | Deferred | N/A | No ($0) |

**Total addressable savings** = Wave 1 + Wave 2 + Wave 3 savings. Wave 4 instances are excluded from savings calculations.
