# -*- coding: utf-8 -*-
#
# GPL License and Copyright Notice ============================================
#  This file is part of Wrye Bash.
#
#  Wrye Bash is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  Wrye Bash is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Wrye Bash.  If not, see <https://www.gnu.org/licenses/>.
#
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2026 Wrye Bash Team
#  https://github.com/wrye-bash
#  Mopy/bash/games.py copyright (C) 2016 Utumno: Original design
#
# =============================================================================
#
# Everything in this file is based on Ganda's pynxm
# (https://github.com/GandaG/pynxm). See also Mopy/LICENSE-THIRD-PARTY.
# Modifications have been made to fit Wrye Bash's code style, refactor it to
# take advantage of Python 3 features, create a higher-level API and make
# third-party dependencies optional.
#
# Original copyright notice and disclaimer:
# =============================================================================
# Copyright 2019 Daniel Nunes
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================
"""A Python wrapper for the Nexus API. Based on pynxm.

For documentation on the API, see the following link:
https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0

Some terminology:
 - game domain: Nexus game ID (e.g. 'skyrim' for
                https://www.nexusmods.com/skyrim/mods/1840)
 - mod id: Nexus mod ID (e.g. '1840' for
           https://www.nexusmods.com/skyrim/mods/1840)
 - colour scheme: Refers to the different colours the site can have, depending
                  on what game you're modding. Note that we use the British
                  English spelling (colour) here for consistency with the API,
                  whereas all other parts of WB use the American English
                  spelling (color)"""
from __future__ import annotations

__author__ = 'Ganda, Infernio'

import enum
import json
import uuid
import webbrowser
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import floor
from threading import Lock, Thread
from time import sleep, time

from . import bass
from .bolt import FName, JsonParsable, Path, gen_enum_parser, json_remap, \
    json_serializable
from .bosh import Installer, NexusFilename, VersionNumber
from .exception import EndorsedTooSoonError, EndorsedWithoutDownloadError, \
    LimitReachedError, RequestError
from .web import ARestHandler, ReqLog

# First see if we even have the dependencies necessary to use the Nexus API
try:
    from websocket import create_connection
except ImportError as i_err:
    raise ImportError('websocket-client missing, nexus API '
                      'unavailable') from i_err

# Constants -------------------------------------------------------------------
_NEXUS_API_URL = 'https://api.nexusmods.com/v1/'

# Public API ------------------------------------------------------------------
class FileCategory(Enum):
    """The valid categories that files (referring to downloadable files, i.e.
    packages, on the Nexus) can have."""
    MAIN_FILES = 'main'
    UPDATES = 'update'
    OPTIONAL_FILES = 'optional'
    MISCELLANEOUS_FILES = 'miscellaneous'
    OLD_FILES = 'old_version'

class UpdatePeriod(Enum):
    """The valid periods for retrieving updated mods."""
    ONE_DAY = '1d'
    ONE_WEEK = '1w'
    ONE_MONTH = '1m'

    @staticmethod
    def calculate(at: int, now: int) -> UpdatePeriod | None:
        if UpdatePeriod.ONE_DAY.contains(at, now):
            return UpdatePeriod.ONE_DAY
        if UpdatePeriod.ONE_WEEK.contains(at, now):
            return UpdatePeriod.ONE_WEEK
        if UpdatePeriod.ONE_MONTH.contains(at, now):
            return UpdatePeriod.ONE_MONTH
        return None

    def contains(self, at: int, now: int) -> bool:
        return (now - self.period) < at

    @enum.property
    def period(self) -> int:
        match self:
            case self.ONE_DAY:
                return 23 * _h + 30 * _m
            case self.ONE_WEEK:
                return 6 * _d + 23 * _h + 30 * _m
            case _:
                return 29 * _d + 23 * _h + 30 * _m

class EndorsementStatus(Enum):
    """The valid states that a user's endorsement of a mod can have."""
    # The user has not yet chosen to endorse or abstain from endorsing the mod
    UNDECIDED = 'Undecided'
    # The user has endorsed the mod
    ENDORSED = 'Endorsed'
    # The user has abstained from endorsing the mod
    ABSTAINED = 'Abstained'

_es_parser = gen_enum_parser(EndorsementStatus)

@dataclass(slots=True)
class NxModUpdate(JsonParsable):
    """Represents a recent update to a mod."""
    # The ID of the mod that has been updated
    mod_id: int
    # The timestamp on which the last edit to a file from the mod was made
    latest_file_update: int
    # The timestamp on which the last edit to the mod's page was made
    latest_mod_activity: int

@dataclass(slots=True)
class NxUploadUser(JsonParsable):
    """Represents a user who uploaded a mod."""
    _parsers = {
        'user_name': json_remap('name'),
    }
    # The ID of the user who uploaded the mod
    member_id: int
    # The ID of the group the user belongs to
    member_group_id: int
    # The screen name of the user
    user_name: str

@dataclass(slots=True)
class NxModEndorsement(JsonParsable):
    """Represents a user's endorsement relative to a mod."""
    _parsers = {
        'endorse_status': lambda d, a: _es_parser[d[a]],
        'endorse_timestamp': json_remap('timestamp'),
        'endorse_version': json_remap('version'),
    }
    # The current endorsement status of this mod by the current user
    endorse_status: EndorsementStatus
    # The timestamp at which the mod was endorsed. None if endorse_status is
    # UNDECIDED
    endorse_timestamp: int | None
    ##: Seems to always be None, Pickysaurus said it may be unused
    endorse_version: str | None

@dataclass(slots=True)
class NxMod(JsonParsable):
    _parsers = {
        'mod_display_name': json_remap('name'),
        'mod_summary': json_remap('summary'),
        'mod_description': json_remap('description'),
        'mod_uid': json_remap('uid'),
        'nx_game_id': json_remap('game_id'),
        'mod_version': json_remap('version'),
        'created_by': json_remap('author'),
        'mod_status': json_remap('status'),
        'mod_available': json_remap('available'),
        'upload_user': lambda d, a: NxUploadUser.parse_single(d['user']),
        'endorsement': lambda d, a: NxModEndorsement.parse_single(d[a]),
    }
    # The user-visible name for this mod
    mod_display_name: str | None
    # A short description of this mod
    mod_summary: str | None
    # The full description of this mod, including markup (BBCode and/or HTML)
    mod_description: str | None = field(repr=False)
    # The URL to the main picture used for this mod
    picture_url: str | None
    # The number of times this mod has been downloaded
    mod_downloads: int | None
    # The number of times this mod has been downloaded, counting each user only
    # once
    mod_unique_downloads: int | None
    # A unique ID representing this mod
    mod_uid: int
    # The game-relatively unique ID of this mod
    mod_id: int
    # The internal ID of the game this mod was uploaded for
    nx_game_id: int
    # Whether or not to allow rating this mod
    allow_rating: bool
    # The Nexus domain name for the game this mod was uploaded for
    domain_name: str
    # The internal ID of the category in which this mod is filed
    category_id: int
    # The latest version of this mod
    mod_version: str
    # The number of times this mod has been endorsed
    endorsement_count: int
    # The timestamp on which this mod was created
    created_timestamp: int
    # Same as created_timestamp, but as a human-readable date
    created_time: str
    # The timestamp on which this mod was last updated
    updated_timestamp: int
    # Same as updated_timestamp, but as a human-readable date
    updated_time: str
    # The screen name of the user who authored this mod
    created_by: str
    # The screen name of the user who uploaded this mod
    uploaded_by: str
    # The URL of the Nexus profile of the user who uploaded this mod
    uploaded_users_profile_url: str
    # Whether or not this mod contains adult content
    contains_adult_content: bool
    # The current status of this mod. Usually 'published'
    mod_status: str
    # Whether or not this mod is currently available (i.e. its page can be
    # accessed, it can be downloaded, etc.)
    mod_available: bool
    # More detailed information about the user who uploaded this mod
    upload_user: NxUploadUser
    # Information about the endorsement of this mod by the current user
    endorsement: NxModEndorsement | None

@dataclass(slots=True)
class NxFile(JsonParsable):
    """Represents details about a file (aka a package, aka the actual things
    you download from the Nexus)."""
    _parsers = {
        'nx_file_ids': json_remap('id'),
        'nx_file_uid': json_remap('uid'),
        'nx_file_id': json_remap('file_id'),
        'file_display_name': json_remap('name'),
        'nx_file_version': json_remap('version'),
        'raw_size': json_remap('size'),
        'uploaded_file_name': json_remap('file_name'),
        'parent_mod_version': json_remap('mod_version'),
        'file_description': json_remap('description'),
        'file_md5': lambda d, a: d.get('md5'), # May be absent, see below
    }
    # A list of IDs that uniquely identify this file - seems to be file ID and
    # game ID
    nx_file_ids: list[int]
    # A unique ID representing this file
    nx_file_uid: int
    # A game-relatively unique ID for this file
    nx_file_id: int
    # The name of this file displayed in the Files tab
    file_display_name: str
    # The version of this file
    nx_file_version: str
    # The internal ID of the category that this file is in
    category_id: int
    # The name of the category that this file is in (e.g. 'MAIN')
    category_name: str
    # Whether or not this is the 'pimary' file, i.e. the one that will be
    # downloaded if you click the main 'Vortex' button on the mod page
    is_primary: bool
    # The size of this file, seems to be in kilobytes - probably better to use
    # size_kb or size_in_bytes (see below)
    raw_size: int
    # The name that this file originally had when its uploader uploaded it
    uploaded_file_name: str
    # The timestamp on which this file was uploaded
    uploaded_timestamp: int
    # Same as uploaded_timestamp, but as a human-readable date
    uploaded_time: str
    # The current version of the mod that this file belongs to
    parent_mod_version: str
    # A URL linking to a virus scan website's results for this file (currently
    # VirusTotal)
    external_virus_scan_url: str
    # The description shown for this file on the Files tab
    file_description: str
    # The size of this file in kilobytes
    size_kb: int
    # The size of this file in bytes
    size_in_bytes: int
    # The HTML that makes up the changelog entry for this file's version (shown
    # if you click on the version number next to the file's download counter).
    # May be None if the file's version has no changelog entry
    changelog_html: str | None
    # A link to a 'content preview' of the file. This is a JSON document
    # offering a tree view of the files and folders within an archive, along
    # with their sizes (it's what Nexus uses if you click on 'Preview file
    # contents' underneath the file's download button)
    content_preview_link: str
    # The MD5 hash of this file. Only present when this file is retrieved as
    # part of an MD5 search
    file_md5: str | None

@dataclass(slots=True)
class NxDownloadedFile(JsonParsable):
    """Represents a file that the user has downloaded."""
    _parsers = {
        'dl_mod': lambda d, a: NxMod.parse_single(d['mod']),
        'dl_file': lambda d, a: NxFile.parse_single(d['file_details']),
    }
    # The mod from which the file was downloaded
    dl_mod: NxMod
    # Details about the downloaded file
    dl_file: NxFile

@dataclass(slots=True)
class NxFileUpdate(JsonParsable):
    """Represents a single file update, i.e. a point at which a newer file has
    replaced/obsoleted an older file."""
    # File ID of the old file
    old_file_id: int
    # File ID of the new file
    new_file_id: int
    # Name of the old file (matches what the file would be named if you'd
    # downloaded it from the Nexus)
    old_file_name: str
    # Name of the new file (matches what the file would be named if you'd
    # downloaded it from the Nexus)
    new_file_name: str
    # Timestamp on which the new file was uploaded
    uploaded_timestamp: int
    # Same as uploaded_timestamp, but as a human-readable date
    uploaded_time: str

@dataclass(slots=True)
class NxModFiles(JsonParsable):
    """Represents files from a mod's Files tab."""
    _parsers = {
        'files_list': lambda d, a: NxFile.parse_many(d['files']),
        'file_updates': lambda d, a: NxFileUpdate.parse_many(d[a]),
    }
    # The files on this mod's Files tab (potentially subject to filters, e.g.
    # only the Main Files)
    files_list: list[NxFile]
    # Past updates to this mod's files, i.e. metadata on which newer files are
    # updates to which older files
    file_updates: list[NxFileUpdate]

@dataclass(slots=True)
class NxCategory(JsonParsable):
    """Represents a category that can be used for mods."""
    _parsers = {
        'category_name': json_remap('name'),
    }
    # The internal ID used for this category
    category_id: int
    # The user-facing name of this category
    category_name: str
    # The category ID of this category's parent. May be False, which indicates
    # that the category has no parent
    parent_category: int | bool

@dataclass(slots=True)
class NxGame(JsonParsable):
    """Represents a game on the Nexus."""
    _parsers = {
        'num_authors': json_remap('authors'),
        'game_categories': lambda d, a: NxCategory.parse_many(d['categories']),
        'num_downloads': json_remap('downloads'),
        'nx_game_id': json_remap('id'),
        'game_display_name': json_remap('name'),
        'num_mods': json_remap('mods'),
    }
    # The date on which this game was approved by Nexus
    approved_date: int
    # The number of mod authors for this game
    num_authors: int
    # The categories available for this game
    game_categories: list[NxCategory] = field(repr=False)
    # The Nexus domain name for this game (e.g. 'skyrim')
    domain_name: str
    # The total number of times users have downloaded mods for this game
    num_downloads: int
    # The number of files available for this game
    file_count: int
    # The total number of endorsements users have left on mods for this game
    file_endorsements: int
    # The total number of times users have viewed mods for this game
    file_views: int
    # The URL for the Nexus forums section for this game
    forum_url: str
    # The genre of this game
    genre: str
    # The internal ID used for this game
    nx_game_id: int
    # The number of mods published for this game
    num_mods: int
    # The user-facing name of this game
    game_display_name: str
    # The Nexus URL of this game
    nexusmods_url: str

@dataclass(slots=True)
class NxUser(JsonParsable):
    """Represents a Nexus user."""
    _parsers = {
        'user_api_key': json_remap('key'),
        'user_name': json_remap('name'),
        'user_email': json_remap('email'),
    }
    # The ID of the user
    user_id: int
    # The API key that is currently being used by the user
    user_api_key: str = field(repr=False)
    # The screen name of the user
    user_name: str
    # Whether or not the user currently has a premium subscription
    is_premium: bool
    # Whether or not the user is a 'Supporter', i.e. had a premium subscription
    # at some point in the past
    is_supporter: bool
    # The email address used by the user
    user_email: str
    # The URL to the user's profile *picture*
    profile_url: str

@dataclass(slots=True)
class NxTrackedMod(JsonParsable):
    """Represents a tracked mod on the Nexus."""
    # The game-relatively unique ID of the tracked mod
    mod_id: int
    # The Nexus domain name for this game (e.g. 'skyrim')
    domain_name: str

@dataclass(slots=True)
class NxEndorsement(JsonParsable):
    """Represents a user's endorsement of a mod."""
    _parsers = {
        'endorsement_date': json_remap('date'),
        'endorsement_version': json_remap('version'),
        'endorsement_status': json_remap('status'),
    }
    # The game-relatively unique ID of the endorsed mod
    mod_id: int
    # The Nexus domain name for this game (e.g. 'skyrim')
    domain_name: str
    # The date on which the mod was endorsed
    endorsement_date: str
    ##: Seems to always be None, Pickysaurus said it may be unused
    endorsement_version: str | None
    # Either 'Abstained' or 'Endorsed', indicating whether or not the
    # endorsement is still active
    endorsement_status: str

@dataclass(slots=True)
class NxColourScheme(JsonParsable):
    """Represents a Nexus colour scheme."""
    _parsers = {
        'colour_scheme_id': json_remap('id'),
        'colour_scheme_name': json_remap('name'),
    }
    # The internal ID used by the colour scheme
    colour_scheme_id: int
    # The name of the colour scheme
    colour_scheme_name: str
    # The primary colour used for the colour scheme
    primary_colour: str
    # The secondary colour used for the colour scheme
    secondary_colour: str
    # The 'darker' colour used for the colour scheme
    darker_colour: str

class NexusLimits:
    def __init__(self, daily_limit: int = 0, daily_remaining: int = 0,
        hourly_limit: int = 0, hourly_remaining: int = 0):
        self.daily_limit = daily_limit
        self.daily_remaining = daily_remaining
        self.hourly_limit = hourly_limit
        self.hourly_remaining = hourly_remaining

class Nexus(ARestHandler):
    """The main class used for connecting to the Nexus API. Requires an API key
    from your Nexus account."""
    _base_url = _NEXUS_API_URL
    # The total number of allowed requests in the current hour
    _hourly_limit: int | None
    # The total number of remaining allowed requests in the current hour
    _hourly_remaining: int | None
    # The point in time at which the hourly limit will be reset, as a string in
    # ISO 8601 format
    _hourly_reset: str | None
    # The total number of allowed requests in the current day
    _daily_limit: int | None
    # The total number of remaining allowed requests in the current day
    _daily_remaining: int | None
    # The point in time at which the daily limit will be reset, as a string in
    # ISO 8601 format
    _daily_reset: str | None

    def __init__(self, api_key: str, wait_between_requests: float = 0.0, *,
        on_limits: Callable[[NexusLimits], None] | None = None,
        logger: ReqLog | None = None):
        super().__init__(extra_headers={
            'accept': 'application/json',
            'apikey': api_key,
            # See the Nexus docs, they request these two always be present:
            # https://help.nexusmods.com/article/114-api-acceptable-use-policy
            'application-name': 'Wrye Bash',
            'application-version': bass.AppVersion,
        }, logger=self._log_request)
        # Rate limiting information - set to None (= unknown) by default
        self._hourly_limit = None
        self._hourly_remaining = None
        self._hourly_reset = None
        self._daily_limit = None
        self._daily_remaining = None
        self._daily_reset = None
        self._logger: ReqLog = logger or (lambda _: None)
        self._next_request_time = 0.0
        self._on_limits = on_limits or (lambda _: None)
        self._wait_between_requests = wait_between_requests

    # Abstract API ------------------------------------------------------------
    def _apply_rate_limit(self):
        now = time()
        remaining = self._next_request_time - now
        if remaining > 0.0 and self._wait_between_requests > 0.0:
            sleep(remaining)

    def _handle_error_response(self, response):
        if response.status_code == 429:
            raise LimitReachedError()
        try:
            msg = response.json()['message']
        except KeyError:
            msg = response.json()['error']
        raise RequestError(response.status_code, msg)

    def _update_rate_limit_info(self, response_headers):
        self._hourly_limit = int(response_headers['x-rl-hourly-limit'])
        self._hourly_remaining = int(response_headers['x-rl-hourly-remaining'])
        self._hourly_reset = response_headers['x-rl-hourly-reset']
        self._daily_limit = int(response_headers['x-rl-daily-limit'])
        self._daily_remaining = int(response_headers['x-rl-daily-remaining'])
        self._daily_reset = response_headers['x-rl-daily-reset']
        now = time()
        self._next_request_time = now + max(
            self._calculate_interval(
                now,
                self._hourly_limit,
                self._hourly_remaining,
                self._hourly_reset,
            ),
            self._calculate_interval(
                now,
                self._daily_limit,
                self._daily_remaining,
                self._daily_reset,
            ),
        )
        self._on_limits(NexusLimits(self._daily_limit, self._daily_remaining,
            self._hourly_limit, self._hourly_remaining))

    # Internal API ------------------------------------------------------------
    def _calculate_interval(
        self,
        now: float,
        limit: int,
        remaining: int,
        reset: str
    ) -> float:
        try:
            reset_date = datetime.strptime(reset, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            return self._wait_between_requests
        if limit <= 0:
            return self._wait_between_requests
        if remaining <= 0:
            return self._wait_between_requests
        timestamp = reset_date.timestamp()
        remaining_time = timestamp - now
        linear_interval = remaining_time / remaining
        progress = (limit - remaining) / limit
        coefficient = progress**2
        result_interval = linear_interval * coefficient
        return result_interval

    def _log_request(self, message: str) -> None:
        return self._logger(
            f'Nexus {message}'
            f' hourly {self._hourly_remaining}/{self._hourly_limit}'
            f' daily {self._daily_remaining}/{self._daily_limit}'
        )

    def _mod_endorse_shared(self, game_domain: str, mod_id: int,
            endpoint_file: str):
        """Shared code of mod_endorse and mod_disendorse."""
        try:
            self._send_post(f'games/{game_domain}/mods/{mod_id}/'
                            f'{endpoint_file}.json')
        except RequestError as e:
            if e.status_code == 403:
                if e.orig_msg == 'NOT_DOWNLOADED_MOD':
                    raise EndorsedWithoutDownloadError()
                elif e.orig_msg == 'TOO_SOON_AFTER_DOWNLOAD':
                    raise EndorsedTooSoonError()
            raise

    # Public API --------------------------------------------------------------
    @classmethod
    def sso(cls, app_slug: str, sso_token: str, sso_id: str | None = None):
        """Application login via Single Sign-On (SSO).

        :param app_slug: A string with the application slug.
        :param sso_token: A string with the connection token.
        :param sso_id: An optional string with an id used in previous
            connections.
        :return: A 'Nexus' instance, ready to be used."""
        ws = create_connection('wss://sso.nexusmods.com')
        if sso_id is None:
            sso_id = str(uuid.uuid4())
        ws.send(json.dumps({'id': sso_id, 'token': sso_token}))
        webbrowser.open(f'https://www.nexusmods.com/sso?id={sso_id}'
                        f'&application={app_slug}')
        api_key = ws.recv()
        return cls(api_key)

    # Mods - operations on multiple mods --------------------------------------
    def mods_updated(self, game_domain: str,
            period: UpdatePeriod) -> list[NxModUpdate]:
        """Returns a list of mods that have been updated in a given period,
        with timestamps of their last update.

        :param game_domain: A string with the Nexus game domain.
        :param period: The period for which to return updated mods."""
        return NxModUpdate.parse_many(self._send_get(
            f'games/{game_domain}/mods/updated.json',
            req_payload={'period': period.value}))

    def mods_latest_added(self, game_domain: str) -> list[NxMod]:
        """Retrieve the 10 latest added mods for a specified game.

        :param game_domain: A string with the Nexus game domain."""
        return NxMod.parse_many(self._send_get(
            f'games/{game_domain}/mods/latest_added.json'))

    def mods_latest_updated(self, game_domain: str) -> list[NxMod]:
        """Retrieve 10 latest updated mods for a specified game.

        :param game_domain: A string with the Nexus game domain."""
        return NxMod.parse_many(self._send_get(
            f'games/{game_domain}/mods/latest_updated.json'))

    def mods_trending(self, game_domain: str) -> list[NxMod]:
        """Retrieve 10 trending mods for a specified game.

        :param game_domain: A string with the Nexus game domain."""
        return NxMod.parse_many(self._send_get(
            f'games/{game_domain}/mods/trending.json'))

    # Mod - operations on a single mod ----------------------------------------
    def mod_changelogs(self, game_domain: str,
            mod_id: int) -> dict[str, list[str]]:
        """Returns a dict mapping versions to lists of strings. Each string
        represent a single entry in the changelog for that version.

        Example:
            A Nexus changelog like this:
                · 1.0.0
                    > Initial release
                · 1.0.1
                    > Fixed mod deleting C: drive
                    > Fixed mod overheating CPU when pressing Enter
            Would result in this output from mod_changelogs:
            {'1.0.0': ['Initial release'],
             '1.0.1': ['Fixed mod deleting C: drive',
                       'Fixed mod overheating CPU when pressing Enter']}

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        return self._send_get(
            f'games/{game_domain}/mods/{mod_id}/changelogs.json')

    def mod_details(self, game_domain: str, mod_id: int) -> NxMod:
        """Retrieve specified mod details, from a specified game.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        return NxMod.parse_single(self._send_get(
            f'games/{game_domain}/mods/{mod_id}.json'))

    def mod_search(self, game_domain: str,
            md5_hash: str) -> list[NxDownloadedFile]:
        """Searches for a mod given its md5 hash.

        :param game_domain: A string with the Nexus game domain.
        :param md5_hash: The mod's md5 hash - this is the hash of the package
           downloaded from the Nexus. Must be in hexadecimal form, so use
           hashlib.md5.hexdigest() or something similar."""
        # lower() because letters (A-F) must be lowercased, otherwise the Nexus
        # API will fail to find the mod in question
        return NxDownloadedFile.parse_many(self._send_get(
            f'games/{game_domain}/mods/md5_search/{md5_hash.lower()}.json'))

    def mod_endorse(self, game_domain: str, mod_id: int):
        """Endorse a mod. May fail if a mod is endorsed without having been
        downloaded, in which case an EndorsedWithoutDownloadError is raised, or
        if a mod is endorsed too quickly after having been downloaded, in which
        case an EndorsedTooSoonError is raised.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        self._mod_endorse_shared(game_domain, mod_id, 'endorse')

    def mod_disendorse(self, game_domain: str, mod_id: int):
        """'Abstain' from endorsing a mod - aka disendorse it. May fail with
        the same errors under the same conditions as mod_endorse.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        self._mod_endorse_shared(game_domain, mod_id, 'abstain')

    # Mod Files - operations on mod files (that's referring to the 'Files'
    # tab, so the files in the main, optional, etc. sections) -----------------
    def mod_files_list(self, game_domain: str, mod_id: int,
            categories: Iterable[FileCategory] | None = None) -> NxModFiles:
        """Lists all files for a specific mod.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id.
        :param categories: Filters returned files by one or more categories. If
            this is not None, return only files in one of the specified
            categories."""
        if categories is None:
            mf_payload = None
        else:
            mf_payload = {'category': ','.join(c.value for c in categories)}
        return NxModFiles.parse_single(self._send_get(
            f'games/{game_domain}/mods/{mod_id}/files.json',
            req_payload=mf_payload))

    def mod_files_details(self, game_domain: str, mod_id: int,
            file_id: int) -> NxFile:
        """Return details for a specified mod file, using a specified game.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id.
        :param file_id: A string with the file id."""
        return NxFile.parse_single(self._send_get(
            f'games/{game_domain}/mods/{mod_id}/files/{file_id}.json'))

    def mod_files_generate_link(self, game_domain: str, mod_id: int,
            file_id: int, nxm_key: str | None = None,
            expiry: str | None = None): # FIXME wrap
        """Generate a download link for a mod file.

        Note: Non-premium users must visit the website and provide the nxm key
        and expiry created by the website in order for this to work. Premium
        users do not need to provide them.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id.
        :param file_id: A string with the file id.
        :param nxm_key: A string with the nxm key provided by the website.
        :param expiry: A string with the expiry of the nxm key."""
        if None in (nxm_key, expiry):
            mfdl_payload = None
        else:
            mfdl_payload = {'key': nxm_key, 'expires': expiry}
        return self._send_get(
            f'games/{game_domain}/mods/{mod_id}/files/{file_id}/'
            f'download_link.json', req_payload=mfdl_payload)

    # Games - operations on multiple games ------------------------------------
    def games_list(self, include_unapproved=False) -> list[NxGame]:
        """Returns details for all games supported by the Nexus.

        :param include_unapproved: A boolean on whether to include unapproved
            games."""
        ia_string = 'true' if include_unapproved else 'false'
        return NxGame.parse_many(self._send_get('games.json',
            req_payload={'include_unapproved': ia_string}))

    # Game - operations on a single game --------------------------------------
    def game_details(self, game_domain: str) -> NxGame:
        """Returns details for the specified game.

        :param game_domain: A string with the Nexus game domain."""
        return NxGame.parse_single(self._send_get(f'games/{game_domain}.json'))

    # User - operations on the currently logged in user -----------------------
    def user_details(self) -> NxUser:
        """Checks that an API key is valid and returns the user's details."""
        return NxUser.parse_single(self._send_get('users/validate.json'))

    def user_tracked_mods(self) -> list[NxTrackedMod]:
        """Returns a list of all the mods being tracked by the current user."""
        return NxTrackedMod.parse_many(self._send_get(
            'user/tracked_mods.json'))

    def user_track_mod(self, game_domain: str, mod_id: int):
        """Tracks this mod with the current user.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        self._send_post('user/tracked_mods.json',
            req_payload={'domain_name': game_domain},
            req_data={'mod_id': str(mod_id)},
            req_headers={'content-type': 'application/x-www-form-urlencoded'})

    def user_untrack_mod(self, game_domain: str, mod_id: int):
        """Stop tracking this mod with the current user.

        :param game_domain: A string with the Nexus game domain.
        :param mod_id: A Nexus mod id."""
        self._send_delete('user/tracked_mods.json',
            req_payload={'domain_name': game_domain},
            req_data={'mod_id': str(mod_id)},
            req_headers={'content-type': 'application/x-www-form-urlencoded'})

    def user_endorsements(self) -> list[NxEndorsement]:
        """Returns a list of all endorsements for the current user."""
        return NxEndorsement.parse_many(self._send_get(
            'user/endorsements.json'))

    # Colour Schemes ----------------------------------------------------------
    def colour_schemes(self) -> list[NxColourScheme]:
        """Returns a list of all colour schemes, including the primary,
        secondary and 'darker' colours."""
        return NxColourScheme.parse_many(self._send_get('colourschemes.json'))

_s = 1
_m = 60 * _s
_h = 60 * _m
_d = 24 * _h
_checked_at = 'checked_at'
_updated_at = 'updated_at'
_latest_version = 'latest_version'

@dataclass(slots=True)
class _NexusUpdateInfo(JsonParsable):
    checked_at: int
    current_version: VersionNumber | None
    latest_version: VersionNumber | None
    updated_at: int

    _parsers = {
        'current_version': lambda d, k: VersionNumber(d[k]) if d[k] else None,
        'latest_version': lambda d, k: VersionNumber(d[k]) if d[k] else None,
    }

    def to_json(self) -> dict:
        return {
            'checked_at': self.checked_at,
            'current_version': self.current_version,
            'latest_version': self.latest_version,
            'updated_at': self.updated_at,
        }

class NexusUpdateChecker(Thread):
    def __init__(
        self,
        database_path: Path,
        game: str,
        logger: ReqLog,
        nexus: Nexus,
        on_error: Callable[[str], None],
        on_progress: Callable[[int, int], None],
        on_update: Callable[[set[int]], None],
    ):
        super().__init__(daemon=True)
        self._changed: bool = False
        database: dict[int, _NexusUpdateInfo] = dict()
        try:
            with open(database_path, 'rb') as database_file:
                json_data = json.loads(database_file.read().decode('utf8'))
                if not isinstance(json_data, dict):
                    raise BaseException(f'Not an object in {database_path}')
                for k, v in json_data.items():
                    database[int(k)] = _NexusUpdateInfo.parse_single(v)
        except FileNotFoundError:
            pass
        self._checked_at: int = 0
        self._database: dict[int, _NexusUpdateInfo] = database
        self._database_path: Path = database_path
        self._force_update: bool = False
        self._game: str = game
        self._logger: ReqLog = logger
        self._nexus: Nexus = nexus
        self._on_error: Callable[[str], None] = on_error
        self._on_progress: Callable[[int, int], None] = on_progress
        self._on_update: Callable[[set[int]], None] = on_update
        self._registered: set[int] = set()

    def _check_for_updates(self, now: int) -> None:
        updated: set[int] = set()
        if not bass.settings['bash.nexus.api_key']:
            self._checked_at = now
            return
        try:
            self._on_progress(1, 100)
            if self._force_update:
                self._force_update = False
                period = UpdatePeriod.calculate(self._checked_at, now)
                period = period or UpdatePeriod.ONE_MONTH
                self._update_database(self._checked_at, period)
            self._on_progress(10, 100)
            for mod in self._registered:
                if self._invalidate_mod(mod, now):
                    updated.add(mod)
            self._on_progress(20, 100)
            if updated:
                of: int = len(updated)
                for index, mod in enumerate(updated):
                    self._update_mod_version(mod, now)
                    self._on_progress(20 + floor(70 * (index / of)), 100)
        except BaseException as error:
            self._on_error(str(error))
            self._checked_at = now
            return
        finally:
            self._save_database_changes()
        self._on_progress(100, 100)
        self._logger(f'Mods updated: {len(updated)}')
        if updated:
            self._on_update(updated)
        self._checked_at = now

    def _invalidate_mod(self, mod_identifier: int, now: int) -> bool:
        try:
            item = self._database[mod_identifier]
        except KeyError:
            self._set_item(mod_identifier)
        else:
            if self._is_update_period_passed(item.checked_at, now):
                period = UpdatePeriod.calculate(item.checked_at, now)
                if period:
                    self._update_database(now, period)
                else:
                    self._set_item(mod_identifier, 0, 0, item.current_version)
        return self._database[mod_identifier].latest_version is None

    @staticmethod
    def _is_update_period_passed(last: int, now: int) -> bool:
        update_period = NexusUpdateChecker._update_period()
        valid_since = now - update_period
        return last < valid_since

    def _save_database_changes(self) -> None:
        if not self._changed:
            return
        self._changed = False
        temp_name = self._database_path.body + '.tmp.json'
        temp_path = self._database_path.head.join(temp_name)
        with open(temp_path, 'wb') as database:
            database.write(json.dumps(
                self._database,
                allow_nan=False,
                default=json_serializable,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf8"))
        temp_path.moveTo(self._database_path)

    def _set_item(self, mod_identifier: int, checked_at: int = 0,
        updated_at: int = 0, current_version: VersionNumber | None = None,
        latest_version: VersionNumber | None = None) -> None:
        self._changed = True
        self._database[mod_identifier] = _NexusUpdateInfo(checked_at,
            current_version, latest_version, updated_at)

    def _update_database(self, now: int, period: UpdatePeriod) -> None:
        data = self._nexus.mods_updated(self._game, period)
        for nexus_item in data:
            mod_identifier = nexus_item.mod_id
            updated_at = nexus_item.latest_file_update
            try:
                item = self._database[mod_identifier]
            except KeyError:
                self._set_item(mod_identifier, now, updated_at)
            else:
                mod_updated = item.updated_at == updated_at
                self._set_item(mod_identifier, now, updated_at,
                    item.current_version,
                    item.latest_version if mod_updated else None)
        for mod_identifier, item in self._database.items():
            checked_at = item.checked_at
            if period.contains(checked_at, now) and (checked_at < now):
                self._set_item(mod_identifier, now, item.updated_at,
                    item.current_version, item.latest_version)

    def _update_mod_version(self, mod_identifier: int, now: int) -> None:
        data = self._nexus.mod_details(self._game, mod_identifier)
        version = VersionNumber(data.mod_version)
        updated_at = data.updated_timestamp
        self._set_item(mod_identifier, now, updated_at, version, version)

    @staticmethod
    def _update_period() -> int:
        period_unit = 0
        match bass.settings['bash.nexus.update_period_unit']:
            case 'd':
                period_unit = _d
            case 'h':
                period_unit = _h
            case 'm':
                period_unit = _m
            case 's':
                period_unit = _s
        return int(bass.settings['bash.nexus.update_period']) * period_unit

    # Public API --------------------------------------------------------------

    def get_version(self, mod: int) -> VersionNumber:
        """
        Returns a mod version known at this moment.
        Also registers a mod for the update checking.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        if mod <= 0:
            return VersionNumber.EMPTY_VERSION
        self.register_mod(mod)
        try:
            item = self._database[mod]
        except KeyError:
            return VersionNumber.EMPTY_VERSION
        return item.current_version or VersionNumber.EMPTY_VERSION

    def register_mod(self, mod: int) -> None:
        """
        Register a mod for the update checking.
        Called automatically in other methods if not yet registered.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        self._registered.add(mod)

    def request_update(self) -> None:
        """
        Starts an update check for all registered mods.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        self._force_update = True

    # Thread Runner -----------------------------------------------------------

    def run(self):
        while True:
            sleep(0.1)
            now = int(time())
            at = self._checked_at
            if self._force_update or self._is_update_period_passed(at, now):
                self._check_for_updates(now)

type _SourceData = dict[FName, tuple[int, VersionNumber]]

class NexusUpdateStatus(Thread):
    def __init__(
        self,
        data: dict,
        on_updated: Callable[[set[FName]], None],
        updater: NexusUpdateChecker,
    ):
        super().__init__(daemon=True)
        self._data_store: dict = data
        self._is_updated_cache: dict[FName, bool] = dict()
        self._on_updated: Callable[[set[FName]], None] = on_updated
        self._requests: set[int] = set()
        self._requests_lock: Lock = Lock()
        self._updater: NexusUpdateChecker = updater
        self._version_cache: dict[FName, VersionNumber] = dict()
        for name, (mod, version) in self._get_data().items():
            latest_version = self._updater.get_version(mod)
            self._is_updated_cache[name] = version >= latest_version
            self._version_cache[name] = latest_version

    def _get_cached_version(self, name: FName) -> VersionNumber:
        return self._version_cache.get(name, VersionNumber.EMPTY_VERSION)

    def _get_data(self, only: set[int] | None = None) -> _SourceData:
        source: dict[FName, NexusFilename] = dict()
        for name, installer in self._data_store.items():
            info = installer.nexus_info
            if info and (only is None or info.mod_identifier in only):
                source[name] = info
        index: dict[int, VersionNumber] = dict()
        for info in source.values():
            empty_version = VersionNumber.EMPTY_VERSION
            old = index.setdefault(info.mod_identifier, empty_version)
            index[info.mod_identifier] = max(old, info.mod_version)
        return {name: (info.mod_identifier, index[info.mod_identifier])
            for (name, info) in source.items()}

    def _request_mod_update(self, name: FName) -> None:
        installer = self._data_store.get(name)
        mod = isinstance(installer, Installer) and installer.mod_identifier
        if mod:
            self.request_update({mod})

    # Public API --------------------------------------------------------------

    def get_version(self, name: FName) -> VersionNumber:
        """
        Get a version at this moment of a mod with specified name.
        Also starts a status update for a mod.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        self._request_mod_update(name)
        return self._get_cached_version(name)

    def is_updated(self, name: FName) -> bool:
        """
        Check if a mod with specified name is updated at this moment.
        Also starts a status update for a mod.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        self._request_mod_update(name)
        return self._is_updated_cache.get(name, True)

    def request_update(self, mods: set[int]) -> None:
        """
        Starts a status update for specified mods.
        Fast, thread-safe, can be called anywhere as many times as you want.
        """
        with self._requests_lock:
            self._requests.update(mods)

    # Thread Runner -----------------------------------------------------------

    def run(self):
        batch: set[int] = set()
        updated: set[FName] = set()
        while True:
            sleep(0.1)
            batch.clear()
            updated.clear()
            with self._requests_lock:
                batch.update(self._requests)
                self._requests.clear()
            if not batch:
                continue
            for name, (mod, version) in self._get_data(batch).items():
                changed = False
                old_version = self._get_cached_version(name)
                nexus_version = self._updater.get_version(mod)
                if nexus_version != old_version:
                    self._version_cache[name] = nexus_version
                    changed = True
                old_updated = self._is_updated_cache.get(name, True)
                is_updated = version >= nexus_version
                if is_updated != old_updated:
                    self._is_updated_cache[name] = is_updated
                    changed = True
                if changed:
                    updated.add(name)
            if updated:
                self._on_updated(updated)
