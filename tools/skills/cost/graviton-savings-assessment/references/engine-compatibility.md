# Engine Compatibility Reference — Graviton Support

This document lists the engine versions AWS supports on each Graviton instance
family for RDS, Aurora, ElastiCache and OpenSearch Service. Use it to answer
engine-readiness questions without running the assessment tool.

**The minimum depends on the Graviton family you move to, not just the engine.**
Redis OSS runs on `cache.r6g` from 5.0.6, needs 6.2 on `cache.r7g`, and is not
offered on `cache.r8g` at all. RDS PostgreSQL 13 runs on `db.r7g` from 13.4 but
needs 13.11 on `db.r8g`. Check the family your target actually is.

**A row can run several versions.** The assessment groups instances by type, engine and
region, so one row may include, say, MySQL 5.7 and 8.0. Each version is checked against
the table below and the row takes the worst result; Engine Readiness lists every version.

**Last reviewed:** 2026-11-12, against:

- RDS: [Supported DB engines for DB instance classes](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.DBInstanceClass.Support.html)
- Aurora: [Supported DB engines for DB instance classes (Aurora)](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.DBInstanceClass.SupportAurora.html)
- ElastiCache: [Supported node types](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheNodes.SupportedTypes.html)
- OpenSearch Service: [Supported instance types](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html)

The assessment's readiness check (`check_engine_graviton_readiness` in
`scripts/graviton_tools/fleet_tools.py`) uses the same table, so update both
together.

## Minimum versions by target family

How to read the last column:

- Each entry is the minimum for one release line: `13.4+` means 13.4 and every
  later 13.x. A bare major such as `15+` means every 15.x version.
- `13.4 only` is a single version below the line's minimum that AWS also
  supports.
- A release line that is not listed is not supported on that family.
- Redis OSS, Memcached and Valkey have one minimum per node family.

| Engine | Graviton families | Minimum supported version |
|---|---|---|
| postgres | m6g, r6g, t4g, x2g | 12.7+, 13+, 14+, 15+, 16+, 17+ |
| postgres | m6gd | 13.4 only, 13.7+, 14+, 15+, 16+, 17+ |
| postgres | r6gd, c6gd | 13.4 only, 13.7+, 14.5+, 15+, 16+, 17+ |
| postgres | m7g, r7g | 13.4+, 14.5+, 15+, 16+, 17+ |
| postgres | m8g, r8g | 13.11+, 14.9+, 15.4+, 16.1+, 17.1+ |
| postgres | m8gd, r8gd, m9g | 13.18+, 14.17+, 15.10+, 16.6+, 17.2+, 18.1+ |
| mysql | m6g, r6g, t4g, x2g, m6gd, r6gd, c6gd, m7g, r7g | 8.0+, 8.4+ |
| mysql | m8g, r8g | 8.0.32+, 8.4+ |
| mysql | m8gd, r8gd, m9g | 8.0.40+, 8.4.3+ |
| mariadb | m6g, r6g, t4g, x2g, m6gd, r6gd, m7g, r7g | 10.4+, 10.5+, 10.6+, 10.11+, 11.4+, 11.8+, 12.3+ |
| mariadb | m8g, r8g | 10.4.29+, 10.5.20+, 10.6.13+, 10.11.7+, 11.4.3+, 11.8.3+, 12.3.2+ |
| mariadb | m8gd, r8gd, m9g | 10.5.27+, 10.6.19+, 10.11.9+, 11.4.3+, 11.8.3+, 12.3.2+ |
| aurora-mysql | r6g, x2g, t4g | 2+, 3+ |
| aurora-mysql | r7g | 2.12.0+, 3.03.1+ |
| aurora-mysql | r8g | 3.08.0+ |
| aurora-postgresql | r6g, x2g | 11.9 only, 11.12+, 12.8+, 13.3+, 14.3+, 15.2+, 16.1+, 17.4+ |
| aurora-postgresql | t4g | 11.12+, 12.7+, 13.3+, 14.3+, 15.2+, 16.1+, 17.4+ |
| aurora-postgresql | r6gd | 14.9+, 15.4+, 16.1+, 17.4+ |
| aurora-postgresql | r7g | 13.10+, 14.7+, 15.2+, 16.1+, 17.4+ |
| aurora-postgresql | r8g | 13.15+, 14.12+, 15.7+, 16.3+, 17.4+ |
| aurora-postgresql | r8gd | 14.12+, 15.7+, 16.3+, 17.4+ |
| redis | m6g, r6g, t4g | 5.0.6+ |
| redis | m7g, r7g, c7gn, r6gd | 6.2+ |
| memcached | m6g, r6g, t4g, m7g, r7g | 1.5.16+ |
| memcached | m8g, r8g, c7gn, c8gn | 1.6.6+ |
| valkey | m6g, r6g, t4g, m7g, r7g, m8g, r8g, r6gd, r7gd, r8gd, c7gn, c8gn | 7.2+ |
| opensearch | c6g, m6g, r6g, r6gd, im4gn, i4g, c7g, m7g, r7g, r7gd, c8g, m8g, r8g, r8gd, i8g, i8ge | Elasticsearch 7.9+, OpenSearch 1.0+ |

Families not listed for an engine do not run it. Notable cases:

- **Redis OSS** is not offered on `cache.m8g`, `cache.r8g`, `cache.c8gn`,
  `cache.r7gd` or `cache.r8gd`. Valkey 7.2+ runs on all of them.
- **Aurora MySQL** is not offered on `db.r6gd` or `db.r8gd`, and `db.r8g` needs
  Aurora MySQL 3.08.0+ (there is no 2.x support).
- **MariaDB** is not offered on `db.c6gd`.
- **Aurora on db.t4g** is offered only in the medium and large sizes.
- **OpenSearch OR1, OR2 and OM2** (already Graviton) need OpenSearch 2.11+.
- Some sizes differ from the rest of their family (for example `db.m8gd.48xlarge`
  lists MySQL 8.0 and 8.4 without a minor floor). The table uses the minimum
  that applies to most sizes; check the AWS page for the exact class.

## Commercial engines

| Engine | Status | Notes |
|---|---|---|
| SQL Server | Not supported | No Graviton instance classes. Consider migrating to Aurora PostgreSQL with AWS SCT and AWS DMS. |
| Oracle | Not supported | No Graviton instance classes on RDS. |
| Db2 | Not supported | No Graviton instance classes on RDS. |

The assessment routes these rows to Wave 4 with no savings.

## How the readiness check reads versions

- RDS and Aurora PostgreSQL release lines are the major version (`13`).
- MySQL and MariaDB release lines are major.minor (`8.0`, `10.6`).
- Aurora MySQL versions are read from the Aurora release in the engine version
  (`8.0.mysql_aurora.3.05.2` is Aurora MySQL 3.05.2). A bare MySQL-compatible
  version such as `5.7.12` does not name the Aurora release, so the check
  returns `verify_version`.
- OpenSearch Service versions are read with their distribution:
  `OpenSearch_2.11` is OpenSearch 2.11, `Elasticsearch_7.10` is
  Elasticsearch 7.10.
- A version newer than every release line in the table returns
  `verify_version` rather than a guess. Review the table when that happens.

## Upgrade notes

- **MySQL 5.7** is not supported on any Graviton class. Upgrade to 8.0 first and
  test application compatibility (default authentication plugin, SQL mode
  changes) before switching the instance class.
- **Aurora MySQL 2** (MySQL 5.7 compatible) is supported on `db.r6g`, and on
  `db.r7g` from 2.12.0. Plan the move to Aurora MySQL 3 for `db.r8g`.
- **Redis OSS** fleets moving to Graviton4 node types need an engine change to
  Valkey; the Graviton2 and Graviton3 node types still run Redis OSS.
- **Elasticsearch** domains below 7.9 must upgrade to Elasticsearch 7.9+ or to
  OpenSearch before moving to any Graviton instance type.
