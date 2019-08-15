# Makes a local cache of AWS elasticbeanstalk info.

import boto3.session
from report_eb_autoscaling_alarms import aws_cache

_eb_client = None


def init_client(profile_name, region_name):
    eb_session = boto3.session.Session(profile_name=profile_name, region_name=region_name)
    global _eb_client
    _eb_client = eb_session.client('elasticbeanstalk')


def cache_put_describe_environments():
    envs = _eb_client.describe_environments()
    aws_cache.cache_put('describe_environments', envs)
    for env in envs['Environments']:
        env_name = env['EnvironmentName']
        resources = _eb_client.describe_environment_resources(EnvironmentName=env_name)
        aws_cache.cache_put('describe_environment_resources-' + env_name, resources)

