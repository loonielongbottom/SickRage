# -*- coding: latin-1 -*-
# Author: adaur <adaur.underground@gmail.com>
# Rewritten from scraps of html by miigotu =P
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of SickRage.
#
# SickRage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickRage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickRage.  If not, see <http://www.gnu.org/licenses/>.

import re
import requests
import cookielib
from urllib import urlencode

from sickbeard import logger
from sickbeard import tvcache
from sickbeard.bs4_parser import BS4Parser
from sickrage.providers.torrent.TorrentProvider import TorrentProvider

from sickrage.helper.common import try_int


class XthorProvider(TorrentProvider):  # pylint: disable=too-many-instance-attributes

    def __init__(self):

        TorrentProvider.__init__(self, "Xthor")

        self.cj = cookielib.CookieJar()

        self.url = 'https://xthor.bz'
        self.urls = {
            'login': self.url + '/takelogin.php',
            'search': self.url + '/browse.php?'
        }

        self.ratio = None
        self.minseed = None
        self.minleech = None
        self.username = None
        self.password = None
        self.freeleech = None

        self.cache = XthorCache(self)

    def login(self):

        if any(requests.utils.dict_from_cookiejar(self.session.cookies).values()):
            return True

        login_params = {'username': self.username,
                        'password': self.password,
                        'submitme': 'X'}

        response = self.get_url(self.urls['login'], post_data=login_params, timeout=30)
        if not response:
            logger.log(u"Unable to connect to provider", logger.WARNING)
            return False

        if re.search('donate.php', response):
            return True
        else:
            logger.log(u"Invalid username or password. Check your settings", logger.WARNING)
            return False

    def search(self, search_strings, age=0, ep_obj=None):  # pylint: disable=too-many-locals, too-many-branches

        results = []
        items = {'Season': [], 'Episode': [], 'RSS': []}

        # check for auth
        if not self.login():
            return results

        """
            Séries / Pack TV 13
            Séries / TV FR 14
            Séries / HD FR 15
            Séries / TV VOSTFR 16
            Séries / HD VOSTFR 17
            Mangas (Anime) 32
            Sport 34
        """
        search_params = {
            'only_free': self.freeleech,
            'searchin': 'title',
            'incldead': 0,
            'type': 'desc',
            'cat': '13,14,15,16,17,32'  # Not sure if this works this way, try commenting this out
        }

        for mode in search_strings.keys():
            logger.log(u"Search Mode: %s" % mode, logger.DEBUG)

            # Sorting: 1: Name, 3: Comments, 5: Size, 6: Completed, 7: Seeders, 8: Leechers == 4: Time ?
            search_params['sort'] = (7, 4)[mode == 'RSS']
            for search_string in search_strings[mode]:
                if mode != 'RSS':
                    logger.log(u"Search string: %s " % search_string, logger.DEBUG)

                search_params['search'] = search_string
                searchURL = self.urls['search'] + urlencode(search_params)
                logger.log(u"Search URL: %s" % searchURL, logger.DEBUG)
                data = self.get_url(searchURL)
                if not data:
                    continue

                with BS4Parser(data, 'html5lib') as html:
                    torrent_table = html.find("table", class_="table2 table-bordered2")
                    torrent_rows = []
                    if torrent_table:
                        torrent_rows = torrent_table.find_all("tr")

                    # Continue only if at least one Release is found
                    if len(torrent_rows) < 2:
                        logger.log(u"Data returned from provider does not contain any torrents", logger.DEBUG)
                        continue

                    # Catégorie, Nom du Torrent, (Download), (Bookmark), Com., Taille, Complété, Seeders, Leechers
                    labels = [label.get_text(strip=True) for label in torrent_rows[0].find_all('td')]

                    for row in torrent_rows[1:]:
                        try:
                            cells = row.find_all('td')
                            # Skip anything that is not from a TV Series category
                            if not cells[labels.index(u'Catégorie')].get_text(strip=True).startswith('Séries /'):
                                continue

                            title = cells[labels.index(u'Nom du Torrent')].get_text(strip=True)
                            download_url = self.url + '/' + row.find("a", href=re.compile("download.php"))['href']

                            size = self._convertSize(cells[labels.index(u'Taille')].get_text(strip=True))
                            seeders = try_int(cells[labels.index(u'Seeders')].get_text(strip=True))
                            leechers = try_int(cells[labels.index(u'Leechers')].get_text(strip=True))

                        except (AttributeError, TypeError, KeyError, ValueError):
                            continue

                        if not all([title, download_url]):
                            continue

                        # Filter unseeded torrent
                        if seeders < self.minseed or leechers < self.minleech:
                            if mode != 'RSS':
                                logger.log(u"Discarding torrent because it doesn't meet the minimum seeders or leechers: {0} (S:{1} L:{2})".format(title, seeders, leechers), logger.DEBUG)
                            continue

                        item = title, download_url, size, seeders, leechers
                        if mode != 'RSS':
                            logger.log(u"Found result: %s " % title, logger.DEBUG)

                        items[mode].append(item)

            # For each search mode sort all the items by seeders if available if available
            items[mode].sort(key=lambda tup: tup[3], reverse=True)

            results += items[mode]

        return results

    def seed_ratio(self):
        return self.ratio

    @staticmethod
    def _convertSize(size):
        modifier = size[-2:].upper()
        size = size[:-2].strip()
        try:
            size = float(size)
            if modifier in 'KB':
                size = size * 1024 ** 1
            elif modifier in 'MB':
                size = size * 1024 ** 2
            elif modifier in 'GB':
                size = size * 1024 ** 3
            elif modifier in 'TB':
                size = size * 1024 ** 4
            else:
                raise
        except Exception:
            size = -1

        return long(size)


class XthorCache(tvcache.TVCache):
    def __init__(self, provider_obj):

        tvcache.TVCache.__init__(self, provider_obj)

        self.minTime = 30

    def _getRSSData(self):
        search_strings = {'RSS': ['']}
        return {'entries': self.provider.search(search_strings)}


provider = XthorProvider()
