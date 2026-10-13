"""Final GPU work must be bound to the exact verified draft and saved scene."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import final


class RenderStarted(Exception):
    pass


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)/'approved'
        self.source.mkdir()
        self.output = Path(self.temp.name)/'final'
        (self.source/'reaction.blend').write_bytes(b'approved scene')
        (self.source/'reaction_draft.mp4').write_bytes(b'verified draft')
        (self.source/'manifest.json').write_text('{}')
        (self.source/'media_qa.json').write_text(json.dumps({
            'status':'PASS', 'all_frames_pixel_compared':True,
            'video_sha256':final.digest(self.source/'reaction_draft.mp4')}))
        (self.source/'draft_plan.json').write_text(json.dumps({
            'scene_sha256':final.digest(self.source/'reaction.blend')}))
        self.addCleanup(patch.stopall)
        self.run = patch.object(final,'run',side_effect=RenderStarted).start()

    def launch(self):
        try:
            final.main(self.source,self.output,'Approved both takes')
        except RenderStarted:
            pass

    def test_matching_evidence_reaches_renderer(self):
        self.launch()
        self.run.assert_called_once()

    def test_changed_scene_rejected_before_gpu_work(self):
        (self.source/'reaction.blend').write_bytes(b'unreviewed scene')
        with self.assertRaisesRegex(AssertionError,'Final differs from draft scene'):
            self.launch()
        self.run.assert_not_called()

    def test_changed_draft_rejected_before_gpu_work(self):
        (self.source/'reaction_draft.mp4').write_bytes(b'unverified draft')
        with self.assertRaisesRegex(AssertionError,'Draft changed after QA'):
            self.launch()
        self.run.assert_not_called()

    def test_changed_scene_on_resume_rejected(self):
        self.launch()
        self.run.reset_mock()
        (self.source/'reaction.blend').write_bytes(b'changed during pause')
        with self.assertRaisesRegex(AssertionError,'Changed render plan'):
            self.launch()
        self.run.assert_not_called()


if __name__=='__main__': unittest.main()
