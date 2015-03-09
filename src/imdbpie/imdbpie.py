from __future__ import absolute_import, unicode_literals

import datetime
import hashlib
import json
import logging
import os
import random
import re
import time

import requests

# handle python 2 and python 3 imports
try:
    from urllib.parse import urlencode
    import html.parser as htmlparser
except ImportError:
    from urllib import urlencode
    import HTMLParser as htmlparser

logger = logging.getLogger(__name__)

BASE_URI = 'app.imdb.com'
API_KEY = '2wex6aeu6a8q9e49k7sfvufd6rhh0n'
SHA1_KEY = hashlib.sha1(API_KEY.encode('utf8')).hexdigest()
USER_AGENTS = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Mobile/9A405',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Mobile/9A406',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9A405 '
    'Safari/7534.48.3',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9A405 '
    'Safari/7534.48.3',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9A406 '
    'Safari/7534.48.3',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Mobile/9A334',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_0 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9A334 '
    'Safari/7534.48.3',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 5_1 like Mac OS X) '
    'AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9B179 '
    'Safari/7534.48.3',
    'Mozilla/5.0(iPhone; U; CPU iPhone OS 4_1 like Mac OS X; en-us)'
    'AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8B5097d '
    'Safari/6531.22.7',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0_2 like Mac OS X) '
    'AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12A366 '
    'Safari/600.1.4'
    'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0 like Mac OS X) AppleWebKit/600.1.4'
    ' (KHTML, like Gecko) Version/8.0 Mobile/12A366 Safari/600.1.4',
)


class Imdb(object):

    def __init__(self, options=None):
        self.locale = 'en_US'
        self.base_uri = BASE_URI
        self.timestamp = time.mktime(datetime.date.today().timetuple())
        self.user_agent = random.choice(USER_AGENTS)

        if options is None:
            options = {}

        self.options = options
        if options.get('anonymize') is True:
            self.base_uri = (
                'aniscartujo.com/webproxy/default.aspx?prx=https://{0}'
            ).format(self.base_uri)

        if options.get('exclude_episodes') is True:
            self.exclude_episodes = True
        else:
            self.exclude_episodes = False

        if options.get('locale'):
            self.locale = options['locale']

        self.caching_enabled = True if options.get('cache') is True else False
        self.cache_dir = options.get('cache_dir') or '/tmp/imdbpiecache'

    def build_url(self, path, params):
        default_params = {
            "api": "v1",
            "appid": "iphone1_1",
            "apiPolicy": "app1_1",
            "apiKey": SHA1_KEY,
            "locale": self.locale,
            "timestamp": self.timestamp
        }

        query_params = dict(
            list(default_params.items()) + list(params.items())
        )
        query_params = urlencode(query_params)
        url = 'https://{0}{1}?{2}'.format(self.base_uri, path, query_params)
        return url

    def find_movie_by_id(self, imdb_id, json=False):
        imdb_id = self.validate_id(imdb_id)
        url = self.build_url('/title/maindetails', {'tconst': imdb_id})
        result = self.get(url)
        if 'error' in result:
            return False
        # if the result is a re-dir, see imdb id tt0000021 for e.g...
        if (
            result["data"].get('tconst') !=
            result["data"].get('news').get('channel')
        ):
            return False

        # get the full cast information, add key if not present
        result["data"][str("credits")] = self.get_credits(imdb_id)
        result['data']['plots'] = self.get_plots(imdb_id)

        if (
            self.exclude_episodes is True and
            result["data"].get('type') == 'tv_episode'
        ):
            return False
        elif json is True:
            return result["data"]
        else:
            title = Title(**result["data"])
            return title

    # TODO: tests for get plots, pull in pull requests.
    # being refactoring improvements for release 2.x.x
    def get_plots(self, imdb_id):
        url = self.build_url('/title/plot', {'tconst': imdb_id})
        result = self.get(url)

        if result.get('error'):
            logger.warn('Failed to get plot for imdb_id: %s. Code: %s',
                        imdb_id, result.get('error').get('code'))
            return []

        if result['data']['tconst'] != imdb_id:
            return []

        plots = result['data'].get('plots', [])
        return [plot.get('text') for plot in plots]

    def get_credits(self, imdb_id):
        imdb_id = self.validate_id(imdb_id)
        url = self.build_url('/title/fullcredits', {'tconst': imdb_id})
        result = self.get(url)
        return result.get('data').get('credits')

    def filter_out(self, string):
        return string not in ('id', 'title')

    def movie_exists(self, imdb_id):
        """
        Check with imdb, does a movie exist
        """
        imdb_id = self.validate_id(imdb_id)
        if imdb_id:
            results = self.find_movie_by_id(imdb_id)
            return True if results else False
        return False

    def validate_id(self, imdb_id):
        """
        Check imdb id is a 7 digit number
        """
        match = re.findall(r'tt(\d+)', imdb_id, re.IGNORECASE)
        if match:
            id_num = match[0]
            if len(id_num) is not 7:
                # pad id to 7 digits
                id_num = id_num.zfill(7)
            return 'tt' + id_num
        else:
            return False

    def find_by_title(self, title):
        default_find_by_title_params = {
            'json': '1',
            'nr': 1,
            'tt': 'on',
            'q': title
        }
        query_params = urlencode(default_find_by_title_params)
        results = self.get(
            ('http://www.imdb.com/xml/find?{0}').format(query_params)
        )

        keys = (
            'title_popular',
            'title_exact',
            'title_approx',
            'title_substring'
        )
        title_results = []

        html_unescaped = htmlparser.HTMLParser().unescape

        # Loop through all results and build a list with popular matches first
        for key in keys:
            if key in results:
                for r in results[key]:
                    year = None
                    year_match = re.search(r'(\d{4})', r['title_description'])
                    if year_match:
                        year = year_match.group(0)

                    title_match = {
                        'title': html_unescaped(r['title']),
                        'year': year,
                        'imdb_id': r['id']
                    }
                    title_results.append(title_match)

        return title_results

    def top_250(self):
        url = self.build_url('/chart/top', {})
        result = self.get(url)
        return result["data"]["list"]["list"]

    def popular_shows(self):
        url = self.build_url('/chart/tv', {})
        result = self.get(url)
        return result["data"]["list"]

    def get_images(self, result):
        if 'error' in result:
            return False

        results = []
        if 'photos' in result.get('data'):
            for image in result.get('data').get('photos'):
                results.append(Image(**image))
        return results

    def title_images(self, imdb_id):
        url = self.build_url('/title/photos', {'tconst': imdb_id})
        result = self.get(url)
        return self.get_images(result)

    def title_reviews(self, imdb_id, limit=10):
        """
        Retrieves reviews for a title ordered by 'Best' descending
        """
        url = self.build_url(
            '/title/usercomments',
            {'tconst': imdb_id, 'limit': limit}
        )
        result = self.get(url)
        if 'error' in result:
            return None

        title_reviews = []
        user_comments = result.get('data').get('user_comments')

        if not user_comments:
            return None

        for review_data in result['data']['user_comments']:
            title_reviews.append(Review(review_data))
        return title_reviews

    def person_images(self, imdb_id):
        url = self.build_url('/name/photos', {'nconst': imdb_id})
        result = self.get(url)
        return self.get_images(result)

    def _get_cache_item_path(self, url):
        """
        Generates a cache location for a given api call.
        Returns a file path
        """
        cache_dir = self.cache_dir
        m = hashlib.md5()
        m.update(url.encode('utf-8'))
        cache_key = m.hexdigest()

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        return os.path.join(cache_dir, cache_key + '.cache')

    def _get_cached_response(self, file_path):
        """ Retrieves response from cache """
        if os.path.exists(file_path):
            logger.info('retrieving from cache: %s', file_path)

            with open(file_path, 'r+') as resp_data:
                cached_resp = json.load(resp_data)

            if cached_resp.get('exp') > self.timestamp:
                return cached_resp

            logger.info('cached expired, removing: %s', file_path)
            os.remove(file_path)
        return None

    @staticmethod
    def _cache_response(file_path, resp):
        with open(file_path, 'w+') as f:
            json.dump(resp, f)

    def get(self, url):
        if self.caching_enabled:
            cached_item_path = self._get_cache_item_path(url)
            cached_resp = self._get_cached_response(cached_item_path)
            if cached_resp:
                return cached_resp

        r = requests.get(url, headers={'User-Agent': self.user_agent})
        response = json.loads(r.content.decode('utf-8'))

        if self.caching_enabled:
            self._cache_response(cached_item_path, response)

        return response


class Person(object):

    def __init__(self, **person):
        p = person.get('name')
        # token and label are the persons categorisation
        # e.g token: writers label: Series writing credits
        self.token = person.get('token')
        self.label = person.get('label')

        # attr is a note about this persons work
        # e.g. (1990 - 1992 20 episodes)
        self.attr = person.get('attr')

        # other primary information about their part
        self.name = p.get('name')
        self.imdb_id = p.get('nconst')
        self.roles = (
            person.get('char').split('/') if person.get('char') else None
        )
        self.job = person.get('job')

    def __repr__(self):
        repr = '<Person: {0} ({1})>'
        return repr.format(self.name.encode('utf-8'), self.imdb_id)


class Title(object):

    def __init__(self, **kwargs):
        self.data = kwargs

        self.imdb_id = self.data.get('tconst')
        self.title = self.data.get('title')
        self.type = self.data.get('type')
        self.year = self._extract_year()
        self.tagline = self.data.get('tagline')
        self.plots = self.data.get('plots')
        self.runtime = self.data.get('runtime')
        self.rating = self.data.get('rating')
        self.genres = self.data.get('genres')
        self.votes = self.data.get('num_votes')
        self.runtime = self.data.get('runtime', {}).get('time')
        self.poster_url = self.data.get('image', {}).get('url')
        self.cover_url = self._extract_cover_url()
        self.release_date = self.data.get('release_date', {}).get('normal')
        self.certification = self.data.get('certificate', {}).get(
            'certificate')
        self.trailer_img_url = None
        self.trailer_image_urls = self._extract_trailer_image_urls()
        self.directors_summary = self._extract_directors_summary()
        self.creators = self._extract_creators()
        self.cast_summary = self._extract_cast_summary()
        self.writers_summary = self._extract_writers_summary()
        self.credits = self._extract_credits()
        self.trailers = self._extract_trailers()

    def _extract_directors_summary(self):
        return [Person(**p) for p in self.data.get('directors_summary', [])]

    def _extract_creators(self):
        return [Person(**p) for p in self.data.get('creators', [])]

    def _extract_trailers(self):
        def build_dict(val):
            return {'url': val['url'], 'format': val['format']}

        trailers = self.data.get('trailer', {}).get('encodings', {}).values()
        return [build_dict(trailer) for trailer in trailers]

    def _extract_writers_summary(self):
        return [Person(**p) for p in self.data.get('writers_summary', [])]

    def _extract_cast_summary(self):
        return [Person(**p) for p in self.data.get('cast_summary', [])]

    def _extract_credits(self):
        credits = []

        if not self.data.get('credits'):
            return []

        for credit_group in self.data['credits']:
            """
            Possible tokens: directors, cast, writers, producers and others
            """
            for person in credit_group['list']:
                person_extra = {
                    'token': credit_group.get('token'),
                    'label': credit_group.get('label'),
                    'job': person.get('job'),
                    'attr': person.get('attr')
                }
                person_data = dict(person_extra.items() + person.items())
                if 'name' in person_data.keys():
                    # some 'special' credits such as script
                    # rewrites have different formatting
                    # check for 'name' is a temporary fix for this,
                    # we lose a minimal amount of data from this
                    credits.append(Person(**person_data))
        return credits

    def _extract_year(self):
        year = self.data.get('year')
        # if there's no year the API returns ????...
        if not year or year == '????':
            return None
        return int(year)

    def _extract_cover_url(self):
        if self.poster_url is not None:
            return '{0}_SX214_.jpg'.format(self.poster_url.replace('.jpg', ''))

    def _extract_trailer_image_urls(self):
        slates = self.data.get('trailer', {}).get('slates', [])
        return [s['url'] for s in slates]


class Image(object):

    def __init__(self, **image):
        self.caption = image.get('caption')
        self.url = image.get('image').get('url')
        self.width = image.get('image').get('width')
        self.height = image.get('image').get('height')

    def __repr__(self):
        return '<Image: {0}>'.format(self.caption.encode('utf-8'))


class Review(object):

    def __init__(self, review):
        self.username = review.get('user_name')
        self.text = review.get('text')
        self.date = review.get('date')
        self.rating = review.get('user_rating')
        self.summary = review.get('summary')
        self.status = review.get('status')
        self.user_location = review.get('user_location')
        self.user_score = review.get('user_score')
        self.user_score_count = review.get('user_score_count')

    def __repr__(self):
        return '<Review: {0}>'.format(self.text[:20])
