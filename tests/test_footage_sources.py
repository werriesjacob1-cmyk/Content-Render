"""Provider-free tests for licensed footage and production graphic routing."""
import copy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main as unittest_main
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import footage_sources as fs
import main
import quality_asset_lineage as lineage


def commons_fixture(license_url, artist="Photographer"):
    return {"query": {"pages": {"4": {
        "pageid": 4, "title": "File:Microscopic organism.webm",
        "imageinfo": [{
            "url": "https://upload.wikimedia.org/media.webm",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Media.webm",
            "size": 1230, "mime": "video/webm",
            "extmetadata": {"LicenseUrl": {"value": license_url}, "Artist": {"value": artist}},
        }],
    }}}}


class FootageTests(TestCase):
    def test_licenses_fail_closed(self):
        for license_url in ("", "https://example.org/unknown",
                            "https://creativecommons.org/licenses/by-nc/4.0/",
                            "https://creativecommons.org/licenses/by-nd/4.0/"):
            with self.subTest(license_url=license_url):
                self.assertEqual(list(fs.commons_rows(commons_fixture(license_url))), [])
        by = "https://creativecommons.org/licenses/by/4.0/"
        self.assertEqual(list(fs.commons_rows(commons_fixture(by, ""))), [])
        self.assertEqual(list(fs.commons_rows(commons_fixture(by), used_ids={4})), [])
        audit = []
        list(fs.commons_rows(commons_fixture(by), audit=audit))
        list(fs.commons_rows(commons_fixture(""), audit=audit))
        self.assertEqual(audit, [True, False])

    def test_attribution_round_trips_into_lineage(self):
        url = "https://creativecommons.org/licenses/by/4.0/"
        candidate, = fs.commons_rows(commons_fixture(url, "<b>Photo Author</b>"))
        with patch.object(main, "_download"), patch.object(main, "_clip_too_dark", return_value=False), \
                patch.object(main, "_downloaded_assets", {}), patch.object(main, "_used_video_ids", set()), \
                patch.object(main, "_used_history", []):
            main._accept(candidate, "raw.mp4", "microscopic organism", 7)
            selected = main._downloaded_assets["raw.mp4"]
        with TemporaryDirectory() as tmp:
            entry = lineage.AssetLineageEntry("1", 1, "intent", "subject", "subject",
                                              "video", "scene.mp4", 3, selected_assets=(selected,))
            row = lineage.write_lineage([entry], Path(tmp) / "lineage.json")["scenes"][0]
        self.assertEqual(row["selected_assets"][0], {
            "id": 4, "source_url": candidate["source_url"], "license": url,
            "attribution": "Photo Author",
        })

    def test_failure_circuit_is_source_local_and_honest(self):
        logs = []
        sources = fs.FootageSources(None, logs.append)
        for status in (404, 429):
            name = f"source_{status}"
            def fail(_query):
                raise HTTPError("https://example.test", status, "", {}, None)

            self.assertEqual(sources.search(name, "x", fail), [])
            self.assertEqual(sources.search(name, "y", lambda _: self.fail("circuit ignored")), [])
        self.assertIn("HTTP 404", logs[0])
        self.assertNotIn("rate limit", logs[0])
        self.assertIn("HTTP 429 (rate limit)", logs[1])
        self.assertEqual(sources.search("healthy", "x", lambda _: ["candidate"]), ["candidate"])
        with patch.dict("os.environ", {"FOOTAGE_HEALTHY_ENABLED": "0"}):
            self.assertEqual(sources.search("healthy", "x", lambda _: self.fail("disabled")), [])

    def test_public_domain_item_requires_explicit_rights_and_bounded_download(self):
        payload = {
            "item": {"title": "Archive clip", "rights_advisory": ["Public domain."]},
            "resources": [{"files": [[{"url": "https://tile.loc.gov/video.mp4",
                                       "mimetype": "video/mp4", "size": 9000}]]}],
        }
        self.assertEqual(fs.congress_row(payload, "https://www.loc.gov/item/example/")["id"], "loc:example")
        payload["item"]["rights_advisory"].append("Editorial use only")
        self.assertIsNone(fs.congress_row(payload, "https://www.loc.gov/item/example/"))

    def test_structure_still_requires_an_explicit_accession(self):
        entry = SimpleNamespace(pdb_id="1CRN", title="Crambin",
                                primary_citation_authors=("Depositor",),
                                structure_url="https://www.rcsb.org/structure/1CRN")
        with patch("molecular_media.fetch_entry", return_value=entry) as fetch:
            self.assertEqual(fs.rcsb_still("protein molecule"), [])
            fetch.assert_not_called()
            candidate, = fs.rcsb_still("protein structure PDB 1CRN")
            fetch.assert_called_once_with("1CRN")
        self.assertEqual(candidate["id"], "pdb:1crn")
        self.assertEqual(candidate["source_url"], entry.structure_url)
        self.assertEqual(candidate["attribution"], "Depositor, RCSB PDB")

    def test_successful_graphic_bypasses_stock_and_preserves_scene(self):
        for subject in ("microscopic organism", "ancient road", "geometric proof"):
            with self.subTest(subject=subject):
                scene = {"id": "2", "voiceover": "A process takes three steps.",
                         "search_query": subject, "source_claim_ids": ["verified"]}
                original = copy.deepcopy(scene)
                plan = SimpleNamespace(source_claim_ids=["verified"])
                with patch("quality_science_motion.render_for_scene", return_value="graphic.mp4"), \
                        patch.object(main, "build_scene") as stock, patch.object(main, "_rendered_assets", {}):
                    self.assertEqual(main._build_with_science(scene, 2, "voice.mp3", 4, {"2": plan}), "graphic.mp4")
                    stock.assert_not_called()
                    self.assertEqual(main._rendered_assets["graphic.mp4"][0]["claim_ids"], ["verified"])
                self.assertEqual(scene, original)


if __name__ == "__main__":
    unittest_main()
