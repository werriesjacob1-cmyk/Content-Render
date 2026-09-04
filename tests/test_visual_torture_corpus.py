import unittest

import visual_director as VD
import visual_torture_corpus as VTC


class VisualTortureCorpusTests(unittest.TestCase):
    def test_canonical_corpus_is_structurally_valid(self):
        self.assertEqual(VTC.validate_corpus(), [])
        self.assertEqual(
            set(VTC.CANONICAL_VISUAL_TORTURE_CORPUS),
            {
                "stomach_lining",
                "neutron_star_spoon",
                "mauna_kea",
                "chess_possible_games",
                "mantis_shrimp",
            },
        )

    def test_generic_stock_is_never_a_preferred_route(self):
        for topic, scenes in VTC.CANONICAL_VISUAL_TORTURE_CORPUS.items():
            for scene in scenes:
                routes = VD.route_scene(scene)
                self.assertGreater(len(routes), 1, (topic, scene.scene_id))
                self.assertNotEqual(routes[0].visual_class, VD.VisualClass.GENERIC_STOCK)
                stock = [r for r in routes if r.visual_class == VD.VisualClass.GENERIC_STOCK]
                self.assertEqual(len(stock), 1, (topic, scene.scene_id))
                self.assertEqual(stock[0], routes[-1], (topic, scene.scene_id))

    def test_high_authenticity_topics_forbid_wallpaper_substitutions(self):
        for topic in ("stomach_lining", "neutron_star_spoon", "mauna_kea", "mantis_shrimp"):
            for scene in VTC.CANONICAL_VISUAL_TORTURE_CORPUS[topic]:
                if scene.authenticity_importance >= 8:
                    self.assertTrue(scene.forbidden_generic_substitutions, (topic, scene.scene_id))

    def test_mechanism_or_scale_scenes_get_programmatic_route(self):
        mechanism_ids = {
            "stomach_mechanism",
            "neutron_star_scale",
            "mauna_kea_cross_section",
            "chess_branching",
            "mantis_shrimp_mechanism",
        }
        found = set()
        for scenes in VTC.CANONICAL_VISUAL_TORTURE_CORPUS.values():
            for scene in scenes:
                if scene.scene_id not in mechanism_ids:
                    continue
                found.add(scene.scene_id)
                classes = {r.visual_class for r in VD.route_scene(scene)}
                self.assertIn(VD.VisualClass.PROGRAMMATIC_DIAGRAM, classes, scene.scene_id)
        self.assertEqual(found, mechanism_ids)

    def test_science_topics_prefer_evidence_before_generation(self):
        for topic in ("stomach_lining", "neutron_star_spoon", "mauna_kea", "mantis_shrimp"):
            for scene in VTC.CANONICAL_VISUAL_TORTURE_CORPUS[topic]:
                routes = VD.route_scene(scene)
                positions = {r.visual_class: i for i, r in enumerate(routes)}
                generated_positions = [
                    positions[c]
                    for c in (
                        VD.VisualClass.VERIFIED_GENERATED_STILL,
                        VD.VisualClass.IMAGE_TO_VIDEO,
                        VD.VisualClass.GENERATED_VIDEO,
                    )
                    if c in positions
                ]
                if not generated_positions:
                    continue
                evidence_positions = [
                    positions[c]
                    for c in (
                        VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO,
                        VD.VisualClass.SCIENTIFIC_VISUALIZATION,
                        VD.VisualClass.MOLECULAR_RENDER,
                        VD.VisualClass.PROGRAMMATIC_DIAGRAM,
                        VD.VisualClass.NORMAL_REAL_FOOTAGE,
                    )
                    if c in positions
                ]
                self.assertTrue(evidence_positions, (topic, scene.scene_id))
                self.assertLess(min(evidence_positions), min(generated_positions), (topic, scene.scene_id))

    def test_mauna_kea_anchor_disallows_generated_substitute(self):
        anchor = VTC.CANONICAL_VISUAL_TORTURE_CORPUS["mauna_kea"][0]
        classes = {r.visual_class for r in VD.route_scene(anchor)}
        self.assertNotIn(VD.VisualClass.GENERATED_VIDEO, classes)
        self.assertNotIn(VD.VisualClass.VERIFIED_GENERATED_STILL, classes)
        self.assertNotIn(VD.VisualClass.IMAGE_TO_VIDEO, classes)

    def test_mantis_shrimp_anchor_requires_real_subject(self):
        anchor = VTC.CANONICAL_VISUAL_TORTURE_CORPUS["mantis_shrimp"][0]
        classes = [r.visual_class for r in VD.route_scene(anchor)]
        self.assertEqual(classes[0], VD.VisualClass.AUTHENTIC_SCIENCE_VIDEO)
        self.assertNotIn(VD.VisualClass.GENERATED_VIDEO, classes)


if __name__ == "__main__":
    unittest.main()
