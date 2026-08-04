"""Readiness probing for the DEM.

The routes themselves live in `api.py`; only the probe lives here, because
getting it right is more subtle than it looks and it deserves its own tests.

Two hazards shape the design:

* The DEM sits on a separate LV mounted `nofail`, so it can disappear while
  this process stays perfectly alive. Readiness therefore has to be answered
  per request — caching what the lifespan hook resolved at startup would give
  exactly the wrong answer in the case the endpoint exists to catch.

* If the underlying storage *hangs* rather than unmounting cleanly, a `stat`
  blocks indefinitely. A probe that simply waits would take the readiness
  endpoint down with it, which is the opposite of useful: the proxy would stop
  getting any answer instead of getting "not ready".

So the filesystem call runs in a worker thread under a timeout, and the
in-flight future is shared between concurrent callers. That second part
matters: a hung mount polled once a second must not spawn a thread per poll
and drain the executor. At most one probe thread exists at a time, however
often `/readyz` is called.
"""
import asyncio
import os
from dataclasses import dataclass
from typing import Optional

# Long enough that a busy-but-healthy disk is not called dead, short enough
# that a polling proxy gets its answer well inside a normal probe interval.
DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason: str = ""


class DemProbe:
    """Answers "is the DEM readable *right now*" cheaply and without hanging.

    Holds the path and source type the lifespan hook resolved, so `/readyz`
    reports what startup actually chose rather than re-deriving it — two
    independent answers would eventually drift apart, which would defeat the
    point of reporting it at all.
    """

    def __init__(
        self,
        path: str,
        source_type: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.path = path
        self.source_type = source_type
        self._timeout = timeout
        self._inflight: Optional[asyncio.Future] = None

    @staticmethod
    def _readable(path: str) -> bool:
        """The cheap check: no rasterio open, no pixel read.

        `os.access` answers the question directly and returns promptly when the
        mount is simply gone. Opening the raster would be both far more
        expensive and no more informative about the failure that actually
        happens here.
        """
        return os.access(path, os.R_OK)

    async def check(self) -> Readiness:
        if not self.path:
            return Readiness(False, "no DEM configured")

        loop = asyncio.get_running_loop()
        if self._inflight is None or self._inflight.done():
            self._inflight = loop.run_in_executor(None, self._readable, self.path)

        try:
            # shield() so a timeout does not cancel the underlying probe: the
            # thread is stuck in the kernel and cannot be cancelled anyway, and
            # letting it finish lets the next caller reuse the same future.
            readable = await asyncio.wait_for(
                asyncio.shield(self._inflight), self._timeout
            )
        except asyncio.TimeoutError:
            return Readiness(
                False,
                f"DEM readability check exceeded {self._timeout:g}s at {self.path} "
                "— storage may be hung",
            )
        except OSError as exc:
            return Readiness(False, f"DEM check failed at {self.path}: {exc}")

        if not readable:
            return Readiness(False, f"DEM not readable at {self.path}")
        return Readiness(True)
