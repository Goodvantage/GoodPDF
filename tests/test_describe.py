from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from goodpdf.pipeline.describe import run_describe
from goodpdf.pipeline.jobs import JobRequest, PipelineStage, build_job_paths


class TestDescribe(unittest.TestCase):
    def test_run_describe_refreshes_existing_index_from_markdown_caption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "sample_doc"
            images = doc / "images"
            images.mkdir(parents=True)

            (doc / "sample_doc.md").write_text(
                "![](images/_page_7_Picture_0.jpeg)\n\n**Picture 2** : Fusarium wilt in west Africa\n",
                encoding="utf-8",
            )
            (images / "_page_7_Picture_0.jpeg").write_bytes(b"jpeg")
            (doc / "_page_7_Picture_0.triage").write_text("index\nold_reason\n", encoding="utf-8")
            (doc / "_page_7_Picture_0.desc").write_text("Old description\n", encoding="utf-8")

            summary = run_describe(root)

            self.assertEqual(summary.index, 1)
            self.assertEqual(summary.failed, 0)
            self.assertEqual(
                (doc / "_page_7_Picture_0.desc").read_text(encoding="utf-8").strip(),
                "Picture 2: Fusarium wilt in west Africa",
            )
            self.assertEqual(
                (doc / "_page_7_Picture_0.triage").read_text(encoding="utf-8"),
                "index\ncaption_from_markdown\n",
            )


class TestJobs(unittest.TestCase):
    def test_validate_resume_requires_cloud_to_start_at_describe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = JobRequest(
                language="en",
                use_cloud_descriptions=False,
                existing_marker_root=Path(temp_dir),
                start_stage=PipelineStage.DESCRIBE,
            )

            with self.assertRaisesRegex(ValueError, "Enable cloud image descriptions"):
                request.validate()

    def test_build_job_paths_resume_uses_existing_marker_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            marker_root = temp_path / "external marker"
            marker_root.mkdir()
            request = JobRequest(
                language="en",
                existing_marker_root=marker_root,
                start_stage=PipelineStage.CLEAN,
            )

            paths = build_job_paths(request, temp_path)

            self.assertEqual(paths.marker_dir, marker_root.resolve())
            self.assertIn("clean_resume", paths.job_id)
            self.assertTrue(str(paths.job_root).startswith(str((temp_path / "jobs").resolve())))


if __name__ == "__main__":
    unittest.main()
