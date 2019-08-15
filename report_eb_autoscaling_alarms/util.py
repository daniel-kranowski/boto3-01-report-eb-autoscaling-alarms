from datetime import datetime
import pytz
import os
import errno


def quote(arg):
    return '"{}"'.format(arg)


def ensure_tz(date):
    assert isinstance(date, datetime)
    if not date.tzinfo:
        return pytz.utc.localize(date)
    else:
        return date


def ensure_path_exists(path):
    if path:
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except OSError as exception:
                if exception.errno != errno.EEXIST:
                    raise


OUTPUT_DIR = './output'
