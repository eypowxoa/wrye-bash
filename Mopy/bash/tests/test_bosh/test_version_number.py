from ...bosh import VersionNumber

class TestVersionNumber:
    def test_empty_string(self):
        assert VersionNumber.EMPTY_VERSION == VersionNumber('')

    def test_version_number(self):
        expected = [VersionNumber(version) for version in [
            '', '0', '00', '01', '1', '2', '10', '20', '20.a', '20a', '.20',
            'a20', 'a.0.20', 'a.20', 'a.20.', 'a..20'
        ]]
        assert list(sorted(reversed(expected))) == expected
