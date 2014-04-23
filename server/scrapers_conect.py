# -*- coding: utf-8 -*-

# Copyright 2012 Facundo Batista
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://launchpad.net/encuentro

"""Some scrapers."""

import bs4

# we execute this script from inside the directory; pylint: disable=W0403
import helpers


def scrap_busqueda(html):    # FIXME: esta la seguimos usando?
    """Get useful info from the search."""
    soup = bs4.BeautifulSoup(helpers.sanitize(html))
    results = soup.find_all("div", "resBusqueda")
    processed = []
    for res in results:
        link = res.find('a')
        title = link.text.strip()
        dest_url = link.get('href')
        processed.append((title, dest_url))
    return processed


def scrap_series(html):
    """Get useful info from the series list."""
    soup = bs4.BeautifulSoup(helpers.sanitize(html))

    # new format
    episodes_list = soup.find('ul', id='listaEpisodios')
    if episodes_list is not None:
        results = []
        seasons = episodes_list.find_all('li', class_='temporada')
        for season in seasons:
            season_title_tag = season.find('a', class_='temporada-titulo')
            if season_title_tag is None:
                season_title = ''
            else:
                season_title = season_title_tag.text.strip() + u': '

            episodes = season.find_all('li')
            for episode in episodes:
                a_tag = episode.find('a')
                link = a_tag['href']
                title = a_tag.text.strip()

                # store it
                results.append((season_title + title, link))
        return results

    # support for the old way
    serietitle_section = soup.find("div", "titSerieEncabezado")
    serietitle_text = serietitle_section.h1.text
    epis_section = soup.find_all("ul", "serieCap")
    episodes = []
    for season in epis_section:
        episodes.extend(season.find_all('a'))
    processed = []
    for epis in episodes:
        title = epis.text.strip()
        dest_url = epis.get('href')
        processed.append((u"%s: %s" % (serietitle_text, title), dest_url))
    return processed


def scrap_video(html):
    """Get useful info from the video page."""
    soup = bs4.BeautifulSoup(helpers.sanitize(html))

    # new format
    item = soup.find('p', class_='duracion')
    if item is not None:
        parts = item.text.split()
        duration = int(parts[1])
        return duration

    # support for the old way
    it = soup.find('div', 'capitulo_thumb')
    duration = None
    while True:
        it = it.next_sibling
        if it is None:
            break

        if u"Duración" in unicode(it):
            p1, p2 = it.text.split(":")
            assert p1.strip() == u"Duración"
            duration = int(p2.split()[0])
    return duration
