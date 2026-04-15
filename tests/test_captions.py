from __future__ import annotations

import unittest

from goodpdf.pipeline.captions import extract_image_captions


class TestCaptions(unittest.TestCase):
    def test_extract_image_captions_cleans_marker_caption_text(self) -> None:
        markdown_text = (
            "Some intro text.\n\n"
            "![](images/_page_7_Picture_0.jpeg)\n\n"
            "**Picture 2** : Fusarium wilt in west Africa\n"
        )

        captions = extract_image_captions(markdown_text)

        self.assertEqual(
            captions,
            {"_page_7_Picture_0.jpeg": "Picture 2: Fusarium wilt in west Africa"},
        )

    def test_extract_image_captions_shares_caption_across_image_block(self) -> None:
        markdown_text = (
            "![](images/_page_7_Picture_0.jpeg)\n\n"
            "![](images/_page_7_Picture_1.jpeg)\n\n"
            "![](images/_page_7_Picture_2.jpeg)\n\n"
            "**Picture 2** : Fusarium wilt in west Africa\n"
        )

        captions = extract_image_captions(markdown_text)

        self.assertEqual(len(captions), 3)
        for name in (
            "_page_7_Picture_0.jpeg",
            "_page_7_Picture_1.jpeg",
            "_page_7_Picture_2.jpeg",
        ):
            self.assertEqual(captions[name], "Picture 2: Fusarium wilt in west Africa")

    def test_extract_image_captions_supports_extra_labels(self) -> None:
        markdown_text = "![](images/foo.jpeg)\n\n**Skema 4.** Alur kerja budidaya\n"

        captions = extract_image_captions(markdown_text, ["skema"])

        self.assertEqual(captions, {"foo.jpeg": "Skema 4. Alur kerja budidaya"})

    def test_extract_image_captions_stops_when_body_text_intervenes(self) -> None:
        markdown_text = (
            "![](images/foo.jpeg)\n\n"
            "This is body text, not a caption.\n\n"
            "**Figure 3** : Too far away\n"
        )

        captions = extract_image_captions(markdown_text)

        self.assertEqual(captions, {})


if __name__ == "__main__":
    unittest.main()
