"""An unsupported renderer must fail before canonical preparation begins."""
from pathlib import Path
import sys,unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from renderer_pin import APT_VERSION,PACKAGES,SOFFICE_VERSION,verify_packages,verify_renderer


class RendererPinChecks(unittest.TestCase):
    def test_only_the_exact_fixed_engine_is_accepted(self):
        for version in ('LibreOffice '+SOFFICE_VERSION+' 620(Build:2)',
                        'LibreOffice 24.2.7.2 420(Build:2)',
                        'LibreOffice '+SOFFICE_VERSION+'9 unknown',
                        'LibreOfficeDev '+SOFFICE_VERSION+' alpha'):
            with self.subTest(version=version),patch('renderer_pin.subprocess.check_output',return_value=version):
                if version.startswith('LibreOffice '+SOFFICE_VERSION+' '):self.assertEqual(verify_renderer(),version)
                else:
                    with self.assertRaisesRegex(ValueError,'requires pinned LibreOffice'):verify_renderer()

    def test_engine_and_uno_packages_must_share_the_exact_pin(self):
        with patch('renderer_pin.subprocess.check_output',return_value=APT_VERSION),patch('renderer_pin.subprocess.run')as command,patch('renderer_pin.verify_renderer',return_value=SOFFICE_VERSION):
            report=verify_packages();self.assertEqual(report['packages'],dict.fromkeys(PACKAGES,APT_VERSION))
            command.assert_called_once()
        def version(arguments,**kwargs):return '4:24.2.7'if arguments[-1]=='python3-uno'else APT_VERSION
        with patch('renderer_pin.subprocess.check_output',side_effect=version),patch('renderer_pin.subprocess.run')as command:
            with self.assertRaisesRegex(ValueError,'do not match the pin'):verify_packages()
            command.assert_not_called()


if __name__=='__main__':unittest.main()
