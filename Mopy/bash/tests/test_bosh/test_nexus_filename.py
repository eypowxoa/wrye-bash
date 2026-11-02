from ...bosh import NexusFilename

class _ATestNexusFilename:
    _test_str: list[str]
    _expected_matches: list[tuple[str, int, str]]

    def test_init(self):
        for (test, expected) in zip(self._test_str, self._expected_matches):
            testing = NexusFilename.parse(test)
            if expected is None:
                assert testing is None
            else:
                assert expected[0] == testing.mod_name
                assert expected[1] == testing.mod_identifier
                assert expected[2] == testing.mod_version.raw_version

class TestNexusFilename_ASLAL(_ATestNexusFilename):
    """Tests that the regex works correctly with a basic package name (taken
    from ASLAL)."""
    _test_str = ['Alternate Start - Live Another Life-272-4-1-4-1608766947.7z']
    _expected_matches = [('Alternate Start - Live Another Life', 272, '4-1-4')]

class TestNexusFilename_MoreHud(_ATestNexusFilename):
    """Tests that the regex works correctly with the package name that
    necessitated the rewrite in the first place (moreHUD). The problem was that
    this one has four parts to its versions, the old regex could only handle
    1-3."""
    _test_str = ['moreHUD SE Light Master - AE-12688-5-1-1-0-1653588018.7z']
    _expected_matches = [('moreHUD SE Light Master - AE', 12688, '5-1-1-0')]

class TestNexusFilename_RaceMenu(_ATestNexusFilename):
    """Tests a broken case. The problem here is the usage of dashes after the
    'v0', which makes it ambigous as to whether that's a version number or the
    mod page ID."""
    _test_str = ['RaceMenu Anniversary Edition v0-4-19-11-19080-0-4-19-11-'
                 '1657140512.7z']
    _expected_matches = [('RaceMenu Anniversary Edition v0', 4,
                          '19-11-19080-0-4-19-11')]

class TestNexusFilename_RaceMenuFixed(_ATestNexusFilename):
    """Tests that the problem described above is indeed due to dashes.
    Replacing them with dots gives the right result."""
    _test_str = ['RaceMenu Anniversary Edition v0.4.19.11-19080-0-4-19-11-'
                 '1657140512.7z']
    _expected_matches = [('RaceMenu Anniversary Edition v0.4.19.11', 19080,
                          '0-4-19-11')]

class TestNexusFilename_NoMatch(_ATestNexusFilename):
    """Tests the package name of the Improved Camera preview release 2, a mod
    that isn't from the Nexus and hence shouldn't match."""
    _test_str = ['ImprovedCameraAE-PR2.7z']
    _expected_matches = [None]

class TestNexusFilename_FutureMod(_ATestNexusFilename):
    """Tests a hypothetical future mod release that has a mod ID with 8 digits
    and a download ID with 17 digits. The old regex could only handle up to 7
    digits for the mod ID and only up to 16 digits for the download ID."""
    _test_str = ['Cool Future Mod-25013821-2-0-1-0-380147987496669221.7z']
    _expected_matches = [('Cool Future Mod', 25013821, '2-0-1-0')]

class TestNexusFilename_NewFormat(_ATestNexusFilename):
    """Tests the download names Nexus uses since mid-2026: '{name} {modID}
    {version} {YYYY-MM-DDTHH-MMZ} {sqid}.7z'."""
    _test_str = ['Skyrim Script Extender (SKSE64) Steam 30379 2.3.1 '
                 '2026-08-27T16-52Z s6Og0dG94.7z']
    _expected_matches = [('Skyrim Script Extender (SKSE64) Steam', 30379,
                          '2.3.1')]

class TestNexusFilename_NewFormatSqidVersion(_ATestNexusFilename):
    """Tests a new format name whose sqid has the version appended - the old
    regex took the first number of the version for the mod ID."""
    _test_str = ['True Storms SE - No Fog Camera Effects 2472 1.0.3 '
                 '2026-07-05T12-39Z kATsMWuTj-1-0-3.rar']
    _expected_matches = [('True Storms SE - No Fog Camera Effects', 2472,
                          '1.0.3')]

class TestNexusFilename_NewFormatTextVersion(_ATestNexusFilename):
    """Tests a new format name with dashes and letters in its version."""
    _test_str = ['SKSE Menu Framework 120352 3.13-Hotfix2 2026-07-09T16-10Z '
                 '587RqTYjW-3-13-Hotfix2.7z']
    _expected_matches = [('SKSE Menu Framework', 120352, '3.13-Hotfix2')]

class TestNexusFilename_NewFormatNumberVersion(_ATestNexusFilename):
    """Tests a new format name with an all digits version - the mod ID is the
    number before the version, not the last one before the timestamp."""
    _test_str = ['Skyland AIO Complex Parallax 34179 2 2026-07-24T11-59Z '
                 'izKcFpJTq.zip']
    _expected_matches = [('Skyland AIO Complex Parallax', 34179, '2')]

class TestNexusFilename_NewFormatNumberInName(_ATestNexusFilename):
    """Tests a new format name with a number in the mod name."""
    _test_str = ['Skyrim 2020 Parallax by Pfuscher 31386 1.0 '
                 '2026-07-24T11-59Z izKcFpJTq.7z']
    _expected_matches = [('Skyrim 2020 Parallax by Pfuscher', 31386, '1.0')]

class TestNexusFilename_OldFormatNumberInName(_ATestNexusFilename):
    """Tests that a space before a number in an old format name does not
    separate the mod ID."""
    _test_str = ['Skyrim 2020 Parallax by Pfuscher-31386-1-0-1600000000.7z']
    _expected_matches = [('Skyrim 2020 Parallax by Pfuscher', 31386, '1-0')]

class TestNexusFilename_OldFormatWithoutTimestamp(_ATestNexusFilename):
    """Tests that an old format name without timestamp can be parsed.
    Example is the Skyrim Special Edition mod SkyHUD v090B v4 at 2026-11-02."""
    _test_str = ['SkyHUD v090B v4-463-0-90B.zip']
    _expected_matches = [('SkyHUD v090B v4', 463, '0-90B')]

class TestNexusFilename_VersionFormat(_ATestNexusFilename):
    """Tests that an old format version parsed correctly.
    Only fictional examples because it is hard to remember real examples:
    file-1.7z - no version or file id, so 1 is mod id.
    file-1-999.7z - not all files have id, so 1 is mod id, 999 is version.
    file-1-1000.7z - 1000 is too big for version, so 1 is mod id, 1000 is file id.
    file-1-2-999.7z - 999 is too small for file id, so 1 is mod id, 2-999 is version.
    file-1-2-1000.7z - full format, so 1 is mod id, 2 is version, 1000 is file id.
    file-1-2-a1000.7z - a1000 is not int, so 1 is mod id, 2-a1000 is version."""
    _test_str = ['file-1.7z', 'file-1-999.7z', 'file-1-1000.7z',
                 'file-1-2-999.7z', 'file-1-2-1000.7z', 'file-1-2-a1000.7z']
    _expected_matches = [('file', 1, ''), ('file', 1, '999'), ('file', 1, ''),
                         ('file', 1, '2-999'), ('file', 1, '2'),
                         ('file', 1, '2-a1000')]
