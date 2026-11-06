#
# Copyright 2026 Tabsdata Inc.
#

"""demo · finance — subscription billing over the `finance` sample in MySQL (CDC).

Two ingest paths over the SAME domain, then marts, then S3:

  finance_src   (@publisher)         batch snapshot: one transactional MySQLSrc
                                     read of plans / prices / customers / payment
                                     methods / subscriptions / subscription events
                                     (100 rows each), on a 5-minute cron
  finance_cdc   (@stream_publisher)  change stream: MySQLCdcStreamSrc tailing
                                     customer_subscriptions and
                                     customer_subscription_events
  finance_marts (@transformer)       enrich subscriptions, split active / churned,
                                     build the event timeline
  finance_s3    (@subscriber)        write each mart to a parquet object in S3,
                                     and each CDC flush under changes/<plan ts>/

The snapshot is what the marts are built from; the stream is the live feed of
what changes afterwards. A CDC source is NOT a publisher: registering it STARTS
it (so there is no trigger for it), it has one ARRAY slot per tracked table
(folded with `concat`), and it declares no `ctx`. Its `server_id` is the replica
id MySQL keys consumers by (one replica per id), so its collection carries a
connection template of its own (connections/mysql_cdc_712.yaml).

The marts use the Tabsdata TableFrame API only — ROW-PRESERVING transforms
(join / filter / select / sort / rename), which is what a @transformer output must
be to sink cleanly; no aggregations here. Statuses are the generator's upper-case
vocabulary (ACTIVE, TRIALING, PAUSED, INCOMPLETE, CANCELED, EXPIRED).

Drive the stream once the suite is up:
    tdx-domain modify-data --domain <instance>_finance \\
        --entity customer_subscriptions --ops Mix --sets 5
"""
from __future__ import annotations

from tabsdatak.api import (
    CronTrigger,
    TableFrameSpec,
    TableFramesSpec,
    publisher,
    stream_publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.mysql import MySQLCdcStreamSrc, MySQLSrc
from tabsdatak.conn.s3 import S3Dest
from tabsdatak.tableframe.functions import col, concat


# --- ingest (batch): MySQL finance snapshot -> finance_src --------------------
# Unqualified names resolve against the connection's default database (the
# domain's). `transactional` defaults to True: one session, one snapshot. Every
# query is capped at 100 rows (ordered by key, so the cap is deterministic): the
# point of this publisher is the pipeline, not the volume.
#
# SCHEDULED: `trigger_by=CronTrigger` fires it every 5 minutes on its own (UTC,
# minute 2 of each 5 — the airportdb publisher takes minute 0, so the two demo SQL
# publishers never tick in the same minute). The suite's manual trigger coexists
# with the schedule, so `run-project` still produces a first batch immediately.
@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT * FROM subscription_plans ORDER BY plan_id LIMIT 100",
            "SELECT * FROM subscription_plan_prices ORDER BY price_id LIMIT 100",
            "SELECT * FROM customers ORDER BY customer_id LIMIT 100",
            "SELECT * FROM payment_methods ORDER BY payment_method_id LIMIT 100",
            "SELECT * FROM customer_subscriptions ORDER BY subscription_id LIMIT 100",
            "SELECT * FROM customer_subscription_events ORDER BY event_id LIMIT 100",
        ],
    ),
    output_tables=[
        "subscription_plans",
        "subscription_plan_prices",
        "customers",
        "payment_methods",
        "customer_subscriptions",
        "customer_subscription_events",
    ],
    trigger_by=CronTrigger(mask="2-59/5 * * * *"),
)
def pub_finance(
    plans: TableFrameSpec,
    prices: TableFrameSpec,
    customers: TableFrameSpec,
    payment_methods: TableFrameSpec,
    subscriptions: TableFrameSpec,
    events: TableFrameSpec,
) -> tuple[
    TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec
]:
    return (plans, prices, customers, payment_methods, subscriptions, events)


# --- ingest (stream): MySQL binlog -> finance_cdc -----------------------------
# `start_from="tail"`: only changes made after the stream attaches — the snapshot
# above already carries the seed. Rows come out TABULAR (`columns` + flattened):
# the new values inlined as ordinary columns, the before-image under
# `@td.cdc.data.col.old.<field>`, and the change metadata (op i/u/d, tx, ts, ...)
# under `@td.cdc.meta.*`. The small src_cfg thresholds keep a demo responsive.
@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=["customer_subscriptions", "customer_subscription_events"],
        start_from="tail",
        columns_format="columns",
        flatten_columns=True,
        src_cfg={
            "tabsdata.cdc.buffer.max_rows": 100,
            "tabsdata.cdc.buffer.max_secs": 5,
            "tabsdata.cdc.poll.idle_secs": 1,
            "tabsdata.cdc.poll.max_secs": 5,
        },
    ),
    batch_max_secs=60,
    batch_max_rows=10,
    output_tables=["subscription_changes", "subscription_event_changes"],
)
def stream_finance_changes(
    subscriptions: TableFramesSpec,
    events: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # One slot per tracked table, each an ARRAY of the frames this flush carried.
    # `concat` returns None for an empty list, so it doubles as the "nothing for
    # this slot" guard.
    return (concat(subscriptions), concat(events))


# --- marts: enrichment joins + filters (finance_src -> finance_marts) ---------
@transformer(
    input_tables=[
        "finance_src/customer_subscriptions@HEAD",
        "finance_src/customers@HEAD",
        "finance_src/subscription_plans@HEAD",
        "finance_src/payment_methods@HEAD",
    ],
    output_tables=["subscriptions_enriched"],
)
def tfr_subscriptions_enriched(
    subscriptions: TableFrameSpec,
    customers: TableFrameSpec,
    plans: TableFrameSpec,
    payment_methods: TableFrameSpec,
) -> TableFrameSpec:
    # subscription -> customer (who, where) -> plan (what) -> payment method (how).
    # `customers` and `subscription_plans` both have a `name`, so each is renamed
    # to its role before joining.
    enriched = subscriptions.join(
        customers.select("customer_id", "name", "email", "country").rename(
            {"name": "customer_name"}
        ),
        on="customer_id",
        how="left",
    )
    enriched = enriched.join(
        plans.select("plan_id", "plan_code", "name", "billing_interval").rename(
            {"name": "plan_name"}
        ),
        on="plan_id",
        how="left",
    )
    enriched = enriched.join(
        payment_methods.select("payment_method_id", "method_type", "brand"),
        on="payment_method_id",
        how="left",
    )
    return enriched.select(
        "subscription_id",
        "customer_id",
        "customer_name",
        "email",
        "country",
        "plan_code",
        "plan_name",
        "billing_interval",
        "currency",
        "unit_amount",
        "quantity",
        "discount_amount",
        "tax_amount",
        "total_amount",
        "method_type",
        "brand",
        "status",
        "started_at",
        "current_period_start",
        "current_period_end",
        "next_billing_at",
    )


@transformer(
    input_tables=["finance_marts/subscriptions_enriched@HEAD"],
    output_tables=["active_subscriptions"],
)
def tfr_active_subscriptions(enriched: TableFrameSpec) -> TableFrameSpec:
    # The billable book: what renews next, soonest first.
    return enriched.filter(col("status") == "ACTIVE").sort("next_billing_at")


@transformer(
    input_tables=[
        "finance_src/customer_subscriptions@HEAD",
        "finance_src/customers@HEAD",
        "finance_src/subscription_plans@HEAD",
    ],
    output_tables=["churned_subscriptions"],
)
def tfr_churned_subscriptions(
    subscriptions: TableFrameSpec, customers: TableFrameSpec, plans: TableFrameSpec
) -> TableFrameSpec:
    # Canceled subscriptions with who and what they were, most recent first.
    churned = subscriptions.filter(col("status") == "CANCELED")
    churned = churned.join(
        customers.select("customer_id", "name", "country").rename({"name": "customer_name"}),
        on="customer_id",
        how="left",
    )
    churned = churned.join(plans.select("plan_id", "plan_code"), on="plan_id", how="left")
    return churned.select(
        "subscription_id",
        "customer_name",
        "country",
        "plan_code",
        "currency",
        "total_amount",
        "started_at",
        "canceled_at",
        "ended_at",
    ).sort("canceled_at", descending=True)


@transformer(
    input_tables=[
        "finance_src/customer_subscription_events@HEAD",
        "finance_src/customer_subscriptions@HEAD",
        "finance_src/customers@HEAD",
    ],
    output_tables=["subscription_timeline"],
)
def tfr_subscription_timeline(
    events: TableFrameSpec, subscriptions: TableFrameSpec, customers: TableFrameSpec
) -> TableFrameSpec:
    # Every lifecycle event with the customer it happened to, in occurrence order.
    timeline = events.join(
        subscriptions.select("subscription_id", "customer_id", "plan_id"),
        on="subscription_id",
        how="left",
    )
    timeline = timeline.join(
        customers.select("customer_id", "name").rename({"name": "customer_name"}),
        on="customer_id",
        how="left",
    )
    return timeline.select(
        "event_id",
        "subscription_id",
        "customer_id",
        "customer_name",
        "plan_id",
        "event_type",
        "from_status",
        "to_status",
        "occurred_at",
        "actor",
    ).sort("occurred_at")


# --- serve: one parquet object per mart (finance_marts -> S3) ---------------
# Paths are relative to the s3 domain's base path; every run of a mart overwrites
# its object, so the bucket always holds the latest view.
@subscriber(
    destination=S3Dest(paths=["finance/subscriptions_enriched.parquet"]),
    input_tables=["finance_marts/subscriptions_enriched"],
)
def sink_subscriptions_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["finance/active_subscriptions.parquet"]),
    input_tables=["finance_marts/active_subscriptions"],
)
def sink_active_subscriptions(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["finance/churned_subscriptions.parquet"]),
    input_tables=["finance_marts/churned_subscriptions"],
)
def sink_churned_subscriptions(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["finance/subscription_timeline.parquet"]),
    input_tables=["finance_marts/subscription_timeline"],
)
def sink_subscription_timeline(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- serve (stream): every CDC flush as its own object (finance_cdc -> S3) ----
# These fire by table dependency each time the stream publishes a flush. The
# `${EXEC_PLAN_TS}` token is the FILE CONNECTOR's own (substituted server-side at
# write time), so the flushes accumulate in time order instead of overwriting.
@subscriber(
    destination=S3Dest(paths=["finance/changes/${EXEC_PLAN_TS}/subscription_changes.parquet"]),
    input_tables=["finance_cdc/subscription_changes"],
)
def sink_subscription_changes(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(
        paths=["finance/changes/${EXEC_PLAN_TS}/subscription_event_changes.parquet"]
    ),
    input_tables=["finance_cdc/subscription_event_changes"],
)
def sink_subscription_event_changes(t: TableFrameSpec) -> TableFrameSpec:
    return t
