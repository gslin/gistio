import os
import json
import urlparse

from redis import StrictRedis
from markdown2 import markdown
import requests
import bleach

from flask import Flask, render_template, make_response, abort, request
app = Flask(__name__)

HEROKU = 'HEROKU' in os.environ

GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID')
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET')

AUTH_PARAMS = {'client_id': GITHUB_CLIENT_ID,
               'client_secret': GITHUB_CLIENT_SECRET}


if HEROKU:
    urlparse.uses_netloc.append('redis')
    redis_url = urlparse.urlparse(os.environ['REDISTOGO_URL'])
    cache = StrictRedis(host=redis_url.hostname,
                        port=redis_url.port,
                        password=redis_url.password)
    PORT = int(os.environ.get('PORT', 5000))
    STATIC_URL = '//static.gist.io/'
else:
    cache = StrictRedis()  # local development
    PORT = 5000
    STATIC_URL = '/static/'

CACHE_EXPIRATION = 60  # seconds

RENDERABLE = (u'Markdown', u'Text', u'Literate CoffeeScript', None)

ALLOWED_TAGS = [
    "a", "abbr", "acronym", "b", "blockquote", "code", "em", "i", "li", "ol", "strong",
    "ul", "br", "img", "span", "div", "pre", "p", "dl", "dd", "dt", "tt", "cite", "h1",
    "h2", "h3", "h4", "h5", "h6", "table", "col", "tr", "td", "th", "tbody", "thead",
    "colgroup", "hr",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "acronym": ["title"],
    "abbr": ["title"],
    "img": ["src"],
}

@app.route('/oauth')
def oauth():
    app.logger.warning("Method: {}".format(request.method))
    app.logger.warning("Args: {}".format(request.args))
    return(u"oauth")

@app.route('/')
def homepage():
    return render_template('home.html', STATIC_URL=STATIC_URL)


@app.route('/<int:id>')
def render_gist(id):
    return render_template('gist.html', gist_id=id, STATIC_URL=STATIC_URL)


@app.route('/<int:id>/content')
def gist_contents(id):
    cache_hit = True
    content = cache.get(id)
    if not content:
        cache_hit = False
        content = fetch_and_render(id)
    if content is None:
        abort(404)
    resp = make_response(content, 200)
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['X-Cache-Hit'] = cache_hit
    resp.headers['X-Expire-TTL-Seconds'] = cache.ttl(id)
    return resp


def fetch_and_render(id):
    """Fetch and render a post from the Github API"""
    r = requests.get('https://api.github.com/gists/{}'.format(id),
                     params=AUTH_PARAMS)
    if r.status_code != 200:
        app.logger.warning('Fetch {} failed: {}'.format(id, r.status_code))
        return None

    try:
        decoded = r.json().copy()
    except ValueError:
        app.logger.error('Fetch {} failed: unable to decode JSON response'.format(id))
        return None

    for f in decoded['files'].values():
        if f['language'] in RENDERABLE:
            app.logger.debug('{}: renderable!'.format(f['filename']))
            payload = {
                'mode': 'gfm',
                'text': f['content'],
            }

            req_render = requests.post('https://api.github.com/markdown',
                                       params=AUTH_PARAMS,
                                       data=unicode(json.dumps(payload)))
            if req_render.status_code == 200:
                f['rendered'] = req_render.text
            else:
                app.logger.warn('Render {} file {} failed: {}'.format(id, f['filename'], req_render.status_code))
                continue
    encoded = json.dumps(decoded)
    cache.setex(id, CACHE_EXPIRATION, encoded)
    return encoded


if __name__ == '__main__':
    if HEROKU:
        app.run(host='0.0.0.0', port=PORT)
    else:
        cache.flushall()
        app.run(host='0.0.0.0', debug=True, port=PORT)
