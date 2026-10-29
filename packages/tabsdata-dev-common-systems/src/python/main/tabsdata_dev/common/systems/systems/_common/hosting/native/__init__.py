#
# Copyright 2026 Tabsdata Inc.
#

"""Native hosting: the system runs as a process on this machine, from binaries
tdd downloads, and tdd starts and stops it -- everything it owns (binaries,
configuration, data) in one directory per system under
``<tdd_dir>/data/system-native/`` (``_base``); the archives come over HTTP into
a cache shared with whoever else fetches them (``download``)."""
