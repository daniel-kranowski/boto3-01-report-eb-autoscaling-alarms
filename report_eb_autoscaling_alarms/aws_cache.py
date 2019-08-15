# The cache consists of files whose path is of the form "<cache_dir>/<key>.json".
# If the cache dir does not exist, we create it on the first put action.

import json
from pathlib import Path
from lib.json_datetime import DateTimeEncoder, DateTimeDecoder
from report_eb_autoscaling_alarms import util

cache_dir = './cache'


# Updates the cache on disk with the given value.
def cache_put(key, value):
    util.ensure_path_exists(cache_dir)
    cfile = Path('{}/{}.json'.format(cache_dir, key))
    if cfile.is_file():
        print('Updating existing cache entry for {}'.format(key))
    else:
        print('New cache entry for {}'.format(key))
    with cfile.open(mode='w', encoding='UTF-8') as f:
        json.dump(value, f, indent=4, sort_keys=True, cls=DateTimeEncoder)


def cache_get(key, verbose=True):
    cfile = Path('{}/{}.json'.format(cache_dir, key))
    if cfile.is_file():
        if verbose:
            print('Found cache entry for {}'.format(key))
        with cfile.open() as f:
            return json.load(f, cls=DateTimeDecoder)
    print('ERROR: object is not cached: {}'.format(key))
    return None


def has_key(key):
    cfile = Path('{}/{}.json'.format(cache_dir, key))
    return cfile.is_file()
