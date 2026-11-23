import asyncio
import base64
import copy
import importlib
import struct
import unittest
import zlib
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from jinja2 import Environment, FileSystemLoader

from src.services.jx3.role_queries import build_equipment_spec_or_text


REAL_ASYNC_CLIENT = httpx.AsyncClient
ICON_BASE = "https://icon.jx3box.com/icon/"


def icon_url(icon_id):
    return ICON_BASE + str(icon_id) + ".png"


def png(width=1, height=1):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = (b"\x00" + b"\x00\x00\x00\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = png()
DATA_URI = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")


def equipment_context(icon_id=7529):
    payload = {"equipScore": 18000, "cacheTime": 1795438546, "panelList": [{"name": "会心", "value": 38.5}],
               "equipList": [{"itemName": "测试装备<甲>", "iconId": icon_id, "itemLevel": 26000,
                             "mountDiamond": [{"itemName": "五行石（七级）", "iconId": "2351"}],
                             "colorDiamond": {"itemName": "测试五彩石", "iconId": 11751},
                             "minEnchant": {"itemName": "测试附魔", "iconId": "7529"}}]}
    before = copy.deepcopy(payload)
    spec, error = build_equipment_spec_or_text(data={"data": payload}, server="测试服", role_name="测试角色", random_text="")
    if error or spec is None:
        raise AssertionError(error)
    if payload != before:
        raise AssertionError("service mutated its source payload")
    return spec.context


class HtmlImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.visible = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs))

    def handle_data(self, value):
        self.visible.append(value)


class TestEquipmentIconModels(unittest.TestCase):
    def test_service_maps_safe_ids_for_all_icon_categories_and_preserves_names(self):
        row = equipment_context()["equipment"][0]
        self.assertEqual(icon_url(7529), row["icon"]["url"])
        self.assertEqual(icon_url(2351), row["stone_icons"][0]["url"])
        self.assertEqual("七级", row["stone_icons"][0]["label"])
        self.assertEqual(icon_url(11751), row["color_stone_icon"]["url"])
        self.assertEqual(icon_url(7529), row["enchant_icons"][0]["url"])
        self.assertEqual(["五行石（七级）"], row["stones"])
        self.assertEqual("测试五彩石", row["color_stone"])
        self.assertEqual(["测试附魔"], row["enchants"])

    def test_service_rejects_invalid_ids_without_losing_equipment(self):
        for value in (None, "", 0, -1, True, False, 1.5, "1.5", "../x", "https://example.test/1.png", "１２", "100000000", 100000000):
            with self.subTest(value=value):
                row = equipment_context(value)["equipment"][0]
                self.assertEqual("", row["icon"]["url"])
                self.assertEqual("测试装备<甲>", row["name"])

    def test_service_numeric_string_is_canonicalized_without_leading_zero(self):
        row = equipment_context("0007529")["equipment"][0]
        self.assertEqual(icon_url(7529), row["icon"]["url"])

    def test_service_missing_optional_icon_ids_retains_full_fallback_names(self):
        data = {"data": {"equipList": [{"itemName": "无图装备", "mountDiamond": [{"itemName": "无等级五行石"}],
                      "colorDiamond": {"itemName": "无图五彩石"}, "maxEnchant": {"itemName": "无图附魔"}}]}}
        spec, error = build_equipment_spec_or_text(data=data, server="服", role_name="名", random_text="")
        self.assertIsNone(error)
        row = spec.context["equipment"][0]
        for item in (row["icon"], row["stone_icons"][0], row["color_stone_icon"], row["enchant_icons"][0]):
            self.assertEqual("", item["url"])
            self.assertTrue(item["name"])


class TestJx3boxIconFetch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.reload(importlib.import_module("src.infra.jx3box_icons"))

    def mock_transport(self, handler):
        transport = httpx.MockTransport(handler)
        def factory(*args, **kwargs):
            kwargs.pop("transport", None)
            return REAL_ASYNC_CLIENT(*args, transport=transport, **kwargs)
        return patch.object(self.module.httpx, "AsyncClient", side_effect=factory)

    async def test_valid_png_is_embedded_once_for_duplicate_urls(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        url = icon_url(7529)
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([url, url, url])
        self.assertEqual({url: DATA_URI}, result)
        self.assertEqual([url], calls)

    async def test_only_exact_https_icon_urls_are_requested(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        invalid = ["http://icon.jx3box.com/icon/1.png", "https://example.test/icon/1.png",
                   "https://icon.jx3box.com.example.test/icon/1.png", "https://icon.jx3box.com/icon/01.png",
                   icon_url(0), icon_url(-1), icon_url(100000000), icon_url(1) + "?x=1", icon_url(1) + "#x",
                   "https://icon.jx3box.com/other/1.png", "https://icon.jx3box.com:444/icon/1.png",
                   "https://user@icon.jx3box.com/icon/1.png", "file:///etc/passwd", "", None]
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris(invalid + [icon_url(1)])
        self.assertEqual({icon_url(1): DATA_URI}, result)
        self.assertEqual([icon_url(1)], calls)

    async def test_http_errors_redirects_non_png_and_truncated_png_are_omitted(self):
        calls = []
        responses = {
            1: (404, "image/png", PNG), 2: (200, "image/jpeg", PNG),
            3: (200, "image/png", b"not an image"), 4: (200, "image/png", PNG[:-12]),
            5: (302, "image/png", PNG),
        }
        def handler(request):
            calls.append(str(request.url))
            num = int(request.url.path.rsplit("/", 1)[-1].split(".")[0])
            status, content_type, body = responses[num]
            return httpx.Response(status, headers={"content-type": content_type, "location": "https://example.test/stolen"}, content=body)
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(i) for i in responses])
        self.assertEqual({}, result)
        self.assertEqual(5, len(calls))
        self.assertTrue(all(url.startswith(ICON_BASE) for url in calls))

    async def test_png_with_corrupted_idat_crc_is_omitted(self):
        damaged = bytearray(PNG)
        damaged[damaged.index(b"IDAT") + 6] ^= 1
        def handler(request):
            return httpx.Response(200, headers={"content-type": "image/png"}, content=bytes(damaged))
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(1)])
        self.assertEqual({}, result)

    async def test_client_construction_failure_falls_back_without_raising(self):
        with patch.object(self.module.httpx, "AsyncClient", side_effect=ValueError("invalid client configuration")):
            result = await self.module.fetch_icon_data_uris([icon_url(1)])
        self.assertEqual({}, result)

    async def test_client_exit_failure_keeps_already_loaded_icons(self):
        class Client:
            def __init__(self, *args, **kwargs):
                kwargs.pop("transport", None)
                self.real = REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)), **kwargs)

            async def __aenter__(self):
                return await self.real.__aenter__()

            async def __aexit__(self, *args):
                await self.real.__aexit__(*args)
                raise OSError("client close failed")

        with patch.object(self.module.httpx, "AsyncClient", Client):
            result = await self.module.fetch_icon_data_uris([icon_url(1)])
        self.assertEqual({icon_url(1): DATA_URI}, result)

    async def test_total_budget_also_bounds_client_startup(self):
        class SlowClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                await asyncio.sleep(1)
                return self

            async def __aexit__(self, *args):
                pass

        with patch.object(self.module.httpx, "AsyncClient", SlowClient), patch.object(self.module, "ICON_TIMEOUT_SECONDS", 0.03):
            result = await asyncio.wait_for(self.module.fetch_icon_data_uris([icon_url(1)]), timeout=0.3)
        self.assertEqual({}, result)

    async def test_oversized_images_and_dimensions_are_omitted(self):
        bodies = {1: PNG + b"x" * 32768, 2: png(257, 1), 3: png(1, 257), 4: png(256, 1)}
        def handler(request):
            num = int(request.url.path.rsplit("/", 1)[-1].split(".")[0])
            return httpx.Response(200, headers={"content-type": "image/png"}, content=bodies[num])
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(i) for i in bodies])
        self.assertEqual({icon_url(4)}, set(result))

    async def test_streaming_stops_after_exceeding_byte_limit(self):
        reads = []
        class LargeStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for n in range(10):
                    reads.append(n)
                    yield b"x" * 16384
        def handler(request):
            return httpx.Response(200, headers={"content-type": "image/png"}, stream=LargeStream())
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(1)])
        self.assertEqual({}, result)
        self.assertLessEqual(len(reads), 3)

    async def test_maximum_unique_request_count_is_128(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(i) for i in range(1, 151)])
        self.assertEqual(128, len(calls))
        self.assertEqual(128, len(result))

    async def test_at_most_four_requests_are_active(self):
        active = 0
        maximum = 0
        async def handler(request):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.005)
                return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
            finally:
                active -= 1
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(i) for i in range(1, 13)])
        self.assertEqual(12, len(result))
        self.assertLessEqual(maximum, 4)

    async def test_total_budget_cancels_work_and_returns_partial_success(self):
        async def handler(request):
            if request.url.path.endswith("/1.png"):
                return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
            await asyncio.sleep(1)
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        with self.mock_transport(handler), patch.object(self.module, "ICON_TIMEOUT_SECONDS", 0.03):
            result = await asyncio.wait_for(self.module.fetch_icon_data_uris([icon_url(1), icon_url(2)]), timeout=0.3)
        self.assertEqual({icon_url(1): DATA_URI}, result)

    async def test_transport_failures_do_not_escape_or_poison_other_icons(self):
        def handler(request):
            if request.url.path.endswith("/1.png"):
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        with self.mock_transport(handler):
            result = await self.module.fetch_icon_data_uris([icon_url(1), icon_url(2)])
        self.assertEqual({icon_url(2): DATA_URI}, result)

    async def test_success_cache_reuses_bytes_until_twenty_four_hour_expiry(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        url = icon_url(1)
        with self.mock_transport(handler):
            with patch.object(self.module, "monotonic", return_value=1000):
                self.assertEqual({url: DATA_URI}, await self.module.fetch_icon_data_uris([url]))
                self.assertEqual({url: DATA_URI}, await self.module.fetch_icon_data_uris([url]))
            with patch.object(self.module, "monotonic", return_value=1000 + 86400):
                self.assertEqual({url: DATA_URI}, await self.module.fetch_icon_data_uris([url]))
        self.assertEqual([url, url], calls)

    async def test_success_cache_retains_only_256_most_recent_entries(self):
        calls = Counter()
        def handler(request):
            calls[str(request.url)] += 1
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        with self.mock_transport(handler):
            await self.module.fetch_icon_data_uris([icon_url(i) for i in range(1, 129)])
            await self.module.fetch_icon_data_uris([icon_url(i) for i in range(129, 257)])
            await self.module.fetch_icon_data_uris([icon_url(1)])
            await self.module.fetch_icon_data_uris([icon_url(257)])
            await self.module.fetch_icon_data_uris([icon_url(1)])
            await self.module.fetch_icon_data_uris([icon_url(2)])
        self.assertEqual(1, calls[icon_url(1)])
        self.assertEqual(2, calls[icon_url(2)])

    async def test_failed_fetches_are_retried_on_next_call(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(500, content=b"offline")
        with self.mock_transport(handler):
            self.assertEqual({}, await self.module.fetch_icon_data_uris([icon_url(1)]))
            self.assertEqual({}, await self.module.fetch_icon_data_uris([icon_url(1)]))
        self.assertEqual(2, len(calls))


class TestEquipmentIconRenderer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.import_module("src.renderers.jx3.equipment_icons")
        self.env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "templates")))

    async def test_preparer_scans_all_categories_once_and_never_changes_input(self):
        context = equipment_context()
        before = copy.deepcopy(context)
        fetch = AsyncMock(return_value={icon_url(7529): DATA_URI, icon_url(2351): DATA_URI})
        with patch.object(self.module, "fetch_icon_data_uris", fetch):
            actual = await self.module.prepare_equipment_icons(context)
        fetch.assert_awaited_once()
        self.assertEqual({icon_url(7529), icon_url(2351), icon_url(11751)}, set(fetch.call_args.args[0]))
        row = actual["equipment"][0]
        self.assertEqual(DATA_URI, row["icon"]["image_src"])
        self.assertEqual(DATA_URI, row["stone_icons"][0]["image_src"])
        self.assertEqual("", row["color_stone_icon"]["image_src"])
        self.assertEqual(DATA_URI, row["enchant_icons"][0]["image_src"])
        self.assertEqual(before, context)

    async def test_failed_fetch_removes_untrusted_existing_image_sources(self):
        context = equipment_context()
        context["equipment"][0]["icon"]["image_src"] = "https://example.test/leak"
        with patch.object(self.module, "fetch_icon_data_uris", AsyncMock(return_value={})):
            actual = await self.module.prepare_equipment_icons(context)
        self.assertEqual("", actual["equipment"][0]["icon"]["image_src"])

    async def test_template_uses_embedded_images_and_short_stone_grade(self):
        with patch.object(self.module, "fetch_icon_data_uris", AsyncMock(return_value={icon_url(i): DATA_URI for i in (7529, 2351, 11751)})):
            context = await self.module.prepare_equipment_icons(equipment_context())
        html = self.env.get_template("装备查询.html").render(**context)
        parser = HtmlImages()
        parser.feed(html)
        self.assertEqual(4, len(parser.images))
        self.assertTrue(all(image.get("src", "").startswith("data:image/png;base64,") for image in parser.images))
        text = "".join(parser.visible)
        self.assertIn("七级", text)
        self.assertNotIn("五行石（七级）", text)
        self.assertIn("测试装备<甲>", text)
        self.assertNotIn("https://icon.jx3box.com/", html)
        self.assertNotIn("<甲>", html)

    async def test_template_missing_download_retains_full_names_without_external_images(self):
        with patch.object(self.module, "fetch_icon_data_uris", AsyncMock(return_value={})):
            context = await self.module.prepare_equipment_icons(equipment_context())
        html = self.env.get_template("装备查询.html").render(**context)
        parser = HtmlImages()
        parser.feed(html)
        self.assertEqual([], parser.images)
        text = "".join(parser.visible)
        for name in ("测试装备<甲>", "五行石（七级）", "测试五彩石", "测试附魔"):
            self.assertIn(name, text)

    async def test_image_renderer_prepares_equipment_only_before_screenshot(self):
        module = importlib.import_module("src.renderers.jx3.image")
        context = equipment_context()
        fetch = AsyncMock(return_value={icon_url(i): DATA_URI for i in (7529, 2351, 11751)})
        screenshot = AsyncMock(return_value=b"image")
        with patch.object(self.module, "fetch_icon_data_uris", fetch), patch.object(module, "jietu", screenshot):
            result = await module.render_template_image(self.env, "装备查询.html", context, width=1119, height="ck")
        self.assertEqual(b"image", result)
        self.assertIn("data:image/png;base64,", screenshot.call_args.args[0])
        self.assertEqual((1119, "ck"), screenshot.call_args.args[1:])
        fetch.assert_awaited_once()
        fetch.reset_mock()
        self.env.from_string("unused")
        from jinja2 import DictLoader
        other_env = Environment(loader=DictLoader({"other.html": "hello"}))
        with patch.object(self.module, "fetch_icon_data_uris", fetch), patch.object(module, "jietu", screenshot):
            await module.render_template_image(other_env, "other.html", context, width=1, height=1)
        fetch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
