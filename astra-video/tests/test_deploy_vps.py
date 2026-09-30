"""Exercise deployment against disposable folders, never a live runner."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('deploy',Path(__file__).resolve().parents[1]/'deploy/deploy_vps.py')
deploy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_release_excludes_runtime_and_original_editor(self):
        for name in ['../runner.py','C:runner.py','data/key.py','config.json','original-editor/cover_caption.py','extension/../runner.py']:
            self.assertFalse(deploy.allowed(name),name)
        for name in ['runner.py','start.cmd','extension/worker.js']:
            self.assertTrue(deploy.allowed(name),name)

    @unittest.skipUnless(os.name=='nt','Windows file lock')
    def test_apply_preserves_runtime_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'vps';target.mkdir()
            (target/'config.json').write_text('private config')
            (target/'runner.py').write_text('# DEPLOYING\nold = True\n')
            (target/'data').mkdir();(target/'data/media.txt').write_text('keep media')
            archive=Path(temp)/'release.zip'
            with zipfile.ZipFile(archive,'w') as bundle: bundle.writestr('runner.py','# DEPLOYING\nnew = True\n')
            deploy.deploy(archive,target,'a'*40,0)
            self.assertIn('new = True',(target/'runner.py').read_text())
            self.assertEqual((target/'config.json').read_text(),'private config')
            self.assertEqual((target/'data/media.txt').read_text(),'keep media')
            self.assertFalse((target/'DEPLOYING').exists())
            self.assertEqual(len(list((target/'data/deployments').glob('*/runner.py'))),1)

    @unittest.skipUnless(os.name=='nt','Windows file lock')
    def test_unresolved_task_prevents_file_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'vps';target.mkdir()
            (target/'config.json').write_text('{}')
            original='# DEPLOYING\nold = True\n';(target/'runner.py').write_text(original)
            (target/'data').mkdir();(target/'data/active.json').write_text('{}')
            archive=Path(temp)/'release.zip'
            with zipfile.ZipFile(archive,'w') as bundle: bundle.writestr('runner.py','new = True\n')
            with self.assertRaisesRegex(RuntimeError,'Unresolved'):
                deploy.deploy(archive,target,'a'*40,0)
            self.assertEqual((target/'runner.py').read_text(),original)
            self.assertFalse((target/'DEPLOYING').exists())

    @unittest.skipUnless(os.name=='nt','Windows file lock')
    def test_copy_failure_rolls_back_code(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'vps';target.mkdir()
            (target/'config.json').write_text('{}')
            original='# DEPLOYING\nold = True\n';(target/'runner.py').write_text(original)
            archive=Path(temp)/'release.zip'
            with zipfile.ZipFile(archive,'w') as bundle:
                bundle.writestr('runner.py','new = True\n');bundle.writestr('second.py','ok = True\n')
            copy=deploy.shutil.copy2
            def fail_second(source,destination):
                if Path(destination)==target/'second.py':raise OSError('Simulated copy failure')
                return copy(source,destination)
            with patch.object(deploy.shutil,'copy2',side_effect=fail_second):
                with self.assertRaises(OSError):deploy.deploy(archive,target,'a'*40,0)
            self.assertEqual((target/'runner.py').read_text(),original)
            self.assertFalse((target/'DEPLOYING').exists())


if __name__=='__main__':unittest.main()
