#
# Copyright 2026 Tabsdata Inc.
#

"""Redpanda backend — a docker broker; a domain is a Kafka topic.

The container needs a custom ``redpanda start`` command (internal + external
kafka listeners, and the Confluent-compatible schema registry published on a
host port), so ``provision_system`` is bespoke; readiness is ``rpk cluster
info``. A domain is a topic managed through the confluent-kafka AdminClient
(there is no per-topic auth). The data plane produces a model's rows as JSON
messages, one per row, keyed by the row's first field, to a
``<domain>.<entity>`` topic per entity. ``create-model`` creates those topics,
each with the partitions ``--up-to-partitions`` gave it (``shape``), so a
consumer can subscribe before anything is produced and a topic nothing writes
still exists; ``modify-data`` is insert-only (a Kafka log only appends).
``entities`` records the produced topics and their message counts.
"""

from __future__ import annotations

import contextlib
import json
from contextlib import contextmanager
from urllib.parse import quote, unquote

from tabsdata_dev.common.systems import constants, datagen, emit, naming, options
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import (
    container_exists,
    container_id,
    docker_exec,
    docker_pull,
    docker_rm,
    docker_run,
    gen_password,
    require_docker,
)
from tabsdata_dev.common.systems.systems._common import container_info
from tabsdata_dev.common.systems.systems._common.host import DEFAULT_HOSTNAME
from tabsdata_dev.common.systems.systems._common.sql import SqlContainerBackend
from tabsdata_dev.common.systems.systems.redpanda import shape

_REGISTRY_INTERNAL_PORT = 8081
# The one SASL user a system with --sasl on has, and how it authenticates --
# what the Kafka connector speaks when its connection has credentials.
SASL_USER = "tdd"
SASL_MECHANISM = "SCRAM-SHA-256"
SASL_ON, SASL_OFF = "on", "off"


def client_conf(brokers: str, user: str = "", password: str = "") -> dict:
    """A confluent-kafka client config for `brokers`, authenticating when the
    system has a user."""
    conf = {"bootstrap.servers": brokers}
    if user:
        conf |= {
            "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": SASL_MECHANISM,
            "sasl.username": user,
            "sasl.password": password,
        }
    return conf


class Redpanda(SqlContainerBackend):
    slug = "redpanda"
    label = "Redpanda"
    kind = "kafka"
    domain_word = "topic"
    max_entity_name_length = 249  # Kafka topic-name limit
    supports_changes = True  # insert-only (a Kafka log only appends)
    supports_trx_modes = False  # a batch is produced whole; no transactions to order

    image = container_info.REDPANDA.ref
    image_platform = container_info.REDPANDA.platform
    internal_port = 9092

    def generate_password(self) -> str:
        return ""  # a password is generated only for --sasl on (plan_system)

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("PORT", "port", options.PORT, "a free host port"),
            options.Option(
                "SASL",
                "sasl",
                options.SYNTH,
                "off; on: every client authenticates, SASL/SCRAM-SHA-256 as user "
                "tdd with a generated password",
                required=False,
            ),
        )

    def synth_default(self, name: str, sys_name: str) -> str:
        if name == "SASL":
            return SASL_OFF
        raise TdxError(f"{self.slug}: no synth default for {name}")

    # ---- custom container lifecycle ------------------------------------

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        sasl = (o.get("SASL") or SASL_OFF).strip().lower()
        if sasl not in (SASL_ON, SASL_OFF):
            raise TdxError(
                f"--sasl must be {SASL_ON} or {SASL_OFF} (got: {o.get('SASL')})"
            )
        raw = o.get("PORT")
        kport = int(raw) if raw else self.next_free_port()
        reg = self.next_free_port()
        while reg == kport:
            reg = self.next_free_port()
        auth = {"USER": "", "PASSWORD": ""}
        if sasl == SASL_ON:
            auth = {
                "USER": SASL_USER,
                "PASSWORD": gen_password(),
                "SASL_MECHANISM": SASL_MECHANISM,
            }
        return {
            "DOCKER_CONTAINER_NAME": self.container_name(name),
            "IMAGE": self.image,
            "HOST": self.hostname,
            "PORT": str(kport),
            "REGISTRY_PORT": str(reg),
            "SCHEMA_REGISTRY_URL": f"http://{self.hostname}:{reg}",
            "KAFKA_BROKERS": f"{self.hostname}:{kport}",
            "SASL": sasl,
            **auth,
        }

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        require_docker()
        container = meta["DOCKER_CONTAINER_NAME"]
        port, reg = meta["PORT"], meta["REGISTRY_PORT"]
        # A client bootstraps against the external listener and is then redirected
        # to the address it advertises, so that one is the descriptor's own host.
        advertised = meta["HOST"]
        if container_exists(container):
            if force:
                docker_rm(container, force=True)
                print(f">>> --force: removed existing container {container}")
            else:
                raise TdxError(f"container already exists: {container} (use --force)")
        print(f">>> pulling docker image {self.image} …", flush=True)
        docker_pull(self.image, self.image_platform)
        print(f">>> starting container {container} from image {self.image}")
        docker_run(
            [
                "-d",
                "--platform",
                self.image_platform,
                "-p",
                f"{port}:{port}",
                "-p",
                f"{reg}:{_REGISTRY_INTERNAL_PORT}",
                "--name",
                container,
                self.image,
                "redpanda",
                "start",
                "--smp",
                "1",
                "--memory",
                "1G",
                "--overprovisioned",
                "--kafka-addr",
                f"internal://0.0.0.0:9092,external://0.0.0.0:{port}",
                "--advertise-kafka-addr",
                f"internal://localhost:9092,external://{advertised}:{port}",
            ]
        )
        print(f">>> waiting for {self.label} to become ready …")
        self._wait_ready(container, "", self.ready_timeout)
        if meta.get("USER"):
            self._enable_sasl(container, meta["USER"], meta["PASSWORD"])
        cid = container_id(container)
        return {"DOCKER_CONTAINER_ID": cid} if cid else {}

    def _enable_sasl(self, container: str, user: str, password: str) -> None:
        """The user, made a superuser, then SASL turned on for every Kafka
        listener -- in that order, through the admin API, which SASL does not
        guard: once it is on, nothing unauthenticated reaches a topic, the
        broker's own rpk included."""
        print(f">>> enabling SASL ({SASL_MECHANISM}) for user {user} …")
        steps = (
            [
                "rpk",
                "security",
                "user",
                "create",
                user,
                "-p",
                password,
                "--mechanism",
                SASL_MECHANISM,
            ],
            ["rpk", "cluster", "config", "set", "superusers", f"['{user}']"],
            ["rpk", "cluster", "config", "set", "enable_sasl", "true"],
        )
        for argv in steps:
            r = docker_exec(container, *argv)
            if r.returncode != 0:
                what = " ".join(argv[:4])
                raise TdxError(f"{what} failed: {(r.stderr or r.stdout).strip()}")
        self._wait_ready(container, password, self.ready_timeout)

    def check_ready(self, container: str, password: str) -> bool:
        from tabsdata_dev.common.systems.shell import docker_exec_check

        # A password means SASL is on (only --sasl on generates one), and then
        # rpk must authenticate like any other client.
        auth = []
        if password:
            auth = [
                "-X",
                f"user={SASL_USER}",
                "-X",
                f"pass={password}",
                "-X",
                f"sasl.mechanism={SASL_MECHANISM}",
            ]
        return docker_exec_check(container, "rpk", "cluster", "info", *auth)

    # ---- topic domain plane (confluent-kafka AdminClient) --------------

    def _admin_client(self, meta: dict[str, str]):
        from confluent_kafka.admin import AdminClient

        brokers = f"{meta.get('HOST', DEFAULT_HOSTNAME)}:{meta['PORT']}"
        return AdminClient(
            client_conf(brokers, meta.get("USER", ""), meta.get("PASSWORD", ""))
        )

    def _topics(self, client) -> list[str]:
        try:
            return list(client.list_topics(timeout=10).topics)
        except Exception as exc:
            raise TdxError(f"kafka list topics failed: {exc}") from exc

    def _delete_topics(self, client, name: str, *, include_root: bool = True) -> None:
        targets = [
            t
            for t in self._topics(client)
            if (include_root and t == name) or t.startswith(f"{name}.")
        ]
        if not targets:
            return
        futures = client.delete_topics(targets)
        for t in targets:
            with contextlib.suppress(Exception):  # best-effort; report nothing
                futures[t].result()

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        brokers = f"{sys_meta['HOST']}:{sys_meta['PORT']}"
        return {
            "HOST": sys_meta["HOST"],
            "PORT": sys_meta["PORT"],
            # No per-topic auth: a domain uses the system's SASL user, if any.
            "USER": sys_meta.get("USER", ""),
            "PASSWORD": sys_meta.get("PASSWORD", ""),
            "SASL_MECHANISM": sys_meta.get("SASL_MECHANISM", ""),
            "DB": entity_name,
            "IMAGE": sys_meta.get("IMAGE", ""),
            "KAFKA_BROKERS": brokers,
            "SCHEMA_REGISTRY_URL": sys_meta.get("SCHEMA_REGISTRY_URL", ""),
            "GROUP_ID": naming.build_identity(),
        }

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        from confluent_kafka.admin import NewTopic

        client = self._admin_client(sys_meta)
        if entity_name in self._topics(client):
            if not force:
                raise TdxError(f"topic '{entity_name}' already exists (use --force)")
            self._delete_topics(client, entity_name)
        futures = client.create_topics(
            [NewTopic(entity_name, num_partitions=1, replication_factor=1)]
        )
        try:
            futures[entity_name].result()
        except Exception as exc:
            raise TdxError(f"kafka create topic '{entity_name}' failed: {exc}") from exc

    def destroy_domain(self, domain_meta: dict[str, str]) -> None:
        self._delete_topics(self._admin_client(domain_meta), domain_meta["DB"])

    def list_domain_entities(self, sys_meta: dict[str, str]) -> list[str]:
        # A domain is one dot-free topic; per-entity `<domain>.<table>` topics go
        # with it, and Kafka internals (_schemas, __consumer_offsets) are skipped.
        return [
            t
            for t in self._topics(self._admin_client(sys_meta))
            if not t.startswith("_") and "." not in t
        ]

    def purge_domain_entity(self, sys_meta: dict[str, str], name: str) -> None:
        self._delete_topics(self._admin_client(sys_meta), name)

    # ---- data plane: produce a model's rows as JSON messages -----------

    def has_model(self, model: str) -> bool:
        return model in datagen.list_models()  # any model — no per-system schema

    def available_models(self) -> list[str]:
        return datagen.list_models()

    @contextmanager
    def data_plane_uri(self, meta: dict[str, str]):
        # A kafka domain is brokers + a topic prefix, not an addressable
        # endpoint, so the descriptor stores no URI: this composes the handle the
        # generic data-plane commands pass around -- the SASL user in it when
        # there is one -- and `_endpoint` takes it apart again.
        user = meta.get("USER", "")
        auth = f"{quote(user, safe='')}:{quote(meta.get('PASSWORD', ''), safe='')}@"
        yield (
            f"kafka://{auth if user else ''}{meta.get('KAFKA_BROKERS', '')}/"
            f"{meta.get('DB', '')}"
        )

    @staticmethod
    def _endpoint(uri: str) -> tuple[dict, str, str]:
        """``(client config, brokers, topic prefix)`` from a data-plane handle."""
        rest = uri.split("://", 1)[-1]
        auth, rest = rest.rsplit("@", 1) if "@" in rest else ("", rest)
        brokers, _, prefix = rest.partition("/")
        user, _, password = auth.partition(":")
        return client_conf(brokers, unquote(user), unquote(password)), brokers, prefix

    def install_schema(
        self, meta: dict[str, str], model: str, *, force: bool = False
    ) -> None:
        # On reload clear the per-entity topics (keep the domain topic itself)
        # so messages don't duplicate; then create every entity's topic with its
        # recorded partitions. Created here rather than on produce: a producer
        # creating a topic gets the broker's default partitions, and a regex
        # subscription sees only the topics that exist when it looks.
        client = self._admin_client(meta)
        prefix = meta.get("DB", "")
        if force:
            self._delete_topics(client, prefix, include_root=False)
        self._create_entity_topics(client, prefix, model, meta)

    def _create_entity_topics(
        self, client, prefix: str, model: str, meta: dict[str, str]
    ) -> None:
        from confluent_kafka.admin import NewTopic

        counts = shape.partitions_of(meta)
        existing = set(self._topics(client))
        wanted = {
            f"{prefix}.{name}": counts.get(name, 1)
            for name in datagen.entities_of(model)
        }
        todo = [
            NewTopic(topic, num_partitions=n, replication_factor=1)
            for topic, n in wanted.items()
            if topic not in existing
        ]
        if todo:
            for topic, future in client.create_topics(todo).items():
                try:
                    future.result()
                except Exception as exc:
                    raise TdxError(
                        f"kafka create topic '{topic}' failed: {exc}"
                    ) from exc
        layout = ", ".join(f"{t.rsplit('.', 1)[-1]}={n}" for t, n in wanted.items())
        print(f">>> kafka domain: {len(wanted)} topic(s), partitions {layout}")

    def _produce(
        self, conf: dict, prefix: str, tables: list[emit.Table]
    ) -> dict[str, int]:
        from confluent_kafka import Producer

        producer = Producer(conf)
        failed: list = []

        def delivered(err, _msg) -> None:
            if err is not None:
                failed.append(err)

        counts: dict[str, int] = {}
        for tbl in tables:
            topic = f"{prefix}.{tbl.name}"
            for row in tbl.rows:
                record = shape.record(row, tbl.columns)
                value = json.dumps(record, default=str, separators=(",", ":")).encode()
                key = shape.message_key(row, tbl.columns)
                while True:
                    try:
                        producer.produce(topic, value, key=key, on_delivery=delivered)
                        break
                    except BufferError:
                        # The local queue is full (100k messages by default): let
                        # deliveries drain it rather than fail a large batch.
                        producer.poll(0.1)
                producer.poll(0)
            counts[topic] = len(tbl.rows)
        left = producer.flush(120)
        if left or failed:
            raise TdxError(
                f"kafka produce: {left} message(s) undelivered, {len(failed)} failed"
                + (f" (first: {failed[0]})" if failed else "")
            )
        return counts

    def load_tables(self, uri: str, tables: list[emit.Table]) -> dict[str, int]:
        conf, brokers, prefix = self._endpoint(uri)
        rows = sum(len(t.rows) for t in tables)
        print(
            f">>> producing {rows} JSON message(s) to {len(tables)} topic(s) "
            f"on {brokers} …"
        )
        return self._produce(conf, prefix, tables)

    def apply_changes(
        self,
        uri: str,
        transactions: list,
        before: dict[str, int],
        *,
        label: str = "modify-data",
        schedule=None,
    ) -> dict[str, int]:
        changes = [c for txn in transactions for c in txn]
        if any(c.kind is not datagen.OpKind.INSERT for c in changes):
            raise TdxError(
                f"{self.slug} topics are append-only for {label} "
                f"(a change is a new message) — use --ops Insert"
            )
        if schedule is not None and schedule.mode.value != "serial":
            raise TdxError(
                f"{self.slug} topics take {label} as one batch of messages: "
                f"{constants.OPT_TRX_MODE} serial only"
            )
        by_table: dict[str, tuple[list, list]] = {}
        for c in changes:
            by_table.setdefault(c.table, (c.columns, []))[1].append(c.row)
        tables = [
            emit.Table(name=t, columns=cols, rows=rows)
            for t, (cols, rows) in by_table.items()
        ]
        conf, brokers, prefix = self._endpoint(uri)
        print(f">>> producing {len(changes)} JSON message(s) to {brokers} …")
        produced = self._produce(conf, prefix, tables)
        new = dict(before)
        for topic, n in produced.items():
            new[topic] = new.get(topic, 0) + n  # kafka log appends
        return new

    def drop_all_tables(self, uri: str) -> None:
        from confluent_kafka.admin import AdminClient

        conf, _, prefix = self._endpoint(uri)
        self._delete_topics(AdminClient(conf), prefix, include_root=False)
