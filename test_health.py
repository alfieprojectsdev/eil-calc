"""Tests for /healthz and /readyz.

None of these need the real 12 GB raster — the readiness check is a filesystem
readability test, so a temp file stands in exactly.
"""
import asyncio
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from health import DemProbe


class TestLiveness(unittest.TestCase):
    """/healthz must answer even when nothing else is configured."""

    def test_healthz_ok_without_any_dem(self):
        # No lifespan, so app.state.dem_probe is never set — liveness must not
        # care. This is the whole point of splitting it from readiness.
        client = TestClient(api.app)
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_healthz_excluded_from_openapi(self):
        client = TestClient(api.app)
        paths = client.get("/openapi.json").json()["paths"]
        self.assertNotIn("/healthz", paths)
        self.assertNotIn("/readyz", paths)


class TestReadinessRoute(unittest.TestCase):
    def setUp(self):
        self._saved = getattr(api.app.state, "dem_probe", None)

    def tearDown(self):
        if self._saved is None:
            api.app.state._state.pop("dem_probe", None)
        else:
            api.app.state.dem_probe = self._saved

    def test_readyz_200_when_dem_readable(self):
        with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
            api.app.state.dem_probe = DemProbe(tmp.name, "ifsar")
            response = TestClient(api.app).get("/readyz")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        # The path must be echoed — ADR-003's definition of done step 1 checks
        # for exactly this.
        self.assertEqual(body["dem"]["path"], tmp.name)
        self.assertEqual(body["dem"]["source"], "ifsar")

    def test_readyz_503_when_dem_vanishes(self):
        """The mount-dropped case: readable at startup, gone afterwards."""
        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        tmp.close()
        api.app.state.dem_probe = DemProbe(tmp.name, "ifsar")
        client = TestClient(api.app)

        self.assertEqual(client.get("/readyz").status_code, 200)

        os.unlink(tmp.name)

        response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "not ready")
        self.assertIn(tmp.name, body["reason"])

    def test_readyz_503_before_startup_completes(self):
        api.app.state._state.pop("dem_probe", None)
        response = TestClient(api.app).get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertIn("startup", response.json()["reason"])

    def test_liveness_stays_green_while_readiness_is_red(self):
        """If both go red together the split has no value."""
        api.app.state.dem_probe = DemProbe("/nonexistent/IfSAR_PH.tif", "ifsar")
        client = TestClient(api.app)
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/readyz").status_code, 503)


class TestDemProbe(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_path(self):
        result = await DemProbe("", "").check()
        self.assertFalse(result.ready)
        self.assertIn("no DEM configured", result.reason)

    async def test_hung_storage_times_out_instead_of_blocking(self):
        """A hung mount must yield 'not ready', not a hung endpoint."""
        release = threading.Event()

        def _hang(_path):
            # Stands in for a stat blocked in the kernel on dead storage.
            release.wait(timeout=10)
            return True

        probe = DemProbe("/hung/mount/IfSAR_PH.tif", "ifsar", timeout=0.2)
        try:
            with patch.object(DemProbe, "_readable", staticmethod(_hang)):
                result = await asyncio.wait_for(probe.check(), timeout=5)
        finally:
            # Free the worker thread; leaving it parked would stall interpreter
            # shutdown while the executor joins it.
            release.set()

        self.assertFalse(result.ready)
        self.assertIn("hung", result.reason)

    async def test_concurrent_polls_share_one_probe_thread(self):
        """A hung mount polled repeatedly must not drain the executor."""
        calls = []

        def _slow(path):
            calls.append(path)
            time.sleep(0.3)
            return True

        probe = DemProbe("/slow/IfSAR_PH.tif", "ifsar", timeout=0.05)
        with patch.object(DemProbe, "_readable", staticmethod(_slow)):
            results = await asyncio.gather(*(probe.check() for _ in range(10)))
            # Let the shared probe finish so it does not leak into other tests.
            await asyncio.sleep(0.4)

        self.assertTrue(all(not r.ready for r in results))
        self.assertEqual(len(calls), 1, f"expected 1 probe thread, got {len(calls)}")


if __name__ == "__main__":
    unittest.main()
