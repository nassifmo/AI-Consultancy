# Review sheet

Period: 2026-01-01 00:00 to 2026-02-01 00:00 (UTC). Data cutoff: 2026-02-15 00:00. 30 shipments, 520 events, 52 enquiries.

For each enquiry check: the stated reference points to the right shipment (or is flagged wrong),
the enquiry type makes sense, and 'known' vs 'actual' differ only when an event was recorded late (stale).

## BKG000100000 (CUS-00008) FRMRS -> SGSIN

- Delay class: **long** (+56.9 h vs plan)
- Planned: depart 2026-01-12 17:00, arrive 2026-02-04 17:00
- Actual: depart 2026-01-12 14:11, arrive 2026-02-07 01:51, released 2026-02-09 20:59
- Containers: SYNU0000014; BL SBL000500000 issued 2026-01-13 23:53

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-04 17:00 | 2025-12-23 10:56 |  |
| DEPA | PLN | 2026-01-12 17:00 | 2025-12-23 10:56 |  |
| CONF | ACT | 2025-12-23 10:56 | 2025-12-24 16:07 | yes |
| GTIN SYNU0000014 | ACT | 2026-01-09 23:47 | 2026-01-09 23:52 |  |
| LOAD SYNU0000014 | ACT | 2026-01-12 07:10 | 2026-01-12 07:35 |  |
| DEPA | ACT | 2026-01-12 14:11 | 2026-01-12 22:43 | yes |
| ARRI | EST | 2026-02-05 21:00 | 2026-01-14 18:02 |  |
| ISSU | ACT | 2026-01-13 23:53 | 2026-01-15 13:40 | yes |
| ARRI | EST | 2026-02-07 02:00 | 2026-02-02 21:03 |  |
| DISC SYNU0000014 | ACT | 2026-02-07 12:39 | 2026-02-07 13:23 |  |
| ARRI | ACT | 2026-02-07 01:51 | 2026-02-08 20:27 | yes |
| RELS | ACT | 2026-02-09 20:59 | 2026-02-09 21:05 |  |
| GTOT SYNU0000014 | ACT | 2026-02-10 20:51 | 2026-02-10 21:12 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000017 | 2026-01-18 18:52 | delay (delay-driven) | SYNU0000014 (container) | departed / 2026-02-05 21:00 | departed / 2026-02-05 21:00 |
| ENQ-000024 | 2026-01-22 08:57 | delay | BKG000100000 (booking, repeat of ENQ-000017) | departed / 2026-02-05 21:00 | departed / 2026-02-05 21:00 |
| ENQ-000030 | 2026-01-25 21:28 | delay (delay-driven) | BKG000100100 (typo) | departed / 2026-02-05 21:00 | departed / 2026-02-05 21:00 |
| ENQ-000032 | 2026-01-26 23:17 | delay | BKG000100000 (booking, repeat of ENQ-000030) | departed / 2026-02-05 21:00 | departed / 2026-02-05 21:00 |
| ENQ-000043 | 2026-02-03 13:11 | delay (delay-driven) | SBL000500000 (bl) | departed / 2026-02-07 02:00 | departed / 2026-02-07 02:00 |
| ENQ-000050 | 2026-02-11 05:34 | status | BKG070100000 (typo) | gated_out / 2026-02-07 01:51 | gated_out / 2026-02-07 01:51 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000017 | human_baseline | human BKG000100000: departed / 2026-02-05 21:00 (ok) | human BKG000100000: departed / 2026-02-05 21:00 (ok) | yes / 1 | 5.4 | **failed** repeat | S11 |
| ENQ-000024 | human_baseline | human BKG000100000: departed / 2026-02-05 21:00 (ok) | human BKG000100000: departed / 2026-02-05 21:00 (ok) | yes / 1 | 25.8 | **failed** repeat | S8 |
| ENQ-000030 | agent_v1 | human BKG000100000: departed / 2026-02-05 21:00 (ok) | human BKG000100000: departed / 2026-02-05 21:00 (ok) | yes / 1 | 22.7 | **failed** handoff repeat | S8 |
| ENQ-000032 | agent_v1 | ai_agent BKG000100000: departed / 2026-02-05 21:00 (ok) | ai_agent BKG000100000: departed / 2026-02-05 21:00 (ok) | yes / 1 | 0.0 | **failed** | S11 |
| ENQ-000043 | human_baseline | human BKG000100000: departed / 2026-02-07 02:00 (ok) | human BKG000100000: departed / 2026-02-07 02:00 (ok) | yes / 1 | 68.1 | **failed** | S2 |
| ENQ-000050 | human_baseline | human BKG000100000: gated_out / 2026-02-07 01:51 (ok) | human BKG000100000: gated_out / 2026-02-07 01:51 (ok) | no / 0 | 9.4 | **resolved** | S1 |

## BKG000100001 (CUS-00005) NLRTM -> CNSHA

- Delay class: **none** (+0.4 h vs plan)
- Planned: depart 2026-01-15 01:00, arrive 2026-02-02 01:00
- Actual: depart 2026-01-15 05:55, arrive 2026-02-02 01:26, released 2026-02-04 05:39
- Containers: SYNU0000020; BL SBL000500001 issued 2026-01-16 22:58

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-02 01:00 | 2025-12-30 14:42 |  |
| DEPA | PLN | 2026-01-15 01:00 | 2025-12-30 14:42 |  |
| CONF | ACT | 2025-12-30 14:42 | 2025-12-30 15:19 |  |
| GTIN SYNU0000020 | ACT | 2026-01-12 13:36 | 2026-01-12 14:43 |  |
| LOAD SYNU0000020 | ACT | 2026-01-14 18:52 | 2026-01-14 19:00 |  |
| DEPA | ACT | 2026-01-15 05:55 | 2026-01-15 06:25 |  |
| ISSU | ACT | 2026-01-16 22:58 | 2026-01-17 00:16 |  |
| ARRI | ACT | 2026-02-02 01:26 | 2026-02-02 01:39 |  |
| DISC SYNU0000020 | ACT | 2026-02-02 23:19 | 2026-02-02 23:33 |  |
| RELS | ACT | 2026-02-04 05:39 | 2026-02-04 06:00 |  |
| GTOT SYNU0000020 | ACT | 2026-02-06 21:54 | 2026-02-06 21:56 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000003 | 2026-01-06 04:22 | status | SYNU0000020 (container) | booked / 2026-02-02 01:00 | booked / 2026-02-02 01:00 |
| ENQ-000014 | 2026-01-13 22:43 | delay | SYNU0000020 (container) | gated_in / 2026-02-02 01:00 | gated_in / 2026-02-02 01:00 |
| ENQ-000031 | 2026-01-25 22:31 | status | SYNU0000020 (container) | departed / 2026-02-02 01:00 | departed / 2026-02-02 01:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000003 | human_baseline | human BKG000100001: booked / 2026-02-02 01:00 (ok) | human BKG000100001: booked / 2026-02-02 01:00 (ok) | no / 0 | 4.2 | **resolved** | S1 |
| ENQ-000014 | human_baseline | human BKG000100001: gated_in / 2026-02-02 01:00 (ok) | human BKG000100001: gated_in / 2026-02-02 01:00 (ok) | no / 0 | 6.2 | **resolved** | S1 |
| ENQ-000031 | agent_v1 | ai_agent BKG000100001: departed / 2026-02-02 01:00 (ok) | ai_agent BKG000100001: departed / 2026-02-02 01:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100002 (CUS-00005) AEJEA -> SGSIN

- Delay class: **none** (-0.5 h vs plan)
- Planned: depart 2025-12-31 01:00, arrive 2026-01-31 01:00
- Actual: depart 2025-12-31 03:47, arrive 2026-01-31 00:28, released 2026-02-01 21:40
- Containers: SYNU0000035, SYNU0000040, SYNU0000056, SYNU0000061; BL SBL000500002 issued 2026-01-01 19:12

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-31 01:00 | 2025-12-12 16:31 |  |
| DEPA | PLN | 2025-12-31 01:00 | 2025-12-12 16:31 |  |
| CONF | ACT | 2025-12-12 16:31 | 2025-12-12 16:37 |  |
| GTIN SYNU0000061 | ACT | 2025-12-28 08:10 | 2025-12-28 08:43 |  |
| GTIN SYNU0000035 | ACT | 2025-12-28 21:34 | 2025-12-28 22:08 |  |
| GTIN SYNU0000040 | ACT | 2025-12-28 23:19 | 2025-12-29 01:31 |  |
| LOAD SYNU0000056 | ACT | 2025-12-30 17:44 | 2025-12-30 17:55 |  |
| LOAD SYNU0000040 | ACT | 2025-12-30 21:46 | 2025-12-30 21:50 |  |
| LOAD SYNU0000061 | ACT | 2025-12-30 21:26 | 2025-12-30 21:50 |  |
| LOAD SYNU0000035 | ACT | 2025-12-31 01:20 | 2025-12-31 04:09 |  |
| DEPA | ACT | 2025-12-31 03:47 | 2025-12-31 04:16 |  |
| GTIN SYNU0000056 | ACT | 2025-12-30 01:37 | 2025-12-31 05:03 | yes |
| ISSU | ACT | 2026-01-01 19:12 | 2026-01-01 19:35 |  |
| ARRI | EST | 2026-01-31 02:00 | 2026-01-02 15:49 |  |
| ARRI | EST | 2026-01-31 01:00 | 2026-01-19 03:43 |  |
| ARRI | EST | 2026-01-31 01:00 | 2026-01-19 20:34 |  |
| ARRI | ACT | 2026-01-31 00:28 | 2026-01-31 00:57 |  |
| DISC SYNU0000061 | ACT | 2026-01-31 16:51 | 2026-01-31 17:35 |  |
| DISC SYNU0000035 | ACT | 2026-01-31 17:35 | 2026-01-31 17:46 |  |
| DISC SYNU0000040 | ACT | 2026-01-31 15:26 | 2026-01-31 18:12 |  |
| DISC SYNU0000056 | ACT | 2026-01-31 23:57 | 2026-02-01 00:20 |  |
| RELS | ACT | 2026-02-01 21:40 | 2026-02-01 22:41 |  |
| GTOT SYNU0000035 | ACT | 2026-02-03 20:09 | 2026-02-03 20:30 |  |
| GTOT SYNU0000040 | ACT | 2026-02-04 01:35 | 2026-02-04 02:01 |  |
| GTOT SYNU0000056 | ACT | 2026-02-04 07:14 | 2026-02-04 07:21 |  |
| GTOT SYNU0000061 | ACT | 2026-02-04 16:14 | 2026-02-06 11:34 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000015 | 2026-01-14 04:12 | status | BKG000100002 (booking) | departed / 2026-01-31 02:00 | departed / 2026-01-31 02:00 |
| ENQ-000040 | 2026-02-02 10:09 | documents | SYNU0000061 (container) | released / 2026-01-31 00:28 | released / 2026-01-31 00:28 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000015 | agent_v1 | ai_agent BKG000100002: departed / 2026-01-31 02:00 (ok) | ai_agent BKG000100002: departed / 2026-01-31 02:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000040 | agent_v1 | human ?: None / - (WRONG) | human ?: None / - (WRONG) | no / 0 | 14.8 | **out_of_scope** handoff | S12 |

## BKG000100003 (CUS-00002) CNSHA -> SAJED

- Delay class: **none** (-1.6 h vs plan)
- Planned: depart 2025-12-09 05:00, arrive 2026-01-18 05:00
- Actual: depart 2025-12-09 08:11, arrive 2026-01-18 03:23, released 2026-01-19 11:54
- Containers: SYNU0000077; BL SBL000500003 issued 2025-12-10 12:25

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-18 05:00 | 2025-11-25 04:50 |  |
| DEPA | PLN | 2025-12-09 05:00 | 2025-11-25 04:50 |  |
| CONF | ACT | 2025-11-25 04:50 | 2025-11-25 05:07 |  |
| GTIN SYNU0000077 | ACT | 2025-12-06 23:05 | 2025-12-07 00:14 |  |
| LOAD SYNU0000077 | ACT | 2025-12-08 20:50 | 2025-12-08 21:08 |  |
| DEPA | ACT | 2025-12-09 08:11 | 2025-12-09 08:37 |  |
| ISSU | ACT | 2025-12-10 12:25 | 2025-12-10 16:34 |  |
| ARRI | EST | 2026-01-18 04:00 | 2025-12-10 22:44 |  |
| ARRI | ACT | 2026-01-18 03:23 | 2026-01-18 05:26 |  |
| DISC SYNU0000077 | ACT | 2026-01-18 19:35 | 2026-01-19 07:06 | yes |
| RELS | ACT | 2026-01-19 11:54 | 2026-01-19 12:05 |  |
| GTOT SYNU0000077 | ACT | 2026-01-21 01:47 | 2026-01-21 09:23 |  |

_No enquiries in the period._

## BKG000100004 (CUS-00006) FRMRS -> AEJEA

- Delay class: **short** (+10.3 h vs plan)
- Planned: depart 2025-12-09 07:00, arrive 2026-01-11 07:00
- Actual: depart 2025-12-09 06:08, arrive 2026-01-11 17:16, released 2026-01-12 22:26
- Containers: SYNU0000082, SYNU0000098, SYNU0000101; BL SBL000500004 issued 2025-12-09 15:13

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-11 07:00 | 2025-11-27 11:13 |  |
| DEPA | PLN | 2025-12-09 07:00 | 2025-11-27 11:13 |  |
| CONF | ACT | 2025-11-27 11:13 | 2025-11-27 11:19 |  |
| GTIN SYNU0000082 | ACT | 2025-12-06 07:52 | 2025-12-06 10:36 |  |
| GTIN SYNU0000101 | ACT | 2025-12-06 12:15 | 2025-12-06 13:00 |  |
| LOAD SYNU0000082 | ACT | 2025-12-08 21:53 | 2025-12-08 22:07 |  |
| LOAD SYNU0000101 | ACT | 2025-12-08 23:42 | 2025-12-08 23:51 |  |
| GTIN SYNU0000098 | ACT | 2025-12-08 01:00 | 2025-12-09 05:18 | yes |
| DEPA | ACT | 2025-12-09 06:08 | 2025-12-09 10:10 |  |
| LOAD SYNU0000098 | ACT | 2025-12-09 03:53 | 2025-12-10 13:15 | yes |
| ISSU | ACT | 2025-12-09 15:13 | 2025-12-10 14:32 | yes |
| ARRI | EST | 2026-01-11 09:00 | 2025-12-12 11:29 |  |
| ARRI | EST | 2026-01-11 15:00 | 2025-12-17 10:33 |  |
| ARRI | EST | 2026-01-11 18:00 | 2026-01-08 19:24 |  |
| ARRI | ACT | 2026-01-11 17:16 | 2026-01-11 17:19 |  |
| DISC SYNU0000101 | ACT | 2026-01-11 21:45 | 2026-01-11 22:15 |  |
| DISC SYNU0000082 | ACT | 2026-01-12 00:51 | 2026-01-12 01:08 |  |
| DISC SYNU0000098 | ACT | 2026-01-12 15:49 | 2026-01-12 16:13 |  |
| RELS | ACT | 2026-01-12 22:26 | 2026-01-12 23:36 |  |
| GTOT SYNU0000098 | ACT | 2026-01-13 10:17 | 2026-01-13 11:43 |  |
| GTOT SYNU0000082 | ACT | 2026-01-14 01:27 | 2026-01-14 02:10 |  |
| GTOT SYNU0000101 | ACT | 2026-01-14 00:39 | 2026-01-14 10:52 | yes |

_No enquiries in the period._

## BKG000100005 (CUS-00004) NLRTM -> SAJED

- Delay class: **long** (+115.2 h vs plan)
- Planned: depart 2026-01-21 14:00, arrive 2026-03-01 14:00
- Actual: depart 2026-01-21 16:19, arrive 2026-03-06 09:11, released 2026-03-07 12:21
- Containers: SYNU0000117; BL SBL000500005 issued 2026-01-23 06:25

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-03-01 14:00 | 2026-01-12 05:27 |  |
| DEPA | PLN | 2026-01-21 14:00 | 2026-01-12 05:27 |  |
| CONF | ACT | 2026-01-12 05:27 | 2026-01-12 06:09 |  |
| GTIN SYNU0000117 | ACT | 2026-01-19 18:55 | 2026-01-19 19:03 |  |
| LOAD SYNU0000117 | ACT | 2026-01-21 07:01 | 2026-01-21 07:32 |  |
| DEPA | ACT | 2026-01-21 16:19 | 2026-01-21 16:28 |  |
| ISSU | ACT | 2026-01-23 06:25 | 2026-01-23 08:01 |  |
| ARRI | EST | 2026-03-06 10:00 | 2026-02-20 13:23 |  |
| ARRI | ACT | 2026-03-06 09:11 | 2026-03-06 10:21 |  |
| DISC SYNU0000117 | ACT | 2026-03-07 05:44 | 2026-03-07 05:49 |  |
| RELS | ACT | 2026-03-07 12:21 | 2026-03-07 13:44 |  |
| GTOT SYNU0000117 | ACT | 2026-03-09 19:12 | 2026-03-09 20:01 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000036 | 2026-01-28 11:34 | delay | BKG000100005 (booking) | departed / 2026-03-01 14:00 | departed / 2026-03-01 14:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000036 | human_baseline | human BKG000100005: departed / 2026-03-01 14:00 (ok) | human BKG000100005: departed / 2026-03-01 14:00 (ok) | no / 0 | 10.0 | **resolved** | S1 |

## BKG000100006 (CUS-00006) FRMRS -> SGSIN

- Delay class: **short** (+11.4 h vs plan)
- Planned: depart 2026-01-04 18:00, arrive 2026-01-23 18:00
- Actual: depart 2026-01-04 22:49, arrive 2026-01-24 05:22, released 2026-01-26 01:43
- Containers: SYNU0000122, SYNU0000138, SYNU0000143; BL SBL000500006 issued 2026-01-06 10:19

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-23 18:00 | 2025-12-24 15:56 |  |
| DEPA | PLN | 2026-01-04 18:00 | 2025-12-24 15:56 |  |
| CONF | ACT | 2025-12-24 15:56 | 2025-12-24 16:19 |  |
| GTIN SYNU0000138 | ACT | 2026-01-02 15:30 | 2026-01-02 16:24 |  |
| GTIN SYNU0000122 | ACT | 2026-01-02 22:35 | 2026-01-02 22:42 |  |
| GTIN SYNU0000143 | ACT | 2026-01-03 03:57 | 2026-01-03 04:17 |  |
| LOAD SYNU0000143 | ACT | 2026-01-04 12:06 | 2026-01-04 13:07 |  |
| LOAD SYNU0000138 | ACT | 2026-01-04 13:59 | 2026-01-04 14:22 |  |
| LOAD SYNU0000122 | ACT | 2026-01-04 17:48 | 2026-01-04 18:40 |  |
| DEPA | ACT | 2026-01-04 22:49 | 2026-01-04 23:05 |  |
| ISSU | ACT | 2026-01-06 10:19 | 2026-01-06 11:35 |  |
| ARRI | EST | 2026-01-24 05:00 | 2026-01-14 14:45 |  |
| DISC SYNU0000143 | ACT | 2026-01-24 16:12 | 2026-01-24 16:25 |  |
| DISC SYNU0000138 | ACT | 2026-01-24 16:25 | 2026-01-24 17:10 |  |
| DISC SYNU0000122 | ACT | 2026-01-24 20:17 | 2026-01-24 23:11 |  |
| ARRI | ACT | 2026-01-24 05:22 | 2026-01-25 04:31 |  |
| RELS | ACT | 2026-01-26 01:43 | 2026-01-26 02:24 |  |
| GTOT SYNU0000143 | ACT | 2026-01-28 17:32 | 2026-01-28 18:34 |  |
| GTOT SYNU0000122 | ACT | 2026-01-29 04:16 | 2026-01-29 04:51 |  |
| GTOT SYNU0000138 | ACT | 2026-01-29 04:16 | 2026-01-29 07:42 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000004 | 2026-01-07 18:32 | status | BKG000100006 (booking) | departed / 2026-01-23 18:00 | departed / 2026-01-23 18:00 |
| ENQ-000021 | 2026-01-21 09:44 | delay (delay-driven) | SYNU0000122 (container) | departed / 2026-01-24 05:00 | departed / 2026-01-24 05:00 |
| ENQ-000037 | 2026-01-28 14:48 | status | SYNU0000138 (container) | released / 2026-01-24 05:22 | released / 2026-01-24 05:22 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000004 | human_baseline | human BKG000100006: departed / 2026-01-23 18:00 (ok) | human BKG000100006: departed / 2026-01-23 18:00 (ok) | no / 0 | 1.9 | **resolved** | S1 |
| ENQ-000021 | agent_v1 | ai_agent BKG000100006: departed / 2026-01-24 05:00 (ok) | ai_agent BKG000100006: departed / 2026-01-24 05:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000037 | agent_v1 | ai_agent BKG000100006: released / 2026-01-24 05:22 (ok) | ai_agent BKG000100006: released / 2026-01-24 05:22 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100007 (CUS-00003) CNSHA -> SGSIN

- Delay class: **none** (-1.2 h vs plan)
- Planned: depart 2025-12-30 22:00, arrive 2026-02-08 22:00
- Actual: depart 2025-12-30 19:11, arrive 2026-02-08 20:50, released 2026-02-11 09:29
- Containers: SYNU0000159; BL SBL000500007 issued 2025-12-31 12:36

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-08 22:00 | 2025-12-13 08:35 |  |
| DEPA | PLN | 2025-12-30 22:00 | 2025-12-13 08:35 |  |
| CONF | ACT | 2025-12-13 08:35 | 2025-12-13 08:51 |  |
| GTIN SYNU0000159 | ACT | 2025-12-28 07:51 | 2025-12-28 08:16 |  |
| LOAD SYNU0000159 | ACT | 2025-12-30 12:39 | 2025-12-30 14:09 |  |
| DEPA | ACT | 2025-12-30 19:11 | 2025-12-30 19:31 |  |
| ISSU | ACT | 2025-12-31 12:36 | 2025-12-31 13:11 |  |
| ARRI | EST | 2026-02-08 22:00 | 2026-01-24 08:48 |  |
| ARRI | ACT | 2026-02-08 20:50 | 2026-02-08 21:00 |  |
| DISC SYNU0000159 | ACT | 2026-02-09 07:57 | 2026-02-09 08:23 |  |
| RELS | ACT | 2026-02-11 09:29 | 2026-02-11 09:29 |  |
| GTOT SYNU0000159 | ACT | 2026-02-13 08:08 | 2026-02-13 08:43 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000038 | 2026-01-28 23:46 | status | SBL000500007 (bl) | departed / 2026-02-08 22:00 | departed / 2026-02-08 22:00 |
| ENQ-000049 | 2026-02-10 03:48 | delay | BKG000100007 (booking) | discharged / 2026-02-08 20:50 | discharged / 2026-02-08 20:50 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000038 | human_baseline | human BKG000100007: departed / 2026-02-08 22:00 (ok) | human BKG000100007: departed / 2026-02-08 22:00 (ok) | no / 0 | 14.2 | **resolved** | S1 |
| ENQ-000049 | agent_v1 | ai_agent BKG000100007: discharged / 2026-02-08 20:50 (ok) | ai_agent BKG000100007: discharged / 2026-02-08 20:50 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100008 (CUS-00008) SAJED -> AEJEA

- Delay class: **short** (+5.4 h vs plan)
- Planned: depart 2025-12-14 14:00, arrive 2026-01-05 14:00
- Actual: depart 2025-12-14 19:00, arrive 2026-01-05 19:22, released 2026-01-07 20:23
- Containers: SYNU0000164, SYNU0000170; BL SBL000500008 issued 2025-12-16 00:49

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-05 14:00 | 2025-12-07 06:40 |  |
| DEPA | PLN | 2025-12-14 14:00 | 2025-12-07 06:40 |  |
| CONF | ACT | 2025-12-07 06:40 | 2025-12-08 11:51 | yes |
| GTIN SYNU0000164 | ACT | 2025-12-13 18:39 | 2025-12-13 18:49 |  |
| LOAD SYNU0000170 | ACT | 2025-12-14 07:09 | 2025-12-14 07:42 |  |
| LOAD SYNU0000164 | ACT | 2025-12-14 08:22 | 2025-12-14 09:02 |  |
| GTIN SYNU0000170 | ACT | 2025-12-13 15:44 | 2025-12-14 12:34 | yes |
| DEPA | ACT | 2025-12-14 19:00 | 2025-12-14 19:49 |  |
| ISSU | ACT | 2025-12-16 00:49 | 2025-12-16 01:20 |  |
| ARRI | EST | 2026-01-05 14:00 | 2025-12-24 01:54 |  |
| ARRI | EST | 2026-01-05 18:00 | 2025-12-25 16:23 |  |
| ARRI | EST | 2026-01-05 18:00 | 2025-12-30 02:06 |  |
| ARRI | ACT | 2026-01-05 19:22 | 2026-01-05 20:20 |  |
| DISC SYNU0000170 | ACT | 2026-01-06 04:04 | 2026-01-06 04:15 |  |
| DISC SYNU0000164 | ACT | 2026-01-06 19:10 | 2026-01-06 19:28 |  |
| RELS | ACT | 2026-01-07 20:23 | 2026-01-07 21:00 |  |
| GTOT SYNU0000164 | ACT | 2026-01-09 18:35 | 2026-01-09 21:53 |  |
| GTOT SYNU0000170 | ACT | 2026-01-09 17:33 | 2026-01-09 23:48 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000002 | 2026-01-03 00:49 | delay (delay-driven) | SYNU0000164 (container) | departed / 2026-01-05 18:00 | departed / 2026-01-05 18:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000002 | agent_v1 | ai_agent BKG000100008: departed / 2026-01-05 18:00 (ok) | ai_agent BKG000100008: departed / 2026-01-05 18:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100009 (CUS-00003) SAJED -> FRMRS

- Delay class: **short** (+8.1 h vs plan)
- Planned: depart 2026-01-25 19:00, arrive 2026-02-20 19:00
- Actual: depart 2026-01-25 19:59, arrive 2026-02-21 03:04, released 2026-02-23 08:24
- Containers: SYNU0000185; BL SBL000500009 issued 2026-01-27 02:47

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-20 19:00 | 2026-01-14 05:32 |  |
| DEPA | PLN | 2026-01-25 19:00 | 2026-01-14 05:32 |  |
| CONF | ACT | 2026-01-14 05:32 | 2026-01-14 06:17 |  |
| GTIN SYNU0000185 | ACT | 2026-01-24 15:46 | 2026-01-24 15:59 |  |
| LOAD SYNU0000185 | ACT | 2026-01-25 15:48 | 2026-01-25 15:57 |  |
| DEPA | ACT | 2026-01-25 19:59 | 2026-01-25 21:06 |  |
| ARRI | EST | 2026-02-21 03:00 | 2026-01-26 19:45 |  |
| ISSU | ACT | 2026-01-27 02:47 | 2026-01-27 02:49 |  |
| ARRI | ACT | 2026-02-21 03:04 | 2026-02-21 07:08 |  |
| DISC SYNU0000185 | ACT | 2026-02-21 10:03 | 2026-02-21 10:06 |  |
| RELS | ACT | 2026-02-23 08:24 | 2026-02-23 09:31 |  |
| GTOT SYNU0000185 | ACT | 2026-02-26 09:19 | 2026-02-26 21:16 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000044 | 2026-02-05 06:35 | status | SYNU0000185 (container) | departed / 2026-02-21 03:00 | departed / 2026-02-21 03:00 |
| ENQ-000051 | 2026-02-13 15:32 | delay (delay-driven) | BKG000100009 (booking) | departed / 2026-02-21 03:00 | departed / 2026-02-21 03:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000044 | agent_v1 | ai_agent BKG000100009: departed / 2026-02-21 03:00 (ok) | ai_agent BKG000100009: departed / 2026-02-21 03:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000051 | human_baseline | human BKG000100009: departed / 2026-02-20 14:08 (WRONG) | human BKG000100009: departed / 2026-02-20 14:08 (WRONG) | no / 0 | 10.2 | **failed** | S4 |

## BKG000100010 (CUS-00007) NLRTM -> EGPSD

- Delay class: **none** (+0.5 h vs plan)
- Planned: depart 2026-01-25 21:00, arrive 2026-02-18 21:00
- Actual: depart 2026-01-26 02:55, arrive 2026-02-18 21:27, released 2026-02-20 02:43
- Containers: SYNU0000190, SYNU0000204, SYNU0000210; BL SBL000500010 issued 2026-01-27 06:49

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-18 21:00 | 2026-01-15 17:05 |  |
| DEPA | PLN | 2026-01-25 21:00 | 2026-01-15 17:05 |  |
| CONF | ACT | 2026-01-15 17:05 | 2026-01-15 17:43 |  |
| GTIN SYNU0000210 | ACT | 2026-01-23 06:03 | 2026-01-23 06:18 |  |
| GTIN SYNU0000190 | ACT | 2026-01-23 20:11 | 2026-01-23 21:19 |  |
| GTIN SYNU0000204 | ACT | 2026-01-24 10:19 | 2026-01-24 11:22 |  |
| LOAD SYNU0000210 | ACT | 2026-01-25 16:34 | 2026-01-25 17:06 |  |
| DEPA | ACT | 2026-01-26 02:55 | 2026-01-26 03:01 |  |
| LOAD SYNU0000204 | ACT | 2026-01-25 20:57 | 2026-01-26 04:50 |  |
| LOAD SYNU0000190 | ACT | 2026-01-25 19:16 | 2026-01-26 21:10 | yes |
| ISSU | ACT | 2026-01-27 06:49 | 2026-01-27 07:53 |  |
| ARRI | EST | 2026-02-18 21:00 | 2026-02-09 12:48 |  |
| ARRI | EST | 2026-02-18 22:00 | 2026-02-12 22:02 |  |
| ARRI | ACT | 2026-02-18 21:27 | 2026-02-18 21:37 |  |
| DISC SYNU0000190 | ACT | 2026-02-19 01:47 | 2026-02-19 02:24 |  |
| DISC SYNU0000204 | ACT | 2026-02-19 06:04 | 2026-02-19 06:18 |  |
| DISC SYNU0000210 | ACT | 2026-02-19 16:55 | 2026-02-19 18:32 |  |
| RELS | ACT | 2026-02-20 02:43 | 2026-02-20 03:03 |  |
| GTOT SYNU0000190 | ACT | 2026-02-22 05:24 | 2026-02-22 09:11 |  |
| GTOT SYNU0000210 | ACT | 2026-02-22 08:57 | 2026-02-22 09:42 |  |
| GTOT SYNU0000204 | ACT | 2026-02-22 07:14 | 2026-02-22 22:21 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000025 | 2026-01-22 11:55 | delay | BKG000100010 (booking) | booked / 2026-02-18 21:00 | booked / 2026-02-18 21:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000025 | human_baseline | human BKG000100010: booked / 2026-02-18 21:00 (ok) | human BKG000100010: booked / 2026-02-18 21:00 (ok) | no / 0 | 15.6 | **resolved** | S1 |

## BKG000100011 (CUS-00002) FRMRS -> EGPSD

- Delay class: **none** (+0.9 h vs plan)
- Planned: depart 2025-12-15 17:00, arrive 2025-12-27 17:00
- Actual: depart 2025-12-15 20:16, arrive 2025-12-27 17:52, released 2025-12-29 00:17
- Containers: SYNU0000225; BL SBL000500011 issued 2025-12-16 05:21

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2025-12-27 17:00 | 2025-12-07 21:57 |  |
| DEPA | PLN | 2025-12-15 17:00 | 2025-12-07 21:57 |  |
| CONF | ACT | 2025-12-07 21:57 | 2025-12-07 22:02 |  |
| GTIN SYNU0000225 | ACT | 2025-12-14 03:02 | 2025-12-14 03:08 |  |
| LOAD SYNU0000225 | ACT | 2025-12-15 10:44 | 2025-12-15 12:02 |  |
| DEPA | ACT | 2025-12-15 20:16 | 2025-12-15 20:43 |  |
| ISSU | ACT | 2025-12-16 05:21 | 2025-12-16 06:04 |  |
| ARRI | ACT | 2025-12-27 17:52 | 2025-12-27 20:28 |  |
| DISC SYNU0000225 | ACT | 2025-12-28 14:56 | 2025-12-28 17:31 |  |
| RELS | ACT | 2025-12-29 00:17 | 2025-12-29 01:06 |  |
| GTOT SYNU0000225 | ACT | 2025-12-29 14:38 | 2025-12-29 15:45 |  |

_No enquiries in the period._

## BKG000100012 (CUS-00004) SAJED -> AEJEA

- Delay class: **none** (+0.2 h vs plan)
- Planned: depart 2025-12-07 09:00, arrive 2025-12-31 09:00
- Actual: depart 2025-12-07 06:04, arrive 2025-12-31 09:09, released 2026-01-02 08:34
- Containers: SYNU0000230, SYNU0000246, SYNU0000251, SYNU0000267; BL SBL000500012 issued 2025-12-08 23:22

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2025-12-31 09:00 | 2025-11-26 21:01 |  |
| DEPA | PLN | 2025-12-07 09:00 | 2025-11-26 21:01 |  |
| CONF | ACT | 2025-11-26 21:01 | 2025-11-26 21:23 |  |
| GTIN SYNU0000251 | ACT | 2025-12-04 14:38 | 2025-12-04 14:39 |  |
| GTIN SYNU0000267 | ACT | 2025-12-04 12:43 | 2025-12-04 17:58 |  |
| GTIN SYNU0000230 | ACT | 2025-12-05 06:07 | 2025-12-05 06:48 |  |
| GTIN SYNU0000246 | ACT | 2025-12-05 23:11 | 2025-12-05 23:48 |  |
| LOAD SYNU0000230 | ACT | 2025-12-06 18:20 | 2025-12-06 18:32 |  |
| LOAD SYNU0000246 | ACT | 2025-12-07 00:33 | 2025-12-07 01:28 |  |
| LOAD SYNU0000251 | ACT | 2025-12-07 03:29 | 2025-12-07 03:32 |  |
| LOAD SYNU0000267 | ACT | 2025-12-07 01:13 | 2025-12-07 05:23 |  |
| DEPA | ACT | 2025-12-07 06:04 | 2025-12-07 06:11 |  |
| ISSU | ACT | 2025-12-08 23:22 | 2025-12-08 23:34 |  |
| ARRI | EST | 2025-12-31 09:00 | 2025-12-09 05:18 |  |
| ARRI | ACT | 2025-12-31 09:09 | 2025-12-31 09:45 |  |
| DISC SYNU0000230 | ACT | 2025-12-31 22:31 | 2025-12-31 22:56 |  |
| DISC SYNU0000251 | ACT | 2025-12-31 23:22 | 2025-12-31 23:31 |  |
| DISC SYNU0000267 | ACT | 2025-12-31 23:48 | 2026-01-01 00:11 |  |
| DISC SYNU0000246 | ACT | 2026-01-01 02:41 | 2026-01-01 02:57 |  |
| RELS | ACT | 2026-01-02 08:34 | 2026-01-02 08:53 |  |
| GTOT SYNU0000246 | ACT | 2026-01-03 10:21 | 2026-01-03 11:06 |  |
| GTOT SYNU0000251 | ACT | 2026-01-03 11:05 | 2026-01-03 11:13 |  |
| GTOT SYNU0000267 | ACT | 2026-01-03 12:00 | 2026-01-03 12:23 |  |
| GTOT SYNU0000230 | ACT | 2026-01-03 14:45 | 2026-01-03 16:39 |  |

_No enquiries in the period._

## BKG000100013 (CUS-00005) FRMRS -> SGSIN

- Delay class: **none** (+0.7 h vs plan)
- Planned: depart 2026-01-04 07:00, arrive 2026-02-08 07:00
- Actual: depart 2026-01-04 05:36, arrive 2026-02-08 07:42, released 2026-02-09 18:48
- Containers: SYNU0000272, SYNU0000288; BL SBL000500013 issued 2026-01-04 23:54

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-08 07:00 | 2025-12-26 11:51 |  |
| DEPA | PLN | 2026-01-04 07:00 | 2025-12-26 11:51 |  |
| CONF | ACT | 2025-12-26 11:51 | 2025-12-27 08:46 | yes |
| GTIN SYNU0000272 | ACT | 2026-01-02 23:55 | 2026-01-03 00:32 |  |
| GTIN SYNU0000288 | ACT | 2026-01-03 03:59 | 2026-01-03 04:35 |  |
| LOAD SYNU0000288 | ACT | 2026-01-03 19:40 | 2026-01-03 20:01 |  |
| LOAD SYNU0000272 | ACT | 2026-01-03 23:14 | 2026-01-03 23:58 |  |
| DEPA | ACT | 2026-01-04 05:36 | 2026-01-04 06:26 |  |
| ISSU | ACT | 2026-01-04 23:54 | 2026-01-05 00:11 |  |
| ARRI | EST | 2026-02-08 08:00 | 2026-01-17 10:31 |  |
| ARRI | EST | 2026-02-08 08:00 | 2026-02-04 05:58 |  |
| ARRI | ACT | 2026-02-08 07:42 | 2026-02-08 08:03 |  |
| DISC SYNU0000288 | ACT | 2026-02-09 01:54 | 2026-02-09 01:58 |  |
| DISC SYNU0000272 | ACT | 2026-02-09 05:31 | 2026-02-09 06:30 |  |
| RELS | ACT | 2026-02-09 18:48 | 2026-02-09 19:29 |  |
| GTOT SYNU0000272 | ACT | 2026-02-12 08:48 | 2026-02-13 01:33 | yes |
| GTOT SYNU0000288 | ACT | 2026-02-12 11:38 | 2026-02-14 03:28 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000020 | 2026-01-20 23:59 | status | BKG000100022 (other_shipment) | departed / 2026-02-08 08:00 | departed / 2026-02-08 08:00 |
| ENQ-000029 | 2026-01-24 17:25 | status | BKG000100013 (booking, repeat of ENQ-000020) | departed / 2026-02-08 08:00 | departed / 2026-02-08 08:00 |
| ENQ-000046 | 2026-02-08 18:10 | delay | BKG000100013 (booking) | arrived / 2026-02-08 07:42 | arrived / 2026-02-08 07:42 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000020 | agent_v1 | ai_agent BKG000100022: departed / 2026-02-04 23:00 (WRONG) | ai_agent BKG000100022: departed / 2026-02-04 23:00 (WRONG) | no / 0 | 0.0 | **failed** repeat | S6 |
| ENQ-000029 | agent_v1 | ai_agent BKG000100013: departed / 2026-02-08 08:00 (ok) | ai_agent BKG000100013: departed / 2026-02-08 08:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000046 | human_baseline | human BKG000100013: discharged / 2026-02-08 07:42 (ok) | human BKG000100013: discharged / 2026-02-08 07:42 (ok) | no / 0 | 9.1 | **resolved** | S1 |

## BKG000100014 (CUS-00003) EGPSD -> FRMRS

- Delay class: **none** (+0.2 h vs plan)
- Planned: depart 2026-01-12 03:00, arrive 2026-01-26 03:00
- Actual: depart 2026-01-12 05:53, arrive 2026-01-26 03:09, released 2026-01-28 07:33
- Containers: SYNU0000293, SYNU0000307, SYNU0000312; BL SBL000500014 issued 2026-01-13 21:17

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-26 03:00 | 2026-01-01 17:41 |  |
| DEPA | PLN | 2026-01-12 03:00 | 2026-01-01 17:41 |  |
| CONF | ACT | 2026-01-01 17:41 | 2026-01-01 17:50 |  |
| GTIN SYNU0000307 | ACT | 2026-01-09 14:14 | 2026-01-09 14:37 |  |
| GTIN SYNU0000312 | ACT | 2026-01-09 17:14 | 2026-01-09 17:19 |  |
| GTIN SYNU0000293 | ACT | 2026-01-10 18:20 | 2026-01-10 18:31 |  |
| LOAD SYNU0000293 | ACT | 2026-01-11 21:22 | 2026-01-11 21:39 |  |
| LOAD SYNU0000312 | ACT | 2026-01-11 22:07 | 2026-01-11 22:35 |  |
| DEPA | ACT | 2026-01-12 05:53 | 2026-01-12 09:00 |  |
| LOAD SYNU0000307 | ACT | 2026-01-11 22:32 | 2026-01-12 19:09 | yes |
| ISSU | ACT | 2026-01-13 21:17 | 2026-01-13 21:21 |  |
| ARRI | ACT | 2026-01-26 03:09 | 2026-01-26 04:22 |  |
| DISC SYNU0000293 | ACT | 2026-01-26 07:19 | 2026-01-26 07:59 |  |
| DISC SYNU0000307 | ACT | 2026-01-26 08:12 | 2026-01-26 08:16 |  |
| DISC SYNU0000312 | ACT | 2026-01-27 01:23 | 2026-01-27 03:36 |  |
| RELS | ACT | 2026-01-28 07:33 | 2026-01-28 07:36 |  |
| GTOT SYNU0000312 | ACT | 2026-01-30 12:42 | 2026-01-30 13:14 |  |
| GTOT SYNU0000307 | ACT | 2026-01-30 16:31 | 2026-01-30 16:39 |  |
| GTOT SYNU0000293 | ACT | 2026-01-31 00:08 | 2026-01-31 01:00 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000012 | 2026-01-13 07:49 | status | BKG000100014 (booking) | departed / 2026-01-26 03:00 | departed / 2026-01-26 03:00 |
| ENQ-000027 | 2026-01-23 11:39 | status | SYNU0000293 (container) | departed / 2026-01-26 03:00 | departed / 2026-01-26 03:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000012 | human_baseline | human BKG000100014: departed / 2026-01-26 03:00 (ok) | human BKG000100014: departed / 2026-01-26 03:00 (ok) | no / 0 | 7.4 | **resolved** | S1 |
| ENQ-000027 | human_baseline | human BKG000100014: departed / 2026-01-26 03:00 (ok) | human BKG000100014: departed / 2026-01-26 03:00 (ok) | no / 0 | 7.6 | **resolved** | S1 |

## BKG000100015 (CUS-00008) EGPSD -> LBBEY

- Delay class: **short** (+13.2 h vs plan)
- Planned: depart 2026-01-05 13:00, arrive 2026-02-06 13:00
- Actual: depart 2026-01-05 10:37, arrive 2026-02-07 02:14, released 2026-02-07 19:14
- Containers: SYNU0000328; BL SBL000500015 issued 2026-01-06 10:49

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-06 13:00 | 2025-12-22 15:53 |  |
| DEPA | PLN | 2026-01-05 13:00 | 2025-12-22 15:53 |  |
| CONF | ACT | 2025-12-22 15:53 | 2025-12-22 16:42 |  |
| GTIN SYNU0000328 | ACT | 2026-01-02 23:14 | 2026-01-03 13:09 | yes |
| LOAD SYNU0000328 | ACT | 2026-01-05 02:34 | 2026-01-05 20:56 | yes |
| ISSU | ACT | 2026-01-06 10:49 | 2026-01-06 11:19 |  |
| DEPA | ACT | 2026-01-05 10:37 | 2026-01-06 13:24 | yes |
| ARRI | EST | 2026-02-07 03:00 | 2026-01-15 17:28 |  |
| ARRI | ACT | 2026-02-07 02:14 | 2026-02-07 02:36 |  |
| RELS | ACT | 2026-02-07 19:14 | 2026-02-07 19:22 |  |
| DISC SYNU0000328 | ACT | 2026-02-07 23:51 | 2026-02-08 00:11 |  |
| GTOT SYNU0000328 | ACT | 2026-02-09 06:57 | 2026-02-09 07:32 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000019 | 2026-01-19 20:44 | delay | BKG000100015 (booking) | departed / 2026-02-07 03:00 | departed / 2026-02-07 03:00 |
| ENQ-000035 | 2026-01-27 10:34 | delay (delay-driven) | BKG040100015 (typo) | departed / 2026-02-07 03:00 | departed / 2026-02-07 03:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000019 | agent_v1 | ai_agent BKG000100015: departed / 2026-02-07 03:00 (ok) | ai_agent BKG000100015: departed / 2026-02-07 03:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000035 | human_baseline | human BKG000100015: departed / 2026-02-07 03:00 (ok) | human BKG000100015: departed / 2026-02-07 03:00 (ok) | no / 0 | 13.6 | **resolved** | S1 |

## BKG000100016 (CUS-00002) FRMRS -> EGPSD

- Delay class: **none** (-1.9 h vs plan)
- Planned: depart 2026-01-10 23:00, arrive 2026-02-15 23:00
- Actual: depart 2026-01-11 00:35, arrive 2026-02-15 21:04, released 2026-02-17 22:08
- Containers: SYNU0000333; BL SBL000500016 issued 2026-01-11 19:51

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-15 23:00 | 2025-12-30 23:02 |  |
| DEPA | PLN | 2026-01-10 23:00 | 2025-12-30 23:02 |  |
| CONF | ACT | 2025-12-30 23:02 | 2025-12-30 23:39 |  |
| GTIN SYNU0000333 | ACT | 2026-01-09 10:09 | 2026-01-09 10:17 |  |
| LOAD SYNU0000333 | ACT | 2026-01-10 19:30 | 2026-01-10 20:01 |  |
| DEPA | ACT | 2026-01-11 00:35 | 2026-01-11 01:53 |  |
| ISSU | ACT | 2026-01-11 19:51 | 2026-01-11 19:55 |  |
| ARRI | EST | 2026-02-15 20:00 | 2026-02-06 07:57 |  |
| ARRI | ACT | 2026-02-15 21:04 | 2026-02-15 21:36 |  |
| DISC SYNU0000333 | ACT | 2026-02-16 10:13 | 2026-02-16 10:24 |  |
| RELS | ACT | 2026-02-17 22:08 | 2026-02-17 22:14 |  |
| GTOT SYNU0000333 | ACT | 2026-02-20 22:13 | 2026-02-21 06:57 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000005 | 2026-01-08 00:27 | status | SYNU0000333 (container) | booked / 2026-02-15 23:00 | booked / 2026-02-15 23:00 |
| ENQ-000023 | 2026-01-22 06:56 | status | SBL000500016 (bl) | departed / 2026-02-15 23:00 | departed / 2026-02-15 23:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000005 | human_baseline | human BKG000100016: booked / 2026-02-15 23:00 (ok) | human BKG000100016: booked / 2026-02-15 23:00 (ok) | no / 0 | 6.8 | **resolved** | S1 |
| ENQ-000023 | human_baseline | human BKG000100016: departed / 2026-02-15 23:00 (ok) | human BKG000100016: departed / 2026-02-15 23:00 (ok) | no / 0 | 8.2 | **resolved** | S1 |

## BKG000100017 (CUS-00008) FRMRS -> LBBEY

- Delay class: **none** (-0.4 h vs plan)
- Planned: depart 2026-01-08 00:00, arrive 2026-02-15 00:00
- Actual: depart 2026-01-07 22:10, arrive 2026-02-14 23:34, released 2026-02-16 21:33
- Containers: SYNU0000349, SYNU0000354; BL SBL000500017 issued 2026-01-09 05:48

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-15 00:00 | 2025-12-29 05:50 |  |
| DEPA | PLN | 2026-01-08 00:00 | 2025-12-29 05:50 |  |
| CONF | ACT | 2025-12-29 05:50 | 2025-12-29 06:22 |  |
| GTIN SYNU0000354 | ACT | 2026-01-06 16:20 | 2026-01-06 17:00 |  |
| GTIN SYNU0000349 | ACT | 2026-01-06 17:34 | 2026-01-06 18:59 |  |
| LOAD SYNU0000354 | ACT | 2026-01-07 17:03 | 2026-01-07 17:12 |  |
| LOAD SYNU0000349 | ACT | 2026-01-07 18:25 | 2026-01-07 18:30 |  |
| DEPA | ACT | 2026-01-07 22:10 | 2026-01-07 22:24 |  |
| ISSU | ACT | 2026-01-09 05:48 | 2026-01-09 06:15 |  |
| ARRI | ACT | 2026-02-14 23:34 | 2026-02-14 23:37 |  |
| DISC SYNU0000349 | ACT | 2026-02-15 17:20 | 2026-02-15 22:52 |  |
| DISC SYNU0000354 | ACT | 2026-02-15 19:28 | 2026-02-16 04:36 | yes |
| RELS | ACT | 2026-02-16 21:33 | 2026-02-16 22:47 |  |
| GTOT SYNU0000354 | ACT | 2026-02-19 06:45 | 2026-02-19 07:01 |  |
| GTOT SYNU0000349 | ACT | 2026-02-19 08:02 | 2026-02-19 08:36 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000008 | 2026-01-11 19:07 | status | SBL000500017 (bl) | departed / 2026-02-15 00:00 | departed / 2026-02-15 00:00 |
| ENQ-000034 | 2026-01-27 05:27 | delay | BKG000100017 (booking) | departed / 2026-02-15 00:00 | departed / 2026-02-15 00:00 |
| ENQ-000048 | 2026-02-09 03:06 | status | BKG000102017 (typo) | departed / 2026-02-15 00:00 | departed / 2026-02-15 00:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000008 | agent_v1 | ai_agent BKG000100017: departed / 2026-02-15 00:00 (ok) | ai_agent BKG000100017: departed / 2026-02-15 00:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |
| ENQ-000034 | human_baseline | human BKG000100017: departed / 2026-02-15 00:00 (ok) | human BKG000100017: departed / 2026-02-15 00:00 (ok) | no / 0 | 3.5 | **resolved** | S1 |
| ENQ-000048 | human_baseline | human BKG000100017: departed / 2026-02-15 00:00 (ok) | human BKG000100017: departed / 2026-02-15 00:00 (ok) | no / 0 | 9.8 | **resolved** | S1 |

## BKG000100018 (CUS-00003) AEJEA -> CNSHA

- Delay class: **none** (+0.6 h vs plan)
- Planned: depart 2025-12-10 20:00, arrive 2026-01-10 20:00
- Actual: depart 2025-12-10 17:07, arrive 2026-01-10 20:33, released 2026-01-11 20:42
- Containers: SYNU0000360, SYNU0000375, SYNU0000380, SYNU0000396; BL SBL000500018 issued 2025-12-11 16:56

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-10 20:00 | 2025-11-27 12:16 |  |
| DEPA | PLN | 2025-12-10 20:00 | 2025-11-27 12:16 |  |
| CONF | ACT | 2025-11-27 12:16 | 2025-11-27 12:32 |  |
| GTIN SYNU0000375 | ACT | 2025-12-08 03:40 | 2025-12-08 04:00 |  |
| GTIN SYNU0000396 | ACT | 2025-12-08 21:22 | 2025-12-08 21:25 |  |
| GTIN SYNU0000360 | ACT | 2025-12-08 18:04 | 2025-12-09 18:46 | yes |
| GTIN SYNU0000380 | ACT | 2025-12-08 13:13 | 2025-12-10 04:40 | yes |
| LOAD SYNU0000360 | ACT | 2025-12-10 06:22 | 2025-12-10 07:03 |  |
| LOAD SYNU0000380 | ACT | 2025-12-10 07:52 | 2025-12-10 08:51 |  |
| LOAD SYNU0000375 | ACT | 2025-12-10 12:58 | 2025-12-10 13:03 |  |
| LOAD SYNU0000396 | ACT | 2025-12-10 14:34 | 2025-12-10 15:22 |  |
| DEPA | ACT | 2025-12-10 17:07 | 2025-12-10 19:36 |  |
| ISSU | ACT | 2025-12-11 16:56 | 2025-12-11 17:17 |  |
| ARRI | EST | 2026-01-10 21:00 | 2025-12-28 03:40 |  |
| ARRI | ACT | 2026-01-10 20:33 | 2026-01-11 02:19 |  |
| DISC SYNU0000360 | ACT | 2026-01-11 01:09 | 2026-01-11 02:21 |  |
| DISC SYNU0000396 | ACT | 2026-01-11 03:34 | 2026-01-11 03:57 |  |
| DISC SYNU0000380 | ACT | 2026-01-11 03:22 | 2026-01-11 04:15 |  |
| DISC SYNU0000375 | ACT | 2026-01-11 05:01 | 2026-01-11 11:55 |  |
| RELS | ACT | 2026-01-11 20:42 | 2026-01-11 22:19 |  |
| GTOT SYNU0000380 | ACT | 2026-01-14 16:09 | 2026-01-14 16:35 |  |
| GTOT SYNU0000360 | ACT | 2026-01-15 07:09 | 2026-01-15 09:14 |  |
| GTOT SYNU0000375 | ACT | 2026-01-15 09:40 | 2026-01-15 23:59 | yes |
| GTOT SYNU0000396 | ACT | 2026-01-14 20:17 | 2026-01-16 16:48 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000013 | 2026-01-13 11:19 | status | BKG000100018 (booking) | released / 2026-01-10 20:33 | released / 2026-01-10 20:33 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000013 | human_baseline | human BKG000100018: released / 2026-01-10 20:33 (ok) | human BKG000100018: released / 2026-01-10 20:33 (ok) | no / 0 | 8.2 | **resolved** | S1 |

## BKG000100019 (CUS-00006) CNSHA -> FRMRS

- Delay class: **none** (+0.2 h vs plan)
- Planned: depart 2026-01-20 09:00, arrive 2026-02-03 09:00
- Actual: depart 2026-01-20 09:27, arrive 2026-02-03 09:12, released 2026-02-05 18:20
- Containers: SYNU0000400; BL SBL000500019 issued 2026-01-22 04:06

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-03 09:00 | 2026-01-10 23:28 |  |
| DEPA | PLN | 2026-01-20 09:00 | 2026-01-10 23:28 |  |
| CONF | ACT | 2026-01-10 23:28 | 2026-01-11 02:00 |  |
| GTIN SYNU0000400 | ACT | 2026-01-17 16:04 | 2026-01-17 16:10 |  |
| LOAD SYNU0000400 | ACT | 2026-01-20 07:04 | 2026-01-20 07:11 |  |
| DEPA | ACT | 2026-01-20 09:27 | 2026-01-20 09:31 |  |
| ISSU | ACT | 2026-01-22 04:06 | 2026-01-22 04:10 |  |
| ARRI | EST | 2026-02-03 09:00 | 2026-02-01 04:26 |  |
| ARRI | ACT | 2026-02-03 09:12 | 2026-02-03 17:52 |  |
| DISC SYNU0000400 | ACT | 2026-02-03 14:42 | 2026-02-03 19:38 |  |
| RELS | ACT | 2026-02-05 18:20 | 2026-02-05 19:06 |  |
| GTOT SYNU0000400 | ACT | 2026-02-08 12:09 | 2026-02-08 12:16 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000026 | 2026-01-22 15:43 | delay | BKG004100019 (typo) | departed / 2026-02-03 09:00 | departed / 2026-02-03 09:00 |
| ENQ-000039 | 2026-01-29 21:57 | status | BKG000100019 (booking) | departed / 2026-02-03 09:00 | departed / 2026-02-03 09:00 |
| ENQ-000047 | 2026-02-08 21:07 | delay | BKG000100019 (booking) | gated_out / 2026-02-03 09:12 | gated_out / 2026-02-03 09:12 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000026 | agent_v1 | human BKG000100019: departed / 2026-02-03 09:00 (ok) | human BKG000100019: departed / 2026-02-03 09:00 (ok) | no / 0 | 9.3 | **resolved** handoff | S1 |
| ENQ-000039 | human_baseline | human BKG000100019: departed / 2026-02-03 09:00 (ok) | human BKG000100019: departed / 2026-02-03 09:00 (ok) | no / 0 | 14.1 | **resolved** | S1 |
| ENQ-000047 | human_baseline | human BKG000100019: gated_out / 2026-02-03 09:12 (ok) | human BKG000100019: gated_out / 2026-02-03 09:12 (ok) | no / 0 | 6.6 | **resolved** | S1 |

## BKG000100020 (CUS-00004) CNSHA -> LBBEY

- Delay class: **none** (+0.6 h vs plan)
- Planned: depart 2025-12-14 03:00, arrive 2025-12-29 03:00
- Actual: depart 2025-12-14 03:01, arrive 2025-12-29 03:38, released 2025-12-31 05:19
- Containers: SYNU0000415, SYNU0000420; BL SBL000500020 issued 2025-12-15 15:32

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2025-12-29 03:00 | 2025-11-23 11:11 |  |
| DEPA | PLN | 2025-12-14 03:00 | 2025-11-23 11:11 |  |
| CONF | ACT | 2025-11-23 11:11 | 2025-11-23 11:17 |  |
| GTIN SYNU0000415 | ACT | 2025-12-11 05:14 | 2025-12-11 05:36 |  |
| GTIN SYNU0000420 | ACT | 2025-12-11 22:49 | 2025-12-11 23:06 |  |
| LOAD SYNU0000415 | ACT | 2025-12-13 15:25 | 2025-12-13 19:37 |  |
| LOAD SYNU0000420 | ACT | 2025-12-13 19:58 | 2025-12-13 22:24 |  |
| DEPA | ACT | 2025-12-14 03:01 | 2025-12-15 15:30 | yes |
| ISSU | ACT | 2025-12-15 15:32 | 2025-12-15 15:42 |  |
| ARRI | EST | 2025-12-29 04:00 | 2025-12-27 12:44 |  |
| ARRI | ACT | 2025-12-29 03:38 | 2025-12-29 04:03 |  |
| DISC SYNU0000420 | ACT | 2025-12-29 08:23 | 2025-12-29 08:35 |  |
| DISC SYNU0000415 | ACT | 2025-12-29 14:09 | 2025-12-29 14:11 |  |
| RELS | ACT | 2025-12-31 05:19 | 2025-12-31 05:40 |  |
| GTOT SYNU0000415 | ACT | 2026-01-02 06:21 | 2026-01-02 06:50 |  |
| GTOT SYNU0000420 | ACT | 2026-01-02 12:26 | 2026-01-02 13:24 |  |

_No enquiries in the period._

## BKG000100021 (CUS-00001) NLRTM -> CNSHA

- Delay class: **short** (+8.0 h vs plan)
- Planned: depart 2026-01-12 22:00, arrive 2026-02-13 22:00
- Actual: depart 2026-01-13 02:00, arrive 2026-02-14 05:57, released 2026-02-16 20:31
- Containers: SYNU0000436, SYNU0000441, SYNU0000457; BL SBL000500021 issued 2026-01-13 14:50

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-13 22:00 | 2026-01-05 18:08 |  |
| DEPA | PLN | 2026-01-12 22:00 | 2026-01-05 18:08 |  |
| CONF | ACT | 2026-01-05 18:08 | 2026-01-05 18:22 |  |
| GTIN SYNU0000441 | ACT | 2026-01-10 07:00 | 2026-01-10 07:08 |  |
| GTIN SYNU0000436 | ACT | 2026-01-10 07:45 | 2026-01-10 08:18 |  |
| GTIN SYNU0000457 | ACT | 2026-01-11 21:33 | 2026-01-11 22:07 |  |
| LOAD SYNU0000457 | ACT | 2026-01-12 19:08 | 2026-01-12 19:55 |  |
| LOAD SYNU0000436 | ACT | 2026-01-12 20:21 | 2026-01-12 20:46 |  |
| LOAD SYNU0000441 | ACT | 2026-01-12 20:47 | 2026-01-12 20:58 |  |
| DEPA | ACT | 2026-01-13 02:00 | 2026-01-13 02:43 |  |
| ISSU | ACT | 2026-01-13 14:50 | 2026-01-13 15:09 |  |
| ARRI | EST | 2026-02-14 06:00 | 2026-02-13 11:27 |  |
| ARRI | ACT | 2026-02-14 05:57 | 2026-02-14 06:55 |  |
| DISC SYNU0000441 | ACT | 2026-02-14 18:00 | 2026-02-14 18:21 |  |
| DISC SYNU0000457 | ACT | 2026-02-14 19:51 | 2026-02-14 20:17 |  |
| DISC SYNU0000436 | ACT | 2026-02-15 02:31 | 2026-02-15 03:27 |  |
| RELS | ACT | 2026-02-16 20:31 | 2026-02-17 14:11 |  |
| GTOT SYNU0000457 | ACT | 2026-02-17 13:41 | 2026-02-17 14:13 |  |
| GTOT SYNU0000441 | ACT | 2026-02-17 13:50 | 2026-02-17 15:50 |  |
| GTOT SYNU0000436 | ACT | 2026-02-17 14:31 | 2026-02-17 19:18 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000028 | 2026-01-24 13:27 | documents | BKG000100021 (booking) | departed / 2026-02-13 22:00 | departed / 2026-02-13 22:00 |
| ENQ-000045 | 2026-02-07 10:36 | delay | BKG000100021 (booking) | departed / 2026-02-13 22:00 | departed / 2026-02-13 22:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000028 | agent_v1 | human ?: None / - (WRONG) | human ?: None / - (WRONG) | no / 0 | 14.1 | **out_of_scope** handoff | S12 |
| ENQ-000045 | agent_v1 | ai_agent BKG000100021: departed / 2026-02-13 22:00 (ok) | ai_agent BKG000100021: departed / 2026-02-13 22:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100022 (CUS-00005) EGPSD -> SAJED

- Delay class: **short** (+4.2 h vs plan)
- Planned: depart 2025-12-30 23:00, arrive 2026-02-04 23:00
- Actual: depart 2025-12-31 01:51, arrive 2026-02-05 03:10, released 2026-02-06 13:38
- Containers: SYNU0000462, SYNU0000478; BL SBL000500022 issued 2025-12-31 09:00

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-04 23:00 | 2025-12-16 13:13 |  |
| DEPA | PLN | 2025-12-30 23:00 | 2025-12-16 13:13 |  |
| CONF | ACT | 2025-12-16 13:13 | 2025-12-16 13:15 |  |
| GTIN SYNU0000462 | ACT | 2025-12-28 21:18 | 2025-12-28 23:00 |  |
| GTIN SYNU0000478 | ACT | 2025-12-29 23:10 | 2025-12-29 23:19 |  |
| LOAD SYNU0000478 | ACT | 2025-12-30 17:20 | 2025-12-30 21:37 |  |
| LOAD SYNU0000462 | ACT | 2025-12-30 23:24 | 2025-12-30 23:26 |  |
| DEPA | ACT | 2025-12-31 01:51 | 2025-12-31 02:17 |  |
| ISSU | ACT | 2025-12-31 09:00 | 2025-12-31 09:10 |  |
| ARRI | EST | 2026-02-05 03:00 | 2026-01-29 10:19 |  |
| ARRI | ACT | 2026-02-05 03:10 | 2026-02-05 03:15 |  |
| DISC SYNU0000462 | ACT | 2026-02-05 08:20 | 2026-02-05 08:28 |  |
| DISC SYNU0000478 | ACT | 2026-02-05 23:20 | 2026-02-05 23:48 |  |
| RELS | ACT | 2026-02-06 13:38 | 2026-02-06 15:50 |  |
| GTOT SYNU0000462 | ACT | 2026-02-08 04:01 | 2026-02-08 04:23 |  |
| GTOT SYNU0000478 | ACT | 2026-02-08 21:10 | 2026-02-10 16:49 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000010 | 2026-01-12 10:18 | status | BKG000100022 (booking) | departed / 2026-02-04 23:00 | departed / 2026-02-04 23:00 |
| ENQ-000011 | 2026-01-12 15:26 | status | BKG000100022 (booking, repeat of ENQ-000010) | departed / 2026-02-04 23:00 | departed / 2026-02-04 23:00 |
| ENQ-000042 | 2026-02-02 20:05 | status | BKG000100022 (booking) | departed / 2026-02-05 03:00 | departed / 2026-02-05 03:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000010 | human_baseline | human BKG000100022: departed / 2026-02-04 23:00 (ok) | human BKG000100022: departed / 2026-02-04 23:00 (ok) | no / 0 | 10.3 | **failed** repeat | S8 |
| ENQ-000011 | human_baseline | human BKG000100022: departed / 2026-02-04 23:00 (ok) | human BKG000100022: departed / 2026-02-04 23:00 (ok) | no / 0 | 4.6 | **resolved** | S1 |
| ENQ-000042 | agent_v1 | ai_agent BKG000100022: departed / 2026-02-05 03:00 (ok) | ai_agent BKG000100022: departed / 2026-02-05 03:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100023 (CUS-00006) LBBEY -> FRMRS

- Delay class: **short** (+5.5 h vs plan)
- Planned: depart 2025-12-28 19:00, arrive 2026-01-25 19:00
- Actual: depart 2025-12-28 16:57, arrive 2026-01-26 00:28, released 2026-01-27 18:09
- Containers: SYNU0000483, SYNU0000499; BL SBL000500023 issued 2025-12-30 16:53

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-25 19:00 | 2025-12-20 16:03 |  |
| DEPA | PLN | 2025-12-28 19:00 | 2025-12-20 16:03 |  |
| CONF | ACT | 2025-12-20 16:03 | 2025-12-20 17:24 |  |
| GTIN SYNU0000499 | ACT | 2025-12-27 13:25 | 2025-12-27 14:24 |  |
| GTIN SYNU0000483 | ACT | 2025-12-26 08:03 | 2025-12-27 16:32 | yes |
| LOAD SYNU0000499 | ACT | 2025-12-28 12:53 | 2025-12-28 13:02 |  |
| DEPA | ACT | 2025-12-28 16:57 | 2025-12-28 17:02 |  |
| LOAD SYNU0000483 | ACT | 2025-12-28 13:49 | 2025-12-29 12:20 | yes |
| ISSU | ACT | 2025-12-30 16:53 | 2025-12-30 17:01 |  |
| ARRI | EST | 2026-01-25 22:00 | 2026-01-09 05:11 |  |
| ARRI | EST | 2026-01-26 00:00 | 2026-01-20 22:08 |  |
| ARRI | EST | 2026-01-26 00:00 | 2026-01-23 19:13 |  |
| ARRI | ACT | 2026-01-26 00:28 | 2026-01-26 02:51 |  |
| DISC SYNU0000499 | ACT | 2026-01-26 18:56 | 2026-01-26 19:02 |  |
| DISC SYNU0000483 | ACT | 2026-01-26 20:08 | 2026-01-26 20:17 |  |
| RELS | ACT | 2026-01-27 18:09 | 2026-01-27 18:21 |  |
| GTOT SYNU0000483 | ACT | 2026-01-30 05:45 | 2026-01-30 08:58 |  |
| GTOT SYNU0000499 | ACT | 2026-01-30 02:39 | 2026-01-30 21:57 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000007 | 2026-01-11 16:33 | delay (delay-driven) | SBL000500023 (bl) | departed / 2026-01-25 22:00 | departed / 2026-01-25 22:00 |
| ENQ-000016 | 2026-01-18 18:20 | delay (delay-driven) | BKG000100023 (booking) | departed / 2026-01-25 22:00 | departed / 2026-01-25 22:00 |
| ENQ-000033 | 2026-01-27 04:30 | delay (delay-driven) | BKG000100023 (booking) | discharged / 2026-01-26 00:28 | discharged / 2026-01-26 00:28 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000007 | human_baseline | human BKG000100023: departed / 2026-01-25 22:00 (ok) | human BKG000100023: departed / 2026-01-25 22:00 (ok) | no / 0 | 8.8 | **resolved** | S1 |
| ENQ-000016 | human_baseline | human BKG000100023: departed / 2026-01-25 22:00 (ok) | human BKG000100023: departed / 2026-01-25 22:00 (ok) | no / 0 | 7.0 | **resolved** | S1 |
| ENQ-000033 | agent_v1 | ai_agent BKG000100023: discharged / 2026-01-26 00:28 (ok) | ai_agent BKG000100023: discharged / 2026-01-26 00:28 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100024 (CUS-00007) LBBEY -> AEJEA

- Delay class: **none** (-0.6 h vs plan)
- Planned: depart 2025-12-15 10:00, arrive 2026-01-12 10:00
- Actual: depart 2025-12-15 07:13, arrive 2026-01-12 09:25, released 2026-01-14 03:52
- Containers: SYNU0000502, SYNU0000518, SYNU0000523; BL SBL000500024 issued 2025-12-16 18:22

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-12 10:00 | 2025-11-26 06:05 |  |
| DEPA | PLN | 2025-12-15 10:00 | 2025-11-26 06:05 |  |
| CONF | ACT | 2025-11-26 06:05 | 2025-11-26 06:50 |  |
| GTIN SYNU0000523 | ACT | 2025-12-12 14:25 | 2025-12-12 16:13 |  |
| GTIN SYNU0000502 | ACT | 2025-12-12 19:11 | 2025-12-12 20:22 |  |
| GTIN SYNU0000518 | ACT | 2025-12-13 04:34 | 2025-12-13 05:22 |  |
| LOAD SYNU0000518 | ACT | 2025-12-15 00:39 | 2025-12-15 01:06 |  |
| LOAD SYNU0000523 | ACT | 2025-12-14 23:43 | 2025-12-15 01:46 |  |
| LOAD SYNU0000502 | ACT | 2025-12-15 04:26 | 2025-12-15 04:35 |  |
| DEPA | ACT | 2025-12-15 07:13 | 2025-12-15 08:04 |  |
| ISSU | ACT | 2025-12-16 18:22 | 2025-12-16 18:29 |  |
| ARRI | ACT | 2026-01-12 09:25 | 2026-01-12 11:25 |  |
| DISC SYNU0000502 | ACT | 2026-01-12 19:03 | 2026-01-12 19:30 |  |
| DISC SYNU0000523 | ACT | 2026-01-13 05:57 | 2026-01-13 06:06 |  |
| RELS | ACT | 2026-01-14 03:52 | 2026-01-14 04:10 |  |
| DISC SYNU0000518 | ACT | 2026-01-12 22:15 | 2026-01-14 13:45 | yes |
| GTOT SYNU0000518 | ACT | 2026-01-15 14:36 | 2026-01-15 14:43 |  |
| GTOT SYNU0000523 | ACT | 2026-01-15 06:12 | 2026-01-16 18:53 | yes |
| GTOT SYNU0000502 | ACT | 2026-01-15 10:12 | 2026-01-17 01:21 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000001 | 2026-01-02 08:30 | other | BKG000100010 (other_shipment) | departed / 2026-01-12 10:00 | departed / 2026-01-12 10:00 |
| ENQ-000009 | 2026-01-12 05:12 | delay | BKG000100024 (booking) | departed / 2026-01-12 10:00 | departed / 2026-01-12 10:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000001 | human_baseline | human ?: None / - (WRONG) | human ?: None / - (WRONG) | no / 0 | 3.7 | **out_of_scope** | S12 |
| ENQ-000009 | agent_v1 | ai_agent BKG000100024: departed / 2026-01-12 10:00 (ok) | ai_agent BKG000100024: departed / 2026-01-12 10:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

## BKG000100025 (CUS-00002) LBBEY -> EGPSD

- Delay class: **long** (+39.2 h vs plan)
- Planned: depart 2026-01-04 10:00, arrive 2026-01-22 10:00
- Actual: depart 2026-01-04 12:34, arrive 2026-01-24 01:15, released 2026-01-24 23:59
- Containers: SYNU0000539, SYNU0000544; BL SBL000500025 issued 2026-01-05 01:41

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-22 10:00 | 2025-12-15 01:53 |  |
| DEPA | PLN | 2026-01-04 10:00 | 2025-12-15 01:53 |  |
| CONF | ACT | 2025-12-15 01:53 | 2025-12-15 02:27 |  |
| GTIN SYNU0000544 | ACT | 2026-01-01 22:41 | 2026-01-01 22:52 |  |
| GTIN SYNU0000539 | ACT | 2026-01-02 05:08 | 2026-01-02 05:26 |  |
| LOAD SYNU0000544 | ACT | 2026-01-04 05:21 | 2026-01-04 05:44 |  |
| DEPA | ACT | 2026-01-04 12:34 | 2026-01-04 14:51 |  |
| LOAD SYNU0000539 | ACT | 2026-01-04 05:22 | 2026-01-05 02:10 | yes |
| ISSU | ACT | 2026-01-05 01:41 | 2026-01-05 02:18 |  |
| ARRI | EST | 2026-01-23 00:00 | 2026-01-10 20:07 |  |
| ARRI | EST | 2026-01-23 11:00 | 2026-01-18 11:06 |  |
| ARRI | EST | 2026-01-24 00:00 | 2026-01-23 03:54 |  |
| ARRI | ACT | 2026-01-24 01:15 | 2026-01-24 01:24 |  |
| RELS | ACT | 2026-01-24 23:59 | 2026-01-25 01:07 |  |
| DISC SYNU0000544 | ACT | 2026-01-25 00:48 | 2026-01-25 01:36 |  |
| DISC SYNU0000539 | ACT | 2026-01-24 19:35 | 2026-01-25 02:03 | yes |
| GTOT SYNU0000544 | ACT | 2026-01-25 12:08 | 2026-01-25 12:25 |  |
| GTOT SYNU0000539 | ACT | 2026-01-25 14:38 | 2026-01-26 04:07 | yes |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000006 | 2026-01-10 14:57 | status | BKG000100025 (booking) | departed / 2026-01-22 10:00 | departed / 2026-01-22 10:00 |
| ENQ-000018 | 2026-01-19 04:42 | delay (delay-driven) | SYNU0000539 (container) | departed / 2026-01-23 11:00 | departed / 2026-01-23 11:00 |
| ENQ-000022 | 2026-01-21 16:13 | delay | BKG000100025 (booking, repeat of ENQ-000018) | departed / 2026-01-23 11:00 | departed / 2026-01-23 11:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000006 | human_baseline | human BKG000100025: departed / 2026-01-23 00:00 (ok) | human BKG000100025: departed / 2026-01-23 00:00 (ok) | no / 0 | 7.9 | **resolved** | S1 |
| ENQ-000018 | agent_v1 | ai_agent BKG000100025: departed / 2026-01-23 11:00 (ok) | human BKG000100025: departed / 2026-01-23 11:00 (ok) | yes / 1 | 22.4 | **failed** rescued repeat | S10 |
| ENQ-000022 | agent_v1 | ai_agent BKG000100025: departed / 2026-01-23 11:00 (ok) | human BKG000100025: departed / 2026-01-23 11:00 (ok) | yes / 1 | 21.7 | **failed** rescued | S10 |

## BKG000100026 (CUS-00006) CNSHA -> AEJEA

- Delay class: **none** (-1.8 h vs plan)
- Planned: depart 2025-12-27 23:00, arrive 2026-02-05 23:00
- Actual: depart 2025-12-28 02:32, arrive 2026-02-05 21:14, released 2026-02-08 01:24
- Containers: SYNU0000550; BL SBL000500026 issued 2025-12-29 22:14

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-05 23:00 | 2025-12-17 17:31 |  |
| DEPA | PLN | 2025-12-27 23:00 | 2025-12-17 17:31 |  |
| CONF | ACT | 2025-12-17 17:31 | 2025-12-17 17:59 |  |
| GTIN SYNU0000550 | ACT | 2025-12-25 09:29 | 2025-12-25 09:47 |  |
| LOAD SYNU0000550 | ACT | 2025-12-27 20:46 | 2025-12-27 21:04 |  |
| DEPA | ACT | 2025-12-28 02:32 | 2025-12-28 04:17 |  |
| ISSU | ACT | 2025-12-29 22:14 | 2025-12-29 22:15 |  |
| ARRI | EST | 2026-02-05 21:00 | 2026-01-16 07:43 |  |
| ARRI | EST | 2026-02-05 21:00 | 2026-01-24 20:00 |  |
| ARRI | ACT | 2026-02-05 21:14 | 2026-02-05 21:32 |  |
| DISC SYNU0000550 | ACT | 2026-02-06 06:33 | 2026-02-07 16:09 | yes |
| RELS | ACT | 2026-02-08 01:24 | 2026-02-08 01:33 |  |
| GTOT SYNU0000550 | ACT | 2026-02-10 15:11 | 2026-02-10 15:34 |  |

_No enquiries in the period._

## BKG000100027 (CUS-00004) FRMRS -> NLRTM

- Delay class: **none** (+1.0 h vs plan)
- Planned: depart 2025-12-11 08:00, arrive 2026-01-17 08:00
- Actual: depart 2025-12-11 06:55, arrive 2026-01-17 08:57, released 2026-01-18 07:43
- Containers: SYNU0000565, SYNU0000570, SYNU0000586, SYNU0000591; BL SBL000500027 issued 2025-12-12 09:01

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-01-17 08:00 | 2025-12-02 02:13 |  |
| DEPA | PLN | 2025-12-11 08:00 | 2025-12-02 02:13 |  |
| CONF | ACT | 2025-12-02 02:13 | 2025-12-02 03:15 |  |
| GTIN SYNU0000586 | ACT | 2025-12-08 14:26 | 2025-12-08 14:34 |  |
| GTIN SYNU0000565 | ACT | 2025-12-08 22:19 | 2025-12-08 22:45 |  |
| GTIN SYNU0000591 | ACT | 2025-12-09 09:08 | 2025-12-09 14:43 |  |
| GTIN SYNU0000570 | ACT | 2025-12-10 03:57 | 2025-12-10 04:10 |  |
| LOAD SYNU0000591 | ACT | 2025-12-10 19:30 | 2025-12-10 20:23 |  |
| LOAD SYNU0000570 | ACT | 2025-12-11 03:34 | 2025-12-11 03:39 |  |
| LOAD SYNU0000565 | ACT | 2025-12-11 04:01 | 2025-12-11 04:08 |  |
| LOAD SYNU0000586 | ACT | 2025-12-11 04:48 | 2025-12-11 04:50 |  |
| DEPA | ACT | 2025-12-11 06:55 | 2025-12-11 08:37 |  |
| ISSU | ACT | 2025-12-12 09:01 | 2025-12-12 09:26 |  |
| ARRI | EST | 2026-01-17 09:00 | 2025-12-15 15:51 |  |
| ARRI | EST | 2026-01-17 10:00 | 2025-12-16 13:40 |  |
| ARRI | EST | 2026-01-17 09:00 | 2025-12-28 22:08 |  |
| ARRI | ACT | 2026-01-17 08:57 | 2026-01-17 10:04 |  |
| DISC SYNU0000591 | ACT | 2026-01-17 20:07 | 2026-01-17 20:53 |  |
| DISC SYNU0000586 | ACT | 2026-01-18 01:57 | 2026-01-18 02:39 |  |
| DISC SYNU0000565 | ACT | 2026-01-18 06:25 | 2026-01-18 06:52 |  |
| RELS | ACT | 2026-01-18 07:43 | 2026-01-18 08:09 |  |
| DISC SYNU0000570 | ACT | 2026-01-18 05:20 | 2026-01-18 10:48 |  |
| GTOT SYNU0000565 | ACT | 2026-01-19 18:20 | 2026-01-19 18:40 |  |
| GTOT SYNU0000586 | ACT | 2026-01-20 07:29 | 2026-01-20 08:14 |  |
| GTOT SYNU0000591 | ACT | 2026-01-20 10:04 | 2026-01-20 10:19 |  |
| GTOT SYNU0000570 | ACT | 2026-01-20 02:01 | 2026-01-21 23:35 | yes |

_No enquiries in the period._

## BKG000100028 (CUS-00001) LBBEY -> SGSIN

- Delay class: **short** (+4.5 h vs plan)
- Planned: depart 2026-01-23 03:00, arrive 2026-02-12 03:00
- Actual: depart 2026-01-23 00:32, arrive 2026-02-12 07:32, released 2026-02-13 23:19
- Containers: SYNU0000605, SYNU0000610, SYNU0000626, SYNU0000631; BL SBL000500028 issued 2026-01-23 17:55

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-12 03:00 | 2026-01-16 00:47 |  |
| DEPA | PLN | 2026-01-23 03:00 | 2026-01-16 00:47 |  |
| CONF | ACT | 2026-01-16 00:47 | 2026-01-16 01:00 |  |
| GTIN SYNU0000605 | ACT | 2026-01-20 03:22 | 2026-01-20 03:47 |  |
| GTIN SYNU0000631 | ACT | 2026-01-20 03:35 | 2026-01-20 05:16 |  |
| GTIN SYNU0000610 | ACT | 2026-01-20 23:59 | 2026-01-21 00:27 |  |
| GTIN SYNU0000626 | ACT | 2026-01-21 09:51 | 2026-01-21 12:48 |  |
| LOAD SYNU0000610 | ACT | 2026-01-22 14:59 | 2026-01-22 15:06 |  |
| LOAD SYNU0000631 | ACT | 2026-01-22 16:31 | 2026-01-22 16:44 |  |
| DEPA | ACT | 2026-01-23 00:32 | 2026-01-23 04:59 |  |
| LOAD SYNU0000605 | ACT | 2026-01-22 20:22 | 2026-01-23 22:37 | yes |
| LOAD SYNU0000626 | ACT | 2026-01-22 16:27 | 2026-01-24 11:23 | yes |
| ISSU | ACT | 2026-01-23 17:55 | 2026-01-24 11:38 | yes |
| ARRI | EST | 2026-02-12 03:00 | 2026-01-27 00:26 |  |
| ARRI | EST | 2026-02-12 07:00 | 2026-02-04 21:50 |  |
| ARRI | EST | 2026-02-12 08:00 | 2026-02-10 09:16 |  |
| ARRI | ACT | 2026-02-12 07:32 | 2026-02-12 07:56 |  |
| DISC SYNU0000626 | ACT | 2026-02-12 14:42 | 2026-02-12 14:48 |  |
| DISC SYNU0000610 | ACT | 2026-02-12 22:57 | 2026-02-12 23:03 |  |
| DISC SYNU0000605 | ACT | 2026-02-13 01:01 | 2026-02-13 01:56 |  |
| DISC SYNU0000631 | ACT | 2026-02-12 22:27 | 2026-02-13 12:32 | yes |
| RELS | ACT | 2026-02-13 23:19 | 2026-02-14 00:40 |  |
| GTOT SYNU0000631 | ACT | 2026-02-15 00:19 | 2026-02-15 00:30 |  |
| GTOT SYNU0000610 | ACT | 2026-02-15 05:30 | 2026-02-15 05:58 |  |
| GTOT SYNU0000626 | ACT | 2026-02-15 10:23 | 2026-02-15 10:25 |  |
| GTOT SYNU0000605 | ACT | 2026-02-15 16:34 | 2026-02-15 17:33 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000041 | 2026-02-02 17:11 | delay | BKG000100628 (typo) | departed / 2026-02-12 03:00 | departed / 2026-02-12 03:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000041 | agent_v1 | human BKG000100028: departed / 2026-02-12 03:00 (ok) | human BKG000100028: departed / 2026-02-12 03:00 (ok) | no / 0 | 7.8 | **resolved** handoff | S1 |

## BKG000100029 (CUS-00001) AEJEA -> CNSHA

- Delay class: **none** (+0.9 h vs plan)
- Planned: depart 2026-01-08 04:00, arrive 2026-02-14 04:00
- Actual: depart 2026-01-08 01:21, arrive 2026-02-14 04:53, released 2026-02-15 19:57
- Containers: SYNU0000647, SYNU0000652, SYNU0000668, SYNU0000673; BL SBL000500029 issued 2026-01-09 06:46

| Event | Class | Happened / expected | Recorded | Stale |
|---|---|---|---|---|
| ARRI | PLN | 2026-02-14 04:00 | 2025-12-18 11:20 |  |
| DEPA | PLN | 2026-01-08 04:00 | 2025-12-18 11:20 |  |
| CONF | ACT | 2025-12-18 11:20 | 2025-12-18 11:30 |  |
| GTIN SYNU0000652 | ACT | 2026-01-05 02:42 | 2026-01-05 02:55 |  |
| GTIN SYNU0000647 | ACT | 2026-01-05 11:01 | 2026-01-05 11:52 |  |
| GTIN SYNU0000673 | ACT | 2026-01-05 20:36 | 2026-01-05 20:46 |  |
| GTIN SYNU0000668 | ACT | 2026-01-06 15:18 | 2026-01-06 15:52 |  |
| LOAD SYNU0000652 | ACT | 2026-01-07 14:40 | 2026-01-07 15:02 |  |
| LOAD SYNU0000668 | ACT | 2026-01-07 16:09 | 2026-01-07 16:25 |  |
| LOAD SYNU0000647 | ACT | 2026-01-07 23:13 | 2026-01-07 23:41 |  |
| DEPA | ACT | 2026-01-08 01:21 | 2026-01-08 02:57 |  |
| LOAD SYNU0000673 | ACT | 2026-01-07 23:06 | 2026-01-08 14:04 | yes |
| ISSU | ACT | 2026-01-09 06:46 | 2026-01-09 06:52 |  |
| ARRI | ACT | 2026-02-14 04:53 | 2026-02-14 05:04 |  |
| DISC SYNU0000668 | ACT | 2026-02-14 13:11 | 2026-02-14 14:22 |  |
| DISC SYNU0000673 | ACT | 2026-02-14 15:46 | 2026-02-14 18:23 |  |
| DISC SYNU0000647 | ACT | 2026-02-14 20:10 | 2026-02-14 21:37 |  |
| DISC SYNU0000652 | ACT | 2026-02-15 00:54 | 2026-02-15 00:56 |  |
| RELS | ACT | 2026-02-15 19:57 | 2026-02-15 21:49 |  |
| GTOT SYNU0000647 | ACT | 2026-02-18 04:10 | 2026-02-18 04:37 |  |
| GTOT SYNU0000652 | ACT | 2026-02-18 05:24 | 2026-02-18 05:28 |  |
| GTOT SYNU0000668 | ACT | 2026-02-18 12:29 | 2026-02-18 12:45 |  |
| GTOT SYNU0000673 | ACT | 2026-02-18 13:46 | 2026-02-18 14:57 |  |

| Enquiry | Received | Type | Stated ref (kind) | Known status / ETA | Actual status / ETA |
|---|---|---|---|---|---|
| ENQ-000052 | 2026-02-13 22:13 | status | BKG000100029 (booking) | departed / 2026-02-14 04:00 | departed / 2026-02-14 04:00 |

| Enquiry | Arm | First answer | Final answer | Escalation req / cases | Human min | Outcome | Scenario |
|---|---|---|---|---|---|---|---|
| ENQ-000052 | agent_v1 | ai_agent BKG000100029: departed / 2026-02-14 04:00 (ok) | ai_agent BKG000100029: departed / 2026-02-14 04:00 (ok) | no / 0 | 0.0 | **resolved** | S1 |

