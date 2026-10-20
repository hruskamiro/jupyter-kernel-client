"""Check built archives when JK_TEST_DIST_DIR points to a fresh build."""

import os
import tarfile
import unittest
import zipfile
from pathlib import Path

import jupyter_kernel_client


@unittest.skipUnless(os.environ.get("JK_TEST_DIST_DIR"), "requires built distributions")
class BundledSkillDistributionTests(unittest.TestCase):
    def test_skill_is_in_wheel_and_sdist(self):
        directory = Path(os.environ["JK_TEST_DIST_DIR"])
        wheels = list(directory.glob("*.whl"))
        sdists = list(directory.glob("*.tar.gz"))
        self.assertEqual(len(wheels), 1, "expected one wheel in the build directory")
        self.assertEqual(len(sdists), 1, "expected one sdist in the build directory")
        package = Path(jupyter_kernel_client.__file__).parent
        with zipfile.ZipFile(wheels[0]) as wheel, tarfile.open(sdists[0]) as sdist:
            for relative in (
                "resources/codex_skill/SKILL.md",
                "resources/codex_skill/agents/openai.yaml",
            ):
                with self.subTest(resource=relative):
                    expected = (package / relative).read_bytes()
                    self.assertTrue(expected)
                    self.assertEqual(wheel.read("jupyter_kernel_client/" + relative), expected)
                    members = [
                        member for member in sdist.getmembers()
                        if member.name.endswith("/src/jupyter_kernel_client/" + relative)
                    ]
                    self.assertEqual(len(members), 1)
                    with sdist.extractfile(members[0]) as resource:
                        self.assertEqual(resource.read(), expected)
